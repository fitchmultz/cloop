"""Shared grounded Recall handoff builders.

Purpose:
    Build transport-neutral grounded-chat launch payloads so planning, review,
    and operator surfaces can reopen Recall with preserved query and grounding
    context instead of inventing ad-hoc chat handoffs.

Responsibilities:
    - Create canonical Recall chat locations with explicit grounding flags.
    - Shape planning launch-surface payloads for grounded chat follow-through.
    - Shape review follow-through chat handoff locations.

Non-scope:
    - Executing grounded chat requests.
    - Frontend-only routing or rendering behavior.

Scope:
    - Grounded-chat handoff payload construction only.

Usage:
    - Imported by planning and review workflow orchestration when emitting
      follow-through contracts.

Invariants/Assumptions:
    - Grounded chat remains the Recall destination for these handoffs.
    - Query text stays deterministic and transport-safe.
    - Grounding flags are optional and only applied when explicitly provided.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def grounded_chat_location(
    *,
    query: str,
    working_set_id: int | None = None,
    include_loop_context: bool | None = True,
    include_memory_context: bool | None = None,
    include_rag_context: bool | None = None,
) -> dict[str, Any]:
    """Build one transport-neutral grounded-chat launch location."""
    location: dict[str, Any] = {
        "state": "recall",
        "recall_tool": "chat",
        "query": query.strip(),
    }
    if working_set_id is not None:
        location["working_set_id"] = working_set_id
    if include_loop_context is not None:
        location["include_loop_context"] = include_loop_context
    if include_memory_context is not None:
        location["include_memory_context"] = include_memory_context
    if include_rag_context is not None:
        location["include_rag_context"] = include_rag_context
    return location


def planning_grounded_chat_launch_surface(
    *,
    session_id: int,
    session_name: str,
    checkpoint_title: str,
    checkpoint_summary: str,
    working_set_id: int | None,
    include_memory_context: bool,
    include_rag_context: bool,
) -> dict[str, Any]:
    """Build one planning launch-surface handoff into grounded chat."""
    summary = checkpoint_summary.strip() or checkpoint_title.strip()
    checkpoint_title_text = checkpoint_title.strip()
    session_name_text = session_name.strip()
    query = (
        f"I just finished the planning checkpoint '{checkpoint_title_text}' in "
        f"'{session_name_text}'. What changed, what should I review next, and what should I do now?"
    )
    location = grounded_chat_location(
        query=query,
        working_set_id=working_set_id,
        include_loop_context=True,
        include_memory_context=include_memory_context,
        include_rag_context=include_rag_context,
    )
    return {
        "surface": "recall_chat",
        "label": "Grounded chat follow-through",
        "resource_type": "planning_session",
        "resource_id": session_id,
        "reason": (
            f"Open grounded chat to synthesize the checkpoint impact and next move after {summary}."
        ),
        "http": {
            "path": "/chat",
            "method": "POST",
            "body": {
                "messages": [{"role": "user", "content": query}],
                "include_loop_context": True,
                "include_memory_context": include_memory_context,
                "include_rag_context": include_rag_context,
            },
        },
        "mcp": {
            "tool": "chat.complete",
            "arguments": {
                "messages": [{"role": "user", "content": query}],
                "include_loop_context": True,
                "include_memory_context": include_memory_context,
                "include_rag_context": include_rag_context,
            },
        },
        "web": {
            "surface": "recall_chat",
            **location,
        },
    }


def review_grounded_chat_handoff(
    *,
    review_focus: str,
    session: Mapping[str, Any],
    current_loop_label: str | None,
    working_set_id: int | None,
) -> dict[str, Any]:
    """Build one review follow-through handoff into grounded chat."""
    queue_name = str(session.get("name") or f"{review_focus.title()} review").strip()
    current_loop_suffix = (
        f" Review {current_loop_label.strip()} next if it still needs attention."
        if current_loop_label and current_loop_label.strip()
        else ""
    )
    query = (
        f"I just recorded a {review_focus} review outcome in '{queue_name}'. "
        f"What changed, what should I verify next, and what should I do now?"
        f"{current_loop_suffix}"
    )
    return grounded_chat_location(
        query=query,
        working_set_id=working_set_id,
        include_loop_context=True,
        include_memory_context=True,
        include_rag_context=False,
    )


__all__ = [
    "grounded_chat_location",
    "planning_grounded_chat_launch_surface",
    "review_grounded_chat_handoff",
]
