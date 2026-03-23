"""Scheduler push-dedupe persistence.

Purpose:
    Own at-most-once push reservation and delivery bookkeeping for scheduler
    task slots.

Responsibilities:
    - Reserve one push marker before external send
    - Record send-attempt lifecycle and terminal delivery state
    - Persist canonical continuity provenance alongside scheduler push rows
    - Persist dedupe rows keyed by `(task_name, slot_key, push_kind)`

Scope:
    - Scheduler push-delivery persistence only

Usage:
    - Imported by scheduler side-effect helpers and the public scheduler
      storage facade

Invariants/Assumptions:
    - Push delivery rows are unique per `(task_name, slot_key, push_kind)`
    - Claiming a push marker happens before sending the external notification
    - Recording a push updates the existing reserved row when present

Non-scope:
    - External push sending
    - Scheduler task-run leasing or schedule eligibility
    - Event emission or payload construction
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Literal

from ..._scheduler.models import SchedulerPushDeliveryReason
from ._shared import dump_optional_json, iso_utc

SchedulerPushDeliveryStatus = Literal[
    "claimed",
    "attempted",
    "sent",
    "no_recipients",
    "skipped",
]


def record_scheduler_push(
    *,
    task_name: str,
    slot_key: str,
    push_kind: str,
    payload: dict[str, Any],
    push_count: int,
    completed_at: datetime,
    conn: sqlite3.Connection,
    notification_id: str | None = None,
    workflow_thread_id: str | None = None,
    delivery_status: Literal["sent", "no_recipients", "skipped"] | None = None,
    delivery_reason: SchedulerPushDeliveryReason | None = None,
) -> bool:
    """Record a scheduler push terminal outcome once per task slot and push kind."""
    payload_json = dump_optional_json(payload)
    assert payload_json is not None

    final_status = delivery_status
    if final_status is None:
        final_status = "sent" if push_count > 0 else "no_recipients"

    cursor = conn.execute(
        """
        UPDATE scheduler_push_deliveries
        SET payload_json = ?,
            notification_id = ?,
            workflow_thread_id = ?,
            send_completed_at = ?,
            delivery_status = ?,
            delivery_reason = ?,
            push_count = ?
        WHERE task_name = ?
          AND slot_key = ?
          AND push_kind = ?
        """,
        (
            payload_json,
            notification_id,
            workflow_thread_id,
            iso_utc(completed_at),
            final_status,
            delivery_reason,
            push_count,
            task_name,
            slot_key,
            push_kind,
        ),
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
            notification_id,
            workflow_thread_id,
            claimed_at,
            send_started_at,
            send_completed_at,
            delivery_status,
            delivery_reason,
            push_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_name,
            slot_key,
            push_kind,
            payload_json,
            notification_id,
            workflow_thread_id,
            iso_utc(completed_at),
            iso_utc(completed_at) if final_status in {"sent", "no_recipients"} else None,
            iso_utc(completed_at),
            final_status,
            delivery_reason,
            push_count,
        ),
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
    notification_id: str | None = None,
    workflow_thread_id: str | None = None,
    delivery_status: Literal["claimed", "skipped"] = "claimed",
) -> bool:
    """Reserve one scheduler push marker before sending the external notification."""
    payload_json = dump_optional_json(payload)
    assert payload_json is not None

    completed_at = iso_utc(claimed_at) if delivery_status == "skipped" else None
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO scheduler_push_deliveries (
            task_name,
            slot_key,
            push_kind,
            payload_json,
            notification_id,
            workflow_thread_id,
            claimed_at,
            send_started_at,
            send_completed_at,
            delivery_status,
            push_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_name,
            slot_key,
            push_kind,
            payload_json,
            notification_id,
            workflow_thread_id,
            iso_utc(claimed_at),
            None,
            completed_at,
            delivery_status,
            0,
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


def mark_scheduler_push_attempt(
    *,
    task_name: str,
    slot_key: str,
    push_kind: str,
    attempted_at: datetime,
    conn: sqlite3.Connection,
) -> bool:
    """Mark a claimed scheduler push row as actively attempting delivery."""
    cursor = conn.execute(
        """
        UPDATE scheduler_push_deliveries
        SET send_started_at = ?,
            delivery_status = 'attempted'
        WHERE task_name = ?
          AND slot_key = ?
          AND push_kind = ?
          AND delivery_status = 'claimed'
        """,
        (iso_utc(attempted_at), task_name, slot_key, push_kind),
    )
    conn.commit()
    return cursor.rowcount == 1


__all__ = [
    "claim_scheduler_push",
    "mark_scheduler_push_attempt",
    "record_scheduler_push",
]
