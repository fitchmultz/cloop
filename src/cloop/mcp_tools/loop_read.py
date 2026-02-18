"""Loop read-only MCP tools.

Purpose:
    MCP tools for reading loop data without mutations.

Tools:
    - loop.list: List loops with optional status filter
    - loop.search: Search loops using DSL query
    - loop.next: Get prioritized loops in action buckets
    - loop.tags: List all unique tags
    - loop.events: Get event history for a loop
    - loop.undo: Undo the most recent reversible event
    - loop.snooze: Snooze a loop until a future time
    - loop.enrich: Trigger AI enrichment for a loop

Non-scope:
    - Core mutations (see loop_core.py)
    - Bulk operations (see loop_bulk.py)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..constants import DEFAULT_LOOP_LIST_LIMIT
from ..idempotency import (
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ..loops import enrichment as loop_enrichment
from ..loops import service as loop_service
from ..loops.models import LoopStatus, validate_iso8601_timestamp
from ..settings import get_settings

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _handle_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    settings: Any,
) -> dict[str, Any] | None:
    """Handle idempotency for MCP tool calls."""
    from ..idempotency import IdempotencyConflictError

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
    """Store response for idempotent MCP tool call."""
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


def register_loop_read_tools(mcp: "FastMCP") -> None:
    """Register loop read tools with the MCP server."""
    from ..mcp_server import with_db_init, with_mcp_error_handling

    mcp.tool(name="loop.list")(with_db_init(with_mcp_error_handling(loop_list)))
    mcp.tool(name="loop.search")(with_db_init(with_mcp_error_handling(loop_search)))
    mcp.tool(name="loop.snooze")(with_db_init(with_mcp_error_handling(loop_snooze)))
    mcp.tool(name="loop.enrich")(with_db_init(with_mcp_error_handling(loop_enrich)))
    mcp.tool(name="loop.events")(with_db_init(with_mcp_error_handling(loop_events)))
    mcp.tool(name="loop.undo")(with_db_init(with_mcp_error_handling(loop_undo)))
    mcp.tool(name="loop.next")(with_db_init(with_mcp_error_handling(loop_next)))
    mcp.tool(name="loop.tags")(with_db_init(with_mcp_error_handling(loop_tags)))
