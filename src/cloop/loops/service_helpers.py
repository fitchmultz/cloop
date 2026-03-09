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

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from . import repo
from .claim_state import validate_claim_for_update
from .models import LoopRecord, LoopStatus, format_utc_datetime, utc_now
from .serialization import enrich_loop_records_batch, loop_record_to_dict

if TYPE_CHECKING:
    pass

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
