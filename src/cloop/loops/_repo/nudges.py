"""Loop nudge-state repository operations.

Purpose:
    Persist organizer/scheduler nudge state tied to loops.

Responsibilities:
    - Read, upsert, reset, and batch-list nudge state rows
    - Convert nudge rows into LoopNudgeState models
    - Support scheduler-facing batch lookups

Non-scope:
    - Scheduler decision logic
    - Core loop CRUD, claims, or timers
    - Review-session persistence
"""

from __future__ import annotations

import sqlite3

from ..models import LoopNudgeState, parse_utc_datetime


def get_nudge_state(
    *,
    loop_id: int,
    nudge_type: str,
    conn: sqlite3.Connection,
) -> "LoopNudgeState | None":
    """Get nudge state for a specific loop and nudge type.

    Args:
        loop_id: Loop ID to get nudge state for
        nudge_type: Type of nudge ('due_soon', 'stale', 'blocked')
        conn: Database connection

    Returns:
        LoopNudgeState if exists, None otherwise
    """
    row = conn.execute(
        """
        SELECT loop_id, nudge_type, escalation_level, nudge_count,
               first_nudged_at, last_nudged_at, last_nudge_event_id
        FROM loop_nudges
        WHERE loop_id = ? AND nudge_type = ?
        """,
        (loop_id, nudge_type),
    ).fetchone()
    if row is None:
        return None
    return LoopNudgeState(
        loop_id=row["loop_id"],
        nudge_type=row["nudge_type"],
        escalation_level=row["escalation_level"],
        nudge_count=row["nudge_count"],
        first_nudged_at_utc=parse_utc_datetime(row["first_nudged_at"]),
        last_nudged_at_utc=parse_utc_datetime(row["last_nudged_at"]),
        last_nudge_event_id=row["last_nudge_event_id"],
    )


def upsert_nudge_state(
    *,
    loop_id: int,
    nudge_type: str,
    escalation_level: int,
    nudge_count: int,
    last_nudge_event_id: int | None,
    conn: sqlite3.Connection,
) -> None:
    """Create or update nudge state for a loop.

    Args:
        loop_id: Loop ID to update
        nudge_type: Type of nudge ('due_soon', 'stale', 'blocked')
        escalation_level: Current escalation level (0-3)
        nudge_count: Number of nudges sent
        last_nudge_event_id: ID of the last nudge event
        conn: Database connection
    """
    conn.execute(
        """
        INSERT INTO loop_nudges
            (loop_id, nudge_type, escalation_level, nudge_count,
             last_nudged_at, last_nudge_event_id)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(loop_id, nudge_type) DO UPDATE SET
            escalation_level = excluded.escalation_level,
            nudge_count = excluded.nudge_count,
            last_nudged_at = CURRENT_TIMESTAMP,
            last_nudge_event_id = excluded.last_nudge_event_id
        """,
        (loop_id, nudge_type, escalation_level, nudge_count, last_nudge_event_id),
    )


def reset_nudge_state(
    *,
    loop_id: int,
    nudge_type: str,
    conn: sqlite3.Connection,
) -> bool:
    """Reset nudge state (e.g., when loop is updated with next_action).

    Args:
        loop_id: Loop ID to reset
        nudge_type: Type of nudge to reset
        conn: Database connection

    Returns:
        True if a row was deleted, False otherwise
    """
    cursor = conn.execute(
        "DELETE FROM loop_nudges WHERE loop_id = ? AND nudge_type = ?",
        (loop_id, nudge_type),
    )
    return cursor.rowcount > 0


def get_nudge_states_batch(
    *,
    loop_ids: list[int],
    nudge_type: str,
    conn: sqlite3.Connection,
) -> dict[int, "LoopNudgeState"]:
    """Fetch nudge states for multiple loops in a single query.

    Args:
        loop_ids: List of loop IDs to fetch states for
        nudge_type: Type of nudge ('due_soon', 'stale', 'blocked')
        conn: Database connection

    Returns:
        Dict mapping loop_id -> LoopNudgeState for loops with existing state
    """
    if not loop_ids:
        return {}
    placeholders = ", ".join("?" for _ in loop_ids)
    rows = conn.execute(
        f"""
        SELECT loop_id, nudge_type, escalation_level, nudge_count,
               first_nudged_at, last_nudged_at, last_nudge_event_id
        FROM loop_nudges
        WHERE loop_id IN ({placeholders}) AND nudge_type = ?
        """,
        [*loop_ids, nudge_type],
    ).fetchall()
    result: dict[int, LoopNudgeState] = {}
    for row in rows:
        state = LoopNudgeState(
            loop_id=row["loop_id"],
            nudge_type=row["nudge_type"],
            escalation_level=row["escalation_level"],
            nudge_count=row["nudge_count"],
            first_nudged_at_utc=parse_utc_datetime(row["first_nudged_at"]),
            last_nudged_at_utc=parse_utc_datetime(row["last_nudged_at"]),
            last_nudge_event_id=row["last_nudge_event_id"],
        )
        result[state.loop_id] = state
    return result
