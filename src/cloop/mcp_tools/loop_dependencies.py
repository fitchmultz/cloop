"""Loop dependency MCP tools.

Purpose:
    MCP tools for managing dependencies between loops.

Responsibilities:
    - Add and remove dependency relationships between loops
    - List a loop's dependencies (blockers)
    - List loops that are blocked by a given loop
    - Handle idempotency for dependency mutations

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

from ..loops.service import (
    add_loop_dependency,
    get_loop_blocking,
    get_loop_dependencies,
    remove_loop_dependency,
)
from ._mutation import run_idempotent_tool_mutation

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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
    payload = {"loop_id": loop_id, "depends_on_loop_id": depends_on_loop_id}
    return run_idempotent_tool_mutation(
        tool_name="loop.dependency.add",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: add_loop_dependency(
            loop_id=loop_id,
            depends_on_loop_id=depends_on_loop_id,
            conn=conn,
        ),
    )


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
    payload = {"loop_id": loop_id, "depends_on_loop_id": depends_on_loop_id}
    return run_idempotent_tool_mutation(
        tool_name="loop.dependency.remove",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: remove_loop_dependency(
            loop_id=loop_id,
            depends_on_loop_id=depends_on_loop_id,
            conn=conn,
        ),
    )


def loop_dependency_list(loop_id: int) -> list[dict[str, Any]]:
    """List all dependencies (blockers) for a loop.

    Args:
        loop_id: The loop to check

    Returns:
        List of dependency loops with status
    """
    from .. import db
    from ..settings import get_settings

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
    from .. import db
    from ..settings import get_settings

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
