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

from ..constants import (
    AUTHOR_MAX,
    BLOCKED_REASON_MAX,
    BULK_OPERATION_MAX_ITEMS,
    COMMENT_BODY_MAX,
    COMPLETION_NOTE_MAX,
    DEFINITION_OF_DONE_MAX,
    NEXT_ACTION_MAX,
    PROJECT_MAX,
    RAW_TEXT_MAX,
    RRULE_MAX,
    SCHEDULE_MAX,
    SEARCH_QUERY_MAX,
    SUMMARY_MAX,
    TEMPLATE_DESCRIPTION_MAX,
    TEMPLATE_NAME_MAX,
    TIMEZONE_MAX,
    TITLE_MAX,
    VIEW_DESCRIPTION_MAX,
    VIEW_NAME_MAX,
    WEBHOOK_DESCRIPTION_MAX,
    WEBHOOK_URL_MAX,
)
from ..loops.due_contract import validate_due_date
from ..loops.models import LoopStatus

if TYPE_CHECKING:
    from ..loops.models import TimerStatus, TimeSession


class LoopCaptureRequest(BaseModel):
    """Request to capture a new loop/task."""

    raw_text: str = Field(..., min_length=1, max_length=RAW_TEXT_MAX)
    captured_at: str = Field(..., description="Client ISO8601 timestamp (local or offset)")
    client_tz_offset_min: int = Field(..., description="Minutes offset from UTC at capture time")
    actionable: bool = False
    scheduled: bool = False
    blocked: bool = False
    schedule: str | None = Field(
        default=None,
        max_length=SCHEDULE_MAX,
        description="Natural-language recurrence phrase (e.g., 'every weekday', 'every 2 weeks')",
    )
    rrule: str | None = Field(
        default=None,
        max_length=RRULE_MAX,
        description="RFC 5545 RRULE string (e.g., 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')",
    )
    timezone: str | None = Field(
        default=None,
        max_length=TIMEZONE_MAX,
        description="IANA timezone name (e.g., 'America/New_York'). Defaults to client offset.",
    )
    template_id: int | None = Field(
        default=None,
        description="Optional template ID to apply for pre-filled fields",
    )
    template_name: str | None = Field(
        default=None,
        max_length=TITLE_MAX,
        description="Optional template name to apply (alternative to template_id)",
    )

    # Rich capture metadata (all optional)
    due_date: str | None = Field(
        default=None,
        description="ISO calendar date for date-only due values (YYYY-MM-DD)",
    )
    due_at_utc: str | None = Field(
        default=None,
        description="ISO8601 due date timestamp",
    )
    next_action: str | None = Field(
        default=None,
        min_length=1,
        max_length=NEXT_ACTION_MAX,
        description="Immediate next action to take",
    )
    time_minutes: int | None = Field(
        default=None,
        ge=1,
        description="Estimated time to complete in minutes",
    )
    activation_energy: int | None = Field(
        default=None,
        ge=0,
        le=3,
        description="Effort level 0-3 (trivial to hard)",
    )
    project: str | None = Field(
        default=None,
        min_length=1,
        max_length=PROJECT_MAX,
        description="Project name to associate",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Tags to apply",
    )
    blocked_reason: str | None = Field(
        default=None,
        max_length=BLOCKED_REASON_MAX,
        description="Reason the loop is blocked (if blocked=true)",
    )

    @field_validator("due_date", mode="before")
    @classmethod
    def validate_due_date_field(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_due_date(v, "due_date")

    @field_validator("due_at_utc", mode="before")
    @classmethod
    def validate_due_at_utc(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from ..loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "due_at_utc")

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

    raw_text: str | None = Field(default=None, min_length=1, max_length=RAW_TEXT_MAX)
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    summary: str | None = Field(default=None, min_length=1, max_length=SUMMARY_MAX)
    definition_of_done: str | None = Field(
        default=None, min_length=1, max_length=DEFINITION_OF_DONE_MAX
    )
    next_action: str | None = Field(default=None, min_length=1, max_length=NEXT_ACTION_MAX)
    due_date: str | None = None
    due_at_utc: str | None = None
    snooze_until_utc: str | None = None
    time_minutes: int | None = Field(default=None, ge=1)
    activation_energy: int | None = Field(default=None, ge=0, le=3)
    urgency: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    project: str | None = Field(default=None, min_length=1, max_length=PROJECT_MAX)
    blocked_reason: str | None = Field(default=None, max_length=BLOCKED_REASON_MAX)
    completion_note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)
    tags: List[str] | None = None
    claim_token: str | None = Field(default=None, description="Claim token for claimed loops")
    recurrence_rrule: str | None = Field(
        default=None, max_length=RRULE_MAX, description="RFC 5545 RRULE string"
    )
    recurrence_tz: str | None = Field(
        default=None, max_length=TIMEZONE_MAX, description="IANA timezone name"
    )
    recurrence_enabled: bool | None = Field(default=None, description="Enable/disable recurrence")

    @field_validator("due_date", mode="before")
    @classmethod
    def validate_due_date_field(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_due_date(v, "due_date")

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
    note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)
    claim_token: str | None = Field(default=None, description="Claim token for claimed loops")


