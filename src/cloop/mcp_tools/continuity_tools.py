"""MCP tools for continuity diagnostics.

Purpose:
    Expose durable continuity delivery diagnostics to MCP clients through the
    shared bounded-read contract.

Responsibilities:
    - Inspect canonical continuity delivery decisions.
    - Preserve the shared cursor, reason vocabulary, and truncation semantics.
    - Register continuity diagnostics tools with the MCP server.

Non-scope:
    - Continuity mutation workflows.
    - Re-implementing continuity diagnostics policy in MCP wrappers.

Scope:
    - Read-only MCP wrappers for continuity delivery diagnostics.

Usage:
    - Imported by `cloop.mcp_server` during MCP server assembly.
    - Called by MCP clients through `continuity.delivery_decisions`.

Invariants/Assumptions:
    - Continuity diagnostics reuse the same shared storage contract as HTTP,
      CLI, and push-notification selection.
    - MCP wrappers must stay thin and must not re-implement diagnostics policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..schemas._loops.continuity import ContinuityDeliveryInspectionChannel
from ..storage.continuity_store import read_continuity_delivery_inspection
from ._runtime import with_db_init, with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def continuity_delivery_decisions(
    channel: ContinuityDeliveryInspectionChannel = "all",
    limit: int = 3,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Inspect canonical continuity delivery decisions.

    Use this when you need the same durable delivery diagnostics contract that
    drives HTTP debugging and scheduler push selection. The result preserves the
    canonical `reason` vocabulary, resend timing, latest push provenance, and
    the opaque continuation cursor for continuing one bounded scan.

    Args:
        channel: Diagnostics slice to inspect. Valid values are `all` and `push`.
            Use `push` when you need the exact sendability decisions used for
            browser push delivery.
        limit: Requested number of sendable decisions to target. Push scans may
            include additional non-sendable rows while walking the bounded scan
            budget to find later sendable notifications.
        cursor: Opaque continuation cursor returned by a prior
            `continuity.delivery_decisions` response. Omit it to start a fresh
            stable snapshot scan.

    Returns:
        Dict matching the shared continuity delivery-inspection contract with:
        - `inspected_at_utc`: UTC timestamp for this inspection read
        - `channel`: the inspected diagnostics channel
        - `limit`: requested sendable-decision target
        - `truncated`: whether more rows remain behind `continuation.cursor`
        - `continuation`: optional object containing the next opaque `cursor`
        - `decisions`: ordered decision rows with `record`, `reason`,
          `resend_ready_at_utc`, and `latest_push_delivery`

    Raises:
        ToolError: If `limit`, `channel`, or `cursor` is invalid.

    Examples:
        - Inspect the first page of all delivery decisions.
        - Inspect push-only sendability and continue with the returned cursor.
        - Correlate one decision with `latest_push_delivery` when debugging why
          a notification did or did not reach browser subscribers.
    """
    from ..settings import get_settings

    return read_continuity_delivery_inspection(
        limit=limit,
        settings=get_settings(),
        channel=channel,
        cursor=cursor,
    ).model_dump(mode="python")


def register_continuity_tools(mcp: "FastMCP") -> None:
    """Register continuity diagnostics MCP tools."""
    mcp.tool(name="continuity.delivery_decisions")(with_db_init(continuity_delivery_decisions))


__all__ = ["continuity_delivery_decisions", "register_continuity_tools"]
