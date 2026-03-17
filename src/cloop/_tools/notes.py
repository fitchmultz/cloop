"""Note tool executors and definitions.

Purpose:
    Implement the note-management tools exposed through `cloop.tools`.

Responsibilities:
    - Execute note create/update, read, list, and search operations
    - Validate note payloads before persistence
    - Publish transport-neutral tool definitions for note operations

Scope:
    - Note tool execution and registration only

Non-scope:
    - Note storage implementation details
    - Non-tool note transport surfaces

Usage:
    - Imported by the internal tool registry and re-exported by `cloop.tools`

Invariants/Assumptions:
    - Title/body size limits follow the shared constants module
    - Results are shaped as tool-friendly dictionaries
    - Note persistence is delegated to `storage.notes_store`
"""

from __future__ import annotations

from typing import Any

from ..constants import NOTE_BODY_MAX, TITLE_MAX
from ..loops.errors import NoteNotFoundError, ValidationError
from ..storage import notes_store
from .models import ToolDefinition
from .validation import _require_fields


def execute_write_note(**kwargs: Any) -> dict[str, Any]:
    """Create or update a note."""
    payload = {"title": kwargs.get("title"), "body": kwargs.get("body")}
    _require_fields(payload, "title", "body")

    title = str(payload["title"])
    body = str(payload["body"])
    if len(title) > TITLE_MAX:
        raise ValidationError("title", f"exceeds maximum length of {TITLE_MAX} characters")
    if len(body) > NOTE_BODY_MAX:
        raise ValidationError(
            "body",
            f"exceeds maximum length of {NOTE_BODY_MAX} characters",
        )

    note = notes_store.upsert_note(
        title=title,
        body=body,
        note_id=kwargs.get("note_id"),
    )
    return {"action": "write_note", "note": note}


def execute_read_note(**kwargs: Any) -> dict[str, Any]:
    """Read a note by id."""
    note_id = kwargs.get("note_id")
    if note_id is None:
        raise ValidationError("note_id", "required for read_note")
    note = notes_store.read_note(int(note_id))
    if note is None:
        raise NoteNotFoundError(note_id=int(note_id))
    return {"action": "read_note", "note": note}


def execute_list_notes(**kwargs: Any) -> dict[str, Any]:
    """List notes with cursor-based pagination."""
    result = notes_store.list_notes(
        limit=min(kwargs.get("limit", 50), 100),
        cursor=kwargs.get("cursor"),
    )
    return {"action": "list_notes", **result}


def execute_search_notes(**kwargs: Any) -> dict[str, Any]:
    """Search notes by text query."""
    query = kwargs.get("query", "")
    if not query:
        raise ValidationError("query", "required for search_notes")

    result = notes_store.search_notes(
        query=query,
        limit=min(kwargs.get("limit", 50), 100),
        cursor=kwargs.get("cursor"),
    )
    return {"action": "search_notes", **result}


NOTE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="write_note",
        description="Create or update a note with the supplied title and body.",
        input_schema={
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
        executor=execute_write_note,
    ),
    ToolDefinition(
        name="read_note",
        description="Fetch a previously stored note by id.",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "integer",
                    "description": "Identifier of the note to retrieve.",
                }
            },
            "required": ["note_id"],
        },
        executor=execute_read_note,
    ),
    ToolDefinition(
        name="list_notes",
        description="List stored notes with pagination. Use to browse available notes.",
        input_schema={
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
        executor=execute_list_notes,
    ),
    ToolDefinition(
        name="search_notes",
        description="Search notes by text query. Matches title and body.",
        input_schema={
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
        executor=execute_search_notes,
    ),
)
