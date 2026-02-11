from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

# Timezone offset validation constants
# Python's timezone class requires offsets strictly between -24 and +24 hours,
# so we use [-1439, +1439] minutes (exclusive of exactly ±24h)
MIN_TZ_OFFSET_MIN = -1439
MAX_TZ_OFFSET_MIN = 1439


class LoopStatus(StrEnum):
    INBOX = "inbox"
    ACTIONABLE = "actionable"
    BLOCKED = "blocked"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    DROPPED = "dropped"


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
    created_at_utc: datetime
    updated_at_utc: datetime
    closed_at_utc: datetime | None


def _normalize_iso(value: str) -> str:
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def validate_iso8601_timestamp(value: str, field_name: str = "timestamp") -> str:
    """Validate that a string is a valid ISO8601 timestamp.

    This function is used as a Pydantic field validator and therefore
    raises ValueError (not ValidationError) for compatibility with
    Pydantic's validation error handling.

    Args:
        value: The timestamp string to validate
        field_name: Name of the field for error messages

    Returns:
        The original value if valid

    Raises:
        ValueError: If the value is not a valid ISO8601 timestamp
    """
    if not value:
        raise ValueError(f"invalid_{field_name}: value cannot be empty")

    try:
        # Normalize 'Z' suffix to '+00:00' for consistency
        normalized = _normalize_iso(value)
        datetime.fromisoformat(normalized)
    except ValueError:
        truncated = value[:50] + "..." if len(value) > 50 else value
        raise ValueError(
            f"invalid_{field_name}: '{truncated}' is not a valid ISO8601 timestamp. "
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
        ValueError: If the value is outside the valid range
    """
    if not (MIN_TZ_OFFSET_MIN <= value <= MAX_TZ_OFFSET_MIN):
        raise ValueError(
            f"invalid_{field_name}: {value} is outside valid range "
            f"[{MIN_TZ_OFFSET_MIN}, {MAX_TZ_OFFSET_MIN}]"
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
