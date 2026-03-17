"""Scheduler nudge-task implementations.

Purpose:
    Implement scheduler-owned due-soon and stale-rescue nudges behind the public
    `cloop.scheduler` facade.

Responsibilities:
    - Select candidate loops for due-soon and stale-rescue nudges
    - Compute due-soon escalation state, ranking, and bucket summaries
    - Emit one deduped event/push per slot and persist nudge state updates

Scope:
    - Due-soon and stale-rescue task logic only

Non-scope:
    - Scheduler slot claiming or runtime orchestration
    - Review-task or webhook-delivery behavior

Usage:
    - Imported by the scheduler facade and runtime dispatch helpers

Invariants/Assumptions:
    - Push failures are logged but do not fail successful nudge computation
    - Due-soon nudges persist state at most once per loop per scheduler slot
    - Stale-rescue tasks return an empty result when no stale loops qualify
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from datetime import timedelta
from typing import Any

from ..constants import MAX_ESCALATION_LEVEL, NUDGE_THRESHOLD_HIGH, NUDGE_THRESHOLD_LOW
from ..loops.due import effective_due_iso, effective_due_sql
from ..loops.models import LoopEventType, utc_now
from ..push_sender import send_scheduler_push
from ..settings import Settings
from .cadence import resolved_context
from .models import SchedulerPushSender, SchedulerRunContext
from .side_effects import (
    emit_scheduler_event,
    send_scheduler_push_once,
    upsert_nudge_state_for_slot,
)

logger = logging.getLogger(__name__)


async def run_due_soon_nudge(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Emit and persist one deduped due-soon nudge slot."""
    from ..loops import repo as loop_repo
    from ..loops.models import format_utc_datetime, parse_utc_datetime
    from ..loops.prioritization import PriorityWeights, bucketize, compute_priority_score
    from ..loops.repo import get_nudge_states_batch

    resolved = resolved_context(context, task_name="due_soon_nudge", settings=settings)
    now = utc_now()
    due_soon_cutoff = format_utc_datetime(now + timedelta(hours=settings.due_soon_hours))
    now_str = format_utc_datetime(now)
    effective_due_expr = effective_due_sql(table_alias="")
    rows = conn.execute(
        f"""SELECT id, title, due_at_utc, next_due_at_utc, urgency, importance,
                  time_minutes, activation_energy
           FROM loops
           WHERE {effective_due_expr} IS NOT NULL
             AND {effective_due_expr} <= ?
             AND next_action IS NULL
             AND status IN ('inbox', 'actionable', 'scheduled')
             AND (snooze_until_utc IS NULL OR snooze_until_utc <= ?)""",
        (due_soon_cutoff, now_str),
    ).fetchall()
    if not rows:
        return {"nudged": 0, "loop_ids": [], "escalation_summary": {}, "bucket_summary": {}}

    weights = PriorityWeights(
        due_weight=settings.priority_weight_due,
        urgency_weight=settings.priority_weight_urgency,
        importance_weight=settings.priority_weight_importance,
        time_penalty=settings.priority_weight_time_penalty,
        activation_penalty=settings.priority_weight_activation_penalty,
        blocked_penalty=settings.priority_weight_blocked_penalty,
    )
    scored_candidates = []
    for row in rows:
        loop_dict = dict(row)
        effective_due = effective_due_iso(row)
        loop_dict["due_at_utc"] = effective_due
        has_open_deps = loop_repo.has_open_dependencies(loop_id=row["id"], conn=conn)
        score = compute_priority_score(
            loop_dict,
            now_utc=now,
            w=weights,
            settings=settings,
            has_open_dependencies=has_open_deps,
        )
        bucket = bucketize(
            loop_dict,
            now_utc=now,
            settings=settings,
            has_open_dependencies=has_open_deps,
        )
        scored_candidates.append(
            {
                "row": row,
                "effective_due": effective_due,
                "score": score,
                "bucket": bucket,
            }
        )

    scored_candidates.sort(key=lambda item: item["score"], reverse=True)
    scored_candidates = scored_candidates[:50]
    loop_ids = [candidate["row"]["id"] for candidate in scored_candidates]
    existing_states = get_nudge_states_batch(loop_ids=loop_ids, nudge_type="due_soon", conn=conn)

    details = []
    escalation_summary: dict[int, int] = {}
    for candidate in scored_candidates:
        row = candidate["row"]
        loop_id = row["id"]
        state = existing_states.get(loop_id)
        effective_due = candidate["effective_due"]
        due_at = parse_utc_datetime(effective_due) if effective_due else now
        hours_until_due = (due_at - now).total_seconds() / 3600
        is_overdue = hours_until_due < 0
        if state is None:
            nudge_count = 1
            escalation_level = MAX_ESCALATION_LEVEL if is_overdue else 0
        else:
            nudge_count = state.nudge_count + 1
            if is_overdue:
                escalation_level = min(
                    MAX_ESCALATION_LEVEL + 1,
                    max(state.escalation_level, MAX_ESCALATION_LEVEL) + (nudge_count // 2),
                )
            elif nudge_count >= NUDGE_THRESHOLD_HIGH:
                escalation_level = min(MAX_ESCALATION_LEVEL + 1, MAX_ESCALATION_LEVEL)
            elif nudge_count >= NUDGE_THRESHOLD_LOW:
                escalation_level = min(MAX_ESCALATION_LEVEL + 1, 1)
            else:
                escalation_level = state.escalation_level
        escalation_summary[escalation_level] = escalation_summary.get(escalation_level, 0) + 1
        details.append(
            {
                "id": loop_id,
                "title": row["title"],
                "due_at_utc": row["due_at_utc"],
                "next_due_at_utc": row["next_due_at_utc"],
                "escalation_level": escalation_level,
                "nudge_count": nudge_count,
                "is_overdue": is_overdue,
                "priority_score": round(candidate["score"], 3),
                "bucket": candidate["bucket"],
            }
        )

    payload = {
        "nudge_type": "due_soon",
        "loop_ids": loop_ids,
        "details": details,
        "escalation_summary": escalation_summary,
        "bucket_summary": dict(Counter(candidate["bucket"] for candidate in scored_candidates)),
        "generated_at_utc": format_utc_datetime(now),
    }

    resolved.assert_active()
    event_id = emit_scheduler_event(
        LoopEventType.NUDGE_DUE_SOON,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        send_scheduler_push_once(
            push_kind="nudge_due_soon",
            payload=payload,
            context=resolved,
            conn=conn,
            send_push_fn=send_push_fn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", exc)
    for detail in details:
        upsert_nudge_state_for_slot(
            loop_id=detail["id"],
            nudge_type="due_soon",
            escalation_level=detail["escalation_level"],
            nudge_count=detail["nudge_count"],
            last_nudge_event_id=event_id,
            slot_key=resolved.slot_key,
            conn=conn,
        )
    conn.commit()
    return {"event_id": event_id, "nudged": len(loop_ids), **payload}


async def run_stale_rescue(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Emit one deduped stale-rescue scheduler slot."""
    from ..loops.models import format_utc_datetime

    resolved = resolved_context(context, task_name="stale_rescue", settings=settings)
    now = utc_now()
    stale_cutoff = format_utc_datetime(now - timedelta(hours=settings.review_stale_hours))
    now_str = format_utc_datetime(now)
    rows = conn.execute(
        """SELECT id, title, status, updated_at FROM loops
           WHERE status IN ('inbox', 'actionable', 'blocked', 'scheduled')
             AND updated_at < ?
             AND (snooze_until_utc IS NULL OR snooze_until_utc <= ?)
           ORDER BY updated_at ASC
           LIMIT 100""",
        (stale_cutoff, now_str),
    ).fetchall()
    loop_ids = [row["id"] for row in rows]
    if not loop_ids:
        return {"rescued": 0, "loop_ids": []}

    payload = {
        "nudge_type": "stale",
        "loop_ids": loop_ids,
        "details": [
            {
                "id": row["id"],
                "title": row["title"],
                "status": row["status"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        "generated_at_utc": format_utc_datetime(now),
    }
    event_id = emit_scheduler_event(
        LoopEventType.NUDGE_STALE,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        send_scheduler_push_once(
            push_kind="nudge_stale",
            payload=payload,
            context=resolved,
            conn=conn,
            send_push_fn=send_push_fn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", exc)
    return {"event_id": event_id, "rescued": len(loop_ids), **payload}
