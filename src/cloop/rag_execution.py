"""Shared RAG execution orchestration.

Purpose:
    Centralize ingestion and question-answering execution so HTTP, CLI, MCP,
    and future transports can share one canonical retrieval contract for
    validation, streaming, response shaping, and interaction logging.

Responsibilities:
    - Execute shared document-ingest requests and persist interaction logs
    - Execute non-streaming RAG ask requests on top of ask orchestration
    - Stream transport-neutral RAG ask events for SSE-style callers
    - Build canonical response payloads for ask interactions
    - Keep retrieval interaction context consistent across transports

Non-scope:
    - HTTP/SSE response formatting
    - CLI argument parsing or text rendering
    - Document chunking, embedding generation, or vector search internals
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .db import get_vector_backend
from .llm import stream_events
from .rag import (
    NO_KNOWLEDGE_MESSAGE,
    answer_prepared_question,
    ingest_paths,
    prepare_ask_context,
)
from .rag.ask_orchestration import PreparedAskContext
from .schemas.rag import AskResponse, IngestResponse
from .settings import Settings
from .storage import interaction_store


@dataclass(slots=True, frozen=True)
class RagAskExecutionResult:
    """Completed non-streaming RAG ask result."""

    response: AskResponse
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    prepared: PreparedAskContext


@dataclass(slots=True, frozen=True)
class RagIngestExecutionResult:
    """Completed document-ingest execution result."""

    response: IngestResponse
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class StreamedRagAskEvent:
    """Transport-neutral streamed event for RAG ask flows."""

    type: str
    payload: dict[str, Any]


def interaction_context(settings: Settings) -> dict[str, str]:
    """Build stable retrieval interaction context for logging."""
    backend = get_vector_backend()
    return {
        "embed_model": settings.embed_model,
        "vector_search_mode": settings.vector_search_mode.value,
        "embed_storage_mode": settings.embed_storage_mode.value,
        "vector_backend": backend.value,
    }


def _ask_request_payload(
    *,
    question: str,
    top_k: int,
    scope: str | None,
    stream: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question, "top_k": top_k}
    if scope is not None:
        payload["scope"] = scope
    if stream:
        payload["stream"] = True
    return payload


def _ask_response_payload(
    *,
    answer: str,
    sources: list[dict[str, Any]],
    context: dict[str, str],
) -> dict[str, Any]:
    return {
        "answer": answer,
        "sources": sources,
        "context": context,
    }


def _record_ask_interaction(
    *,
    endpoint: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    prepared: PreparedAskContext,
    model: str | None,
    latency_ms: float | None,
    settings: Settings,
) -> None:
    interaction_store.record_interaction(
        endpoint=endpoint,
        request_payload=request_payload,
        response_payload=response_payload,
        model=model,
        latency_ms=latency_ms,
        token_estimate=prepared.token_estimate,
        selected_chunks=prepared.chunks,
        tool_calls=[],
        settings=settings,
    )


def _validate_top_k(top_k: int) -> None:
    if top_k <= 0:
        raise ValueError("top_k must be positive")


def execute_ask_request(
    *,
    question: str,
    top_k: int,
    scope: str | None,
    settings: Settings,
    endpoint: str = "/ask",
) -> RagAskExecutionResult:
    """Run the canonical non-streaming RAG ask flow with logging."""
    _validate_top_k(top_k)
    prepared = prepare_ask_context(
        question=question,
        top_k=top_k,
        scope=scope,
        settings=settings,
    )
    request_payload = _ask_request_payload(question=question, top_k=top_k, scope=scope)
    context_snapshot = interaction_context(settings)

    if not prepared.has_knowledge:
        response_payload = _ask_response_payload(
            answer=NO_KNOWLEDGE_MESSAGE,
            sources=[],
            context=context_snapshot,
        )
        _record_ask_interaction(
            endpoint=endpoint,
            request_payload=request_payload,
            response_payload=response_payload,
            prepared=prepared,
            model=None,
            latency_ms=None,
            settings=settings,
        )
        response = AskResponse(answer=NO_KNOWLEDGE_MESSAGE, chunks=[])
        return RagAskExecutionResult(
            response=response,
            request_payload=request_payload,
            response_payload=response_payload,
            prepared=prepared,
        )

    answer = answer_prepared_question(prepared=prepared, settings=settings)
    response_payload = _ask_response_payload(
        answer=answer.answer,
        sources=answer.sources,
        context=context_snapshot,
    )
    _record_ask_interaction(
        endpoint=endpoint,
        request_payload=request_payload,
        response_payload=response_payload,
        prepared=prepared,
        model=answer.model,
        latency_ms=answer.latency_ms,
        settings=settings,
    )
    response = AskResponse(
        answer=answer.answer,
        chunks=answer.chunks,
        model=answer.model,
        sources=answer.sources,
    )
    return RagAskExecutionResult(
        response=response,
        request_payload=request_payload,
        response_payload=response_payload,
        prepared=prepared,
    )


def stream_ask_request(
    *,
    question: str,
    top_k: int,
    scope: str | None,
    settings: Settings,
    endpoint: str = "/ask",
) -> Iterator[StreamedRagAskEvent]:
    """Run the canonical streaming RAG ask flow with transport-neutral events."""
    _validate_top_k(top_k)
    prepared = prepare_ask_context(
        question=question,
        top_k=top_k,
        scope=scope,
        settings=settings,
    )
    request_payload = _ask_request_payload(question=question, top_k=top_k, scope=scope, stream=True)
    context_snapshot = interaction_context(settings)

    if not prepared.has_knowledge:
        response_payload = _ask_response_payload(
            answer=NO_KNOWLEDGE_MESSAGE,
            sources=[],
            context=context_snapshot,
        )
        _record_ask_interaction(
            endpoint=endpoint,
            request_payload=request_payload,
            response_payload=response_payload,
            prepared=prepared,
            model=None,
            latency_ms=None,
            settings=settings,
        )
        yield StreamedRagAskEvent(
            type="done",
            payload=AskResponse(answer=NO_KNOWLEDGE_MESSAGE, chunks=[]).model_dump(mode="json"),
        )
        return

    tokens: list[str] = []
    model: str | None = settings.pi_model
    latency_ms: float | None = 0.0

    for event in stream_events(prepared.messages, settings=settings):
        event_type = event["type"]
        if event_type == "text_delta":
            token = str(event.get("delta", ""))
            if not token:
                continue
            tokens.append(token)
            yield StreamedRagAskEvent(type="text_delta", payload={"token": token})
        elif event_type == "done":
            model = str(event.get("model") or settings.pi_model)
            latency_ms = float(event.get("latency_ms", 0.0))

    final_answer = "".join(tokens)
    response_payload = _ask_response_payload(
        answer=final_answer,
        sources=prepared.sources,
        context=context_snapshot,
    )
    _record_ask_interaction(
        endpoint=endpoint,
        request_payload=request_payload,
        response_payload=response_payload,
        prepared=prepared,
        model=model,
        latency_ms=latency_ms,
        settings=settings,
    )
    yield StreamedRagAskEvent(
        type="done",
        payload=AskResponse(
            answer=final_answer,
            chunks=prepared.chunks,
            model=model,
            sources=prepared.sources,
        ).model_dump(mode="json"),
    )


def execute_ingest_request(
    *,
    paths: list[str],
    mode: str,
    recursive: bool,
    force_rehash: bool,
    settings: Settings,
    endpoint: str = "/ingest",
) -> RagIngestExecutionResult:
    """Run the canonical ingest flow with interaction logging."""
    if not paths:
        raise ValueError("paths cannot be empty")

    request_payload = {
        "paths": paths,
        "mode": mode,
        "recursive": recursive,
        "force_rehash": force_rehash,
    }
    result = ingest_paths(
        paths,
        mode=mode,
        recursive=recursive,
        force_rehash=force_rehash,
        settings=settings,
    )
    interaction_store.record_interaction(
        endpoint=endpoint,
        request_payload=request_payload,
        response_payload=result,
        model=settings.embed_model,
        latency_ms=None,
        token_estimate=None,
        tool_calls=[],
        settings=settings,
    )
    response = IngestResponse(**result)
    return RagIngestExecutionResult(
        response=response,
        request_payload=request_payload,
        response_payload=result,
    )
