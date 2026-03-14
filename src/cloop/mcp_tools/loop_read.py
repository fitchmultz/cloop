"""Loop read-only MCP tools.

Purpose:
    MCP tools for reading loop data without mutations.

Responsibilities:
    - List loops plus DSL and semantic-loop search with filtering
    - Retrieve prioritized loops organized into action buckets
    - Get event history and support undo operations
    - Manage loop snoozing and AI enrichment triggers
    - List all unique tags used across loops

Tools:
    - loop.list: List loops with optional status filter
    - loop.search: Search loops using DSL query
    - loop.semantic_search: Search loops by semantic similarity
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

from ..constants import DEFAULT_LOOP_LIST_LIMIT
from ..loops import events as loop_event_ops
from ..loops import read_service
from ..loops import service as loop_service
from ..loops.enrichment_orchestration import orchestrate_loop_enrichment
from ..loops.models import LoopStatus, validate_iso8601_timestamp
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    parsed_status = LoopStatus(status) if status else None
    with db.core_connection(settings) as conn:
        return read_service.list_loops_page(
            status=parsed_status,
            limit=limit,
            cursor=cursor,
            conn=conn,
        )


def _parse_loop_status_filter(status: str) -> list[LoopStatus] | None:
    """Parse a loop status scope for read-only search tools."""
    if status == "all":
        return None
    if status == "open":
        return [
            LoopStatus.INBOX,
            LoopStatus.ACTIONABLE,
            LoopStatus.BLOCKED,
            LoopStatus.SCHEDULED,
        ]
    return [LoopStatus(status)]


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return read_service.search_loops_by_query_page(
            query=query, limit=limit, cursor=cursor, conn=conn
        )


@with_mcp_error_handling
def loop_semantic_search(
    query: str,
    status: str = "open",
    limit: int = DEFAULT_LOOP_LIST_LIMIT,
    offset: int = 0,
    min_score: float | None = None,
) -> dict[str, Any]:
    """Search loops by semantic similarity to a natural-language query.

    This ranks loops by meaning instead of exact token matches. The search path
    backfills missing or stale loop embeddings on demand so older loops remain
    searchable after the feature cutover.

    Args:
        query: Natural-language search query.
        status: Search scope (`open`, `all`, or one concrete loop status).
        limit: Maximum number of results to return (default: 50).
        offset: Pagination offset for ranked matches.
        min_score: Optional minimum cosine similarity score between 0.0 and 1.0.

    Returns:
        Dict with `query`, `limit`, `offset`, `min_score`, `indexed_count`,
        `candidate_count`, `match_count`, and `items`.

    Raises:
        ToolError: If validation fails or embeddings are unavailable.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    statuses = _parse_loop_status_filter(status)
    with db.core_connection(settings) as conn:
        return read_service.semantic_search_loops(
            query=query,
            statuses=statuses,
            limit=limit,
            offset=offset,
            min_score=min_score,
            conn=conn,
            settings=settings,
        )


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

    payload = {"loop_id": loop_id, "snooze_until_utc": snooze_until_utc}
    return run_idempotent_tool_mutation(
        tool_name="loop.snooze",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until_utc},
            conn=conn,
        ),
    )


@with_mcp_error_handling
def loop_enrich(loop_id: int, request_id: str | None = None) -> dict[str, Any]:
    """Run the canonical synchronous enrichment flow for a loop.

    The result includes the updated loop snapshot plus the suggestion metadata
    generated during enrichment.

    Args:
        loop_id: The unique identifier of the loop to enrich.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with `loop`, `suggestion_id`, `applied_fields`, and
        `needs_clarification`.

    Raises:
        ToolError: If loop not found or enrichment fails.
    """
    payload = {"loop_id": loop_id}
    return run_idempotent_tool_mutation(
        tool_name="loop.enrich",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: _execute_enrichment(
            loop_id=loop_id,
            conn=conn,
            settings=settings,
        ),
    )


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_event_ops.get_loop_events(
            loop_id=loop_id,
            limit=limit,
            before_id=before_id,
            conn=conn,
        )


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
    payload = {"loop_id": loop_id}
    return run_idempotent_tool_mutation(
        tool_name="loop.undo",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_event_ops.undo_last_event(loop_id=loop_id, conn=conn),
    )


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return read_service.next_loops(limit=limit, conn=conn, settings=settings)


@with_mcp_error_handling
def loop_tags() -> list[str]:
    """List all unique tags used across loops.

    Returns tags that have been assigned to at least one loop. Tags are
    normalized to lowercase and deduplicated. Useful for building tag
    selectors or understanding loop categorization patterns.

    Returns:
        Alphabetically sorted list of unique tag names (lowercase).
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return read_service.list_tags(conn=conn)


def _execute_enrichment(*, loop_id: int, conn: Any, settings: Any) -> dict[str, Any]:
    """Run the shared explicit enrichment flow inside the mutation helper."""
    return orchestrate_loop_enrichment(
        loop_id=loop_id,
        conn=conn,
        settings=settings,
    ).to_payload()


def register_loop_read_tools(mcp: "FastMCP") -> None:
    """Register loop read tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="loop.list")(with_db_init(loop_list))
    mcp.tool(name="loop.search")(with_db_init(loop_search))
    mcp.tool(name="loop.semantic_search")(with_db_init(loop_semantic_search))
    mcp.tool(name="loop.snooze")(with_db_init(loop_snooze))
    mcp.tool(name="loop.enrich")(with_db_init(loop_enrich))
    mcp.tool(name="loop.events")(with_db_init(loop_events))
    mcp.tool(name="loop.undo")(with_db_init(loop_undo))
    mcp.tool(name="loop.next")(with_db_init(loop_next))
    mcp.tool(name="loop.tags")(with_db_init(loop_tags))
