"""Dedicated scheduler runtime for proactive assistant routines.

Purpose:
    Run periodic tasks for daily/weekly review generation, due-soon nudges,
    and stale-loop rescue without requiring manual polling.

Responsibilities:
    - Execute periodic jobs with SQLite-backed leases and run-state
    - Expose a dedicated scheduler process entrypoint
    - Emit events for SSE consumption

Non-scope:
    - HTTP application lifespan management
    - Review computation logic (see loops/review.py)
"""

import argparse
import asyncio
import json
import logging
import sqlite3
import uuid
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from typing import Any

from . import db
from .constants import MAX_ESCALATION_LEVEL, NUDGE_THRESHOLD_HIGH, NUDGE_THRESHOLD_LOW
from .loops.models import LoopEventType, utc_now
from .loops.review import compute_review_cohorts
from .push_sender import send_scheduler_push
from .settings import Settings, get_settings
from .storage import scheduler_store

logger = logging.getLogger(__name__)

SCHEDULER_TASKS = (
    "daily_review",
    "weekly_review",
    "due_soon_nudge",
    "stale_rescue",
)


def _emit_scheduler_event(
    event_type: LoopEventType,
    payload: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Emit a scheduler event to loop_events table.

    Returns the event ID for SSE streaming.
    """
    now = utc_now()
    cursor = conn.execute(
        """INSERT INTO loop_events (loop_id, event_type, payload_json, created_at)
           VALUES (NULL, ?, ?, ?)
        """,
        (event_type.value, json.dumps(payload), now.isoformat()),
    )
    conn.commit()
    return cursor.lastrowid or 0


async def run_daily_review(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Generate daily review cohorts and emit event."""
    from .loops.models import format_utc_datetime

    result = compute_review_cohorts(
        settings=settings,
        now_utc=utc_now(),
        conn=conn,
        include_daily=True,
        include_weekly=False,
        limit_per_cohort=50,
    )

    payload = {
        "review_type": "daily",
        "cohorts": [
            {
                "cohort": c.cohort.value,
                "count": c.count,
                "loop_ids": [item["id"] for item in c.items],
            }
            for c in result.daily
        ],
        "total_items": sum(c.count for c in result.daily),
        "generated_at_utc": format_utc_datetime(utc_now()),
    }

    event_id = _emit_scheduler_event(LoopEventType.REVIEW_GENERATED, payload, conn)
    logger.info(
        f"Daily review generated: {payload['total_items']} items across {len(result.daily)} cohorts"
    )

    # Send push notification
    try:
        send_scheduler_push("review_generated", payload, settings, conn)
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")

    return {"event_id": event_id, **payload}


async def run_weekly_review(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Generate weekly review cohorts and emit event."""
    from .loops.models import format_utc_datetime

    result = compute_review_cohorts(
        settings=settings,
        now_utc=utc_now(),
        conn=conn,
        include_daily=False,
        include_weekly=True,
        limit_per_cohort=100,
    )

    payload = {
        "review_type": "weekly",
        "cohorts": [
            {
                "cohort": c.cohort.value,
                "count": c.count,
                "loop_ids": [item["id"] for item in c.items],
            }
            for c in result.weekly
        ],
        "total_items": sum(c.count for c in result.weekly),
        "generated_at_utc": format_utc_datetime(utc_now()),
    }

    event_id = _emit_scheduler_event(LoopEventType.REVIEW_GENERATED, payload, conn)
    cohort_count = len(result.weekly)
    logger.info(
        f"Weekly review generated: {payload['total_items']} items across {cohort_count} cohorts"
    )

    # Send push notification
    try:
        send_scheduler_push("review_generated", payload, settings, conn)
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")

    return {"event_id": event_id, **payload}


async def run_due_soon_nudge(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Find loops due soon without next_action and emit escalating nudge events."""
    from datetime import timedelta

    from .loops import repo as loop_repo
    from .loops.models import format_utc_datetime, parse_utc_datetime
    from .loops.prioritization import PriorityWeights, bucketize, compute_priority_score
    from .loops.repo import get_nudge_states_batch, upsert_nudge_state

    now = utc_now()
    due_soon_cutoff = format_utc_datetime(now + timedelta(hours=settings.due_soon_hours))
    now_str = format_utc_datetime(now)

    # Find due-soon and overdue loops without next_action
    # Include overdue loops (due_at_utc <= now) for escalation
    # Exclude snoozed loops (snooze_until_utc in the future)
    # Use COALESCE to include recurring loops with only next_due_at_utc
    rows = conn.execute(
        """SELECT id, title, due_at_utc, next_due_at_utc, urgency, importance,
                  time_minutes, activation_energy
           FROM loops
           WHERE COALESCE(due_at_utc, next_due_at_utc) IS NOT NULL
             AND COALESCE(due_at_utc, next_due_at_utc) <= ?
             AND next_action IS NULL
             AND status IN ('inbox', 'actionable', 'scheduled')
             AND (snooze_until_utc IS NULL OR snooze_until_utc <= ?)
        """,
        (due_soon_cutoff, now_str),
    ).fetchall()

    if not rows:
        return {"nudged": 0, "loop_ids": [], "escalation_summary": {}, "bucket_summary": {}}

    # Build priority weights from settings
    weights = PriorityWeights(
        due_weight=settings.priority_weight_due,
        urgency_weight=settings.priority_weight_urgency,
        importance_weight=settings.priority_weight_importance,
        time_penalty=settings.priority_weight_time_penalty,
        activation_penalty=settings.priority_weight_activation_penalty,
        blocked_penalty=settings.priority_weight_blocked_penalty,
    )

    # Score each candidate
    scored_candidates = []
    for row in rows:
        loop_dict = dict(row)
        # Compute effective due date: prefer due_at_utc, fall back to next_due_at_utc
        effective_due = row["due_at_utc"] or row["next_due_at_utc"]
        loop_dict["due_at_utc"] = effective_due  # Override for scoring/bucketing
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
                "has_open_deps": has_open_deps,
            }
        )

    # Sort by score descending and truncate to top 50
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    scored_candidates = scored_candidates[:50]

    loop_ids = [c["row"]["id"] for c in scored_candidates]

    # Fetch existing nudge states
    existing_states = get_nudge_states_batch(
        loop_ids=loop_ids,
        nudge_type="due_soon",
        conn=conn,
    )

    # Build details with escalation info
    details = []
    escalation_summary: dict[int, int] = {}  # level -> count

    for candidate in scored_candidates:
        row = candidate["row"]
        loop_id = row["id"]
        state = existing_states.get(loop_id)
        effective_due = candidate["effective_due"]
        due_at = parse_utc_datetime(effective_due) if effective_due else now
        hours_until_due = (due_at - now).total_seconds() / 3600
        is_overdue = hours_until_due < 0

        # Calculate escalation
        if state is None:
            nudge_count = 1
            # First nudge: overdue loops start at max escalation
            if is_overdue:
                escalation_level = MAX_ESCALATION_LEVEL
            else:
                escalation_level = 0
        else:
            nudge_count = state.nudge_count + 1
            # Escalate based on count and overdue status
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

        # Track escalation summary
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

    bucket_summary = dict(Counter(c["bucket"] for c in scored_candidates))

    payload = {
        "nudge_type": "due_soon",
        "loop_ids": loop_ids,
        "details": details,
        "escalation_summary": escalation_summary,
        "bucket_summary": bucket_summary,
        "generated_at_utc": format_utc_datetime(now),
    }

    event_id = _emit_scheduler_event(LoopEventType.NUDGE_DUE_SOON, payload, conn)

    # Send push notification
    try:
        send_scheduler_push("nudge_due_soon", payload, settings, conn)
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")

    # Persist nudge states
    for detail in details:
        upsert_nudge_state(
            loop_id=detail["id"],
            nudge_type="due_soon",
            escalation_level=detail["escalation_level"],
            nudge_count=detail["nudge_count"],
            last_nudge_event_id=event_id,
            conn=conn,
        )
    conn.commit()

    logger.info(
        f"Due-soon nudge: {len(loop_ids)} loops, buckets: {bucket_summary}, "
        f"escalation: {escalation_summary}"
    )

    return {"event_id": event_id, "nudged": len(loop_ids), **payload}


