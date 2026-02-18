"""Loop bulk operation MCP tools.

Purpose:
    MCP tools for bulk operations on multiple loops.

Responsibilities:
    - Bulk update multiple loops with per-item results
    - Bulk close multiple loops with completion/drop status
    - Bulk snooze multiple loops until specified times
    - Support transactional mode (all-or-nothing)
    - Validate bulk operation limits and timestamp formats
    - Handle idempotency for bulk mutations

Tools:
    - loop.bulk_update: Update multiple loops at once
    - loop.bulk_close: Close multiple loops at once
    - loop.bulk_snooze: Snooze multiple loops at once

Non-scope:
    - Single-item operations (see loop_core.py)
    - Transaction management (handled in service layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..constants import BULK_OPERATION_MAX_ITEMS
from ..idempotency import (
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ..loops import service as loop_service
from ..loops.models import validate_iso8601_timestamp
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


def register_loop_bulk_tools(mcp: "FastMCP") -> None:
    """Register loop bulk operation tools with the MCP server."""
    from ..mcp_server import with_db_init, with_mcp_error_handling

    mcp.tool(name="loop.bulk_update")(with_db_init(with_mcp_error_handling(loop_bulk_update)))
    mcp.tool(name="loop.bulk_close")(with_db_init(with_mcp_error_handling(loop_bulk_close)))
    mcp.tool(name="loop.bulk_snooze")(with_db_init(with_mcp_error_handling(loop_bulk_snooze)))