class LoopStatusRequest(BaseModel):
    """Request to transition loop status."""

    status: LoopStatus
    note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)
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
    due_date: str | None = None
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


class LoopEnrichmentResponse(BaseModel):
    """Canonical response for an explicit loop enrichment run."""

    loop: LoopResponse
    suggestion_id: int
    applied_fields: List[str]
    needs_clarification: List[str]


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
    filtered: bool = Field(default=False, description="True if filters were applied")


class LoopImportRequest(BaseModel):
    """Request to import loops from export data."""

    loops: List[LoopExportItem]


class LoopImportResponse(BaseModel):
    """Response from loop import."""

    imported: int
    skipped: int = Field(default=0, description="Number of loops skipped due to conflicts")
    updated: int = Field(default=0, description="Number of existing loops updated")
    conflicts_detected: int = Field(default=0, description="Number of conflicts detected")
    dry_run: bool = Field(default=False, description="Whether this was a dry-run preview")
    preview: dict[str, Any] | None = Field(
        default=None, description="Preview details for dry-run mode"
    )


class LoopSearchRequest(BaseModel):
    """Request for DSL-based loop search."""

    query: str = Field(
        ..., min_length=1, max_length=SEARCH_QUERY_MAX, description="DSL query string"
    )
    limit: int = Field(default=50, ge=1, le=200, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class LoopSearchResponse(BaseModel):
    """Response from DSL-based loop search."""

    query: str
    limit: int
    offset: int
    items: List[LoopResponse]


LoopSearchStatusFilter = Literal[
    "open",
    "all",
    "inbox",
    "actionable",
    "blocked",
    "scheduled",
    "completed",
    "dropped",
]


class SemanticSearchLoopResponse(LoopResponse):
    """Loop payload augmented with semantic similarity score."""

    semantic_score: float


class LoopSemanticSearchRequest(BaseModel):
    """Request for semantic loop search."""

    query: str = Field(
        ..., min_length=1, max_length=SEARCH_QUERY_MAX, description="Natural-language query"
    )
    status: LoopSearchStatusFilter = Field(default="open", description="Loop status scope")
    limit: int = Field(default=50, ge=1, le=200, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional minimum cosine similarity score",
    )


class LoopSemanticSearchResponse(BaseModel):
    """Response from semantic loop search."""

    query: str
    status: LoopSearchStatusFilter
    limit: int
    offset: int
    min_score: float | None = None
    indexed_count: int
    candidate_count: int
    match_count: int
    items: List[SemanticSearchLoopResponse]


class LoopViewCreateRequest(BaseModel):
    """Request to create a saved view."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX, description="View name")
    query: str = Field(
        ..., min_length=1, max_length=SEARCH_QUERY_MAX, description="DSL query string"
    )
    description: str | None = Field(
        default=None, max_length=VIEW_DESCRIPTION_MAX, description="Optional description"
    )


class LoopViewUpdateRequest(BaseModel):
    """Request to update a saved view."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


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

    url: str = Field(
        ..., min_length=1, max_length=WEBHOOK_URL_MAX, description="Webhook URL (https recommended)"
    )
    event_types: List[str] = Field(
        default=["*"], description="Event types to subscribe to, ['*'] for all"
    )
    description: str | None = Field(
        default=None, max_length=WEBHOOK_DESCRIPTION_MAX, description="Optional description"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must use http or https")
        return v


class WebhookSubscriptionUpdate(BaseModel):
    """Request to update a webhook subscription."""

    url: str | None = Field(default=None, min_length=1, max_length=WEBHOOK_URL_MAX)
    event_types: List[str] | None = None
    active: bool | None = None
    description: str | None = Field(default=None, max_length=WEBHOOK_DESCRIPTION_MAX)

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
        ..., min_length=1, max_length=AUTHOR_MAX, description="Identifier for claiming agent"
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

    notes: str | None = Field(
        default=None, max_length=SUMMARY_MAX, description="Optional notes for this session"
    )


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
    note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)


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

    updates: List[BulkUpdateItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of updates (max {BULK_OPERATION_MAX_ITEMS} items)",
    )
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkCloseRequest(BaseModel):
    """Request for bulk loop close."""

    items: List[BulkCloseItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of items to close (max {BULK_OPERATION_MAX_ITEMS} items)",
    )
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkSnoozeRequest(BaseModel):
    """Request for bulk loop snooze."""

    items: List[BulkSnoozeItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of items to snooze (max {BULK_OPERATION_MAX_ITEMS} items)",
    )
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkEnrichItem(BaseModel):
    """Single item in a bulk enrich request."""

    loop_id: int


class BulkEnrichRequest(BaseModel):
    """Request for bulk loop enrichment."""

    items: List[BulkEnrichItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of loops to enrich (max {BULK_OPERATION_MAX_ITEMS} items)",
    )


class BulkResultItem(BaseModel):
    """Result for a single item in bulk operation."""

    index: int
    loop_id: int
    ok: bool
    loop: LoopResponse | None = None
    error: Dict[str, Any] | None = None


class BulkEnrichmentResultItem(BulkResultItem):
    """Result for one loop inside a bulk enrichment run."""

    suggestion_id: int | None = None
    applied_fields: List[str] = Field(default_factory=list)
    needs_clarification: List[str] = Field(default_factory=list)


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


class BulkEnrichResponse(BaseModel):
    """Response for bulk enrichment operation."""

    ok: bool
    results: List[BulkEnrichmentResultItem]
    succeeded: int
    failed: int


# ============================================================================
# Query-Based Bulk Operation Schemas
# ============================================================================


class QueryBulkUpdateRequest(BaseModel):
    """Bulk update targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    fields: LoopUpdateRequest = Field(..., description="Fields to update on matched loops")
    transactional: bool = Field(default=False, description="Rollback all on any failure")
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100, ge=1, le=BULK_OPERATION_MAX_ITEMS, description="Max loops to affect"
    )


class QueryBulkCloseRequest(BaseModel):
    """Bulk close targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    status: Literal[LoopStatus.COMPLETED, LoopStatus.DROPPED] = LoopStatus.COMPLETED
    note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)
    transactional: bool = Field(default=False, description="Rollback all on any failure")
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100, ge=1, le=BULK_OPERATION_MAX_ITEMS, description="Max loops to affect"
    )


