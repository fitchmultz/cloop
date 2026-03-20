"""MCP tools for durable working-set undo.

Purpose:
    Expose exact-handle working-set undo to MCP clients through thin shared
    tool wrappers.

Responsibilities:
    - Register MCP tools for deterministic working-set undo
    - Reuse shared idempotency and error-handling helpers around
      `loops/working_sets.py`
    - Keep MCP docstrings aligned with the operator-facing undo contract

Scope:
    - MCP transport wrappers for working-set undo only

Usage:
    - Registered by `cloop.mcp_server` through `cloop.mcp_tools`

Invariants/Assumptions:
    - Undo targets one exact latest reversible working-set event
    - MCP callers may safely retry with the same `request_id`

Non-scope:
    - Working-set CRUD or read/listing tools
    - MCP server assembly
    - Working-set business logic implementation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..loops import working_sets
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def working_set_undo(
    expected_event_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Undo one exact latest working-set mutation event.

    Use this when a prior working-set response exposed
    `latest_reversible_event_id` and you want to reverse that exact mutation
    without guessing which event is currently latest. If a newer working-set
    change happened first, this tool fails with a stale-handle error instead of
    undoing the wrong state.

    Args:
        expected_event_id: Exact reversible working-set event ID returned by a
            previous working-set or working-set-context response.
        request_id: Optional idempotency key. Reusing the same key with the same
            arguments replays the original undo result.

    Returns:
        Dict with the shared working-set undo contract:
        - `working_set`: restored working-set payload when the undo targets a set
        - `context`: current working-set context payload after undo
        - `affected_working_set_id` / `affected_working_set_name`: primary set touched
        - `undone_event_id` / `undone_event_type`: event that was reversed
        - `undo_event_id`: audit event recorded for the undo mutation
        - `summary`: human-readable explanation of what changed

    Raises:
        ToolError: If the event handle is stale, missing, not reversible, or the
            underlying working-set state can no longer be restored safely.

    Examples:
        - Undo a just-created working set after deciding not to keep it.
        - Restore the prior active working-set context after an accidental focus switch.
        - Safely retry the same undo request by reusing `request_id`.
    """
    payload = {"expected_event_id": expected_event_id}
    return run_idempotent_tool_mutation(
        tool_name="working_set.undo",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.undo_working_set_event(
            expected_event_id=expected_event_id,
            conn=conn,
        ),
    )


def register_working_set_tools(mcp: "FastMCP") -> None:
    """Register working-set MCP tools."""
    from ._runtime import with_db_init

    mcp.tool(name="working_set.undo")(with_db_init(working_set_undo))
