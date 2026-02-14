from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime
from typing import Any, Mapping

from ..typingx import escape_like_pattern
from .errors import LoopNotFoundError, ValidationError
from .models import (
    EnrichmentState,
    LoopClaim,
    LoopClaimSummary,
    LoopRecord,
    LoopStatus,
    format_utc_datetime,
    parse_utc_datetime,
    utc_now,
)
from .query import LoopQuery, compile_loop_query, parse_loop_query

logger = logging.getLogger(__name__)


_ALLOWED_UPDATE_FIELDS = {
    "raw_text",
    "title",
    "status",
    "captured_at_utc",
    "captured_tz_offset_min",
    "closed_at",
    "summary",
    "definition_of_done",
    "next_action",
    "due_at_utc",
    "snooze_until_utc",
    "time_minutes",
    "activation_energy",
    "urgency",
    "importance",
    "project_id",
    "blocked_reason",
    "completion_note",
    "user_locks_json",
    "provenance_json",
    "enrichment_state",
}


def _parse_json_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON list: {e}. Raw value: {repr(value)[:200]}") from e
    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected JSON list, got {type(parsed).__name__}. Raw value: {repr(value)[:200]}"
        )
    return [str(item) for item in parsed]


def _parse_json_dict(value: Any) -> dict[str, object]:
    if value is None or value == "":
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON dict: {e}. Raw value: {repr(value)[:200]}") from e
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Expected JSON dict, got {type(parsed).__name__}. Raw value: {repr(value)[:200]}"
        )
    return parsed


def _row_to_record(row: sqlite3.Row) -> LoopRecord:
    return LoopRecord(
        id=row["id"],
        raw_text=row["raw_text"],
        title=row["title"] if row["title"] is not None else None,
        summary=row["summary"] if row["summary"] is not None else None,
        definition_of_done=(
            row["definition_of_done"] if row["definition_of_done"] is not None else None
        ),
        next_action=row["next_action"] if row["next_action"] is not None else None,
        status=LoopStatus(row["status"]),
        captured_at_utc=parse_utc_datetime(row["captured_at_utc"]),
        captured_tz_offset_min=row["captured_tz_offset_min"],
        due_at_utc=parse_utc_datetime(row["due_at_utc"]) if row["due_at_utc"] else None,
        snooze_until_utc=(
            parse_utc_datetime(row["snooze_until_utc"]) if row["snooze_until_utc"] else None
        ),
        time_minutes=row["time_minutes"] if row["time_minutes"] is not None else None,
        activation_energy=(
            row["activation_energy"] if row["activation_energy"] is not None else None
        ),
        urgency=row["urgency"] if row["urgency"] is not None else None,
        importance=row["importance"] if row["importance"] is not None else None,
        project_id=row["project_id"] if row["project_id"] is not None else None,
        blocked_reason=row["blocked_reason"] if row["blocked_reason"] is not None else None,
        completion_note=row["completion_note"] if row["completion_note"] is not None else None,
        user_locks=_parse_json_list(row["user_locks_json"]),
        provenance=_parse_json_dict(row["provenance_json"]),
        enrichment_state=EnrichmentState(row["enrichment_state"] or EnrichmentState.IDLE.value),
        created_at_utc=parse_utc_datetime(row["created_at"]),
        updated_at_utc=parse_utc_datetime(row["updated_at"]),
        closed_at_utc=parse_utc_datetime(row["closed_at"]) if row["closed_at"] else None,
    )