class QueryBulkSnoozeRequest(BaseModel):
    """Bulk snooze targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    snooze_until_utc: str = Field(..., description="Snooze until timestamp")
    transactional: bool = Field(default=False, description="Rollback all on any failure")
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100, ge=1, le=BULK_OPERATION_MAX_ITEMS, description="Max loops to affect"
    )

    @field_validator("snooze_until_utc", mode="before")
    @classmethod
    def validate_snooze_until_utc(cls, v: str) -> str:
        from ..loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "snooze_until_utc")


class QueryBulkEnrichRequest(BaseModel):
    """Bulk enrich targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100,
        ge=1,
        le=BULK_OPERATION_MAX_ITEMS,
        description="Max loops to affect",
    )


class QueryBulkPreviewResponse(BaseModel):
    """Response for dry-run preview of query-based bulk operation."""

    query: str
    dry_run: bool
    matched_count: int
    limited: bool
    targets: List[LoopResponse]


class QueryBulkUpdateResponse(BaseModel):
    """Response for query-based bulk update."""

    query: str
    dry_run: bool
    ok: bool
    transactional: bool
    matched_count: int
    limited: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class QueryBulkCloseResponse(BaseModel):
    """Response for query-based bulk close."""

    query: str
    dry_run: bool
    ok: bool
    transactional: bool
    matched_count: int
    limited: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class QueryBulkSnoozeResponse(BaseModel):
    """Response for query-based bulk snooze."""

    query: str
    dry_run: bool
    ok: bool
    transactional: bool
    matched_count: int
    limited: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class QueryBulkEnrichResponse(BaseModel):
    """Response for query-based bulk enrichment."""

    query: str
    dry_run: bool
    ok: bool
    matched_count: int
    limited: bool
    results: List[BulkEnrichmentResultItem]
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

    name: str = Field(..., min_length=1, max_length=TEMPLATE_NAME_MAX)
    description: str | None = Field(default=None, max_length=TEMPLATE_DESCRIPTION_MAX)
    raw_text_pattern: str = Field(default="", max_length=RAW_TEXT_MAX)
    defaults: Dict[str, Any] = Field(default_factory=dict)


