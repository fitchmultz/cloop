"""Public scheduler storage facade.

Purpose:
    Expose the canonical `cloop.storage.scheduler_store` import surface while
    delegating scheduler persistence details to focused internal modules.

Responsibilities:
    - Re-export scheduler task-run, schedule, and push-dedupe helpers
    - Preserve a stable public scheduler storage surface for callers and tests
    - Keep scheduler storage ownership discoverable without a monolithic module

Scope:
    - Public scheduler storage facade only

Usage:
    - Import scheduler persistence helpers from here or via `cloop.storage`
    - Internal implementation lives under `cloop.storage._scheduler_store`

Invariants/Assumptions:
    - `cloop.storage.scheduler_store` remains the canonical public scheduler
      storage module
    - Internal boundaries may evolve without changing the public facade

Non-scope:
    - Scheduler cadence calculations or runtime orchestration
    - Legacy compatibility wrappers for pre-slot scheduler APIs
"""

from __future__ import annotations

from ._scheduler_store.push_dedupe import claim_scheduler_push, record_scheduler_push
from ._scheduler_store.schedule import get_task_schedule, task_ready, update_task_schedule
from ._scheduler_store.task_runs import (
    claim_task_run,
    finish_task_run,
    get_task_run,
    heartbeat_task_run,
    mark_abandoned_runs,
)

__all__ = [
    "claim_scheduler_push",
    "claim_task_run",
    "finish_task_run",
    "get_task_run",
    "get_task_schedule",
    "heartbeat_task_run",
    "mark_abandoned_runs",
    "record_scheduler_push",
    "task_ready",
    "update_task_schedule",
]