def create_loop(
    *,
    raw_text: str,
    captured_at_utc: str,
    captured_tz_offset_min: int,
    status: LoopStatus,
    conn: sqlite3.Connection,
) -> LoopRecord:
    cursor = conn.execute(
        """
        INSERT INTO loops (
            raw_text,
            title,
            status,
            captured_at_utc,
            captured_tz_offset_min
        )
        VALUES (?, NULL, ?, ?, ?)
        """,
        (raw_text, status.value, captured_at_utc, captured_tz_offset_min),
    )
    row = conn.execute("SELECT * FROM loops WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise RuntimeError("loop_create_failed")
    return _row_to_record(row)


def read_loop(*, loop_id: int, conn: sqlite3.Connection) -> LoopRecord | None:
    row = conn.execute("SELECT * FROM loops WHERE id = ?", (loop_id,)).fetchone()
    return _row_to_record(row) if row else None


def list_loops(
    *,
    status: LoopStatus | None,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    sql = "SELECT * FROM loops"
    params: list[Any] = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status.value)
    sql += " ORDER BY updated_at DESC, captured_at_utc DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def list_loops_by_statuses(
    *,
    statuses: list[LoopStatus],
    limit: int | None = None,
    offset: int | None = None,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    if not statuses:
        return []
    placeholders = ", ".join("?" for _ in statuses)
    sql = f"SELECT * FROM loops WHERE status IN ({placeholders})"
    params: list[Any] = [status.value for status in statuses]
    sql += " ORDER BY updated_at DESC, captured_at_utc DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
        if offset is not None:
            sql += " OFFSET ?"
            params.append(offset)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def list_all_loops(*, conn: sqlite3.Connection) -> list[LoopRecord]:
    rows = conn.execute(
        "SELECT * FROM loops ORDER BY updated_at DESC, captured_at_utc DESC, id DESC"
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def list_loops_by_tag(
    *,
    tag: str,
    statuses: list[LoopStatus] | None,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    sql = """
        SELECT loops.*
        FROM loops
        JOIN loop_tags ON loop_tags.loop_id = loops.id
        JOIN tags ON tags.id = loop_tags.tag_id
        WHERE LOWER(tags.name) = LOWER(?)
    """
    params: list[Any] = [tag]
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        sql += f" AND loops.status IN ({placeholders})"
        params.extend(status.value for status in statuses)
    sql += (
        " ORDER BY loops.updated_at DESC, loops.captured_at_utc DESC, loops.id DESC"
        " LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def insert_loop_from_export(
    *,
    payload: Mapping[str, Any],
    project_id: int | None,
    conn: sqlite3.Connection,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO loops (
            raw_text,
            title,
            summary,
            definition_of_done,
            next_action,
            status,
            captured_at_utc,
            captured_tz_offset_min,
            due_at_utc,
            snooze_until_utc,
            time_minutes,
            activation_energy,
            urgency,
            importance,
            project_id,
            blocked_reason,
            completion_note,
            user_locks_json,
            provenance_json,
            enrichment_state,
            created_at,
            updated_at,
            closed_at
        )
        VALUES (
            :raw_text,
            :title,
            :summary,
            :definition_of_done,
            :next_action,
            :status,
            :captured_at_utc,
            :captured_tz_offset_min,
            :due_at_utc,
            :snooze_until_utc,
            :time_minutes,
            :activation_energy,
            :urgency,
            :importance,
            :project_id,
            :blocked_reason,
            :completion_note,
            :user_locks_json,
            :provenance_json,
            :enrichment_state,
            :created_at,
            :updated_at,
            :closed_at
        )
        """,
        {**payload, "project_id": project_id},
    )
    if cursor.lastrowid is None:
        raise RuntimeError("loop_import_failed")
    return int(cursor.lastrowid)


def list_tags(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT LOWER(tags.name) AS name
        FROM tags
        JOIN loop_tags ON loop_tags.tag_id = tags.id
        ORDER BY name ASC
        """
    ).fetchall()
    return [row["name"] for row in rows]


def search_loops(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    escaped_query = escape_like_pattern(query)
    like_query = f"%{escaped_query}%"
    rows = conn.execute(
        """
        SELECT *
        FROM loops
        WHERE raw_text LIKE ? ESCAPE '\\'
           OR title LIKE ? ESCAPE '\\'
           OR summary LIKE ? ESCAPE '\\'
           OR next_action LIKE ? ESCAPE '\\'
        ORDER BY updated_at DESC, captured_at_utc DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (like_query, like_query, like_query, like_query, limit, offset),
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def update_loop_fields(
    *,
    loop_id: int,
    fields: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> LoopRecord:
    # Detect invalid fields BEFORE processing
    invalid_fields = set(fields.keys()) - _ALLOWED_UPDATE_FIELDS
    if invalid_fields:
        invalid_list = ", ".join(sorted(invalid_fields))
        raise ValidationError("fields", f"invalid fields: {invalid_list}")

    updates = dict(fields)
    if not updates:
        raise ValidationError("fields", "no valid fields to update")
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values())
    sql = f"""
        UPDATE loops
        SET {set_clause},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """
    params.append(loop_id)
    conn.execute(sql, params)
    row = conn.execute("SELECT * FROM loops WHERE id = ?", (loop_id,)).fetchone()
    if row is None:
        raise LoopNotFoundError(loop_id)
    return _row_to_record(row)


def insert_loop_event(
    *,
    loop_id: int,
    event_type: str,
    payload: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO loop_events (
            loop_id,
            event_type,
            payload_json
        )
        VALUES (?, ?, ?)
        """,
        (loop_id, event_type, json.dumps(dict(payload))),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("insert_loop_event_failed")
    return int(cursor.lastrowid)


def list_loop_events(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM loop_events WHERE loop_id = ? ORDER BY id ASC",
        (loop_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def insert_loop_suggestion(
    *,
    loop_id: int,
    suggestion_json: Mapping[str, Any],
    model: str,
    conn: sqlite3.Connection,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO loop_suggestions (
            loop_id,
            suggestion_json,
            model
        )
        VALUES (?, ?, ?)
        """,
        (loop_id, json.dumps(dict(suggestion_json)), model),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("loop_suggestion_insert_failed")
    return int(cursor.lastrowid)


def upsert_project(*, name: str, conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    if cursor.lastrowid is None:
        raise RuntimeError("project_insert_failed")
    return int(cursor.lastrowid)


def read_project_name(*, project_id: int | None, conn: sqlite3.Connection) -> str | None:
    if project_id is None:
        return None
    row = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row["name"] if row else None


def read_project_names_batch(*, project_ids: set[int], conn: sqlite3.Connection) -> dict[int, str]:
    """Fetch multiple project names in a single query.

    Returns a dict mapping project_id -> project_name.
    Project IDs that don't exist will be omitted from the result.
    """
    if not project_ids:
        return {}
    placeholders = ", ".join("?" for _ in project_ids)
    sql = f"SELECT id, name FROM projects WHERE id IN ({placeholders})"
    rows = conn.execute(sql, list(project_ids)).fetchall()
    return {int(row["id"]): row["name"] for row in rows}


def list_loop_tags_batch(*, loop_ids: list[int], conn: sqlite3.Connection) -> dict[int, list[str]]:
    """Fetch tags for multiple loops in a single query.

    Returns a dict mapping loop_id -> list of tag names.
    Loops with no tags will have an empty list.
    """
    if not loop_ids:
        return {}
    placeholders = ", ".join("?" for _ in loop_ids)
    sql = f"""
        SELECT loop_tags.loop_id, LOWER(tags.name) AS name
        FROM loop_tags
        JOIN tags ON tags.id = loop_tags.tag_id
        WHERE loop_tags.loop_id IN ({placeholders})
        ORDER BY loop_tags.loop_id, name ASC
    """
    rows = conn.execute(sql, loop_ids).fetchall()
    result: dict[int, list[str]] = {loop_id: [] for loop_id in loop_ids}
    for row in rows:
        loop_id = int(row["loop_id"])
        result.setdefault(loop_id, []).append(row["name"])
    return result


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM projects ORDER BY name ASC").fetchall()
    return [dict(row) for row in rows]


def upsert_tag(*, name: str, conn: sqlite3.Connection) -> int:
    normalized = name.strip().lower()
    if not normalized:
        raise ValidationError("tag_name", "tag name cannot be empty")
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (normalized,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute("INSERT INTO tags (name) VALUES (?)", (normalized,))
    if cursor.lastrowid is None:
        raise RuntimeError("tag_insert_failed")
    return int(cursor.lastrowid)


def list_loop_tags(*, loop_id: int, conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT LOWER(tags.name) AS name
        FROM loop_tags
        JOIN tags ON tags.id = loop_tags.tag_id
        WHERE loop_tags.loop_id = ?
        ORDER BY name ASC
        """,
        (loop_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def replace_loop_tags(*, loop_id: int, tag_names: list[str], conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM loop_tags WHERE loop_id = ?", (loop_id,))
    for name in tag_names:
        normalized = name.strip().lower()
        if not normalized:
            continue
        tag_id = upsert_tag(name=normalized, conn=conn)
        conn.execute(
            "INSERT OR IGNORE INTO loop_tags (loop_id, tag_id) VALUES (?, ?)",
            (loop_id, tag_id),
        )
    conn.execute(
        """
        DELETE FROM tags
        WHERE id NOT IN (SELECT DISTINCT tag_id FROM loop_tags)
        """
    )


def insert_loop_link(
    *,
    loop_id: int,
    related_loop_id: int,
    relationship_type: str,
    confidence: float | None,
    source: str,
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO loop_links (
            loop_id,
            related_loop_id,
            relationship_type,
            confidence,
            source
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (loop_id, related_loop_id, relationship_type, confidence, source),
    )


def fetch_loop_embeddings(
    *,
    conn: sqlite3.Connection,
    limit: int | None = None,
    exclude_loop_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch loop embeddings with optional pagination.

    Args:
        conn: Database connection
        limit: Maximum number of embeddings to fetch (None = no limit)
        exclude_loop_id: Optional loop ID to exclude from results

    Returns:
        List of embedding records as dictionaries
    """
    sql = """
        SELECT loop_id, embedding_blob, embedding_dim, embedding_norm, embed_model
        FROM loop_embeddings
    """
    params: list[Any] = []

    if exclude_loop_id is not None:
        sql += " WHERE loop_id != ?"
        params.append(exclude_loop_id)

    # Order by loop_id for deterministic results when using LIMIT
    sql += " ORDER BY loop_id"

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def upsert_loop_embedding(
    *,
    loop_id: int,
    embedding_blob: bytes,
    embedding_dim: int,
    embedding_norm: float,
    embed_model: str,
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        """
        INSERT INTO loop_embeddings (
            loop_id,
            embedding_blob,
            embedding_dim,
            embedding_norm,
            embed_model
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(loop_id) DO UPDATE SET
            embedding_blob = excluded.embedding_blob,
            embedding_dim = excluded.embedding_dim,
            embedding_norm = excluded.embedding_norm,
            embed_model = excluded.embed_model,
            created_at = CURRENT_TIMESTAMP
        """,
        (loop_id, embedding_blob, embedding_dim, embedding_norm, embed_model),
    )


def search_loops_by_query(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """Search loops using the DSL query language.

    This is the canonical query path used by API, CLI, MCP, and UI.

    Args:
        query: DSL query string (e.g., 'status:inbox tag:work due:today')
        limit: Maximum number of results
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
        LIMIT ? OFFSET ?
    """

    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
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
        conn.commit()
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
        conn.commit()
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
    conn.commit()
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


def read_loops_batch(*, loop_ids: list[int], conn: sqlite3.Connection) -> dict[int, LoopRecord]:
    """Fetch multiple loops by ID in a single query.

    Args:
        loop_ids: List of loop IDs to fetch
        conn: Database connection

    Returns:
        Dict mapping loop_id -> LoopRecord for found loops
    """
    if not loop_ids:
        return {}
    placeholders = ", ".join("?" for _ in loop_ids)
    sql = f"SELECT * FROM loops WHERE id IN ({placeholders})"
    rows = conn.execute(sql, loop_ids).fetchall()
    return {_row_to_record(row).id: _row_to_record(row) for row in rows}


# ============================================================================
# Loop Claim Repository Functions
# ============================================================================


def claim_loop(
    *,
    loop_id: int,
    owner: str,
    lease_until: datetime,
    conn: sqlite3.Connection,
    token_bytes: int = 32,
) -> LoopClaim:
    """Acquire a claim on a loop. Returns claim with token.

    Args:
        loop_id: Loop to claim
        owner: Identifier for the claiming agent/client
        lease_until: When the claim expires
        conn: Database connection
        token_bytes: Number of bytes for token generation (default 32)

    Returns:
        LoopClaim with claim_token for subsequent operations

    Raises:
        sqlite3.IntegrityError: If already claimed (loop_id is PK)
    """
    token = secrets.token_hex(token_bytes)  # token_hex(n) produces 2n hex characters
    leased_at = utc_now()
    conn.execute(
        """
        INSERT INTO loop_claims (loop_id, owner, claim_token, leased_at, lease_until)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            loop_id,
            owner,
            token,
            format_utc_datetime(leased_at),
            format_utc_datetime(lease_until),
        ),
    )
    conn.commit()
    return LoopClaim(
        loop_id=loop_id,
        owner=owner,
        claim_token=token,
        leased_at_utc=leased_at,
        lease_until_utc=lease_until,
    )


def read_claim(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> LoopClaim | None:
    """Read the current claim for a loop, if any.

    Args:
        loop_id: Loop to check
        conn: Database connection

    Returns:
        LoopClaim if exists, None otherwise
    """
    row = conn.execute(
        """
        SELECT loop_id, owner, claim_token, leased_at, lease_until
        FROM loop_claims
        WHERE loop_id = ?
        """,
        (loop_id,),
    ).fetchone()
    if row is None:
        return None
    return LoopClaim(
        loop_id=row["loop_id"],
        owner=row["owner"],
        claim_token=row["claim_token"],
        leased_at_utc=parse_utc_datetime(row["leased_at"]),
        lease_until_utc=parse_utc_datetime(row["lease_until"]),
    )


def renew_claim(
    *,
    loop_id: int,
    claim_token: str,
    new_lease_until: datetime,
    conn: sqlite3.Connection,
) -> LoopClaim | None:
    """Extend a claim's lease. Returns updated claim or None if token invalid.

    Args:
        loop_id: Loop with existing claim
        claim_token: Token from original claim
        new_lease_until: New expiry time
        conn: Database connection

    Returns:
        Updated LoopClaim if successful, None if token invalid or expired
    """
    now_str = format_utc_datetime(utc_now())
    cursor = conn.execute(
        """
        UPDATE loop_claims
        SET lease_until = ?
        WHERE loop_id = ? AND claim_token = ? AND lease_until > ?
        """,
        (format_utc_datetime(new_lease_until), loop_id, claim_token, now_str),
    )
    conn.commit()
    if cursor.rowcount == 0:
        return None
    return read_claim(loop_id=loop_id, conn=conn)


def release_claim(
    *,
    loop_id: int,
    claim_token: str,
    conn: sqlite3.Connection,
) -> bool:
    """Release a claim. Returns True if released, False if not found.

    Args:
        loop_id: Loop to release
        claim_token: Token from original claim
        conn: Database connection

    Returns:
        True if claim was released, False if not found
    """
    cursor = conn.execute(
        """
        DELETE FROM loop_claims
        WHERE loop_id = ? AND claim_token = ?
        """,
        (loop_id, claim_token),
    )
    conn.commit()
    return cursor.rowcount > 0


def release_claim_by_loop_id(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Force-release any claim on a loop (admin override).

    Args:
        loop_id: Loop to release
        conn: Database connection

    Returns:
        True if a claim was released, False if no claim existed
    """
    cursor = conn.execute(
        "DELETE FROM loop_claims WHERE loop_id = ?",
        (loop_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def purge_expired_claims(
    *,
    conn: sqlite3.Connection,
) -> int:
    """Delete all expired claims. Returns count purged.

    Args:
        conn: Database connection

    Returns:
        Number of expired claims deleted
    """
    now_str = format_utc_datetime(utc_now())
    cursor = conn.execute(
        "DELETE FROM loop_claims WHERE lease_until <= ?",
        (now_str,),
    )
    conn.commit()
    return cursor.rowcount


def list_active_claims(
    *,
    owner: str | None = None,
    limit: int = 100,
    conn: sqlite3.Connection,
) -> list[LoopClaimSummary]:
    """List all active (non-expired) claims, optionally filtered by owner.

    Args:
        owner: Optional owner filter
        limit: Max results
        conn: Database connection

    Returns:
        List of active LoopClaimSummaries (without tokens) ordered by lease_until ascending
    """
    now_str = format_utc_datetime(utc_now())
    if owner:
        rows = conn.execute(
            """
            SELECT loop_id, owner, leased_at, lease_until
            FROM loop_claims
            WHERE owner = ? AND lease_until > ?
            ORDER BY lease_until ASC
            LIMIT ?
            """,
            (owner, now_str, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT loop_id, owner, leased_at, lease_until
            FROM loop_claims
            WHERE lease_until > ?
            ORDER BY lease_until ASC
            LIMIT ?
            """,
            (now_str, limit),
        ).fetchall()
    return [
        LoopClaimSummary(
            loop_id=r["loop_id"],
            owner=r["owner"],
            leased_at_utc=parse_utc_datetime(r["leased_at"]),
            lease_until_utc=parse_utc_datetime(r["lease_until"]),
        )
        for r in rows
    ]