class LoopTemplateUpdateRequest(BaseModel):
    """Request to update a loop template."""

    name: str | None = Field(default=None, min_length=1, max_length=TEMPLATE_NAME_MAX)
    description: str | None = Field(default=None, max_length=TEMPLATE_DESCRIPTION_MAX)
    raw_text_pattern: str | None = Field(default=None, max_length=RAW_TEXT_MAX)
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

    author: str = Field(..., min_length=1, max_length=AUTHOR_MAX, description="Comment author")
    body_md: str = Field(
        ..., min_length=1, max_length=COMMENT_BODY_MAX, description="Markdown body"
    )
    parent_id: int | None = Field(default=None, description="Parent comment ID for replies")


class LoopCommentUpdateRequest(BaseModel):
    """Request to update a comment."""

    body_md: str = Field(
        ..., min_length=1, max_length=COMMENT_BODY_MAX, description="Markdown body"
    )


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


class LoopOperationMetricsResponse(BaseModel):
    """Operation-level metrics for loop lifecycle events."""

    capture_count: int
    update_count: int
    transition_counts: Dict[str, int]
    reset_count: int


class ProjectMetricsResponse(BaseModel):
    """Per-project metrics breakdown."""

    project_id: int | None
    project_name: str | None
    total_loops: int
    open_loops: int
    completed_loops: int
    dropped_loops: int
    capture_count_window: int
    completion_count_window: int
    avg_age_open_hours: float | None


class TrendPointResponse(BaseModel):
    """Single data point in a trend series."""

    date: str
    capture_count: int
    completion_count: int
    open_count: int


class TrendMetricsResponse(BaseModel):
    """Time-series trend metrics."""

    window_days: int
    points: List[TrendPointResponse]
    total_captures: int
    total_completions: int
    avg_daily_captures: float
    avg_daily_completions: float


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
    operation_metrics: LoopOperationMetricsResponse | None = None

    # New optional fields
    project_breakdown: List[ProjectMetricsResponse] | None = None
    trend_metrics: TrendMetricsResponse | None = None


# ============================================================================
# Duplicate Detection and Merge Schemas
# ============================================================================


class DuplicateCandidateResponse(BaseModel):
    """A potential duplicate loop with similarity score."""

    loop_id: int
    score: float
    title: str | None
    raw_text_preview: str
    status: str
    captured_at_utc: str


