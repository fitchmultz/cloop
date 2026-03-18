"""Planning-workflow schemas for loops.

Purpose:
    Define AI-native planning session, checkpoint, execution-history, and
    operator-handoff payloads.

Responsibilities:
    - Validate planning-session creation payloads
    - Shape checkpoint, snapshot, and execution-history responses
    - Model follow-up resources, launch surfaces, rollback cues, and continuity
      summaries for planning execution handoff
    - Keep planning contracts isolated from other review workflows

Scope:
    - Planning request/response payloads shared by HTTP, CLI, MCP, and web
    - No transport-local rendering or persistence logic

Usage:
    - Imported via `cloop.schemas.loops` for planning-session routes and shared
      response builders

Invariants/Assumptions:
    - Execution-history items remain JSON-serializable and transport-agnostic
    - Handoff metadata fields reflect the shared planning execution contract

Non-scope:
    - Planning orchestration or checkpoint execution logic
    - Relationship/enrichment review session schemas
    - Core loop CRUD/search models
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from ._shared import RAW_TEXT_MAX, SEARCH_QUERY_MAX, VIEW_NAME_MAX, BaseModel, Field
from .core import LoopResponse

PlanningSessionStatus = Literal["draft", "in_progress", "completed"]


class PlanningSessionCreateRequest(BaseModel):
    """Create an AI-native planning session."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    prompt: str = Field(..., min_length=1, max_length=RAW_TEXT_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    loop_limit: int = Field(default=10, ge=1, le=25)
    include_memory_context: bool = True
    include_rag_context: bool = False
    rag_k: int = Field(default=5, ge=1, le=20)
    rag_scope: str | None = Field(default=None, max_length=SEARCH_QUERY_MAX)


class PlanningSessionResponse(BaseModel):
    """Planning session metadata."""

    id: int
    name: str
    prompt: str
    query: str | None = None
    loop_limit: int
    include_memory_context: bool
    include_rag_context: bool
    rag_k: int
    rag_scope: str | None = None
    current_checkpoint_index: int
    checkpoint_count: int
    executed_checkpoint_count: int
    next_unexecuted_checkpoint_index: int | None = None
    generated_at_utc: str | None = None
    last_executed_at_utc: str | None = None
    status: PlanningSessionStatus
    created_at_utc: str
    updated_at_utc: str


