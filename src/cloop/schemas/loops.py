"""Loop/task management request/response models.

Purpose:
    Define Pydantic models for the /loops/* endpoints.

Responsibilities:
    - Loop capture and CRUD request/response models
    - Status transition models
    - Export/import schemas
    - Comment CRUD request/response models

Non-scope:
    - Database models (see loops/models.py)
    - Business logic validation (see loops/service.py)

Models for the /loops/* endpoints supporting:
- Loop capture and CRUD
- Status transitions
- Prioritized "next actions" view
- Export/import for data portability
- Threaded comments with markdown support
"""

from typing import TYPE_CHECKING, Any, Dict, List, Literal

from pydantic import BaseModel, Field, field_validator

from ..loops.models import LoopStatus

if TYPE_CHECKING:
    from ..loops.models import TimerStatus, TimeSession


class LoopCaptureRequest(BaseModel):
    """Request to capture a new loop/task."""

    raw_text: str = Field(..., min_length=1)
    captured_at: str = Field(..., description="Client ISO8601 timestamp (local or offset)")
    client_tz_offset_min: int = Field(..., description="Minutes offset from UTC at capture time")
    actionable: bool = False
    scheduled: bool = False
    blocked: bool = False
    schedule: str | None = Field(
        default=None,
        description="Natural-language recurrence phrase (e.g., 'every weekday', 'every 2 weeks')",
    )
    rrule: str | None = Field(
        default=None,
        description="RFC 5545 RRULE string (e.g., 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')",
    )
    timezone: str | None = Field(
        default=None,
        description="IANA timezone name (e.g., 'America/New_York'). Defaults to client offset.",
    )
    template_id: int | None = Field(
        default=None,
        description="Optional template ID to apply for pre-filled fields",
    )
    template_name: str | None = Field(
        default=None,
        description="Optional template name to apply (alternative to template_id)",
    )

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, v: str) -> str:
        from ..loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "captured_at")

    @field_validator("client_tz_offset_min")
    @classmethod
    def validate_tz_offset(cls, v: int) -> int:
        from ..loops.models import validate_tz_offset

        return validate_tz_offset(v, "client_tz_offset_min")


class LoopUpdateRequest(BaseModel):
    """Request to update loop fields."""

    raw_text: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None, min_length=1)
    definition_of_done: str | None = Field(default=None, min_length=1)
    next_action: str | None = Field(default=None, min_length=1)
    due_at_utc: str | None = None
    snooze_until_utc: str | None = None
    time_minutes: int | None = Field(default=None, ge=1)
    activation_energy: int | None = Field(default=None, ge=0, le=3)
    urgency: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    project: str | None = Field(default=None, min_length=1)
    blocked_reason: str | None = None
    completion_note: str | None = None
    tags: List[str] | None = None
    claim_token: str | None = Field(default=None, description="Claim token for claimed loops")
    recurrence_rrule: str | None = Field(default=None, description="RFC 5545 RRULE string")
    recurrence_tz: str | None = Field(default=None, description="IANA timezone name")
    recurrence_enabled: bool | None = Field(default=None, description="Enable/disable recurrence")

    @field_validator("due_at_utc", mode="before")
    @classmethod
    def validate_due_at_utc(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from ..loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "due_at_utc")

    @field_validator("snooze_until_utc", mode="before")
    @classmethod
    def validate_snooze_until_utc(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from ..loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "snooze_until_utc")


class LoopCloseRequest(BaseModel):
    """Request to close a loop (completed or dropped)."""

    status: LoopStatus = LoopStatus.COMPLETED
    note: str | None = None
    claim_token: str | None = Field(default=None, description="Claim token for claimed loops")


class LoopStatusRequest(BaseModel):
    """Request to transition loop status."""

    status: LoopStatus
    note: str | None = None
    claim_token: str | None = Field(default=None, description="Claim token for claimed loops")


class LoopBase(BaseModel):
    """Base fields shared by LoopResponse and LoopExportItem.

    Contains 22 common fields that represent loop state.
    """

    raw_text: str
    summary: str | None = None
    definition_of_done: str | None = None
    next_action: str | None = None
    captured_at_utc: str
    captured_tz_offset_min: int
    due_at_utc: str | None = None
    snooze_until_utc: str | None = None
    time_minutes: int | None = None
    activation_energy: int | None = None
    urgency: float | None = None
    importance: float | None = None
    blocked_reason: str | None = None
    completion_note: str | None = None
    project: str | None = None
    tags: List[str] = Field(default_factory=list)
    user_locks: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    enrichment_state: str | None = None
    recurrence_rrule: str | None = None
    recurrence_tz: str | None = None
    next_due_at_utc: str | None = None
    recurrence_enabled: bool = False
    parent_loop_id: int | None = None
    created_at_utc: str
    updated_at_utc: str
    closed_at_utc: str | None = None


