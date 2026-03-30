"""Durable continuity transport schemas.

Purpose:
    Define request and response models for backend-backed continuity outcomes,
    backend-authored workflow summaries, recovery provenance, durable
    notification delivery state, and durable recovery acknowledgements.

Responsibilities:
    - Validate continuity outcome, last-seen, notification-state, and recovery-ack writes.
    - Shape continuity snapshot and delivery-inspection responses for cross-device hydration.
    - Model explicit fallback and replacement states when persisted targets drift
      or disappear.

Non-scope:
    - Continuity persistence logic or target resolution behavior.
    - Frontend-only ranking, rendering, or local cache state.

Usage:
    Imported by continuity storage and HTTP routes.

Invariants/Assumptions:
    - Location payloads remain transport-neutral and map to shell navigation.
    - Durable continuity stores only high-signal landed outcomes and observations.
    - Replacement provenance is emitted by the backend and consumed as the
      canonical recovery contract.
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
ContinuitySuccessorKind = Literal["replacement"]
ContinuityWorkflowSummarySource = Literal["receipt", "recent"]
ContinuityWorkflowSummaryPriorStateKind = Literal["replaced", "gone"]
ContinuityDisplayCardKind = Literal[
    "mutation",
    "decision",
    "handoff",
    "refresh",
    "context",
    "receipt",
]
ContinuityDisplayCardTone = Literal["neutral", "attention", "progress", "caution"]
ContinuityObservedEntityKind = Literal[
    "planning_session",
    "review_session",
    "working_set",
    "cohort_snapshot",
    "workflow_thread",
]
ContinuityDeliveryInspectionChannel = Literal["all", "push"]
ContinuityDeliveryReason = Literal[
    "sent",
    "cooled_down",
    "suppressed",
    "acknowledged",
    "missing_target",
    "deduped",
    "skipped",
]
ContinuitySchedulerPushDeliveryStatus = Literal[
    "claimed",
    "attempted",
    "sent",
    "no_recipients",
    "skipped",
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


class ContinuitySuccessorTargetResponse(BaseModel):
    """Backend-authored replacement target for a superseded continuity path."""

    kind: ContinuitySuccessorKind = "replacement"
    outcome_id: int
    title: str
    summary: str | None = None
    workflow_thread: WorkflowThreadRefResponse | None = None
    requested_location: ContinuityLocationResponse | None = None
    resolved_location: ContinuityLocationResponse
    status: ContinuityTargetStatus
    message: str | None = None


class ResolvedContinuityTargetResponse(BaseModel):
    """Resolved continuity target with explicit fallback and successor state."""

    requested_location: ContinuityLocationResponse | None = None
    resolved_location: ContinuityLocationResponse
    status: ContinuityTargetStatus
    message: str | None = None
    successor: ContinuitySuccessorTargetResponse | None = None


class ContinuityLoopEventUndoHandle(BaseModel):
    """Exact handle for undoing one reversible loop event."""

    kind: Literal["loop_event"] = "loop_event"
    loop_id: int
    expected_event_id: int
    event_type: str | None = None
    claim_token: str | None = None


class ContinuityPlanningRunUndoHandle(BaseModel):
    """Exact handle for rolling back one reversible planning run."""

    kind: Literal["planning_run"] = "planning_run"
    session_id: int
    run_id: int
    checkpoint_index: int
    checkpoint_title: str
    action_count: int = 0
    best_effort: bool = False


class ContinuityWorkingSetEventUndoHandle(BaseModel):
    """Exact handle for undoing one reversible working-set event."""

    kind: Literal["working_set_event"] = "working_set_event"
    expected_event_id: int
    event_type: str | None = None
    working_set_id: int | None = None
    working_set_name: str | None = None


class ContinuityRelationshipDecisionState(BaseModel):
    """One relationship-link state captured for exact-handle undo."""

    state: Literal["active", "dismissed", "resolved"]
    confidence: float | None = None
    source: str | None = None


class ContinuityRelationshipDecisionPairState(BaseModel):
    """Bidirectional relationship-pair state captured around one decision."""

    duplicate: ContinuityRelationshipDecisionState | None = None
    related: ContinuityRelationshipDecisionState | None = None


class ContinuityRelationshipDecisionUndoHandle(BaseModel):
    """Exact handle for undoing one saved relationship decision."""

    kind: Literal["relationship_decision"] = "relationship_decision"
    session_id: int
    loop_id: int
    candidate_loop_id: int
    expected_pair_state: ContinuityRelationshipDecisionPairState = Field(
        default_factory=ContinuityRelationshipDecisionPairState
    )
    restore_pair_state: ContinuityRelationshipDecisionPairState = Field(
        default_factory=ContinuityRelationshipDecisionPairState
    )


class ContinuityClarificationAnswerUndoHandle(BaseModel):
    """Exact handle for undoing one answer-only clarification submission."""

    kind: Literal["clarification_answer"] = "clarification_answer"
    loop_id: int
    clarification_ids: list[int] = Field(default_factory=list, min_length=1)


ContinuityExecutableUndoHandle = (
    ContinuityLoopEventUndoHandle
    | ContinuityPlanningRunUndoHandle
    | ContinuityWorkingSetEventUndoHandle
    | ContinuityRelationshipDecisionUndoHandle
    | ContinuityClarificationAnswerUndoHandle
)


class ContinuityUndoAction(BaseModel):
    """Executable undo contract attached to one durable continuity outcome."""

    label: str
    description: str
    undo: ContinuityExecutableUndoHandle
    requires_confirmation: bool = False
    confirm_title: str | None = None
    confirm_description: str | None = None
    success_location: ContinuityLocationResponse | None = None


class ContinuityRerunPostRunBehavior(BaseModel):
    """Post-rerun landing contract for one durable rerun action."""

    summary: str
    location: ContinuityLocationResponse | None = None


class ContinuityPlanningSessionRerunHandle(BaseModel):
    """Exact handle for rerunning one planning session."""

    kind: Literal["planning_session"] = "planning_session"
    session_id: int
    session_name: str


class ContinuityReviewSessionRerunHandle(BaseModel):
    """Exact handle for refreshing one saved review session."""

    kind: Literal["review_session"] = "review_session"
    review_focus: Literal["relationship", "enrichment"]
    session_id: int
    session_name: str


class ContinuityRecallQueryRerunHandle(BaseModel):
    """Exact handle for rerunning one recall query."""

    kind: Literal["recall_query"] = "recall_query"
    recall_tool: Literal["chat", "rag"]
    query: str
    working_set_id: int | None = None
    include_loop_context: bool | None = None
    include_memory_context: bool | None = None
    include_rag_context: bool | None = None


ContinuityExecutableRerunHandle = (
    ContinuityPlanningSessionRerunHandle
    | ContinuityReviewSessionRerunHandle
    | ContinuityRecallQueryRerunHandle
)


class ContinuityRerunAttemptContract(BaseModel):
    """Deterministic rerun contract describing invariants and landing semantics."""

    mode: Literal["refresh", "rerun"]
    provenance_label: str
    freshness_label: str | None = None
    strategy_summary: str
    strict_invariants: list[str] = Field(default_factory=list)
    may_vary: list[str] = Field(default_factory=list)
    post_run: ContinuityRerunPostRunBehavior


class ContinuityRerunAction(BaseModel):
    """Executable rerun contract attached to one durable continuity outcome."""

    label: str
    description: str
    rerun: ContinuityExecutableRerunHandle
    contract: ContinuityRerunAttemptContract


class ContinuityDisplayPreviewItemResponse(BaseModel):
    """One backend-authored preview row for a continuity display card."""

    label: str
    value: str


class ContinuityDisplayWorkingSetResponse(BaseModel):
    """Working-set context attached to a continuity display handoff."""

    working_set_id: int
    working_set_name: str
    item_count: int = 0
    missing_item_count: int = 0


class ContinuityDisplayHandoffResponse(BaseModel):
    """Backend-authored follow-through handoff details for one continuity card."""

    change_summary: str
    created_resources: list[str] = Field(default_factory=list)
    next_step: str | None = None
    breadcrumbs: list[str] = Field(default_factory=list)
    working_set: ContinuityDisplayWorkingSetResponse | None = None


class ContinuityDisplayTrustResponse(BaseModel):
    """Backend-authored trust metadata for one continuity display card."""

    generation_label: str | None = None
    generation_tone: ContinuityDisplayCardTone | None = None
    context_sources: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence_label: str | None = None
    confidence_tone: ContinuityDisplayCardTone | None = None
    freshness_label: str | None = None
    freshness_tone: ContinuityDisplayCardTone | None = None
    rollback_label: str | None = None
    rollback_tone: ContinuityDisplayCardTone | None = None
    impact_summary: str | None = None
    impact_tone: ContinuityDisplayCardTone | None = None


class ContinuityDisplayCardResponse(BaseModel):
    """Minimal backend-authored continuity card display contract."""

    kind: ContinuityDisplayCardKind
    tone: ContinuityDisplayCardTone
    eyebrow: str
    title: str
    summary: str
    rationale: str
    preview: list[ContinuityDisplayPreviewItemResponse] = Field(default_factory=list)
    trust: ContinuityDisplayTrustResponse
    handoff: ContinuityDisplayHandoffResponse | None = None
    action_context_label: str | None = None
    action_warning: str | None = None


class ReviewFollowThroughResponse(BaseModel):
    """Backend-authored review follow-through contract for fresh landed outcomes."""

    display_card: ContinuityDisplayCardResponse
    undo_action: ContinuityUndoAction | None = None
    rerun_action: ContinuityRerunAction | None = None
    resume_location: ContinuityLocationResponse | None = None
    workflow_thread: WorkflowThreadRefResponse
    working_set_id: int | None = None


class ContinuityOutcomeWriteRequest(BaseModel):
    """Request to persist one high-signal landed outcome."""

    kind: str
    label: str
    description: str
    occurred_at_utc: str
    launch_location: ContinuityLocationResponse | None = None
    display_card: ContinuityDisplayCardResponse
    undo_action: ContinuityUndoAction | None = None
    rerun_action: ContinuityRerunAction | None = None
    resume_location: ContinuityLocationResponse | None = None
    working_set_id: int | None = None
    workflow_thread: WorkflowThreadRefResponse
    dedupe_key: str
    source_surface: str
    signal_level: ContinuitySignalLevel = "high"
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class ContinuityNotificationStateUpsertRequest(BaseModel):
    """Request to persist durable delivery state for one notification record."""

    inboxed_at_utc: str | None = None
    seen_at_utc: str | None = None
    acknowledged_at_utc: str | None = None
    suppressed_until_utc: str | None = None


class ContinuityNotificationStateResponse(BaseModel):
    """Durable delivery state returned alongside one notification record."""

    inboxed_at_utc: str | None = None
    seen_at_utc: str | None = None
    acknowledged_at_utc: str | None = None
    suppressed_until_utc: str | None = None


class ContinuityRecoveryAcknowledgementUpsertRequest(BaseModel):
    """Request to persist one durable continuity recovery acknowledgement."""

    recovery_key: str
    acknowledged_at_utc: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityRecoveryAcknowledgementResponse(BaseModel):
    """Durable recovery acknowledgement returned to the frontend."""

    recovery_key: str
    acknowledged_at_utc: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityOutcomeRecordResponse(BaseModel):
    """Persisted high-signal landed outcome returned to the frontend shell."""

    id: int
    kind: str
    label: str
    description: str
    occurred_at_utc: str
    launch_location: ContinuityLocationResponse | None = None
    display_card: ContinuityDisplayCardResponse
    undo_action: ContinuityUndoAction | None = None
    rerun_action: ContinuityRerunAction | None = None
    resume_location: ContinuityLocationResponse | None = None
    resolved_resume: ResolvedContinuityTargetResponse
    workflow_thread: WorkflowThreadRefResponse
    working_set_id: int | None = None
    degraded: bool = False
    degraded_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContinuityWorkflowSummarySignalsResponse(BaseModel):
    """Deterministic ranking signals for one backend-authored workflow summary."""

    drift_severity: Literal["none", "minor", "moderate", "major", "replaced", "gone"]
    drift_score: int
    working_set_relevant: bool
    downstream_ready: bool
    degraded: bool
    recency_tie_breaker: int


class ContinuityWorkflowSummaryPriorStateResponse(BaseModel):
    """Prior-path state explanation attached to one workflow summary."""

    kind: ContinuityWorkflowSummaryPriorStateKind
    title: str
    summary: str


class ContinuityWorkflowSummaryResponse(BaseModel):
    """Backend-authored ranked continuity summary for one resumable workflow."""

    id: str
    source: ContinuityWorkflowSummarySource
    rank: int
    ranking_signals: ContinuityWorkflowSummarySignalsResponse
    workflow_thread: WorkflowThreadRefResponse
    representative_outcome_id: int | None = None
    latest_outcome_id: int | None = None
    occurred_at_utc: str
    outcome_count: int
    outcome_preview_titles: list[str] = Field(default_factory=list)
    requested_resume_location: ContinuityLocationResponse | None = None
    resolved_resume: ResolvedContinuityTargetResponse
    display_title: str
    display_summary: str
    display_card: ContinuityDisplayCardResponse
    undo_action: ContinuityUndoAction | None = None
    rerun_action: ContinuityRerunAction | None = None
    working_set_id: int | None = None
    working_set_name: str | None = None
    degraded: bool = False
    degraded_label: str | None = None
    why_now: list[str] = Field(default_factory=list)
    changed_since_last_seen: list[str] = Field(default_factory=list)
    prior_state: ContinuityWorkflowSummaryPriorStateResponse | None = None


class ContinuityNotificationRecordResponse(BaseModel):
    """Backend-authored continuity notification record for transport delivery."""

    id: str
    title: str
    body: str
    severity: Literal["info", "warning", "alert"]
    workflow_thread: WorkflowThreadRefResponse
    resolved_location: ContinuityLocationResponse
    state: ContinuityNotificationStateResponse = Field(
        default_factory=ContinuityNotificationStateResponse
    )


class ContinuitySchedulerPushDeliveryResponse(BaseModel):
    """Latest persisted scheduler push-delivery row joined onto one notification."""

    task_name: str
    slot_key: str
    push_kind: str
    notification_id: str | None = None
    workflow_thread_id: str | None = None
    claimed_at_utc: str
    send_started_at_utc: str | None = None
    send_completed_at_utc: str | None = None
    delivery_status: ContinuitySchedulerPushDeliveryStatus
    delivery_reason: str | None = None
    push_count: int


class ContinuityDeliveryDecisionResponse(BaseModel):
    """One inspected continuity delivery decision with canonical reason."""

    record: ContinuityNotificationRecordResponse
    reason: ContinuityDeliveryReason
    resend_ready_at_utc: str | None = None
    latest_push_delivery: ContinuitySchedulerPushDeliveryResponse | None = None


class ContinuityDeliveryInspectionContinuationResponse(BaseModel):
    """Stable cue for continuing one bounded delivery-diagnostics scan."""

    cursor: str


class ContinuityDeliveryInspectionResponse(BaseModel):
    """Debug-first continuity delivery inspection payload."""

    inspected_at_utc: str
    channel: ContinuityDeliveryInspectionChannel
    limit: int = Field(
        description=(
            "Requested sent-decision limit. Push inspections may include additional "
            "non-sent decisions from the bounded scan needed to find sendable records."
        )
    )
    truncated: bool = False
    continuation: ContinuityDeliveryInspectionContinuationResponse | None = None
    decisions: list[ContinuityDeliveryDecisionResponse] = Field(default_factory=list)


class ContinuitySnapshotResponse(BaseModel):
    """Durable continuity snapshot used to hydrate frontend cache state."""

    recorded_at_utc: str
    outcomes: list[ContinuityOutcomeRecordResponse] = Field(default_factory=list)
    workflow_summaries: list[ContinuityWorkflowSummaryResponse] = Field(default_factory=list)
    notification_records: list[ContinuityNotificationRecordResponse] = Field(default_factory=list)
    last_seen_markers: list[ContinuityLastSeenMarkerResponse] = Field(default_factory=list)
    recovery_acknowledgements: list[ContinuityRecoveryAcknowledgementResponse] = Field(
        default_factory=list
    )


__all__ = [
    "ContinuityDeliveryDecisionResponse",
    "ContinuityDeliveryInspectionChannel",
    "ContinuityDeliveryInspectionContinuationResponse",
    "ContinuityDeliveryInspectionResponse",
    "ContinuityDeliveryReason",
    "ContinuityClarificationAnswerUndoHandle",
    "ContinuityExecutableRerunHandle",
    "ContinuityExecutableUndoHandle",
    "ContinuityLoopEventUndoHandle",
    "ContinuityPlanningRunUndoHandle",
    "ContinuityPlanningSessionRerunHandle",
    "ContinuityRecallQueryRerunHandle",
    "ContinuityRerunAction",
    "ContinuityRerunAttemptContract",
    "ContinuityRerunPostRunBehavior",
    "ContinuityReviewSessionRerunHandle",
    "ContinuitySchedulerPushDeliveryResponse",
    "ContinuitySchedulerPushDeliveryStatus",
    "ContinuityUndoAction",
    "ContinuityWorkingSetEventUndoHandle",
    "ContinuityLastSeenBatchUpsertRequest",
    "ContinuityLastSeenMarkerResponse",
    "ContinuityLastSeenMarkerUpsertRequest",
    "ContinuityLocationResponse",
    "ContinuityNotificationRecordResponse",
    "ContinuityNotificationStateResponse",
    "ContinuityNotificationStateUpsertRequest",
    "ContinuityOutcomeRecordResponse",
    "ContinuityOutcomeWriteRequest",
    "ContinuityRecoveryAcknowledgementResponse",
    "ContinuityRecoveryAcknowledgementUpsertRequest",
    "ContinuitySnapshotResponse",
    "ContinuitySuccessorTargetResponse",
    "ContinuityWorkflowSummaryPriorStateResponse",
    "ContinuityWorkflowSummaryResponse",
    "ContinuityWorkflowSummarySignalsResponse",
    "ResolvedContinuityTargetResponse",
    "WorkflowThreadRefResponse",
]
