"""Core loop-record repository operations.

Purpose:
    Own the base loop persistence operations for CRUD, listing, search, and export/import.

Responsibilities:
    - Read and mutate core loop rows
    - Apply repository-level field validation for raw loop updates
    - Shape LoopRecord results for service-layer orchestration

Non-scope:
    - Events, review artifacts, and comments persistence
    - Claims, timers, and dependency graph storage
    - Saved views, templates, or planning-session persistence
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Mapping

from ...typingx import escape_like_pattern
from ..errors import LoopCreateError, LoopImportError, LoopNotFoundError, ValidationError
from ..models import LoopRecord, LoopStatus, format_utc_datetime
from ..utils import normalize_tag
from .shared import _ALLOWED_UPDATE_FIELDS, _row_to_record


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
            due_date,
            recurrence_rrule,
            recurrence_tz,
            next_due_at_utc,
            recurrence_enabled
        )
        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_text,
            status.value,
            captured_at_utc,
            captured_tz_offset_min,
            None,
            recurrence_rrule,
            recurrence_tz,
            next_due_at_utc,
            1 if recurrence_enabled else 0,
        ),
    )
    row = conn.execute("SELECT * FROM loops WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise LoopCreateError(raw_text=raw_text)
    return _row_to_record(row)


def read_loop(*, loop_id: int, conn: sqlite3.Connection) -> LoopRecord | None:
    row = conn.execute("SELECT * FROM loops WHERE id = ?", (loop_id,)).fetchone()
    return _row_to_record(row) if row else None


def delete_loop(*, loop_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a loop row and cascade related records."""
    cursor = conn.execute("DELETE FROM loops WHERE id = ?", (loop_id,))
    if cursor.rowcount > 0:
        conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM loop_tags)")
        return True
    return False


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


def export_loops_filtered(
    *,
    status: list[LoopStatus] | None = None,
    project_name: str | None = None,
    tag: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    updated_after: str | None = None,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """Export loops with optional filters."""
    sql = "SELECT DISTINCT loops.* FROM loops"
    params: list[Any] = []
    conditions: list[str] = []
    joins: list[str] = []

    if project_name:
        joins.append("JOIN projects ON projects.id = loops.project_id")
        conditions.append("LOWER(projects.name) = LOWER(?)")
        params.append(project_name.strip())

    if tag:
        joins.append("JOIN loop_tags ON loop_tags.loop_id = loops.id")
        joins.append("JOIN tags ON tags.id = loop_tags.tag_id")
        conditions.append("LOWER(tags.name) = LOWER(?)")
        params.append(normalize_tag(tag))

    if status:
        placeholders = ", ".join("?" for _ in status)
        conditions.append(f"loops.status IN ({placeholders})")
        params.extend(s.value for s in status)

    if created_after:
        conditions.append("loops.created_at >= ?")
        params.append(created_after)

    if created_before:
        conditions.append("loops.created_at <= ?")
        params.append(created_before)

    if updated_after:
        conditions.append("loops.updated_at >= ?")
        params.append(updated_after)

    if joins:
        sql += " " + " ".join(joins)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY loops.updated_at DESC, loops.captured_at_utc DESC, loops.id DESC"

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def find_loop_by_raw_text(
    *,
    raw_text: str,
    conn: sqlite3.Connection,
) -> LoopRecord | None:
    """Find a loop by exact raw_text match."""
    row = conn.execute(
        "SELECT * FROM loops WHERE raw_text = ? LIMIT 1",
        [raw_text],
    ).fetchone()
    return _row_to_record(row) if row else None


def find_loop_by_title(
    *,
    title: str,
    conn: sqlite3.Connection,
) -> LoopRecord | None:
    """Find a loop by exact title match."""
    row = conn.execute(
        "SELECT * FROM loops WHERE title = ? LIMIT 1",
        [title],
    ).fetchone()
    return _row_to_record(row) if row else None


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
            due_date,
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
            :due_date,
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
        raise LoopImportError(payload=payload)
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
