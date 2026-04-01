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

from .continuity_reruns import build_recall_query_rerun_action
from .db import get_vector_backend
from .llm import stream_events
from .rag import (
    NO_KNOWLEDGE_MESSAGE,
    answer_prepared_question,
    ingest_paths,
    prepare_ask_context,
)
from .rag.ask_orchestration import PreparedAskContext
from .recall_follow_through import build_ingest_follow_through, build_rag_follow_through
from .recall_working_sets import resolve_recall_working_set
from .schemas.rag import AskResponse, IngestResponse
from .settings import PiToolBudgetSurface, Settings
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
    working_set_id: int | None,
    stream: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question, "top_k": top_k}
    if scope is not None:
        payload["scope"] = scope
    if working_set_id is not None:
        payload["working_set_id"] = working_set_id
    if stream:
        payload["stream"] = True
    return payload


def _ask_rerun_action(
    *,
    question: str,
    sources: list[dict[str, Any]],
    working_set_id: int | None,
):
    source_count = len(sources)
    return build_recall_query_rerun_action(
        recall_tool="rag",
        query=question,
        label="Refresh evidence",
        description="Land back in Recall with a fresh evidence-backed result.",
        provenance_label="Document-backed recall result",
        freshness_label=(
            f"{source_count} retrieved source{'s' if source_count != 1 else ''} in the prior answer"
            if source_count > 0
            else "Document-backed recall result"
        ),
        strategy_summary="Reuse the same document question against the current indexed evidence.",
        strict_invariants=[
            "Same document recall surface",
            "Same query text",
            "Same recall landing surface after the rerun",
        ],
        may_vary=[
            "Retrieved source set or chunk ranking",
            "Answer wording and evidence emphasis",
            "Generation strategy path or alternate selector choice",
        ],
        include_rag_context=True,
        working_set_id=working_set_id,
    )


def _ask_follow_through(
    *,
    answer: str,
    question: str,
    sources: list[dict[str, Any]],
    working_set: dict[str, Any] | None,
):
    if answer == NO_KNOWLEDGE_MESSAGE:
        return None
    working_set_id = (
        int(working_set["working_set_id"])
        if isinstance(working_set, dict) and isinstance(working_set.get("working_set_id"), int)
        else None
    )
    return build_rag_follow_through(
        question=question,
        answer=answer,
        sources=sources,
        rerun_action=_ask_rerun_action(
            question=question,
            sources=sources,
            working_set_id=working_set_id,
        ),
        working_set=working_set,
    )


