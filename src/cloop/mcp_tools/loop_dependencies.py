"""Loop dependency MCP tools.

Purpose:
    MCP tools for managing dependencies between loops.

Tools:
    - loop.dependency.add: Add a dependency relationship
    - loop.dependency.remove: Remove a dependency relationship
    - loop.dependency.list: List all dependencies for a loop
    - loop.dependency.blocking: List loops blocked by this loop

Non-scope:
    - Dependency validation (handled in service layer)
    - Cycle detection (handled in service layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..idempotency import (
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ..loops.service import (
    add_loop_dependency,
    get_loop_blocking,
    get_loop_dependencies,
    remove_loop_dependency,
)
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


def loop_dependency_list(loop_id: int) -> list[dict[str, Any]]:
    """List all dependencies (blockers) for a loop.

    Args:
        loop_id: The loop to check

    Returns:
        List of dependency loops with status
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return get_loop_dependencies(loop_id=loop_id, conn=conn)


def loop_dependency_blocking(loop_id: int) -> list[dict[str, Any]]:
    """List all loops that depend on this loop.

    Args:
        loop_id: The loop to check

    Returns:
        List of dependent loops
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return get_loop_blocking(loop_id=loop_id, conn=conn)


def register_loop_dependency_tools(mcp: "FastMCP") -> None:
    """Register loop dependency tools with the MCP server."""
    from ..mcp_server import with_db_init, with_mcp_error_handling

    mcp.tool(name="loop.dependency.add")(with_db_init(with_mcp_error_handling(loop_dependency_add)))
    mcp.tool(name="loop.dependency.remove")(
        with_db_init(with_mcp_error_handling(loop_dependency_remove))
    )
    mcp.tool(name="loop.dependency.list")(
        with_db_init(with_mcp_error_handling(loop_dependency_list))
    )
    mcp.tool(name="loop.dependency.blocking")(
        with_db_init(with_mcp_error_handling(loop_dependency_blocking))
    )
