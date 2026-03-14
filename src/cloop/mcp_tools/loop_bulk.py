"""Loop bulk operation MCP tools.

Purpose:
    MCP tools for bulk operations on multiple loops.

Responsibilities:
    - Bulk update multiple loops with per-item results
    - Bulk close multiple loops with completion/drop status
    - Bulk snooze multiple loops until specified times
    - Bulk enrich multiple loops or query-selected loop sets
    - Support transactional mode (all-or-nothing) where applicable
    - Validate bulk operation limits and timestamp formats
    - Handle idempotency for bulk mutations

Tools:
    - loop.bulk_update: Update multiple loops at once
    - loop.bulk_close: Close multiple loops at once
    - loop.bulk_snooze: Snooze multiple loops at once
    - loop.bulk_enrich: Enrich multiple explicitly selected loops
    - loop.bulk_enrich_query: Preview or enrich a query-selected loop set

Non-scope:
    - Single-item operations (see loop_core.py)
    - Transaction management (handled in service layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from ..constants import BULK_OPERATION_MAX_ITEMS
from ..loops import bulk as loop_bulk
from ..loops.enrichment_orchestration import (
    orchestrate_bulk_loop_enrichment,
    orchestrate_query_bulk_loop_enrichment,
)
from ..loops.models import validate_iso8601_timestamp
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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

    payload = {"updates": updates, "transactional": transactional}
    return run_idempotent_tool_mutation(
        tool_name="loop.bulk_update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_bulk.bulk_update_loops(
            updates=updates,
            transactional=transactional,
            conn=conn,
        ),
    )


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

    payload = {"items": items, "transactional": transactional}
    return run_idempotent_tool_mutation(
        tool_name="loop.bulk_close",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_bulk.bulk_close_loops(
            items=items,
            transactional=transactional,
            conn=conn,
        ),
    )


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

    for item in items:
        if "snooze_until_utc" in item and item["snooze_until_utc"] is not None:
            validate_iso8601_timestamp(item["snooze_until_utc"], "snooze_until_utc")

    payload = {"items": items, "transactional": transactional}
    return run_idempotent_tool_mutation(
        tool_name="loop.bulk_snooze",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_bulk.bulk_snooze_loops(
            items=items,
            transactional=transactional,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def loop_bulk_enrich(
    loop_ids: list[int],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bulk enrich multiple explicitly selected loops.

    Args:
        loop_ids: Loop identifiers to enrich.
        request_id: Optional idempotency key.

    Returns:
        Dict with `ok`, `results`, `succeeded`, and `failed`.

    Raises:
        ToolError: If loop_ids exceeds BULK_OPERATION_MAX_ITEMS limit.
    """
    if len(loop_ids) > BULK_OPERATION_MAX_ITEMS:
        raise ToolError(
            f"Bulk enrich exceeds maximum items limit: {len(loop_ids)} > {BULK_OPERATION_MAX_ITEMS}"
        )

    payload = {"loop_ids": loop_ids}
    return run_idempotent_tool_mutation(
        tool_name="loop.bulk_enrich",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: orchestrate_bulk_loop_enrichment(
            loop_ids=loop_ids,
            conn=conn,
            settings=settings,
        ).to_payload(),
    )


@with_mcp_error_handling
def loop_bulk_enrich_query(
    query: str,
    limit: int = 100,
    dry_run: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Preview or enrich loops selected by a DSL query.

    Args:
        query: DSL query string used to select loops.
        limit: Maximum loops to affect.
        dry_run: If true, preview targets without enriching them.
        request_id: Optional idempotency key for non-dry-run executions.

    Returns:
        Dry run returns `query`, `dry_run`, `matched_count`, `limited`, and `targets`.
        Execution returns `query`, `dry_run`, `ok`, `matched_count`, `limited`,
        `results`, `succeeded`, and `failed`.

    Raises:
        ToolError: If limit exceeds BULK_OPERATION_MAX_ITEMS.
    """
    if limit > BULK_OPERATION_MAX_ITEMS:
        raise ToolError(
            "Bulk enrich query limit exceeds maximum items limit: "
            f"{limit} > {BULK_OPERATION_MAX_ITEMS}"
        )

    if dry_run:
        from .. import db
        from ..settings import get_settings

        settings = get_settings()
        with db.core_connection(settings) as conn:
            return orchestrate_query_bulk_loop_enrichment(
                query=query,
                limit=limit,
                dry_run=True,
                conn=conn,
                settings=settings,
            )

    payload = {"query": query, "limit": limit, "dry_run": False}
    return run_idempotent_tool_mutation(
        tool_name="loop.bulk_enrich_query",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: orchestrate_query_bulk_loop_enrichment(
            query=query,
            limit=limit,
            dry_run=False,
            conn=conn,
            settings=settings,
        ),
    )


def register_loop_bulk_tools(mcp: "FastMCP") -> None:
    """Register loop bulk operation tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="loop.bulk_update")(with_db_init(loop_bulk_update))
    mcp.tool(name="loop.bulk_close")(with_db_init(loop_bulk_close))
    mcp.tool(name="loop.bulk_snooze")(with_db_init(loop_bulk_snooze))
    mcp.tool(name="loop.bulk_enrich")(with_db_init(loop_bulk_enrich))
    mcp.tool(name="loop.bulk_enrich_query")(with_db_init(loop_bulk_enrich_query))