async def run_stale_rescue(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Find stale loops and emit rescue nudge event."""
    from datetime import timedelta

    from .loops.models import format_utc_datetime

    now = utc_now()
    stale_cutoff = format_utc_datetime(now - timedelta(hours=settings.review_stale_hours))
    now_str = format_utc_datetime(now)

    # Find stale loops, excluding snoozed loops
    rows = conn.execute(
        """SELECT id, title, status, updated_at FROM loops
           WHERE status IN ('inbox', 'actionable', 'blocked', 'scheduled')
             AND updated_at < ?
             AND (snooze_until_utc IS NULL OR snooze_until_utc <= ?)
           ORDER BY updated_at ASC
           LIMIT 100
        """,
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
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ],
        "generated_at_utc": format_utc_datetime(now),
    }

    event_id = _emit_scheduler_event(LoopEventType.NUDGE_STALE, payload, conn)
    logger.info(f"Stale rescue nudge: {len(loop_ids)} loops")

    # Send push notification
    try:
        send_scheduler_push("nudge_stale", payload, settings, conn)
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")

    return {"event_id": event_id, "rescued": len(loop_ids), **payload}


def _task_interval_hours(task_name: str, settings: Settings) -> float:
    if task_name == "daily_review":
        return settings.scheduler_daily_review_interval_hours
    if task_name == "weekly_review":
        return settings.scheduler_weekly_review_interval_hours
    if task_name == "due_soon_nudge":
        return settings.scheduler_due_soon_nudge_interval_hours
    if task_name == "stale_rescue":
        return settings.scheduler_stale_rescue_interval_hours
    raise ValueError(f"Unknown scheduler task: {task_name}")


def _task_runner(task_name: str):
    if task_name == "daily_review":
        return run_daily_review
    if task_name == "weekly_review":
        return run_weekly_review
    if task_name == "due_soon_nudge":
        return run_due_soon_nudge
    if task_name == "stale_rescue":
        return run_stale_rescue
    raise ValueError(f"Unknown scheduler task: {task_name}")


async def run_scheduler_task(
    *,
    task_name: str,
    settings: Settings,
    owner_token: str,
) -> dict[str, Any] | None:
    """Run one scheduler task if this process acquires the lease and it is due."""
    with db.core_connection(settings) as conn:
        if not scheduler_store.acquire_task_lease(
            task_name=task_name,
            owner_token=owner_token,
            lease_seconds=settings.scheduler_lease_seconds,
            conn=conn,
        ):
            return None
        started_at = utc_now()
        try:
            if not scheduler_store.task_due(task_name=task_name, now_utc=started_at, conn=conn):
                return None
            runner = _task_runner(task_name)
            result = await runner(settings, conn)
            finished_at = utc_now()
            interval_hours = _task_interval_hours(task_name, settings)
            next_due_at = started_at + timedelta(hours=interval_hours)
            scheduler_store.update_task_run_state(
                task_name=task_name,
                started_at=started_at,
                finished_at=finished_at,
                success=True,
                next_due_at=next_due_at,
                result=result,
                error=None,
                conn=conn,
            )
            return result
        except Exception as exc:
            finished_at = utc_now()
            interval_hours = _task_interval_hours(task_name, settings)
            next_due_at = started_at + timedelta(hours=interval_hours)
            scheduler_store.update_task_run_state(
                task_name=task_name,
                started_at=started_at,
                finished_at=finished_at,
                success=False,
                next_due_at=next_due_at,
                result=None,
                error=str(exc),
                conn=conn,
            )
            raise
        finally:
            scheduler_store.release_task_lease(
                task_name=task_name,
                owner_token=owner_token,
                conn=conn,
            )


async def run_scheduler_once(
    settings: Settings, *, owner_token: str | None = None
) -> dict[str, Any]:
    """Run one scheduler polling cycle."""
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via configuration")
        return {}
    resolved_owner = owner_token or f"scheduler-{uuid.uuid4()}"
    results: dict[str, Any] = {}
    for task_name in SCHEDULER_TASKS:
        result = await run_scheduler_task(
            task_name=task_name,
            settings=settings,
            owner_token=f"{resolved_owner}:{task_name}",
        )
        if result is not None:
            results[task_name] = result
    return results


async def scheduler_loop(settings: Settings) -> None:
    """Run the dedicated scheduler process until cancelled."""
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via configuration")
        return
    logger.info("Dedicated scheduler started")
    owner_token = f"scheduler-{uuid.uuid4()}"
    while True:
        try:
            await run_scheduler_once(settings, owner_token=owner_token)
            await asyncio.sleep(settings.scheduler_poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Scheduler stopped")
            raise
        except Exception as exc:
            logger.exception("Scheduler error: %s", exc)
            await asyncio.sleep(settings.scheduler_poll_interval_seconds)


def build_scheduler_parser() -> argparse.ArgumentParser:
    """Build the dedicated scheduler CLI parser."""
    parser = argparse.ArgumentParser(
        prog="cloop-scheduler",
        description="Run the dedicated Cloop scheduler process.",
        epilog="""
Examples:
  cloop-scheduler
  cloop-scheduler --once
  cloop-scheduler --poll-seconds 30

Exit codes:
  0  success
  1  scheduler execution failed
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one polling cycle and exit.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=None,
        help="Override scheduler poll interval for this process.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the dedicated scheduler process."""
    parser = build_scheduler_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.poll_seconds is not None:
        settings = replace(settings, scheduler_poll_interval_seconds=args.poll_seconds)
    db.init_databases(settings)
    try:
        if args.once:
            asyncio.run(run_scheduler_once(settings))
        else:
            asyncio.run(scheduler_loop(settings))
    except Exception:
        logger.exception("Scheduler process failed")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
