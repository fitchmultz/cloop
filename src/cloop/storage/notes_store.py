"""Note storage.

Purpose:
    Own CRUD and search persistence for lightweight notes.

Responsibilities:
    - Create and update note rows
    - Read notes by ID
    - List and search notes with cursor pagination

Non-scope:
    - Tool execution or HTTP transport concerns
    - General database connection management

Invariants/Assumptions:
    - Notes paginate by `(updated_at DESC, id DESC)`.
    - Cursor encoding reuses the loop pagination helpers.
"""

from __future__ import annotations

from typing import Any

from .. import db
from ..loops.pagination import LoopCursor, encode_cursor, prepare_cursor_state
from ..settings import Settings, get_settings


def upsert_note(
    *,
    title: str,
    body: str,
    note_id: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Insert or update a note row."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        if note_id is None:
            cursor = conn.execute(
                "INSERT INTO notes (title, body) VALUES (?, ?)",
                (title, body),
            )
            conn.commit()
            note_id = cursor.lastrowid
        else:
            conn.execute(
                """
                UPDATE notes
                SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, body, note_id),
            )
            conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else {}


def read_note(note_id: int, settings: Settings | None = None) -> dict[str, Any] | None:
    """Read a note by ID."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


def list_notes(
    *,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List notes with cursor pagination."""
    settings = settings or get_settings()
    limit = min(limit, 100)

    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "note.list"},
        cursor=cursor,
    )

    with db.core_connection(settings) as conn:
        if state.cursor_anchor:
            anchor_updated_at, _, anchor_id = state.cursor_anchor
            rows = conn.execute(
                """
                SELECT id, title, body, created_at, updated_at
                FROM notes
                WHERE (updated_at < ?) OR (updated_at = ? AND id < ?)
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (anchor_updated_at, anchor_updated_at, anchor_id, limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, title, body, created_at, updated_at
                FROM notes
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit + 1,),
            ).fetchall()

    items = [dict(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and items:
        last = items[-1]
        cursor_obj = LoopCursor(
            snapshot_utc=state.snapshot_utc,
            updated_at_utc=last["updated_at"],
            captured_at_utc=last["updated_at"],
            loop_id=last["id"],
            fingerprint=state.fingerprint,
        )
        next_cursor = encode_cursor(cursor_obj)

    return {"items": items, "next_cursor": next_cursor, "limit": limit}


def search_notes(
    *,
    query: str,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Search notes by title/body text with cursor pagination."""
    settings = settings or get_settings()
    limit = min(limit, 100)

    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "note.search", "query": query},
        cursor=cursor,
    )
    search_pattern = f"%{query}%"

    with db.core_connection(settings) as conn:
        if state.cursor_anchor:
            anchor_updated_at, _, anchor_id = state.cursor_anchor
            rows = conn.execute(
                """
                SELECT id, title, body, created_at, updated_at
                FROM notes
                WHERE (title LIKE ? OR body LIKE ?)
                  AND ((updated_at < ?) OR (updated_at = ? AND id < ?))
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (
                    search_pattern,
                    search_pattern,
                    anchor_updated_at,
                    anchor_updated_at,
                    anchor_id,
                    limit + 1,
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, title, body, created_at, updated_at
                FROM notes
                WHERE title LIKE ? OR body LIKE ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (search_pattern, search_pattern, limit + 1),
            ).fetchall()

    items = [dict(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and items:
        last = items[-1]
        cursor_obj = LoopCursor(
            snapshot_utc=state.snapshot_utc,
            updated_at_utc=last["updated_at"],
            captured_at_utc=last["updated_at"],
            loop_id=last["id"],
            fingerprint=state.fingerprint,
        )
        next_cursor = encode_cursor(cursor_obj)

    return {"items": items, "next_cursor": next_cursor, "limit": limit, "query": query}
