"""Loop timer command handlers.

Purpose:
    Implement CLI command handlers for loop timer operations.

Responsibilities:
    - Handle timer start, stop, status, and sessions commands
"""

from __future__ import annotations

import sys
from argparse import Namespace

from .. import db
from ..loops.errors import LoopNotFoundError
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


def timer_command(args: Namespace, settings: Settings) -> int:
    """Handle timer start/stop/status commands."""
    action = args.timer_action
    loop_id = args.id

    try:
        with db.core_connection(settings) as conn:
            if action == "start":
                try:
                    session = start_timer(loop_id=loop_id, conn=conn)
                    print(f"Timer started for loop {loop_id}")
                    print(f"  Session ID: {session.id}")
                    print(f"  Started at: {format_utc_datetime(session.started_at_utc)}")
                    return 0
                except ActiveTimerExistsError as e:
                    print(f"Error: Timer already running for loop {loop_id}", file=sys.stderr)
                    print(f"  Session ID: {e.session.id}", file=sys.stderr)
                    print(
                        f"  Started at: {format_utc_datetime(e.session.started_at_utc)}",
                        file=sys.stderr,
                    )
                    return 1
                except LoopNotFoundError:
                    print(f"Error: Loop {loop_id} not found", file=sys.stderr)
                    return 2

            elif action == "stop":
                try:
                    notes = getattr(args, "notes", None)
                    session = stop_timer(loop_id=loop_id, notes=notes, conn=conn)
                    print(f"Timer stopped for loop {loop_id}")
                    print(f"  Session ID: {session.id}")
                    duration = session.duration_seconds or 0
                    duration_mins = duration // 60
                    print(f"  Duration: {duration}s ({duration_mins}m)")
                    if session.notes:
                        print(f"  Notes: {session.notes}")
                    return 0
                except NoActiveTimerError:
                    print(f"Error: No active timer for loop {loop_id}", file=sys.stderr)
                    return 1
                except LoopNotFoundError:
                    print(f"Error: Loop {loop_id} not found", file=sys.stderr)
                    return 2

            elif action == "status":
                try:
                    status = get_timer_status(loop_id=loop_id, conn=conn)
                    print(f"Timer status for loop {loop_id}:")
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
                    return 0
                except LoopNotFoundError:
                    print(f"Error: Loop {loop_id} not found", file=sys.stderr)
                    return 2

            else:
                print(f"Error: Unknown timer action: {action}", file=sys.stderr)
                return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def sessions_command(args: Namespace, settings: Settings) -> int:
    """List time sessions for a loop."""
    loop_id = args.id
    limit = getattr(args, "limit", 20)

    try:
        with db.core_connection(settings) as conn:
            sessions = list_time_sessions(
                loop_id=loop_id,
                limit=limit,
                offset=0,
                conn=conn,
            )

            if not sessions:
                print(f"No time sessions for loop {loop_id}")
                return 0

            print(f"Time sessions for loop {loop_id}:")
            print("-" * 60)

            for s in sessions:
                status = "ACTIVE" if s.is_active else f"{s.duration_seconds}s"
                duration = f"{s.duration_seconds // 60}m" if s.duration_seconds else "running"
                started = format_utc_datetime(s.started_at_utc)
                print(f"  [{s.id}] {started} - {duration} ({status})")
                if s.notes:
                    print(f"       Notes: {s.notes}")

            return 0
    except LoopNotFoundError:
        print(f"Error: Loop {loop_id} not found", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
