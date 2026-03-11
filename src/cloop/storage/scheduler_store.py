"""Scheduler persistence for slot-based runs and deduped side effects.

Purpose:
    Coordinate the dedicated scheduler process with deterministic run slots,
    durable run ownership, and deduped push delivery markers.

Responsibilities:
    - Persist next-eligibility state per scheduler task
    - Claim, heartbeat, and finalize logical task runs keyed by slot
    - Mark expired runs abandoned when a new worker evaluates the same slot
    - Persist push-send dedupe records per task slot

Non-scope:
    - Computing slot keys or scheduler cadence policy
    - Emitting scheduler events or push payloads
    - Background loop orchestration

Invariants/Assumptions:
    - `(task_name, slot_key)` uniquely identifies one logical scheduler run.
    - A succeeded run row means the slot must never execute again.
    - Push send markers are unique per `(task_name, slot_key, push_kind)`.
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
        (_iso(now_utc), task_name, _iso(now_utc)),
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
                _iso(lease_until),
                _iso(started_at),
                _iso(started_at),
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
        (_iso(heartbeat_at), _iso(lease_until), task_name, slot_key, owner_token),
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
            _iso(finished_at),
            _iso(finished_at),
            _iso(finished_at),
            json.dumps(result) if result is not None else None,
            error,
            task_name,
            slot_key,
            owner_token,
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


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
    return row["next_due_at"] <= _iso(now_utc)


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
    started_at_iso = _iso(started_at)
    finished_at_iso = _iso(finished_at)
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
            _iso(next_due_at),
            slot_key,
            started_at_iso,
            finished_at_iso,
            finished_at_iso if success else None,
            finished_at_iso if not success else None,
            json.dumps(result) if result is not None else None,
            error,
        ),
    )
    conn.commit()


def record_scheduler_push(
    *,
    task_name: str,
    slot_key: str,
    push_kind: str,
    payload: dict[str, Any],
    push_count: int,
    sent_at: datetime,
    conn: sqlite3.Connection,
) -> bool:
    """Record a push send once per task slot and push kind."""
    cursor = conn.execute(
        """
        UPDATE scheduler_push_deliveries
        SET payload_json = ?,
            push_count = ?,
            sent_at = ?
        WHERE task_name = ?
          AND slot_key = ?
          AND push_kind = ?
        """,
        (json.dumps(payload), push_count, _iso(sent_at), task_name, slot_key, push_kind),
    )
    if cursor.rowcount == 1:
        conn.commit()
        return True

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO scheduler_push_deliveries (
            task_name,
            slot_key,
            push_kind,
            payload_json,
            push_count,
            sent_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_name, slot_key, push_kind, json.dumps(payload), push_count, _iso(sent_at)),
    )
    conn.commit()
    return cursor.rowcount == 1


def claim_scheduler_push(
    *,
    task_name: str,
    slot_key: str,
    push_kind: str,
    payload: dict[str, Any],
    claimed_at: datetime,
    conn: sqlite3.Connection,
) -> bool:
    """Reserve one scheduler push marker before sending the external notification."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO scheduler_push_deliveries (
            task_name,
            slot_key,
            push_kind,
            payload_json,
            push_count,
            sent_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_name, slot_key, push_kind, json.dumps(payload), 0, _iso(claimed_at)),
    )
    conn.commit()
    return cursor.rowcount == 1


# Legacy helper aliases retained for internal call sites/tests while the new
# slot-based model becomes the single runtime path.
def task_due(*, task_name: str, now_utc: datetime, conn: sqlite3.Connection) -> bool:
    """Compatibility alias for cadence eligibility checks."""
    return task_ready(task_name=task_name, now_utc=now_utc, conn=conn)


def acquire_task_lease(
    *,
    task_name: str,
    owner_token: str,
    lease_seconds: int,
    conn: sqlite3.Connection,
) -> bool:
    """Compatibility wrapper that claims a synthetic legacy slot."""
    return claim_task_run(
        task_name=task_name,
        slot_key="legacy",
        owner_token=owner_token,
        started_at=_utc_now(),
        lease_seconds=lease_seconds,
        conn=conn,
    )


def get_task_run_state(*, task_name: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Compatibility wrapper exposing schedule bookkeeping in the old shape."""
    row = get_task_schedule(task_name=task_name, conn=conn)
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
    """Compatibility wrapper around schedule updates."""
    update_task_schedule(
        task_name=task_name,
        next_due_at=next_due_at,
        started_at=started_at,
        finished_at=finished_at,
        slot_key="legacy",
        success=success,
        result=result,
        error=error,
        conn=conn,
    )


def start_task_execution(
    *,
    run_id: str,
    task_name: str,
    owner_token: str,
    started_at: datetime,
    conn: sqlite3.Connection,
) -> None:
    """Compatibility wrapper that claims a slot keyed by run ID."""
    claim_task_run(
        task_name=task_name,
        slot_key=run_id,
        owner_token=owner_token,
        started_at=started_at,
        lease_seconds=60,
        conn=conn,
    )


def heartbeat_task_execution(
    *,
    run_id: str,
    owner_token: str,
    heartbeat_at: datetime,
    conn: sqlite3.Connection,
) -> None:
    """Compatibility wrapper that heartbeats a run-ID keyed slot."""
    heartbeat_task_run(
        task_name=conn.execute(
            "SELECT task_name FROM scheduler_task_runs WHERE slot_key = ? LIMIT 1",
            (run_id,),
        ).fetchone()["task_name"],
        slot_key=run_id,
        owner_token=owner_token,
        lease_seconds=60,
        heartbeat_at=heartbeat_at,
        conn=conn,
    )


def finish_task_execution(
    *,
    run_id: str,
    owner_token: str,
    finished_at: datetime,
    status: str,
    error: str | None,
    result: dict[str, Any] | None,
    conn: sqlite3.Connection,
) -> None:
    """Compatibility wrapper that finalizes a run-ID keyed slot."""
    row = conn.execute(
        "SELECT task_name FROM scheduler_task_runs WHERE slot_key = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("scheduler_task_run_missing")
    finish_task_run(
        task_name=row["task_name"],
        slot_key=run_id,
        owner_token=owner_token,
        finished_at=finished_at,
        status=status,
        result=result,
        error=error,
        conn=conn,
    )
