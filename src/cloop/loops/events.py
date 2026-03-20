"""Loop event history and undo functionality.

Purpose:
    Provide event history tracking and freshness-safe undo capabilities for
    loops, including pagination and reversible event handling.

Responsibilities:
    - Retrieve paginated event history for loops
    - Identify reversible event types
    - Perform one-step undo of a specific latest reversible event
    - Record undo events for audit trail

Non-scope:
    - Direct database access (see repo.py)
    - Event recording during normal operations (see service.py)
    - HTTP request/response handling (see routes/loops.py)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .. import typingx
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import LoopNotFoundError, UndoNotPossibleError
from .write_ops import _record_to_dict, _validate_claim_for_update

# ============================================================================
# Event History and Undo Service Functions
# ============================================================================

_REVERSIBLE_EVENT_TYPES = frozenset({"update", "status_change", "close"})


@typingx.validate_io()
def get_loop_events(
    *,
    loop_id: int,
    limit: int = 50,
    before_id: int | None = None,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get event history for a loop.

    Args:
        loop_id: Loop to query
        limit: Max results (default 50)
        before_id: Pagination cursor - only events with id < before_id
        conn: Database connection

    Returns:
        List of event dicts with human-readable timestamps and parsed payloads

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    events = repo.list_loop_events_paginated(
        loop_id=loop_id,
        limit=limit,
        before_id=before_id,
        conn=conn,
    )

    result = []
    for event in events:
        payload = json.loads(event["payload_json"]) if event["payload_json"] else {}
        result.append(
            {
                "id": event["id"],
                "loop_id": event["loop_id"],
                "event_type": event["event_type"],
                "payload": payload,
                "created_at_utc": event["created_at"],
                "is_reversible": event["event_type"] in _REVERSIBLE_EVENT_TYPES,
            }
        )

    return result


def _restore_update_before_state(
    *,
    loop_id: int,
    before_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> Any:
    """Restore fields captured by a reversible update event."""
    restore_fields = dict(before_state)
    previous_tags = restore_fields.pop("tags", None)

    if not restore_fields and previous_tags is None:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="empty_before_state",
            message="Update event has no fields to restore",
        )

    updated = None
    if restore_fields:
        updated = repo.update_loop_fields(loop_id=loop_id, fields=restore_fields, conn=conn)
    if previous_tags is not None:
        repo.replace_loop_tags(loop_id=loop_id, tag_names=list(previous_tags), conn=conn)
    if updated is None:
        updated = repo.read_loop(loop_id=loop_id, conn=conn)
    if updated is None:
        raise LoopNotFoundError(loop_id)
    return updated


@typingx.validate_io()
def undo_last_event(
    *,
    loop_id: int,
    expected_event_id: int,
    claim_token: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Undo the current latest reversible event for a loop.

    This performs a one-step rollback by:
    1. Finding the latest reversible event
    2. Verifying it matches the expected event handle
    3. Extracting the before_state from its payload
    4. Applying the inverse mutation
    5. Recording an undo event for audit trail

    Args:
        loop_id: Loop to modify
        expected_event_id: Exact reversible event ID the caller intends to undo
        claim_token: Required if loop is claimed
        conn: Database connection

    Returns:
        Dict with updated loop and undo details.

    Raises:
        LoopNotFoundError: If loop doesn't exist
        UndoNotPossibleError: If the requested event is stale or not reversible
    """
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

    event = repo.get_latest_reversible_event(loop_id=loop_id, conn=conn)
    if event is None:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="no_reversible_events",
            message="No reversible events found for this loop",
        )
    if int(event["id"]) != expected_event_id:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="stale_event_handle",
            message=(
                f"expected reversible event {expected_event_id}, but loop {loop_id} now "
                f"requires undoing event {int(event['id'])} first"
            ),
        )

    payload = json.loads(event["payload_json"]) if event["payload_json"] else {}
    before_state = dict(payload.get("before_state") or {})
    if not before_state:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="missing_before_state",
            message=f"Event {event['id']} lacks before_state needed for undo",
        )

    event_type = str(event["event_type"])
    with conn:
        if event_type in {"status_change", "close"}:
            old_status = before_state.get("status")
            if not old_status:
                raise UndoNotPossibleError(
                    loop_id=loop_id,
                    reason="invalid_before_state",
                    message="Status change event missing previous status",
                )
            restore_fields = {
                "status": old_status,
                "closed_at": before_state.get("closed_at"),
                "completion_note": before_state.get("completion_note"),
                "recurrence_enabled": before_state.get("recurrence_enabled"),
            }
            updated = repo.update_loop_fields(
                loop_id=loop_id,
                fields=restore_fields,
                conn=conn,
            )
        elif event_type == "update":
            updated = _restore_update_before_state(
                loop_id=loop_id,
                before_state=before_state,
                conn=conn,
            )
        else:
            raise UndoNotPossibleError(
                loop_id=loop_id,
                reason="unsupported_event_type",
                message=f"Event type '{event_type}' is not supported for undo",
            )

        undo_payload = {
            "undone_event_id": int(event["id"]),
            "undone_event_type": event_type,
            "restored_fields": before_state,
        }
        undo_event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type="undo",
            payload=undo_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=undo_event_id,
            event_type="undo",
            payload={
                "undone_event_id": int(event["id"]),
                "undone_event_type": event_type,
            },
            conn=conn,
        )

    project = repo.read_project_name(project_id=updated.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
    loop_payload = _record_to_dict(updated, project=project, tags=tags)
    latest_reversible_event = repo.get_latest_reversible_event(loop_id=updated.id, conn=conn)
    loop_payload["latest_reversible_event_id"] = (
        int(latest_reversible_event["id"]) if latest_reversible_event is not None else None
    )
    loop_payload["latest_reversible_event_type"] = (
        str(latest_reversible_event["event_type"]) if latest_reversible_event is not None else None
    )

    return {
        "loop": loop_payload,
        "undone_event_id": int(event["id"]),
        "undone_event_type": event_type,
        "undo_event_id": undo_event_id,
    }
