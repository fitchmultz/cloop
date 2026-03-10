"""Shared service helpers to prevent circular imports.

Purpose:
    Provide helper functions and constants used by both service.py
    and its submodules (bulk.py, events.py) to avoid circular imports.

Responsibilities:
    - Loop record conversion to dict
    - Batch enrichment of records
    - Recurrence handling on completion
    - Claim validation for updates
    - State transition constants

Non-scope:
    - Business logic orchestration (see service.py)
    - Domain-specific operations (see claims.py, timers.py, etc.)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from typing import Any

from ..webhooks.service import queue_deliveries
from . import repo
from .claim_state import validate_claim_for_update
from .errors import DependencyNotMetError, LoopNotFoundError, TransitionError, ValidationError
from .metrics import record_transition, record_update
from .models import (
    LoopEventType,
    LoopRecord,
    LoopStatus,
    format_utc_datetime,
    is_terminal_status,
    utc_now,
)
from .serialization import enrich_loop_records_batch, loop_record_to_dict
from .utils import normalize_tags

logger = logging.getLogger(__name__)

_ALLOWED_TRANSITIONS: dict[LoopStatus, set[LoopStatus]] = {
    LoopStatus.INBOX: {
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.ACTIONABLE: {
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.BLOCKED: {
        LoopStatus.ACTIONABLE,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.SCHEDULED: {
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.COMPLETED: {
        LoopStatus.INBOX,
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.DROPPED,
    },
    LoopStatus.DROPPED: {
        LoopStatus.INBOX,
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
    },
}

_LOCKABLE_FIELDS = {
    "raw_text",
    "title",
    "summary",
    "definition_of_done",
    "next_action",
    "due_at_utc",
    "snooze_until_utc",
    "time_minutes",
    "activation_energy",
    "urgency",
    "importance",
    "project_id",
    "blocked_reason",
    "completion_note",
    "tags",
}

_REVERSIBLE_UPDATE_FIELD_ALIASES: dict[str, str] = {
    "title": "title",
    "summary": "summary",
    "definition_of_done": "definition_of_done",
    "next_action": "next_action",
    "due_at_utc": "due_at_utc",
    "snooze_until_utc": "snooze_until_utc",
    "time_minutes": "time_minutes",
    "activation_energy": "activation_energy",
    "urgency": "urgency",
    "importance": "importance",
    "project_id": "project_id",
    "project": "project_id",
    "blocked_reason": "blocked_reason",
}


def _handle_recurrence_on_completion(
    *,
    record: LoopRecord,
    conn: sqlite3.Connection,
) -> int | None:
    """Handle recurring loop completion by creating next occurrence.

    When a recurring loop is completed, this creates a new loop for the
    next scheduled occurrence and disables recurrence on the completed loop.

    Args:
        record: The loop being completed
        conn: Database connection

    Returns:
        The next loop ID if created, None otherwise
    """
    if not record.is_recurring():
        return None
    if record.recurrence_rrule is None or record.recurrence_tz is None:
        return None

    from .recurrence import RecurrenceError, compute_next_due

    now = utc_now()
    try:
        next_due = compute_next_due(
            record.recurrence_rrule,
            record.recurrence_tz,
            now,
        )
    except RecurrenceError:
        # If recurrence computation fails (e.g., corrupted RRULE),
        # don't prevent completion - just don't create next occurrence
        return None
    if next_due is None:
        return None

    # Create new loop for next occurrence
    next_captured_at = format_utc_datetime(now)
    next_loop = repo.create_loop(
        raw_text=record.raw_text,
        captured_at_utc=next_captured_at,
        captured_tz_offset_min=record.captured_tz_offset_min,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    # Update new loop with recurrence info and next due date
    next_due_str = format_utc_datetime(next_due)
    repo.update_loop_fields(
        loop_id=next_loop.id,
        fields={
            "title": record.title,
            "summary": record.summary,
            "definition_of_done": record.definition_of_done,
            "time_minutes": record.time_minutes,
            "activation_energy": record.activation_energy,
            "project_id": record.project_id,
            "recurrence_rrule": record.recurrence_rrule,
            "recurrence_tz": record.recurrence_tz,
            "next_due_at_utc": next_due_str,
            "recurrence_enabled": 1,
        },
        conn=conn,
    )
    # Copy tags to new loop
    existing_tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
    if existing_tags:
        repo.replace_loop_tags(loop_id=next_loop.id, tag_names=existing_tags, conn=conn)

    return next_loop.id


def _record_to_dict(
    record: LoopRecord,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Convert LoopRecord to dict for API response."""
    return loop_record_to_dict(record, project=project, tags=tags)