class DuplicatesListResponse(BaseModel):
    """Response for listing duplicate candidates."""

    loop_id: int
    candidates: List[DuplicateCandidateResponse]


class MergePreviewResponse(BaseModel):
    """Preview of what a merge would produce."""

    surviving_loop_id: int
    duplicate_loop_id: int
    merged_title: str | None
    merged_summary: str | None
    merged_tags: List[str]
    merged_next_action: str | None
    field_conflicts: Dict[str, Dict[str, Any]]


class MergeRequest(BaseModel):
    """Request to merge a duplicate loop into another."""

    target_loop_id: int
    field_overrides: Dict[str, str | None] | None = None


class MergeResultResponse(BaseModel):
    """Result of a completed merge operation."""

    surviving_loop_id: int
    closed_loop_id: int
    merged_tags: List[str]
    fields_updated: List[str]


class RelationshipReviewCandidateResponse(LoopResponse):
    """A related or duplicate candidate surfaced for relationship review."""

    relationship_type: Literal["related", "duplicate"]
    score: float
    raw_text_preview: str
    existing_state: str | None = None
    existing_source: str | None = None


class LoopRelationshipReviewResponse(BaseModel):
    """Relationship-review payload for one loop."""

    loop: LoopResponse
    indexed_count: int
    candidate_count: int
    duplicate_count: int
    related_count: int
    duplicate_candidates: List[RelationshipReviewCandidateResponse]
    related_candidates: List[RelationshipReviewCandidateResponse]
    existing_duplicates: List[RelationshipReviewCandidateResponse] = Field(default_factory=list)
    existing_related: List[RelationshipReviewCandidateResponse] = Field(default_factory=list)


class LoopRelationshipReviewQueueItemResponse(BaseModel):
    """One loop with pending relationship-review candidates."""

    loop: LoopResponse
    duplicate_count: int
    related_count: int
    top_score: float
    duplicate_candidates: List[RelationshipReviewCandidateResponse]
    related_candidates: List[RelationshipReviewCandidateResponse]


class LoopRelationshipReviewQueueResponse(BaseModel):
    """Relationship-review queue across multiple loops."""

    status: str
    relationship_kind: Literal["all", "duplicate", "related"]
    limit: int
    candidate_limit: int
    indexed_count: int
    loop_count: int
    items: List[LoopRelationshipReviewQueueItemResponse]


class RelationshipReviewActionCreateRequest(BaseModel):
    """Create a saved relationship-review action."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["confirm", "dismiss"]
    relationship_type: Literal["suggested", "related", "duplicate"] = "suggested"
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class RelationshipReviewActionUpdateRequest(BaseModel):
    """Update a saved relationship-review action."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["confirm", "dismiss"] | None = None
    relationship_type: Literal["suggested", "related", "duplicate"] | None = None
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class RelationshipReviewActionResponse(BaseModel):
    """Saved relationship-review action response."""

    id: int
    name: str
    review_kind: Literal["relationship"] = "relationship"
    action_type: Literal["confirm", "dismiss"]
    relationship_type: Literal["suggested", "related", "duplicate"]
    description: str | None = None
    created_at_utc: str
    updated_at_utc: str


class RelationshipReviewSessionCreateRequest(BaseModel):
    """Create a saved relationship-review session."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    query: str = Field(..., min_length=1, max_length=SEARCH_QUERY_MAX)
    relationship_kind: Literal["all", "duplicate", "related"] = "all"
    candidate_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)
    current_loop_id: int | None = None


class RelationshipReviewSessionUpdateRequest(BaseModel):
    """Update a saved relationship-review session."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    relationship_kind: Literal["all", "duplicate", "related"] | None = None
    candidate_limit: int | None = Field(default=None, ge=1, le=20)
    item_limit: int | None = Field(default=None, ge=1, le=100)
    current_loop_id: int | None = None


