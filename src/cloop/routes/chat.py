"""Chat completion endpoint with optional tool support.

Purpose:
    HTTP endpoints for chat completions with tool calling.

Responsibilities:
    - POST /chat: Chat completion endpoint
    - Tool execution integration

Non-scope:
    - LLM provider logic (see llm.py)
    - Tool implementations (see tools.py)

Supports:
- Basic chat completions
- Manual tool execution (read_note, write_note, loop_*)
- LLM-orchestrated tool mode
- SSE streaming for real-time responses
"""

import json
import sqlite3
import time
from collections.abc import Iterator
from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..llm import (
    ToolCallError,
    chat_completion,
    chat_with_tools,
    estimate_tokens,
    stream_completion,
)
from ..loops.errors import CloopError
from ..rag import retrieve_similar_chunks
from ..schemas.chat import ChatRequest, ChatResponse, _InteractionMetadata
from ..settings import Settings, ToolMode, get_settings
from ..sse import format_sse_event
from ..tools import TOOL_SPECS

router = APIRouter(prefix="/chat", tags=["chat"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


def handle_tool_call(tool_call, settings: Settings) -> Dict[str, Any]:
    """Execute a manual tool call."""
    from ..tools import EXECUTORS

    executor = EXECUTORS.get(tool_call.name)
    if executor is None:
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool_call.name}")
    try:
        return executor(**tool_call.arguments)
    except CloopError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _interaction_context(settings: Settings) -> Dict[str, str]:
    """Build interaction context for logging."""
    backend = db.get_vector_backend()
    return {
        "embed_model": settings.embed_model,
        "vector_search_mode": settings.vector_search_mode.value,
        "embed_storage_mode": settings.embed_storage_mode.value,
        "vector_backend": backend.value,
    }


def _build_chat_guidance(
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


def _build_loop_context_snapshot(settings: Settings) -> str:
    """Build compact loop context snapshot for LLM system message.

    Returns markdown-formatted string with:
    - Due soon items (within 48h)
    - Blocked items
    - Top next actions (quick wins, high leverage)

    Target: ~500-1000 tokens to avoid context bloat.
    """
    from ..loops.service import next_loops, search_loops_by_query

    lines = ["## Current Loop Context"]

    try:
        with db.core_connection(settings) as conn:
            # Get prioritized next loops
            buckets = next_loops(limit=5, conn=conn, settings=settings)

            # Get blocked loops separately (excluded from next_loops)
            blocked = search_loops_by_query(
                query="status:blocked",
                limit=5,
                offset=0,
                conn=conn,
            )
    except sqlite3.Error:
        # Fail gracefully - don't block chat if loop context fails
        return ""

    # Due soon section
    due_soon = buckets.get("due_soon", [])
    if due_soon:
        lines.append("\n### Due Soon")
        for loop in due_soon[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            due = loop.get("due_at_utc")
            lines.append(f"- {title}")
            if due:
                lines.append(f"  Due: {due}")

    # Blocked section
    if blocked:
        lines.append("\n### Blocked")
        for loop in blocked[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            reason = loop.get("blocked_reason", "waiting on dependency")
            lines.append(f"- {title} ({reason})")

    # Quick wins section
    quick_wins = buckets.get("quick_wins", [])
    if quick_wins:
        lines.append("\n### Quick Wins")
        for loop in quick_wins[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            mins = loop.get("time_minutes", "?")
            lines.append(f"- {title} (~{mins} min)")

    # High leverage section
    high_leverage = buckets.get("high_leverage", [])
    if high_leverage:
        lines.append("\n### High Leverage")
        for loop in high_leverage[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            lines.append(f"- {title}")

    # Standard/other actionable items
    standard = buckets.get("standard", [])
    if standard:
        lines.append("\n### Next Actions")
        for loop in standard[:3]:
            title = loop.get("title") or loop.get("raw_text", "")[:60]
            lines.append(f"- {title}")

    result = "\n".join(lines)
    return result if result != "## Current Loop Context" else ""


def _build_memory_context(settings: Settings, limit: int = 10) -> str:
    """Build compact memory context for LLM system message.

    Returns markdown-formatted string with:
    - Preferences
    - Facts
    - Commitments
    - Context entries

    Sorted by priority (highest first), bounded by limit.
    Target: ~300-500 tokens to avoid context bloat.
    """
    try:
        result = db.list_memory_entries(
            limit=limit,
            settings=settings,
        )
    except sqlite3.Error:
        return ""

    items = result.get("items", [])
    if not items:
        return ""

    # Sort by priority (highest first) to match docstring promise
    items = sorted(items, key=lambda x: x.get("priority", 0), reverse=True)

    lines = ["## User Memory"]

    by_category: dict[str, list[dict]] = {}
    for item in items:
        cat = item.get("category", "fact")
        by_category.setdefault(cat, []).append(item)

    category_labels = {
        "preference": "Preferences",
        "fact": "Facts",
        "commitment": "Commitments",
        "context": "Context",
    }

    for cat in ["preference", "commitment", "fact", "context"]:
        if cat not in by_category:
            continue
        lines.append(f"\n### {category_labels.get(cat, cat)}")
        for item in by_category[cat]:
            key = item.get("key")
            content = item.get("content", "")[:200]
            if key:
                lines.append(f"- {key}: {content}")
            else:
                lines.append(f"- {content}")

    result_str = "\n".join(lines)
    return result_str if result_str != "## User Memory" else ""


@router.post("", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    stream: Annotated[bool | None, Query(description="Stream Server-Sent Events when true")] = None,
) -> Any:
    messages = [message.model_dump() for message in request.messages]
    tool_result: Dict[str, Any] | None = None
    tool_calls: List[Dict[str, Any]] = []

    # Build and inject loop context if requested
    loop_context: str | None = None
    if request.include_loop_context:
        loop_context = _build_loop_context_snapshot(settings)
        if loop_context:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": loop_context,
                },
            )

    messages.insert(
        0,
        {
            "role": "system",
            "content": _build_chat_guidance(
                include_loop_context=request.include_loop_context,
                include_memory_context=request.include_memory_context,
                include_rag_context=request.include_rag_context,
            ),
        },
    )

    # Build and inject memory context if requested (inserted first so memory precedes loop context)
    memory_context: str | None = None
    if request.include_memory_context:
        memory_context = _build_memory_context(settings, limit=request.memory_limit)
        if memory_context:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": memory_context,
                },
            )

    # Build and inject RAG context if requested
    rag_chunks: List[Dict[str, Any]] = []
    rag_context: str | None = None
    if request.include_rag_context:
        user_messages = [m for m in request.messages if m.role == "user"]
        if user_messages:
            query = user_messages[-1].content
            try:
                rag_chunks = retrieve_similar_chunks(
                    query,
                    top_k=request.rag_k,
                    scope=request.rag_scope,
                    settings=settings,
                )
            except RuntimeError, CloopError:
                rag_chunks = []

            if rag_chunks:
                context_parts = [
                    f"[{idx}] {chunk['content']}" for idx, chunk in enumerate(rag_chunks, start=1)
                ]
                rag_context = "\n\n".join(context_parts)
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": f"Relevant context from your documents:\n\n{rag_context}",
                    },
                )

    tool_mode = request.tool_mode or settings.tool_mode_default

    if request.tool_call and tool_mode is not ToolMode.MANUAL:
        raise HTTPException(status_code=400, detail="tool_call is only supported in manual mode")

    if tool_mode is ToolMode.MANUAL:
        tool_call = request.tool_call
        if tool_call is None:
            raise HTTPException(status_code=422, detail="tool_call required in manual mode")
        tool_result = handle_tool_call(tool_call, settings)
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
    if memory_context:
        context_snapshot["memory_context"] = memory_context
    if loop_context:
        context_snapshot["loop_context"] = loop_context
    if rag_context:
        context_snapshot["rag_context"] = rag_context

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
                yield format_sse_event("token", {"token": token})
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
            sanitized_rag_chunks = [
                {k: v for k, v in chunk.items() if k != "embedding_blob"} for chunk in rag_chunks
            ]
            db.record_interaction(
                endpoint="/chat",
                request_payload=request_payload,
                response_payload=response_payload,
                model=metadata["model"],
                latency_ms=metadata["latency_ms"],
                token_estimate=token_estimate,
                selected_chunks=sanitized_rag_chunks,
                tool_calls=tool_calls,
                settings=settings,
            )
            yield format_sse_event(
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
    sanitized_rag_chunks = [
        {k: v for k, v in chunk.items() if k != "embedding_blob"} for chunk in rag_chunks
    ]
    db.record_interaction(
        endpoint="/chat",
        request_payload=request.model_dump(),
        response_payload=response_payload,
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        token_estimate=token_estimate,
        selected_chunks=sanitized_rag_chunks,
        tool_calls=tool_calls,
        settings=settings,
    )

    return ChatResponse(
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        model=metadata.get("model"),
    )
