"""Planning workflow grounding and generation helpers.

Purpose:
    Build grounded planning context and translate pi output into validated
    checkpointed planning workflows.

Responsibilities:
    - Select target loops for grounding
    - Build optional memory and RAG context payloads
    - Prompt pi with the allowed planning schema
    - Validate and normalize generated workflow JSON

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Planning context construction and generation only
    - No session persistence or checkpoint execution

Usage:
    Called by planning-session creation and refresh flows.

Invariants/Assumptions:
    - Planner output is constrained to deterministic operation kinds
    - Grounding payloads only reference known loop IDs from the current system
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ...chat_orchestration import build_memory_context, build_rag_context
from ...schemas.chat import ChatMessage, ChatRequest
from ...settings import PiToolBudgetSurface, Settings
from .. import read_service
from ..errors import ValidationError
from ..models import format_utc_datetime, utc_now
from .inputs import _extract_json_object
from .models import GeneratedPlanningWorkflowModel, PlanningCheckpointModel


def _compact_loop_payload(loop: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(loop["id"]),
        "title": loop.get("title"),
        "raw_text": loop.get("raw_text"),
        "summary": loop.get("summary"),
        "next_action": loop.get("next_action"),
        "status": loop.get("status"),
        "due_date": loop.get("due_date"),
        "due_at_utc": loop.get("due_at_utc"),
        "updated_at_utc": loop.get("updated_at_utc"),
        "project": loop.get("project"),
        "tags": list(loop.get("tags") or []),
        "blocked_reason": loop.get("blocked_reason"),
        "enrichment_state": loop.get("enrichment_state"),
    }


def _default_target_loops(
    *,
    limit: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> list[dict[str, Any]]:
    buckets = read_service.next_loops(limit=limit, conn=conn, settings=settings)
    ordered: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for bucket_name in ("due_soon", "quick_wins", "high_leverage", "standard"):
        for loop in buckets.get(bucket_name, []):
            loop_id = int(loop["id"])
            if loop_id in seen_ids:
                continue
            seen_ids.add(loop_id)
            ordered.append(loop)
            if len(ordered) >= limit:
                return ordered

    if ordered:
        return ordered
    return read_service.search_loops_by_query(query="status:open", limit=limit, offset=0, conn=conn)


def _resolve_target_loops(
    *,
    query: str | None,
    options: Mapping[str, Any],
    conn: sqlite3.Connection,
    settings: Settings,
) -> list[dict[str, Any]]:
    limit = int(options["loop_limit"])
    if query:
        return read_service.search_loops_by_query(query=query, limit=limit, offset=0, conn=conn)
    return _default_target_loops(limit=limit, conn=conn, settings=settings)


def _build_planner_rag_context(
    *,
    prompt: str,
    options: Mapping[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    if not options.get("include_rag_context"):
        return {"content": "", "chunks_used": 0, "sources": []}

    request = ChatRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        include_rag_context=True,
        rag_k=int(options["rag_k"]),
        rag_scope=options.get("rag_scope"),
    )
    rag_result = build_rag_context(request=request, settings=settings)
    return {
        "content": rag_result.content,
        "chunks_used": len(rag_result.chunks),
        "sources": rag_result.sources,
    }


def _planner_schema_description() -> dict[str, Any]:
    return {
        "title": "short plan title",
        "summary": "concise overview of how the workflow addresses the request",
        "assumptions": [
            "optional assumption or caution",
            (
                "if a checkpoint creates a saved review session, "
                "that session may become the next operator queue"
            ),
        ],
        "checkpoints": [
            {
                "title": "checkpoint title",
                "summary": "what this checkpoint accomplishes",
                "success_criteria": "how the operator will know this checkpoint is done",
                "operations": [
                    {
                        "kind": "create_enrichment_review_session",
                        "summary": "queue suggestion follow-up before later deterministic edits",
                        "name": "launch-enrichment-follow-up",
                        "query": "project:launch status:open",
                        "pending_kind": "all",
                        "suggestion_limit": 3,
                        "clarification_limit": 3,
                        "item_limit": 25,
                    }
                ],
            }
        ],
        "operation_kinds": {
            "create_loop": {
                "required": ["summary", "raw_text"],
                "optional": ["status", "capture_fields"],
            },
            "update_loop": {
                "required": ["summary", "loop_id", "fields"],
                "optional_fields": [
                    "title",
                    "summary",
                    "definition_of_done",
                    "next_action",
                    "due_date",
                    "due_at_utc",
                    "snooze_until_utc",
                    "time_minutes",
                    "activation_energy",
                    "urgency",
                    "importance",
                    "project",
                    "blocked_reason",
                    "completion_note",
                    "tags",
                ],
            },
            "transition_loop": {
                "required": ["summary", "loop_id", "status"],
                "allowed_statuses": ["inbox", "actionable", "blocked", "scheduled"],
                "optional": ["note"],
            },
            "close_loop": {
                "required": ["summary", "loop_id"],
                "allowed_statuses": ["completed", "dropped"],
                "optional": ["status", "note"],
            },
            "enrich_loop": {"required": ["summary", "loop_id"]},
            "bulk_enrich_query": {
                "required": ["summary", "query"],
                "optional": ["limit"],
            },
            "query_bulk_update": {
                "required": ["summary", "query", "fields"],
                "optional": ["limit"],
            },
            "query_bulk_close": {
                "required": ["summary", "query"],
                "optional": ["status", "note", "limit"],
            },
            "query_bulk_snooze": {
                "required": ["summary", "query", "snooze_until_utc"],
                "optional": ["limit"],
            },
            "create_relationship_review_session": {
                "required": ["summary", "name", "query"],
                "optional": ["relationship_kind", "candidate_limit", "item_limit"],
            },
            "create_enrichment_review_session": {
                "required": ["summary", "name", "query"],
                "optional": [
                    "pending_kind",
                    "suggestion_limit",
                    "clarification_limit",
                    "item_limit",
                ],
            },
            "create_loop_view": {
                "required": ["summary", "name", "query"],
                "optional": ["description"],
            },
            "update_loop_view": {
                "required": ["summary", "view_id"],
                "optional": ["name", "query", "description"],
            },
            "create_loop_template_from_loop": {
                "required": ["summary", "loop_id", "template_name"],
            },
            "update_loop_template": {
                "required": ["summary", "template_id"],
                "optional": ["name", "description", "raw_text_pattern", "defaults_json"],
            },
        },
    }


def _build_planner_messages(
    *,
    prompt: str,
    query: str | None,
    target_loops: Sequence[Mapping[str, Any]],
    memory_context: str,
    memory_entries_used: int,
    rag_context: str,
    rag_chunks_used: int,
) -> list[dict[str, str]]:
    grounded_payload = {
        "operator_request": prompt,
        "query": query,
        "target_loop_count": len(target_loops),
        "target_loops": [_compact_loop_payload(loop) for loop in target_loops],
        "memory_entries_used": memory_entries_used,
        "memory_context": memory_context,
        "rag_chunks_used": rag_chunks_used,
        "rag_context": rag_context,
    }

    return [
        {
            "role": "system",
            "content": (
                "You are Cloop's planning workflow generator. "
                "Return only JSON. Build a checkpointed workflow that uses only the allowed "
                "deterministic operations. Do not invent unseen loop IDs. Prefer 2-5 checkpoints "
                "with the smallest useful operation set. Prefer query_bulk_update, "
                "query_bulk_close, or query_bulk_snooze when the same deterministic change "
                "applies to multiple loops from one DSL query. If work requires human judgment "
                "about duplicates, suggestions, or clarifications, create saved review sessions "
                "instead of pretending that review has already happened. When a saved review "
                "session is needed, treat it as a real operator handoff point and avoid later "
                "checkpoint steps that assume the review outcome already exists. If clarification "
                "answers are missing, do not fabricate them. Keep summaries practical and concrete."
            ),
        },
        {"role": "user", "content": json.dumps(grounded_payload)},
        {
            "role": "system",
            "content": json.dumps(_planner_schema_description()),
        },
    ]


def _generate_workflow_plan(
    *,
    prompt: str,
    query: str | None,
    options: Mapping[str, Any],
    conn: sqlite3.Connection,
    settings: Settings,
    planner_chat_completion: Any,
) -> dict[str, Any]:
    target_loops = _resolve_target_loops(
        query=query,
        options=options,
        conn=conn,
        settings=settings,
    )
    memory_result = (
        build_memory_context(settings, limit=10) if options.get("include_memory_context") else None
    )
    rag_result = _build_planner_rag_context(prompt=prompt, options=options, settings=settings)

    messages = _build_planner_messages(
        prompt=prompt,
        query=query,
        target_loops=target_loops,
        memory_context=memory_result.content if memory_result else "",
        memory_entries_used=memory_result.entry_count if memory_result else 0,
        rag_context=str(rag_result["content"]),
        rag_chunks_used=int(rag_result["chunks_used"]),
    )
    content, metadata = planner_chat_completion(
        messages,
        surface=PiToolBudgetSurface.PLANNING,
        settings=settings,
        thinking_level=settings.pi_thinking_level,
        timeout_s=settings.pi_timeout,
    )
    raw_json = _extract_json_object(content)
    try:
        plan_model = GeneratedPlanningWorkflowModel.model_validate(raw_json)
    except PydanticValidationError as exc:
        raise ValidationError("response", f"invalid planner response: {exc}") from exc

    checkpoints = [
        {
            **checkpoint.model_dump(mode="json"),
            "focus_loop_ids": _checkpoint_focus_loop_ids(checkpoint),
        }
        for checkpoint in plan_model.checkpoints
    ]

    return {
        "workflow": {
            "title": plan_model.title,
            "summary": plan_model.summary,
            "assumptions": list(plan_model.assumptions),
            "checkpoints": checkpoints,
            "context_summary": {
                "query": query,
                "target_loop_count": len(target_loops),
                "memory_entries_used": memory_result.entry_count if memory_result else 0,
                "rag_chunks_used": int(rag_result["chunks_used"]),
                "generated_at_utc": format_utc_datetime(utc_now()),
            },
            "target_loops": [_compact_loop_payload(loop) for loop in target_loops],
            "sources": list(rag_result["sources"]),
            "planner_metadata": metadata,
        }
    }


def _checkpoint_focus_loop_ids(checkpoint: PlanningCheckpointModel) -> list[int]:
    ordered: list[int] = []
    seen_ids: set[int] = set()
    for operation in checkpoint.operations:
        loop_id = getattr(operation, "loop_id", None)
        if isinstance(loop_id, int) and loop_id not in seen_ids:
            seen_ids.add(loop_id)
            ordered.append(loop_id)
    return ordered


__all__ = [
    "_compact_loop_payload",
    "_default_target_loops",
    "_resolve_target_loops",
    "_build_planner_rag_context",
    "_planner_schema_description",
    "_build_planner_messages",
    "_generate_workflow_plan",
    "_checkpoint_focus_loop_ids",
]
