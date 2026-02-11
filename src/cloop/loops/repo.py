from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Mapping

from .. import typingx
from .models import EnrichmentState, LoopRecord, LoopStatus, parse_utc_datetime

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
_escape_like_pattern = typingx.escape_like_pattern


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
        id=typingx.as_type(int, row["id"]),
        raw_text=typingx.as_type(str, row["raw_text"]),
        title=typingx.as_type(str, row["title"]) if row["title"] is not None else None,
        summary=typingx.as_type(str, row["summary"]) if row["summary"] is not None else None,
        definition_of_done=(
            typingx.as_type(str, row["definition_of_done"])
            if row["definition_of_done"] is not None
            else None
        ),
        next_action=(
            typingx.as_type(str, row["next_action"]) if row["next_action"] is not None else None
        ),
        status=LoopStatus(typingx.as_type(str, row["status"])),
        captured_at_utc=parse_utc_datetime(typingx.as_type(str, row["captured_at_utc"])),
        captured_tz_offset_min=typingx.as_type(int, row["captured_tz_offset_min"]),
        due_at_utc=(
            parse_utc_datetime(typingx.as_type(str, row["due_at_utc"]))
            if row["due_at_utc"]
            else None
        ),
        snooze_until_utc=(
            parse_utc_datetime(typingx.as_type(str, row["snooze_until_utc"]))
            if row["snooze_until_utc"]
            else None
        ),
        time_minutes=(
            typingx.as_type(int, row["time_minutes"]) if row["time_minutes"] is not None else None
        ),
        activation_energy=(
            typingx.as_type(int, row["activation_energy"])
            if row["activation_energy"] is not None
            else None
        ),
        urgency=(typingx.as_type(float, row["urgency"]) if row["urgency"] is not None else None),
        importance=(
            typingx.as_type(float, row["importance"]) if row["importance"] is not None else None
        ),
        project_id=(
            typingx.as_type(int, row["project_id"]) if row["project_id"] is not None else None
        ),
        blocked_reason=(
            typingx.as_type(str, row["blocked_reason"])
            if row["blocked_reason"] is not None
            else None
        ),
        completion_note=(
            typingx.as_type(str, row["completion_note"])
            if row["completion_note"] is not None
            else None
        ),
        user_locks=_parse_json_list(row["user_locks_json"]),
        provenance=_parse_json_dict(row["provenance_json"]),
        enrichment_state=EnrichmentState(
            typingx.as_type(str, row["enrichment_state"] or EnrichmentState.IDLE.value)
        ),
        created_at_utc=parse_utc_datetime(typingx.as_type(str, row["created_at"])),
        updated_at_utc=parse_utc_datetime(typingx.as_type(str, row["updated_at"])),
        closed_at_utc=(
            parse_utc_datetime(typingx.as_type(str, row["closed_at"])) if row["closed_at"] else None
        ),
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
    sql += " ORDER BY updated_at DESC, captured_at_utc DESC LIMIT ? OFFSET ?"
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
    sql += " ORDER BY updated_at DESC, captured_at_utc DESC"
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
        "SELECT * FROM loops ORDER BY updated_at DESC, captured_at_utc DESC"
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
    sql += " ORDER BY loops.updated_at DESC, loops.captured_at_utc DESC LIMIT ? OFFSET ?"
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
    return [typingx.as_type(str, row["name"]) for row in rows]


def search_loops(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    escaped_query = typingx.escape_like_pattern(query)
    like_query = f"%{escaped_query}%"
    rows = conn.execute(
        """
        SELECT *
        FROM loops
        WHERE raw_text LIKE ? ESCAPE '\\'
           OR title LIKE ? ESCAPE '\\'
           OR summary LIKE ? ESCAPE '\\'
           OR next_action LIKE ? ESCAPE '\\'
        ORDER BY captured_at_utc DESC
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
    updates = {key: value for key, value in fields.items() if key in _ALLOWED_UPDATE_FIELDS}
    if not updates:
        raise ValueError("no_valid_fields")
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
        raise ValueError("loop_not_found")
    return _row_to_record(row)


def insert_loop_event(
    *,
    loop_id: int,
    event_type: str,
    payload: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
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
    return typingx.as_type(str, row["name"]) if row else None


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
    return {int(row["id"]): typingx.as_type(str, row["name"]) for row in rows}


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
        result.setdefault(loop_id, []).append(typingx.as_type(str, row["name"]))
    return result


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM projects ORDER BY name ASC").fetchall()
    return [dict(row) for row in rows]


def upsert_tag(*, name: str, conn: sqlite3.Connection) -> int:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("tag_name_empty")
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
    return [typingx.as_type(str, row["name"]) for row in rows]


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