class LoopResponse(LoopBase):
    """Full loop response for API endpoints."""

    id: int
    title: str | None
    status: LoopStatus
    project_id: int | None = None


class LoopNextResponse(BaseModel):
    """Prioritized "Next Actions" grouped by bucket."""

    due_soon: List[LoopResponse]
    quick_wins: List[LoopResponse]
    high_leverage: List[LoopResponse]
    standard: List[LoopResponse]


class LoopExportItem(LoopBase):
    """Loop item for export/import (supports data portability).

    Differences from LoopResponse:
    - id is optional (imports create new IDs)
    - status is str (not enum, for import flexibility)
    - title has default None
    - project_id excluded (imports resolve by name)
    """

    id: int | None = None
    title: str | None = None
    status: str


class LoopExportResponse(BaseModel):
    """Response for loop export."""

    version: int = 1
    loops: List[LoopExportItem]


class LoopImportRequest(BaseModel):
    """Request to import loops from export data."""

    loops: List[LoopExportItem]


class LoopImportResponse(BaseModel):
    """Response from loop import."""

    imported: int


class LoopSearchRequest(BaseModel):
    """Request for DSL-based loop search."""

    query: str = Field(..., min_length=1, description="DSL query string")
    limit: int = Field(default=50, ge=1, le=200, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class LoopSearchResponse(BaseModel):
    """Response from DSL-based loop search."""

    query: str
    limit: int
    offset: int
    items: List[LoopResponse]


class LoopViewCreateRequest(BaseModel):
    """Request to create a saved view."""

    name: str = Field(..., min_length=1, max_length=255, description="View name")
    query: str = Field(..., min_length=1, description="DSL query string")
    description: str | None = Field(default=None, description="Optional description")


class LoopViewUpdateRequest(BaseModel):
    """Request to update a saved view."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    query: str | None = Field(default=None, min_length=1)
    description: str | None = None


class LoopViewResponse(BaseModel):
    """Saved view response."""

    id: int
    name: str
    query: str
    description: str | None = None
    created_at_utc: str
    updated_at_utc: str


class LoopViewApplyResponse(BaseModel):
    """Response from applying a saved view."""

    view: LoopViewResponse
    query: str
    limit: int
    offset: int
    items: List[LoopResponse]


class LoopEventStreamResponse(BaseModel):
    """SSE event envelope for loop events."""

    event_id: int
    event_type: str
    loop_id: int
    payload: Dict[str, Any]
    timestamp: str


class WebhookSubscriptionCreate(BaseModel):
    """Request to create a webhook subscription."""

    url: str = Field(..., min_length=1, description="Webhook URL (https recommended)")
    event_types: List[str] = Field(
        default=["*"], description="Event types to subscribe to, ['*'] for all"
    )
    description: str | None = Field(default=None, description="Optional description")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must use http or https")
        return v


class WebhookSubscriptionUpdate(BaseModel):
    """Request to update a webhook subscription."""

    url: str | None = Field(default=None, min_length=1)
    event_types: List[str] | None = None
    active: bool | None = None
    description: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("URL must use http or https")
        return v


class WebhookSubscriptionResponse(BaseModel):
    """Webhook subscription response."""

    id: int
    url: str
    event_types: List[str]
    active: bool
    description: str | None
    created_at_utc: str
    updated_at_utc: str


class WebhookSubscriptionCreateResponse(BaseModel):
    """Webhook subscription creation response.

    Includes the secret that was generated - this is the ONLY time
    the secret will be returned. Store it securely for signature verification.
    """

    id: int
    url: str
    event_types: List[str]
    active: bool
    description: str | None
    created_at_utc: str
    updated_at_utc: str
    secret: str


class WebhookDeliveryResponse(BaseModel):
    """Webhook delivery response."""

    id: int
    subscription_id: int
    event_id: int
    event_type: str
    status: str
    http_status: int | None
    error_message: str | None
    attempt_count: int
    next_retry_at: str | None
    created_at_utc: str
    updated_at_utc: str


# ============================================================================
# Loop Claim Schemas
# ============================================================================


class LoopClaimRequest(BaseModel):
    """Request to claim a loop for exclusive access."""

    owner: str = Field(
        ..., min_length=1, max_length=255, description="Identifier for claiming agent"
    )
    ttl_seconds: int | None = Field(default=None, ge=1, description="Lease duration in seconds")


class LoopRenewClaimRequest(BaseModel):
    """Request to renew an existing claim."""

    claim_token: str = Field(..., min_length=1, description="Token from original claim")
    ttl_seconds: int | None = Field(default=None, ge=1, description="New lease duration in seconds")


class LoopReleaseClaimRequest(BaseModel):
    """Request to release a claim."""

    claim_token: str = Field(..., min_length=1, description="Token from original claim")


class LoopClaimResponse(BaseModel):
    """Response for claim operations."""

    loop_id: int
    owner: str
    claim_token: str
    leased_at_utc: str
    lease_until_utc: str


class LoopClaimStatusResponse(BaseModel):
    """Claim status response (without token)."""

    loop_id: int
    owner: str
    leased_at_utc: str
    lease_until_utc: str


# ============================================================================
# Loop Dependency Schemas
# ============================================================================


class DependencyAddRequest(BaseModel):
    """Request to add a dependency."""

    depends_on_loop_id: int = Field(..., description="Loop ID that this loop depends on")


class DependencyInfo(BaseModel):
    """Information about a dependency relationship."""

    id: int = Field(..., description="Loop ID")
    title: str = Field(..., description="Loop title or truncated raw_text")
    status: str = Field(..., description="Loop status")


class LoopWithDependenciesResponse(BaseModel):
    """Loop response with dependency information."""

    id: int
    raw_text: str
    title: str | None
    status: str
    dependencies: list[DependencyInfo] = Field(default_factory=list)
    blocking: list[DependencyInfo] = Field(default_factory=list)
    has_open_dependencies: bool = Field(
        default=False, description="True if loop has unclosed dependencies"
    )


# ============================================================================
# Time Tracking Schemas
# ============================================================================


class TimerStartRequest(BaseModel):
    """Request to start a timer."""

    pass  # No fields needed - timer starts now


class TimerStopRequest(BaseModel):
    """Request to stop a timer."""

    notes: str | None = Field(default=None, description="Optional notes for this session")


class TimeSessionResponse(BaseModel):
    """Response for a time session."""

    id: int
    loop_id: int
    started_at_utc: str
    ended_at_utc: str | None
    duration_seconds: int | None
    is_active: bool
    notes: str | None

    @classmethod
    def from_session(cls, session: "TimeSession") -> "TimeSessionResponse":
        from ..loops.models import format_utc_datetime

        return cls(
            id=session.id,
            loop_id=session.loop_id,
            started_at_utc=format_utc_datetime(session.started_at_utc),
            ended_at_utc=format_utc_datetime(session.ended_at_utc)
            if session.ended_at_utc
            else None,
            duration_seconds=session.duration_seconds,
            is_active=session.is_active,
            notes=session.notes,
        )


class TimerStatusResponse(BaseModel):
    """Response for timer status."""

    loop_id: int
    has_active_session: bool
    active_session: TimeSessionResponse | None
    total_tracked_seconds: int
    total_tracked_minutes: int
    estimated_minutes: int | None
    estimation_accuracy: float | None  # actual/estimate ratio (null if no estimate)

    @classmethod
    def from_status(cls, status: "TimerStatus") -> "TimerStatusResponse":
        total_minutes = status.total_tracked_seconds // 60
        accuracy = None
        if status.estimated_minutes and status.estimated_minutes > 0:
            accuracy = round(total_minutes / status.estimated_minutes, 2)

        return cls(
            loop_id=status.loop_id,
            has_active_session=status.has_active_session,
            active_session=TimeSessionResponse.from_session(status.active_session)
            if status.active_session
            else None,
            total_tracked_seconds=status.total_tracked_seconds,
            total_tracked_minutes=total_minutes,
            estimated_minutes=status.estimated_minutes,
            estimation_accuracy=accuracy,
        )


class TimeSessionListResponse(BaseModel):
    """Response for listing time sessions."""

    loop_id: int
    sessions: list[TimeSessionResponse]
    total_count: int


# ============================================================================
# Bulk Operation Schemas
# ============================================================================


class BulkUpdateItem(BaseModel):
    """Single item in a bulk update request."""

    loop_id: int
    fields: LoopUpdateRequest


class BulkCloseItem(BaseModel):
    """Single item in a bulk close request."""

    loop_id: int
    status: Literal[LoopStatus.COMPLETED, LoopStatus.DROPPED] = LoopStatus.COMPLETED
    note: str | None = None


class BulkSnoozeItem(BaseModel):
    """Single item in a bulk snooze request."""

    loop_id: int
    snooze_until_utc: str

    @field_validator("snooze_until_utc", mode="before")
    @classmethod
    def validate_snooze_until_utc(cls, v: str) -> str:
        from ..loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "snooze_until_utc")


class BulkUpdateRequest(BaseModel):
    """Request for bulk loop update."""

    updates: List[BulkUpdateItem] = Field(..., min_length=1, max_length=100)
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkCloseRequest(BaseModel):
    """Request for bulk loop close."""

    items: List[BulkCloseItem] = Field(..., min_length=1, max_length=100)
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkSnoozeRequest(BaseModel):
    """Request for bulk loop snooze."""

    items: List[BulkSnoozeItem] = Field(..., min_length=1, max_length=100)
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkResultItem(BaseModel):
    """Result for a single item in bulk operation."""

    index: int
    loop_id: int
    ok: bool
    loop: LoopResponse | None = None
    error: Dict[str, Any] | None = None


class BulkUpdateResponse(BaseModel):
    """Response for bulk update operation."""

    ok: bool
    transactional: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class BulkCloseResponse(BaseModel):
    """Response for bulk close operation."""

    ok: bool
    transactional: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class BulkSnoozeResponse(BaseModel):
    """Response for bulk snooze operation."""

    ok: bool
    transactional: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


# ============================================================================
# Loop Template Schemas
# ============================================================================


class LoopTemplateResponse(BaseModel):
    """Response model for a loop template."""

    id: int
    name: str
    description: str | None
    raw_text_pattern: str
    defaults: Dict[str, Any]
    is_system: bool
    created_at: str
    updated_at: str


class LoopTemplateCreateRequest(BaseModel):
    """Request to create a new loop template."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    raw_text_pattern: str = Field(default="", max_length=10000)
    defaults: Dict[str, Any] = Field(default_factory=dict)


class LoopTemplateUpdateRequest(BaseModel):
    """Request to update a loop template."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    raw_text_pattern: str | None = Field(default=None, max_length=10000)
    defaults: Dict[str, Any] | None = None


class LoopTemplateListResponse(BaseModel):
    """Response for listing templates."""

    templates: List[LoopTemplateResponse]


# ============================================================================
# Review Cohort Schemas
# ============================================================================


class LoopReviewCohortItem(BaseModel):
    """Single loop item within a review cohort."""

    id: int
    raw_text: str
    title: str | None = None
    status: str
    next_action: str | None = None
    due_at_utc: str | None = None
    updated_at_utc: str


class LoopReviewCohortResponse(BaseModel):
    """Response for a single review cohort."""

    cohort: str
    count: int
    items: List[LoopReviewCohortItem]


class LoopReviewResponse(BaseModel):
    """Response for GET /loops/review with daily and weekly cohorts."""

    daily: List[LoopReviewCohortResponse]
    weekly: List[LoopReviewCohortResponse]
    generated_at_utc: str


# ============================================================================
# Loop Event History and Undo Schemas
# ============================================================================


class LoopEventResponse(BaseModel):
    """Single event in loop event history."""

    id: int
    loop_id: int
    event_type: str
    payload: Dict[str, Any]
    created_at_utc: str
    is_reversible: bool


class LoopEventListResponse(BaseModel):
    """Paginated event history response."""

    loop_id: int
    events: List[LoopEventResponse]
    has_more: bool
    next_cursor: int | None = None


class LoopUndoResponse(BaseModel):
    """Response from undo operation."""

    loop: LoopResponse
    undone_event_id: int
    undone_event_type: str


# ============================================================================
# Loop Comment Schemas
# ============================================================================


class LoopCommentCreateRequest(BaseModel):
    """Request to create a comment on a loop."""

    author: str = Field(..., min_length=1, max_length=255, description="Comment author")
    body_md: str = Field(..., min_length=1, max_length=10000, description="Markdown body")
    parent_id: int | None = Field(default=None, description="Parent comment ID for replies")


class LoopCommentUpdateRequest(BaseModel):
    """Request to update a comment."""

    body_md: str = Field(..., min_length=1, max_length=10000, description="Markdown body")


class LoopCommentResponse(BaseModel):
    """Response for a single comment."""

    id: int
    loop_id: int
    parent_id: int | None
    author: str
    body_md: str
    created_at_utc: str
    updated_at_utc: str
    deleted_at_utc: str | None = None
    is_deleted: bool
    is_reply: bool
    replies: List["LoopCommentResponse"] = Field(default_factory=list)


class LoopCommentListResponse(BaseModel):
    """Response for listing comments on a loop."""

    loop_id: int
    comments: List[LoopCommentResponse]
    total_count: int


# Resolve forward references
LoopCommentResponse.model_rebuild()


# ============================================================================
# Loop Metrics Schemas
# ============================================================================


class LoopStatusCountsResponse(BaseModel):
    """Loop counts by status."""

    inbox: int
    actionable: int
    blocked: int
    scheduled: int
    completed: int
    dropped: int


class LoopMetricsResponse(BaseModel):
    """Operational metrics for loop workflow health."""

    generated_at_utc: str
    total_loops: int
    status_counts: LoopStatusCountsResponse
    stale_open_count: int
    blocked_too_long_count: int
    no_next_action_count: int
    enrichment_pending_count: int
    enrichment_failed_count: int
    capture_count_24h: int
    completion_count_24h: int
    avg_age_open_hours: float | None
