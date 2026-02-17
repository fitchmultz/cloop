"""MCP server exposing loop operations to external AI agents.

Purpose:
    Expose loop operations via Model Context Protocol for AI agent integration.

Responsibilities:
    - Provide tool handlers for loop CRUD operations
    - Integrate with FastAPI lifespan for startup/shutdown
    - Support stdio and SSE transports

Non-scope:
    - HTTP REST API (see routes/)
    - CLI interface (see cli.py)

Tool Handlers:
    - loop.create: Capture a new loop
    - loop.update: Update loop fields
    - loop.close: Close a loop as completed/dropped
    - loop.get: Retrieve a single loop by ID
    - loop.next: Get prioritized loops organized into action buckets
    - loop.transition: Transition loop to a non-terminal status
    - loop.list: List loops with optional status filter
    - loop.search: Search loops by text
    - loop.snooze: Set snooze timer on a loop
    - loop.enrich: Trigger AI enrichment for a loop
    - loop.events: Get event history for a loop
    - loop.undo: Undo the most recent reversible event
    - loop.tags: List all unique tags used across loops
    - project.list: List all projects

Idempotency:
    All mutation tools support an optional `request_id` parameter for safe retries.
    Same request_id + same args replays prior response without additional writes.
    Same request_id + different args raises ToolError.

Non-scope:
    - HTTP API endpoints (see main.py)
    - CLI commands (see cli.py)
"""

# =============================================================================
# MCP Tool Docstring Format
# =============================================================================
#
# All MCP tool docstrings should follow this format:
#
#     """One-line summary of tool purpose (under 80 chars).
#
#     Extended description explaining behavior, special cases, and usage notes.
#     Include any important warnings or edge cases here.
#
#     Args:
#         param_name: Description including type if non-obvious.
#             - Document valid options and defaults
#             - Note what happens if omitted for optional params
#
#     Returns:
#         Description of return value structure.
#         - Include field names for dict returns
#         - Note special cases (None, empty list, etc.)
#
#     Raises:
#         ToolError: Conditions that trigger this error.
#
# Notes:
#   - Always include Args and Returns sections (even if Args is empty)
#   - Use Raises section only if the tool can raise ToolError
#   - Keep one-line summary under 80 characters
# =============================================================================

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import db
from .constants import BULK_OPERATION_MAX_ITEMS, DEFAULT_LOOP_LIST_LIMIT
from .idempotency import (
    IdempotencyConflictError,
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from .loops import enrichment as loop_enrichment
from .loops import repo as loop_repo
from .loops import service as loop_service
from .loops.errors import (
    ClaimNotFoundError,
    CloopError,
    DependencyCycleError,
    LoopClaimedError,
    NotFoundError,
    TransitionError,
    UndoNotPossibleError,
    ValidationError,
)
from .loops.models import (
    LoopStatus,
    is_terminal_status,
    validate_iso8601_timestamp,
    validate_tz_offset,
)
from .settings import get_settings

mcp = FastMCP("Cloop Loops", json_response=True)

F = TypeVar("F", bound=Callable[..., Any])


def with_db_init(func: F) -> F:
    """Initialize databases before executing an MCP tool handler.

    Ensures settings are loaded and databases are initialized before any
    MCP tool operation. This centralizes initialization logic that was
    previously duplicated across all handlers.
    """

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = get_settings()
        db.init_databases(settings)
        return func(*args, **kwargs)

    return _wrapper  # type: ignore[return-value]


def _to_tool_error(exc: Exception) -> ToolError:
    """Convert service layer exceptions to MCP ToolError with user-friendly message."""
    if isinstance(exc, NotFoundError):
        return ToolError(exc.message)
    if isinstance(exc, TransitionError):
        return ToolError(f"Invalid status transition: {exc.from_status} -> {exc.to_status}")
    if isinstance(exc, ValidationError):
        return ToolError(exc.message)
    if isinstance(exc, LoopClaimedError):
        return ToolError(f"Loop {exc.loop_id} is claimed by '{exc.owner}' until {exc.lease_until}")
    if isinstance(exc, ClaimNotFoundError):
        return ToolError(exc.message)
    if isinstance(exc, DependencyCycleError):
        return ToolError(exc.message)
    if isinstance(exc, UndoNotPossibleError):
        return ToolError(f"Cannot undo: {exc.message}")
    if isinstance(exc, CloopError):
        return ToolError(exc.message)

    # Unknown exception type - pass through the message
    return ToolError(str(exc))


def with_mcp_error_handling(func: F) -> F:
    """Wrap MCP tool handler to convert exceptions to ToolError.

    Catches both typed CloopError and legacy ValueError for consistent
    error responses to MCP clients.
    """

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise _to_tool_error(exc) from exc

    return _wrapper  # type: ignore[return-value]


def _handle_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    settings: Any,
) -> dict[str, Any] | None:
    """Handle idempotency for MCP tool calls.

    Args:
        tool_name: MCP tool name (e.g., "loop.create")
        request_id: Optional idempotency key
        payload: Request payload (will be hashed)
        settings: Settings object

    Returns:
        None if should proceed with mutation, or replayed response dict

    Raises:
        ToolError: If idempotency key conflict or validation error
    """
    if request_id is None:
        return None

    try:
        key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    except ValueError as e:
        raise ToolError(str(e)) from None

    scope = build_mcp_scope(tool_name)
    request_hash = canonical_request_hash(payload)
    expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

    with db.core_connection(settings) as conn:
        try:
            claim = db.claim_or_replay_idempotency(
                scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                expires_at=expires_at,
                conn=conn,
            )
        except IdempotencyConflictError as e:
            raise ToolError(f"Idempotency conflict: {e}") from None

        if not claim["is_new"] and claim["replay"]:
            return claim["replay"]["response_body"]

        return None