class RelationshipReviewSessionResponse(BaseModel):
    """Saved relationship-review session metadata."""

    id: int
    name: str
    review_kind: Literal["relationship"] = "relationship"
    query: str
    relationship_kind: Literal["all", "duplicate", "related"]
    candidate_limit: int
    item_limit: int
    current_loop_id: int | None = None
    created_at_utc: str
    updated_at_utc: str


class RelationshipReviewSessionSnapshotResponse(BaseModel):
    """Session snapshot for relationship review."""

    session: RelationshipReviewSessionResponse
    loop_count: int
    current_index: int | None = None
    current_item: LoopRelationshipReviewQueueItemResponse | None = None
    items: List[LoopRelationshipReviewQueueItemResponse]


class RelationshipReviewSessionActionRequest(BaseModel):
    """Run a relationship-review action inside a saved session."""

    loop_id: int
    candidate_loop_id: int
    candidate_relationship_type: Literal["related", "duplicate"]
    action_preset_id: int | None = None
    action_type: Literal["confirm", "dismiss"] | None = None
    relationship_type: Literal["suggested", "related", "duplicate"] | None = None


class RelationshipReviewSessionActionResponse(BaseModel):
    """Result of a relationship-review session action."""

    result: "RelationshipDecisionResponse"
    snapshot: RelationshipReviewSessionSnapshotResponse


class EnrichmentReviewQueueItemResponse(BaseModel):
    """One loop with pending enrichment follow-up work."""

    loop: LoopResponse
    pending_suggestion_count: int
    pending_clarification_count: int
    newest_pending_at: str
    pending_suggestions: List["SuggestionResponse"]
    pending_clarifications: List["ClarificationResponse"]


class EnrichmentReviewActionCreateRequest(BaseModel):
    """Create a saved enrichment-review action."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["apply", "reject"]
    fields: List[str] | None = None
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class EnrichmentReviewActionUpdateRequest(BaseModel):
    """Update a saved enrichment-review action."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["apply", "reject"] | None = None
    fields: List[str] | None = None
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class EnrichmentReviewActionResponse(BaseModel):
    """Saved enrichment-review action response."""

    id: int
    name: str
    review_kind: Literal["enrichment"] = "enrichment"
    action_type: Literal["apply", "reject"]
    fields: List[str] | None = None
    description: str | None = None
    created_at_utc: str
    updated_at_utc: str


class EnrichmentReviewSessionCreateRequest(BaseModel):
    """Create a saved enrichment-review session."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    query: str = Field(..., min_length=1, max_length=SEARCH_QUERY_MAX)
    pending_kind: Literal["all", "suggestions", "clarifications"] = "all"
    suggestion_limit: int = Field(default=3, ge=1, le=20)
    clarification_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)
    current_loop_id: int | None = None


class EnrichmentReviewSessionUpdateRequest(BaseModel):
    """Update a saved enrichment-review session."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    pending_kind: Literal["all", "suggestions", "clarifications"] | None = None
    suggestion_limit: int | None = Field(default=None, ge=1, le=20)
    clarification_limit: int | None = Field(default=None, ge=1, le=20)
    item_limit: int | None = Field(default=None, ge=1, le=100)
    current_loop_id: int | None = None


class EnrichmentReviewSessionResponse(BaseModel):
    """Saved enrichment-review session metadata."""

    id: int
    name: str
    review_kind: Literal["enrichment"] = "enrichment"
    query: str
    pending_kind: Literal["all", "suggestions", "clarifications"]
    suggestion_limit: int
    clarification_limit: int
    item_limit: int
    current_loop_id: int | None = None
    created_at_utc: str
    updated_at_utc: str


class EnrichmentReviewSessionSnapshotResponse(BaseModel):
    """Session snapshot for enrichment review."""

    session: EnrichmentReviewSessionResponse
    loop_count: int
    current_index: int | None = None
    current_item: EnrichmentReviewQueueItemResponse | None = None
    items: List[EnrichmentReviewQueueItemResponse]


