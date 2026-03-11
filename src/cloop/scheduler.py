"""Dedicated scheduler runtime for proactive assistant routines.

Purpose:
    Run periodic reviews, nudges, stale rescue, and webhook delivery from one
    dedicated process using deterministic scheduler slots.

Responsibilities:
    - Claim one logical run per task slot and heartbeat ownership
    - Deduplicate scheduler-owned loop events and push notifications
    - Execute webhook retry processing inside the dedicated scheduler process
    - Expose the `cloop-scheduler` CLI entrypoint

Non-scope:
    - FastAPI application lifespan management
    - General route handling
    - Loop business logic outside scheduler-owned orchestration
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine

from . import db
from .constants import MAX_ESCALATION_LEVEL, NUDGE_THRESHOLD_HIGH, NUDGE_THRESHOLD_LOW
from .loops.due import effective_due_iso, effective_due_sql
from .loops.models import LoopEventType, utc_now
from .loops.review import compute_review_cohorts
from .push_sender import send_scheduler_push
from .settings import Settings, get_settings
from .storage import scheduler_store
from .webhooks.service import process_pending_deliveries

logger = logging.getLogger(__name__)

SCHEDULER_TASKS = (
    "daily_review",
    "weekly_review",
    "due_soon_nudge",
    "stale_rescue",
    "webhook_delivery",
)


@dataclass(slots=True)
class SchedulerRunContext:
    """Runtime state for one claimed scheduler slot."""

    task_name: str
    slot_key: str
    owner_token: str
    settings: Settings
    lease_lost: asyncio.Event

    def assert_active(self) -> None:
        """Abort immediately if this run lost ownership of its slot."""
        if self.lease_lost.is_set():
            raise RuntimeError(f"scheduler_lease_lost:{self.task_name}:{self.slot_key}")


def _resolved_context(
    context: SchedulerRunContext | None,
    *,
    task_name: str,
    settings: Settings,
) -> SchedulerRunContext:
    """Return the provided scheduler context or a one-shot context for direct calls."""
    if context is not None:
        return context
    return SchedulerRunContext(
        task_name=task_name,
        slot_key=f"adhoc-{uuid.uuid4()}",
        owner_token="adhoc",
        settings=settings,
        lease_lost=asyncio.Event(),
    )


def _slot_interval_seconds(task_name: str, settings: Settings) -> int:
    if task_name == "daily_review":
        return int(settings.scheduler_daily_review_interval_hours * 3600)
    if task_name == "weekly_review":
        return int(settings.scheduler_weekly_review_interval_hours * 3600)
    if task_name == "due_soon_nudge":
        return int(settings.scheduler_due_soon_nudge_interval_hours * 3600)
    if task_name == "stale_rescue":
        return int(settings.scheduler_stale_rescue_interval_hours * 3600)
    if task_name == "webhook_delivery":
        return max(1, int(settings.scheduler_poll_interval_seconds))
    raise ValueError(f"Unknown scheduler task: {task_name}")


def _slot_key(task_name: str, now_utc: datetime, settings: Settings) -> str:
    if task_name == "daily_review":
        return now_utc.date().isoformat()
    if task_name == "weekly_review":
        week_start = (now_utc - timedelta(days=now_utc.weekday())).date()
        return week_start.isoformat()
    if task_name in {"due_soon_nudge", "stale_rescue", "webhook_delivery"}:
        interval_seconds = _slot_interval_seconds(task_name, settings)
        slot_number = int(now_utc.timestamp()) // interval_seconds
        return str(slot_number)
    raise ValueError(f"Unknown scheduler task: {task_name}")


def _next_due_at(
    task_name: str,
    started_at: datetime,
    settings: Settings,
    *,
    success: bool,
) -> datetime:
    if not success:
        return started_at + timedelta(seconds=settings.scheduler_poll_interval_seconds)
    return started_at + timedelta(seconds=_slot_interval_seconds(task_name, settings))


async def _heartbeat_scheduler_run(
    *,
    context: SchedulerRunContext,
    runner_task: asyncio.Task[Any],
) -> None:
    """Renew the owned slot lease and cancel the runner on lease loss."""
    interval_seconds = max(1.0, context.settings.scheduler_lease_seconds / 3)
    while not context.lease_lost.is_set():
        await asyncio.sleep(interval_seconds)
        with db.core_connection(context.settings) as heartbeat_conn:
            renewed = scheduler_store.heartbeat_task_run(
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


def _emit_scheduler_event(
    event_type: LoopEventType,
    payload: dict[str, Any],
    *,
    context: SchedulerRunContext,
    conn: sqlite3.Connection,
) -> int:
    """Insert one scheduler-owned loop event per `(task, slot, event_type)`."""
    context.assert_active()
    cursor = conn.execute(
        """
        INSERT INTO loop_events (
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
    if cursor.lastrowid is not None:
        conn.commit()
        return int(cursor.lastrowid)
    if cursor.rowcount == 1:
        conn.commit()
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)

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
    return int(row["id"])


