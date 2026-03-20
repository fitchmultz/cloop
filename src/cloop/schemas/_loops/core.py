"""Core loop request/response schemas.

Purpose:
    Define capture, CRUD, import/export, and search models for core loop workflows.

Responsibilities:
    - Validate core loop capture and update payloads
    - Define canonical loop response/export models
    - Shape DSL and semantic search request/response envelopes

Non-scope:
    - Saved views, webhooks, or review-workflow models
    - Timer, dependency, or relationship-review schemas
    - Business-rule execution outside field validation
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from ._shared import (
    BLOCKED_REASON_MAX,
    COMPLETION_NOTE_MAX,
    DEFINITION_OF_DONE_MAX,
    NEXT_ACTION_MAX,
    PROJECT_MAX,
    RAW_TEXT_MAX,
    RRULE_MAX,
    SCHEDULE_MAX,
    SEARCH_QUERY_MAX,
    SUMMARY_MAX,
    TIMEZONE_MAX,
    TITLE_MAX,
    BaseModel,
    Field,
    LoopStatus,
    field_validator,
    validate_due_date,
)

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
        from ...loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "due_at_utc")

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, v: str) -> str:
        from ...loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "captured_at")

    @field_validator("client_tz_offset_min")
    @classmethod
    def validate_tz_offset(cls, v: int) -> int:
        from ...loops.models import validate_tz_offset

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
        from ...loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "due_at_utc")

    @field_validator("snooze_until_utc", mode="before")
    @classmethod
    def validate_snooze_until_utc(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from ...loops.models import validate_iso8601_timestamp

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
    latest_reversible_event_id: int | None = None
    latest_reversible_event_type: str | None = None


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
