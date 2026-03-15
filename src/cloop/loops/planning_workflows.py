"""Shared AI-native planning workflows.

Purpose:
    Centralize durable, checkpointed planning sessions so HTTP, CLI, MCP, and
    the web UI can share one contract for AI-generated multi-step workflow
    planning on top of deterministic loop operations.

Responsibilities:
    - Build grounded planning context from loops, memory, and optional RAG
    - Generate structured checkpoint plans through pi
    - Persist durable planning sessions plus execution history
    - Move a planning cursor through checkpoints
    - Execute the current checkpoint through deterministic shared operations
    - Return transparent before/after results for checkpoint execution
    - Refresh an existing planning session against current loop state

Non-scope:
    - Transport-specific request/response shaping
    - Direct tool registration or CLI rendering
    - Raw SQL details (see repo.py)
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from .. import typingx
from ..chat_orchestration import build_memory_context, build_rag_context
from ..llm import chat_completion
from ..schemas.chat import ChatMessage, ChatRequest
from ..schemas.loops import LoopUpdateRequest
from ..settings import Settings
from . import enrichment_orchestration, read_service, repo, review_workflows, service
from .errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from .models import LoopStatus, format_utc_datetime, utc_now

PlanningSessionStatus = Literal["draft", "in_progress", "completed"]
PlanningMoveDirection = Literal["next", "previous"]

_MAX_PLANNING_TARGETS = 25
_MAX_PLANNING_CHECKPOINTS = 6
_MAX_PLANNING_OPERATIONS_PER_CHECKPOINT = 10

_DEFAULT_PLANNING_OPTIONS = {
    "loop_limit": 10,
    "include_memory_context": True,
    "include_rag_context": False,
    "rag_k": 5,
    "rag_scope": None,
}


class PlanningSessionOptionsModel(BaseModel):
    """Validated persisted options for one planning session."""

    loop_limit: int = Field(default=10, ge=1, le=_MAX_PLANNING_TARGETS)
    include_memory_context: bool = True
    include_rag_context: bool = False
    rag_k: int = Field(default=5, ge=1, le=20)
    rag_scope: str | None = None


class BasePlanningOperationModel(BaseModel):
    """Shared human-facing metadata for one generated operation."""

    kind: str
    summary: str = Field(..., min_length=1, max_length=500)


class CreateLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["create_loop"] = "create_loop"
    raw_text: str = Field(..., min_length=1, max_length=4000)
    status: Literal["inbox", "actionable", "blocked", "scheduled"] = "inbox"
    capture_fields: LoopUpdateRequest | None = None


class UpdateLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["update_loop"] = "update_loop"
    loop_id: int
    fields: LoopUpdateRequest


class TransitionLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["transition_loop"] = "transition_loop"
    loop_id: int
    status: Literal["inbox", "actionable", "blocked", "scheduled"]
    note: str | None = None


class CloseLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["close_loop"] = "close_loop"
    loop_id: int
    status: Literal["completed", "dropped"] = "completed"
    note: str | None = None


class EnrichLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["enrich_loop"] = "enrich_loop"
    loop_id: int


class BulkEnrichQueryOperationModel(BasePlanningOperationModel):
    kind: Literal["bulk_enrich_query"] = "bulk_enrich_query"
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)


class CreateRelationshipReviewSessionOperationModel(BasePlanningOperationModel):
    kind: Literal["create_relationship_review_session"] = "create_relationship_review_session"
    name: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    relationship_kind: Literal["all", "duplicate", "related"] = "all"
    candidate_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)


class CreateEnrichmentReviewSessionOperationModel(BasePlanningOperationModel):
    kind: Literal["create_enrichment_review_session"] = "create_enrichment_review_session"
    name: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    pending_kind: Literal["all", "suggestions", "clarifications"] = "all"
    suggestion_limit: int = Field(default=3, ge=1, le=20)
    clarification_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)


PlanningOperationModel = Annotated[
    CreateLoopOperationModel
    | UpdateLoopOperationModel
    | TransitionLoopOperationModel
    | CloseLoopOperationModel
    | EnrichLoopOperationModel
    | BulkEnrichQueryOperationModel
    | CreateRelationshipReviewSessionOperationModel
    | CreateEnrichmentReviewSessionOperationModel,
    Field(discriminator="kind"),
]


class PlanningCheckpointModel(BaseModel):
    """One checkpoint inside a generated planning workflow."""

    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=1000)
    success_criteria: str = Field(..., min_length=1, max_length=1000)
    operations: list[PlanningOperationModel] = Field(
        ...,
        min_length=1,
        max_length=_MAX_PLANNING_OPERATIONS_PER_CHECKPOINT,
    )


class GeneratedPlanningWorkflowModel(BaseModel):
    """Validated AI-generated workflow structure."""

    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    checkpoints: list[PlanningCheckpointModel] = Field(
        ...,
        min_length=1,
        max_length=_MAX_PLANNING_CHECKPOINTS,
    )


_OPERATION_ADAPTER = TypeAdapter(PlanningOperationModel)


def _normalize_name(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError(field, f"{field.replace('_', ' ')} must not be empty")
    return normalized


def _normalize_prompt(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError("prompt", "prompt must not be empty")
    return normalized


def _normalize_optional_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_move_direction(value: str) -> PlanningMoveDirection:
    if value == "next":
        return "next"
    if value == "previous":
        return "previous"
    raise ValidationError("direction", "must be next or previous")


def _validate_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {**_DEFAULT_PLANNING_OPTIONS, **(dict(options) if options else {})}
    return PlanningSessionOptionsModel.model_validate(merged).model_dump(mode="json")


def _extract_json_object(payload: str) -> dict[str, Any]:
    text = payload.strip()
    decoder = json.JSONDecoder()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValidationError("response", "invalid JSON from planner")


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
        "assumptions": ["optional assumption or caution"],
        "checkpoints": [
            {
                "title": "checkpoint title",
                "summary": "what this checkpoint accomplishes",
                "success_criteria": "how the operator will know this checkpoint is done",
                "operations": [
                    {
                        "kind": "update_loop",
                        "summary": "why this concrete update helps",
                        "loop_id": 123,
                        "fields": {"next_action": "Email finance for final numbers"},
                    },
                    {
                        "kind": "create_relationship_review_session",
                        "summary": "queue duplicate cleanup for alpha loops",
                        "name": "alpha-duplicates",
                        "query": "project:alpha status:open",
                        "relationship_kind": "duplicate",
                        "candidate_limit": 3,
                        "item_limit": 25,
                    },
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
                "with the smallest useful operation set. If work requires human judgment about "
                "duplicates or suggestion follow-up, create saved review sessions instead of "
                "pretending that review has already happened. "
                "If clarification answers are missing, do not fabricate them. "
                "Keep summaries practical and concrete."
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
    content, metadata = chat_completion(
        messages,
        settings=settings,
        model=settings.pi_model,
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


def _require_planning_session_row(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    row = repo.get_planning_session(session_id=session_id, conn=conn)
    if row is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return row


def _planning_session_payload(
    row: Mapping[str, Any],
    *,
    execution_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    options = _validate_options(json.loads(str(row.get("options_json") or "{}")))
    workflow = json.loads(str(row.get("plan_json") or "{}"))
    checkpoints = workflow.get("workflow", {}).get("checkpoints") or []
    executed_checkpoint_count = len(execution_rows)
    status: PlanningSessionStatus = "draft"
    if executed_checkpoint_count >= len(checkpoints):
        status = "completed"
    elif executed_checkpoint_count > 0:
        status = "in_progress"

    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "prompt": str(row["prompt"]),
        "query": str(row["query"]) if row.get("query") is not None else None,
        "loop_limit": int(options["loop_limit"]),
        "include_memory_context": bool(options["include_memory_context"]),
        "include_rag_context": bool(options["include_rag_context"]),
        "rag_k": int(options["rag_k"]),
        "rag_scope": options.get("rag_scope"),
        "current_checkpoint_index": int(row.get("current_checkpoint_index") or 0),
        "checkpoint_count": len(checkpoints),
        "executed_checkpoint_count": executed_checkpoint_count,
        "status": status,
        "created_at_utc": str(row["created_at"]),
        "updated_at_utc": str(row["updated_at"]),
    }


def _build_execution_history(
    execution_rows: Sequence[Mapping[str, Any]],
    *,
    checkpoints: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for row in execution_rows:
        payload = json.loads(str(row["result_json"])) if row.get("result_json") else {}
        checkpoint_index = int(row["checkpoint_index"])
        checkpoint_title = ""
        if 0 <= checkpoint_index < len(checkpoints):
            checkpoint_title = str(checkpoints[checkpoint_index].get("title") or "")
        history.append(
            {
                "checkpoint_index": checkpoint_index,
                "checkpoint_title": checkpoint_title,
                "executed_at_utc": str(row["created_at"]),
                "operation_count": len(payload.get("results") or []),
                "results": list(payload.get("results") or []),
            }
        )
    return history


def _build_planning_session_snapshot(
    *,
    session_row: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    execution_rows = repo.list_planning_session_runs(session_id=int(session_row["id"]), conn=conn)
    session = _planning_session_payload(session_row, execution_rows=execution_rows)
    plan_json = json.loads(str(session_row.get("plan_json") or "{}"))
    workflow = dict(plan_json.get("workflow") or {})
    checkpoints = list(workflow.get("checkpoints") or [])
    current_index = int(session["current_checkpoint_index"]) if checkpoints else 0
    current_checkpoint = checkpoints[current_index] if checkpoints else None
    execution_history = _build_execution_history(execution_rows, checkpoints=checkpoints)

    return {
        "session": session,
        "plan_title": str(workflow.get("title") or ""),
        "plan_summary": str(workflow.get("summary") or ""),
        "assumptions": list(workflow.get("assumptions") or []),
        "context_summary": dict(workflow.get("context_summary") or {}),
        "target_loops": list(workflow.get("target_loops") or []),
        "sources": list(workflow.get("sources") or []),
        "checkpoints": checkpoints,
        "current_checkpoint": current_checkpoint,
        "execution_history": execution_history,
    }


def _move_checkpoint_index(
    *,
    current_index: int,
    checkpoint_count: int,
    direction: PlanningMoveDirection,
) -> int:
    if checkpoint_count < 1:
        raise ValidationError("direction", "planning session has no checkpoints")
    target_index = current_index + (1 if direction == "next" else -1)
    if target_index < 0 or target_index >= checkpoint_count:
        raise ValidationError(
            "direction",
            f"no {direction} checkpoint available in this planning session",
        )
    return target_index


def _unique_saved_session_name(
    *,
    base_name: str,
    existing_names: set[str],
) -> str:
    normalized = base_name.strip()
    if not normalized:
        normalized = "planning-session"
    if normalized not in existing_names:
        return normalized
    suffix = 2
    while True:
        candidate = f"{normalized} ({suffix})"
        if candidate not in existing_names:
            return candidate
        suffix += 1


def _snapshot_existing_loops(
    *,
    loop_ids: Sequence[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for loop_id in loop_ids:
        if loop_id in seen_ids:
            continue
        seen_ids.add(loop_id)
        try:
            snapshots.append(read_service.get_loop(loop_id=loop_id, conn=conn))
        except LoopNotFoundError:
            continue
    return snapshots


def _normalize_capture_fields(fields: LoopUpdateRequest | None) -> dict[str, Any] | None:
    if fields is None:
        return None
    payload = fields.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    payload.pop("claim_token", None)
    return payload or None


def _normalize_update_fields(fields: LoopUpdateRequest) -> dict[str, Any]:
    payload = fields.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    payload.pop("claim_token", None)
    if not payload:
        raise ValidationError(
            "fields",
            "planning update_loop operation requires at least one field",
        )
    return payload


def _operation_payload(operation: PlanningOperationModel) -> dict[str, Any]:
    return _OPERATION_ADAPTER.dump_python(operation, mode="json")


def _operation_result_payload(
    *,
    index: int,
    operation: PlanningOperationModel,
    result: dict[str, Any],
    before_loops: list[dict[str, Any]] | None = None,
    after_loops: list[dict[str, Any]] | None = None,
    undoable: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": index,
        "kind": operation.kind,
        "summary": operation.summary,
        "ok": True,
        "operation": _operation_payload(operation),
        "result": result,
        "undoable": undoable,
    }
    if before_loops is not None:
        payload["before_loops"] = before_loops
    if after_loops is not None:
        payload["after_loops"] = after_loops
    return payload


def _execute_plan_operation(
    *,
    operation: PlanningOperationModel,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    if isinstance(operation, CreateLoopOperationModel):
        created = service.capture_loop(
            raw_text=operation.raw_text,
            captured_at_iso=format_utc_datetime(utc_now()),
            client_tz_offset_min=0,
            status=LoopStatus(operation.status),
            capture_fields=_normalize_capture_fields(operation.capture_fields),
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result={"loop": created},
            after_loops=[created],
            undoable=False,
        )

    if isinstance(operation, UpdateLoopOperationModel):
        before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
        updated = service.update_loop(
            loop_id=operation.loop_id,
            fields=_normalize_update_fields(operation.fields),
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result={"loop": updated},
            before_loops=before,
            after_loops=[updated],
            undoable=True,
        )

    if isinstance(operation, TransitionLoopOperationModel):
        before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
        updated = service.transition_status(
            loop_id=operation.loop_id,
            to_status=LoopStatus(operation.status),
            note=operation.note,
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result={"loop": updated},
            before_loops=before,
            after_loops=[updated],
            undoable=True,
        )

    if isinstance(operation, CloseLoopOperationModel):
        before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
        updated = service.transition_status(
            loop_id=operation.loop_id,
            to_status=LoopStatus(operation.status),
            note=operation.note,
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result={"loop": updated},
            before_loops=before,
            after_loops=[updated],
            undoable=True,
        )

    if isinstance(operation, EnrichLoopOperationModel):
        before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
        result = enrichment_orchestration.orchestrate_loop_enrichment(
            loop_id=operation.loop_id,
            conn=conn,
            settings=settings,
        ).to_payload()
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            before_loops=before,
            after_loops=[result["loop"]],
            undoable=False,
        )

    if isinstance(operation, BulkEnrichQueryOperationModel):
        result = enrichment_orchestration.orchestrate_query_bulk_loop_enrichment(
            query=operation.query,
            limit=operation.limit,
            dry_run=False,
            conn=conn,
            settings=settings,
        )
        affected_loop_ids = [
            int(item["loop_id"])
            for item in list(result.get("results") or [])
            if item.get("loop_id") is not None
        ]
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            after_loops=_snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn),
            undoable=False,
        )

    if isinstance(operation, CreateRelationshipReviewSessionOperationModel):
        existing_names = {
            str(session["name"])
            for session in review_workflows.list_relationship_review_sessions(conn=conn)
        }
        session_name = _unique_saved_session_name(
            base_name=operation.name,
            existing_names=existing_names,
        )
        result = review_workflows.create_relationship_review_session(
            name=session_name,
            query=operation.query,
            relationship_kind=operation.relationship_kind,
            candidate_limit=operation.candidate_limit,
            item_limit=operation.item_limit,
            current_loop_id=None,
            conn=conn,
            settings=settings,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            undoable=False,
        )

    if isinstance(operation, CreateEnrichmentReviewSessionOperationModel):
        existing_names = {
            str(session["name"])
            for session in review_workflows.list_enrichment_review_sessions(conn=conn)
        }
        session_name = _unique_saved_session_name(
            base_name=operation.name,
            existing_names=existing_names,
        )
        result = review_workflows.create_enrichment_review_session(
            name=session_name,
            query=operation.query,
            pending_kind=operation.pending_kind,
            suggestion_limit=operation.suggestion_limit,
            clarification_limit=operation.clarification_limit,
            item_limit=operation.item_limit,
            current_loop_id=None,
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            undoable=False,
        )

    raise RuntimeError(f"unsupported planning operation kind: {operation.kind}")


def _next_checkpoint_index(
    *,
    checkpoint_count: int,
    current_index: int,
    executed_indices: set[int],
) -> int:
    for index in range(current_index + 1, checkpoint_count):
        if index not in executed_indices:
            return index
    for index in range(0, checkpoint_count):
        if index not in executed_indices:
            return index
    return max(0, min(current_index, checkpoint_count - 1))


@typingx.validate_io()
def create_planning_session(
    *,
    name: str,
    prompt: str,
    query: str | None,
    loop_limit: int,
    include_memory_context: bool,
    include_rag_context: bool,
    rag_k: int,
    rag_scope: str | None,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    normalized_name = _normalize_name(name, field="name")
    normalized_prompt = _normalize_prompt(prompt)
    normalized_query = _normalize_optional_query(query)
    options = _validate_options(
        {
            "loop_limit": loop_limit,
            "include_memory_context": include_memory_context,
            "include_rag_context": include_rag_context,
            "rag_k": rag_k,
            "rag_scope": rag_scope,
        }
    )
    generated = _generate_workflow_plan(
        prompt=normalized_prompt,
        query=normalized_query,
        options=options,
        conn=conn,
        settings=settings,
    )
    try:
        with conn:
            row = repo.create_planning_session(
                name=normalized_name,
                prompt=normalized_prompt,
                query=normalized_query,
                options_json=options,
                plan_json=generated,
                current_checkpoint_index=0,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name",
            f"planning session '{normalized_name}' already exists",
        ) from None
    return _build_planning_session_snapshot(session_row=row, conn=conn)


@typingx.validate_io()
def list_planning_sessions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for row in repo.list_planning_sessions(conn=conn):
        execution_rows = repo.list_planning_session_runs(session_id=int(row["id"]), conn=conn)
        sessions.append(_planning_session_payload(row, execution_rows=execution_rows))
    return sessions


@typingx.validate_io()
def get_planning_session(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    return _build_planning_session_snapshot(
        session_row=_require_planning_session_row(session_id=session_id, conn=conn),
        conn=conn,
    )


@typingx.validate_io()
def move_planning_session(
    *,
    session_id: int,
    direction: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    session_row = _require_planning_session_row(session_id=session_id, conn=conn)
    plan_json = json.loads(str(session_row.get("plan_json") or "{}"))
    checkpoints = list((plan_json.get("workflow") or {}).get("checkpoints") or [])
    normalized_direction = _validate_move_direction(direction)
    target_index = _move_checkpoint_index(
        current_index=int(session_row.get("current_checkpoint_index") or 0),
        checkpoint_count=len(checkpoints),
        direction=normalized_direction,
    )
    with conn:
        updated = repo.update_planning_session(
            session_id=session_id,
            current_checkpoint_index=target_index,
            conn=conn,
        )
    if updated is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return _build_planning_session_snapshot(session_row=updated, conn=conn)


@typingx.validate_io()
def refresh_planning_session(
    *,
    session_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    session_row = _require_planning_session_row(session_id=session_id, conn=conn)
    options = _validate_options(json.loads(str(session_row.get("options_json") or "{}")))
    generated = _generate_workflow_plan(
        prompt=str(session_row["prompt"]),
        query=str(session_row["query"]) if session_row.get("query") is not None else None,
        options=options,
        conn=conn,
        settings=settings,
    )
    with conn:
        repo.delete_planning_session_runs(session_id=session_id, conn=conn)
        updated = repo.update_planning_session(
            session_id=session_id,
            plan_json=generated,
            current_checkpoint_index=0,
            conn=conn,
        )
    if updated is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return _build_planning_session_snapshot(session_row=updated, conn=conn)


@typingx.validate_io()
def delete_planning_session(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    _require_planning_session_row(session_id=session_id, conn=conn)
    with conn:
        repo.delete_planning_session(session_id=session_id, conn=conn)
    return {"deleted": True, "session_id": session_id}


@typingx.validate_io()
def execute_planning_session_checkpoint(
    *,
    session_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    session_row = _require_planning_session_row(session_id=session_id, conn=conn)
    snapshot = _build_planning_session_snapshot(session_row=session_row, conn=conn)
    session = snapshot["session"]
    checkpoints = snapshot["checkpoints"]
    if not checkpoints:
        raise ValidationError("session_id", "planning session has no checkpoints")

    checkpoint_index = int(session["current_checkpoint_index"])
    executed_indices = {int(entry["checkpoint_index"]) for entry in snapshot["execution_history"]}
    if checkpoint_index in executed_indices:
        raise ValidationError(
            "session_id",
            (
                f"checkpoint {checkpoint_index + 1} has already been executed "
                "for this planning session"
            ),
        )

    raw_checkpoint = checkpoints[checkpoint_index]
    try:
        checkpoint = PlanningCheckpointModel.model_validate(raw_checkpoint)
    except PydanticValidationError as exc:
        raise ValidationError("checkpoint", f"stored checkpoint is invalid: {exc}") from exc

    results: list[dict[str, Any]] = []
    for operation_index, operation in enumerate(checkpoint.operations):
        results.append(
            _execute_plan_operation(
                operation=operation,
                index=operation_index,
                conn=conn,
                settings=settings,
            )
        )

    execution_payload = {
        "session_id": session_id,
        "checkpoint_index": checkpoint_index,
        "checkpoint_title": checkpoint.title,
        "checkpoint_summary": checkpoint.summary,
        "success_criteria": checkpoint.success_criteria,
        "results": results,
    }

    with conn:
        run_row = repo.create_planning_session_run(
            session_id=session_id,
            checkpoint_index=checkpoint_index,
            result_json=execution_payload,
            conn=conn,
        )
        next_index = _next_checkpoint_index(
            checkpoint_count=len(checkpoints),
            current_index=checkpoint_index,
            executed_indices={*executed_indices, checkpoint_index},
        )
        updated = repo.update_planning_session(
            session_id=session_id,
            current_checkpoint_index=next_index,
            conn=conn,
        )

    if updated is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")

    snapshot_after = _build_planning_session_snapshot(session_row=updated, conn=conn)
    execution_payload["executed_at_utc"] = str(run_row["created_at"])
    return {"execution": execution_payload, "snapshot": snapshot_after}
