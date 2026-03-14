"""Shared chat orchestration for request preparation and response shaping.

Purpose:
    Centralize the grounded-chat preparation used by HTTP today so later CLI and
    MCP transports can inherit the same request semantics instead of rebuilding
    context injection, retrieval, and response summaries independently.

Responsibilities:
    - Resolve effective chat options from request + settings
    - Build loop, memory, and RAG grounding context
    - Inject the canonical chat guidance/system messages
    - Prepare response-facing context summaries and source metadata

Non-scope:
    - Transport/SSE formatting
    - Bridge execution lifecycle
    - Interaction logging persistence
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from . import db, memory_management
from .loops.due import effective_due_iso
from .loops.errors import CloopError
from .rag import retrieve_similar_chunks
from .rag.ask_orchestration import format_sources, sanitize_chunk
from .schemas.chat import ChatRequest
from .settings import Settings, ToolMode


@dataclass(slots=True, frozen=True)
class EffectiveChatOptions:
    """Resolved chat options after applying request defaults and settings."""

    tool_mode: ToolMode
    include_loop_context: bool
    include_memory_context: bool
    memory_limit: int
    include_rag_context: bool
    rag_k: int
    rag_scope: str | None


@dataclass(slots=True, frozen=True)
class PreparedChatRequest:
    """Prepared chat payload ready for transport execution."""

    messages: list[dict[str, Any]]
    token_estimate: int
    interaction_context: dict[str, str]
    context_summary: dict[str, Any]
    effective_options: EffectiveChatOptions
    rag_chunks: list[dict[str, Any]]
    sources: list[dict[str, Any]]


@dataclass(slots=True, frozen=True)
class MemoryContextBuildResult:
    """Built memory context plus summary metadata."""

    content: str
    entry_count: int


@dataclass(slots=True, frozen=True)
class RagContextBuildResult:
    """Built RAG context plus response/log payloads."""

    content: str
    chunks: list[dict[str, Any]]
    sources: list[dict[str, Any]]


def build_effective_chat_options(
    *, request: ChatRequest, settings: Settings
) -> EffectiveChatOptions:
    """Resolve request options against settings defaults."""
    return EffectiveChatOptions(
        tool_mode=request.tool_mode or settings.tool_mode_default,
        include_loop_context=request.include_loop_context,
        include_memory_context=request.include_memory_context,
        memory_limit=request.memory_limit,
        include_rag_context=request.include_rag_context,
        rag_k=request.rag_k,
        rag_scope=request.rag_scope,
    )


def interaction_context(settings: Settings) -> dict[str, str]:
    """Build interaction context for logging."""
    backend = db.get_vector_backend()
    return {
        "embed_model": settings.embed_model,
        "vector_search_mode": settings.vector_search_mode.value,
        "embed_storage_mode": settings.embed_storage_mode.value,
        "vector_backend": backend.value,
    }


def build_chat_guidance(
    *,
    include_loop_context: bool,
    include_memory_context: bool,
    include_rag_context: bool,
) -> str:
    """Return product-specific chat guidance to keep answers grounded and useful."""
    guidance = [
        "You are Cloop's loop-aware planning assistant.",
        "Prioritize concrete, actionable guidance over generic self-help language.",
        (
            "If loop context is available, ground your answer in the actual loop "
            "titles, statuses, due items, and blockers you were given."
        ),
        "Prefer naming 1-3 specific loops or next actions instead of broad categories.",
        (
            "If the user asks what to focus on next, rank the most relevant current "
            "loops and explain why briefly."
        ),
        "Be concise, clear, and practical. Avoid motivational filler.",
    ]
    if include_memory_context:
        guidance.append("Use memory context to personalize recommendations when it is relevant.")
    if include_rag_context:
        guidance.append("Use retrieved document context when it directly supports the answer.")
    if not include_loop_context:
        guidance.append(
            "If no loop context is available, say that you are answering generally "
            "rather than pretending you inspected the user's loop state."
        )
    return "\n".join(guidance)


def build_loop_context_snapshot(settings: Settings) -> str:
    """Build a compact loop context snapshot for grounded chat requests."""
    from .loops.read_service import next_loops, search_loops_by_query

    lines = ["## Current Loop Context"]

    try:
        with db.core_connection(settings) as conn:
            buckets = next_loops(limit=5, conn=conn, settings=settings)
            blocked = search_loops_by_query(
                query="status:blocked",
                limit=5,
                offset=0,
                conn=conn,
            )
    except sqlite3.Error:
        return ""

    due_soon = buckets.get("due_soon", [])
    if due_soon:
        lines.append("\n### Due Soon")
        for loop in due_soon[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            due = effective_due_iso(loop)
            lines.append(f"- {title}")
            next_action = loop.get("next_action")
            if next_action:
                lines.append(f"  Next action: {next_action}")
            if due:
                lines.append(f"  Due: {due}")

    if blocked:
        lines.append("\n### Blocked")
        for loop in blocked[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            reason = loop.get("blocked_reason", "waiting on dependency")
            lines.append(f"- {title} ({reason})")
            next_action = loop.get("next_action")
            if next_action:
                lines.append(f"  Next action: {next_action}")

    quick_wins = buckets.get("quick_wins", [])
    if quick_wins:
        lines.append("\n### Quick Wins")
        for loop in quick_wins[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            mins = loop.get("time_minutes", "?")
            lines.append(f"- {title} (~{mins} min)")
            next_action = loop.get("next_action")
            if next_action:
                lines.append(f"  Next action: {next_action}")

    high_leverage = buckets.get("high_leverage", [])
    if high_leverage:
        lines.append("\n### High Leverage")
        for loop in high_leverage[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            lines.append(f"- {title}")
            next_action = loop.get("next_action")
            if next_action:
                lines.append(f"  Next action: {next_action}")

    standard = buckets.get("standard", [])
    if standard:
        lines.append("\n### Next Actions")
        for loop in standard[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            lines.append(f"- {title}")
            next_action = loop.get("next_action")
            if next_action:
                lines.append(f"  Next action: {next_action}")

    result = "\n".join(lines)
    return result if result != "## Current Loop Context" else ""


def build_memory_context(settings: Settings, *, limit: int = 10) -> MemoryContextBuildResult:
    """Build compact memory context plus a summary count."""
    try:
        result = memory_management.list_memory_entries(
            limit=limit,
            settings=settings,
        )
    except sqlite3.Error:
        return MemoryContextBuildResult(content="", entry_count=0)

    items = result.get("items", [])
    if not items:
        return MemoryContextBuildResult(content="", entry_count=0)

    items = sorted(items, key=lambda x: x.get("priority", 0), reverse=True)
    lines = ["## User Memory"]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        category = item.get("category", "fact")
        by_category.setdefault(category, []).append(item)

    category_labels = {
        "preference": "Preferences",
        "fact": "Facts",
        "commitment": "Commitments",
        "context": "Context",
    }

    included_count = 0
    for category in ["preference", "commitment", "fact", "context"]:
        if category not in by_category:
            continue
        lines.append(f"\n### {category_labels.get(category, category)}")
        for item in by_category[category]:
            included_count += 1
            key = item.get("key")
            content = item.get("content", "")[:200]
            if key:
                lines.append(f"- {key}: {content}")
            else:
                lines.append(f"- {content}")

    result_str = "\n".join(lines)
    content = result_str if result_str != "## User Memory" else ""
    return MemoryContextBuildResult(content=content, entry_count=included_count if content else 0)


def build_rag_context(
    *,
    request: ChatRequest,
    settings: Settings,
) -> RagContextBuildResult:
    """Build RAG grounding context for chat plus response-facing source metadata."""
    if not request.include_rag_context:
        return RagContextBuildResult(content="", chunks=[], sources=[])

    user_messages = [message for message in request.messages if message.role == "user"]
    if not user_messages:
        return RagContextBuildResult(content="", chunks=[], sources=[])

    query = user_messages[-1].content
    try:
        chunks = retrieve_similar_chunks(
            query,
            top_k=request.rag_k,
            scope=request.rag_scope,
            settings=settings,
        )
    except RuntimeError, CloopError:
        return RagContextBuildResult(content="", chunks=[], sources=[])

    if not chunks:
        return RagContextBuildResult(content="", chunks=[], sources=[])

    context_parts = [f"[{index}] {chunk['content']}" for index, chunk in enumerate(chunks, start=1)]
    sanitized_chunks = [sanitize_chunk(chunk) for chunk in chunks]
    return RagContextBuildResult(
        content="\n\n".join(context_parts),
        chunks=sanitized_chunks,
        sources=format_sources(sanitized_chunks),
    )


def prepare_chat_request(*, request: ChatRequest, settings: Settings) -> PreparedChatRequest:
    """Prepare a chat request for execution and client-facing response shaping."""
    options = build_effective_chat_options(request=request, settings=settings)
    messages = [message.model_dump() for message in request.messages]
    log_context = interaction_context(settings)
    context_summary: dict[str, Any] = {
        "loop_context_applied": False,
        "memory_context_applied": False,
        "memory_entries_used": 0,
        "rag_context_applied": False,
        "rag_chunks_used": 0,
    }

    loop_context = ""
    if options.include_loop_context:
        loop_context = build_loop_context_snapshot(settings)
        if loop_context:
            messages.insert(0, {"role": "system", "content": loop_context})
            log_context["loop_context"] = loop_context
            context_summary["loop_context_applied"] = True

    messages.insert(
        0,
        {
            "role": "system",
            "content": build_chat_guidance(
                include_loop_context=options.include_loop_context,
                include_memory_context=options.include_memory_context,
                include_rag_context=options.include_rag_context,
            ),
        },
    )

    memory_result = MemoryContextBuildResult(content="", entry_count=0)
    if options.include_memory_context:
        memory_result = build_memory_context(settings, limit=options.memory_limit)
        if memory_result.content:
            messages.insert(0, {"role": "system", "content": memory_result.content})
            log_context["memory_context"] = memory_result.content
            context_summary["memory_context_applied"] = True
            context_summary["memory_entries_used"] = memory_result.entry_count

    rag_result = build_rag_context(request=request, settings=settings)
    if rag_result.content:
        messages.insert(
            0,
            {
                "role": "system",
                "content": f"Relevant context from your documents:\n\n{rag_result.content}",
            },
        )
        log_context["rag_context"] = rag_result.content
        context_summary["rag_context_applied"] = True
        context_summary["rag_chunks_used"] = len(rag_result.chunks)

    from .llm import estimate_tokens

    return PreparedChatRequest(
        messages=messages,
        token_estimate=estimate_tokens(messages),
        interaction_context=log_context,
        context_summary=context_summary,
        effective_options=options,
        rag_chunks=rag_result.chunks,
        sources=rag_result.sources,
    )
