"""Shared RAG ask orchestration.

Purpose:
    Centralize the retrieval-plus-answer flow used by RAG question answering so
    HTTP routes and CLI commands share the same context construction,
    sanitization, and answer-generation behavior.

Responsibilities:
    - Retrieve relevant chunks for a question
    - Sanitize chunk payloads for external consumers
    - Build source references from retrieved chunks
    - Build the prompt/messages used for answer generation
    - Execute non-streaming LLM completion for RAG ask flows

Non-scope:
    - Document ingestion
    - Streaming token emission and SSE transport details
    - Interaction logging persistence

Usage:
    - Call `prepare_ask_context(...)` when a transport needs retrieval and
      prompt preparation, including streaming routes.
    - Call `answer_question(...)` or `answer_prepared_question(...)` when a
      transport needs the complete non-streaming ask flow.

Invariants/Assumptions:
    - The no-knowledge fallback message is consistent across transports.
    - Response chunks never expose `embedding_blob`.
    - Source payloads are derived from the sanitized chunk list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..llm import chat_completion, estimate_tokens
from ..settings import Settings
from .search import retrieve_similar_chunks

NO_KNOWLEDGE_MESSAGE = "No knowledge available. Ingest documents first."


@dataclass(slots=True, frozen=True)
class PreparedAskContext:
    """Prepared retrieval and prompt context for a RAG ask request."""

    chunks: list[dict[str, Any]]
    messages: list[dict[str, str]]
    sources: list[dict[str, Any]]
    token_estimate: int

    @property
    def has_knowledge(self) -> bool:
        """Whether retrieval found any knowledge to answer from."""
        return bool(self.chunks)


@dataclass(slots=True, frozen=True)
class AskAnswer:
    """Completed non-streaming answer payload for a RAG ask request."""

    answer: str
    chunks: list[dict[str, Any]]
    latency_ms: float | None
    model: str | None
    sources: list[dict[str, Any]]
    token_estimate: int


def sanitize_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Remove internal-only vector payloads from a retrieved chunk."""
    sanitized = dict(chunk)
    sanitized.pop("embedding_blob", None)
    return sanitized


def format_sources(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format sanitized chunks into source references."""
    return [
        {
            "id": chunk.get("id"),
            "document_path": chunk.get("document_path"),
            "chunk_index": chunk.get("chunk_index"),
            "score": chunk.get("score"),
        }
        for chunk in chunks
    ]


def build_ask_messages(*, question: str, chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build the prompt messages for a RAG question-answering request."""
    context = "\n\n".join(
        f"[{index}] {chunk['content']}" for index, chunk in enumerate(chunks, start=1)
    )
    return [
        {
            "role": "system",
            "content": "Use the provided context to answer. If unsure, say you do not know.",
        },
        {
            "role": "user",
            "content": f"Question: {question}\n\nContext:\n{context}",
        },
    ]


def prepare_ask_context(
    *,
    question: str,
    top_k: int,
    scope: str | None,
    settings: Settings,
) -> PreparedAskContext:
    """Retrieve chunks and build the shared prompt context for a question."""
    raw_chunks = retrieve_similar_chunks(
        question,
        top_k=top_k,
        scope=scope,
        settings=settings,
    )
    sanitized_chunks = [sanitize_chunk(chunk) for chunk in raw_chunks]
    if not sanitized_chunks:
        return PreparedAskContext(
            chunks=[],
            messages=[],
            sources=[],
            token_estimate=0,
        )

    messages = build_ask_messages(question=question, chunks=sanitized_chunks)
    return PreparedAskContext(
        chunks=sanitized_chunks,
        messages=messages,
        sources=format_sources(sanitized_chunks),
        token_estimate=estimate_tokens(messages),
    )


def answer_question(
    *,
    question: str,
    top_k: int,
    scope: str | None,
    settings: Settings,
) -> AskAnswer:
    """Run the shared non-streaming RAG ask flow."""
    prepared = prepare_ask_context(
        question=question,
        top_k=top_k,
        scope=scope,
        settings=settings,
    )
    return answer_prepared_question(prepared=prepared, settings=settings)


def answer_prepared_question(
    *,
    prepared: PreparedAskContext,
    settings: Settings,
) -> AskAnswer:
    """Answer a question from already-prepared retrieval context."""
    if not prepared.has_knowledge:
        return AskAnswer(
            answer=NO_KNOWLEDGE_MESSAGE,
            chunks=[],
            latency_ms=None,
            model=None,
            sources=[],
            token_estimate=0,
        )

    content, metadata = chat_completion(prepared.messages, settings=settings)
    return AskAnswer(
        answer=content,
        chunks=prepared.chunks,
        latency_ms=metadata.get("latency_ms"),
        model=metadata.get("model"),
        sources=prepared.sources,
        token_estimate=prepared.token_estimate,
    )
