"""Loop/task management request/response models.

Models for the /loops/* endpoints supporting:
- Loop capture and CRUD
- Status transitions
- Prioritized "next actions" view
- Export/import for data portability
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator

from ..loops.models import LoopStatus


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
