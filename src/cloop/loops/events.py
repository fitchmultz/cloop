"""Loop event history and undo functionality.

Purpose:
    Provide event history tracking and undo capabilities for loops,
    including pagination and reversible event handling.

Responsibilities:
    - Retrieve paginated event history for loops
    - Identify reversible event types
    - Perform one-step undo of reversible events
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
from .service_helpers import _record_to_dict, _validate_claim_for_update

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
    # Verify loop exists
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    events = repo.list_loop_events_paginated(
        loop_id=loop_id,
        limit=limit,
        before_id=before_id,
        conn=conn,
    )

    # Parse payloads and format for API response
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


@typingx.validate_io()
def undo_last_event(
    *,
    loop_id: int,
    claim_token: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Undo the most recent reversible event for a loop.

    This performs a one-step rollback by:
    1. Finding the latest reversible event
    2. Extracting the before_state from its payload
    3. Applying the inverse mutation
    4. Recording an undo event for audit trail

    Args:
        loop_id: Loop to modify
        claim_token: Required if loop is claimed
        conn: Database connection

    Returns:
        Dict with updated loop and undo details:
        - loop: The updated loop dict
        - undone_event_id: ID of the event that was undone
        - undone_event_type: Type of the undone event

    Raises:
        LoopNotFoundError: If loop doesn't exist
        UndoNotPossibleError: If no reversible event exists
        LoopClaimedError: If loop is claimed and token is invalid
        ClaimNotFoundError: If claim_token is invalid
    """
    # Verify loop exists and check claim
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

    # Find latest reversible event
    event = repo.get_latest_reversible_event(loop_id=loop_id, conn=conn)
    if event is None:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="no_reversible_events",
            message="No reversible events found for this loop",
        )

    payload = json.loads(event["payload_json"]) if event["payload_json"] else {}
    before_state = payload.get("before_state", {})

    if not before_state:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="missing_before_state",
            message=f"Event {event['id']} lacks before_state needed for undo",
        )

    event_type = event["event_type"]

    with conn:
        if event_type == "status_change" or event_type == "close":
            # Restore previous status
            old_status = before_state.get("status")
            if old_status:
                restore_fields: dict[str, Any] = {"status": old_status}
                # Restore closed_at if it was set before
                old_closed_at = before_state.get("closed_at")
                restore_fields["closed_at"] = old_closed_at
                updated = repo.update_loop_fields(
                    loop_id=loop_id,
                    fields=restore_fields,
                    conn=conn,
                )
            else:
                raise UndoNotPossibleError(
                    loop_id=loop_id,
                    reason="invalid_before_state",
                    message="Status change event missing previous status",
                )

        elif event_type == "update":
            # Restore all changed fields
            restore_fields = {}
            for field, old_value in before_state.items():
                restore_fields[field] = old_value

            if not restore_fields:
                raise UndoNotPossibleError(
                    loop_id=loop_id,
                    reason="empty_before_state",
                    message="Update event has no fields to restore",
                )

            updated = repo.update_loop_fields(
                loop_id=loop_id,
                fields=restore_fields,
                conn=conn,
            )

        else:
            # Should not reach here if _REVERSIBLE_EVENT_TYPES is correct
            raise UndoNotPossibleError(
                loop_id=loop_id,
                reason="unsupported_event_type",
                message=f"Event type '{event_type}' is not supported for undo",
            )

        # Record undo event for audit trail
        undo_event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type="undo",
            payload={
                "undone_event_id": event["id"],
                "undone_event_type": event_type,
                "restored_fields": before_state,
            },
            conn=conn,
        )

        # Queue webhook delivery if configured
        queue_deliveries(
            event_id=undo_event_id,
            event_type="undo",
            payload={
                "undone_event_id": event["id"],
                "undone_event_type": event_type,
            },
            conn=conn,
        )

    project = repo.read_project_name(project_id=updated.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)

    return {
        "loop": _record_to_dict(updated, project=project, tags=tags),
        "undone_event_id": event["id"],
        "undone_event_type": event_type,
    }
