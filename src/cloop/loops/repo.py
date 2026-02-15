"""Loop repository layer for raw database operations.

Purpose:
    Provide low-level SQLite CRUD operations for loops and related entities
    (tags, projects, events, claims, dependencies, time sessions, comments).

Responsibilities:
    - Execute parameterized SQL queries and mutations
    - Convert database rows to domain models
    - Handle transactional consistency via connection passing

Non-scope:
    - Business rule validation (see service.py)
    - HTTP request/response handling (see routes/loops.py)
    - Query DSL parsing (see query.py)
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from ..typingx import escape_like_pattern
from .errors import LoopNotFoundError, ValidationError
from .models import (
    EnrichmentState,
    LoopClaim,
    LoopClaimSummary,
    LoopComment,
    LoopRecord,
    LoopStatus,
    format_utc_datetime,
    parse_utc_datetime,
    utc_now,
)
from .query import LoopQuery, compile_loop_query, parse_loop_query

if TYPE_CHECKING:
    from .models import TimeSession

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
    "recurrence_rrule",
    "recurrence_tz",
    "next_due_at_utc",
    "recurrence_enabled",
    "parent_loop_id",
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
        recurrence_rrule=(
            row["recurrence_rrule"]
            if "recurrence_rrule" in row.keys() and row["recurrence_rrule"] is not None
            else None
        ),
        recurrence_tz=(
            row["recurrence_tz"]
            if "recurrence_tz" in row.keys() and row["recurrence_tz"] is not None
            else None
        ),
        next_due_at_utc=(
            parse_utc_datetime(row["next_due_at_utc"])
            if "next_due_at_utc" in row.keys() and row["next_due_at_utc"]
            else None
        ),
        recurrence_enabled=(
            bool(row["recurrence_enabled"]) if "recurrence_enabled" in row.keys() else False
        ),
        parent_loop_id=(
            row["parent_loop_id"]
            if "parent_loop_id" in row.keys() and row["parent_loop_id"] is not None
            else None
        ),
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
    recurrence_rrule: str | None = None,
    recurrence_tz: str | None = None,
    next_due_at_utc: str | None = None,
    recurrence_enabled: bool = False,
) -> LoopRecord:
    cursor = conn.execute(
        """
        INSERT INTO loops (
            raw_text,
            title,
            status,
            captured_at_utc,
            captured_tz_offset_min,
            recurrence_rrule,
            recurrence_tz,
            next_due_at_utc,
            recurrence_enabled
        )
        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_text,
            status.value,
            captured_at_utc,
            captured_tz_offset_min,
            recurrence_rrule,
            recurrence_tz,
            next_due_at_utc,
            1 if recurrence_enabled else 0,
        ),
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


