"""Memory entry storage.

Purpose:
    Own persistence for durable assistant memory entries.

Responsibilities:
    - CRUD for `memory_entries`
    - Filtered list/search with cursor pagination
    - JSON metadata serialization/deserialization

Non-scope:
    - HTTP response models or transport error handling
    - Memory extraction/inference logic

Invariants/Assumptions:
    - Cursor ordering uses `(updated_at DESC, id DESC)` for deterministic scans.
    - Search ordering matches the cursor contract by using recency-first ordering.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .. import db, typingx
from ..loops.pagination import LoopCursor, encode_cursor, prepare_cursor_state
from ..settings import Settings, get_settings


@contextmanager
def _memory_connection(
    *,
    settings: Settings,
    conn: sqlite3.Connection | None,
) -> Iterator[tuple[sqlite3.Connection, bool]]:
    """Yield a usable connection plus whether this helper owns commit lifecycle."""
    if conn is not None:
        yield conn, False
        return

    with db.core_connection(settings) as opened:
        yield opened, True


def _row_to_memory_dict(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    metadata_json = row["metadata_json"]
    metadata = json.loads(metadata_json) if metadata_json else {}
    return {
        "id": row["id"],
        "key": row["key"],
        "content": row["content"],
        "category": row["category"],
        "priority": row["priority"],
        "source": row["source"],
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@typingx.validate_io()
def create_memory_entry(
    *,
    key: str | None,
    content: str,
    category: str = "fact",
    priority: int = 0,
    source: str = "user_stated",
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Create a new memory entry."""
    settings = settings or get_settings()
    metadata_json = json.dumps(metadata or {})
    with _memory_connection(settings=settings, conn=conn) as (active_conn, owns_commit):
        cursor = active_conn.execute(
            """
            INSERT INTO memory_entries (key, content, category, priority, source, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, content, category, priority, source, metadata_json),
        )
        if owns_commit:
            active_conn.commit()
        entry_id = cursor.lastrowid
        row = active_conn.execute(
            """
            SELECT id, key, content, category, priority, source, metadata_json, created_at,
                   updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
    return _row_to_memory_dict(row)


@typingx.validate_io()
def get_memory_entry(
    entry_id: int,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Get a memory entry by ID."""
    settings = settings or get_settings()
    with _memory_connection(settings=settings, conn=conn) as (active_conn, _owns_commit):
        row = active_conn.execute(
            """
            SELECT id, key, content, category, priority, source, metadata_json, created_at,
                   updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
    return _row_to_memory_dict(row) if row else None


@typingx.validate_io()
def update_memory_entry(
    entry_id: int,
    *,
    fields: Mapping[str, Any],
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Update a memory entry using explicit field presence semantics."""
    settings = settings or get_settings()
    if not fields:
        return get_memory_entry(entry_id, settings=settings, conn=conn)

    updates: list[str] = []
    params: list[Any] = []

    for field_name, field_value in fields.items():
        if field_name == "key":
            updates.append("key = ?")
            params.append(field_value)
        elif field_name == "content":
            updates.append("content = ?")
            params.append(field_value)
        elif field_name == "category":
            updates.append("category = ?")
            params.append(field_value)
        elif field_name == "priority":
            updates.append("priority = ?")
            params.append(field_value)
        elif field_name == "source":
            updates.append("source = ?")
            params.append(field_value)
        elif field_name == "metadata":
            updates.append("metadata_json = ?")
            params.append(json.dumps(field_value))

    if not updates:
        return get_memory_entry(entry_id, settings=settings, conn=conn)

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(entry_id)

    with _memory_connection(settings=settings, conn=conn) as (active_conn, owns_commit):
        cursor = active_conn.execute(
            f"UPDATE memory_entries SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        if cursor.rowcount == 0:
            return None
        if owns_commit:
            active_conn.commit()
    return get_memory_entry(entry_id, settings=settings, conn=conn)


@typingx.validate_io()
def delete_memory_entry(
    entry_id: int,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Delete a memory entry."""
    settings = settings or get_settings()
    with _memory_connection(settings=settings, conn=conn) as (active_conn, owns_commit):
        cursor = active_conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
        if owns_commit:
            active_conn.commit()
        return cursor.rowcount > 0


@typingx.validate_io()
def list_memory_entries(
    *,
    category: str | None = None,
    source: str | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """List memory entries with filters and cursor pagination."""
    settings = settings or get_settings()
    limit = min(limit, 100)
    state = prepare_cursor_state(
        fingerprint_payload_dict={
            "tool": "memory.list",
            "category": category,
            "source": source,
            "min_priority": min_priority,
        },
        cursor=cursor,
    )

    conditions: list[str] = []
    params: list[Any] = []
    if category:
        conditions.append("category = ?")
        params.append(category)
    if source:
        conditions.append("source = ?")
        params.append(source)
    if min_priority is not None:
        conditions.append("priority >= ?")
        params.append(min_priority)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _memory_connection(settings=settings, conn=conn) as (active_conn, _owns_commit):
        if state.cursor_anchor:
            anchor_updated_at, _, anchor_id = state.cursor_anchor
            query = f"""
                SELECT id, key, content, category, priority, source, metadata_json, created_at,
                       updated_at
                FROM memory_entries
                {where_clause}
                {"AND" if conditions else "WHERE"} ((updated_at < ?) OR (updated_at = ? AND id < ?))
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
            """
            params.extend([anchor_updated_at, anchor_updated_at, anchor_id, limit + 1])
        else:
            query = f"""
                SELECT id, key, content, category, priority, source, metadata_json, created_at,
                       updated_at
                FROM memory_entries
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
            """
            params.append(limit + 1)
        rows = active_conn.execute(query, params).fetchall()

    items = [_row_to_memory_dict(row) for row in rows[:limit]]
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


@typingx.validate_io()
def search_memory_entries(
    *,
    query: str,
    category: str | None = None,
    source: str | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Search memory entries by text."""
    settings = settings or get_settings()
    limit = min(limit, 100)
    state = prepare_cursor_state(
        fingerprint_payload_dict={
            "tool": "memory.search",
            "query": query,
            "category": category,
            "source": source,
            "min_priority": min_priority,
        },
        cursor=cursor,
    )
    search_pattern = f"%{typingx.escape_like_pattern(query)}%"
    conditions = ["(key LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"]
    params: list[Any] = [search_pattern, search_pattern]
    if category:
        conditions.append("category = ?")
        params.append(category)
    if source:
        conditions.append("source = ?")
        params.append(source)
    if min_priority is not None:
        conditions.append("priority >= ?")
        params.append(min_priority)

    with _memory_connection(settings=settings, conn=conn) as (active_conn, _owns_commit):
        if state.cursor_anchor:
            anchor_updated_at, _, anchor_id = state.cursor_anchor
            query_sql = f"""
                SELECT id, key, content, category, priority, source, metadata_json, created_at,
                       updated_at
                FROM memory_entries
                WHERE {" AND ".join(conditions)}
                  AND ((updated_at < ?) OR (updated_at = ? AND id < ?))
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
            """
            params.extend([anchor_updated_at, anchor_updated_at, anchor_id, limit + 1])
        else:
            query_sql = f"""
                SELECT id, key, content, category, priority, source, metadata_json, created_at,
                       updated_at
                FROM memory_entries
                WHERE {" AND ".join(conditions)}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
            """
            params.append(limit + 1)
        rows = active_conn.execute(query_sql, params).fetchall()

    items = [_row_to_memory_dict(row) for row in rows[:limit]]
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
