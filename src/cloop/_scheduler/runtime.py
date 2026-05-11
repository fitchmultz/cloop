"""Scheduler runtime orchestration.

Purpose:
    Coordinate slot claiming, task dispatch, result recording, and dedicated
    scheduler-loop polling behind the public `cloop.scheduler` facade.

Responsibilities:
    - Resolve task handlers for named scheduler tasks
    - Claim due task slots, run tasks, and finalize state in scheduler storage
    - Run one polling cycle or the long-lived dedicated scheduler loop
    - Expose the webhook-delivery task implementation used by runtime dispatch

Scope:
    - Scheduler runtime orchestration and task dispatch only

Non-scope:
    - Scheduler CLI argument parsing
    - Task-specific payload shaping or candidate selection

Usage:
    - Imported by the scheduler facade and CLI helper module

Invariants/Assumptions:
    - One process owns a task slot before any task body executes
    - Completed task runs update both task-run rows and task-schedule rows
    - Lease loss cancels the active task and records an abandoned run
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from typing import Any

from .. import db
from ..loops.models import utc_now
from ..settings import Settings
from ..storage._scheduler_store import schedule as scheduler_schedule_store
from ..storage._scheduler_store import task_runs as scheduler_task_runs
from ..webhooks.service import process_pending_deliveries
from .cadence import next_due_at, slot_key
from .models import SCHEDULER_TASKS, SchedulerRunContext, SchedulerTaskRunnerResolver
from .side_effects import heartbeat_scheduler_run
from .task_life import run_life_garden
from .task_nudges import run_due_soon_nudge, run_stale_rescue
from .task_reviews import run_daily_review, run_weekly_review

logger = logging.getLogger(__name__)


async def run_webhook_delivery(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Process queued webhook deliveries from the dedicated scheduler runtime."""
    _ = context
    return process_pending_deliveries(conn=conn, settings=settings, batch_size=100)


def task_runner(
    task_name: str,
):
    """Resolve one scheduler task name to its coroutine implementation."""
    if task_name == "daily_review":
        return run_daily_review
    if task_name == "weekly_review":
        return run_weekly_review
    if task_name == "life_garden":
        return run_life_garden
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
    task_runner_resolver: SchedulerTaskRunnerResolver = task_runner,
) -> dict[str, Any] | None:
    """Run one scheduler task if this process owns the task slot and it is due."""
    started_at = utc_now()
    current_slot_key = slot_key(task_name, started_at, settings)
    with db.core_connection(settings) as conn:
        if not scheduler_schedule_store.task_ready(
            task_name=task_name,
            now_utc=started_at,
            conn=conn,
        ):
            return None
        if not scheduler_task_runs.claim_task_run(
            task_name=task_name,
            slot_key=current_slot_key,
            owner_token=owner_token,
            started_at=started_at,
            lease_seconds=settings.scheduler_lease_seconds,
            conn=conn,
        ):
            return None

    context = SchedulerRunContext(
        task_name=task_name,
        slot_key=current_slot_key,
        owner_token=owner_token,
        settings=settings,
        lease_lost=asyncio.Event(),
    )
    runner_task = asyncio.current_task()
    assert runner_task is not None
    heartbeat_task = asyncio.create_task(
        heartbeat_scheduler_run(context=context, runner_task=runner_task)
    )
    try:
        with db.core_connection(settings) as conn:
            result = await task_runner_resolver(task_name)(settings, conn, context)
        finished_at = utc_now()
        with db.core_connection(settings) as conn:
            scheduler_task_runs.finish_task_run(
                task_name=task_name,
                slot_key=current_slot_key,
                owner_token=owner_token,
                finished_at=finished_at,
                status="succeeded",
                result=result,
                error=None,
                conn=conn,
            )
            scheduler_schedule_store.update_task_schedule(
                task_name=task_name,
                next_due_at=next_due_at(task_name, started_at, settings, success=True),
                started_at=started_at,
                finished_at=finished_at,
                slot_key=current_slot_key,
                success=True,
                result=result,
                error=None,
                conn=conn,
            )
        return result
    except asyncio.CancelledError as exc:
        finished_at = utc_now()
        with db.core_connection(settings) as conn:
            scheduler_task_runs.finish_task_run(
                task_name=task_name,
                slot_key=current_slot_key,
                owner_token=owner_token,
                finished_at=finished_at,
                status="abandoned" if context.lease_lost.is_set() else "failed",
                result=None,
                error="lease_lost" if context.lease_lost.is_set() else "cancelled",
                conn=conn,
            )
            if not context.lease_lost.is_set():
                scheduler_schedule_store.update_task_schedule(
                    task_name=task_name,
                    next_due_at=next_due_at(task_name, started_at, settings, success=False),
                    started_at=started_at,
                    finished_at=finished_at,
                    slot_key=current_slot_key,
                    success=False,
                    result=None,
                    error="cancelled",
                    conn=conn,
                )
        raise RuntimeError(f"scheduler_task_cancelled:{task_name}:{current_slot_key}") from exc
    except Exception as exc:  # noqa: BLE001
        finished_at = utc_now()
        with db.core_connection(settings) as conn:
            scheduler_task_runs.finish_task_run(
                task_name=task_name,
                slot_key=current_slot_key,
                owner_token=owner_token,
                finished_at=finished_at,
                status="failed",
                result=None,
                error=str(exc),
                conn=conn,
            )
            scheduler_schedule_store.update_task_schedule(
                task_name=task_name,
                next_due_at=next_due_at(task_name, started_at, settings, success=False),
                started_at=started_at,
                finished_at=finished_at,
                slot_key=current_slot_key,
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
    task_runner_resolver: SchedulerTaskRunnerResolver = task_runner,
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
            task_runner_resolver=task_runner_resolver,
        )
        if result is not None:
            results[task_name] = result
    return results


async def scheduler_loop(
    settings: Settings,
    *,
    task_runner_resolver: SchedulerTaskRunnerResolver = task_runner,
) -> None:
    """Run the dedicated scheduler process until cancelled."""
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via configuration")
        return
    owner_token = f"scheduler-{uuid.uuid4()}"
    logger.info("Dedicated scheduler started")
    while True:
        try:
            await run_scheduler_once(
                settings,
                owner_token=owner_token,
                task_runner_resolver=task_runner_resolver,
            )
            await asyncio.sleep(settings.scheduler_poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Scheduler stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler error: %s", type(exc).__name__)
            await asyncio.sleep(settings.scheduler_poll_interval_seconds)
