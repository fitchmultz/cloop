"""Background scheduler for proactive assistant routines.

Purpose:
    Run periodic tasks for daily/weekly review generation, due-soon nudges,
    and stale-loop rescue without requiring manual polling.

Responsibilities:
    - Manage scheduler lifecycle (start/stop)
    - Execute periodic jobs with idempotent SQLite-backed state
    - Emit events for SSE consumption

Non-scope:
    - HTTP endpoint handling (see routes/)
    - Review computation logic (see loops/review.py)
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from . import db
from .loops.models import LoopEventType, utc_now
from .loops.review import compute_review_cohorts
from .settings import Settings

logger = logging.getLogger(__name__)

SCHEDULER_TASKS = {
    "daily_review",
    "weekly_review",
    "due_soon_nudge",
    "stale_rescue",
}


def _get_last_run(task_name: str, conn: sqlite3.Connection) -> datetime | None:
    """Get last run time for a scheduler task."""
    row = conn.execute(
        "SELECT last_run_at FROM scheduler_runs WHERE task_name = ?",
        (task_name,),
    ).fetchone()
    if row is None:
        return None
    return datetime.fromisoformat(row["last_run_at"])


def _record_run(
    task_name: str,
    result: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Record a successful scheduler run."""
    now = utc_now()
    conn.execute(
        """INSERT INTO scheduler_runs (task_name, last_run_at, last_result_json, runs_count)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(task_name) DO UPDATE SET
               last_run_at = excluded.last_run_at,
               last_result_json = excluded.last_result_json,
               runs_count = runs_count + 1
        """,
        (task_name, now.isoformat(), json.dumps(result)),
    )
    conn.commit()


def _should_run(
    task_name: str,
    interval_hours: float,
    conn: sqlite3.Connection,
) -> bool:
    """Check if enough time has elapsed since last run."""
    last_run = _get_last_run(task_name, conn)
    if last_run is None:
        return True
    elapsed = (utc_now() - last_run).total_seconds() / 3600
    return elapsed >= interval_hours


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
           VALUES (0, ?, ?, ?)
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

    return {"event_id": event_id, **payload}


