"""Scheduler state storage.

Purpose:
    Persist scheduler leases and run-state in SQLite so a dedicated scheduler
    process can coordinate safely.

Responsibilities:
    - Acquire, renew, heartbeat, and release task leases
    - Read and update task run-state records
    - Answer whether a task is due based on persisted eligibility

Non-scope:
    - Task execution logic
    - Scheduler transport/runtime loops

Invariants/Assumptions:
    - `scheduler_task_leases.task_name` is unique.
    - `scheduler_task_state.task_name` is unique.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def acquire_task_lease(
    *,
    task_name: str,
    owner_token: str,
    lease_seconds: int,
    conn: sqlite3.Connection,
) -> bool:
    """Atomically acquire a task lease if it is absent or expired."""
    now = _utc_now()
    lease_until = _iso(now + timedelta(seconds=lease_seconds))
    cursor = conn.execute(
        """
        INSERT INTO scheduler_task_leases (
            task_name, owner_token, acquired_at, heartbeat_at, lease_until
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(task_name) DO UPDATE SET
            owner_token = excluded.owner_token,
            acquired_at = excluded.acquired_at,
            heartbeat_at = excluded.heartbeat_at,
            lease_until = excluded.lease_until
        WHERE scheduler_task_leases.lease_until <= excluded.acquired_at
        """,
        (task_name, owner_token, _iso(now), _iso(now), lease_until),
    )
    conn.commit()
    return cursor.rowcount == 1


def renew_task_lease(
    *,
    task_name: str,
    owner_token: str,
    lease_seconds: int,
    conn: sqlite3.Connection,
) -> bool:
    """Renew an existing lease held by the given owner."""
    now = _utc_now()
    cursor = conn.execute(
        """
        UPDATE scheduler_task_leases
        SET heartbeat_at = ?, lease_until = ?
        WHERE task_name = ? AND owner_token = ?
        """,
        (_iso(now), _iso(now + timedelta(seconds=lease_seconds)), task_name, owner_token),
    )
    conn.commit()
    return cursor.rowcount == 1


def heartbeat_task_lease(
    *,
    task_name: str,
    owner_token: str,
    lease_seconds: int,
    conn: sqlite3.Connection,
) -> bool:
    """Alias for lease renewal during long task execution."""
    return renew_task_lease(
        task_name=task_name,
        owner_token=owner_token,
        lease_seconds=lease_seconds,
        conn=conn,
    )


def release_task_lease(*, task_name: str, owner_token: str, conn: sqlite3.Connection) -> bool:
    """Release a lease held by the given owner."""
    cursor = conn.execute(
        "DELETE FROM scheduler_task_leases WHERE task_name = ? AND owner_token = ?",
        (task_name, owner_token),
    )
    conn.commit()
    return cursor.rowcount == 1


def get_task_run_state(*, task_name: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return persisted scheduler task state."""
    row = conn.execute(
        "SELECT * FROM scheduler_task_state WHERE task_name = ?",
        (task_name,),
    ).fetchone()
    if row is None:
        return None
    return {
        "task_name": row["task_name"],
        "last_started_at": row["last_started_at"],
        "last_finished_at": row["last_finished_at"],
        "last_success_at": row["last_success_at"],
        "last_failure_at": row["last_failure_at"],
        "last_error": row["last_error"],
        "last_result": json.loads(row["last_result_json"]) if row["last_result_json"] else None,
        "next_due_at": row["next_due_at"],
        "runs_count": row["runs_count"],
    }


def task_due(*, task_name: str, now_utc: datetime, conn: sqlite3.Connection) -> bool:
    """Return True when the task should run now."""
    row = conn.execute(
        "SELECT next_due_at FROM scheduler_task_state WHERE task_name = ?",
        (task_name,),
    ).fetchone()
    if row is None or row["next_due_at"] is None:
        return True
    return row["next_due_at"] <= _iso(now_utc)


def update_task_run_state(
    *,
    task_name: str,
    started_at: datetime,
    finished_at: datetime,
    success: bool,
    next_due_at: datetime,
    result: dict[str, Any] | None,
    error: str | None,
    conn: sqlite3.Connection,
) -> None:
    """Persist run outcome and next eligibility."""
    started_at_iso = _iso(started_at)
    finished_at_iso = _iso(finished_at)
    next_due_at_iso = _iso(next_due_at)
    success_at = finished_at_iso if success else None
    failure_at = finished_at_iso if not success else None
    conn.execute(
        """
        INSERT INTO scheduler_task_state (
            task_name,
            last_started_at,
            last_finished_at,
            last_success_at,
            last_failure_at,
            last_error,
            last_result_json,
            next_due_at,
            runs_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(task_name) DO UPDATE SET
            last_started_at = excluded.last_started_at,
            last_finished_at = excluded.last_finished_at,
            last_success_at = excluded.last_success_at,
            last_failure_at = excluded.last_failure_at,
            last_error = excluded.last_error,
            last_result_json = excluded.last_result_json,
            next_due_at = excluded.next_due_at,
            runs_count = scheduler_task_state.runs_count + 1
        """,
        (
            task_name,
            started_at_iso,
            finished_at_iso,
            success_at,
            failure_at,
            error,
            json.dumps(result) if result is not None else None,
            next_due_at_iso,
        ),
    )
    conn.commit()
