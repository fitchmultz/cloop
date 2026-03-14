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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

from . import db, memory_management
from .ai_bridge.protocol import BridgeToolSpec
from .constants import NOTE_BODY_MAX, TITLE_MAX
from .loops import read_service
from .loops.errors import (
    CloopError,
    LoopNotFoundError,
    NoteNotFoundError,
    TransitionError,
    ValidationError,
)
from .loops.models import LoopStatus, format_utc_datetime, is_terminal_status, utc_now
from .settings import get_settings
from .storage import notes_store

logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    def __call__(self, **kwargs: Any) -> Dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Canonical transport-neutral tool registration."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    executor: ToolExecutor
    manual_exposed: bool = True
    agent_exposed: bool = True

    def as_openai_tool_spec(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def as_bridge_tool_spec(self) -> BridgeToolSpec:
        return BridgeToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )


def _require_fields(payload: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if payload.get(field) is None]
    if missing:
        raise ValidationError("fields", f"missing required: {', '.join(missing)}")


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
    note = notes_store.upsert_note(title=title, body=body, note_id=note_id)
    return {"action": "write_note", "note": note}


def execute_read_note(**kwargs: Any) -> Dict[str, Any]:
    note_id = kwargs.get("note_id")
    if note_id is None:
        raise ValidationError("note_id", "required for read_note")
    note = notes_store.read_note(int(note_id))
    if note is None:
        raise NoteNotFoundError(note_id=int(note_id))
    return {"action": "read_note", "note": note}