def _send_scheduler_push_once(
    *,
    push_kind: str,
    payload: dict[str, Any],
    context: SchedulerRunContext,
    conn: sqlite3.Connection,
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

    push_count = send_scheduler_push(push_kind, payload, context.settings, conn)
    scheduler_store.record_scheduler_push(
        task_name=context.task_name,
        slot_key=context.slot_key,
        push_kind=push_kind,
        payload=payload,
        push_count=push_count,
        sent_at=utc_now(),
        conn=conn,
    )
    return push_count


def _upsert_nudge_state_for_slot(
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


async def run_daily_review(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Generate one daily review payload and emit exactly one deduped event/push."""
    from .loops.models import format_utc_datetime

    resolved = _resolved_context(context, task_name="daily_review", settings=settings)

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
    event_id = _emit_scheduler_event(
        LoopEventType.REVIEW_GENERATED,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        _send_scheduler_push_once(
            push_kind="review_generated",
            payload=payload,
            context=resolved,
            conn=conn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", exc)
    return {"event_id": event_id, **payload}


async def run_weekly_review(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Generate one weekly review payload and emit exactly one deduped event/push."""
    from .loops.models import format_utc_datetime

    resolved = _resolved_context(context, task_name="weekly_review", settings=settings)

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
    event_id = _emit_scheduler_event(
        LoopEventType.REVIEW_GENERATED,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        _send_scheduler_push_once(
            push_kind="review_generated",
            payload=payload,
            context=resolved,
            conn=conn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", exc)
    return {"event_id": event_id, **payload}


async def run_due_soon_nudge(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Emit and persist one deduped due-soon nudge slot."""
    from .loops import repo as loop_repo
    from .loops.models import format_utc_datetime, parse_utc_datetime
    from .loops.prioritization import PriorityWeights, bucketize, compute_priority_score
    from .loops.repo import get_nudge_states_batch

    resolved = _resolved_context(context, task_name="due_soon_nudge", settings=settings)
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
        "bucket_summary": dict(Counter(c["bucket"] for c in scored_candidates)),
        "generated_at_utc": format_utc_datetime(now),
    }

    resolved.assert_active()
    event_id = _emit_scheduler_event(
        LoopEventType.NUDGE_DUE_SOON,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        _send_scheduler_push_once(
            push_kind="nudge_due_soon",
            payload=payload,
            context=resolved,
            conn=conn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", exc)
    for detail in details:
        _upsert_nudge_state_for_slot(
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
) -> dict[str, Any]:
    """Emit one deduped stale-rescue scheduler slot."""
    from .loops.models import format_utc_datetime

    resolved = _resolved_context(context, task_name="stale_rescue", settings=settings)

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
    event_id = _emit_scheduler_event(
        LoopEventType.NUDGE_STALE,
        payload,
        context=resolved,
        conn=conn,
    )
    try:
        _send_scheduler_push_once(
            push_kind="nudge_stale",
            payload=payload,
            context=resolved,
            conn=conn,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push notification failed: %s", exc)
    return {"event_id": event_id, "rescued": len(loop_ids), **payload}


async def run_webhook_delivery(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Process queued webhook deliveries from the dedicated scheduler runtime."""
    _ = context
    return process_pending_deliveries(conn=conn, settings=settings, batch_size=100)


def _task_runner(
    task_name: str,
) -> Callable[
    [Settings, sqlite3.Connection, SchedulerRunContext | None],
    Coroutine[Any, Any, dict[str, Any]],
]:
    if task_name == "daily_review":
        return run_daily_review
    if task_name == "weekly_review":
        return run_weekly_review
    if task_name == "due_soon_nudge":
        return run_due_soon_nudge
    if task_name == "stale_rescue":
        return run_stale_rescue
    if task_name == "webhook_delivery":
        return run_webhook_delivery
    raise ValueError(f"Unknown scheduler task: {task_name}")


async def run_scheduler_task(
    *,
    task_name: str,
    settings: Settings,
    owner_token: str,
) -> dict[str, Any] | None:
    """Run one scheduler task if this process owns the task slot and it is due."""
    started_at = utc_now()
    slot_key = _slot_key(task_name, started_at, settings)
    with db.core_connection(settings) as conn:
        if not scheduler_store.task_ready(task_name=task_name, now_utc=started_at, conn=conn):
            return None
        if not scheduler_store.claim_task_run(
            task_name=task_name,
            slot_key=slot_key,
            owner_token=owner_token,
            started_at=started_at,
            lease_seconds=settings.scheduler_lease_seconds,
            conn=conn,
        ):
            return None

    context = SchedulerRunContext(
        task_name=task_name,
        slot_key=slot_key,
        owner_token=owner_token,
        settings=settings,
        lease_lost=asyncio.Event(),
    )
    runner_task = asyncio.current_task()
    assert runner_task is not None
    heartbeat_task = asyncio.create_task(
        _heartbeat_scheduler_run(context=context, runner_task=runner_task)
    )
    try:
        with db.core_connection(settings) as conn:
            result = await _task_runner(task_name)(settings, conn, context)
        finished_at = utc_now()
        with db.core_connection(settings) as conn:
            scheduler_store.finish_task_run(
                task_name=task_name,
                slot_key=slot_key,
                owner_token=owner_token,
                finished_at=finished_at,
                status="succeeded",
                result=result,
                error=None,
                conn=conn,
            )
            scheduler_store.update_task_schedule(
                task_name=task_name,
                next_due_at=_next_due_at(task_name, started_at, settings, success=True),
                started_at=started_at,
                finished_at=finished_at,
                slot_key=slot_key,
                success=True,
                result=result,
                error=None,
                conn=conn,
            )
        return result
    except asyncio.CancelledError as exc:
        finished_at = utc_now()
        with db.core_connection(settings) as conn:
            scheduler_store.finish_task_run(
                task_name=task_name,
                slot_key=slot_key,
                owner_token=owner_token,
                finished_at=finished_at,
                status="abandoned" if context.lease_lost.is_set() else "failed",
                result=None,
                error="lease_lost" if context.lease_lost.is_set() else "cancelled",
                conn=conn,
            )
            if not context.lease_lost.is_set():
                scheduler_store.update_task_schedule(
                    task_name=task_name,
                    next_due_at=_next_due_at(task_name, started_at, settings, success=False),
                    started_at=started_at,
                    finished_at=finished_at,
                    slot_key=slot_key,
                    success=False,
                    result=None,
                    error="cancelled",
                    conn=conn,
                )
        raise RuntimeError(f"scheduler_task_cancelled:{task_name}:{slot_key}") from exc
    except Exception as exc:  # noqa: BLE001
        finished_at = utc_now()
        with db.core_connection(settings) as conn:
            scheduler_store.finish_task_run(
                task_name=task_name,
                slot_key=slot_key,
                owner_token=owner_token,
                finished_at=finished_at,
                status="failed",
                result=None,
                error=str(exc),
                conn=conn,
            )
            scheduler_store.update_task_schedule(
                task_name=task_name,
                next_due_at=_next_due_at(task_name, started_at, settings, success=False),
                started_at=started_at,
                finished_at=finished_at,
                slot_key=slot_key,
                success=False,
                result=None,
                error=str(exc),
                conn=conn,
            )
        raise
    finally:
        context.lease_lost.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def run_scheduler_once(
    settings: Settings,
    *,
    owner_token: str | None = None,
) -> dict[str, Any]:
    """Run one full scheduler polling cycle."""
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
    owner_token = f"scheduler-{uuid.uuid4()}"
    logger.info("Dedicated scheduler started")
    while True:
        try:
            await run_scheduler_once(settings, owner_token=owner_token)
            await asyncio.sleep(settings.scheduler_poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Scheduler stopped")
            raise
        except Exception as exc:  # noqa: BLE001
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
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=None,
        help="Override scheduler poll interval seconds for this process.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the dedicated scheduler process."""
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
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("Scheduler execution failed")
        return 1
    return 0


__all__ = [
    "build_scheduler_parser",
    "main",
    "run_daily_review",
    "run_due_soon_nudge",
    "run_scheduler_once",
    "run_scheduler_task",
    "run_stale_rescue",
    "run_webhook_delivery",
    "run_weekly_review",
    "scheduler_loop",
]
