"""Scheduler schedule-bookkeeping persistence.

Purpose:
    Own per-task cadence bookkeeping for scheduler eligibility and latest-run
    summary state.

Responsibilities:
    - Read one task schedule row
    - Evaluate whether a task is currently due
    - Persist next-due and latest-run summary fields

Scope:
    - Scheduler schedule/bookkeeping persistence only

Usage:
    - Imported by scheduler runtime orchestration and the public scheduler
      storage facade

Invariants/Assumptions:
    - One row exists per `task_name` in `scheduler_task_schedule`
    - `runs_count` increments exactly once per completed evaluation persisted
      here
    - Stored `next_due_at` values are UTC ISO-8601 strings

Non-scope:
    - Task-run slot claiming or lease ownership
    - Push dedupe persistence
    - Scheduler cadence math beyond comparing persisted due timestamps
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ._shared import dump_optional_json, iso_utc


def get_task_schedule(*, task_name: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return cadence bookkeeping for one task."""
    row = conn.execute(
        """
        SELECT *
        FROM scheduler_task_schedule
        WHERE task_name = ?
        """,
        (task_name,),
    ).fetchone()
    return dict(row) if row is not None else None


def task_ready(*, task_name: str, now_utc: datetime, conn: sqlite3.Connection) -> bool:
    """Return whether a task is currently eligible to evaluate a slot."""
    row = get_task_schedule(task_name=task_name, conn=conn)
    if row is None or row["next_due_at"] is None:
        return True
    return row["next_due_at"] <= iso_utc(now_utc)


def update_task_schedule(
    *,
    task_name: str,
    next_due_at: datetime,
    started_at: datetime,
    finished_at: datetime,
    slot_key: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str | None,
    conn: sqlite3.Connection,
) -> None:
    """Persist cadence bookkeeping for the latest task evaluation."""
    started_at_iso = iso_utc(started_at)
    finished_at_iso = iso_utc(finished_at)
    conn.execute(
        """
        INSERT INTO scheduler_task_schedule (
            task_name,
            next_due_at,
            last_slot_key,
            last_started_at,
            last_finished_at,
            last_success_at,
            last_failure_at,
            last_result_json,
            last_error,
            runs_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(task_name) DO UPDATE SET
            next_due_at = excluded.next_due_at,
            last_slot_key = excluded.last_slot_key,
            last_started_at = excluded.last_started_at,
            last_finished_at = excluded.last_finished_at,
            last_success_at = excluded.last_success_at,
            last_failure_at = excluded.last_failure_at,
            last_result_json = excluded.last_result_json,
            last_error = excluded.last_error,
            runs_count = scheduler_task_schedule.runs_count + 1
        """,
        (
            task_name,
            iso_utc(next_due_at),
            slot_key,
            started_at_iso,
            finished_at_iso,
            finished_at_iso if success else None,
            finished_at_iso if not success else None,
            dump_optional_json(result),
            error,
        ),
    )
    conn.commit()


__all__ = [
    "get_task_schedule",
    "task_ready",
    "update_task_schedule",
]
