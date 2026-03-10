"""Loop saved view MCP tools.

Purpose:
    MCP tools for managing saved views with DSL queries.

Responsibilities:
    - Create, update, and delete saved views with DSL queries
    - List and retrieve saved views
    - Apply saved views to filter and return matching loops
    - Handle idempotency for view mutations

Tools:
    - loop.view.create: Create a saved view
    - loop.view.list: List all saved views
    - loop.view.get: Get a view by ID
    - loop.view.update: Update a saved view
    - loop.view.delete: Delete a saved view
    - loop.view.apply: Apply a saved view and return matching loops

Non-scope:
    - Core loop operations (see loop_core.py)
    - View persistence layer (see loops/service.py)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..constants import DEFAULT_LOOP_LIST_LIMIT
from ..loops import views as loop_views
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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
    payload = {"name": name, "query": query, "description": description}
    return run_idempotent_tool_mutation(
        tool_name="loop.view.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_views.create_loop_view(
            name=name,
            query=query,
            description=description,
            conn=conn,
        ),
    )


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_views.list_loop_views(conn=conn)


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_views.get_loop_view(view_id=view_id, conn=conn)


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
    payload = {"view_id": view_id, "name": name, "query": query, "description": description}
    return run_idempotent_tool_mutation(
        tool_name="loop.view.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: loop_views.update_loop_view(
            view_id=view_id,
            name=name,
            query=query,
            description=description,
            conn=conn,
        ),
    )


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
    payload = {"view_id": view_id}
    return run_idempotent_tool_mutation(
        tool_name="loop.view.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: _delete_view(view_id=view_id, conn=conn),
    )


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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_views.apply_loop_view_page(
            view_id=view_id,
            limit=limit,
            cursor=cursor,
            conn=conn,
        )


def _delete_view(*, view_id: int, conn: Any) -> dict[str, Any]:
    """Delete a saved view and normalize the tool response."""
    loop_views.delete_loop_view(view_id=view_id, conn=conn)
    return {"deleted": True}


def register_loop_view_tools(mcp: "FastMCP") -> None:
    """Register loop view tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="loop.view.create")(with_db_init(loop_view_create))
    mcp.tool(name="loop.view.list")(with_db_init(loop_view_list))
    mcp.tool(name="loop.view.get")(with_db_init(loop_view_get))
    mcp.tool(name="loop.view.update")(with_db_init(loop_view_update))
    mcp.tool(name="loop.view.delete")(with_db_init(loop_view_delete))
    mcp.tool(name="loop.view.apply")(with_db_init(loop_view_apply))