async def run_due_soon_nudge(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Find loops due soon without next_action and emit escalating nudge events."""
    from datetime import timedelta

    from .loops.models import format_utc_datetime, parse_utc_datetime
    from .loops.repo import get_nudge_states_batch, upsert_nudge_state

    now = utc_now()
    due_soon_cutoff = format_utc_datetime(now + timedelta(hours=settings.review_due_soon_hours))

    # Find due-soon and overdue loops without next_action
    # Include overdue loops (due_at_utc <= now) for escalation
    rows = conn.execute(
        """SELECT id, title, due_at_utc FROM loops
           WHERE due_at_utc IS NOT NULL
             AND due_at_utc <= ?
             AND next_action IS NULL
             AND status IN ('inbox', 'actionable', 'scheduled')
           ORDER BY due_at_utc ASC
           LIMIT 50
        """,
        (due_soon_cutoff,),
    ).fetchall()

    loop_ids = [row["id"] for row in rows]

    if not loop_ids:
        return {"nudged": 0, "loop_ids": [], "escalation_summary": {}}

    # Fetch existing nudge states
    existing_states = get_nudge_states_batch(
        loop_ids=loop_ids,
        nudge_type="due_soon",
        conn=conn,
    )

    # Build details with escalation info
    details = []
    escalation_summary: dict[int, int] = {}  # level -> count

    for row in rows:
        loop_id = row["id"]
        state = existing_states.get(loop_id)
        due_at = parse_utc_datetime(row["due_at_utc"]) if row["due_at_utc"] else now
        hours_until_due = (due_at - now).total_seconds() / 3600
        is_overdue = hours_until_due < 0

        # Calculate escalation
        if state is None:
            nudge_count = 1
            # First nudge: overdue loops start at level 2
            if is_overdue:
                escalation_level = 2
            else:
                escalation_level = 0
        else:
            nudge_count = state.nudge_count + 1
            # Escalate based on count and overdue status
            if is_overdue:
                escalation_level = min(3, max(state.escalation_level, 2) + (nudge_count // 2))
            elif nudge_count >= 4:
                escalation_level = min(3, 2)
            elif nudge_count >= 2:
                escalation_level = min(3, 1)
            else:
                escalation_level = state.escalation_level

        # Track escalation summary
        escalation_summary[escalation_level] = escalation_summary.get(escalation_level, 0) + 1

        details.append(
            {
                "id": loop_id,
                "title": row["title"],
                "due_at_utc": row["due_at_utc"],
                "escalation_level": escalation_level,
                "nudge_count": nudge_count,
                "is_overdue": is_overdue,
            }
        )

    payload = {
        "nudge_type": "due_soon",
        "loop_ids": loop_ids,
        "details": details,
        "escalation_summary": escalation_summary,
        "generated_at_utc": format_utc_datetime(now),
    }

    event_id = _emit_scheduler_event(LoopEventType.NUDGE_DUE_SOON, payload, conn)

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

    logger.info(f"Due-soon nudge: {len(loop_ids)} loops, escalation levels: {escalation_summary}")

    return {"event_id": event_id, "nudged": len(loop_ids), **payload}


async def run_stale_rescue(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Find stale loops and emit rescue nudge event."""
    from datetime import timedelta

    from .loops.models import format_utc_datetime

    now = utc_now()
    stale_cutoff = format_utc_datetime(now - timedelta(hours=settings.review_stale_hours))

    rows = conn.execute(
        """SELECT id, title, status, updated_at FROM loops
           WHERE status IN ('inbox', 'actionable', 'blocked', 'scheduled')
             AND updated_at < ?
           ORDER BY updated_at ASC
           LIMIT 100
        """,
        (stale_cutoff,),
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

    return {"event_id": event_id, "rescued": len(loop_ids), **payload}


async def scheduler_loop(settings: Settings) -> None:
    """Main scheduler loop that runs periodic tasks."""
    logger.info("Scheduler started")

    while True:
        try:
            with db.core_connection(settings) as conn:
                # Check and run each task if interval elapsed
                if _should_run(
                    "daily_review", settings.scheduler_daily_review_interval_hours, conn
                ):
                    await run_daily_review(settings, conn)
                    _record_run("daily_review", {"status": "ok"}, conn)

                if _should_run(
                    "weekly_review", settings.scheduler_weekly_review_interval_hours, conn
                ):
                    await run_weekly_review(settings, conn)
                    _record_run("weekly_review", {"status": "ok"}, conn)

                if _should_run(
                    "due_soon_nudge", settings.scheduler_due_soon_nudge_interval_hours, conn
                ):
                    await run_due_soon_nudge(settings, conn)
                    _record_run("due_soon_nudge", {"status": "ok"}, conn)

                if _should_run(
                    "stale_rescue", settings.scheduler_stale_rescue_interval_hours, conn
                ):
                    await run_stale_rescue(settings, conn)
                    _record_run("stale_rescue", {"status": "ok"}, conn)

            # Sleep for 1 minute before checking again
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Scheduler stopped")
            raise
        except Exception as e:
            logger.exception(f"Scheduler error: {e}")
            await asyncio.sleep(60)


_scheduler_task: asyncio.Task | None = None


def start_scheduler(settings: Settings) -> None:
    """Start the scheduler background task."""
    global _scheduler_task

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via configuration")
        return

    if _scheduler_task is not None and not _scheduler_task.done():
        logger.warning("Scheduler already running")
        return

    _scheduler_task = asyncio.create_task(scheduler_loop(settings))
    logger.info("Scheduler task created")


def stop_scheduler() -> None:
    """Stop the scheduler background task."""
    global _scheduler_task

    if _scheduler_task is not None and not _scheduler_task.done():
        _scheduler_task.cancel()
        _scheduler_task = None
        logger.info("Scheduler stop requested")
