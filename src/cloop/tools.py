"""Tool executors for LLM function calling.

Purpose:
    Implement tool handlers callable by LLM during chat completions.

Responsibilities:
    - Execute write_note, read_note operations
    - Validate required fields before execution
    - Return structured results for LLM context

Non-scope:
    - Tool registration with litellm (see llm.py)
    - HTTP API endpoints (see routes/)

Entrypoints:
    - execute_write_note(**kwargs) -> Dict[str, Any]
    - execute_read_note(**kwargs) -> Dict[str, Any]
    - EXECUTORS: Dict[str, ToolExecutor]
    - TOOL_SPECS: List[Dict] for litellm tool definitions
"""

import json
from typing import Any, Dict, List, Protocol

from . import db
from .constants import NOTE_BODY_MAX, TITLE_MAX
from .loops.errors import NoteNotFoundError, ValidationError


class ToolExecutor(Protocol):
    def __call__(self, **kwargs: Any) -> Dict[str, Any]: ...


def _require_fields(payload: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if payload.get(field) is None]
    if missing:
        raise ValidationError("fields", f"missing required: {', '.join(missing)}")


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


TOOL_SPECS: List[Dict[str, Any]] = [
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
]


EXECUTORS: Dict[str, ToolExecutor] = {
    "write_note": execute_write_note,
    "read_note": execute_read_note,
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