def _finalize_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    response: dict[str, Any],
    settings: Any,
) -> None:
    """Store response for idempotent MCP tool call.

    Args:
        tool_name: MCP tool name
        request_id: Optional idempotency key
        payload: Request payload
        response: Response body to store
        settings: Settings object
    """
    if request_id is None:
        return

    key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    scope = build_mcp_scope(tool_name)

    with db.core_connection(settings) as conn:
        db.finalize_idempotency_response(
            scope=scope,
            idempotency_key=key,
            response_status=200,
            response_body=response,
            conn=conn,
        )


@mcp.tool(name="loop.create")
@with_db_init
@with_mcp_error_handling
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
        from .loops.recurrence import parse_recurrence_schedule

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

    replay = _handle_mcp_idempotency(
        tool_name="loop.create",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        record = loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=client_tz_offset_min,
            status=loop_status,
            conn=conn,
            recurrence_rrule=recurrence_rrule,
            recurrence_tz=timezone,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.create",
        request_id=request_id,
        payload=payload,
        response=record,
        settings=settings,
    )
    return record


@mcp.tool(name="loop.update")
@with_db_init
@with_mcp_error_handling
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

    replay = _handle_mcp_idempotency(
        tool_name="loop.update",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.update_loop(
            loop_id=loop_id, fields=fields, claim_token=claim_token, conn=conn
        )

    _finalize_mcp_idempotency(
        tool_name="loop.update",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.close")
@with_db_init
@with_mcp_error_handling
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

    replay = _handle_mcp_idempotency(
        tool_name="loop.close",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            claim_token=claim_token,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.close",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.list")
@with_db_init
@with_mcp_error_handling
def loop_list(
    status: str | None = None, limit: int = DEFAULT_LOOP_LIST_LIMIT, cursor: str | None = None
) -> dict[str, Any]:
    """List loops with optional status filter and cursor-based pagination.

    Args:
        status: Optional status filter (inbox, actionable, blocked, scheduled, completed, dropped)
        limit: Maximum number of results (default: 50)
        cursor: Optional cursor token for continuation

    Returns:
        Dict with items, next_cursor (or None), and limit
    """
    settings = get_settings()
    parsed_status = LoopStatus(status) if status else None
    with db.core_connection(settings) as conn:
        return loop_service.list_loops_page(
            status=parsed_status,
            limit=limit,
            cursor=cursor,
            conn=conn,
        )


@mcp.tool(name="loop.search")
@with_db_init
@with_mcp_error_handling
def loop_search(
    query: str, limit: int = DEFAULT_LOOP_LIST_LIMIT, cursor: str | None = None
) -> dict[str, Any]:
    """Search loops using the DSL query language with cursor-based pagination.

    Query syntax:
        - status:<value> where value in {open, all, inbox, actionable,
          blocked, scheduled, completed, dropped}
        - tag:<value>
        - project:<value>
        - due:<value> where value in {today, tomorrow, overdue, none, next7d}
        - text:<value>
        - Bare tokens without field: prefix are treated as text:<token>

    Examples:
        - "status:inbox tag:work due:today"
        - "project:ClientAlpha blocked"
        - "status:open groceries"

    Args:
        query: DSL query string
        limit: Maximum number of results (default: 50)
        cursor: Optional cursor token for continuation

    Returns:
        Dict with items, next_cursor (or None), and limit
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.search_loops_by_query_page(
            query=query, limit=limit, cursor=cursor, conn=conn
        )


@mcp.tool(name="loop.snooze")
@with_db_init
@with_mcp_error_handling
def loop_snooze(
    loop_id: int,
    snooze_until_utc: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Snooze a loop until a specified future time.

    Sets the snooze_until_utc field on the loop. Snoozed loops are excluded
    from loop.next results until the snooze time passes.

    Args:
        loop_id: The unique identifier of the loop to snooze.
        snooze_until_utc: ISO 8601 timestamp when snooze expires.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The updated loop record with snooze_until_utc set.

    Raises:
        ToolError: If loop not found or timestamp validation fails.
    """
    validate_iso8601_timestamp(snooze_until_utc, "snooze_until_utc")

    settings = get_settings()

    payload = {"loop_id": loop_id, "snooze_until_utc": snooze_until_utc}

    replay = _handle_mcp_idempotency(
        tool_name="loop.snooze",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until_utc},
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.snooze",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.enrich")
@with_db_init
@with_mcp_error_handling
def loop_enrich(loop_id: int, request_id: str | None = None) -> dict[str, Any]:
    """Trigger AI enrichment for a loop.

    Requests and executes AI enrichment to extract structured data from
    the loop's raw_text. Enrichment may populate: summary, next_action,
    time_minutes, tags, project suggestion, and due date.

    This is a synchronous operation that performs the enrichment immediately.

    Args:
        loop_id: The unique identifier of the loop to enrich.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The enriched loop record with updated fields.

    Raises:
        ToolError: If loop not found or enrichment fails.
    """
    settings = get_settings()

    payload = {"loop_id": loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.enrich",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        result = loop_enrichment.enrich_loop(loop_id=loop_id, conn=conn, settings=settings)

    _finalize_mcp_idempotency(
        tool_name="loop.enrich",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.events")
@with_db_init
@with_mcp_error_handling
def loop_events(
    loop_id: int,
    limit: int = 50,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get event history for a loop.

    Returns events in reverse chronological order (newest first).
    Use before_id cursor for pagination.

    Args:
        loop_id: Loop ID to query
        limit: Max results (default 50)
        before_id: Pagination cursor - only events with id < before_id

    Returns:
        List of event dicts with id, event_type, payload, created_at_utc, is_reversible
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.get_loop_events(
            loop_id=loop_id,
            limit=limit,
            before_id=before_id,
            conn=conn,
        )


@mcp.tool(name="loop.undo")
@with_db_init
@with_mcp_error_handling
def loop_undo(
    loop_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Undo the most recent reversible event for a loop.

    Reversible events include: update, status_change, close.
    Enrichment, claim, and timer events cannot be undone.

    Args:
        loop_id: Loop ID to modify
        request_id: Optional idempotency key

    Returns:
        Dict with updated loop and undo details:
        - loop: The updated loop dict
        - undone_event_id: ID of the event that was undone
        - undone_event_type: Type of the undone event
    """
    settings = get_settings()
    payload = {"loop_id": loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.undo",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.undo_last_event(
            loop_id=loop_id,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.undo",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.create")
@with_db_init
@with_mcp_error_handling
def loop_view_create(
    name: str,
    query: str,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved view with a DSL query.

    Saved views allow storing and reusing DSL query strings for quick access
    to commonly needed loop filters. Views can be applied with loop.view.apply.

    Args:
        name: Unique view name (must not conflict with existing views)
        query: DSL query string (same syntax as loop.search)
        description: Optional human-readable description of the view's purpose
        request_id: Optional idempotency key for safe retries

    Returns:
        The created view record with id, name, query, description, and created_at_utc

    Raises:
        ToolError: If name already exists or query is invalid
    """
    settings = get_settings()
    payload = {"name": name, "query": query, "description": description}

    replay = _handle_mcp_idempotency(
        tool_name="loop.view.create",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.create_loop_view(
            name=name,
            query=query,
            description=description,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.view.create",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.list")
@with_db_init
@with_mcp_error_handling
def loop_view_list() -> list[dict[str, Any]]:
    """List all saved views.

    Returns all user-created saved views ordered by name. Views are reusable
    DSL queries that can be applied with loop.view.apply.

    Returns:
        List of view dicts, each containing:
        - id: Unique view identifier
        - name: View name
        - query: The stored DSL query string
        - description: Optional description
        - created_at_utc: Creation timestamp
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.list_loop_views(conn=conn)


@mcp.tool(name="loop.view.get")
@with_db_init
@with_mcp_error_handling
def loop_view_get(view_id: int) -> dict[str, Any]:
    """Get a saved view by its ID.

    Retrieves the full details of a specific saved view including its
    stored DSL query and metadata.

    Args:
        view_id: The unique identifier of the view to retrieve

    Returns:
        The view record with id, name, query, description, and created_at_utc

    Raises:
        ToolError: If no view exists with the given ID
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.get_loop_view(view_id=view_id, conn=conn)


@mcp.tool(name="loop.view.update")
@with_db_init
@with_mcp_error_handling
def loop_view_update(
    view_id: int,
    name: str | None = None,
    query: str | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one or more fields of an existing saved view.

    Only provided fields are updated; others remain unchanged. At least one
    field must be provided for update.

    Args:
        view_id: The unique identifier of the view to update
        name: Optional new name (must be unique if changed)
        query: Optional new DSL query string
        description: Optional new description
        request_id: Optional idempotency key for safe retries

    Returns:
        The updated view record with all current fields

    Raises:
        ToolError: If view not found, name conflicts, or query is invalid
    """
    settings = get_settings()
    payload = {"view_id": view_id, "name": name, "query": query, "description": description}

    replay = _handle_mcp_idempotency(
        tool_name="loop.view.update",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.update_loop_view(
            view_id=view_id,
            name=name,
            query=query,
            description=description,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.view.update",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.delete")
@with_db_init
@with_mcp_error_handling
def loop_view_delete(
    view_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete a saved view permanently.

    Permanently removes the saved view. This operation cannot be undone.
    Associated loops are not affected - only the saved view itself is deleted.

    Args:
        view_id: The unique identifier of the view to delete
        request_id: Optional idempotency key for safe retries

    Returns:
        Dict with deleted: True to confirm successful deletion

    Raises:
        ToolError: If view not found
    """
    settings = get_settings()
    payload = {"view_id": view_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.view.delete",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        loop_service.delete_loop_view(view_id=view_id, conn=conn)

    result = {"deleted": True}
    _finalize_mcp_idempotency(
        tool_name="loop.view.delete",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.apply")
@with_db_init
@with_mcp_error_handling
def loop_view_apply(
    view_id: int,
    limit: int = DEFAULT_LOOP_LIST_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Apply a saved view and return matching loops with cursor-based pagination.

    Args:
        view_id: View ID to apply
        limit: Max results (default: 50)
        cursor: Optional cursor token for continuation

    Returns:
        Dict with view info, query, limit, cursor, next_cursor (or None), and items
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.apply_loop_view_page(
            view_id=view_id,
            limit=limit,
            cursor=cursor,
            conn=conn,
        )


@mcp.tool(name="loop.bulk_update")
@with_db_init
@with_mcp_error_handling
def loop_bulk_update(
    updates: list[dict[str, Any]],
    transactional: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bulk update multiple loops with per-item result envelopes.

    Args:
        updates: List of updates, each with:
            - loop_id: int (required)
            - fields: dict (required) - fields to update (not status)
        transactional: If True, rollback all on any failure (default: False)
        request_id: Optional idempotency key

    Returns:
        Dict with:
            - ok: bool (True if all succeeded)
            - transactional: bool
            - results: list of per-item results with index, loop_id, ok, loop/error
            - succeeded: int count
            - failed: int count

    Raises:
        ToolError: If updates exceeds BULK_OPERATION_MAX_ITEMS limit.
    """
    if len(updates) > BULK_OPERATION_MAX_ITEMS:
        raise ToolError(
            f"Bulk update exceeds maximum items limit: {len(updates)} > {BULK_OPERATION_MAX_ITEMS}"
        )

    settings = get_settings()

    payload = {"updates": updates, "transactional": transactional}

    replay = _handle_mcp_idempotency(
        tool_name="loop.bulk_update",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.bulk_update_loops(
            updates=updates,
            transactional=transactional,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.bulk_update",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.bulk_close")
@with_db_init
@with_mcp_error_handling
def loop_bulk_close(
    items: list[dict[str, Any]],
    transactional: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bulk close multiple loops with per-item result envelopes.

    Args:
        items: List of items, each with:
            - loop_id: int (required)
            - status: str (optional, default: "completed", must be completed or dropped)
            - note: str (optional, completion note)
        transactional: If True, rollback all on any failure (default: False)
        request_id: Optional idempotency key

    Returns:
        Dict with:
            - ok: bool (True if all succeeded)
            - transactional: bool
            - results: list of per-item results with index, loop_id, ok, loop/error
            - succeeded: int count
            - failed: int count

    Raises:
        ToolError: If items exceeds BULK_OPERATION_MAX_ITEMS limit.
    """
    if len(items) > BULK_OPERATION_MAX_ITEMS:
        raise ToolError(
            f"Bulk close exceeds maximum items limit: {len(items)} > {BULK_OPERATION_MAX_ITEMS}"
        )

    settings = get_settings()

    payload = {"items": items, "transactional": transactional}

    replay = _handle_mcp_idempotency(
        tool_name="loop.bulk_close",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.bulk_close_loops(
            items=items,
            transactional=transactional,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.bulk_close",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.bulk_snooze")
@with_db_init
@with_mcp_error_handling
def loop_bulk_snooze(
    items: list[dict[str, Any]],
    transactional: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bulk snooze multiple loops with per-item result envelopes.

    Args:
        items: List of items, each with:
            - loop_id: int (required)
            - snooze_until_utc: str (required, ISO 8601 timestamp)
        transactional: If True, rollback all on any failure (default: False)
        request_id: Optional idempotency key

    Returns:
        Dict with:
            - ok: bool (True if all succeeded)
            - transactional: bool
            - results: list of per-item results with index, loop_id, ok, loop/error
            - succeeded: int count
            - failed: int count

    Raises:
        ToolError: If items exceeds BULK_OPERATION_MAX_ITEMS limit.
    """
    if len(items) > BULK_OPERATION_MAX_ITEMS:
        raise ToolError(
            f"Bulk snooze exceeds maximum items limit: {len(items)} > {BULK_OPERATION_MAX_ITEMS}"
        )

    settings = get_settings()

    for item in items:
        if "snooze_until_utc" in item and item["snooze_until_utc"] is not None:
            validate_iso8601_timestamp(item["snooze_until_utc"], "snooze_until_utc")

    payload = {"items": items, "transactional": transactional}

    replay = _handle_mcp_idempotency(
        tool_name="loop.bulk_snooze",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.bulk_snooze_loops(
            items=items,
            transactional=transactional,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.bulk_snooze",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


# ============================================================================
# Loop Claim MCP Tools
# ============================================================================


@mcp.tool(name="loop.claim")
@with_db_init
@with_mcp_error_handling
def loop_claim(
    loop_id: int,
    owner: str,
    ttl_seconds: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Claim a loop for exclusive access. Returns claim_token required for mutations.

    Args:
        loop_id: Loop ID to claim
        owner: Identifier for the claiming agent
        ttl_seconds: Lease duration in seconds (default 300)
        request_id: Optional idempotency key

    Returns:
        Dict with claim details including claim_token
    """
    settings = get_settings()

    payload = {"loop_id": loop_id, "owner": owner, "ttl_seconds": ttl_seconds}

    replay = _handle_mcp_idempotency(
        tool_name="loop.claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.claim_loop(
            loop_id=loop_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            conn=conn,
            settings=settings,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.renew_claim")
@with_db_init
@with_mcp_error_handling
def loop_renew_claim(
    loop_id: int,
    claim_token: str,
    ttl_seconds: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Renew an existing claim on a loop.

    Args:
        loop_id: Loop ID
        claim_token: Token from original claim
        ttl_seconds: New lease duration in seconds
        request_id: Optional idempotency key

    Returns:
        Dict with updated claim details
    """
    settings = get_settings()

    payload = {
        "loop_id": loop_id,
        "claim_token": claim_token,
        "ttl_seconds": ttl_seconds,
    }

    replay = _handle_mcp_idempotency(
        tool_name="loop.renew_claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.renew_claim(
            loop_id=loop_id,
            claim_token=claim_token,
            ttl_seconds=ttl_seconds,
            conn=conn,
            settings=settings,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.renew_claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.release_claim")
@with_db_init
@with_mcp_error_handling
def loop_release_claim(
    loop_id: int,
    claim_token: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Release a claim on a loop.

    Args:
        loop_id: Loop ID
        claim_token: Token from original claim
        request_id: Optional idempotency key

    Returns:
        Dict with ok status
    """
    settings = get_settings()

    payload = {"loop_id": loop_id, "claim_token": claim_token}

    replay = _handle_mcp_idempotency(
        tool_name="loop.release_claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        loop_service.release_claim(
            loop_id=loop_id,
            claim_token=claim_token,
            conn=conn,
        )

    result = {"ok": True}
    _finalize_mcp_idempotency(
        tool_name="loop.release_claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.get_claim")
@with_db_init
@with_mcp_error_handling
def loop_get_claim(loop_id: int) -> dict[str, Any] | None:
    """Get the current claim status for a loop.

    Args:
        loop_id: Loop ID to check

    Returns:
        Dict with claim info (without token) or None if not claimed
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.get_claim_status(loop_id=loop_id, conn=conn)


@mcp.tool(name="loop.list_claims")
@with_db_init
@with_mcp_error_handling
def loop_list_claims(
    owner: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List all active claims.

    Args:
        owner: Optional owner filter
        limit: Max results (default 100)

    Returns:
        List of claim dicts (without tokens) ordered by lease_until ascending
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.list_active_claims(owner=owner, limit=limit, conn=conn)


@mcp.tool(name="loop.force_release_claim")
@with_db_init
@with_mcp_error_handling
def loop_force_release_claim(
    loop_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Force-release any claim on a loop (admin override).

    Args:
        loop_id: Loop ID
        request_id: Optional idempotency key

    Returns:
        Dict with ok and released status
    """
    settings = get_settings()

    payload = {"loop_id": loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.force_release_claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        released = loop_service.force_release_claim(loop_id=loop_id, conn=conn)

    result = {"ok": True, "released": released}
    _finalize_mcp_idempotency(
        tool_name="loop.force_release_claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


# ============================================================================
# Loop Dependency MCP Tools
# ============================================================================


@mcp.tool(name="loop.dependency.add")
@with_db_init
@with_mcp_error_handling
def loop_dependency_add(
    loop_id: int,
    depends_on_loop_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a dependency relationship (loop_id depends on depends_on_loop_id).

    Args:
        loop_id: The loop that is blocked
        depends_on_loop_id: The loop that blocks it
        request_id: Optional idempotency key

    Returns:
        Updated loop with dependencies
    """
    from cloop.loops.service import add_loop_dependency

    settings = get_settings()
    payload = {"loop_id": loop_id, "depends_on_loop_id": depends_on_loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.dependency.add",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = add_loop_dependency(
            loop_id=loop_id,
            depends_on_loop_id=depends_on_loop_id,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.dependency.add",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.dependency.remove")
@with_db_init
@with_mcp_error_handling
def loop_dependency_remove(
    loop_id: int,
    depends_on_loop_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Remove a dependency relationship.

    Args:
        loop_id: The blocked loop
        depends_on_loop_id: The loop it depended on
        request_id: Optional idempotency key

    Returns:
        Updated loop with dependencies
    """
    from cloop.loops.service import remove_loop_dependency

    settings = get_settings()
    payload = {"loop_id": loop_id, "depends_on_loop_id": depends_on_loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.dependency.remove",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = remove_loop_dependency(
            loop_id=loop_id,
            depends_on_loop_id=depends_on_loop_id,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.dependency.remove",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.dependency.list")
@with_db_init
@with_mcp_error_handling
def loop_dependency_list(loop_id: int) -> list[dict[str, Any]]:
    """List all dependencies (blockers) for a loop.

    Args:
        loop_id: The loop to check

    Returns:
        List of dependency loops with status
    """
    from cloop.loops.service import get_loop_dependencies

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return get_loop_dependencies(loop_id=loop_id, conn=conn)


@mcp.tool(name="loop.dependency.blocking")
@with_db_init
@with_mcp_error_handling
def loop_dependency_blocking(loop_id: int) -> list[dict[str, Any]]:
    """List all loops that depend on this loop.

    Args:
        loop_id: The loop to check

    Returns:
        List of dependent loops
    """
    from cloop.loops.service import get_loop_blocking

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return get_loop_blocking(loop_id=loop_id, conn=conn)


@mcp.tool(name="loop.get")
@with_db_init
@with_mcp_error_handling
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


@mcp.tool(name="loop.next")
@with_db_init
@with_mcp_error_handling
def loop_next(limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Get prioritized loops organized into action buckets.

    Returns loops ready for action, sorted into priority buckets:
    - due_soon: Items with imminent due dates
    - quick_wins: Low effort, high impact items
    - high_leverage: Important strategic items
    - standard: Other actionable items

    Only includes loops from inbox and actionable statuses that:
    - Have a next_action defined
    - Are not snoozed
    - Have no open dependencies (blocked items excluded)

    Args:
        limit: Maximum number of loops to return per bucket (default: 5).

    Returns:
        Dict with keys: due_soon, quick_wins, high_leverage, standard.
        Each key maps to a list of loop objects sorted by priority score.
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.next_loops(limit=limit, conn=conn, settings=settings)


@mcp.tool(name="loop.transition")
@with_db_init
@with_mcp_error_handling
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

    replay = _handle_mcp_idempotency(
        tool_name="loop.transition",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            claim_token=claim_token,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.transition",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.tags")
@with_db_init
@with_mcp_error_handling
def loop_tags() -> list[str]:
    """List all unique tags used across loops.

    Returns tags that have been assigned to at least one loop. Tags are
    normalized to lowercase and deduplicated. Useful for building tag
    selectors or understanding loop categorization patterns.

    Returns:
        Alphabetically sorted list of unique tag names (lowercase).
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.list_tags(conn=conn)


@mcp.tool(name="project.list")
@with_db_init
@with_mcp_error_handling
def project_list() -> list[dict[str, Any]]:
    """List all projects.

    Returns all projects that have been associated with loops, ordered
    by name. Projects are auto-created when referenced in loop captures.

    Returns:
        List of project dicts, each with:
        - id: Unique project identifier
        - name: Project name
        - created_at_utc: When the project was created
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_projects(conn=conn)


# ============================================================================
# Loop Template MCP Tools
# ============================================================================


@mcp.tool(name="loop.template.list")
@with_db_init
@with_mcp_error_handling
def loop_template_list() -> list[dict[str, Any]]:
    """List all loop templates.

    Returns both user-created and system templates. System templates are
    built-in patterns that cannot be deleted. User templates can be created
    from scratch or derived from existing loops.

    Returns:
        List of template dicts, each with:
        - id: Unique template identifier
        - name: Template name
        - description: Optional template description
        - raw_text_pattern: Pattern with optional {{variable}} placeholders
        - defaults_json: Default field values for new loops
        - is_system: True for built-in templates, False for user-created
        - created_at_utc: When the template was created
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_loop_templates(conn=conn)


@mcp.tool(name="loop.template.get")
@with_db_init
@with_mcp_error_handling
def loop_template_get(template_id: int) -> dict[str, Any] | None:
    """Get a template by its ID.

    Retrieves the full details of a specific template including its pattern,
    defaults, and metadata.

    Args:
        template_id: The unique identifier of the template to retrieve.

    Returns:
        Template dict with id, name, description, raw_text_pattern,
        defaults_json, is_system, and created_at_utc, or None if not found.
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.get_loop_template(template_id=template_id, conn=conn)


@mcp.tool(name="loop.template.create")
@with_db_init
@with_mcp_error_handling
def loop_template_create(
    name: str,
    description: str | None = None,
    raw_text_pattern: str = "",
    defaults: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a new loop template.

    Templates provide reusable patterns for creating loops with pre-filled
    fields. Use {{variable}} placeholders in raw_text_pattern to create
    dynamic templates that prompt for values when applied.

    Args:
        name: Template name (must be unique, case-insensitive).
        description: Optional human-readable description of the template's
            purpose and usage.
        raw_text_pattern: Pattern with optional {{variable}} placeholders
            that will be replaced when the template is applied.
        defaults: Default field values (tags, time_minutes, next_action,
            project_id, etc.) to apply to loops created from this template.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The created template record with id, name, description,
        raw_text_pattern, defaults_json, is_system, and created_at_utc.

    Raises:
        ToolError: If name is already in use or validation fails.
    """
    settings = get_settings()
    payload = {
        "name": name,
        "description": description,
        "raw_text_pattern": raw_text_pattern,
        "defaults": defaults,
    }

    replay = _handle_mcp_idempotency(
        tool_name="loop.template.create",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        template = loop_repo.create_loop_template(
            name=name,
            description=description,
            raw_text_pattern=raw_text_pattern,
            defaults_json=defaults or {},
            is_system=False,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.template.create",
        request_id=request_id,
        payload=payload,
        response=template,
        settings=settings,
    )
    return template


@mcp.tool(name="loop.template.delete")
@with_db_init
@with_mcp_error_handling
def loop_template_delete(
    template_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete a loop template permanently.

    Permanently removes a user-created template. System templates
    (is_system=True) cannot be deleted. This operation cannot be undone.

    Args:
        template_id: The unique identifier of the template to delete.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with deleted: True if the template was deleted, or deleted: False
        if the template was not found or is a system template.

    Raises:
        ToolError: If the template is a system template (cannot be deleted).
    """
    settings = get_settings()
    payload = {"template_id": template_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.template.delete",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        deleted = loop_repo.delete_loop_template(template_id=template_id, conn=conn)

    result = {"deleted": deleted}
    _finalize_mcp_idempotency(
        tool_name="loop.template.delete",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.template.from_loop")
@with_db_init
@with_mcp_error_handling
def loop_template_from_loop(
    loop_id: int,
    name: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a template from an existing loop.

    Extracts the raw_text, tags, time_minutes, next_action, and other
    fields from an existing loop to create a reusable template. The
    template can then be used to quickly create similar loops.

    Args:
        loop_id: The unique identifier of the loop to use as template source.
        name: Name for the new template (must be unique, case-insensitive).
        request_id: Optional idempotency key for safe retries.

    Returns:
        The created template record with id, name, description,
        raw_text_pattern, defaults_json, is_system, and created_at_utc.

    Raises:
        ToolError: If the source loop is not found or name is already in use.
    """
    settings = get_settings()
    payload = {"loop_id": loop_id, "name": name}

    replay = _handle_mcp_idempotency(
        tool_name="loop.template.from_loop",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        template = loop_service.create_template_from_loop(
            loop_id=loop_id,
            template_name=name,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.template.from_loop",
        request_id=request_id,
        payload=payload,
        response=template,
        settings=settings,
    )
    return template


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
