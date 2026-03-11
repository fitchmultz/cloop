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
    - Search ordering prefers higher priority, then recency.
"""

from __future__ import annotations

import json
from typing import Any

from .. import db
from ..loops.pagination import LoopCursor, encode_cursor, prepare_cursor_state
from ..settings import Settings, get_settings


def _row_to_memory_dict(row) -> dict[str, Any]:
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


def create_memory_entry(
    *,
    key: str | None,
    content: str,
    category: str = "fact",
    priority: int = 0,
    source: str = "user_stated",
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create a new memory entry."""
    settings = settings or get_settings()
    metadata_json = json.dumps(metadata or {})
    with db.core_connection(settings) as conn:
        cursor = conn.execute(
            """
            INSERT INTO memory_entries (key, content, category, priority, source, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, content, category, priority, source, metadata_json),
        )
        conn.commit()
        entry_id = cursor.lastrowid
        row = conn.execute(
            """
            SELECT id, key, content, category, priority, source, metadata_json, created_at,
                   updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
    return _row_to_memory_dict(row)


def get_memory_entry(entry_id: int, settings: Settings | None = None) -> dict[str, Any] | None:
    """Get a memory entry by ID."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        row = conn.execute(
            """
            SELECT id, key, content, category, priority, source, metadata_json, created_at,
                   updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
    return _row_to_memory_dict(row) if row else None


def update_memory_entry(
    entry_id: int,
    *,
    key: str | None = None,
    content: str | None = None,
    category: str | None = None,
    priority: int | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Update a memory entry."""
    settings = settings or get_settings()
    updates: list[str] = []
    params: list[Any] = []

    if key is not None:
        updates.append("key = ?")
        params.append(key)
    if content is not None:
        updates.append("content = ?")
        params.append(content)
    if category is not None:
        updates.append("category = ?")
        params.append(category)
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if source is not None:
        updates.append("source = ?")
        params.append(source)
    if metadata is not None:
        updates.append("metadata_json = ?")
        params.append(json.dumps(metadata))

    if not updates:
        return get_memory_entry(entry_id, settings)

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(entry_id)

    with db.core_connection(settings) as conn:
        conn.execute(
            f"UPDATE memory_entries SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    return get_memory_entry(entry_id, settings)


def delete_memory_entry(entry_id: int, settings: Settings | None = None) -> bool:
    """Delete a memory entry."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        cursor = conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_memory_entries(
    *,
    category: str | None = None,
    source: str | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List memory entries with filters and cursor pagination."""
    settings = settings or get_settings()
    limit = min(limit, 100)
    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "memory.list", "category": category, "source": source},
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

    with db.core_connection(settings) as conn:
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
        rows = conn.execute(query, params).fetchall()

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


def search_memory_entries(
    *,
    query: str,
    category: str | None = None,
    source: str | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Search memory entries by text."""
    settings = settings or get_settings()
    limit = min(limit, 100)
    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "memory.search", "query": query, "category": category},
        cursor=cursor,
    )
    search_pattern = f"%{query}%"
    conditions = ["(key LIKE ? OR content LIKE ?)"]
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

    with db.core_connection(settings) as conn:
        if state.cursor_anchor:
            anchor_updated_at, _, anchor_id = state.cursor_anchor
            query_sql = f"""
                SELECT id, key, content, category, priority, source, metadata_json, created_at,
                       updated_at
                FROM memory_entries
                WHERE {" AND ".join(conditions)}
                  AND ((updated_at < ?) OR (updated_at = ? AND id < ?))
                ORDER BY priority DESC, updated_at DESC, id DESC
                LIMIT ?
            """
            params.extend([anchor_updated_at, anchor_updated_at, anchor_id, limit + 1])
        else:
            query_sql = f"""
                SELECT id, key, content, category, priority, source, metadata_json, created_at,
                       updated_at
                FROM memory_entries
                WHERE {" AND ".join(conditions)}
                ORDER BY priority DESC, updated_at DESC, id DESC
                LIMIT ?
            """
            params.append(limit + 1)
        rows = conn.execute(query_sql, params).fetchall()

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