class EnrichmentReviewSessionActionRequest(BaseModel):
    """Run an enrichment-review action inside a saved session."""

    suggestion_id: int
    action_preset_id: int | None = None
    action_type: Literal["apply", "reject"] | None = None
    fields: List[str] | None = None


class EnrichmentReviewActionResultResponse(BaseModel):
    """Normalized result of applying or rejecting a suggestion."""

    suggestion_id: int
    resolution: str
    loop: LoopResponse | None = None
    applied_fields: List[str] = Field(default_factory=list)


class EnrichmentReviewSessionActionResponse(BaseModel):
    """Result of an enrichment-review session action."""

    result: EnrichmentReviewActionResultResponse
    snapshot: EnrichmentReviewSessionSnapshotResponse


class EnrichmentReviewSessionClarificationRequest(BaseModel):
    """Answer clarifications inside a saved enrichment session."""

    loop_id: int
    answers: List["ClarificationSubmitRequest"]


class EnrichmentReviewSessionClarificationResponse(BaseModel):
    """Result of answering clarifications inside a saved enrichment session."""

    result: "ClarificationSubmitResponse"
    snapshot: EnrichmentReviewSessionSnapshotResponse


class RelationshipDecisionRequest(BaseModel):
    """Confirm or dismiss one relationship candidate."""

    relationship_type: Literal["related", "duplicate"]


class RelationshipDecisionResponse(BaseModel):
    """Result of confirming or dismissing one relationship candidate."""

    loop_id: int
    candidate_loop_id: int
    relationship_type: Literal["related", "duplicate"]
    link_state: Literal["active", "dismissed"]


class ApplySuggestionRequest(BaseModel):
    """Request to apply a loop suggestion."""

    fields: List[str] | None = None


class ApplySuggestionResponse(BaseModel):
    """Result of applying a suggestion."""

    loop: dict[str, Any]
    suggestion_id: int
    applied_fields: List[str]
    resolution: str


class RejectSuggestionResponse(BaseModel):
    """Result of rejecting a suggestion."""

    suggestion_id: int
    resolution: str


class ClarificationSubmitRequest(BaseModel):
    """Request to submit an answer to a clarification question."""

    clarification_id: int = Field(..., description="ID of the clarification to answer")
    answer: str = Field(..., min_length=1, max_length=1000, description="User's answer")


class ClarificationSubmitBatchRequest(BaseModel):
    """Request to submit answers to multiple clarification questions at once."""

    answers: List[ClarificationSubmitRequest] = Field(
        ...,
        description="List of clarification_id + answer pairs for existing clarifications",
    )


class ClarificationResponse(BaseModel):
    """A single clarification with optional answer."""

    id: int
    loop_id: int
    question: str
    answer: str | None = None
    answered_at: str | None = None
    created_at: str


class SuggestionResponse(BaseModel):
    """A single suggestion with parsed data and linked clarifications."""

    id: int
    loop_id: int
    suggestion_json: str
    parsed: dict[str, Any]
    clarifications: List[ClarificationResponse] = Field(default_factory=list)
    model: str
    created_at: str
    resolution: str | None = None
    resolved_at: str | None = None
    resolved_fields_json: str | None = None


class SuggestionListResponse(BaseModel):
    """List of suggestions."""

    suggestions: List[SuggestionResponse]
    count: int


class ClarificationListResponse(BaseModel):
    """List of clarifications for a loop."""

    clarifications: List[ClarificationResponse]
    count: int


class ClarificationSubmitResponse(BaseModel):
    """Response after submitting clarification answers."""

    loop_id: int
    answered_count: int
    clarifications: List[ClarificationResponse]
    superseded_suggestion_ids: List[int] = Field(default_factory=list)
    message: str = "Clarifications recorded. Re-enrich to generate an updated suggestion."


# Resolve forward references
LoopCommentResponse.model_rebuild()
RelationshipReviewSessionActionResponse.model_rebuild()
EnrichmentReviewQueueItemResponse.model_rebuild()
EnrichmentReviewSessionClarificationRequest.model_rebuild()
EnrichmentReviewSessionClarificationResponse.model_rebuild()
