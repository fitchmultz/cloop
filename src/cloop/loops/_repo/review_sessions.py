"""Saved review-workflow repository operations.

Purpose:
    Persist review action presets and durable review-session metadata.

Responsibilities:
    - Create, list, update, and delete review action presets
    - Create, list, update, and delete saved review sessions
    - Serialize review-session option payloads for storage

Non-scope:
    - Relationship-link or suggestion row persistence
    - Planning-session execution history
    - Core loop CRUD or query execution
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .shared import _UNSET


def create_review_action_preset(
    *,
    name: str,
    review_kind: str,
    action_type: str,
    config_json: Mapping[str, Any],
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a persisted review action preset."""
    cursor = conn.execute(
        """
        INSERT INTO review_action_presets (name, review_kind, action_type, config_json, description)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, review_kind, action_type, json.dumps(dict(config_json)), description),
    )
    row = conn.execute(
        "SELECT * FROM review_action_presets WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("review_action_preset_insert_failed")
    return dict(row)


def list_review_action_presets(
    *,
    review_kind: str | None,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List review action presets, optionally filtered by review kind."""
    params: list[Any] = []
    where_clause = ""
    if review_kind is not None:
        where_clause = "WHERE review_kind = ?"
        params.append(review_kind)
    rows = conn.execute(
        f"""
        SELECT *
        FROM review_action_presets
        {where_clause}
        ORDER BY review_kind ASC, name ASC, id ASC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_review_action_preset(
    *,
    action_preset_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get one review action preset."""
    row = conn.execute(
        "SELECT * FROM review_action_presets WHERE id = ?",
        (action_preset_id,),
    ).fetchone()
    return dict(row) if row else None


def update_review_action_preset(
    *,
    action_preset_id: int,
    name: str | None = None,
    action_type: str | None = None,
    config_json: Mapping[str, Any] | None = None,
    description: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Update one review action preset and return the updated row."""
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if action_type is not None:
        updates.append("action_type = ?")
        params.append(action_type)
    if config_json is not None:
        updates.append("config_json = ?")
        params.append(json.dumps(dict(config_json)))
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if not updates:
        return get_review_action_preset(action_preset_id=action_preset_id, conn=conn)
    params.append(action_preset_id)
    conn.execute(
        f"""
        UPDATE review_action_presets
        SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        params,
    )
    return get_review_action_preset(action_preset_id=action_preset_id, conn=conn)


def delete_review_action_preset(*, action_preset_id: int, conn: sqlite3.Connection) -> bool:
    """Delete one review action preset."""
    cursor = conn.execute("DELETE FROM review_action_presets WHERE id = ?", (action_preset_id,))
    return cursor.rowcount > 0


def create_review_session(
    *,
    name: str,
    review_kind: str,
    query: str,
    options_json: Mapping[str, Any],
    current_loop_id: int | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a persisted review session."""
    cursor = conn.execute(
        """
        INSERT INTO review_sessions (name, review_kind, query, options_json, current_loop_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, review_kind, query, json.dumps(dict(options_json)), current_loop_id),
    )
    row = conn.execute("SELECT * FROM review_sessions WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise RuntimeError("review_session_insert_failed")
    return dict(row)


def list_review_sessions(
    *,
    review_kind: str | None,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List review sessions, optionally filtered by review kind."""
    params: list[Any] = []
    where_clause = ""
    if review_kind is not None:
        where_clause = "WHERE review_kind = ?"
        params.append(review_kind)
    rows = conn.execute(
        f"""
        SELECT *
        FROM review_sessions
        {where_clause}
        ORDER BY review_kind ASC, updated_at DESC, id DESC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_review_session(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get one review session."""
    row = conn.execute("SELECT * FROM review_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def update_review_session(
    *,
    session_id: int,
    name: str | None = None,
    query: str | None = None,
    options_json: Mapping[str, Any] | None = None,
    current_loop_id: int | None | object = _UNSET,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Update one review session and return the updated row."""
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if query is not None:
        updates.append("query = ?")
        params.append(query)
    if options_json is not None:
        updates.append("options_json = ?")
        params.append(json.dumps(dict(options_json)))
    if current_loop_id is not _UNSET:
        updates.append("current_loop_id = ?")
        params.append(current_loop_id)
    if not updates:
        return get_review_session(session_id=session_id, conn=conn)
    params.append(session_id)
    conn.execute(
        f"""
        UPDATE review_sessions
        SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        params,
    )
    return get_review_session(session_id=session_id, conn=conn)


def delete_review_session(*, session_id: int, conn: sqlite3.Connection) -> bool:
    """Delete one review session."""
    cursor = conn.execute("DELETE FROM review_sessions WHERE id = ?", (session_id,))
    return cursor.rowcount > 0
