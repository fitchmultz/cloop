"""
Loop domain models.

Purpose: Define core domain types for the loop management system including
loop records, events, claims, time tracking sessions, and comments.

Responsibilities:
- Loop status enum and transitions
- LoopRecord dataclass with all loop fields
- LoopEvent types for audit trail
- TimeSession and TimerStatus for time tracking
- LoopComment for threaded discussion
- Datetime parsing/formatting helpers (always UTC internally)

Non-scope: Database operations (see repo.py), business logic (see service.py)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from ..constants import MAX_TZ_OFFSET_MIN, MIN_TZ_OFFSET_MIN
from .errors import ValidationError


class LoopStatus(StrEnum):
    INBOX = "inbox"
    ACTIONABLE = "actionable"
    BLOCKED = "blocked"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    DROPPED = "dropped"


TERMINAL_STATUSES: frozenset[LoopStatus] = frozenset(
    {
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    }
)


def is_terminal_status(status: LoopStatus) -> bool:
    """Check if a status represents a terminal (closed) state.

    Terminal statuses are final states from which a loop cannot transition
    except via reopening.

    Args:
        status: The loop status to check

    Returns:
        True if the status is COMPLETED or DROPPED
    """
    return status in TERMINAL_STATUSES


def resolve_status_from_flags(
    scheduled: bool,
    blocked: bool,
    actionable: bool,
) -> LoopStatus:
    """Resolve loop status from boolean flags.

    Precedence order: scheduled > blocked > actionable > inbox.

    Args:
        scheduled: True if the loop is scheduled
        blocked: True if the loop is blocked
        actionable: True if the loop is actionable

    Returns:
        The resolved LoopStatus based on flag precedence
    """
    if scheduled:
        return LoopStatus.SCHEDULED
    if blocked:
        return LoopStatus.BLOCKED
    if actionable:
        return LoopStatus.ACTIONABLE
    return LoopStatus.INBOX


class LoopEventType(StrEnum):
    CAPTURE = "capture"
    UPDATE = "update"
    STATUS_CHANGE = "status_change"
    CLOSE = "close"
    ENRICH_REQUEST = "enrich_requested"
    ENRICH_SUCCESS = "enrich_succeeded"
    ENRICH_FAILURE = "enrich_failed"
    CLAIM = "claim"
    CLAIM_RELEASED = "claim_released"
    CLAIM_EXPIRED = "claim_expired"
    TIMER_STARTED = "timer_started"
    TIMER_STOPPED = "timer_stopped"
    COMMENT_ADDED = "comment_added"
    COMMENT_UPDATED = "comment_updated"
    COMMENT_DELETED = "comment_deleted"


class EnrichmentState(StrEnum):
    IDLE = "idle"
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LoopRecord:
    id: int
    raw_text: str
    title: str | None
    summary: str | None
    definition_of_done: str | None
    next_action: str | None
    status: LoopStatus
    captured_at_utc: datetime
    captured_tz_offset_min: int
    due_at_utc: datetime | None
    snooze_until_utc: datetime | None
    time_minutes: int | None
    activation_energy: int | None
    urgency: float | None
    importance: float | None
    project_id: int | None
    blocked_reason: str | None
    completion_note: str | None
    user_locks: list[str]
    provenance: dict[str, object]
    enrichment_state: EnrichmentState
    recurrence_rrule: str | None
    recurrence_tz: str | None
    next_due_at_utc: datetime | None
    recurrence_enabled: bool
    parent_loop_id: int | None
    created_at_utc: datetime
    updated_at_utc: datetime
    closed_at_utc: datetime | None

    def is_recurring(self) -> bool:
        """Check if this loop has an active recurrence schedule."""
        return self.recurrence_enabled and self.recurrence_rrule is not None


@dataclass(frozen=True, slots=True)
class LoopClaim:
    loop_id: int
    owner: str
    claim_token: str
    leased_at_utc: datetime
    lease_until_utc: datetime


@dataclass(frozen=True, slots=True)
class LoopClaimSummary:
    """Claim information without sensitive token (for list operations)."""

    loop_id: int
    owner: str
    leased_at_utc: datetime
    lease_until_utc: datetime


@dataclass(frozen=True, slots=True)
class TimeSession:
    """A time tracking session for a loop."""

    id: int
    loop_id: int
    started_at_utc: datetime
    ended_at_utc: datetime | None
    duration_seconds: int | None
    notes: str | None
    created_at_utc: datetime

    @property
    def is_active(self) -> bool:
        """Returns True if this session is still running."""
        return self.ended_at_utc is None

    @property
    def elapsed_seconds(self) -> int:
        """Returns duration if stopped, or current elapsed if active."""
        if self.duration_seconds is not None:
            return self.duration_seconds
        # Calculate elapsed time for active session
        return int((utc_now() - self.started_at_utc).total_seconds())


@dataclass(frozen=True, slots=True)
class TimerStatus:
    """Current timer status for a loop."""

    loop_id: int
    has_active_session: bool
    active_session: TimeSession | None
    total_tracked_seconds: int
    estimated_minutes: int | None


def _normalize_iso(value: str) -> str:
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def validate_iso8601_timestamp(value: str, field_name: str = "timestamp") -> str:
    """Validate that a string is a valid ISO8601 timestamp.

    This function raises ValidationError for typed exception handling
    in both HTTP and MCP layers.

    Args:
        value: The timestamp string to validate
        field_name: Name of the field for error messages

    Returns:
        The original value if valid

    Raises:
        ValidationError: If the value is not a valid ISO8601 timestamp
    """
    if not value:
        raise ValidationError(field_name, "value cannot be empty")

    try:
        # Normalize 'Z' suffix to '+00:00' for consistency
        normalized = _normalize_iso(value)
        datetime.fromisoformat(normalized)
    except ValueError:
        truncated = value[:50] + "..." if len(value) > 50 else value
        raise ValidationError(
            field_name,
            f"'{truncated}' is not a valid ISO8601 timestamp. "
            f"Expected format: 2024-01-15T10:30:00+00:00",
        ) from None

    return value


def parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(_normalize_iso(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_tz_offset(value: int, field_name: str = "tz_offset_min") -> int:
    """Validate that a timezone offset is within valid bounds.

    Args:
        value: The timezone offset in minutes
        field_name: Name of the field for error messages

    Returns:
        The original value if valid

    Raises:
        ValidationError: If the value is outside the valid range
    """
    if not (MIN_TZ_OFFSET_MIN <= value <= MAX_TZ_OFFSET_MIN):
        raise ValidationError(
            field_name, f"{value} is outside valid range [{MIN_TZ_OFFSET_MIN}, {MAX_TZ_OFFSET_MIN}]"
        )
    return value


def parse_client_datetime(value: str, *, tz_offset_min: int) -> datetime:
    validate_tz_offset(tz_offset_min, "tz_offset_min")
    parsed = datetime.fromisoformat(_normalize_iso(value))
    if parsed.tzinfo is None:
        offset = timezone(timedelta(minutes=tz_offset_min))
        parsed = parsed.replace(tzinfo=offset)
    return parsed.astimezone(timezone.utc)


def format_utc_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class LoopComment:
    """A threaded comment on a loop."""

    id: int
    loop_id: int
    parent_id: int | None
    author: str
    body_md: str
    created_at_utc: datetime
    updated_at_utc: datetime
    deleted_at_utc: datetime | None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at_utc is not None

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None
