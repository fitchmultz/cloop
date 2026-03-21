"""Durable continuity transport schemas.

Purpose:
    Define request and response models for backend-backed continuity outcomes,
    grouped workflow threads, durable resume anchors, and last-seen markers.

Responsibilities:
    - Validate continuity outcome, anchor, and last-seen write payloads.
    - Shape continuity snapshot responses for cross-device hydration.
    - Model explicit fallback states when persisted targets drift or disappear.

Non-scope:
    - Continuity persistence logic or target resolution behavior.
    - Frontend-only ranking, rendering, or local cache state.

Usage:
    Imported by continuity storage and HTTP routes.

Invariants/Assumptions:
    - Location payloads remain transport-neutral and map to shell navigation.
    - Durable continuity stores only high-signal landed outcomes, anchors, and observations.
"""

from __future__ import annotations

from typing import Any, Literal

from ._shared import BaseModel, Field

ContinuityShellState = Literal[
    "operator",
    "capture",
    "do",
    "decide",
    "plan",
    "review",
    "recall",
    "working_set",
]
ContinuityRecallTool = Literal["chat", "memory", "rag"]
ContinuityReviewFocus = Literal["planning", "relationship", "enrichment", "cohorts"]
ContinuityObservedReviewFocus = Literal["planning", "relationship", "enrichment"]
ContinuityWorkflowThreadKind = Literal[
    "planning_checkpoint",
    "review_session",
    "working_set",
    "command",
    "recall",
    "ad_hoc",
]
ContinuitySignalLevel = Literal["high", "secondary"]
ContinuityTargetStatus = Literal[
    "ok",
    "working_set_scope_removed",
    "launch_fallback",
    "home_fallback",
]
ContinuityObservedEntityKind = Literal[
    "planning_session",
    "review_session",
    "working_set",
    "cohort_snapshot",
    "workflow_thread",
]


class ContinuityLocationResponse(BaseModel):
    """Transport-safe shell launch target."""

    state: ContinuityShellState
    recall_tool: ContinuityRecallTool = "chat"
    review_focus: ContinuityReviewFocus | None = None
    session_id: int | None = None
    loop_id: int | None = None
    view_id: int | None = None
    memory_id: int | None = None
    working_set_id: int | None = None
    query: str | None = None


class WorkflowThreadRefResponse(BaseModel):
    """Explicit continuity workflow-thread reference."""

    id: str
    kind: ContinuityWorkflowThreadKind
    title: str
    summary: str | None = None
    parent_outcome_id: int | None = None


class ResolvedContinuityTargetResponse(BaseModel):
    """Resolved continuity target with explicit fallback state."""

    requested_location: ContinuityLocationResponse | None = None
    resolved_location: ContinuityLocationResponse
    status: ContinuityTargetStatus
    message: str | None = None


class ContinuityOutcomeWriteRequest(BaseModel):
    """Request to persist one high-signal landed outcome."""

    kind: str
    label: str
    description: str
    occurred_at_utc: str
    launch_location: ContinuityLocationResponse | None = None
    outcome_card: dict[str, Any]
    resume_location: ContinuityLocationResponse | None = None
    working_set_id: int | None = None
    workflow_thread: WorkflowThreadRefResponse
    dedupe_key: str
    source_surface: str
    signal_level: ContinuitySignalLevel = "high"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityAnchorUpsertRequest(BaseModel):
    """Request to upsert one durable continuity resume anchor."""

    anchor_kind: Literal["planning", "review"]
    review_focus: ContinuityObservedReviewFocus
    session_id: int
    visited_at_utc: str
    launch_location: ContinuityLocationResponse | None = None
    resume_location: ContinuityLocationResponse | None = None
    outcome_title: str | None = None
    outcome_summary: str | None = None
    working_set_id: int | None = None
    workflow_thread_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityAnchorResponse(BaseModel):
    """Durable continuity resume anchor response."""

    kind: Literal["planning", "review"]
    review_focus: ContinuityObservedReviewFocus
    session_id: int
    visited_at_utc: str
    launch_location: ContinuityLocationResponse | None = None
    resume_location: ContinuityLocationResponse | None = None
    outcome_title: str | None = None
    outcome_summary: str | None = None
    working_set_id: int | None = None
    workflow_thread_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityAnchorsResponse(BaseModel):
    """Grouped durable continuity anchors."""

    planning: ContinuityAnchorResponse | None = None
    review: ContinuityAnchorResponse | None = None


class ContinuityLastSeenMarkerUpsertRequest(BaseModel):
    """One durable operator observation for a continuity-relevant entity."""

    entity_kind: ContinuityObservedEntityKind
    entity_key: str
    observed_at_utc: str
    observed_fingerprint: str
    working_set_id: int | None = None
    workflow_thread_id: str | None = None
    observed_state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityLastSeenMarkerResponse(BaseModel):
    """Durable last-seen marker returned to the frontend."""

    entity_kind: ContinuityObservedEntityKind
    entity_key: str
    observed_at_utc: str
    observed_fingerprint: str
    working_set_id: int | None = None
    workflow_thread_id: str | None = None
    observed_state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityLastSeenBatchUpsertRequest(BaseModel):
    """Batch upsert for durable last-seen continuity markers."""

    markers: list[ContinuityLastSeenMarkerUpsertRequest] = Field(default_factory=list)


class ContinuityOutcomeRecordResponse(BaseModel):
    """Persisted high-signal landed outcome returned to the frontend shell."""

    id: int
    kind: str
    label: str
    description: str
    occurred_at_utc: str
    launch_location: ContinuityLocationResponse | None = None
    outcome_card: dict[str, Any]
    resume_location: ContinuityLocationResponse | None = None
    resolved_resume: ResolvedContinuityTargetResponse
    workflow_thread: WorkflowThreadRefResponse
    working_set_id: int | None = None
    degraded: bool = False
    degraded_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityThreadSummaryResponse(BaseModel):
    """Grouped workflow-thread rollup for continuity readers."""

    workflow_thread: WorkflowThreadRefResponse
    outcome_count: int
    latest_outcome_id: int
    latest_occurred_at_utc: str
    representative_title: str
    representative_summary: str


class ContinuitySnapshotResponse(BaseModel):
    """Durable continuity snapshot used to hydrate frontend cache state."""

    recorded_at_utc: str
    outcomes: list[ContinuityOutcomeRecordResponse] = Field(default_factory=list)
    anchors: ContinuityAnchorsResponse = Field(default_factory=ContinuityAnchorsResponse)
    threads: list[ContinuityThreadSummaryResponse] = Field(default_factory=list)
    last_seen_markers: list[ContinuityLastSeenMarkerResponse] = Field(default_factory=list)


__all__ = [
    "ContinuityAnchorResponse",
    "ContinuityAnchorUpsertRequest",
    "ContinuityAnchorsResponse",
    "ContinuityLastSeenBatchUpsertRequest",
    "ContinuityLastSeenMarkerResponse",
    "ContinuityLastSeenMarkerUpsertRequest",
    "ContinuityLocationResponse",
    "ContinuityOutcomeRecordResponse",
    "ContinuityOutcomeWriteRequest",
    "ContinuitySnapshotResponse",
    "ContinuityThreadSummaryResponse",
    "ResolvedContinuityTargetResponse",
    "WorkflowThreadRefResponse",
]
