"""Public scheduler runtime facade.

Purpose:
    Expose the canonical `cloop.scheduler` import surface while delegating
    scheduler runtime details to focused internal modules.

Responsibilities:
    - Re-export the public scheduler task/runtime/CLI surface from one stable module
    - Preserve monkeypatch seams for scheduler push sending and task dispatch in tests
    - Keep scheduler ownership discoverable without a monolithic implementation file

Scope:
    - Public scheduler facade only

Non-scope:
    - Scheduler slot cadence internals
    - Task-specific payload shaping, side effects, or runtime orchestration internals

Usage:
    - Import scheduler tasks, runtime helpers, and CLI entrypoints from here
    - Internal scheduler implementation lives under `cloop._scheduler`

Invariants/Assumptions:
    - `cloop.scheduler` remains the canonical public import surface
    - Monkeypatching `cloop.scheduler.send_scheduler_push` affects scheduler task pushes
    - Monkeypatching `cloop.scheduler._task_runner` affects runtime task dispatch
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ._scheduler.cli import build_scheduler_parser
from ._scheduler.cli import main as _main_impl
from ._scheduler.models import SCHEDULER_TASKS, SchedulerRunContext
from ._scheduler.runtime import (
    run_scheduler_once as _run_scheduler_once,
)
from ._scheduler.runtime import (
    run_scheduler_task as _run_scheduler_task,
)
from ._scheduler.runtime import (
    run_webhook_delivery,
)
from ._scheduler.runtime import (
    scheduler_loop as _scheduler_loop,
)
from ._scheduler.side_effects import (
    emit_scheduler_event as _emit_scheduler_event_impl,
)
from ._scheduler.side_effects import (
    send_scheduler_push_once as _send_scheduler_push_once_impl,
)
from ._scheduler.task_life import (
    run_life_garden as _run_life_garden,
)
from ._scheduler.task_nudges import (
    run_due_soon_nudge as _run_due_soon_nudge,
)
from ._scheduler.task_nudges import (
    run_stale_rescue as _run_stale_rescue,
)
from ._scheduler.task_reviews import (
    run_daily_review as _run_daily_review,
)
from ._scheduler.task_reviews import (
    run_weekly_review as _run_weekly_review,
)
from .loops.models import LoopEventType
from .push_sender import send_scheduler_push
from .settings import Settings


def _emit_scheduler_event(
    event_type: LoopEventType,
    payload: dict[str, Any],
    *,
    context: SchedulerRunContext,
    conn: sqlite3.Connection,
) -> int:
    """Insert one scheduler-owned loop event per `(task, slot, event_type)`."""
    return _emit_scheduler_event_impl(
        event_type,
        payload,
        context=context,
        conn=conn,
    )


def _send_scheduler_push_once(
    *,
    push_kind: str,
    payload: dict[str, Any],
    context: SchedulerRunContext,
    conn: sqlite3.Connection,
) -> int:
    """Send at most one scheduler push per `(task, slot, push_kind)`."""
    return _send_scheduler_push_once_impl(
        push_kind=push_kind,
        payload=payload,
        context=context,
        conn=conn,
        send_push_fn=send_scheduler_push,
    )


async def run_daily_review(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Generate one daily review payload and emit exactly one deduped event/push."""
    return await _run_daily_review(
        settings,
        conn,
        context,
        send_push_fn=send_scheduler_push,
    )


async def run_weekly_review(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Generate one weekly review payload and emit exactly one deduped event/push."""
    return await _run_weekly_review(
        settings,
        conn,
        context,
        send_push_fn=send_scheduler_push,
    )


async def run_life_garden(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Run one background Life organizer cleanup and memory-gardening pass."""
    return await _run_life_garden(
        settings,
        conn,
        context,
        send_push_fn=send_scheduler_push,
    )


async def run_due_soon_nudge(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Emit and persist one deduped due-soon nudge slot."""
    return await _run_due_soon_nudge(
        settings,
        conn,
        context,
        send_push_fn=send_scheduler_push,
    )


async def run_stale_rescue(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
) -> dict[str, Any]:
    """Emit one deduped stale-rescue scheduler slot."""
    return await _run_stale_rescue(
        settings,
        conn,
        context,
        send_push_fn=send_scheduler_push,
    )


def _task_runner(task_name: str):
    """Resolve one scheduler task name to the public facade coroutine implementation."""
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
) -> dict[str, Any] | None:
    """Run one scheduler task if this process owns the task slot and it is due."""
    return await _run_scheduler_task(
        task_name=task_name,
        settings=settings,
        owner_token=owner_token,
        task_runner_resolver=_task_runner,
    )


async def run_scheduler_once(
    settings: Settings,
    *,
    owner_token: str | None = None,
) -> dict[str, Any]:
    """Run one full scheduler polling cycle."""
    return await _run_scheduler_once(
        settings,
        owner_token=owner_token,
        task_runner_resolver=_task_runner,
    )


async def scheduler_loop(settings: Settings) -> None:
    """Run the dedicated scheduler process until cancelled."""
    await _scheduler_loop(settings, task_runner_resolver=_task_runner)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the dedicated scheduler process."""
    return _main_impl(
        argv,
        run_once_fn=run_scheduler_once,
        scheduler_loop_fn=scheduler_loop,
    )


__all__ = [
    "SCHEDULER_TASKS",
    "SchedulerRunContext",
    "_emit_scheduler_event",
    "_send_scheduler_push_once",
    "_task_runner",
    "build_scheduler_parser",
    "main",
    "run_daily_review",
    "run_due_soon_nudge",
    "run_life_garden",
    "run_scheduler_once",
    "run_scheduler_task",
    "run_stale_rescue",
    "run_webhook_delivery",
    "run_weekly_review",
    "scheduler_loop",
    "send_scheduler_push",
]
