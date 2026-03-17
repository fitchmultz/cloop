"""Loop timer repository operations.

Purpose:
    Persist tracked-time sessions for loop timers.

Responsibilities:
    - Create, stop, list, count, and delete time sessions
    - Surface active-session and aggregate tracked-time lookups
    - Convert time-session rows into domain models

Non-scope:
    - Timer orchestration/business rules
    - Core loop CRUD or comment persistence
    - Planning/review session metadata
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import TimeSession


def _row_to_time_session(row: sqlite3.Row) -> "TimeSession":
    """Convert a database row to a TimeSession."""
    from ..models import TimeSession, parse_utc_datetime

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
    from ..models import format_utc_datetime

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
    from ..models import format_utc_datetime

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


def count_time_sessions(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> int:
    """Count all time sessions for a loop."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM time_sessions
        WHERE loop_id = ?
        """,
        (loop_id,),
    ).fetchone()
    return int(row["count"]) if row else 0


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
    return cursor.rowcount > 0
