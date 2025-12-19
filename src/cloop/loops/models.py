from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum


class LoopStatus(StrEnum):
    INBOX = "inbox"
    ACTIONABLE = "actionable"
    BLOCKED = "blocked"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    DROPPED = "dropped"


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


def parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(_normalize_iso(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_client_datetime(value: str, *, tz_offset_min: int) -> datetime:
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
