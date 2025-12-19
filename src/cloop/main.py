import json
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Dict, List, Literal, Optional, TypedDict

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, conlist, model_validator
from starlette.requests import Request

from . import db, web
from .llm import (
    ToolCallError,
    chat_completion,
    chat_with_tools,
    estimate_tokens,
    stream_completion,
)
from .loops import enrichment as loop_enrichment
from .loops import service as loop_service
from .loops.models import LoopStatus
from .rag import (
    _SQL_PY_METRIC,
    _VECLIKE_METRIC,
    _select_retrieval_order,
    ingest_paths,
    retrieve_similar_chunks,
)
from .settings import Settings, ToolMode, get_settings
from .tools import EXECUTORS, TOOL_SPECS


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_databases(get_settings())
    yield


app = FastAPI(title="Cloop LLM Service", version="0.1.0", lifespan=lifespan)
app.include_router(web.router)


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


class _InteractionMetadata(TypedDict):
    model: str
    latency_ms: float
    usage: dict[str, Any]


class ChatMessage(BaseModel):
    role: str
    content: str


class ToolCall(BaseModel):
    name: str = Field(..., description="Supported: read_note, write_note")
    note_id: Optional[int] = None
    title: Optional[str] = None
    body: Optional[str] = None


if TYPE_CHECKING:
    ChatMessageList = List[ChatMessage]
else:
    ChatMessageList = conlist(ChatMessage, min_length=1)


class ChatRequest(BaseModel):
    messages: ChatMessageList
    tool_call: Optional[ToolCall] = Field(
        default=None, description="Optional instruction to interact with notes"
    )
    tool_mode: Optional[ToolMode] = Field(
        default=None,
        description="Tool orchestration mode: manual, llm, or none. Defaults to settings.",
    )

    @model_validator(mode="after")
    def _manual_requires_tool(self) -> "ChatRequest":
        if self.tool_mode is ToolMode.MANUAL and self.tool_call is None:
            raise ValueError("tool_call required in manual mode")
        return self


class IngestMode(StrEnum):
    ADD = "add"
    REINDEX = "reindex"
    PURGE = "purge"
    SYNC = "sync"


class ChatResponse(BaseModel):
    message: str
    tool_result: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[str] = None


class IngestRequest(BaseModel):
    paths: List[str]
    mode: Optional[IngestMode] = Field(
        default=None,
        description="Ingestion mode: add, reindex, purge, or sync. Defaults to add.",
    )
    recursive: Optional[bool] = Field(
        default=None,
        description="Recurse into directories when true (default).",
    )


class IngestResponse(BaseModel):
    files: int
    chunks: int


class AskResponse(BaseModel):
    answer: str
    chunks: List[Dict[str, Any]]
    model: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class LoopCaptureRequest(BaseModel):
    raw_text: str = Field(..., min_length=1)
    captured_at: str = Field(..., description="Client ISO8601 timestamp (local or offset)")
    client_tz_offset_min: int = Field(..., description="Minutes offset from UTC at capture time")
    actionable: bool = False
    scheduled: bool = False
    blocked: bool = False


class LoopUpdateRequest(BaseModel):
    raw_text: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None, min_length=1)
    definition_of_done: str | None = Field(default=None, min_length=1)
    next_action: str | None = Field(default=None, min_length=1)
    due_at_utc: str | None = None
    snooze_until_utc: str | None = None
    time_minutes: int | None = Field(default=None, ge=1)
    activation_energy: int | None = Field(default=None, ge=0, le=3)
    urgency: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    project: str | None = Field(default=None, min_length=1)
    tags: List[str] | None = None


class LoopCloseRequest(BaseModel):
    status: LoopStatus = LoopStatus.COMPLETED
    note: str | None = None


class LoopStatusRequest(BaseModel):
    status: LoopStatus
    note: str | None = None