class PlanningTargetLoopResponse(BaseModel):
    """Compact loop snapshot included in planning context."""

    id: int
    title: str | None = None
    raw_text: str
    summary: str | None = None
    next_action: str | None = None
    status: str
    due_date: str | None = None
    due_at_utc: str | None = None
    updated_at_utc: str | None = None
    project: str | None = None
    tags: List[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    enrichment_state: str | None = None


class PlanningCheckpointResponse(BaseModel):
    """One planning checkpoint."""

    title: str
    summary: str
    success_criteria: str
    focus_loop_ids: List[int] = Field(default_factory=list)
    operations: List[Dict[str, Any]] = Field(default_factory=list)


class PlanningCheckpointExecutionResultResponse(BaseModel):
    """One operation result from executing a planning checkpoint."""

    index: int
    kind: str
    summary: str
    ok: bool
    operation: Dict[str, Any]
    result: Dict[str, Any] | None = None
    before_loops: List[LoopResponse] = Field(default_factory=list)
    after_loops: List[LoopResponse] = Field(default_factory=list)
    undoable: bool = False
    rollback_supported: bool = False
    resource_refs: List[Dict[str, Any]] = Field(default_factory=list)
    rollback_actions: List[Dict[str, Any]] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class PlanningExecutionLaunchSurfaceResponse(BaseModel):
    """Transport-ready affordance for opening the next operator surface."""

    surface: str
    label: str
    resource_type: str
    resource_id: int
    reason: str | None = None
    http: Dict[str, Any] = Field(default_factory=dict)
    mcp: Dict[str, Any] = Field(default_factory=dict)
    web: Dict[str, Any] = Field(default_factory=dict)


class PlanningExecutionFollowUpResourceResponse(BaseModel):
    """Created or updated follow-up resource emitted by checkpoint execution."""

    resource_type: str
    resource_id: int
    role: str
    label: str | None = None
    operation_index: int
    operation_kind: str
    operation_summary: str
    details: Dict[str, Any] = Field(default_factory=dict)
    launch_surface: PlanningExecutionLaunchSurfaceResponse | None = None


class PlanningExecutionRollbackCueOperationResponse(BaseModel):
    """Rollback/undo cue for one executed operation."""

    index: int
    kind: str
    summary: str
    undoable: bool = False
    rollback_supported: bool = False
    rollback_action_count: int = 0


class PlanningExecutionRollbackCueResponse(BaseModel):
    """Aggregate rollback/undo cues for one executed checkpoint."""

    rollback_supported_operation_count: int = 0
    undoable_operation_count: int = 0
    rollback_action_count: int = 0
    operations: List[PlanningExecutionRollbackCueOperationResponse] = Field(default_factory=list)


class PlanningContextFreshnessTargetChangeResponse(BaseModel):
    """One target loop that changed after the plan was generated."""

    loop_id: int
    label: str
    changed_fields: List[str] = Field(default_factory=list)
    previous_updated_at_utc: str | None = None
    current_updated_at_utc: str | None = None


class PlanningContextFreshnessResponse(BaseModel):
    """Deterministic freshness summary for a planning session's target loops."""

    generated_at_utc: str | None = None
    target_loop_count: int = 0
    stale_target_loop_ids: List[int] = Field(default_factory=list)
    stale_target_loop_count: int = 0
    missing_target_loop_ids: List[int] = Field(default_factory=list)
    missing_target_loop_count: int = 0
    latest_target_loop_update_at_utc: str | None = None
    changed_targets: List[PlanningContextFreshnessTargetChangeResponse] = Field(
        default_factory=list
    )
    changed_field_counts: Dict[str, int] = Field(default_factory=dict)
    status_changed_count: int = 0
    next_action_changed_count: int = 0
    summary_label: str | None = None
    is_stale: bool = False


class PlanningResourceChangeGroupResponse(BaseModel):
    """Grouped deterministic resource changes emitted by planning execution."""

    resource_type: str
    resource_type_label: str
    role: str
    role_label: str
    display_label: str
    count: int
    resource_ids: List[int] = Field(default_factory=list)
    preview_labels: List[str] = Field(default_factory=list)
    operation_indexes: List[int] = Field(default_factory=list)
    operation_summaries: List[str] = Field(default_factory=list)


class PlanningResourceChangeSummaryResponse(BaseModel):
    """Summary of durable resources changed by planning execution."""

    total_change_count: int = 0
    loop_change_count: int = 0
    downstream_change_count: int = 0
    group_count: int = 0
    created_resource_count: int = 0
    updated_resource_count: int = 0
    groups: List[PlanningResourceChangeGroupResponse] = Field(default_factory=list)
    loop_groups: List[PlanningResourceChangeGroupResponse] = Field(default_factory=list)
    downstream_groups: List[PlanningResourceChangeGroupResponse] = Field(default_factory=list)
    summary_label: str | None = None
    downstream_summary_label: str | None = None


class PlanningExecutionHistoryItemResponse(BaseModel):
    """Stored execution history for one checkpoint."""

    checkpoint_index: int
    checkpoint_title: str
    executed_at_utc: str
    operation_count: int
    results: List[PlanningCheckpointExecutionResultResponse] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    resource_change_summary: PlanningResourceChangeSummaryResponse = Field(
        default_factory=PlanningResourceChangeSummaryResponse
    )
    follow_up_resources: List[PlanningExecutionFollowUpResourceResponse] = Field(
        default_factory=list
    )
    launch_surfaces: List[PlanningExecutionLaunchSurfaceResponse] = Field(default_factory=list)
    rollback_cues: PlanningExecutionRollbackCueResponse = Field(
        default_factory=PlanningExecutionRollbackCueResponse
    )


class PlanningSessionSnapshotResponse(BaseModel):
    """Full planning session snapshot."""

    session: PlanningSessionResponse
    plan_title: str
    plan_summary: str
    assumptions: List[str] = Field(default_factory=list)
    context_summary: Dict[str, Any] = Field(default_factory=dict)
    context_freshness: PlanningContextFreshnessResponse = Field(
        default_factory=PlanningContextFreshnessResponse
    )
    execution_analytics: Dict[str, Any] = Field(default_factory=dict)
    resource_change_summary: PlanningResourceChangeSummaryResponse = Field(
        default_factory=PlanningResourceChangeSummaryResponse
    )
    target_loops: List[PlanningTargetLoopResponse] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    checkpoints: List[PlanningCheckpointResponse] = Field(default_factory=list)
    current_checkpoint: PlanningCheckpointResponse | None = None
    execution_history: List[PlanningExecutionHistoryItemResponse] = Field(default_factory=list)


class PlanningSessionExecuteResponse(BaseModel):
    """Execute the current checkpoint in a planning session."""

    execution: PlanningExecutionHistoryItemResponse
    snapshot: PlanningSessionSnapshotResponse
