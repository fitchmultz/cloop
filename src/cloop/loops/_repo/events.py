"""Loop event and enrichment-follow-up repository operations.

Purpose:
    Persist loop event history plus enrichment suggestions and clarifications.

Responsibilities:
    - Insert and list loop events
    - Persist suggestion and clarification rows
    - Resolve and answer review artifacts tied to enrichment flows

Non-scope:
    - Core loop-row CRUD
    - Saved review session metadata
    - Comment, timer, or dependency persistence
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any, Mapping


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


def read_loop_suggestion(
    *,
    suggestion_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get a single suggestion by ID."""
    row = conn.execute(
        """
        SELECT id, loop_id, suggestion_json, model, created_at,
               resolution, resolved_at, resolved_fields_json
        FROM loop_suggestions WHERE id = ?
        """,
        (suggestion_id,),
    ).fetchone()
    return dict(row) if row else None


def list_loop_suggestions(
    *,
    loop_id: int | None = None,
    resolution: str | None = None,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List suggestions, optionally filtered by loop_id and resolution status."""
    conditions = []
    params: list[Any] = []

    if loop_id is not None:
        conditions.append("loop_id = ?")
        params.append(loop_id)
    if resolution is not None:
        conditions.append("resolution = ?")
        params.append(resolution)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    rows = conn.execute(
        f"""
        SELECT id, loop_id, suggestion_json, model, created_at,
               resolution, resolved_at, resolved_fields_json
        FROM loop_suggestions
        {where_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_pending_suggestions(
    *,
    conn: sqlite3.Connection,
    loop_id: int | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """Get unresolved suggestions, optionally scoped to one loop.

    Pass `limit=None` to return all unresolved suggestions for the scope.
    """
    params: list[Any] = []
    where_clause = "WHERE resolution IS NULL"
    if loop_id is not None:
        where_clause += " AND loop_id = ?"
        params.append(loop_id)

    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, loop_id, suggestion_json, model, created_at,
               resolution, resolved_at, resolved_fields_json
        FROM loop_suggestions
        {where_clause}
        ORDER BY created_at DESC, id DESC
        {limit_clause}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_pending_suggestions_for_loops(
    *,
    loop_ids: Sequence[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get unresolved suggestions for multiple loops in one query."""
    if not loop_ids:
        return []
    placeholders = ", ".join("?" for _ in loop_ids)
    rows = conn.execute(
        f"""
        SELECT id, loop_id, suggestion_json, model, created_at,
               resolution, resolved_at, resolved_fields_json
        FROM loop_suggestions
        WHERE resolution IS NULL AND loop_id IN ({placeholders})
        ORDER BY created_at DESC, id DESC
        """,
        list(loop_ids),
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_loop_suggestion(
    *,
    suggestion_id: int,
    resolution: str,
    applied_fields: list[str] | None = None,
    conn: sqlite3.Connection,
) -> bool:
    """Mark a suggestion as resolved (applied/rejected/partial/superseded)."""
    from ..models import format_utc_datetime, utc_now

    if resolution not in ("applied", "rejected", "partial", "superseded"):
        raise ValueError(f"Invalid resolution: {resolution}")

    cursor = conn.execute(
        """
        UPDATE loop_suggestions
        SET resolution = ?, resolved_at = ?, resolved_fields_json = ?
        WHERE id = ?
        """,
        (
            resolution,
            format_utc_datetime(utc_now()),
            json.dumps(applied_fields) if applied_fields else None,
            suggestion_id,
        ),
    )
    return cursor.rowcount == 1


def insert_loop_clarification(
    *,
    loop_id: int,
    question: str,
    conn: sqlite3.Connection,
) -> int:
    """Insert a clarification question for a loop."""
    cursor = conn.execute(
        """
        INSERT INTO loop_clarifications (loop_id, question)
        VALUES (?, ?)
        """,
        (loop_id, question),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("loop_clarification_insert_failed")
    return int(cursor.lastrowid)


def read_loop_clarification(
    *,
    clarification_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get a single clarification row by ID."""
    row = conn.execute(
        """
        SELECT id, loop_id, question, answer, answered_at, created_at
        FROM loop_clarifications
        WHERE id = ?
        """,
        (clarification_id,),
    ).fetchone()
    return dict(row) if row else None


def list_loop_clarifications(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List all clarifications for a loop, unanswered first."""
    rows = conn.execute(
        """
        SELECT id, loop_id, question, answer, answered_at, created_at
        FROM loop_clarifications
        WHERE loop_id = ?
        ORDER BY answered_at IS NULL DESC, created_at ASC, id ASC
        """,
        (loop_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_loop_clarifications_for_loops(
    *,
    loop_ids: Sequence[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List clarifications for multiple loops in one query."""
    if not loop_ids:
        return []
    placeholders = ", ".join("?" for _ in loop_ids)
    rows = conn.execute(
        f"""
        SELECT id, loop_id, question, answer, answered_at, created_at
        FROM loop_clarifications
        WHERE loop_id IN ({placeholders})
        ORDER BY loop_id ASC, answered_at IS NULL DESC, created_at ASC, id ASC
        """,
        list(loop_ids),
    ).fetchall()
    return [dict(row) for row in rows]


def list_unanswered_clarifications_for_loops(
    *,
    loop_ids: Sequence[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List unanswered clarifications for multiple loops in one query."""
    if not loop_ids:
        return []
    placeholders = ", ".join("?" for _ in loop_ids)
    rows = conn.execute(
        f"""
        SELECT id, loop_id, question, answer, answered_at, created_at
        FROM loop_clarifications
        WHERE loop_id IN ({placeholders}) AND answer IS NULL
        ORDER BY loop_id ASC, created_at ASC, id ASC
        """,
        list(loop_ids),
    ).fetchall()
    return [dict(row) for row in rows]


def answer_loop_clarification(
    *,
    clarification_id: int,
    answer: str,
    conn: sqlite3.Connection,
) -> bool:
    """Record an answer to an unanswered clarification question."""
    from ..models import format_utc_datetime, utc_now

    cursor = conn.execute(
        """
        UPDATE loop_clarifications
        SET answer = ?, answered_at = ?
        WHERE id = ? AND answer IS NULL
        """,
        (answer, format_utc_datetime(utc_now()), clarification_id),
    )
    return cursor.rowcount == 1


def list_answered_clarifications(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get only answered clarifications for enrichment context."""
    rows = conn.execute(
        """
        SELECT id, loop_id, question, answer, answered_at, created_at
        FROM loop_clarifications
        WHERE loop_id = ? AND answer IS NOT NULL
        ORDER BY answered_at DESC, id DESC
        """,
        (loop_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_unanswered_clarification_questions(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> set[str]:
    """Get set of unanswered clarification question texts for deduplication.

    Args:
        loop_id: Loop to query
        conn: Database connection

    Returns:
        Set of question strings that have not been answered
    """
    rows = conn.execute(
        """
        SELECT question
        FROM loop_clarifications
        WHERE loop_id = ? AND answer IS NULL
        """,
        (loop_id,),
    ).fetchall()
    return {row["question"] for row in rows}