class LoopResponse(BaseModel):
    id: int
    raw_text: str
    title: str | None
    summary: str | None = None
    definition_of_done: str | None = None
    next_action: str | None = None
    status: LoopStatus
    captured_at_utc: str
    captured_tz_offset_min: int
    due_at_utc: str | None = None
    snooze_until_utc: str | None = None
    time_minutes: int | None = None
    activation_energy: int | None = None
    urgency: float | None = None
    importance: float | None = None
    project_id: int | None = None
    project: str | None = None
    tags: List[str] = Field(default_factory=list)
    user_locks: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    enrichment_state: str | None = None
    created_at_utc: str
    updated_at_utc: str
    closed_at_utc: str | None = None


class LoopNextResponse(BaseModel):
    due_soon: List[LoopResponse]
    quick_wins: List[LoopResponse]
    high_leverage: List[LoopResponse]


class HealthResponse(BaseModel):
    ok: bool
    model: str
    vector_mode: str
    vector_backend: str
    core_db: str
    rag_db: str
    schema_version: int
    embed_storage: str
    tool_mode_default: str
    retrieval_order: List[str]
    retrieval_metric: str


def _http_error(detail: Any, *, status_code: int, error_type: str) -> JSONResponse:
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or "Request failed"
        details = detail
    else:
        message = str(detail)
        details = {}
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": error_type, "message": message, "details": details}},
    )


@app.exception_handler(HTTPException)
def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    return _http_error(exc.detail, status_code=exc.status_code, error_type="http_error")


@app.exception_handler(RequestValidationError)
def handle_validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
    serialized_errors: List[Dict[str, Any]] = []
    for error in exc.errors():
        normalized = dict(error)
        ctx = normalized.get("ctx")
        if isinstance(ctx, dict):
            normalized["ctx"] = {
                key: (str(value) if isinstance(value, Exception) else value)
                for key, value in ctx.items()
            }
        serialized_errors.append(normalized)
    return _http_error(
        {"message": "Validation failed", "errors": serialized_errors},
        status_code=422,
        error_type="validation_error",
    )


@app.exception_handler(Exception)
def handle_generic_exception(_: Request, exc: Exception) -> JSONResponse:
    return _http_error(
        {"message": "Unexpected server error", "exception": exc.__class__.__name__},
        status_code=500,
        error_type="server_error",
    )


def handle_tool_call(tool_call: ToolCall) -> Dict[str, Any]:
    executor = EXECUTORS.get(tool_call.name)
    if executor is None:
        raise HTTPException(status_code=400, detail="Unsupported tool name")
    payload = tool_call.model_dump(exclude_none=True, exclude={"name"})
    try:
        return executor(**payload)
    except ValueError as exc:  # Surface validation issues as 4xx for manual mode
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail) from exc


