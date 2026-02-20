"""Tool executors for LLM function calling.

Purpose:
    Implement tool handlers callable by LLM during chat completions.

Responsibilities:
    - Execute note operations (read_note, write_note)
    - Execute loop lifecycle operations (create, update, close, transition, snooze)
    - Execute loop query operations (list, search, next, get)
    - Execute loop enrichment (enrich)
    - Validate required fields before execution
    - Return structured results for LLM context

Non-scope:
    - Tool registration with litellm (see llm.py)
    - HTTP API endpoints (see routes/)
    - MCP server tools (see mcp_server.py)

Entrypoints:
    - execute_* functions for each tool
    - EXECUTORS: Dict[str, ToolExecutor] mapping names to handlers
    - TOOL_SPECS: List[Dict] for litellm tool definitions
"""

import json
import logging
import sqlite3
from typing import Any, Dict, List, Protocol

from . import db
from .constants import MEMORY_CONTENT_MAX, MEMORY_KEY_MAX, NOTE_BODY_MAX, TITLE_MAX
from .loops.errors import (
    CloopError,
    LoopNotFoundError,
    MemoryNotFoundError,
    NoteNotFoundError,
    TransitionError,
    ValidationError,
)
from .loops.models import LoopStatus, format_utc_datetime, is_terminal_status, utc_now
from .settings import get_settings

logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    def __call__(self, **kwargs: Any) -> Dict[str, Any]: ...


def _require_fields(payload: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if payload.get(field) is None]
    if missing:
        raise ValidationError("fields", f"missing required: {', '.join(missing)}")


def _loop_to_dict(loop: Any) -> Dict[str, Any]:
    """Convert LoopRecord to dict for JSON response.

    Handles both LoopRecord objects and dicts (already enriched records).
    """
    if isinstance(loop, dict):
        return loop

    return {
        "id": loop.id,
        "raw_text": loop.raw_text,
        "status": loop.status.value if hasattr(loop.status, "value") else loop.status,
        "created_at_utc": format_utc_datetime(loop.created_at_utc) if loop.created_at_utc else None,
        "updated_at_utc": format_utc_datetime(loop.updated_at_utc) if loop.updated_at_utc else None,
        "title": loop.title,
        "summary": loop.summary,
        "next_action": loop.next_action,
        "due_at_utc": format_utc_datetime(loop.due_at_utc) if loop.due_at_utc else None,
        "snooze_until_utc": format_utc_datetime(loop.snooze_until_utc)
        if loop.snooze_until_utc
        else None,
        "time_minutes": loop.time_minutes,
        "tags": list(loop.tags) if hasattr(loop, "tags") and loop.tags else [],
    }


# ============================================================================
# Note Tool Executors
# ============================================================================


def execute_write_note(**kwargs: Any) -> Dict[str, Any]:
    payload = {"title": kwargs.get("title"), "body": kwargs.get("body")}
    _require_fields(payload, "title", "body")

    # Validate max lengths
    title = str(payload["title"])
    body = str(payload["body"])
    if len(title) > TITLE_MAX:
        raise ValidationError("title", f"exceeds maximum length of {TITLE_MAX} characters")
    if len(body) > NOTE_BODY_MAX:
        raise ValidationError("body", f"exceeds maximum length of {NOTE_BODY_MAX} characters")

    note_id = kwargs.get("note_id")
    note = db.upsert_note(title=title, body=body, note_id=note_id)
    return {"action": "write_note", "note": note}


def execute_read_note(**kwargs: Any) -> Dict[str, Any]:
    note_id = kwargs.get("note_id")
    if note_id is None:
        raise ValidationError("note_id", "required for read_note")
    note = db.read_note(int(note_id))
    if note is None:
        raise NoteNotFoundError(note_id=int(note_id))
    return {"action": "read_note", "note": note}


def execute_list_notes(**kwargs: Any) -> Dict[str, Any]:
    """List notes with cursor-based pagination."""
    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    result = db.list_notes(
        limit=min(limit, 100),
        cursor=cursor,
    )
    return {"action": "list_notes", **result}


