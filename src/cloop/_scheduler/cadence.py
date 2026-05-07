"""Scheduler slot cadence helpers.

Purpose:
    Centralize deterministic slot and next-run calculations for scheduler tasks.

Responsibilities:
    - Resolve ad-hoc contexts for direct task execution
    - Compute per-task slot intervals and deterministic slot keys
    - Determine the next due time after successful or failed runs

Scope:
    - Scheduler cadence and slot calculations only

Non-scope:
    - Task execution or side-effect persistence
    - Scheduler CLI/process orchestration

Usage:
    - Imported by scheduler task modules and runtime orchestration

Invariants/Assumptions:
    - A `(task_name, slot_key)` pair identifies one logical scheduler run
    - Failed runs retry on the poll interval instead of the task cadence interval
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

from ..settings import Settings
from .models import SchedulerRunContext


def resolved_context(
    context: SchedulerRunContext | None,
    *,
    task_name: str,
    settings: Settings,
) -> SchedulerRunContext:
    """Return the provided context or a one-shot ad-hoc scheduler context."""
    if context is not None:
        return context
    return SchedulerRunContext(
        task_name=task_name,
        slot_key=f"adhoc-{uuid.uuid4()}",
        owner_token="adhoc",
        settings=settings,
        lease_lost=asyncio.Event(),
    )


def slot_interval_seconds(task_name: str, settings: Settings) -> int:
    """Return the logical interval for one scheduler task slot."""
    if task_name == "daily_review":
        return int(settings.scheduler_daily_review_interval_hours * 3600)
    if task_name == "weekly_review":
        return int(settings.scheduler_weekly_review_interval_hours * 3600)
    if task_name == "life_garden":
        return int(settings.scheduler_life_garden_interval_hours * 3600)
    if task_name == "due_soon_nudge":
        return int(settings.scheduler_due_soon_nudge_interval_hours * 3600)
    if task_name == "stale_rescue":
        return int(settings.scheduler_stale_rescue_interval_hours * 3600)
    if task_name == "webhook_delivery":
        return max(1, int(settings.scheduler_poll_interval_seconds))
    raise ValueError(f"Unknown scheduler task: {task_name}")


def slot_key(task_name: str, now_utc: datetime, settings: Settings) -> str:
    """Return the deterministic slot key for one scheduler task and timestamp."""
    if task_name == "daily_review":
        return now_utc.date().isoformat()
    if task_name == "weekly_review":
        week_start = (now_utc - timedelta(days=now_utc.weekday())).date()
        return week_start.isoformat()
    if task_name in {"life_garden", "due_soon_nudge", "stale_rescue", "webhook_delivery"}:
        interval_seconds = slot_interval_seconds(task_name, settings)
        slot_number = int(now_utc.timestamp()) // interval_seconds
        return str(slot_number)
    raise ValueError(f"Unknown scheduler task: {task_name}")


def next_due_at(
    task_name: str,
    started_at: datetime,
    settings: Settings,
    *,
    success: bool,
) -> datetime:
    """Return the next scheduler eligibility time for one task run."""
    if not success:
        return started_at + timedelta(seconds=settings.scheduler_poll_interval_seconds)
    return started_at + timedelta(seconds=slot_interval_seconds(task_name, settings))
