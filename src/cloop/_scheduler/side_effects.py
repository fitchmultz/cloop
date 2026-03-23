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
from ..schemas._loops.continuity import ContinuityNotificationRecordResponse
from ..storage._scheduler_store import push_dedupe as scheduler_push_store
from ..storage._scheduler_store import task_runs as scheduler_task_runs
from ..storage.continuity_store import read_continuity_notification_records
from .models import SchedulerPushSender, SchedulerRunContext

logger = logging.getLogger(__name__)


def _select_scheduler_notification(
    *,
    context: SchedulerRunContext,
) -> ContinuityNotificationRecordResponse | None:
    notifications = read_continuity_notification_records(
        limit=1,
        settings=context.settings,
        channel="push",
    )
    return notifications[0] if notifications else None


def _scheduler_push_payload(
    payload: dict[str, Any],
    *,
    notification: ContinuityNotificationRecordResponse | None,
) -> dict[str, Any]:
    if notification is None:
        return payload
    return {
        **payload,
        "notification_id": notification.id,
        "workflow_thread_id": notification.workflow_thread.id,
    }


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

    notification = _select_scheduler_notification(context=context)
    payload_with_provenance = _scheduler_push_payload(payload, notification=notification)
    claimed_at = utc_now()
    claimed = scheduler_push_store.claim_scheduler_push(
        task_name=context.task_name,
        slot_key=context.slot_key,
        push_kind=push_kind,
        payload=payload_with_provenance,
        claimed_at=claimed_at,
        conn=conn,
        notification_id=notification.id if notification is not None else None,
        workflow_thread_id=notification.workflow_thread.id if notification is not None else None,
        delivery_status="claimed" if notification is not None else "skipped",
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

    if notification is None:
        return 0

    scheduler_push_store.mark_scheduler_push_attempt(
        task_name=context.task_name,
        slot_key=context.slot_key,
        push_kind=push_kind,
        attempted_at=utc_now(),
        conn=conn,
    )
    result = send_push_fn(push_kind, payload_with_provenance, context.settings, conn)
    recorded_payload = payload_with_provenance
    if result.delivery_reason is not None:
        recorded_payload = {
            **payload_with_provenance,
            "delivery_reason": result.delivery_reason,
        }
    scheduler_push_store.record_scheduler_push(
        task_name=context.task_name,
        slot_key=context.slot_key,
        push_kind=push_kind,
        payload=recorded_payload,
        push_count=result.push_count,
        completed_at=utc_now(),
        conn=conn,
        notification_id=notification.id,
        workflow_thread_id=notification.workflow_thread.id,
        delivery_status=result.delivery_status,
    )
    return result.push_count


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
