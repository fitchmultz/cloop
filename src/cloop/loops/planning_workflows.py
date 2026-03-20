"""Shared AI-native planning workflows.

Purpose:
    Re-export the feature-owned planning workflow modules behind the
    canonical `cloop.loops.planning_workflows` import surface.

Responsibilities:
    - Preserve one stable planning workflow namespace for transports and tests
    - Inject facade-level planner dependencies used by existing monkeypatch paths
    - Keep planning models, helpers, and public service operations discoverable

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Public planning workflow facade only
    - No inline persistence, planner prompting, or checkpoint execution logic

Usage:
    Import from `cloop.loops.planning_workflows` for shared planning session
    orchestration across CLI, HTTP, MCP, tests, and the web UI.

Invariants/Assumptions:
    - Public callers keep using this module instead of the internal package
    - `chat_completion` remains patchable at this facade for tests
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import typingx
from ..llm import chat_completion
from ..settings import Settings
from . import views as loop_views
from ._planning_workflows.execution import (
    _execute_plan_operation,
    _execute_rollback_action,
    _loop_undo_action,
    _normalize_capture_fields,
    _normalize_update_fields,
    _operation_payload,
    _operation_result_payload,
    _resource_label,
    _resource_ref,
    _rollback_action,
    _rollback_execution_results,
    _template_row_payload,
    _validate_checkpoint_for_execution,
    _validate_operation_for_execution,
)
from ._planning_workflows.generation import (
    _build_planner_messages,
    _build_planner_rag_context,
    _checkpoint_focus_loop_ids,
    _compact_loop_payload,
    _default_target_loops,
    _generate_workflow_plan,
    _planner_schema_description,
    _resolve_target_loops,
)
from ._planning_workflows.inputs import (
    _extract_json_object,
    _normalize_name,
    _normalize_optional_query,
    _normalize_prompt,
    _validate_move_direction,
    _validate_options,
)
from ._planning_workflows.models import (
    _DEFAULT_PLANNING_OPTIONS,
    _MAX_PLANNING_CHECKPOINTS,
    _MAX_PLANNING_OPERATIONS_PER_CHECKPOINT,
    _MAX_PLANNING_TARGETS,
    _OPERATION_ADAPTER,
    BasePlanningOperationModel,
    BulkEnrichQueryOperationModel,
    CloseLoopOperationModel,
    CreateEnrichmentReviewSessionOperationModel,
    CreateLoopOperationModel,
    CreateLoopTemplateFromLoopOperationModel,
    CreateLoopViewOperationModel,
    CreateRelationshipReviewSessionOperationModel,
    EnrichLoopOperationModel,
    GeneratedPlanningWorkflowModel,
    PlanningCheckpointModel,
    PlanningMoveDirection,
    PlanningOperationModel,
    PlanningSessionOptionsModel,
    PlanningSessionStatus,
    QueryBulkCloseOperationModel,
    QueryBulkSnoozeOperationModel,
    QueryBulkUpdateOperationModel,
    TransitionLoopOperationModel,
    UpdateLoopOperationModel,
    UpdateLoopTemplateOperationModel,
    UpdateLoopViewOperationModel,
)
from ._planning_workflows.service import (
    create_planning_session_impl,
    delete_planning_session,
    execute_planning_session_checkpoint,
    get_planning_session,
    list_planning_sessions,
    move_planning_session,
    refresh_planning_session_impl,
    rollback_planning_session_run,
)
from ._planning_workflows.snapshot import (
    _build_context_freshness,
    _build_execution_analytics,
    _build_execution_history,
    _build_execution_summary,
    _build_follow_up_resources,
    _build_launch_surfaces,
    _build_planning_session_snapshot,
    _build_rollback_cues,
    _collect_resource_ids,
    _move_checkpoint_index,
    _next_checkpoint_index,
    _next_unexecuted_checkpoint_index,
    _planning_session_payload,
    _require_planning_session_row,
    _snapshot_existing_loops,
    _unique_saved_session_name,
)


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
    return create_planning_session_impl(
        name=name,
        prompt=prompt,
        query=query,
        loop_limit=loop_limit,
        include_memory_context=include_memory_context,
        include_rag_context=include_rag_context,
        rag_k=rag_k,
        rag_scope=rag_scope,
        conn=conn,
        settings=settings,
        planner_chat_completion=chat_completion,
    )


@typingx.validate_io()
def refresh_planning_session(
    *,
    session_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    return refresh_planning_session_impl(
        session_id=session_id,
        conn=conn,
        settings=settings,
        planner_chat_completion=chat_completion,
    )


__all__ = [
    "chat_completion",
    "loop_views",
    "PlanningSessionStatus",
    "PlanningMoveDirection",
    "_MAX_PLANNING_TARGETS",
    "_MAX_PLANNING_CHECKPOINTS",
    "_MAX_PLANNING_OPERATIONS_PER_CHECKPOINT",
    "_DEFAULT_PLANNING_OPTIONS",
    "PlanningSessionOptionsModel",
    "BasePlanningOperationModel",
    "CreateLoopOperationModel",
    "UpdateLoopOperationModel",
    "TransitionLoopOperationModel",
    "CloseLoopOperationModel",
    "EnrichLoopOperationModel",
    "BulkEnrichQueryOperationModel",
    "QueryBulkUpdateOperationModel",
    "QueryBulkCloseOperationModel",
    "QueryBulkSnoozeOperationModel",
    "CreateRelationshipReviewSessionOperationModel",
    "CreateEnrichmentReviewSessionOperationModel",
    "CreateLoopViewOperationModel",
    "UpdateLoopViewOperationModel",
    "CreateLoopTemplateFromLoopOperationModel",
    "UpdateLoopTemplateOperationModel",
    "PlanningOperationModel",
    "PlanningCheckpointModel",
    "GeneratedPlanningWorkflowModel",
    "_OPERATION_ADAPTER",
    "_normalize_name",
    "_normalize_prompt",
    "_normalize_optional_query",
    "_validate_move_direction",
    "_validate_options",
    "_extract_json_object",
    "_compact_loop_payload",
    "_default_target_loops",
    "_resolve_target_loops",
    "_build_planner_rag_context",
    "_planner_schema_description",
    "_build_planner_messages",
    "_generate_workflow_plan",
    "_checkpoint_focus_loop_ids",
    "_require_planning_session_row",
    "_next_unexecuted_checkpoint_index",
    "_collect_resource_ids",
    "_build_execution_summary",
    "_build_follow_up_resources",
    "_build_launch_surfaces",
    "_build_rollback_cues",
    "_planning_session_payload",
    "_build_execution_history",
    "_build_context_freshness",
    "_build_execution_analytics",
    "_build_planning_session_snapshot",
    "_move_checkpoint_index",
    "_unique_saved_session_name",
    "_snapshot_existing_loops",
    "_next_checkpoint_index",
    "_normalize_capture_fields",
    "_normalize_update_fields",
    "_operation_payload",
    "_resource_label",
    "_resource_ref",
    "_rollback_action",
    "_loop_undo_action",
    "_template_row_payload",
    "_operation_result_payload",
    "_execute_rollback_action",
    "_rollback_execution_results",
    "_validate_operation_for_execution",
    "_validate_checkpoint_for_execution",
    "_execute_plan_operation",
    "create_planning_session",
    "list_planning_sessions",
    "get_planning_session",
    "move_planning_session",
    "refresh_planning_session",
    "delete_planning_session",
    "execute_planning_session_checkpoint",
    "rollback_planning_session_run",
]
