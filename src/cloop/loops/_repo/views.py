"""Saved-view and query-driven loop repository operations.

Purpose:
    Own DSL-query backed reads, cursor pagination, and saved loop-view persistence.

Responsibilities:
    - Execute DSL-backed loop searches
    - Apply cursor-pagination anchors for stable reads
    - Create, update, list, and delete saved loop views

Non-scope:
    - Core loop mutation paths
    - Claims, templates, or review-session persistence
    - Query parsing semantics beyond repository execution
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..errors import ValidationError
from ..models import LoopRecord, LoopStatus, utc_now
from ..query import LoopQuery, compile_loop_query, parse_loop_query
from .shared import _row_to_record


def search_loops_by_query(
    *,
    query: str,
    limit: int | None,
    offset: int = 0,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """Search loops using the DSL query language.

    This is the canonical query path used by API, CLI, MCP, and UI.

    Args:
        query: DSL query string (e.g., 'status:inbox tag:work due:today')
        limit: Maximum number of results, or None for all matches
        offset: Pagination offset
        conn: Database connection

    Returns:
        List of matching LoopRecords, ordered by updated_at DESC, captured_at_utc DESC, id DESC

    Raises:
        ValidationError: If query syntax is invalid
    """
    parsed: LoopQuery = parse_loop_query(query)
    now = utc_now()
    where_sql, params = compile_loop_query(parsed, now_utc=now)

    sql = f"""
        SELECT DISTINCT loops.*
        FROM loops
        LEFT JOIN projects ON projects.id = loops.project_id
        LEFT JOIN loop_tags ON loop_tags.loop_id = loops.id
        LEFT JOIN tags ON tags.id = loop_tags.tag_id
        {where_sql}
        ORDER BY loops.updated_at DESC, loops.captured_at_utc DESC, loops.id DESC
    """

    if limit is not None:
        sql += "\n        LIMIT ? OFFSET ?"
        params = [*params, limit, offset]

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def create_loop_view(
    *,
    name: str,
    query: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a new saved view.

    Args:
        name: Unique view name
        query: DSL query string
        description: Optional description
        conn: Database connection

    Returns:
        Created view record as dict

    Raises:
        ValidationError: If name already exists
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationError("name", "view name cannot be empty")

    parse_loop_query(query)

    try:
        cursor = conn.execute(
            """
            INSERT INTO loop_views (name, query, description)
            VALUES (?, ?, ?)
            """,
            (normalized_name, query, description),
        )
        view_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("name", f"view '{normalized_name}' already exists") from None

    row = conn.execute("SELECT * FROM loop_views WHERE id = ?", (view_id,)).fetchone()
    return dict(row)


def list_loop_views(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all saved views.

    Args:
        conn: Database connection

    Returns:
        List of view records as dicts, ordered by name
    """
    rows = conn.execute("SELECT * FROM loop_views ORDER BY name ASC").fetchall()
    return [dict(row) for row in rows]