def execute_search_notes(**kwargs: Any) -> Dict[str, Any]:
    """Search notes by text query."""
    query = kwargs.get("query", "")
    if not query:
        raise ValidationError("query", "required for search_notes")

    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    result = db.search_notes(
        query=query,
        limit=min(limit, 100),
        cursor=cursor,
    )
    return {"action": "search_notes", **result}


# ============================================================================
# Loop Tool Executors
# ============================================================================


def _handle_tool_error(operation: str, exc: Exception) -> None:
    """Handle tool execution errors with proper logging.

    Re-raises CloopError instances unchanged.
    Converts known error types to ValidationError.
    Logs unexpected errors for debugging.
    """
    if isinstance(exc, CloopError):
        raise

    # Known error types that should be converted to validation errors
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        raise ValidationError(operation, f"failed to {operation.replace('_', ' ')}: {exc}") from exc

    # Database errors
    if isinstance(exc, sqlite3.Error):
        logger.error(f"Database error in {operation}: {exc}")
        raise ValidationError(operation, f"database error during {operation}: {exc}") from exc

    # Unexpected errors - log and re-raise as validation error
    logger.exception(f"Unexpected error in {operation}: {exc}")
    raise ValidationError(operation, f"unexpected error during {operation}: {exc}") from exc


def execute_loop_create(**kwargs: Any) -> Dict[str, Any]:
    """Create a new loop."""
    from .loops import service as loop_service

    raw_text = kwargs.get("raw_text")
    if not raw_text:
        raise ValidationError("raw_text", "required for loop_create")

    captured_at = kwargs.get("captured_at")
    if not captured_at:
        captured_at = format_utc_datetime(utc_now())

    tz_offset = kwargs.get("client_tz_offset_min", 0)
    status_str = kwargs.get("status", "inbox")

    try:
        status = LoopStatus(status_str)
    except ValueError as e:
        raise ValidationError("status", f"invalid status: {status_str}") from e

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.capture_loop(
                raw_text=raw_text,
                captured_at_iso=captured_at,
                client_tz_offset_min=tz_offset,
                status=status,
                conn=conn,
            )
    except ValidationError, LoopNotFoundError:
        raise
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_create", e)

    return {"action": "loop_create", "loop": result}


def execute_loop_update(**kwargs: Any) -> Dict[str, Any]:
    """Update fields on an existing loop."""
    from .loops import service as loop_service

    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", "required for loop_update")

    fields = kwargs.get("fields", {})
    if not fields:
        raise ValidationError("fields", "at least one field required")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.update_loop(
                loop_id=int(loop_id),
                fields=fields,
                conn=conn,
            )
    except LoopNotFoundError as e:
        raise ValidationError("loop_id", f"Loop not found: {loop_id}") from e
    except ValidationError, TransitionError:
        raise
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_update", e)

    return {"action": "loop_update", "loop": result}


def execute_loop_close(**kwargs: Any) -> Dict[str, Any]:
    """Close a loop as completed or dropped."""
    from .loops import service as loop_service

    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", "required for loop_close")

    status_str = kwargs.get("status", "completed")
    note = kwargs.get("note")

    try:
        status = LoopStatus(status_str)
    except ValueError as e:
        raise ValidationError("status", f"invalid status: {status_str}") from e

    if status not in (LoopStatus.COMPLETED, LoopStatus.DROPPED):
        raise ValidationError("status", "must be 'completed' or 'dropped'")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.transition_status(
                loop_id=int(loop_id),
                to_status=status,
                note=note,
                conn=conn,
            )
    except LoopNotFoundError as e:
        raise ValidationError("loop_id", f"Loop not found: {loop_id}") from e
    except TransitionError as e:
        raise ValidationError(
            "status", f"Invalid transition: {e.from_status} -> {e.to_status}"
        ) from e
    except (ValidationError, ValueError) as e:
        raise ValidationError("fields", str(e)) from e
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_close", e)

    return {"action": "loop_close", "loop": result}


