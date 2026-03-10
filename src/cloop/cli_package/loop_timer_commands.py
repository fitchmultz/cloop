"""Loop timer command handlers.

Purpose:
    Implement CLI command handlers for loop timer operations.

Responsibilities:
    - Handle timer start, stop, status, and sessions commands
    - Standardize timer command execution on the shared CLI runtime
    - Keep timer-specific human-readable rendering isolated from orchestration

Non-scope:
    - Loop content operations (see loop_core_commands.py)
    - Dependency operations (see loop_dep_commands.py)
    - View operations (see loop_view_commands.py)
"""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from ..loops.errors import LoopNotFoundError, ValidationError
from ..loops.models import format_utc_datetime
from ..loops.service import (
    ActiveTimerExistsError,
    NoActiveTimerError,
    get_timer_status,
    list_time_sessions,
    start_timer,
    stop_timer,
)
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_db_action


def _render_timer_start(session: Any) -> None:
    print(f"Timer started for loop {session.loop_id}")
    print(f"  Session ID: {session.id}")
    print(f"  Started at: {format_utc_datetime(session.started_at_utc)}")


def _render_timer_stop(session: Any) -> None:
    print(f"Timer stopped for loop {session.loop_id}")
    print(f"  Session ID: {session.id}")
    duration = session.duration_seconds or 0
    print(f"  Duration: {duration}s ({duration // 60}m)")
    if session.notes:
        print(f"  Notes: {session.notes}")


def _render_timer_status(status: Any) -> None:
    print(f"Timer status for loop {status.loop_id}:")
    if status.has_active_session and status.active_session:
        elapsed = status.active_session.elapsed_seconds
        print("  Status: RUNNING")
        print(f"  Session ID: {status.active_session.id}")
        started = format_utc_datetime(status.active_session.started_at_utc)
        print(f"  Started: {started}")
        print(f"  Elapsed: {elapsed}s ({elapsed // 60}m {elapsed % 60}s)")
    else:
        print("  Status: STOPPED")

    total_min = status.total_tracked_seconds // 60
    total_sec = status.total_tracked_seconds % 60
    print(f"  Total tracked: {total_min}m {total_sec}s")

    if status.estimated_minutes:
        print(f"  Estimated: {status.estimated_minutes}m")
        if total_min > 0:
            ratio = round(total_min / status.estimated_minutes, 2)
            print(f"  Actual/Estimate: {ratio}x")


def _render_sessions(result: dict[str, Any]) -> None:
    loop_id = result["loop_id"]
    sessions = result["sessions"]
    if not sessions:
        print(f"No time sessions for loop {loop_id}")
        return

    print(f"Time sessions for loop {loop_id} ({result['total_count']} total):")
    print("-" * 60)
    for session in sessions:
        status = "ACTIVE" if session.is_active else f"{session.duration_seconds}s"
        duration = f"{session.duration_seconds // 60}m" if session.duration_seconds else "running"
        started = format_utc_datetime(session.started_at_utc)
        print(f"  [{session.id}] {started} - {duration} ({status})")
        if session.notes:
            print(f"       Notes: {session.notes}")


def _timer_error_handlers(loop_id: int) -> list:
    return [
        error_handler(
            LoopNotFoundError,
            lambda exc: cli_error(f"loop {exc.loop_id} not found", exit_code=2),
        ),
        error_handler(
            ValidationError,
            lambda exc: cli_error(exc.message),
        ),
        error_handler(
            ActiveTimerExistsError,
            lambda exc: cli_error(
                "\n".join(
                    [
                        f"Timer already running for loop {loop_id}",
                        f"  Session ID: {exc.session.id}",
                        f"  Started at: {format_utc_datetime(exc.session.started_at_utc)}",
                    ]
                )
            ),
        ),
        error_handler(
            NoActiveTimerError,
            lambda _exc: cli_error(f"no active timer for loop {loop_id}"),
        ),
    ]


def timer_command(args: Namespace, settings: Settings) -> int:
    """Handle timer start/stop/status commands."""
    action = args.timer_action
    loop_id = args.id
    error_handlers = _timer_error_handlers(loop_id)

    if action == "start":
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: start_timer(loop_id=loop_id, conn=conn),
            render=_render_timer_start,
            error_handlers=error_handlers,
        )
    if action == "stop":
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: stop_timer(
                loop_id=loop_id,
                notes=getattr(args, "notes", None),
                conn=conn,
            ),
            render=_render_timer_stop,
            error_handlers=error_handlers,
        )
    if action == "status":
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: get_timer_status(loop_id=loop_id, conn=conn),
            render=_render_timer_status,
            error_handlers=error_handlers,
        )
    return run_cli_db_action(
        settings=settings,
        action=lambda _conn: fail_cli(f"unknown timer action: {action}", exit_code=2),
    )


def sessions_command(args: Namespace, settings: Settings) -> int:
    """List time sessions for a loop."""
    loop_id = args.id
    limit = getattr(args, "limit", 20)
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: {
            "loop_id": loop_id,
            **list_time_sessions(
                loop_id=loop_id,
                limit=limit,
                offset=0,
                conn=conn,
            ),
        },
        render=_render_sessions,
        error_handlers=_timer_error_handlers(loop_id),
    )