def list_next_loop_candidates(
    *,
    limit: int,
    now_utc: datetime,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """Fetch candidate loops for next-loops with SQL-level filtering.

    Applies predicates in SQL:
    - status IN ('inbox', 'actionable')
    - next_action IS NOT NULL
    - snooze_until_utc IS NULL OR snooze_until_utc <= now_utc

    Uses UNION ALL with individual status equality to leverage the
    idx_loops_next_candidates partial index effectively.

    Note: Does NOT filter by open dependencies; that remains in service layer.

    Args:
        limit: Maximum candidates to return
        now_utc: Current UTC time for snooze comparison
        conn: Database connection

    Returns:
        List of candidate LoopRecords ordered by updated_at DESC
    """
    now_str = format_utc_datetime(now_utc)
    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT *
            FROM loops
            WHERE status = 'inbox'
              AND next_action IS NOT NULL
              AND (snooze_until_utc IS NULL OR snooze_until_utc <= ?)
            UNION ALL
            SELECT *
            FROM loops
            WHERE status = 'actionable'
              AND next_action IS NOT NULL
              AND (snooze_until_utc IS NULL OR snooze_until_utc <= ?)
        )
        ORDER BY updated_at DESC, captured_at_utc DESC, id DESC
        LIMIT ?
        """,
        (now_str, now_str, limit),
    ).fetchall()
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


def list_loop_events_paginated(
    *,
    loop_id: int,
    limit: int = 50,
    before_id: int | None = None,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List loop events with pagination support.

    Returns events in reverse chronological order (newest first).

    Args:
        loop_id: Loop to query
        limit: Max results
        before_id: Only return events with id < before_id
        conn: Database connection

    Returns:
        List of event dicts with id, event_type, payload_json, created_at
    """
    sql = (
        "SELECT id, loop_id, event_type, payload_json, created_at "
        "FROM loop_events WHERE loop_id = ?"
    )
    params: list[Any] = [loop_id]

    if before_id is not None:
        sql += " AND id < ?"
        params.append(before_id)

    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_latest_reversible_event(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get the most recent reversible event for a loop.

    Reversible events are: update, status_change, close

    Args:
        loop_id: Loop to query
        conn: Database connection

    Returns:
        Event dict or None if no reversible events exist
    """
    reversible_types = ("update", "status_change", "close")
    placeholders = ", ".join("?" for _ in reversible_types)

    row = conn.execute(
        f"""
        SELECT id, loop_id, event_type, payload_json, created_at
        FROM loop_events
        WHERE loop_id = ? AND event_type IN ({placeholders})
        ORDER BY id DESC
        LIMIT 1
        """,
        [loop_id, *reversible_types],
    ).fetchone()

    return dict(row) if row else None


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


def list_loop_links_by_type(
    *,
    loop_id: int,
    relationship_type: str,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List loop links of a specific relationship type.

    Args:
        loop_id: Loop to query
        relationship_type: Type of relationship (e.g., 'duplicate', 'related')
        conn: Database connection

    Returns:
        List of link dicts with related_loop_id, confidence, source, created_at
    """
    rows = conn.execute(
        """
        SELECT related_loop_id, relationship_type, confidence, source, created_at
        FROM loop_links
        WHERE loop_id = ? AND relationship_type = ?
        ORDER BY confidence DESC
        """,
        (loop_id, relationship_type),
    ).fetchall()
    return [dict(row) for row in rows]


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


# ============================================================================
# Loop Dependency Repository Functions
# ============================================================================


def add_dependency(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> int:
    """Add a dependency relationship (loop_id depends_on depends_on_loop_id).

    Args:
        loop_id: The loop that is blocked
        depends_on_loop_id: The loop that blocks it
        conn: Database connection

    Returns:
        The dependency record ID

    Raises:
        sqlite3.IntegrityError: If dependency already exists
    """
    cursor = conn.execute(
        """
        INSERT INTO loop_dependencies (loop_id, depends_on_loop_id)
        VALUES (?, ?)
        """,
        (loop_id, depends_on_loop_id),
    )
    conn.commit()
    if cursor.lastrowid is None:
        raise RuntimeError("add_dependency_failed")
    return int(cursor.lastrowid)


def remove_dependency(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Remove a dependency relationship.

    Args:
        loop_id: The blocked loop
        depends_on_loop_id: The loop it depended on
        conn: Database connection

    Returns:
        True if removed, False if not found
    """
    cursor = conn.execute(
        """
        DELETE FROM loop_dependencies
        WHERE loop_id = ? AND depends_on_loop_id = ?
        """,
        (loop_id, depends_on_loop_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """List all loop IDs that this loop depends on (its blockers).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of loop IDs that this loop depends on
    """
    rows = conn.execute(
        """
        SELECT depends_on_loop_id
        FROM loop_dependencies
        WHERE loop_id = ?
        ORDER BY depends_on_loop_id
        """,
        (loop_id,),
    ).fetchall()
    return [row["depends_on_loop_id"] for row in rows]


def list_dependents(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """List all loop IDs that depend on this loop (its dependents).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of loop IDs that depend on this loop
    """
    rows = conn.execute(
        """
        SELECT loop_id
        FROM loop_dependencies
        WHERE depends_on_loop_id = ?
        ORDER BY loop_id
        """,
        (loop_id,),
    ).fetchall()
    return [row["loop_id"] for row in rows]


def list_open_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """List dependency loop IDs that are NOT closed (completed/dropped).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of open dependency loop IDs
    """
    rows = conn.execute(
        """
        SELECT ld.depends_on_loop_id
        FROM loop_dependencies ld
        JOIN loops l ON l.id = ld.depends_on_loop_id
        WHERE ld.loop_id = ?
          AND l.status NOT IN ('completed', 'dropped')
        ORDER BY ld.depends_on_loop_id
        """,
        (loop_id,),
    ).fetchall()
    return [row["depends_on_loop_id"] for row in rows]


def has_open_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Check if a loop has any open (unsatisfied) dependencies.

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        True if there are open dependencies, False otherwise
    """
    row = conn.execute(
        """
        SELECT 1
        FROM loop_dependencies ld
        JOIN loops l ON l.id = ld.depends_on_loop_id
        WHERE ld.loop_id = ?
          AND l.status NOT IN ('completed', 'dropped')
        LIMIT 1
        """,
        (loop_id,),
    ).fetchone()
    return row is not None


def detect_dependency_cycle(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Check if adding loop_id -> depends_on_loop_id would create a cycle.

    A cycle exists if depends_on_loop_id can reach loop_id through existing
    dependencies (transitively). Also rejects self-dependencies.

    Args:
        loop_id: The loop that would become blocked
        depends_on_loop_id: The loop that would become the blocker
        conn: Database connection

    Returns:
        True if adding this dependency would create a cycle
    """
    if loop_id == depends_on_loop_id:
        return True

    # BFS/DFS to check if depends_on_loop_id can reach loop_id
    visited: set[int] = set()
    queue = [depends_on_loop_id]

    while queue:
        current = queue.pop(0)
        if current == loop_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        # Find what 'current' depends on (its blockers)
        rows = conn.execute(
            """
            SELECT depends_on_loop_id
            FROM loop_dependencies
            WHERE loop_id = ?
            """,
            (current,),
        ).fetchall()
        for row in rows:
            dep_id = row["depends_on_loop_id"]
            if dep_id not in visited:
                queue.append(dep_id)

    return False


def list_children(
    *,
    parent_loop_id: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """List all child loops of a parent loop.

    Args:
        parent_loop_id: The parent loop ID
        conn: Database connection

    Returns:
        List of child LoopRecords
    """
    rows = conn.execute(
        """
        SELECT * FROM loops
        WHERE parent_loop_id = ?
        ORDER BY captured_at_utc ASC, id ASC
        """,
        (parent_loop_id,),
    ).fetchall()
    return [_row_to_record(row) for row in rows]


# ============================================================================
# Time Session Repository Functions
# ============================================================================


def _row_to_time_session(row: sqlite3.Row) -> "TimeSession":
    """Convert a database row to a TimeSession."""
    from .models import TimeSession, parse_utc_datetime

    return TimeSession(
        id=row["id"],
        loop_id=row["loop_id"],
        started_at_utc=parse_utc_datetime(row["started_at"]),
        ended_at_utc=parse_utc_datetime(row["ended_at"]) if row["ended_at"] else None,
        duration_seconds=row["duration_seconds"],
        notes=row["notes"],
        created_at_utc=parse_utc_datetime(row["created_at"]),
    )


def create_time_session(
    *,
    loop_id: int,
    started_at: datetime,
    conn: sqlite3.Connection,
) -> "TimeSession":
    """Create a new time session (start a timer).

    Args:
        loop_id: Loop to track time for
        started_at: When the session started (UTC)
        conn: Database connection

    Returns:
        The created TimeSession

    Raises:
        sqlite3.IntegrityError: If loop_id doesn't exist
    """
    from .models import format_utc_datetime

    cursor = conn.execute(
        """
        INSERT INTO time_sessions (loop_id, started_at)
        VALUES (?, ?)
        """,
        (loop_id, format_utc_datetime(started_at)),
    )
    session_id = cursor.lastrowid
    if session_id is None:
        raise RuntimeError("time_session_create_failed")
    conn.commit()

    row = conn.execute("SELECT * FROM time_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise RuntimeError("time_session_fetch_failed")

    return _row_to_time_session(row)


def get_active_time_session(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> "TimeSession | None":
    """Get the active (unstopped) time session for a loop, if any.

    Args:
        loop_id: Loop to check
        conn: Database connection

    Returns:
        Active TimeSession or None if no active session
    """
    row = conn.execute(
        """
        SELECT * FROM time_sessions
        WHERE loop_id = ? AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (loop_id,),
    ).fetchone()
    return _row_to_time_session(row) if row else None


def stop_time_session(
    *,
    session_id: int,
    ended_at: datetime,
    duration_seconds: int,
    notes: str | None = None,
    conn: sqlite3.Connection,
) -> "TimeSession":
    """Stop a time session (stop the timer).

    Args:
        session_id: Session to stop
        ended_at: When the session ended (UTC)
        duration_seconds: Calculated duration in seconds
        notes: Optional notes for this session
        conn: Database connection

    Returns:
        The updated TimeSession

    Raises:
        ValueError: If session not found or already stopped
    """
    from .models import format_utc_datetime

    cursor = conn.execute(
        """
        UPDATE time_sessions
        SET ended_at = ?, duration_seconds = ?, notes = ?
        WHERE id = ? AND ended_at IS NULL
        """,
        (format_utc_datetime(ended_at), duration_seconds, notes, session_id),
    )
    if cursor.rowcount == 0:
        raise ValueError(f"No active session found with id={session_id}")
    conn.commit()

    row = conn.execute("SELECT * FROM time_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise RuntimeError("time_session_fetch_failed")
    return _row_to_time_session(row)


def list_time_sessions(
    *,
    loop_id: int,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection,
) -> list["TimeSession"]:
    """List time sessions for a loop, most recent first.

    Args:
        loop_id: Loop to list sessions for
        limit: Maximum number of sessions to return
        offset: Pagination offset
        conn: Database connection

    Returns:
        List of TimeSession objects
    """
    rows = conn.execute(
        """
        SELECT * FROM time_sessions
        WHERE loop_id = ?
        ORDER BY started_at DESC
        LIMIT ? OFFSET ?
        """,
        (loop_id, limit, offset),
    ).fetchall()
    return [_row_to_time_session(row) for row in rows]


def get_total_tracked_time(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> int:
    """Get total tracked time for a loop in seconds.

    Args:
        loop_id: Loop to get total for
        conn: Database connection

    Returns:
        Total seconds tracked (only completed sessions)
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(duration_seconds), 0) AS total
        FROM time_sessions
        WHERE loop_id = ? AND duration_seconds IS NOT NULL
        """,
        (loop_id,),
    ).fetchone()
    return int(row["total"]) if row else 0


def delete_time_session(
    *,
    session_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Delete a time session.

    Args:
        session_id: Session to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found
    """
    cursor = conn.execute("DELETE FROM time_sessions WHERE id = ?", (session_id,))
    conn.commit()
    return cursor.rowcount > 0


# ============================================================================
# Loop Template Repository Functions
# ============================================================================


def create_loop_template(
    *,
    name: str,
    description: str | None,
    raw_text_pattern: str,
    defaults_json: dict[str, Any],
    is_system: bool = False,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a new loop template.

    Args:
        name: Template name (must be unique)
        description: Optional template description
        raw_text_pattern: Pattern text with optional {{variable}} placeholders
        defaults_json: Dictionary of default field values
        is_system: Whether this is a system template (cannot be modified)
        conn: Database connection

    Returns:
        Created template record as dict

    Raises:
        ValidationError: If name is empty or already exists
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationError("name", "template name cannot be empty")

    try:
        cursor = conn.execute(
            """
            INSERT INTO loop_templates (
                name, description, raw_text_pattern, defaults_json, is_system
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_name,
                description,
                raw_text_pattern,
                json.dumps(defaults_json),
                1 if is_system else 0,
            ),
        )
        template_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValidationError("name", f"template '{normalized_name}' already exists") from None

    row = conn.execute("SELECT * FROM loop_templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row)


def list_loop_templates(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all loop templates, ordered by system templates first, then name.

    Args:
        conn: Database connection

    Returns:
        List of template records as dicts
    """
    rows = conn.execute("SELECT * FROM loop_templates ORDER BY is_system DESC, name ASC").fetchall()
    return [dict(row) for row in rows]


def get_loop_template(*, template_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get a template by ID.

    Args:
        template_id: Template ID
        conn: Database connection

    Returns:
        Template record as dict, or None if not found
    """
    row = conn.execute("SELECT * FROM loop_templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row) if row else None


def get_loop_template_by_name(*, name: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get a template by name (case-insensitive).

    Args:
        name: Template name to lookup
        conn: Database connection

    Returns:
        Template record as dict, or None if not found
    """
    row = conn.execute(
        "SELECT * FROM loop_templates WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def update_loop_template(
    *,
    template_id: int,
    name: str | None = None,
    description: str | None = None,
    raw_text_pattern: str | None = None,
    defaults_json: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a loop template. System templates cannot be modified.

    Args:
        template_id: Template ID to update
        name: New name (optional)
        description: New description (optional)
        raw_text_pattern: New pattern (optional)
        defaults_json: New defaults (optional)
        conn: Database connection

    Returns:
        Updated template record

    Raises:
        ValidationError: If template not found, is a system template, or name conflict
    """
    existing = get_loop_template(template_id=template_id, conn=conn)
    if not existing:
        raise ValidationError("template_id", f"template {template_id} not found")
    if existing["is_system"]:
        raise ValidationError("template_id", "system templates cannot be modified")

    updates: dict[str, Any] = {}
    if name is not None:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("name", "template name cannot be empty")
        updates["name"] = normalized
    if description is not None:
        updates["description"] = description
    if raw_text_pattern is not None:
        updates["raw_text_pattern"] = raw_text_pattern
    if defaults_json is not None:
        updates["defaults_json"] = json.dumps(defaults_json)

    if not updates:
        return existing

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [template_id]

    try:
        conn.execute(
            f"UPDATE loop_templates SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name", f"template '{updates.get('name', '')}' already exists"
        ) from None

    row = conn.execute("SELECT * FROM loop_templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row)


def delete_loop_template(*, template_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a loop template. System templates cannot be deleted.

    Args:
        template_id: Template ID to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found

    Raises:
        ValidationError: If trying to delete a system template
    """
    existing = get_loop_template(template_id=template_id, conn=conn)
    if not existing:
        return False
    if existing["is_system"]:
        raise ValidationError("template_id", "system templates cannot be deleted")

    cursor = conn.execute("DELETE FROM loop_templates WHERE id = ?", (template_id,))
    conn.commit()
    return cursor.rowcount > 0


# ============================================================================
# Loop Comment Repository Functions
# ============================================================================


def _row_to_comment(row: sqlite3.Row) -> LoopComment:
    """Convert a database row to a LoopComment."""
    return LoopComment(
        id=row["id"],
        loop_id=row["loop_id"],
        parent_id=row["parent_id"],
        author=row["author"],
        body_md=row["body_md"],
        created_at_utc=parse_utc_datetime(row["created_at"]),
        updated_at_utc=parse_utc_datetime(row["updated_at"]),
        deleted_at_utc=parse_utc_datetime(row["deleted_at"]) if row["deleted_at"] else None,
    )


def create_comment(
    *,
    loop_id: int,
    author: str,
    body_md: str,
    parent_id: int | None = None,
    conn: sqlite3.Connection,
) -> LoopComment:
    """Create a new comment on a loop.

    Args:
        loop_id: Loop to comment on
        author: Comment author identifier
        body_md: Markdown body text
        parent_id: Optional parent comment ID for replies
        conn: Database connection

    Returns:
        The created LoopComment
    """
    cursor = conn.execute(
        """
        INSERT INTO loop_comments (loop_id, parent_id, author, body_md)
        VALUES (?, ?, ?, ?)
        """,
        (loop_id, parent_id, author, body_md),
    )
    comment_id = cursor.lastrowid
    if comment_id is None:
        raise RuntimeError("comment_create_failed")

    row = conn.execute("SELECT * FROM loop_comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise RuntimeError("comment_fetch_failed")

    return _row_to_comment(row)


def list_comments(
    *,
    loop_id: int,
    include_deleted: bool = False,
    conn: sqlite3.Connection,
) -> list[LoopComment]:
    """List all comments for a loop, ordered for thread display.

    Returns comments ordered by:
    1. Parent comments first (parent_id IS NULL)
    2. Then replies grouped under parents
    3. Within each group, by created_at ASC

    Args:
        loop_id: Loop to list comments for
        include_deleted: Whether to include soft-deleted comments
        conn: Database connection

    Returns:
        List of LoopComment objects in thread order
    """
    deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"

    rows = conn.execute(
        f"""
        SELECT * FROM loop_comments
        WHERE loop_id = ? {deleted_filter}
        ORDER BY
            COALESCE(parent_id, id) ASC,
            parent_id IS NULL DESC,
            created_at ASC
        """,
        (loop_id,),
    ).fetchall()

    return [_row_to_comment(row) for row in rows]


def get_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> LoopComment | None:
    """Get a single comment by ID.

    Args:
        comment_id: Comment ID
        conn: Database connection

    Returns:
        LoopComment or None if not found
    """
    row = conn.execute(
        "SELECT * FROM loop_comments WHERE id = ?",
        (comment_id,),
    ).fetchone()
    return _row_to_comment(row) if row else None


def update_comment(
    *,
    comment_id: int,
    body_md: str,
    conn: sqlite3.Connection,
) -> LoopComment:
    """Update a comment's body.

    Args:
        comment_id: Comment to update
        body_md: New markdown body
        conn: Database connection

    Returns:
        Updated LoopComment

    Raises:
        RuntimeError: If comment not found or deleted
    """
    cursor = conn.execute(
        """
        UPDATE loop_comments
        SET body_md = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND deleted_at IS NULL
        """,
        (body_md, comment_id),
    )
    if cursor.rowcount == 0:
        raise RuntimeError("comment_not_found_or_deleted")

    row = conn.execute("SELECT * FROM loop_comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise RuntimeError("comment_fetch_failed")

    return _row_to_comment(row)


def soft_delete_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Soft-delete a comment (sets deleted_at timestamp).

    Args:
        comment_id: Comment to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found or already deleted
    """
    cursor = conn.execute(
        """
        UPDATE loop_comments
        SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND deleted_at IS NULL
        """,
        (comment_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def count_comments(
    *,
    loop_id: int,
    include_deleted: bool = False,
    conn: sqlite3.Connection,
) -> int:
    """Count comments for a loop.

    Args:
        loop_id: Loop to count comments for
        include_deleted: Whether to include soft-deleted comments
        conn: Database connection

    Returns:
        Number of comments
    """
    deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count FROM loop_comments
        WHERE loop_id = ? {deleted_filter}
        """,
        (loop_id,),
    ).fetchone()

    return int(row["count"]) if row else 0
