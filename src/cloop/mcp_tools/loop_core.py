"""Core loop mutation MCP tools.

Purpose:
    MCP tools for creating, updating, and closing loops.

Responsibilities:
    - Create new loops with optional recurrence
    - Update loop fields with claim token validation
    - Close loops with terminal status (completed/dropped)
    - Retrieve single loop by ID
    - Transition loops between non-terminal statuses
    - Validate timestamps, timezone offsets, and status transitions
    - Handle idempotency for all mutations

Tools:
    - loop.create: Capture a new loop
    - loop.update: Update loop fields
    - loop.close: Close with terminal status
    - loop.get: Retrieve single loop
    - loop.transition: Non-terminal status change

Non-scope:
    - Read-only operations (see loop_read.py)
    - Bulk operations (see loop_bulk.py)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import db
from ..loops import service as loop_service
from ..loops.errors import ValidationError
from ..loops.models import (
    LoopStatus,
    is_terminal_status,
    validate_iso8601_timestamp,
    validate_tz_offset,
)
from ..settings import get_settings
from ._idempotency import (
    finalize_tool_idempotency,
    prepare_tool_idempotency,
    replay_tool_response,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def loop_create(
    raw_text: str,
    captured_at: str,
    client_tz_offset_min: int,
    status: str = "inbox",
    schedule: str | None = None,
    rrule: str | None = None,
    timezone: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Capture a new loop item.

    Creates a new loop with the provided text and metadata. The loop starts
    in 'inbox' status by default but can be set to any valid status.

    Recurrence: Either 'schedule' (natural language like "every Monday") or
    'rrule' (direct RRULE string) can be provided to create a recurring loop.

    Args:
        raw_text: The text content of the loop.
        captured_at: ISO 8601 timestamp when the loop was captured.
        client_tz_offset_min: Client timezone offset in minutes from UTC.
        status: Initial status (default: "inbox"). Valid: inbox, actionable,
            blocked, scheduled, completed, dropped.
        schedule: Natural language recurrence phrase (e.g., "every Monday").
        rrule: Direct RRULE string for recurrence (e.g., "FREQ=WEEKLY;BYDAY=MO").
        timezone: IANA timezone for recurrence (e.g., "America/New_York").
        request_id: Optional idempotency key for safe retries.

    Returns:
        The created loop record with all fields including id, status,
        raw_text, created_at_utc, and recurrence fields if specified.

    Raises:
        ToolError: If timestamp validation fails or status is invalid.
    """
    validate_iso8601_timestamp(captured_at, "captured_at")
    validate_tz_offset(client_tz_offset_min, "client_tz_offset_min")

    settings = get_settings()
    loop_status = LoopStatus(status)

    # Resolve recurrence RRULE from schedule phrase or direct rrule
    recurrence_rrule: str | None = None
    if schedule:
        from ..loops.recurrence import parse_recurrence_schedule

        parsed = parse_recurrence_schedule(schedule)
        recurrence_rrule = parsed.rrule
    elif rrule:
        recurrence_rrule = rrule

    payload = {
        "raw_text": raw_text,
        "captured_at": captured_at,
        "client_tz_offset_min": client_tz_offset_min,
        "status": status,
        "schedule": schedule,
        "rrule": rrule,
        "timezone": timezone,
    }

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.create",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        record = loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=client_tz_offset_min,
            status=loop_status,
            conn=conn,
            recurrence_rrule=recurrence_rrule,
            recurrence_tz=timezone,
        )
        finalize_tool_idempotency(state=idempotency, response=record, conn=conn)
    return record