def execute_list_notes(**kwargs: Any) -> Dict[str, Any]:
    """List notes with cursor-based pagination."""
    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    result = notes_store.list_notes(
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

    result = notes_store.search_notes(
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


def _run_loop_db_action(
    operation: str,
    action: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Run a loop-domain DB action with shared connection/error handling."""
    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            return action(conn=conn, settings=settings)
    except Exception as exc:
        _handle_tool_error(operation, exc)
    raise AssertionError("unreachable")


def _require_loop_id(kwargs: dict[str, Any], *, operation: str) -> int:
    """Extract and validate a loop_id from tool kwargs."""
    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", f"required for {operation}")
    return int(loop_id)


def _parse_loop_status(
    raw_status: str | None,
    *,
    field: str = "status",
    required_for: str | None = None,
) -> LoopStatus:
    """Parse a LoopStatus value with stable tool-facing validation errors."""
    if not raw_status:
        if required_for is None:
            raise ValidationError(field, "status is required")
        raise ValidationError(field, f"required for {required_for}")
    try:
        return LoopStatus(raw_status)
    except ValueError as exc:
        raise ValidationError(field, f"invalid status: {raw_status}") from exc


def _map_loop_tool_errors(
    *,
    loop_id: int | None = None,
    wrap_field: str | None = None,
) -> Callable[[Exception], None]:
    """Build the shared domain-to-tool error mapping for loop executors."""

    def _mapper(exc: Exception) -> None:
        if isinstance(exc, LoopNotFoundError):
            resolved_loop_id = loop_id if loop_id is not None else exc.loop_id
            raise ValidationError("loop_id", f"Loop not found: {resolved_loop_id}") from exc
        if isinstance(exc, TransitionError):
            raise ValidationError(
                "status", f"Invalid transition: {exc.from_status} -> {exc.to_status}"
            ) from exc
        if isinstance(exc, ValidationError):
            if wrap_field is None:
                raise
            raise ValidationError(wrap_field, str(exc)) from exc
        raise exc

    return _mapper


def _execute_loop_action(
    *,
    operation: str,
    action: Callable[..., dict[str, Any]],
    loop_id: int | None = None,
    wrap_field: str | None = None,
) -> dict[str, Any]:
    """Run a loop-domain action with shared DB access and domain error mapping."""
    try:
        return _run_loop_db_action(operation, action)
    except Exception as exc:  # noqa: BLE001
        _map_loop_tool_errors(loop_id=loop_id, wrap_field=wrap_field)(exc)
        raise AssertionError("unreachable") from exc


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
    status = _parse_loop_status(kwargs.get("status", "inbox"))

    result = _execute_loop_action(
        operation="loop_create",
        action=lambda conn, settings: loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=tz_offset,
            status=status,
            conn=conn,
        ),
    )

    return {"action": "loop_create", "loop": result}


def execute_loop_update(**kwargs: Any) -> Dict[str, Any]:
    """Update fields on an existing loop."""
    from .loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_update")

    fields = kwargs.get("fields", {})
    if not fields:
        raise ValidationError("fields", "at least one field required")

    result = _execute_loop_action(
        operation="loop_update",
        loop_id=loop_id,
        action=lambda conn, settings: loop_service.update_loop(
            loop_id=loop_id,
            fields=fields,
            conn=conn,
        ),
    )

    return {"action": "loop_update", "loop": result}


def execute_loop_close(**kwargs: Any) -> Dict[str, Any]:
    """Close a loop as completed or dropped."""
    from .loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_close")
    note = kwargs.get("note")
    status = _parse_loop_status(kwargs.get("status", "completed"))

    if status not in (LoopStatus.COMPLETED, LoopStatus.DROPPED):
        raise ValidationError("status", "must be 'completed' or 'dropped'")

    result = _execute_loop_action(
        operation="loop_close",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: loop_service.transition_status(
            loop_id=loop_id,
            to_status=status,
            note=note,
            conn=conn,
        ),
    )

    return {"action": "loop_close", "loop": result}


def execute_loop_list(**kwargs: Any) -> Dict[str, Any]:
    """List loops with optional status filter."""
    status_str = kwargs.get("status")
    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    status = _parse_loop_status(status_str) if status_str else None

    result = _execute_loop_action(
        operation="loop_list",
        action=lambda conn, settings: read_service.list_loops_page(
            status=status,
            limit=min(limit, 100),  # Cap at 100
            cursor=cursor,
            conn=conn,
        ),
    )

    return {"action": "loop_list", **result}


def execute_loop_search(**kwargs: Any) -> Dict[str, Any]:
    """Search loops using DSL query."""
    query = kwargs.get("query", "")
    limit = kwargs.get("limit", 50)
    cursor = kwargs.get("cursor")

    result = _execute_loop_action(
        operation="loop_search",
        action=lambda conn, settings: read_service.search_loops_by_query_page(
            query=query,
            limit=min(limit, 100),
            cursor=cursor,
            conn=conn,
        ),
    )

    return {"action": "loop_search", **result}


def execute_loop_next(**kwargs: Any) -> Dict[str, Any]:
    """Get prioritized next action loops."""
    limit = kwargs.get("limit", 5)

    result = _execute_loop_action(
        operation="loop_next",
        action=lambda conn, settings: read_service.next_loops(
            limit=min(limit, 20),  # Cap at 20
            conn=conn,
            settings=settings,
        ),
    )

    # Result is already a dict with bucket names
    return {"action": "loop_next", **result}


def execute_loop_transition(**kwargs: Any) -> Dict[str, Any]:
    """Transition loop to a non-terminal status."""
    from .loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_transition")
    note = kwargs.get("note")
    status = _parse_loop_status(kwargs.get("status"), required_for="loop_transition")

    if is_terminal_status(status):
        raise ValidationError("status", "use loop_close for terminal statuses")

    result = _execute_loop_action(
        operation="loop_transition",
        loop_id=loop_id,
        action=lambda conn, settings: loop_service.transition_status(
            loop_id=loop_id,
            to_status=status,
            note=note,
            conn=conn,
        ),
    )

    return {"action": "loop_transition", "loop": result}


def execute_loop_snooze(**kwargs: Any) -> Dict[str, Any]:
    """Snooze a loop until a future time."""
    from .loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_snooze")

    snooze_until = kwargs.get("snooze_until_utc")
    if not snooze_until:
        raise ValidationError("snooze_until_utc", "required for loop_snooze")

    result = _execute_loop_action(
        operation="loop_snooze",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until},
            conn=conn,
        ),
    )

    return {"action": "loop_snooze", "loop": result}


def execute_loop_enrich(**kwargs: Any) -> Dict[str, Any]:
    """Trigger AI enrichment for a loop."""
    from .loops.enrichment_orchestration import orchestrate_loop_enrichment

    loop_id = _require_loop_id(kwargs, operation="loop_enrich")

    result = _execute_loop_action(
        operation="loop_enrich",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: orchestrate_loop_enrichment(
            loop_id=loop_id,
            conn=conn,
            settings=settings,
        ).to_payload(),
    )

    return {
        "action": "loop_enrich",
        "loop": result["loop"],
        "suggestion_id": result["suggestion_id"],
        "applied_fields": result.get("applied_fields", []),
        "needs_clarification": result.get("needs_clarification", []),
    }


def execute_loop_get(**kwargs: Any) -> Dict[str, Any]:
    """Get a single loop by ID."""
    loop_id = _require_loop_id(kwargs, operation="loop_get")
    result = _execute_loop_action(
        operation="loop_get",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: read_service.get_loop(loop_id=loop_id, conn=conn),
    )

    return {"action": "loop_get", "loop": result}


# ============================================================================
# Memory Tool Executors
# ============================================================================


def execute_memory_create(**kwargs: Any) -> Dict[str, Any]:
    """Create a new memory entry."""
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


def execute_memory_search(**kwargs: Any) -> Dict[str, Any]:
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


def execute_memory_update(**kwargs: Any) -> Dict[str, Any]:
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


def execute_memory_delete(**kwargs: Any) -> Dict[str, Any]:
    """Delete a memory entry."""
    entry_id = kwargs.get("entry_id")
    if entry_id is None:
        raise ValidationError("entry_id", "entry_id is required")

    return {
        "action": "memory_delete",
        **memory_management.delete_memory_entry(entry_id=int(entry_id), settings=get_settings()),
    }


# ============================================================================
# Tool Specifications
# ============================================================================


_RAW_TOOL_SPECS: List[Dict[str, Any]] = [
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


_EXECUTORS: Dict[str, ToolExecutor] = {
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

_TOOL_EXPOSURE_OVERRIDES: Dict[str, Dict[str, bool]] = {
    "loop_enrich": {"manual_exposed": True, "agent_exposed": False},
}


def _closed_object_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Close object schemas for stricter validation across providers."""
    normalized = dict(schema)
    schema_type = normalized.get("type")
    if schema_type == "object":
        properties = normalized.get("properties") or {}
        normalized["properties"] = {
            key: _closed_object_schema(value) if isinstance(value, dict) else value
            for key, value in properties.items()
        }
        normalized.setdefault("additionalProperties", False)
    elif schema_type == "array":
        items = normalized.get("items")
        if isinstance(items, dict):
            normalized["items"] = _closed_object_schema(items)
    return normalized


def _build_tool_registry() -> tuple[ToolDefinition, ...]:
    definitions: list[ToolDefinition] = []
    for spec in _RAW_TOOL_SPECS:
        function_spec = spec.get("function") or {}
        name = str(function_spec.get("name", ""))
        if not name:
            continue
        executor = _EXECUTORS.get(name)
        if executor is None:
            raise RuntimeError(f"Missing executor for tool {name}")
        overrides = _TOOL_EXPOSURE_OVERRIDES.get(name, {})
        definitions.append(
            ToolDefinition(
                name=name,
                description=str(function_spec.get("description", "")),
                input_schema=_closed_object_schema(
                    dict(function_spec.get("parameters") or {"type": "object", "properties": {}})
                ),
                executor=executor,
                manual_exposed=overrides.get("manual_exposed", True),
                agent_exposed=overrides.get("agent_exposed", True),
            )
        )
    return tuple(definitions)


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = _build_tool_registry()
TOOL_SPECS: List[Dict[str, Any]] = [tool.as_openai_tool_spec() for tool in TOOL_DEFINITIONS]
AGENT_TOOL_SPECS: List[Dict[str, Any]] = [
    tool.as_openai_tool_spec() for tool in TOOL_DEFINITIONS if tool.agent_exposed
]
MANUAL_TOOL_NAMES = frozenset(tool.name for tool in TOOL_DEFINITIONS if tool.manual_exposed)
EXECUTORS: Dict[str, ToolExecutor] = {tool.name: tool.executor for tool in TOOL_DEFINITIONS}


def get_tool_definition(name: str) -> ToolDefinition | None:
    for tool in TOOL_DEFINITIONS:
        if tool.name == name:
            return tool
    return None


def get_agent_bridge_tools() -> list[BridgeToolSpec]:
    return [tool.as_bridge_tool_spec() for tool in TOOL_DEFINITIONS if tool.agent_exposed]


def normalize_tool_arguments(raw: str | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("arguments", "invalid JSON") from exc
