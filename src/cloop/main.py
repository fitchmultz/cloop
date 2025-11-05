import json
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import Request

from . import db
from .llm import (
    ToolCallError,
    chat_completion,
    chat_with_tools,
    estimate_tokens,
    stream_completion,
)
from .rag import ingest_paths, retrieve_similar_chunks
from .settings import Settings, ToolMode, get_settings
from .tools import EXECUTORS, TOOL_SPECS


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_databases(get_settings())
    yield


app = FastAPI(title="Cloop LLM Service", version="0.1.0", lifespan=lifespan)


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


class ChatMessage(BaseModel):
    role: str
    content: str


class ToolCall(BaseModel):
    name: str = Field(..., description="Supported: read_note, write_note")
    note_id: Optional[int] = None
    title: Optional[str] = None
    body: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    tool_call: Optional[ToolCall] = Field(
        default=None, description="Optional instruction to interact with notes"
    )
    tool_mode: Optional[ToolMode] = Field(
        default=None,
        description="Tool orchestration mode: manual, llm, or none. Defaults to settings.",
    )


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
    return _http_error(
        {"message": "Validation failed", "errors": exc.errors()},
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


@app.get("/health", response_model=HealthResponse)
def health_endpoint(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        ok=True,
        model=settings.llm_model,
        vector_mode=settings.vector_search_mode.value,
        vector_backend=db.get_vector_backend().value,
        core_db=str(settings.core_db_path),
        rag_db=str(settings.rag_db_path),
        schema_version=db.SCHEMA_VERSION,
        embed_storage=settings.embed_storage_mode.value,
        tool_mode_default=settings.tool_mode_default.value,
    )


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    stream: Optional[bool] = Query(None, description="Stream Server-Sent Events when true"),
) -> Any:
    messages = [message.model_dump() for message in request.messages]
    tool_result: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = []

    tool_mode = request.tool_mode or settings.tool_mode_default

    if request.tool_call and tool_mode is not ToolMode.MANUAL:
        raise HTTPException(status_code=400, detail="tool_call is only supported in manual mode")

    if tool_mode is ToolMode.MANUAL:
        if request.tool_call is None:
            raise HTTPException(status_code=400, detail="tool_call required in manual mode")
        tool_result = handle_tool_call(request.tool_call)
        messages.append(
            {
                "role": "system",
                "content": f"Tool output: {json.dumps(tool_result)}",
            }
        )

    if not messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    token_estimate = estimate_tokens(messages)
    stream_enabled = stream if stream is not None else settings.stream_default
    if stream_enabled and tool_mode is ToolMode.LLM:
        raise HTTPException(status_code=400, detail="Streaming not supported for llm tool_mode")

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
            metadata = {
                "model": settings.llm_model,
                "latency_ms": (time.monotonic() - start) * 1000,
                "usage": {},
            }
            response_payload = {
                "message": final_message,
                "tool_result": tool_result,
                "metadata": metadata,
                "tool_calls": tool_calls,
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


@app.get("/ask", response_model=AskResponse)
def ask_endpoint(
    settings: SettingsDep,
    q: str = Query(..., description="Question to run against the knowledge base"),
    k: Optional[int] = Query(None, description="Override number of chunks to return"),
    stream: Optional[bool] = Query(None, description="Stream Server-Sent Events when true"),
    scope: Optional[str] = Query(
        None,
        description="Restrict retrieval by path substring or doc:ID",
    ),
) -> Any:
    top_k = k or settings.default_top_k
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="k must be positive")

    chunks = retrieve_similar_chunks(q, top_k=top_k, scope=scope, settings=settings)
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
            metadata = {
                "model": settings.llm_model,
                "latency_ms": (time.monotonic() - start) * 1000,
                "usage": {},
            }
            response_payload = {
                "answer": final_answer,
                "metadata": metadata,
                "sources": sources,
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
        response_payload={"answer": content, "sources": sources},
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
