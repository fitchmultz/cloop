"""RAG (Retrieval-Augmented Generation) endpoints.

Purpose:
    HTTP endpoints for document ingestion and question answering.

Responsibilities:
    - POST /ingest: Ingest documents into knowledge base
    - GET /ask: Ask questions against the knowledge base

Non-scope:
    - Document loading (see rag/loaders.py)
    - Search algorithms (see rag/search.py)

Endpoints:
- POST /ingest: Ingest documents into knowledge base
- GET /ask: Ask questions against the knowledge base
"""

import time
from collections.abc import Iterator
from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..llm import stream_completion
from ..loops.errors import CloopError
from ..rag import (
    NO_KNOWLEDGE_MESSAGE,
    answer_prepared_question,
    ingest_paths,
    prepare_ask_context,
)
from ..schemas.chat import _InteractionMetadata
from ..schemas.rag import AskResponse, IngestMode, IngestRequest, IngestResponse
from ..settings import Settings, get_settings
from ..sse import format_sse_event

router = APIRouter(tags=["rag"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


def _interaction_context(settings: Settings) -> Dict[str, str]:
    """Build interaction context for logging."""
    backend = db.get_vector_backend()
    return {
        "embed_model": settings.embed_model,
        "vector_search_mode": settings.vector_search_mode.value,
        "embed_storage_mode": settings.embed_storage_mode.value,
        "vector_backend": backend.value,
    }


@router.post("/ingest", response_model=IngestResponse)
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


@router.get("/ask", response_model=AskResponse)
def ask_endpoint(
    settings: SettingsDep,
    q: Annotated[str, Query(description="Question to run against the knowledge base")],
    k: Annotated[int | None, Query(description="Override number of chunks to return")] = None,
    stream: Annotated[bool | None, Query(description="Stream Server-Sent Events when true")] = None,
    scope: Annotated[
        str | None,
        Query(description="Restrict retrieval by path substring or doc:ID"),
    ] = None,
) -> Any:
    top_k = k or settings.default_top_k
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="k must be positive")

    context_snapshot = _interaction_context(settings)
    stream_enabled = stream if stream is not None else settings.stream_default
    try:
        prepared = prepare_ask_context(
            question=q,
            top_k=top_k,
            scope=scope,
            settings=settings,
        )
    except (RuntimeError, CloopError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not prepared.has_knowledge:
        if stream_enabled:

            def empty_stream() -> Iterator[str]:
                yield format_sse_event(
                    "done",
                    {
                        "answer": NO_KNOWLEDGE_MESSAGE,
                        "model": settings.llm_model,
                        "chunks": [],
                    },
                )

            return StreamingResponse(empty_stream(), media_type="text/event-stream")
        return AskResponse(answer=NO_KNOWLEDGE_MESSAGE, chunks=[])

    if stream_enabled:
        request_payload = {"q": q, "k": top_k, "stream": True}
        if scope:
            request_payload["scope"] = scope

        def event_stream() -> Iterator[str]:
            start = time.monotonic()
            tokens: List[str] = []
            for token in stream_completion(prepared.messages, settings=settings):
                if not token:
                    continue
                tokens.append(token)
                yield format_sse_event("token", {"token": token})
            final_answer = "".join(tokens)
            metadata: _InteractionMetadata = {
                "model": settings.llm_model,
                "latency_ms": (time.monotonic() - start) * 1000,
                "usage": {},
            }
            response_payload = {
                "answer": final_answer,
                "metadata": metadata,
                "sources": prepared.sources,
                "context": context_snapshot,
            }
            db.record_interaction(
                endpoint="/ask",
                request_payload=request_payload,
                response_payload=response_payload,
                model=metadata["model"],
                latency_ms=metadata["latency_ms"],
                token_estimate=prepared.token_estimate,
                selected_chunks=prepared.chunks,
                tool_calls=[],
                settings=settings,
            )
            yield format_sse_event(
                "done",
                {
                    "answer": final_answer,
                    "model": metadata["model"],
                    "chunks": prepared.chunks,
                    "sources": prepared.sources,
                },
            )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    answer = answer_prepared_question(prepared=prepared, settings=settings)

    db.record_interaction(
        endpoint="/ask",
        request_payload={
            key: value
            for key, value in {"q": q, "k": top_k, "scope": scope}.items()
            if value is not None
        },
        response_payload={
            "answer": answer.answer,
            "sources": answer.sources,
            "context": context_snapshot,
        },
        model=answer.model,
        latency_ms=answer.latency_ms,
        token_estimate=answer.token_estimate,
        selected_chunks=answer.chunks,
        tool_calls=[],
        settings=settings,
    )

    return AskResponse(
        answer=answer.answer,
        chunks=answer.chunks,
        model=answer.model,
        sources=answer.sources,
    )
