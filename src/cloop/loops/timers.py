"""Timer and time tracking operations for loops.

Purpose:
    Manage timer state and time tracking sessions for loops.
    Provides functions to start, stop, and query timer status.

Responsibilities:
    - Start and stop timers for individual loops
    - Track active time sessions
    - Calculate elapsed time and totals
    - List historical time sessions
    - Raise appropriate errors for invalid timer operations

Non-scope:
    - This module does NOT handle state transitions
    - This module does NOT handle scheduling or due dates
    - This module does NOT handle webhook delivery itself (only queues events)
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, TypedDict

from .. import typingx
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import LoopNotFoundError
from .models import LoopEventType

if TYPE_CHECKING:
    from .models import TimerStatus, TimeSession


class TimeSessionListResult(TypedDict):
    """Paginated time-session results with total row count."""

    sessions: list["TimeSession"]
    total_count: int


class TimerError(Exception):
    """Base error for timer operations."""

    pass


class ActiveTimerExistsError(TimerError):
    """Raised when trying to start a timer but one is already active."""

    def __init__(self, loop_id: int, session: "TimeSession"):
        self.loop_id = loop_id
        self.session = session
        super().__init__(
            f"Loop {loop_id} already has an active timer started at {session.started_at_utc}"
        )


class NoActiveTimerError(TimerError):
    """Raised when trying to stop a timer but none is active."""

    def __init__(self, loop_id: int):
        self.loop_id = loop_id
        super().__init__(f"Loop {loop_id} has no active timer to stop")


@typingx.validate_io()
def start_timer(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> "TimeSession":
    """Start a timer for a loop.

    Enforces the single-active-timer-per-loop rule.

    Args:
        loop_id: Loop to start timer for
        conn: Database connection

    Returns:
        The newly created TimeSession

    Raises:
        LoopNotFoundError: If loop doesn't exist
        ActiveTimerExistsError: If a timer is already running for this loop
    """
    from .models import utc_now

    # Verify loop exists
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    # Check for existing active session
    active = repo.get_active_time_session(loop_id=loop_id, conn=conn)
    if active is not None:
        raise ActiveTimerExistsError(loop_id, active)

    # Create new session
    session = repo.create_time_session(
        loop_id=loop_id,
        started_at=utc_now(),
        conn=conn,
    )

    # Record event
    event_payload = {"session_id": session.id}
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.TIMER_STARTED.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.TIMER_STARTED.value,
        payload=event_payload,
        conn=conn,
    )

    return session


@typingx.validate_io()
def stop_timer(
    *,
    loop_id: int,
    notes: str | None = None,
    conn: sqlite3.Connection,
) -> "TimeSession":
    """Stop the active timer for a loop.

    Args:
        loop_id: Loop to stop timer for
        notes: Optional notes for this session
        conn: Database connection

    Returns:
        The completed TimeSession with calculated duration

    Raises:
        LoopNotFoundError: If loop doesn't exist
        NoActiveTimerError: If no timer is running for this loop
    """
    from .models import utc_now

    # Verify loop exists first
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    # Get active session
    active = repo.get_active_time_session(loop_id=loop_id, conn=conn)
    if active is None:
        raise NoActiveTimerError(loop_id)

    # Calculate duration
    now = utc_now()
    duration_seconds = int((now - active.started_at_utc).total_seconds())

    # Stop the session
    session = repo.stop_time_session(
        session_id=active.id,
        ended_at=now,
        duration_seconds=duration_seconds,
        notes=notes,
        conn=conn,
    )

    # Record event
    event_payload = {
        "session_id": session.id,
        "duration_seconds": duration_seconds,
    }
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.TIMER_STOPPED.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.TIMER_STOPPED.value,
        payload=event_payload,
        conn=conn,
    )

    return session


@typingx.validate_io()
def get_timer_status(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> "TimerStatus":
    """Get the current timer status for a loop.

    Args:
        loop_id: Loop to get status for
        conn: Database connection

    Returns:
        TimerStatus with active session (if any) and totals

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    from .models import TimerStatus

    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    active = repo.get_active_time_session(loop_id=loop_id, conn=conn)
    total_seconds = repo.get_total_tracked_time(loop_id=loop_id, conn=conn)

    return TimerStatus(
        loop_id=loop_id,
        has_active_session=active is not None,
        active_session=active,
        total_tracked_seconds=total_seconds,
        estimated_minutes=loop.time_minutes,
    )


@typingx.validate_io()
def list_time_sessions(
    *,
    loop_id: int,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection,
) -> TimeSessionListResult:
    """List time sessions for a loop.

    Args:
        loop_id: Loop to list sessions for
        limit: Maximum number of sessions
        offset: Pagination offset
        conn: Database connection

    Returns:
        Dict with paginated sessions and the total session count

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    sessions = repo.list_time_sessions(
        loop_id=loop_id,
        limit=limit,
        offset=offset,
        conn=conn,
    )
    total_count = repo.count_time_sessions(loop_id=loop_id, conn=conn)
    return {"sessions": sessions, "total_count": total_count}
