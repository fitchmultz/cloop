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
    from .push import service as push_service

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

    # Send push notification to subscribed clients
    if payload["total_items"] > 0:
        message = push_service.build_push_payload_for_scheduler_event(
            event_type="review_generated", payload=payload
        )
        push_service.send_to_all(message=message, conn=conn, settings=settings)

    return {"event_id": event_id, **payload}


async def run_weekly_review(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Generate weekly review cohorts and emit event."""
    from .loops.models import format_utc_datetime
    from .push import service as push_service

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

    # Send push notification to subscribed clients
    if payload["total_items"] > 0:
        message = push_service.build_push_payload_for_scheduler_event(
            event_type="review_generated", payload=payload
        )
        push_service.send_to_all(message=message, conn=conn, settings=settings)

    return {"event_id": event_id, **payload}


async def run_due_soon_nudge(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Find loops due soon without next_action and emit nudge event."""
    from datetime import timedelta

    from .loops.models import format_utc_datetime
    from .push import service as push_service

    now = utc_now()
    due_soon_cutoff = format_utc_datetime(now + timedelta(hours=settings.review_due_soon_hours))
    now_str = format_utc_datetime(now)

    rows = conn.execute(
        """SELECT id, title, due_at_utc FROM loops
           WHERE due_at_utc IS NOT NULL
             AND due_at_utc > ?
             AND due_at_utc <= ?
             AND next_action IS NULL
             AND status IN ('inbox', 'actionable', 'scheduled')
           ORDER BY due_at_utc ASC
           LIMIT 50
        """,
        (now_str, due_soon_cutoff),
    ).fetchall()

    loop_ids = [row["id"] for row in rows]

    if not loop_ids:
        return {"nudged": 0, "loop_ids": []}

    payload = {
        "nudge_type": "due_soon",
        "loop_ids": loop_ids,
        "details": [
            {"id": r["id"], "title": r["title"], "due_at_utc": r["due_at_utc"]} for r in rows
        ],
        "generated_at_utc": format_utc_datetime(now),
    }

    event_id = _emit_scheduler_event(LoopEventType.NUDGE_DUE_SOON, payload, conn)
    logger.info(f"Due-soon nudge: {len(loop_ids)} loops")

    # Send push notification to subscribed clients
    message = push_service.build_push_payload_for_scheduler_event(
        event_type="nudge_due_soon", payload=payload
    )
    push_service.send_to_all(message=message, conn=conn, settings=settings)

    return {"event_id": event_id, "nudged": len(loop_ids), **payload}


async def run_stale_rescue(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Find stale loops and emit rescue nudge event."""
    from datetime import timedelta

    from .loops.models import format_utc_datetime
    from .push import service as push_service

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

    # Send push notification to subscribed clients
    message = push_service.build_push_payload_for_scheduler_event(
        event_type="nudge_stale", payload=payload
    )
    push_service.send_to_all(message=message, conn=conn, settings=settings)

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