def loop_update(
    loop_id: int,
    fields: dict[str, Any],
    claim_token: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one or more fields of an existing loop.

    Only the provided fields are updated; others remain unchanged.
    Timestamps (due_at_utc, snooze_until_utc) must be ISO 8601 format.

    Args:
        loop_id: The unique identifier of the loop to update.
        fields: Dict of field names to new values. Supported fields include:
            - raw_text: Updated text content
            - status: New status (use loop.close for terminal statuses)
            - due_at_utc: ISO 8601 due date timestamp
            - snooze_until_utc: ISO 8601 snooze timestamp
            - next_action: Actionable next step description
            - time_minutes: Estimated effort in minutes
            - tags: List of tag strings
            - project_id: Project association
        claim_token: Required if loop is claimed by another agent.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The updated loop record with all current fields.

    Raises:
        ToolError: If loop not found, validation fails, or claim mismatch.
    """
    if "due_at_utc" in fields and fields["due_at_utc"] is not None:
        validate_iso8601_timestamp(fields["due_at_utc"], "due_at_utc")
    if "snooze_until_utc" in fields and fields["snooze_until_utc"] is not None:
        validate_iso8601_timestamp(fields["snooze_until_utc"], "snooze_until_utc")

    settings = get_settings()

    payload = {"loop_id": loop_id, "fields": fields, "claim_token": claim_token}

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.update",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        result = loop_service.update_loop(
            loop_id=loop_id, fields=fields, claim_token=claim_token, conn=conn
        )
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
    return result


def loop_close(
    loop_id: int,
    status: str = "completed",
    note: str | None = None,
    claim_token: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Close a loop with a terminal status (completed or dropped).

    Terminal statuses are final; use loop.transition for non-terminal
    status changes (inbox, actionable, blocked, scheduled).

    Args:
        loop_id: The unique identifier of the loop to close.
        status: Terminal status - "completed" or "dropped" (default: "completed").
        note: Optional completion/drop note explaining the resolution.
        claim_token: Required if loop is claimed by another agent.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The closed loop record with updated status and closed_at_utc.

    Raises:
        ToolError: If loop not found, status is not terminal, or claim mismatch.
    """
    settings = get_settings()
    loop_status = LoopStatus(status)
    if not is_terminal_status(loop_status):
        raise ValidationError("status", "must be completed or dropped")

    payload = {"loop_id": loop_id, "status": status, "note": note, "claim_token": claim_token}

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.close",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        result = loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            claim_token=claim_token,
            conn=conn,
        )
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
    return result


def loop_get(loop_id: int) -> dict[str, Any]:
    """Retrieve a single loop by its ID.

    Args:
        loop_id: The unique identifier of the loop to retrieve.

    Returns:
        The full loop object with all fields including tags and project name.

    Raises:
        LoopNotFoundError: If no loop exists with the given ID.
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.get_loop(loop_id=loop_id, conn=conn)


def loop_transition(
    loop_id: int,
    status: str,
    note: str | None = None,
    claim_token: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Transition a loop to a new non-terminal status.

    Valid status transitions depend on current state:
    - inbox -> actionable, blocked, scheduled
    - actionable -> inbox, blocked, scheduled
    - blocked -> inbox, actionable, scheduled
    - scheduled -> inbox, actionable, blocked
    - completed/dropped -> can reopen to inbox or actionable

    Use loop.close for terminal transitions (completed, dropped).

    Args:
        loop_id: The unique identifier of the loop to transition.
        status: Target status: inbox, actionable, blocked, or scheduled.
        note: Optional note explaining the transition.
        claim_token: Optional claim token for protected loops.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The updated loop object.

    Raises:
        LoopNotFoundError: If no loop exists with the given ID.
        TransitionError: If the status transition is not allowed.
        ValueError: If status is not a valid LoopStatus value.
    """
    settings = get_settings()
    loop_status = LoopStatus(status)

    # Validate that status is non-terminal (use loop.close for terminal statuses)
    if is_terminal_status(loop_status):
        raise ValidationError("status", "use loop.close for terminal statuses (completed, dropped)")

    payload = {"loop_id": loop_id, "status": status, "note": note, "claim_token": claim_token}

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.transition",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        result = loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            claim_token=claim_token,
            conn=conn,
        )
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
    return result


def register_loop_core_tools(mcp: "FastMCP") -> None:
    """Register core loop mutation tools with the MCP server."""
    from ..mcp_server import with_db_init, with_mcp_error_handling

    mcp.tool(name="loop.create")(with_db_init(with_mcp_error_handling(loop_create)))
    mcp.tool(name="loop.update")(with_db_init(with_mcp_error_handling(loop_update)))
    mcp.tool(name="loop.close")(with_db_init(with_mcp_error_handling(loop_close)))
    mcp.tool(name="loop.get")(with_db_init(with_mcp_error_handling(loop_get)))
    mcp.tool(name="loop.transition")(with_db_init(with_mcp_error_handling(loop_transition)))
