"""Shared scheduler runtime models.

Purpose:
    Define the runtime context and callable contracts shared by scheduler task,
    runtime, and CLI modules.

Responsibilities:
    - Describe one claimed scheduler slot runtime context
    - Centralize scheduler task names and callable type aliases
    - Keep scheduler runtime signatures consistent across modules

Scope:
    - Scheduler dataclasses, task-name constants, and type aliases only

Non-scope:
    - Slot cadence calculations
    - Scheduler task execution or side-effect implementation

Usage:
    - Imported by scheduler task, side-effect, runtime, and facade modules

Invariants/Assumptions:
    - `SchedulerRunContext` represents one claimed scheduler slot
    - Scheduler task names remain stable across storage rows and runtime dispatch
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..settings import Settings

SCHEDULER_TASKS = (
    "daily_review",
    "weekly_review",
    "due_soon_nudge",
    "stale_rescue",
    "webhook_delivery",
)

SchedulerPushDeliveryReason = Literal["notification_missing"]


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


@dataclass(frozen=True, slots=True)
class SchedulerPushResult:
    """Terminal scheduler push outcome returned by the push sender."""

    push_count: int
    delivery_status: Literal["sent", "no_recipients", "skipped"]
    delivery_reason: SchedulerPushDeliveryReason | None = None


SchedulerTaskRunner = Callable[
    [Settings, sqlite3.Connection, SchedulerRunContext | None],
    Awaitable[dict[str, Any]],
]
SchedulerTaskRunnerResolver = Callable[[str], SchedulerTaskRunner]
SchedulerPushSender = Callable[
    [str, dict[str, Any], Settings, sqlite3.Connection], SchedulerPushResult
]
