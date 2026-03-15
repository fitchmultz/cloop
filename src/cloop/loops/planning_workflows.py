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

from pydantic import BaseModel, Field, TypeAdapter, model_validator
from pydantic import ValidationError as PydanticValidationError

from .. import typingx
from ..chat_orchestration import build_memory_context, build_rag_context
from ..llm import chat_completion
from ..schemas.chat import ChatMessage, ChatRequest
from ..schemas.loops import LoopUpdateRequest
from ..settings import Settings
from . import (
    bulk,
    enrichment_orchestration,
    read_service,
    repo,
    review_workflows,
    service,
    template_management,
)
from . import (
    events as loop_events,
)
from . import (
    views as loop_views,
)
from .errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from .models import LoopStatus, format_utc_datetime, parse_utc_datetime, utc_now
from .query import parse_loop_query

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


class QueryBulkUpdateOperationModel(BasePlanningOperationModel):
    kind: Literal["query_bulk_update"] = "query_bulk_update"
    query: str = Field(..., min_length=1, max_length=500)
    fields: LoopUpdateRequest
    limit: int = Field(default=25, ge=1, le=100)


class QueryBulkCloseOperationModel(BasePlanningOperationModel):
    kind: Literal["query_bulk_close"] = "query_bulk_close"
    query: str = Field(..., min_length=1, max_length=500)
    status: Literal["completed", "dropped"] = "completed"
    note: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


class QueryBulkSnoozeOperationModel(BasePlanningOperationModel):
    kind: Literal["query_bulk_snooze"] = "query_bulk_snooze"
    query: str = Field(..., min_length=1, max_length=500)
    snooze_until_utc: str
    limit: int = Field(default=25, ge=1, le=100)


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


class CreateLoopViewOperationModel(BasePlanningOperationModel):
    kind: Literal["create_loop_view"] = "create_loop_view"
    name: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=500)


class UpdateLoopViewOperationModel(BasePlanningOperationModel):
    kind: Literal["update_loop_view"] = "update_loop_view"
    view_id: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_has_changes(self) -> UpdateLoopViewOperationModel:
        if self.name is None and self.query is None and self.description is None:
            raise ValueError("update_loop_view requires at least one changed field")
        return self


class CreateLoopTemplateFromLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["create_loop_template_from_loop"] = "create_loop_template_from_loop"
    loop_id: int
    template_name: str = Field(..., min_length=1, max_length=120)


class UpdateLoopTemplateOperationModel(BasePlanningOperationModel):
    kind: Literal["update_loop_template"] = "update_loop_template"
    template_id: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    raw_text_pattern: str | None = Field(default=None, max_length=4000)
    defaults_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_has_changes(self) -> UpdateLoopTemplateOperationModel:
        if (
            self.name is None
            and self.description is None
            and self.raw_text_pattern is None
            and self.defaults_json is None
        ):
            raise ValueError("update_loop_template requires at least one changed field")
        return self