def _ask_response_payload(
    *,
    answer: str,
    question: str,
    sources: list[dict[str, Any]],
    context: dict[str, str],
    working_set: dict[str, Any] | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    working_set_id = (
        int(working_set["working_set_id"])
        if isinstance(working_set, dict) and isinstance(working_set.get("working_set_id"), int)
        else None
    )
    rerun_action = _ask_rerun_action(
        question=question,
        sources=sources,
        working_set_id=working_set_id,
    )
    follow_through = _ask_follow_through(
        answer=answer,
        question=question,
        sources=sources,
        working_set=working_set,
    )
    payload = {
        "answer": answer,
        "sources": sources,
        "context": context,
        "rerun_action": rerun_action.model_dump(mode="python"),
        "follow_through": follow_through.model_dump(mode="python")
        if follow_through is not None
        else None,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


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
        tool_results=[],
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
    working_set_id: int | None,
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
    working_set = resolve_recall_working_set(working_set_id=working_set_id, settings=settings)
    request_payload = _ask_request_payload(
        question=question,
        top_k=top_k,
        scope=scope,
        working_set_id=working_set_id,
    )
    context_snapshot = interaction_context(settings)

    if not prepared.has_knowledge:
        response_payload = _ask_response_payload(
            answer=NO_KNOWLEDGE_MESSAGE,
            question=question,
            sources=[],
            context=context_snapshot,
            working_set=working_set,
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
        response = AskResponse(
            answer=NO_KNOWLEDGE_MESSAGE,
            chunks=[],
            metadata={},
            rerun_action=_ask_rerun_action(
                question=question,
                sources=[],
                working_set_id=working_set_id,
            ),
            follow_through=None,
        )
        return RagAskExecutionResult(
            response=response,
            request_payload=request_payload,
            response_payload=response_payload,
            prepared=prepared,
        )

    answer = answer_prepared_question(prepared=prepared, settings=settings)
    response_payload = _ask_response_payload(
        answer=answer.answer,
        question=question,
        sources=answer.sources,
        context=context_snapshot,
        working_set=working_set,
        metadata=answer.metadata,
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
        metadata=answer.metadata,
        rerun_action=_ask_rerun_action(
            question=question,
            sources=answer.sources,
            working_set_id=working_set_id,
        ),
        follow_through=_ask_follow_through(
            answer=answer.answer,
            question=question,
            sources=answer.sources,
            working_set=working_set,
        ),
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
    working_set_id: int | None,
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
    working_set = resolve_recall_working_set(working_set_id=working_set_id, settings=settings)
    request_payload = _ask_request_payload(
        question=question,
        top_k=top_k,
        scope=scope,
        working_set_id=working_set_id,
        stream=True,
    )
    context_snapshot = interaction_context(settings)

    if not prepared.has_knowledge:
        response_payload = _ask_response_payload(
            answer=NO_KNOWLEDGE_MESSAGE,
            question=question,
            sources=[],
            context=context_snapshot,
            working_set=working_set,
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
            payload=AskResponse(
                answer=NO_KNOWLEDGE_MESSAGE,
                chunks=[],
                metadata={},
                rerun_action=_ask_rerun_action(
                    question=question,
                    sources=[],
                    working_set_id=working_set_id,
                ),
                follow_through=None,
            ).model_dump(mode="json"),
        )
        return

    tokens: list[str] = []
    metadata: dict[str, Any] = {
        "model": settings.pi_model_preferences[0],
        "latency_ms": 0.0,
        "usage": {},
        "provider": None,
        "api": None,
        "stop_reason": None,
        "requested_selector": settings.pi_model_preferences[0],
        "requested_selectors": list(settings.pi_model_preferences),
        "resolved_selector": None,
        "fallback_used": False,
        "selector_mode": settings.pi_selector_mode.value,
        "generation_strategy": "primary",
        "alternate_strategy_used": False,
        "strategy_reason": None,
        "strategy_attempts": [],
    }

    for event in stream_events(
        prepared.messages,
        surface=PiToolBudgetSurface.RAG,
        settings=settings,
    ):
        event_type = event["type"]
        if event_type == "text_delta":
            token = str(event.get("delta", ""))
            if not token:
                continue
            tokens.append(token)
            yield StreamedRagAskEvent(type="text_delta", payload={"token": token})
        elif event_type == "done":
            metadata = {
                "model": event.get("resolved_selector")
                or event.get("model")
                or settings.pi_model_preferences[0],
                "latency_ms": float(event.get("latency_ms", 0.0)),
                "usage": event.get("usage") or {},
                "provider": event.get("provider"),
                "api": event.get("api"),
                "stop_reason": event.get("stop_reason"),
                "requested_selector": event.get("requested_selector"),
                "requested_selectors": list(event.get("requested_selectors") or []),
                "resolved_selector": event.get("resolved_selector") or event.get("model"),
                "fallback_used": bool(event.get("fallback_used", False)),
                "selector_mode": event.get("selector_mode"),
                "generation_strategy": event.get("generation_strategy", "primary"),
                "alternate_strategy_used": bool(event.get("alternate_strategy_used", False)),
                "strategy_reason": event.get("strategy_reason"),
                "strategy_attempts": list(event.get("strategy_attempts") or []),
            }

    final_answer = "".join(tokens)
    response_payload = _ask_response_payload(
        answer=final_answer,
        question=question,
        sources=prepared.sources,
        context=context_snapshot,
        working_set=working_set,
        metadata=metadata,
    )
    _record_ask_interaction(
        endpoint=endpoint,
        request_payload=request_payload,
        response_payload=response_payload,
        prepared=prepared,
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        settings=settings,
    )
    yield StreamedRagAskEvent(
        type="done",
        payload=AskResponse(
            answer=final_answer,
            chunks=prepared.chunks,
            model=metadata.get("model"),
            sources=prepared.sources,
            metadata=metadata,
            rerun_action=_ask_rerun_action(
                question=question,
                sources=prepared.sources,
                working_set_id=working_set_id,
            ),
            follow_through=_ask_follow_through(
                answer=final_answer,
                question=question,
                sources=prepared.sources,
                working_set=working_set,
            ),
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
    working_set_id: int | None = None,
    query: str | None = None,
) -> RagIngestExecutionResult:
    """Run the canonical ingest flow with interaction logging."""
    if not paths:
        raise ValueError("paths cannot be empty")

    request_payload: dict[str, Any] = {
        "paths": paths,
        "mode": mode,
        "recursive": recursive,
        "force_rehash": force_rehash,
    }
    if working_set_id is not None:
        request_payload["working_set_id"] = working_set_id
    if query is not None:
        request_payload["query"] = query
    result = ingest_paths(
        paths,
        mode=mode,
        recursive=recursive,
        force_rehash=force_rehash,
        settings=settings,
    )
    working_set = resolve_recall_working_set(working_set_id=working_set_id, settings=settings)
    follow_through = build_ingest_follow_through(
        paths=paths,
        mode=mode,
        recursive=recursive,
        result=result,
        query=query,
        working_set=working_set,
    )
    response = IngestResponse(
        **result,
        follow_through=follow_through,
    )
    response_payload = response.model_dump(mode="python")
    interaction_store.record_interaction(
        endpoint=endpoint,
        request_payload=request_payload,
        response_payload=response_payload,
        model=settings.embed_model,
        latency_ms=None,
        token_estimate=None,
        tool_calls=[],
        settings=settings,
    )
    return RagIngestExecutionResult(
        response=response,
        request_payload=request_payload,
        response_payload=response_payload,
    )
