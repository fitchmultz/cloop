"""Memory tool executors and definitions.

Purpose:
    Implement the direct memory-management tools exposed through `cloop.tools`.

Responsibilities:
    - Execute memory create, search, update, and delete flows
    - Shape tool-friendly payloads for persisted memory entries
    - Publish transport-neutral tool definitions for memory operations

Scope:
    - Direct memory tool execution and registration only

Non-scope:
    - Memory persistence internals
    - Non-tool memory transport surfaces

Usage:
    - Imported by the internal tool registry and re-exported by `cloop.tools`

Invariants/Assumptions:
    - Canonical memory behavior lives in `cloop.memory_management`
    - Tool payloads remain deterministic and dictionary-shaped
    - Entry IDs are validated before update/delete operations
"""

from __future__ import annotations

from typing import Any

from .. import memory_management
from ..loops.errors import ValidationError
from ..settings import get_settings
from .models import ToolDefinition


def execute_memory_create(**kwargs: Any) -> dict[str, Any]:
    """Create a memory entry."""
    entry = memory_management.create_memory_entry(
        payload={
            "key": kwargs.get("key"),
            "content": kwargs.get("content"),
            "category": kwargs.get("category", "fact"),
            "priority": kwargs.get("priority", 0),
            "source": kwargs.get("source", "user_stated"),
            "metadata": kwargs.get("metadata"),
        },
        settings=get_settings(),
    )
    return {"action": "memory_create", "memory": entry}


def execute_memory_search(**kwargs: Any) -> dict[str, Any]:
    """Search memory entries."""
    query = kwargs.get("query")
    if query is None:
        raise ValidationError("query", "query is required")

    result = memory_management.search_memory_entries(
        query=str(query),
        category=kwargs.get("category"),
        source=kwargs.get("source"),
        min_priority=kwargs.get("min_priority"),
        limit=kwargs.get("limit", 10),
        settings=get_settings(),
    )
    return {"action": "memory_search", "memories": result["items"], "query": result["query"]}


def execute_memory_update(**kwargs: Any) -> dict[str, Any]:
    """Update a memory entry."""
    entry_id = kwargs.get("entry_id")
    if entry_id is None:
        raise ValidationError("entry_id", "entry_id is required")

    entry = memory_management.update_memory_entry(
        entry_id=int(entry_id),
        fields={
            key: value
            for key, value in {
                "key": kwargs.get("key"),
                "content": kwargs.get("content"),
                "category": kwargs.get("category"),
                "priority": kwargs.get("priority"),
                "source": kwargs.get("source"),
                "metadata": kwargs.get("metadata"),
            }.items()
            if value is not None
        },
        settings=get_settings(),
    )
    return {"action": "memory_update", "memory": entry}


def execute_memory_delete(**kwargs: Any) -> dict[str, Any]:
    """Delete a memory entry."""
    entry_id = kwargs.get("entry_id")
    if entry_id is None:
        raise ValidationError("entry_id", "entry_id is required")
    return {
        "action": "memory_delete",
        **memory_management.delete_memory_entry(
            entry_id=int(entry_id),
            settings=get_settings(),
        ),
    }


MEMORY_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="memory_create",
        description="Create a memory entry to persist preferences, facts, or commitments",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Optional identifier for the memory"},
                "content": {"type": "string", "description": "The memory content to store"},
                "category": {
                    "type": "string",
                    "enum": ["preference", "fact", "commitment", "context"],
                    "default": "fact",
                },
                "priority": {"type": "integer", "default": 0, "minimum": 0, "maximum": 100},
                "source": {
                    "type": "string",
                    "enum": ["user_stated", "inferred", "imported", "system"],
                    "default": "user_stated",
                },
            },
            "required": ["content"],
        },
        executor=execute_memory_create,
    ),
    ToolDefinition(
        name="memory_search",
        description="Search memory entries by text query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
                "category": {
                    "type": "string",
                    "enum": ["preference", "fact", "commitment", "context"],
                },
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        executor=execute_memory_search,
    ),
    ToolDefinition(
        name="memory_update",
        description="Update an existing memory entry",
        input_schema={
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "content": {"type": "string"},
                "priority": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["entry_id"],
        },
        executor=execute_memory_update,
    ),
    ToolDefinition(
        name="memory_delete",
        description="Delete a memory entry by ID",
        input_schema={
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
            },
            "required": ["entry_id"],
        },
        executor=execute_memory_delete,
    ),
)