def _enrich_records_batch(
    records: list[LoopRecord],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Enrich multiple loop records with project names and tags in batch.

    This avoids the N+1 query problem by fetching all projects and tags
    in just 2 queries total, regardless of the number of records.
    """
    return enrich_loop_records_batch(records, conn=conn)


def _enrich_record(
    *,
    record: LoopRecord,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Enrich a single loop record with project name and tags."""
    project = repo.read_project_name(project_id=record.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
    return _record_to_dict(record, project=project, tags=tags)


def _validate_claim_for_update(
    *,
    loop_id: int,
    claim_token: str | None,
    conn: sqlite3.Connection,
) -> None:
    """Validate that the caller has a valid claim on the loop.

    Call this at the start of mutation operations (update_loop, transition_status, etc.)

    Args:
        loop_id: Loop being modified
        claim_token: Token provided by caller (or None)
        conn: Database connection

    Raises:
        LoopClaimedError: If loop is claimed by someone else
        ClaimNotFoundError: If loop is claimed but no/invalid token provided
    """
    validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)


def _capture_update_before_state(
    *,
    record: LoopRecord,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture reversible field values before applying an update."""
    before_state: dict[str, Any] = {}
    seen_record_fields: set[str] = set()

    for incoming_field, record_field in _REVERSIBLE_UPDATE_FIELD_ALIASES.items():
        if incoming_field not in fields or record_field in seen_record_fields:
            continue

        old_value = getattr(record, record_field, None)
        if record_field in {"due_at_utc", "snooze_until_utc"} and old_value is not None:
            before_state[record_field] = format_utc_datetime(old_value)
        else:
            before_state[record_field] = old_value

        seen_record_fields.add(record_field)

    return before_state


def _extract_normalized_tags(fields: dict[str, Any]) -> list[str] | None:
    """Pop and normalize tags from an update payload when present."""
    if "tags" not in fields:
        return None

    raw_tags = fields.pop("tags")
    if raw_tags is None:
        return None
    if not isinstance(raw_tags, list):
        raw_tags = [raw_tags]
    return normalize_tags(raw_tags)


def _resolve_project_field(
    *,
    fields: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Resolve external project input into the canonical project_id field."""
    if "project" not in fields:
        return

    project_name = fields.pop("project")
    normalized_name = str(project_name).strip() if project_name else ""
    fields["project_id"] = (
        repo.upsert_project(name=normalized_name, conn=conn) if normalized_name else None
    )


def _apply_loop_update(
    *,
    loop_id: int,
    fields: Mapping[str, Any],
    conn: sqlite3.Connection,
    claim_token: str | None = None,
) -> LoopRecord:
    """Apply the canonical single-loop field update without owning a transaction."""
    if "status" in fields:
        raise ValidationError("status", "use /loops/{id}/status or /loops/{id}/close endpoints")

    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)

    before_state = _capture_update_before_state(record=record, fields=fields)
    mutable_fields = dict(fields)
    normalized_tags = _extract_normalized_tags(mutable_fields)
    _resolve_project_field(fields=mutable_fields, conn=conn)

    locked_fields = set(record.user_locks)
    lock_targets = set(mutable_fields.keys())
    if normalized_tags is not None:
        lock_targets.add("tags")
    for field_name in lock_targets:
        if field_name in _LOCKABLE_FIELDS:
            locked_fields.add(field_name)

    updated_fields = dict(mutable_fields)
    updated_fields["user_locks_json"] = json.dumps(sorted(locked_fields))
    updated = repo.update_loop_fields(loop_id=loop_id, fields=updated_fields, conn=conn)
    record_update()

    if normalized_tags is not None:
        repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
    if "next_action" in fields and fields["next_action"] is not None:
        repo.reset_nudge_state(loop_id=loop_id, nudge_type="due_soon", conn=conn)

    event_payload: dict[str, Any] = {"fields": dict(fields)}
    if before_state:
        event_payload["before_state"] = before_state
    event_id = repo.insert_loop_event(
        loop_id=updated.id,
        event_type=LoopEventType.UPDATE.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.UPDATE.value,
        payload=event_payload,
        conn=conn,
    )

    return updated


def _apply_status_transition(
    *,
    loop_id: int,
    to_status: LoopStatus,
    conn: sqlite3.Connection,
    note: str | None = None,
    claim_token: str | None = None,
) -> LoopRecord:
    """Apply the canonical single-loop status transition without owning a transaction."""
    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)
    if record.status == to_status:
        return record

    allowed = _ALLOWED_TRANSITIONS.get(record.status, set())
    if to_status not in allowed:
        raise TransitionError(record.status.value, to_status.value)

    if to_status == LoopStatus.ACTIONABLE:
        open_deps = repo.list_open_dependencies(loop_id=loop_id, conn=conn)
        if open_deps:
            raise DependencyNotMetError(loop_id, open_deps)

    before_state: dict[str, Any] = {"status": record.status.value}
    if record.closed_at_utc is not None:
        before_state["closed_at"] = format_utc_datetime(record.closed_at_utc)

    closed_at = format_utc_datetime(utc_now()) if is_terminal_status(to_status) else None

    next_loop_id: int | None = None
    if to_status == LoopStatus.COMPLETED:
        next_loop_id = _handle_recurrence_on_completion(record=record, conn=conn)

    updates: dict[str, Any] = {"status": to_status.value, "closed_at": closed_at}
    if to_status is LoopStatus.COMPLETED and note and note.strip():
        updates["completion_note"] = note.strip()
    if to_status == LoopStatus.COMPLETED and record.is_recurring():
        updates["recurrence_enabled"] = 0

    updated = repo.update_loop_fields(loop_id=loop_id, fields=updates, conn=conn)
    record_transition(record.status.value, to_status.value)

    event_type = (
        LoopEventType.CLOSE.value
        if is_terminal_status(to_status)
        else LoopEventType.STATUS_CHANGE.value
    )
    payload: dict[str, Any] = {
        "from": record.status.value,
        "to": to_status.value,
        "before_state": before_state,
    }
    if note:
        payload["note"] = note
    if closed_at:
        payload["closed_at_utc"] = closed_at
    if next_loop_id is not None:
        payload["next_occurrence_loop_id"] = next_loop_id

    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=event_type,
        payload=payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        conn=conn,
    )

    return updated
