"""RAG (Retrieval-Augmented Generation) endpoints.

Endpoints:
- POST /ingest: Ingest documents into knowledge base
- GET /ask: Ask questions against the knowledge base
"""

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..llm import chat_completion, estimate_tokens, stream_completion
from ..loops.errors import CloopError
from ..rag import (
    ingest_paths,
    retrieve_similar_chunks,
)
from ..schemas.chat import _InteractionMetadata
from ..schemas.rag import AskResponse, IngestMode, IngestRequest, IngestResponse
from ..settings import Settings, get_settings

router = APIRouter(tags=["rag"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


def _sse_event(event: str, payload: Dict[str, Any]) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _sanitize_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Remove embedding blob from chunk for API response."""
    sanitized = dict(chunk)
    sanitized.pop("embedding_blob", None)
    return sanitized


def _format_sources(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format chunks as source references."""
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
    try:
        chunks = retrieve_similar_chunks(q, top_k=top_k, scope=scope, settings=settings)
    except (RuntimeError, CloopError) as exc:
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
