"""Scheduler review-task implementations.

Purpose:
    Implement the scheduler-owned daily and weekly review tasks behind the
    public `cloop.scheduler` facade.

Responsibilities:
    - Compute daily and weekly review cohorts
    - Build review-generated payloads for events and pushes
    - Emit one deduped review event/push per scheduler slot

Scope:
    - Review-task payload shaping and side effects only

Non-scope:
    - Slot claiming or runtime orchestration
    - Due-soon, stale-rescue, or webhook tasks

Usage:
    - Imported by the scheduler facade and runtime dispatch helpers

Invariants/Assumptions:
    - Review tasks emit at most one `review_generated` event per slot
    - Push failures are logged but do not fail an otherwise successful review task
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..loops.models import LoopEventType, utc_now
from ..loops.review import compute_review_cohorts
from ..push_sender import send_scheduler_push
from ..settings import Settings
from .cadence import resolved_context
from .models import SchedulerPushSender, SchedulerRunContext
from .side_effects import emit_scheduler_event, send_scheduler_push_once

logger = logging.getLogger(__name__)


def _build_review_payload(
    *, review_type: str, cohorts: list[Any], generated_at_utc: str
) -> dict[str, Any]:
    """Convert computed cohorts into the scheduler review payload shape."""
    return {
        "review_type": review_type,
        "cohorts": [
            {
                "cohort": cohort.cohort.value,
                "count": cohort.count,
                "loop_ids": [item["id"] for item in cohort.items],
            }
            for cohort in cohorts
        ],
        "total_items": sum(cohort.count for cohort in cohorts),
        "generated_at_utc": generated_at_utc,
    }


async def run_daily_review(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Generate one daily review payload and emit exactly one deduped event/push."""
    from ..loops.models import format_utc_datetime

    resolved = resolved_context(context, task_name="daily_review", settings=settings)
    result = compute_review_cohorts(
        settings=settings,
        now_utc=utc_now(),
        conn=conn,
        include_daily=True,
        include_weekly=False,
        limit_per_cohort=50,
    )
    payload = _build_review_payload(
        review_type="daily",
        cohorts=result.daily,
        generated_at_utc=format_utc_datetime(utc_now()),
    )
    event_id = emit_scheduler_event(
        LoopEventType.REVIEW_GENERATED,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        send_scheduler_push_once(
            push_kind="review_generated",
            payload=payload,
            context=resolved,
            conn=conn,
            send_push_fn=send_push_fn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", type(exc).__name__)
    return {"event_id": event_id, **payload}


async def run_weekly_review(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Generate one weekly review payload and emit exactly one deduped event/push."""
    from ..loops.models import format_utc_datetime

    resolved = resolved_context(context, task_name="weekly_review", settings=settings)
    result = compute_review_cohorts(
        settings=settings,
        now_utc=utc_now(),
        conn=conn,
        include_daily=False,
        include_weekly=True,
        limit_per_cohort=100,
    )
    payload = _build_review_payload(
        review_type="weekly",
        cohorts=result.weekly,
        generated_at_utc=format_utc_datetime(utc_now()),
    )
    event_id = emit_scheduler_event(
        LoopEventType.REVIEW_GENERATED,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        send_scheduler_push_once(
            push_kind="review_generated",
            payload=payload,
            context=resolved,
            conn=conn,
            send_push_fn=send_push_fn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", type(exc).__name__)
    return {"event_id": event_id, **payload}
