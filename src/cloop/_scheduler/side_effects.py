"""Scheduler side-effect helpers.

Purpose:
    Centralize scheduler slot heartbeat, event emission, push dedupe, and nudge
    persistence behavior shared across scheduler tasks.

Responsibilities:
    - Renew claimed scheduler slot leases and cancel runners on lease loss
    - Emit deduped scheduler-owned loop events
    - Reserve and record at-most-once scheduler push sends per slot
    - Persist loop nudge state once per scheduler slot

Scope:
    - Scheduler runtime side effects only

Non-scope:
    - Task-specific candidate selection or payload building
    - Scheduler CLI/process orchestration

Usage:
    - Imported by scheduler task modules and runtime orchestration

Invariants/Assumptions:
    - Event dedupe keys are `(task_name, slot_key, event_type)`
    - Push dedupe keys are `(task_name, slot_key, push_kind)`
    - Heartbeat loss cancels the owned task immediately
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any

from .. import db
from ..loops.models import LoopEventType, utc_now
from ..storage._scheduler_store import push_dedupe as scheduler_push_store
from ..storage._scheduler_store import task_runs as scheduler_task_runs
from .models import SchedulerPushSender, SchedulerRunContext

logger = logging.getLogger(__name__)


async def heartbeat_scheduler_run(
    *,
    context: SchedulerRunContext,
    runner_task: asyncio.Task[Any],
) -> None:
    """Renew the owned slot lease and cancel the runner on lease loss."""
    interval_seconds = max(1.0, context.settings.scheduler_lease_seconds / 3)
    while not context.lease_lost.is_set():
        await asyncio.sleep(interval_seconds)
        with db.core_connection(context.settings) as heartbeat_conn:
            renewed = scheduler_task_runs.heartbeat_task_run(
                task_name=context.task_name,
                slot_key=context.slot_key,
                owner_token=context.owner_token,
                lease_seconds=context.settings.scheduler_lease_seconds,
                heartbeat_at=utc_now(),
                conn=heartbeat_conn,
            )
        if not renewed:
            context.lease_lost.set()
            runner_task.cancel()
            return


def emit_scheduler_event(
    event_type: LoopEventType,
    payload: dict[str, Any],
    *,
    context: SchedulerRunContext,
    conn: sqlite3.Connection,
) -> int:
    """Insert one scheduler-owned loop event per `(task, slot, event_type)`."""
    context.assert_active()
    conn.execute(
        """
        INSERT OR IGNORE INTO loop_events (
            loop_id,
            event_type,
            payload_json,
            source_task_name,
            source_slot_key,
            created_at
        )
        VALUES (NULL, ?, ?, ?, ?, ?)
        """,
        (
            event_type.value,
            json.dumps(payload),
            context.task_name,
            context.slot_key,
            utc_now().isoformat(),
        ),
    )
    row = conn.execute(
        """
        SELECT id
        FROM loop_events
        WHERE source_task_name = ?
          AND source_slot_key = ?
          AND event_type = ?
        """,
        (context.task_name, context.slot_key, event_type.value),
    ).fetchone()
    if row is None:
        raise RuntimeError("scheduler_event_dedupe_lookup_failed")
    conn.commit()
    return int(row["id"])


def send_scheduler_push_once(
    *,
    push_kind: str,
    payload: dict[str, Any],
    context: SchedulerRunContext,
    conn: sqlite3.Connection,
    send_push_fn: SchedulerPushSender,
) -> int:
    """Send at most one scheduler push per `(task, slot, push_kind)`."""
    context.assert_active()
    existing = conn.execute(
        """
        SELECT push_count
        FROM scheduler_push_deliveries
        WHERE task_name = ? AND slot_key = ? AND push_kind = ?
        """,
        (context.task_name, context.slot_key, push_kind),
    ).fetchone()
    if existing is not None:
        return int(existing["push_count"] or 0)

    claimed = scheduler_push_store.claim_scheduler_push(
        task_name=context.task_name,
        slot_key=context.slot_key,
        push_kind=push_kind,
        payload=payload,
        claimed_at=utc_now(),
        conn=conn,
    )
    if not claimed:
        row = conn.execute(
            """
            SELECT push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            (context.task_name, context.slot_key, push_kind),
        ).fetchone()
        return int(row["push_count"] or 0) if row is not None else 0

    push_count = send_push_fn(push_kind, payload, context.settings, conn)
    scheduler_push_store.record_scheduler_push(
        task_name=context.task_name,
        slot_key=context.slot_key,
        push_kind=push_kind,
        payload=payload,
        push_count=push_count,
        sent_at=utc_now(),
        conn=conn,
    )
    return push_count


def upsert_nudge_state_for_slot(
    *,
    loop_id: int,
    nudge_type: str,
    escalation_level: int,
    nudge_count: int,
    last_nudge_event_id: int,
    slot_key: str,
    conn: sqlite3.Connection,
) -> None:
    """Persist one nudge update per loop and scheduler slot."""
    conn.execute(
        """
        INSERT INTO loop_nudges (
            loop_id,
            nudge_type,
            escalation_level,
            nudge_count,
            first_nudged_at,
            last_nudged_at,
            last_nudge_event_id,
            last_slot_key
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?)
        ON CONFLICT(loop_id, nudge_type) DO UPDATE SET
            escalation_level = excluded.escalation_level,
            nudge_count = excluded.nudge_count,
            last_nudged_at = CURRENT_TIMESTAMP,
            last_nudge_event_id = excluded.last_nudge_event_id,
            last_slot_key = excluded.last_slot_key
        WHERE loop_nudges.last_slot_key IS NULL
           OR loop_nudges.last_slot_key != excluded.last_slot_key
        """,
        (
            loop_id,
            nudge_type,
            escalation_level,
            nudge_count,
            last_nudge_event_id,
            slot_key,
        ),
    )