def execute_loop_list(**kwargs: Any) -> Dict[str, Any]:
    """List loops with optional status filter."""
    from .loops import service as loop_service

    status_str = kwargs.get("status")
    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    status = None
    if status_str:
        try:
            status = LoopStatus(status_str)
        except ValueError as e:
            raise ValidationError("status", f"invalid status: {status_str}") from e

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.list_loops_page(
                status=status,
                limit=min(limit, 100),  # Cap at 100
                cursor=cursor,
                conn=conn,
            )
    except ValidationError, LoopNotFoundError:
        raise
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_list", e)

    return {"action": "loop_list", **result}


def execute_loop_search(**kwargs: Any) -> Dict[str, Any]:
    """Search loops using DSL query."""
    from .loops import service as loop_service

    query = kwargs.get("query", "")
    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.search_loops_by_query_page(
                query=query,
                limit=min(limit, 100),
                cursor=cursor,
                conn=conn,
            )
    except ValidationError, LoopNotFoundError:
        raise
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_search", e)

    return {"action": "loop_search", **result}


def execute_loop_next(**kwargs: Any) -> Dict[str, Any]:
    """Get prioritized next action loops."""
    from .loops import service as loop_service

    limit = kwargs.get("limit", 5)

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.next_loops(
                limit=min(limit, 20),  # Cap at 20
                conn=conn,
                settings=settings,
            )
    except ValidationError, LoopNotFoundError:
        raise
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_next", e)

    # Result is already a dict with bucket names
    return {"action": "loop_next", **result}


def execute_loop_transition(**kwargs: Any) -> Dict[str, Any]:
    """Transition loop to a non-terminal status."""
    from .loops import service as loop_service

    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", "required for loop_transition")

    status_str = kwargs.get("status")
    if not status_str:
        raise ValidationError("status", "required for loop_transition")
    note = kwargs.get("note")

    try:
        status = LoopStatus(status_str)
    except ValueError as e:
        raise ValidationError("status", f"invalid status: {status_str}") from e

    if is_terminal_status(status):
        raise ValidationError("status", "use loop_close for terminal statuses")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.transition_status(
                loop_id=int(loop_id),
                to_status=status,
                note=note,
                conn=conn,
            )
    except LoopNotFoundError as e:
        raise ValidationError("loop_id", f"Loop not found: {loop_id}") from e
    except TransitionError as e:
        raise ValidationError(
            "status", f"Invalid transition: {e.from_status} -> {e.to_status}"
        ) from e
    except ValidationError:
        raise
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_transition", e)

    return {"action": "loop_transition", "loop": result}


def execute_loop_snooze(**kwargs: Any) -> Dict[str, Any]:
    """Snooze a loop until a future time."""
    from .loops import service as loop_service

    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", "required for loop_snooze")

    snooze_until = kwargs.get("snooze_until_utc")
    if not snooze_until:
        raise ValidationError("snooze_until_utc", "required for loop_snooze")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.update_loop(
                loop_id=int(loop_id),
                fields={"snooze_until_utc": snooze_until},
                conn=conn,
            )
    except LoopNotFoundError as e:
        raise ValidationError("loop_id", f"Loop not found: {loop_id}") from e
    except (ValidationError, ValueError) as e:
        raise ValidationError("fields", str(e)) from e
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_snooze", e)

    return {"action": "loop_snooze", "loop": result}


def execute_loop_enrich(**kwargs: Any) -> Dict[str, Any]:
    """Trigger AI enrichment for a loop."""
    from .loops import enrichment as loop_enrichment
    from .loops import service as loop_service

    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", "required for loop_enrich")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            loop_service.request_enrichment(loop_id=int(loop_id), conn=conn)
            result = loop_enrichment.enrich_loop(
                loop_id=int(loop_id),
                conn=conn,
                settings=settings,
            )
    except LoopNotFoundError as e:
        raise ValidationError("loop_id", f"Loop not found: {loop_id}") from e
    except (ValidationError, ValueError) as e:
        raise ValidationError("fields", str(e)) from e
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_enrich", e)

    return {"action": "loop_enrich", "loop": result}


