"""Planning-session repository operations.

Purpose:
    Persist checkpointed planning sessions and execution history rows.

Responsibilities:
    - Create, list, update, and delete planning sessions
    - Persist planning-session execution results
    - Serialize planning options, plans, and run payloads for storage

Non-scope:
    - Planning orchestration or checkpoint execution logic
    - Saved review sessions or action presets
    - Core loop CRUD and metadata persistence
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .shared import _UNSET


def create_planning_session(
    *,
    name: str,
    prompt: str,
    query: str | None,
    options_json: Mapping[str, Any],
    plan_json: Mapping[str, Any],
    current_checkpoint_index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a persisted planning session."""
    cursor = conn.execute(
        """
        INSERT INTO planning_sessions (
            name,
            prompt,
            query,
            options_json,
            plan_json,
            current_checkpoint_index
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            prompt,
            query,
            json.dumps(dict(options_json)),
            json.dumps(dict(plan_json)),
            current_checkpoint_index,
        ),
    )
    row = conn.execute(
        "SELECT * FROM planning_sessions WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("planning_session_insert_failed")
    return dict(row)


def list_planning_sessions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List persisted planning sessions."""
    rows = conn.execute(
        """
        SELECT *
        FROM planning_sessions
        ORDER BY updated_at DESC, id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_planning_session(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get one planning session."""
    row = conn.execute("SELECT * FROM planning_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def update_planning_session(
    *,
    session_id: int,
    name: str | None = None,
    prompt: str | None = None,
    query: str | None | object = _UNSET,
    options_json: Mapping[str, Any] | None = None,
    plan_json: Mapping[str, Any] | None = None,
    current_checkpoint_index: int | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Update one planning session and return the updated row."""
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if prompt is not None:
        updates.append("prompt = ?")
        params.append(prompt)
    if query is not _UNSET:
        updates.append("query = ?")
        params.append(query)
    if options_json is not None:
        updates.append("options_json = ?")
        params.append(json.dumps(dict(options_json)))
    if plan_json is not None:
        updates.append("plan_json = ?")
        params.append(json.dumps(dict(plan_json)))
    if current_checkpoint_index is not None:
        updates.append("current_checkpoint_index = ?")
        params.append(current_checkpoint_index)
    if not updates:
        return get_planning_session(session_id=session_id, conn=conn)
    params.append(session_id)
    conn.execute(
        f"""
        UPDATE planning_sessions
        SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        params,
    )
    return get_planning_session(session_id=session_id, conn=conn)


def delete_planning_session(*, session_id: int, conn: sqlite3.Connection) -> bool:
    """Delete one planning session."""
    cursor = conn.execute("DELETE FROM planning_sessions WHERE id = ?", (session_id,))
    return cursor.rowcount > 0


def create_planning_session_run(
    *,
    session_id: int,
    checkpoint_index: int,
    result_json: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Persist one checkpoint execution result for a planning session."""
    cursor = conn.execute(
        """
        INSERT INTO planning_session_runs (session_id, checkpoint_index, result_json)
        VALUES (?, ?, ?)
        """,
        (session_id, checkpoint_index, json.dumps(dict(result_json))),
    )
    row = conn.execute(
        "SELECT * FROM planning_session_runs WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("planning_session_run_insert_failed")
    return dict(row)


def list_planning_session_runs(
    *,
    session_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List execution rows for one planning session."""
    rows = conn.execute(
        """
        SELECT *
        FROM planning_session_runs
        WHERE session_id = ?
        ORDER BY checkpoint_index ASC, id ASC
        """,
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_planning_session_runs(*, session_id: int, conn: sqlite3.Connection) -> int:
    """Delete persisted checkpoint executions for one planning session."""
    cursor = conn.execute("DELETE FROM planning_session_runs WHERE session_id = ?", (session_id,))
    return int(cursor.rowcount)