def get_loop_view(*, view_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get a saved view by ID.

    Args:
        view_id: View ID
        conn: Database connection

    Returns:
        View record as dict, or None if not found
    """
    row = conn.execute("SELECT * FROM loop_views WHERE id = ?", (view_id,)).fetchone()
    return dict(row) if row else None


def get_loop_view_by_name(*, name: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get a saved view by name.

    Args:
        name: View name
        conn: Database connection

    Returns:
        View record as dict, or None if not found
    """
    row = conn.execute("SELECT * FROM loop_views WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def update_loop_view(
    *,
    view_id: int,
    name: str | None = None,
    query: str | None = None,
    description: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a saved view.

    Args:
        view_id: View ID
        name: New name (optional)
        query: New query string (optional)
        description: New description (optional)
        conn: Database connection

    Returns:
        Updated view record as dict

    Raises:
        ValidationError: If view not found or name conflict
    """
    existing = get_loop_view(view_id=view_id, conn=conn)
    if not existing:
        raise ValidationError("view_id", f"view {view_id} not found")

    updates: dict[str, Any] = {}
    if name is not None:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("name", "view name cannot be empty")
        updates["name"] = normalized
    if query is not None:
        parse_loop_query(query)
        updates["query"] = query
    if description is not None:
        updates["description"] = description

    if not updates:
        return existing

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [view_id]

    try:
        conn.execute(
            f"""
            UPDATE loop_views
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            params,
        )
    except sqlite3.IntegrityError:
        raise ValidationError("name", f"view '{updates.get('name', '')}' already exists") from None

    row = conn.execute("SELECT * FROM loop_views WHERE id = ?", (view_id,)).fetchone()
    return dict(row)


def delete_loop_view(*, view_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a saved view.

    Args:
        view_id: View ID
        conn: Database connection

    Returns:
        True if deleted, False if not found
    """
    cursor = conn.execute("DELETE FROM loop_views WHERE id = ?", (view_id,))
    return cursor.rowcount > 0


def _cursor_where_clause(prefix: str = "") -> str:
    p = f"{prefix}." if prefix else ""
    return (
        f"(datetime({p}updated_at) < datetime(?) OR "
        f"(datetime({p}updated_at) = datetime(?) "
        f"AND datetime({p}captured_at_utc) < datetime(?)) OR "
        f"(datetime({p}updated_at) = datetime(?) "
        f"AND datetime({p}captured_at_utc) = datetime(?) "
        f"AND {p}id < ?))"
    )


def list_loops_cursor(
    *,
    status: LoopStatus | None,
    limit: int,
    snapshot_utc: str,
    cursor_anchor: tuple[str, str, int] | None,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """List loops using cursor-based keyset pagination.

    Args:
        status: Optional status filter
        limit: Maximum number of results (fetches limit+1 to detect has_more)
        snapshot_utc: Upper bound for updated_at to ensure stable paging
        cursor_anchor: Optional (updated_at, captured_at_utc, id) tuple for continuation
        conn: Database connection

    Returns:
        List of LoopRecords ordered by updated_at DESC, captured_at_utc DESC, id DESC
    """
    sql = "SELECT * FROM loops WHERE datetime(updated_at) <= datetime(?)"
    params: list[Any] = [snapshot_utc]

    if status is not None:
        sql += " AND status = ?"
        params.append(status.value)

    if cursor_anchor is not None:
        updated_at, captured_at_utc, loop_id = cursor_anchor
        sql += " AND " + _cursor_where_clause()
        params.extend(
            [updated_at, updated_at, captured_at_utc, updated_at, captured_at_utc, loop_id]
        )

    sql += " ORDER BY datetime(updated_at) DESC, datetime(captured_at_utc) DESC, id DESC LIMIT ?"
    params.append(limit + 1)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def search_loops_by_query_cursor(
    *,
    query: str,
    limit: int,
    snapshot_utc: str,
    cursor_anchor: tuple[str, str, int] | None,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """Search loops using DSL query with cursor-based keyset pagination.

    Args:
        query: DSL query string
        limit: Maximum number of results (fetches limit+1 to detect has_more)
        snapshot_utc: Upper bound for updated_at to ensure stable paging
        cursor_anchor: Optional (updated_at, captured_at_utc, id) tuple for continuation
        conn: Database connection

    Returns:
        List of LoopRecords ordered by updated_at DESC, captured_at_utc DESC, id DESC

    Raises:
        ValidationError: If query syntax is invalid
    """
    parsed: LoopQuery = parse_loop_query(query)
    now = utc_now()
    where_sql, params = compile_loop_query(parsed, now_utc=now)

    sql = """
        SELECT DISTINCT loops.*
        FROM loops
        LEFT JOIN projects ON projects.id = loops.project_id
        LEFT JOIN loop_tags ON loop_tags.loop_id = loops.id
        LEFT JOIN tags ON tags.id = loop_tags.tag_id
    """
    where_clauses: list[str] = []
    if where_sql:
        normalized_where = where_sql.removeprefix("WHERE ").strip()
        if normalized_where:
            where_clauses.append(normalized_where)

    where_clauses.append("datetime(loops.updated_at) <= datetime(?)")
    params.append(snapshot_utc)

    if cursor_anchor is not None:
        updated_at, captured_at_utc, loop_id = cursor_anchor
        where_clauses.append(_cursor_where_clause("loops"))
        params.extend(
            [updated_at, updated_at, captured_at_utc, updated_at, captured_at_utc, loop_id]
        )

    if where_clauses:
        sql += " WHERE " + " AND ".join(f"({clause})" for clause in where_clauses)

    sql += (
        " ORDER BY datetime(loops.updated_at) DESC, "
        "datetime(loops.captured_at_utc) DESC, loops.id DESC LIMIT ?"
    )
    params.append(limit + 1)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]
