"""Scheduler CLI runtime helpers.

Purpose:
    Build the dedicated scheduler CLI parser and process entrypoint behind the
    public `cloop.scheduler` facade.

Responsibilities:
    - Define the `cloop-scheduler` CLI arguments and help text
    - Initialize settings/databases before starting the scheduler runtime
    - Run one-shot or long-lived scheduler execution and map failures to exit codes

Scope:
    - Scheduler CLI parser and entrypoint only

Non-scope:
    - Scheduler task execution logic
    - FastAPI app boot or general CLI command trees

Usage:
    - Imported by `cloop.scheduler`, which exposes the public CLI helpers

Invariants/Assumptions:
    - `cloop-scheduler --once` runs exactly one polling cycle then exits
    - KeyboardInterrupt exits cleanly with status code 0
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any

from .. import db
from ..settings import Settings, get_settings
from .runtime import run_scheduler_once, scheduler_loop

logger = logging.getLogger(__name__)

SchedulerOnceFn = Callable[[Settings], Coroutine[Any, Any, dict[str, Any]]]
SchedulerLoopFn = Callable[[Settings], Coroutine[Any, Any, None]]


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


def main(
    argv: list[str] | None = None,
    *,
    run_once_fn: SchedulerOnceFn = run_scheduler_once,
    scheduler_loop_fn: SchedulerLoopFn = scheduler_loop,
) -> int:
    """CLI entrypoint for the dedicated scheduler process."""
    parser = build_scheduler_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.poll_seconds is not None:
        settings = replace(settings, scheduler_poll_interval_seconds=args.poll_seconds)
    db.init_databases(settings)
    try:
        if args.once:
            asyncio.run(run_once_fn(settings))
        else:
            asyncio.run(scheduler_loop_fn(settings))
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("Scheduler execution failed")
        return 1
    return 0