def _sse_event(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _sanitize_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(chunk)
    sanitized.pop("embedding_blob", None)
    return sanitized


def _format_sources(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for chunk in chunks:
        sources.append(
            {
                "id": chunk.get("id"),
                "document_path": chunk.get("document_path"),
                "chunk_index": chunk.get("chunk_index"),
                "score": chunk.get("score"),
            }
        )
    return sources


def _interaction_context(settings: Settings) -> Dict[str, str]:
    backend = db.get_vector_backend()
    return {
        "embed_model": settings.embed_model,
        "vector_search_mode": settings.vector_search_mode.value,
        "embed_storage_mode": settings.embed_storage_mode.value,
        "vector_backend": backend.value,
    }


@app.get("/health", response_model=HealthResponse)
def health_endpoint(settings: SettingsDep) -> HealthResponse:
    backend = db.get_vector_backend()
    order = [
        path.value
        for path in _select_retrieval_order(backend=backend, scope=None, settings=settings)
    ]
    metric = (
        _VECLIKE_METRIC
        if backend in {db.VectorBackend.VEC, db.VectorBackend.VSS}
        else _SQL_PY_METRIC
    )
    return HealthResponse(
        ok=True,
        model=settings.llm_model,
        vector_mode=settings.vector_search_mode.value,
        vector_backend=backend.value,
        core_db=str(settings.core_db_path),
        rag_db=str(settings.rag_db_path),
        schema_version=db.SCHEMA_VERSION,
        embed_storage=settings.embed_storage_mode.value,
        tool_mode_default=settings.tool_mode_default.value,
        retrieval_order=order,
        retrieval_metric=metric,
    )


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    stream: Annotated[
        Optional[bool], Query(description="Stream Server-Sent Events when true")
    ] = None,
) -> Any:
    messages = [message.model_dump() for message in request.messages]
    tool_result: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = []

    tool_mode = request.tool_mode or settings.tool_mode_default

    if request.tool_call and tool_mode is not ToolMode.MANUAL:
        raise HTTPException(status_code=400, detail="tool_call is only supported in manual mode")

    if tool_mode is ToolMode.MANUAL:
        tool_call = request.tool_call
        if tool_call is None:
            raise HTTPException(status_code=422, detail="tool_call required in manual mode")
        tool_result = handle_tool_call(tool_call)
        messages.append(
            {
                "role": "system",
                "content": f"Tool output: {json.dumps(tool_result)}",
            }
        )

    token_estimate = estimate_tokens(messages)
    stream_enabled = stream if stream is not None else settings.stream_default
    if stream_enabled and tool_mode is ToolMode.LLM:
        raise HTTPException(status_code=400, detail="Streaming not supported for llm tool_mode")

    context_snapshot = _interaction_context(settings)

    if stream_enabled:
        request_payload = request.model_dump()
        request_payload["stream"] = True

        def event_stream() -> Iterator[str]:
            start = time.monotonic()
            tokens: List[str] = []
            for token in stream_completion(messages, settings=settings):
                if not token:
                    continue
                tokens.append(token)
                yield _sse_event("token", {"token": token})
            final_message = "".join(tokens)
            metadata: _InteractionMetadata = {
                "model": settings.llm_model,
                "latency_ms": (time.monotonic() - start) * 1000,
                "usage": {},
            }
            response_payload = {
                "message": final_message,
                "tool_result": tool_result,
                "metadata": metadata,
                "tool_calls": tool_calls,
                "context": context_snapshot,
            }
            db.record_interaction(
                endpoint="/chat",
                request_payload=request_payload,
                response_payload=response_payload,
                model=metadata["model"],
                latency_ms=metadata["latency_ms"],
                token_estimate=token_estimate,
                tool_calls=tool_calls,
                settings=settings,
            )
            yield _sse_event(
                "done",
                {
                    "message": final_message,
                    "model": metadata["model"],
                    "tool_result": tool_result,
                    "tool_calls": tool_calls,
                },
            )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if tool_mode is ToolMode.LLM:
        try:
            content, metadata, tool_calls = chat_with_tools(messages, TOOL_SPECS, settings=settings)
        except ToolCallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        outputs = metadata.get("tool_outputs") or []
        tool_result = outputs[0] if outputs else None
    else:
        content, metadata = chat_completion(messages, settings=settings)

    response_payload = {
        "message": content,
        "tool_result": tool_result,
        "metadata": metadata,
        "tool_calls": tool_calls,
        "context": context_snapshot,
    }
    db.record_interaction(
        endpoint="/chat",
        request_payload=request.model_dump(),
        response_payload=response_payload,
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        token_estimate=token_estimate,
        tool_calls=tool_calls,
        settings=settings,
    )

    return ChatResponse(
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        model=metadata.get("model"),
    )


@app.post("/ingest", response_model=IngestResponse)
def ingest_endpoint(
    request: IngestRequest,
    settings: SettingsDep,
) -> IngestResponse:
    if not request.paths:
        raise HTTPException(status_code=400, detail="paths cannot be empty")
    mode = (request.mode or IngestMode.ADD).value
    recursive = True if request.recursive is None else bool(request.recursive)
    try:
        result = ingest_paths(request.paths, mode=mode, recursive=recursive, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.record_interaction(
        endpoint="/ingest",
        request_payload=request.model_dump(),
        response_payload=result,
        model=settings.embed_model,
        latency_ms=None,
        token_estimate=None,
        tool_calls=[],
        settings=settings,
    )
    return IngestResponse(**result)


def _resolve_loop_status(request: LoopCaptureRequest) -> LoopStatus:
    if request.scheduled:
        return LoopStatus.SCHEDULED
    if request.blocked:
        return LoopStatus.BLOCKED
    if request.actionable:
        return LoopStatus.ACTIONABLE
    return LoopStatus.INBOX


@app.post("/loops/capture", response_model=LoopResponse)
def loop_capture_endpoint(
    request: LoopCaptureRequest,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
) -> LoopResponse:
    status = _resolve_loop_status(request)
    with db.core_connection(settings) as conn:
        try:
            record = loop_service.capture_loop(
                raw_text=request.raw_text,
                captured_at_iso=request.captured_at,
                client_tz_offset_min=request.client_tz_offset_min,
                status=status,
                conn=conn,
            )
            if settings.autopilot_enabled:
                record = loop_service.request_enrichment(loop_id=record["id"], conn=conn)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.autopilot_enabled:
        background_tasks.add_task(
            loop_enrichment.enrich_loop,
            loop_id=record["id"],
            settings=settings,
        )
    return LoopResponse(**record)


@app.get("/loops", response_model=List[LoopResponse])
def loop_list_endpoint(
    settings: SettingsDep,
    status: Annotated[
        LoopStatus | Literal["all", "open"] | None,
        Query(description="Filter by loop status, 'open', or 'all'"),
    ] = "open",
    tag: Annotated[str | None, Query(description="Filter by tag")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> List[LoopResponse]:
    tag_value = tag.strip().lower() if tag else None
    with db.core_connection(settings) as conn:
        if status == "open":
            statuses = [
                LoopStatus.INBOX,
                LoopStatus.ACTIONABLE,
                LoopStatus.BLOCKED,
                LoopStatus.SCHEDULED,
            ]
            if tag_value:
                loops = loop_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_service.list_loops_by_statuses(
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
        else:
            resolved_status = None if status is None or status == "all" else status
            if tag_value:
                statuses = [resolved_status] if resolved_status else None
                loops = loop_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_service.list_loops(
                    status=resolved_status, limit=limit, offset=offset, conn=conn
                )
    return [LoopResponse(**loop_item) for loop_item in loops]


@app.get("/loops/tags", response_model=List[str])
def loop_tags_endpoint(settings: SettingsDep) -> List[str]:
    with db.core_connection(settings) as conn:
        return loop_service.list_tags(conn=conn)


@app.get("/loops/{loop_id}", response_model=LoopResponse)
def loop_get_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        try:
            record = loop_service.get_loop(loop_id=loop_id, conn=conn)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return LoopResponse(**record)


@app.patch("/loops/{loop_id}", response_model=LoopResponse)
def loop_update_endpoint(
    loop_id: int,
    request: LoopUpdateRequest,
    settings: SettingsDep,
) -> LoopResponse:
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")
    with db.core_connection(settings) as conn:
        try:
            record = loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not_found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc
    return LoopResponse(**record)


@app.post("/loops/{loop_id}/close", response_model=LoopResponse)
def loop_close_endpoint(
    loop_id: int,
    request: LoopCloseRequest,
    settings: SettingsDep,
) -> LoopResponse:
    if request.status not in {LoopStatus.COMPLETED, LoopStatus.DROPPED}:
        raise HTTPException(status_code=400, detail="status must be completed or dropped")
    with db.core_connection(settings) as conn:
        try:
            record = loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not_found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc
    return LoopResponse(**record)


@app.post("/loops/{loop_id}/status", response_model=LoopResponse)
def loop_status_endpoint(
    loop_id: int,
    request: LoopStatusRequest,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        try:
            record = loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not_found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc
    return LoopResponse(**record)


@app.post("/loops/{loop_id}/enrich", response_model=LoopResponse)
def loop_enrich_endpoint(
    loop_id: int,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        try:
            record = loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not_found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc
    background_tasks.add_task(
        loop_enrichment.enrich_loop,
        loop_id=loop_id,
        settings=settings,
    )
    return LoopResponse(**record)


@app.get("/loops/next", response_model=LoopNextResponse)
def loop_next_endpoint(
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> LoopNextResponse:
    with db.core_connection(settings) as conn:
        payload = loop_service.next_loops(limit=limit, conn=conn)
    return LoopNextResponse(**payload)


@app.get("/ask", response_model=AskResponse)
def ask_endpoint(
    settings: SettingsDep,
    q: Annotated[str, Query(description="Question to run against the knowledge base")],
    k: Annotated[Optional[int], Query(description="Override number of chunks to return")] = None,
    stream: Annotated[
        Optional[bool], Query(description="Stream Server-Sent Events when true")
    ] = None,
    scope: Annotated[
        Optional[str],
        Query(description="Restrict retrieval by path substring or doc:ID"),
    ] = None,
) -> Any:
    top_k = k or settings.default_top_k
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="k must be positive")

    context_snapshot = _interaction_context(settings)
    try:
        chunks = retrieve_similar_chunks(q, top_k=top_k, scope=scope, settings=settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stream_enabled = stream if stream is not None else settings.stream_default
    if not chunks:
        if stream_enabled:

            def empty_stream() -> Iterator[str]:
                yield _sse_event(
                    "done",
                    {
                        "answer": "No knowledge available. Ingest documents first.",
                        "model": settings.llm_model,
                        "chunks": [],
                    },
                )

            return StreamingResponse(empty_stream(), media_type="text/event-stream")
        return AskResponse(answer="No knowledge available. Ingest documents first.", chunks=[])

    context = "\n\n".join(
        f"[{idx}] {chunk['content']}" for idx, chunk in enumerate(chunks, start=1)
    )
    messages = [
        {
            "role": "system",
            "content": "Use the provided context to answer. If unsure, say you do not know.",
        },
        {
            "role": "user",
            "content": f"Question: {q}\n\nContext:\n{context}",
        },
    ]
    token_estimate = estimate_tokens(messages)

    if stream_enabled:
        request_payload = {"q": q, "k": top_k, "stream": True}
        if scope:
            request_payload["scope"] = scope
        sanitized_chunks = [_sanitize_chunk(chunk) for chunk in chunks]
        sources = _format_sources(sanitized_chunks)

        def event_stream() -> Iterator[str]:
            start = time.monotonic()
            tokens: List[str] = []
            for token in stream_completion(messages, settings=settings):
                if not token:
                    continue
                tokens.append(token)
                yield _sse_event("token", {"token": token})
            final_answer = "".join(tokens)
            metadata: _InteractionMetadata = {
                "model": settings.llm_model,
                "latency_ms": (time.monotonic() - start) * 1000,
                "usage": {},
            }
            response_payload = {
                "answer": final_answer,
                "metadata": metadata,
                "sources": sources,
                "context": context_snapshot,
            }
            db.record_interaction(
                endpoint="/ask",
                request_payload=request_payload,
                response_payload=response_payload,
                model=metadata["model"],
                latency_ms=metadata["latency_ms"],
                token_estimate=token_estimate,
                selected_chunks=sanitized_chunks,
                tool_calls=[],
                settings=settings,
            )
            yield _sse_event(
                "done",
                {
                    "answer": final_answer,
                    "model": metadata["model"],
                    "chunks": sanitized_chunks,
                    "sources": sources,
                },
            )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    content, metadata = chat_completion(messages, settings=settings)
    sanitized_chunks = [_sanitize_chunk(chunk) for chunk in chunks]
    sources = _format_sources(sanitized_chunks)

    db.record_interaction(
        endpoint="/ask",
        request_payload={
            key: value
            for key, value in {"q": q, "k": top_k, "scope": scope}.items()
            if value is not None
        },
        response_payload={
            "answer": content,
            "sources": sources,
            "context": context_snapshot,
        },
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        token_estimate=token_estimate,
        selected_chunks=sanitized_chunks,
        tool_calls=[],
        settings=settings,
    )

    return AskResponse(
        answer=content,
        chunks=sanitized_chunks,
        model=metadata.get("model"),
        sources=sources,
    )
