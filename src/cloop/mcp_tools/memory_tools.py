"""Direct memory-management MCP tools.

Purpose:
    Expose durable memory CRUD and query operations to MCP clients through a
    narrow, deterministic contract that reuses the shared memory-management
    service layer.

Responsibilities:
    - List and search memory entries with the canonical filters/cursor contract
    - Get one memory entry by ID
    - Create, update, and delete memory entries idempotently

Non-scope:
    - Chat grounding or inferred memory extraction
    - Transport-specific storage or validation logic
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import memory_management
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def memory_list(
    category: str | None = None,
    source: str | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List durable memory entries.

    Args:
        category: Optional category filter.
        source: Optional source filter.
        min_priority: Optional inclusive priority floor.
        limit: Maximum number of items to return.
        cursor: Optional pagination cursor from a previous response.

    Returns:
        Dict with `items`, `next_cursor`, and `limit`.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return memory_management.list_memory_entries(
            category=category,
            source=source,
            min_priority=min_priority,
            limit=limit,
            cursor=cursor,
            settings=settings,
            conn=conn,
        )


@with_mcp_error_handling
def memory_search(
    query: str,
    category: str | None = None,
    source: str | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Search durable memory entries.

    Args:
        query: Search text to match against memory key and content.
        category: Optional category filter.
        source: Optional source filter.
        min_priority: Optional inclusive priority floor.
        limit: Maximum number of items to return.
        cursor: Optional pagination cursor from a previous response.

    Returns:
        Dict with `items`, `next_cursor`, `limit`, and `query`.

    Raises:
        ToolError: If the query is invalid.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return memory_management.search_memory_entries(
            query=query,
            category=category,
            source=source,
            min_priority=min_priority,
            limit=limit,
            cursor=cursor,
            settings=settings,
            conn=conn,
        )


@with_mcp_error_handling
def memory_get(entry_id: int) -> dict[str, Any]:
    """Get one durable memory entry.

    Args:
        entry_id: Memory entry identifier.

    Returns:
        Memory entry payload.

    Raises:
        ToolError: If the memory entry does not exist.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return memory_management.get_memory_entry(entry_id=entry_id, settings=settings, conn=conn)


@with_mcp_error_handling
def memory_create(
    content: str,
    key: str | None = None,
    category: str = "fact",
    priority: int = 0,
    source: str = "user_stated",
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create one durable memory entry.

    Args:
        content: Memory content/value.
        key: Optional natural-language identifier.
        category: Memory category.
        priority: Retrieval priority from 0 to 100.
        source: Origin label for the memory.
        metadata: Optional structured metadata object.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Created memory entry payload.

    Raises:
        ToolError: If validation fails.
    """
    payload = {
        "key": key,
        "content": content,
        "category": category,
        "priority": priority,
        "source": source,
        "metadata": metadata,
    }
    return run_idempotent_tool_mutation(
        tool_name="memory.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: memory_management.create_memory_entry(
            payload=payload,
            settings=settings,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def memory_update(
    entry_id: int,
    key: str | None = None,
    content: str | None = None,
    category: str | None = None,
    priority: int | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    clear_key: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one durable memory entry.

    Args:
        entry_id: Memory entry identifier.
        key: Optional replacement key.
        content: Optional replacement content.
        category: Optional replacement category.
        priority: Optional replacement priority.
        source: Optional replacement source.
        metadata: Optional replacement metadata object.
        clear_key: When true, clear the key regardless of the `key` argument.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Updated memory entry payload.

    Raises:
        ToolError: If validation fails or the memory entry is missing.
    """
    fields: dict[str, Any] = {
        field_name: field_value
        for field_name, field_value in {
            "key": key,
            "content": content,
            "category": category,
            "priority": priority,
            "source": source,
            "metadata": metadata,
        }.items()
        if field_value is not None
    }
    if clear_key:
        fields["key"] = None

    payload = {"entry_id": entry_id, "fields": fields}
    return run_idempotent_tool_mutation(
        tool_name="memory.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: memory_management.update_memory_entry(
            entry_id=entry_id,
            fields=fields,
            settings=settings,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def memory_delete(
    entry_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one durable memory entry.

    Args:
        entry_id: Memory entry identifier.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with `entry_id` and `deleted`.

    Raises:
        ToolError: If the memory entry does not exist.
    """
    payload = {"entry_id": entry_id}
    return run_idempotent_tool_mutation(
        tool_name="memory.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: memory_management.delete_memory_entry(
            entry_id=entry_id,
            settings=settings,
            conn=conn,
        ),
    )


def register_memory_tools(mcp: "FastMCP") -> None:
    """Register direct memory-management MCP tools."""
    from ._runtime import with_db_init

    mcp.tool(name="memory.list")(with_db_init(memory_list))
    mcp.tool(name="memory.search")(with_db_init(memory_search))
    mcp.tool(name="memory.get")(with_db_init(memory_get))
    mcp.tool(name="memory.create")(with_db_init(memory_create))
    mcp.tool(name="memory.update")(with_db_init(memory_update))
    mcp.tool(name="memory.delete")(with_db_init(memory_delete))