def execute_loop_get(**kwargs: Any) -> Dict[str, Any]:
    """Get a single loop by ID."""
    from .loops import service as loop_service

    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", "required for loop_get")

    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            result = loop_service.get_loop(loop_id=int(loop_id), conn=conn)
    except LoopNotFoundError as e:
        raise ValidationError("loop_id", f"Loop not found: {loop_id}") from e
    except (ValidationError, ValueError) as e:
        raise ValidationError("fields", str(e)) from e
    except sqlite3.Error as e:
        raise ValidationError("database", f"Database error: {e}") from e
    except Exception as e:
        _handle_tool_error("loop_get", e)

    return {"action": "loop_get", "loop": result}


# ============================================================================
# Memory Tool Executors
# ============================================================================


def execute_memory_create(**kwargs: Any) -> Dict[str, Any]:
    """Create a new memory entry."""
    content = kwargs.get("content")
    if not content:
        raise ValidationError("content", "content is required")

    key = kwargs.get("key")
    if key is not None and len(str(key)) > MEMORY_KEY_MAX:
        raise ValidationError("key", f"exceeds maximum length of {MEMORY_KEY_MAX} characters")
    if len(str(content)) > MEMORY_CONTENT_MAX:
        raise ValidationError(
            "content", f"exceeds maximum length of {MEMORY_CONTENT_MAX} characters"
        )

    entry = db.create_memory_entry(
        key=key,
        content=content,
        category=kwargs.get("category", "fact"),
        priority=kwargs.get("priority", 0),
        source=kwargs.get("source", "user_stated"),
        metadata=kwargs.get("metadata"),
        settings=get_settings(),
    )
    return {"action": "memory_create", "memory": entry}


def execute_memory_search(**kwargs: Any) -> Dict[str, Any]:
    """Search memory entries."""
    query = kwargs.get("query")
    if not query:
        raise ValidationError("query", "query is required")

    result = db.search_memory_entries(
        query=query,
        category=kwargs.get("category"),
        source=kwargs.get("source"),
        min_priority=kwargs.get("min_priority"),
        limit=kwargs.get("limit", 10),
        settings=get_settings(),
    )
    return {"action": "memory_search", "memories": result["items"], "query": query}


def execute_memory_update(**kwargs: Any) -> Dict[str, Any]:
    """Update a memory entry."""
    entry_id = kwargs.get("entry_id")
    if not entry_id:
        raise ValidationError("entry_id", "entry_id is required")

    entry = db.update_memory_entry(
        entry_id,
        key=kwargs.get("key"),
        content=kwargs.get("content"),
        category=kwargs.get("category"),
        priority=kwargs.get("priority"),
        source=kwargs.get("source"),
        metadata=kwargs.get("metadata"),
        settings=get_settings(),
    )
    if entry is None:
        raise MemoryNotFoundError(entry_id)
    return {"action": "memory_update", "memory": entry}


def execute_memory_delete(**kwargs: Any) -> Dict[str, Any]:
    """Delete a memory entry."""
    entry_id = kwargs.get("entry_id")
    if not entry_id:
        raise ValidationError("entry_id", "entry_id is required")

    deleted = db.delete_memory_entry(entry_id, settings=get_settings())
    if not deleted:
        raise MemoryNotFoundError(entry_id)
    return {"action": "memory_delete", "deleted": True, "entry_id": entry_id}


# ============================================================================
# Tool Specifications
# ============================================================================