PlanningOperationModel = Annotated[
    CreateLoopOperationModel
    | UpdateLoopOperationModel
    | TransitionLoopOperationModel
    | CloseLoopOperationModel
    | EnrichLoopOperationModel
    | BulkEnrichQueryOperationModel
    | QueryBulkUpdateOperationModel
    | QueryBulkCloseOperationModel
    | QueryBulkSnoozeOperationModel
    | CreateRelationshipReviewSessionOperationModel
    | CreateEnrichmentReviewSessionOperationModel
    | CreateLoopViewOperationModel
    | UpdateLoopViewOperationModel
    | CreateLoopTemplateFromLoopOperationModel
    | UpdateLoopTemplateOperationModel,
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
                "about duplicates or suggestion follow-up, create saved review sessions instead "
                "of pretending that review has already happened. If clarification answers are "
                "missing, do not fabricate them. Keep summaries practical and concrete."
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


def _require_planning_session_row(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    row = repo.get_planning_session(session_id=session_id, conn=conn)
    if row is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return row


def _next_unexecuted_checkpoint_index(
    *,
    checkpoint_count: int,
    executed_indices: set[int],
) -> int | None:
    for index in range(checkpoint_count):
        if index not in executed_indices:
            return index
    return None


def _collect_resource_ids(
    *,
    results: Sequence[Mapping[str, Any]],
    resource_type: str,
    roles: set[str] | None = None,
) -> list[int]:
    collected: list[int] = []
    seen_ids: set[int] = set()
    for result in results:
        for resource in result.get("resource_refs", []):
            if str(resource.get("resource_type")) != resource_type:
                continue
            if roles is not None and str(resource.get("role")) not in roles:
                continue
            resource_id = resource.get("resource_id")
            if not isinstance(resource_id, int) or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
    return collected


def _build_execution_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    created_loop_ids = _collect_resource_ids(
        results=results,
        resource_type="loop",
        roles={"created"},
    )
    touched_loop_ids = _collect_resource_ids(
        results=results,
        resource_type="loop",
        roles={"created", "updated", "transitioned", "closed", "enriched", "snoozed"},
    )
    created_review_session_ids = _collect_resource_ids(
        results=results,
        resource_type="review_session",
        roles={"created"},
    )
    created_view_ids = _collect_resource_ids(
        results=results,
        resource_type="view",
        roles={"created"},
    )
    updated_view_ids = _collect_resource_ids(
        results=results,
        resource_type="view",
        roles={"updated"},
    )
    created_template_ids = _collect_resource_ids(
        results=results,
        resource_type="template",
        roles={"created"},
    )
    updated_template_ids = _collect_resource_ids(
        results=results,
        resource_type="template",
        roles={"updated"},
    )
    return {
        "operation_kinds": [str(result.get("kind") or "") for result in results],
        "touched_loop_ids": touched_loop_ids,
        "created_loop_ids": created_loop_ids,
        "created_review_session_ids": created_review_session_ids,
        "created_view_ids": created_view_ids,
        "updated_view_ids": updated_view_ids,
        "created_template_ids": created_template_ids,
        "updated_template_ids": updated_template_ids,
        "undoable_operation_count": sum(1 for result in results if result.get("undoable")),
        "rollback_supported_operation_count": sum(
            1 for result in results if result.get("rollback_supported")
        ),
        "follow_up_resource_count": (
            len(created_review_session_ids) + len(created_view_ids) + len(created_template_ids)
        ),
    }


def _planning_session_payload(
    row: Mapping[str, Any],
    *,
    execution_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    options = _validate_options(json.loads(str(row.get("options_json") or "{}")))
    workflow = json.loads(str(row.get("plan_json") or "{}"))
    workflow_payload = dict(workflow.get("workflow") or {})
    checkpoints = list(workflow_payload.get("checkpoints") or [])
    executed_indices = {int(entry["checkpoint_index"]) for entry in execution_rows}
    executed_checkpoint_count = len(executed_indices)
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
        "next_unexecuted_checkpoint_index": _next_unexecuted_checkpoint_index(
            checkpoint_count=len(checkpoints),
            executed_indices=executed_indices,
        ),
        "generated_at_utc": (workflow_payload.get("context_summary") or {}).get("generated_at_utc"),
        "last_executed_at_utc": str(execution_rows[-1]["created_at"]) if execution_rows else None,
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
        results = list(payload.get("results") or [])
        history.append(
            {
                "checkpoint_index": checkpoint_index,
                "checkpoint_title": checkpoint_title,
                "executed_at_utc": str(row["created_at"]),
                "operation_count": len(results),
                "results": results,
                "summary": dict(payload.get("summary") or _build_execution_summary(results)),
            }
        )
    return history


def _build_context_freshness(
    *,
    context_summary: Mapping[str, Any],
    target_loops: Sequence[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    generated_at_utc = context_summary.get("generated_at_utc")
    if not generated_at_utc:
        return {}

    try:
        generated_at = parse_utc_datetime(str(generated_at_utc))
    except ValueError:
        return {"generated_at_utc": generated_at_utc, "is_stale": False}

    target_loop_ids = [int(loop["id"]) for loop in target_loops if loop.get("id") is not None]
    records = repo.read_loops_batch(loop_ids=target_loop_ids, conn=conn)
    stale_target_loop_ids: list[int] = []
    missing_target_loop_ids: list[int] = []
    latest_target_update = None

    for loop_id in target_loop_ids:
        record = records.get(loop_id)
        if record is None:
            missing_target_loop_ids.append(loop_id)
            continue
        if latest_target_update is None or record.updated_at_utc > latest_target_update:
            latest_target_update = record.updated_at_utc
        if record.updated_at_utc > generated_at:
            stale_target_loop_ids.append(loop_id)

    return {
        "generated_at_utc": str(generated_at_utc),
        "target_loop_count": len(target_loop_ids),
        "stale_target_loop_ids": stale_target_loop_ids,
        "stale_target_loop_count": len(stale_target_loop_ids),
        "missing_target_loop_ids": missing_target_loop_ids,
        "latest_target_loop_update_at_utc": (
            format_utc_datetime(latest_target_update) if latest_target_update is not None else None
        ),
        "is_stale": bool(stale_target_loop_ids or missing_target_loop_ids),
    }


def _build_execution_analytics(
    *,
    execution_history: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    executed_checkpoint_indexes = [int(item["checkpoint_index"]) for item in execution_history]
    all_results = [
        result for item in execution_history for result in list(item.get("results") or [])
    ]
    summary = _build_execution_summary(all_results)
    summary.update(
        {
            "executed_checkpoint_indexes": executed_checkpoint_indexes,
            "remaining_checkpoint_indexes": [
                index
                for index in range(len(checkpoints))
                if index not in executed_checkpoint_indexes
            ],
            "last_executed_at_utc": (
                str(execution_history[-1]["executed_at_utc"]) if execution_history else None
            ),
            "total_operations_executed": len(all_results),
            "completed": bool(checkpoints) and len(executed_checkpoint_indexes) >= len(checkpoints),
        }
    )
    return summary


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
    context_summary = dict(workflow.get("context_summary") or {})
    target_loops = list(workflow.get("target_loops") or [])

    return {
        "session": session,
        "plan_title": str(workflow.get("title") or ""),
        "plan_summary": str(workflow.get("summary") or ""),
        "assumptions": list(workflow.get("assumptions") or []),
        "context_summary": context_summary,
        "context_freshness": _build_context_freshness(
            context_summary=context_summary,
            target_loops=target_loops,
            conn=conn,
        ),
        "execution_analytics": _build_execution_analytics(
            execution_history=execution_history,
            checkpoints=checkpoints,
        ),
        "target_loops": target_loops,
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


def _resource_label(resource: Mapping[str, Any]) -> str | None:
    title = resource.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    raw_text = resource.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        return raw_text.strip()[:120]
    name = resource.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _resource_ref(
    *,
    resource_type: str,
    resource_id: int,
    role: str,
    label: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "role": role,
    }
    if label is not None:
        payload["label"] = label
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def _rollback_action(
    *,
    kind: str,
    resource_type: str,
    resource_id: int,
    summary: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "kind": kind,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "summary": summary,
    }
    if payload:
        action["payload"] = dict(payload)
    return action


def _loop_undo_action(*, loop_id: int, summary: str) -> dict[str, Any]:
    return _rollback_action(
        kind="loop.undo",
        resource_type="loop",
        resource_id=loop_id,
        summary=summary,
        payload={"loop_id": loop_id},
    )


def _template_row_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    defaults_json = payload.get("defaults_json")
    if isinstance(defaults_json, str):
        payload["defaults_json"] = json.loads(defaults_json) if defaults_json else {}
    return payload


def _operation_result_payload(
    *,
    index: int,
    operation: PlanningOperationModel,
    result: Mapping[str, Any],
    before_loops: Sequence[Mapping[str, Any]] | None = None,
    after_loops: Sequence[Mapping[str, Any]] | None = None,
    resource_refs: Sequence[Mapping[str, Any]] | None = None,
    rollback_actions: Sequence[Mapping[str, Any]] | None = None,
    provenance: Mapping[str, Any] | None = None,
    undoable: bool | None = None,
) -> dict[str, Any]:
    normalized_rollback_actions = [dict(action) for action in rollback_actions or []]
    payload: dict[str, Any] = {
        "index": index,
        "kind": operation.kind,
        "summary": operation.summary,
        "ok": True,
        "operation": _operation_payload(operation),
        "result": dict(result),
        "undoable": (
            bool(undoable)
            if undoable is not None
            else any(action.get("kind") == "loop.undo" for action in normalized_rollback_actions)
        ),
        "rollback_supported": bool(normalized_rollback_actions),
        "resource_refs": [dict(resource) for resource in resource_refs or []],
        "rollback_actions": normalized_rollback_actions,
        "provenance": dict(provenance or {}),
    }
    if before_loops is not None:
        payload["before_loops"] = [dict(loop) for loop in before_loops]
    if after_loops is not None:
        payload["after_loops"] = [dict(loop) for loop in after_loops]
    return payload


def _execute_rollback_action(*, action: Mapping[str, Any], conn: sqlite3.Connection) -> None:
    kind = str(action.get("kind") or "")
    resource_id = int(action["resource_id"])
    payload = dict(action.get("payload") or {})

    if kind == "loop.undo":
        loop_events.undo_last_event(loop_id=resource_id, conn=conn)
        return
    if kind == "planning.loop.delete":
        if not repo.delete_loop(loop_id=resource_id, conn=conn):
            raise ResourceNotFoundError("loop", f"Loop not found for rollback: {resource_id}")
        return
    if kind in {"review.relationship.session.delete", "review.enrichment.session.delete"}:
        if not repo.delete_review_session(session_id=resource_id, conn=conn):
            raise ResourceNotFoundError(
                "review session", f"Review session not found for rollback: {resource_id}"
            )
        return
    if kind == "loop.view.delete":
        if not repo.delete_loop_view(view_id=resource_id, conn=conn):
            raise ResourceNotFoundError("view", f"Saved view not found for rollback: {resource_id}")
        return
    if kind == "loop.view.update":
        repo.update_loop_view(
            view_id=resource_id,
            name=payload.get("name"),
            query=payload.get("query"),
            description=payload.get("description"),
            conn=conn,
        )
        return
    if kind == "loop.template.delete":
        if not repo.delete_loop_template(template_id=resource_id, conn=conn):
            raise ResourceNotFoundError(
                "template", f"Loop template not found for rollback: {resource_id}"
            )
        return
    if kind == "loop.template.update":
        repo.update_loop_template(
            template_id=resource_id,
            name=payload.get("name"),
            description=payload.get("description"),
            raw_text_pattern=payload.get("raw_text_pattern"),
            defaults_json=payload.get("defaults_json"),
            conn=conn,
        )
        return

    raise RuntimeError(f"unsupported planning rollback action: {kind}")


def _rollback_execution_results(
    *,
    results: Sequence[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    attempted = 0
    failed_actions: list[dict[str, Any]] = []
    for result in reversed(results):
        for action in reversed(list(result.get("rollback_actions") or [])):
            attempted += 1
            try:
                _execute_rollback_action(action=action, conn=conn)
            except Exception as exc:  # noqa: BLE001
                failed_actions.append(
                    {
                        "kind": action.get("kind"),
                        "resource_type": action.get("resource_type"),
                        "resource_id": action.get("resource_id"),
                        "message": str(exc),
                    }
                )
    return {
        "attempted_action_count": attempted,
        "failed_action_count": len(failed_actions),
        "failed_actions": failed_actions,
        "rollback_complete": len(failed_actions) == 0,
    }


def _validate_operation_for_execution(
    *,
    operation: PlanningOperationModel,
    conn: sqlite3.Connection,
) -> None:
    if isinstance(operation, CreateLoopOperationModel):
        _normalize_capture_fields(operation.capture_fields)
        return
    if isinstance(operation, UpdateLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        _normalize_update_fields(operation.fields)
        return
    if isinstance(operation, TransitionLoopOperationModel | CloseLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        return
    if isinstance(operation, EnrichLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        return
    if isinstance(
        operation,
        BulkEnrichQueryOperationModel
        | QueryBulkUpdateOperationModel
        | QueryBulkCloseOperationModel
        | QueryBulkSnoozeOperationModel,
    ):
        parse_loop_query(operation.query)
        if isinstance(operation, QueryBulkUpdateOperationModel):
            _normalize_update_fields(operation.fields)
        return
    if isinstance(
        operation,
        CreateRelationshipReviewSessionOperationModel
        | CreateEnrichmentReviewSessionOperationModel
        | CreateLoopViewOperationModel,
    ):
        parse_loop_query(operation.query)
        return
    if isinstance(operation, UpdateLoopViewOperationModel):
        if repo.get_loop_view(view_id=operation.view_id, conn=conn) is None:
            raise ValidationError("view_id", f"view {operation.view_id} not found")
        if operation.query is not None:
            parse_loop_query(operation.query)
        return
    if isinstance(operation, CreateLoopTemplateFromLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        return
    if isinstance(operation, UpdateLoopTemplateOperationModel):
        template = repo.get_loop_template(template_id=operation.template_id, conn=conn)
        if template is None:
            raise ValidationError("template_id", f"template {operation.template_id} not found")
        if bool(template.get("is_system")):
            raise ValidationError("template_id", "system templates cannot be modified")
        return

    raise RuntimeError(f"unsupported planning operation kind: {operation.kind}")


def _validate_checkpoint_for_execution(
    *,
    checkpoint: PlanningCheckpointModel,
    conn: sqlite3.Connection,
) -> None:
    rollback_unsupported_seen = False
    for operation in checkpoint.operations:
        _validate_operation_for_execution(operation=operation, conn=conn)
        if operation.kind in {"enrich_loop", "bulk_enrich_query"}:
            rollback_unsupported_seen = True
            continue
        if rollback_unsupported_seen:
            raise ValidationError(
                "checkpoint",
                "non-rollback planning operations must be the final operations in a checkpoint",
            )


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
        created_loop_id = int(created["id"])
        return _operation_result_payload(
            index=index,
            operation=operation,
            result={"loop": created},
            after_loops=[created],
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=created_loop_id,
                    role="created",
                    label=_resource_label(created),
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="planning.loop.delete",
                    resource_type="loop",
                    resource_id=created_loop_id,
                    summary=f"Delete loop {created_loop_id} created by this checkpoint",
                )
            ],
            provenance={
                "status": operation.status,
                "capture_fields": _normalize_capture_fields(operation.capture_fields) or {},
            },
            undoable=False,
        )

    if isinstance(operation, UpdateLoopOperationModel):
        before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
        fields = _normalize_update_fields(operation.fields)
        updated = service.update_loop(
            loop_id=operation.loop_id,
            fields=fields,
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result={"loop": updated},
            before_loops=before,
            after_loops=[updated],
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=operation.loop_id,
                    role="updated",
                    label=_resource_label(updated),
                )
            ],
            rollback_actions=[
                _loop_undo_action(
                    loop_id=operation.loop_id,
                    summary=f"Undo loop update for loop {operation.loop_id}",
                )
            ],
            provenance={"loop_ids": [operation.loop_id], "fields": sorted(fields.keys())},
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
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=operation.loop_id,
                    role="transitioned",
                    label=_resource_label(updated),
                    metadata={"status": operation.status},
                )
            ],
            rollback_actions=[
                _loop_undo_action(
                    loop_id=operation.loop_id,
                    summary=f"Undo loop status transition for loop {operation.loop_id}",
                )
            ],
            provenance={
                "loop_ids": [operation.loop_id],
                "to_status": operation.status,
                "note": operation.note,
            },
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
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=operation.loop_id,
                    role="closed",
                    label=_resource_label(updated),
                    metadata={"status": operation.status},
                )
            ],
            rollback_actions=[
                _loop_undo_action(
                    loop_id=operation.loop_id,
                    summary=f"Undo loop close for loop {operation.loop_id}",
                )
            ],
            provenance={
                "loop_ids": [operation.loop_id],
                "status": operation.status,
                "note": operation.note,
            },
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
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=operation.loop_id,
                    role="enriched",
                    label=_resource_label(result["loop"]),
                    metadata={"suggestion_id": result["suggestion_id"]},
                )
            ],
            provenance={
                "loop_ids": [operation.loop_id],
                "suggestion_id": result["suggestion_id"],
                "applied_fields": list(result.get("applied_fields") or []),
                "needs_clarification": list(result.get("needs_clarification") or []),
            },
            undoable=False,
        )

    if isinstance(operation, BulkEnrichQueryOperationModel):
        preview = enrichment_orchestration.preview_query_loop_enrichment_targets(
            query=operation.query,
            limit=operation.limit,
            conn=conn,
        )
        before_loops = list(preview.get("targets") or [])
        result = enrichment_orchestration.orchestrate_query_bulk_loop_enrichment(
            query=operation.query,
            limit=operation.limit,
            dry_run=False,
            conn=conn,
            settings=settings,
        )
        affected_loop_ids = [int(target["id"]) for target in before_loops]
        after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            before_loops=before_loops,
            after_loops=after_loops,
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=loop_id,
                    role="enriched",
                )
                for loop_id in affected_loop_ids
            ],
            provenance={
                "query": operation.query,
                "matched_count": int(result.get("matched_count") or 0),
                "limited": bool(result.get("limited", False)),
                "matched_loop_ids": affected_loop_ids,
            },
            undoable=False,
        )

    if isinstance(operation, QueryBulkUpdateOperationModel):
        fields = _normalize_update_fields(operation.fields)
        preview = bulk.query_bulk_update_loops(
            query=operation.query,
            fields=fields,
            transactional=True,
            dry_run=True,
            limit=operation.limit,
            conn=conn,
        )
        before_loops = list(preview.get("targets") or [])
        result = bulk.query_bulk_update_loops(
            query=operation.query,
            fields=fields,
            transactional=True,
            dry_run=False,
            limit=operation.limit,
            conn=conn,
        )
        affected_loop_ids = [int(target["id"]) for target in before_loops]
        after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            before_loops=before_loops,
            after_loops=after_loops,
            resource_refs=[
                _resource_ref(resource_type="loop", resource_id=loop_id, role="updated")
                for loop_id in affected_loop_ids
            ],
            rollback_actions=[
                _loop_undo_action(
                    loop_id=int(item["loop_id"]),
                    summary=f"Undo query bulk update for loop {int(item['loop_id'])}",
                )
                for item in list(result.get("results") or [])
                if item.get("ok") and item.get("loop_id") is not None
            ],
            provenance={
                "query": operation.query,
                "matched_count": int(result.get("matched_count") or 0),
                "limited": bool(result.get("limited", False)),
                "matched_loop_ids": affected_loop_ids,
                "fields": sorted(fields.keys()),
            },
            undoable=bool(affected_loop_ids),
        )

    if isinstance(operation, QueryBulkCloseOperationModel):
        preview = bulk.query_bulk_close_loops(
            query=operation.query,
            status=operation.status,
            note=operation.note,
            transactional=True,
            dry_run=True,
            limit=operation.limit,
            conn=conn,
        )
        before_loops = list(preview.get("targets") or [])
        result = bulk.query_bulk_close_loops(
            query=operation.query,
            status=operation.status,
            note=operation.note,
            transactional=True,
            dry_run=False,
            limit=operation.limit,
            conn=conn,
        )
        affected_loop_ids = [int(target["id"]) for target in before_loops]
        after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            before_loops=before_loops,
            after_loops=after_loops,
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=loop_id,
                    role="closed",
                    metadata={"status": operation.status},
                )
                for loop_id in affected_loop_ids
            ],
            rollback_actions=[
                _loop_undo_action(
                    loop_id=int(item["loop_id"]),
                    summary=f"Undo query bulk close for loop {int(item['loop_id'])}",
                )
                for item in list(result.get("results") or [])
                if item.get("ok") and item.get("loop_id") is not None
            ],
            provenance={
                "query": operation.query,
                "matched_count": int(result.get("matched_count") or 0),
                "limited": bool(result.get("limited", False)),
                "matched_loop_ids": affected_loop_ids,
                "status": operation.status,
                "note": operation.note,
            },
            undoable=bool(affected_loop_ids),
        )

    if isinstance(operation, QueryBulkSnoozeOperationModel):
        preview = bulk.query_bulk_snooze_loops(
            query=operation.query,
            snooze_until_utc=operation.snooze_until_utc,
            transactional=True,
            dry_run=True,
            limit=operation.limit,
            conn=conn,
        )
        before_loops = list(preview.get("targets") or [])
        result = bulk.query_bulk_snooze_loops(
            query=operation.query,
            snooze_until_utc=operation.snooze_until_utc,
            transactional=True,
            dry_run=False,
            limit=operation.limit,
            conn=conn,
        )
        affected_loop_ids = [int(target["id"]) for target in before_loops]
        after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            before_loops=before_loops,
            after_loops=after_loops,
            resource_refs=[
                _resource_ref(
                    resource_type="loop",
                    resource_id=loop_id,
                    role="snoozed",
                    metadata={"snooze_until_utc": operation.snooze_until_utc},
                )
                for loop_id in affected_loop_ids
            ],
            rollback_actions=[
                _loop_undo_action(
                    loop_id=int(item["loop_id"]),
                    summary=f"Undo query bulk snooze for loop {int(item['loop_id'])}",
                )
                for item in list(result.get("results") or [])
                if item.get("ok") and item.get("loop_id") is not None
            ],
            provenance={
                "query": operation.query,
                "matched_count": int(result.get("matched_count") or 0),
                "limited": bool(result.get("limited", False)),
                "matched_loop_ids": affected_loop_ids,
                "snooze_until_utc": operation.snooze_until_utc,
            },
            undoable=bool(affected_loop_ids),
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
        session_id = int(result["session"]["id"])
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            resource_refs=[
                _resource_ref(
                    resource_type="review_session",
                    resource_id=session_id,
                    role="created",
                    label=str(result["session"]["name"]),
                    metadata={"review_kind": "relationship"},
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="review.relationship.session.delete",
                    resource_type="review_session",
                    resource_id=session_id,
                    summary=f"Delete relationship review session {session_id}",
                )
            ],
            provenance={
                "review_kind": "relationship",
                "query": operation.query,
                "loop_count": int(result.get("loop_count") or 0),
            },
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
        session_id = int(result["session"]["id"])
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            resource_refs=[
                _resource_ref(
                    resource_type="review_session",
                    resource_id=session_id,
                    role="created",
                    label=str(result["session"]["name"]),
                    metadata={"review_kind": "enrichment"},
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="review.enrichment.session.delete",
                    resource_type="review_session",
                    resource_id=session_id,
                    summary=f"Delete enrichment review session {session_id}",
                )
            ],
            provenance={
                "review_kind": "enrichment",
                "query": operation.query,
                "loop_count": int(result.get("loop_count") or 0),
            },
            undoable=False,
        )

    if isinstance(operation, CreateLoopViewOperationModel):
        existing_names = {str(view["name"]) for view in loop_views.list_loop_views(conn=conn)}
        view_name = _unique_saved_session_name(
            base_name=operation.name, existing_names=existing_names
        )
        result = loop_views.create_loop_view(
            name=view_name,
            query=operation.query,
            description=operation.description,
            conn=conn,
        )
        view_id = int(result["id"])
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            resource_refs=[
                _resource_ref(
                    resource_type="view",
                    resource_id=view_id,
                    role="created",
                    label=str(result["name"]),
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="loop.view.delete",
                    resource_type="view",
                    resource_id=view_id,
                    summary=f"Delete saved view {view_id}",
                )
            ],
            provenance={"query": operation.query},
            undoable=False,
        )

    if isinstance(operation, UpdateLoopViewOperationModel):
        before_view = repo.get_loop_view(view_id=operation.view_id, conn=conn)
        if before_view is None:
            raise ValidationError("view_id", f"view {operation.view_id} not found")
        result = loop_views.update_loop_view(
            view_id=operation.view_id,
            name=operation.name,
            query=operation.query,
            description=operation.description,
            conn=conn,
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            resource_refs=[
                _resource_ref(
                    resource_type="view",
                    resource_id=operation.view_id,
                    role="updated",
                    label=str(result["name"]),
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="loop.view.update",
                    resource_type="view",
                    resource_id=operation.view_id,
                    summary=f"Restore saved view {operation.view_id} to its previous definition",
                    payload={
                        "name": before_view.get("name"),
                        "query": before_view.get("query"),
                        "description": before_view.get("description"),
                    },
                )
            ],
            provenance={"view_id": operation.view_id, "before": dict(before_view)},
            undoable=False,
        )

    if isinstance(operation, CreateLoopTemplateFromLoopOperationModel):
        existing_names = {
            str(_template_row_payload(template)["name"])
            for template in repo.list_loop_templates(conn=conn)
        }
        template_name = _unique_saved_session_name(
            base_name=operation.template_name,
            existing_names=existing_names,
        )
        result = _template_row_payload(
            template_management.create_template_from_loop(
                loop_id=operation.loop_id,
                template_name=template_name,
                conn=conn,
            )
        )
        template_id = int(result["id"])
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            resource_refs=[
                _resource_ref(
                    resource_type="template",
                    resource_id=template_id,
                    role="created",
                    label=str(result["name"]),
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="loop.template.delete",
                    resource_type="template",
                    resource_id=template_id,
                    summary=f"Delete loop template {template_id}",
                )
            ],
            provenance={"source_loop_id": operation.loop_id},
            undoable=False,
        )

    if isinstance(operation, UpdateLoopTemplateOperationModel):
        before_template_row = repo.get_loop_template(template_id=operation.template_id, conn=conn)
        if before_template_row is None:
            raise ValidationError("template_id", f"template {operation.template_id} not found")
        before_template = _template_row_payload(before_template_row)
        result = _template_row_payload(
            template_management.update_loop_template(
                template_id=operation.template_id,
                name=operation.name,
                description=operation.description,
                raw_text_pattern=operation.raw_text_pattern,
                defaults_json=operation.defaults_json,
                conn=conn,
            )
        )
        return _operation_result_payload(
            index=index,
            operation=operation,
            result=result,
            resource_refs=[
                _resource_ref(
                    resource_type="template",
                    resource_id=operation.template_id,
                    role="updated",
                    label=str(result["name"]),
                )
            ],
            rollback_actions=[
                _rollback_action(
                    kind="loop.template.update",
                    resource_type="template",
                    resource_id=operation.template_id,
                    summary=(
                        f"Restore loop template {operation.template_id} to its previous definition"
                    ),
                    payload={
                        "name": before_template.get("name"),
                        "description": before_template.get("description"),
                        "raw_text_pattern": before_template.get("raw_text_pattern"),
                        "defaults_json": before_template.get("defaults_json"),
                    },
                )
            ],
            provenance={"template_id": operation.template_id, "before": before_template},
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

    _validate_checkpoint_for_execution(checkpoint=checkpoint, conn=conn)

    results: list[dict[str, Any]] = []
    try:
        for operation_index, operation in enumerate(checkpoint.operations):
            results.append(
                _execute_plan_operation(
                    operation=operation,
                    index=operation_index,
                    conn=conn,
                    settings=settings,
                )
            )
    except Exception as exc:  # noqa: BLE001
        rollback_summary = _rollback_execution_results(results=results, conn=conn)
        rollback_note = (
            "rollback completed"
            if rollback_summary["rollback_complete"]
            else (
                "rollback incomplete: "
                f"{rollback_summary['failed_action_count']} rollback actions failed"
            )
        )
        raise ValidationError(
            "checkpoint",
            (
                f"checkpoint execution failed after {len(results)} successful operations: {exc}; "
                f"{rollback_note}"
            ),
        ) from exc

    execution_payload = {
        "session_id": session_id,
        "checkpoint_index": checkpoint_index,
        "checkpoint_title": checkpoint.title,
        "checkpoint_summary": checkpoint.summary,
        "success_criteria": checkpoint.success_criteria,
        "results": results,
        "summary": _build_execution_summary(results),
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
