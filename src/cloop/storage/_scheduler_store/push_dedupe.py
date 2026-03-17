"""Scheduler push-dedupe persistence.

Purpose:
    Own at-most-once push reservation and delivery bookkeeping for scheduler
    task slots.

Responsibilities:
    - Reserve one push marker before external send
    - Record sent payload metadata and push counts
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
from typing import Any

from ._shared import dump_optional_json, iso_utc


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
    payload_json = dump_optional_json(payload)
    assert payload_json is not None

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
        (payload_json, push_count, iso_utc(sent_at), task_name, slot_key, push_kind),
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
        (task_name, slot_key, push_kind, payload_json, push_count, iso_utc(sent_at)),
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
    payload_json = dump_optional_json(payload)
    assert payload_json is not None

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
        (task_name, slot_key, push_kind, payload_json, 0, iso_utc(claimed_at)),
    )
    conn.commit()
    return cursor.rowcount == 1


__all__ = [
    "claim_scheduler_push",
    "record_scheduler_push",
]
