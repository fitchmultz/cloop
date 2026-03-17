"""Scheduler task-run persistence.

Purpose:
    Own durable task-slot claiming, lease renewal, abandonment, and finalization
    for scheduler task runs.

Responsibilities:
    - Mark expired running slots abandoned before new claims
    - Claim deterministic task slots with lease ownership
    - Read one persisted task-run row
    - Heartbeat and finalize owned task runs

Scope:
    - Scheduler task-run row persistence only

Usage:
    - Imported by scheduler runtime orchestration and the public scheduler
      storage facade

Invariants/Assumptions:
    - `(task_name, slot_key)` uniquely identifies one logical scheduler run
    - A succeeded row must never be reclaimed
    - Only the owning token may heartbeat or finalize a running row

Non-scope:
    - Scheduler cadence eligibility calculations
    - Push dedupe persistence or scheduler-side effect emission
    - Legacy compatibility wrappers for pre-slot execution APIs
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ._shared import dump_optional_json, iso_utc


def mark_abandoned_runs(*, task_name: str, now_utc: datetime, conn: sqlite3.Connection) -> int:
    """Mark expired running rows as abandoned before evaluating a slot."""
    cursor = conn.execute(
        """
        UPDATE scheduler_task_runs
        SET status = 'abandoned',
            finished_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = ?
          AND status = 'running'
          AND lease_until IS NOT NULL
          AND lease_until <= ?
        """,
        (iso_utc(now_utc), task_name, iso_utc(now_utc)),
    )
    return cursor.rowcount


def claim_task_run(
    *,
    task_name: str,
    slot_key: str,
    owner_token: str,
    started_at: datetime,
    lease_seconds: int,
    conn: sqlite3.Connection,
) -> bool:
    """Claim a logical scheduler run for a deterministic slot."""
    lease_until = started_at + timedelta(seconds=lease_seconds)
    conn.execute("BEGIN IMMEDIATE")
    try:
        mark_abandoned_runs(task_name=task_name, now_utc=started_at, conn=conn)
        cursor = conn.execute(
            """
            INSERT INTO scheduler_task_runs (
                task_name,
                slot_key,
                status,
                owner_token,
                lease_until,
                started_at,
                heartbeat_at
            )
            VALUES (?, ?, 'running', ?, ?, ?, ?)
            ON CONFLICT(task_name, slot_key) DO UPDATE SET
                status = 'running',
                owner_token = excluded.owner_token,
                lease_until = excluded.lease_until,
                started_at = excluded.started_at,
                heartbeat_at = excluded.heartbeat_at,
                finished_at = NULL,
                result_json = NULL,
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE scheduler_task_runs.status != 'succeeded'
              AND (
                scheduler_task_runs.status IN ('queued', 'failed', 'abandoned')
                OR (
                    scheduler_task_runs.status = 'running'
                    AND scheduler_task_runs.lease_until <= excluded.started_at
                )
              )
            """,
            (
                task_name,
                slot_key,
                owner_token,
                iso_utc(lease_until),
                iso_utc(started_at),
                iso_utc(started_at),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return cursor.rowcount == 1


def get_task_run(
    *, task_name: str, slot_key: str, conn: sqlite3.Connection
) -> dict[str, Any] | None:
    """Fetch one scheduler task run row."""
    row = conn.execute(
        """
        SELECT *
        FROM scheduler_task_runs
        WHERE task_name = ? AND slot_key = ?
        """,
        (task_name, slot_key),
    ).fetchone()
    return dict(row) if row is not None else None


def heartbeat_task_run(
    *,
    task_name: str,
    slot_key: str,
    owner_token: str,
    lease_seconds: int,
    heartbeat_at: datetime,
    conn: sqlite3.Connection,
) -> bool:
    """Renew the lease and heartbeat for an owned running task slot."""
    lease_until = heartbeat_at + timedelta(seconds=lease_seconds)
    cursor = conn.execute(
        """
        UPDATE scheduler_task_runs
        SET heartbeat_at = ?,
            lease_until = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = ?
          AND slot_key = ?
          AND owner_token = ?
          AND status = 'running'
        """,
        (iso_utc(heartbeat_at), iso_utc(lease_until), task_name, slot_key, owner_token),
    )
    conn.commit()
    return cursor.rowcount == 1


def finish_task_run(
    *,
    task_name: str,
    slot_key: str,
    owner_token: str,
    finished_at: datetime,
    status: str,
    result: dict[str, Any] | None,
    error: str | None,
    conn: sqlite3.Connection,
) -> bool:
    """Finalize a claimed task slot if this owner still holds the row."""
    cursor = conn.execute(
        """
        UPDATE scheduler_task_runs
        SET status = ?,
            finished_at = ?,
            heartbeat_at = ?,
            lease_until = ?,
            result_json = ?,
            error = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = ?
          AND slot_key = ?
          AND owner_token = ?
          AND status = 'running'
        """,
        (
            status,
            iso_utc(finished_at),
            iso_utc(finished_at),
            iso_utc(finished_at),
            dump_optional_json(result),
            error,
            task_name,
            slot_key,
            owner_token,
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


__all__ = [
    "claim_task_run",
    "finish_task_run",
    "get_task_run",
    "heartbeat_task_run",
    "mark_abandoned_runs",
]