TOOL_SPECS: List[Dict[str, Any]] = [
    # Note tools
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": "Create or update a note with the supplied title and body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title for the note."},
                    "body": {"type": "string", "description": "Full body text."},
                    "note_id": {
                        "type": "integer",
                        "description": "Existing note id to update. Omit to create a new note.",
                    },
                },
                "required": ["title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Fetch a previously stored note by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "integer",
                        "description": "Identifier of the note to retrieve.",
                    }
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "List stored notes with pagination. Use to browse available notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 50, max: 100).",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor from previous response.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search notes by text query. Matches title and body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text to match against note title and body.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 50, max: 100).",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor from previous response.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # Loop tools
    {
        "type": "function",
        "function": {
            "name": "loop_create",
            "description": "Create a new loop/task. Use this to capture new items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "raw_text": {
                        "type": "string",
                        "description": "The text content of the loop/task.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["inbox", "actionable", "blocked", "scheduled"],
                        "description": "Initial status (default: inbox).",
                    },
                    "captured_at": {
                        "type": "string",
                        "description": "ISO 8601 timestamp (optional, defaults to now).",
                    },
                    "client_tz_offset_min": {
                        "type": "integer",
                        "description": "Timezone offset in minutes (default: 0).",
                    },
                },
                "required": ["raw_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_update",
            "description": "Update fields on an existing loop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer", "description": "ID of the loop to update."},
                    "fields": {
                        "type": "object",
                        "description": "Fields to update.",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "next_action": {
                                "type": "string",
                                "description": "What to do next for this task.",
                            },
                            "due_at_utc": {
                                "type": "string",
                                "description": "Due date as ISO 8601 timestamp.",
                            },
                            "time_minutes": {
                                "type": "integer",
                                "description": "Estimated time in minutes.",
                            },
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["loop_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_close",
            "description": "Close a loop as completed or dropped. Use when a task is done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer", "description": "ID of the loop to close."},
                    "status": {
                        "type": "string",
                        "enum": ["completed", "dropped"],
                        "description": "Terminal status (default: completed).",
                    },
                    "note": {"type": "string", "description": "Optional completion/drop note."},
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_list",
            "description": "List loops with optional status filter. Use to show tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "inbox",
                            "actionable",
                            "blocked",
                            "scheduled",
                            "completed",
                            "dropped",
                        ],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 50, max: 100).",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor from previous response.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_search",
            "description": "Search loops using query syntax. Supports status:value, tag:value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'status:inbox due:today').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 50, max: 100).",
                    },
                    "cursor": {"type": "string", "description": "Pagination cursor."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_next",
            "description": "Get prioritized next actions organized into buckets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max results per bucket (default: 5, max: 20).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_transition",
            "description": "Transition a loop to non-terminal status. Use loop_close.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer", "description": "ID of the loop."},
                    "status": {
                        "type": "string",
                        "enum": ["inbox", "actionable", "blocked", "scheduled"],
                        "description": "Target status.",
                    },
                    "note": {"type": "string", "description": "Optional transition note."},
                },
                "required": ["loop_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_snooze",
            "description": "Snooze a loop until a future time. Hidden from next actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer", "description": "ID of the loop to snooze."},
                    "snooze_until_utc": {
                        "type": "string",
                        "description": "ISO 8601 timestamp when snooze expires.",
                    },
                },
                "required": ["loop_id", "snooze_until_utc"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_enrich",
            "description": "Trigger AI enrichment for a loop. Extracts summary and tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer", "description": "ID of the loop to enrich."},
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_get",
            "description": "Get a single loop by its ID. Retrieve full task details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer", "description": "ID of the loop to retrieve."},
                },
                "required": ["loop_id"],
            },
        },
    },
    # Memory tools
    {
        "type": "function",
        "function": {
            "name": "memory_create",
            "description": "Create a memory entry to persist preferences, facts, or commitments",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search memory entries by text query",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": "Update an existing memory entry",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer"},
                    "content": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_delete",
            "description": "Delete a memory entry by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer"},
                },
                "required": ["entry_id"],
            },
        },
    },
]


EXECUTORS: Dict[str, ToolExecutor] = {
    # Note tools
    "write_note": execute_write_note,
    "read_note": execute_read_note,
    "list_notes": execute_list_notes,
    "search_notes": execute_search_notes,
    # Loop tools
    "loop_create": execute_loop_create,
    "loop_update": execute_loop_update,
    "loop_close": execute_loop_close,
    "loop_list": execute_loop_list,
    "loop_search": execute_loop_search,
    "loop_next": execute_loop_next,
    "loop_transition": execute_loop_transition,
    "loop_snooze": execute_loop_snooze,
    "loop_enrich": execute_loop_enrich,
    "loop_get": execute_loop_get,
    # Memory tools
    "memory_create": execute_memory_create,
    "memory_search": execute_memory_search,
    "memory_update": execute_memory_update,
    "memory_delete": execute_memory_delete,
}


def normalize_tool_arguments(raw: str | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("arguments", "invalid JSON") from exc
