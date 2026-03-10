"""Loop timer/time tracking endpoints.

Purpose:
    HTTP endpoints for managing time tracking on loops.

Responsibilities:
    - Start and stop timers for loops
    - Retrieve current timer status
    - List time tracking sessions

Non-scope:
    - Billing or invoicing based on time
    - Time reporting or analytics (see metrics in core.py)
    - Recurring time entries

Endpoints:
- POST /{loop_id}/timer/start: Start a timer for a loop
- POST /{loop_id}/timer/stop: Stop the active timer
- GET /{loop_id}/timer/status: Get timer status
- GET /{loop_id}/sessions: List time tracking sessions
"""

from fastapi import APIRouter, HTTPException, Query

from ... import db
from ...loops.errors import LoopNotFoundError
from ...loops.timers import (
    ActiveTimerExistsError,
    NoActiveTimerError,
    get_timer_status,
    list_time_sessions,
    start_timer,
    stop_timer,
)
from ...schemas.loops import (
    TimerStatusResponse,
    TimerStopRequest,
    TimeSessionListResponse,
    TimeSessionResponse,
)
from ._common import (
    SettingsDep,
    build_timer_session_response,
    build_timer_status_response,
)

router = APIRouter()


@router.post(
    "/{loop_id}/timer/start",
    response_model=TimeSessionResponse,
    summary="Start timer for a loop",
    description=(
        "Starts a new time tracking session for the loop. Only one active session per loop allowed."
    ),
)
async def start_timer_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> TimeSessionResponse:
    """Start a timer for a loop."""
    with db.core_connection(settings) as conn:
        try:
            session = start_timer(loop_id=loop_id, conn=conn)
            return build_timer_session_response(session)
        except ActiveTimerExistsError as e:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "timer_already_active",
                    "message": str(e),
                    "session_id": e.session.id,
                },
            ) from e
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None


@router.post(
    "/{loop_id}/timer/stop",
    response_model=TimeSessionResponse,
    summary="Stop timer for a loop",
    description="Stops the active time tracking session and records the duration.",
)
async def stop_timer_endpoint(
    loop_id: int,
    settings: SettingsDep,
    request: TimerStopRequest | None = None,
) -> TimeSessionResponse:
    """Stop the active timer for a loop."""
    with db.core_connection(settings) as conn:
        try:
            notes = request.notes if request else None
            session = stop_timer(loop_id=loop_id, notes=notes, conn=conn)
            return build_timer_session_response(session)
        except NoActiveTimerError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "no_active_timer",
                    "message": str(e),
                },
            ) from e
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None


@router.get(
    "/{loop_id}/timer/status",
    response_model=TimerStatusResponse,
    summary="Get timer status for a loop",
    description=(
        "Returns the current timer status including any active session and total tracked time."
    ),
)
async def get_timer_status_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> TimerStatusResponse:
    """Get timer status for a loop."""
    with db.core_connection(settings) as conn:
        try:
            status = get_timer_status(loop_id=loop_id, conn=conn)
            return build_timer_status_response(status)
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None


@router.get(
    "/{loop_id}/sessions",
    response_model=TimeSessionListResponse,
    summary="List time sessions for a loop",
    description="Returns the time tracking session history for the loop.",
)
async def list_sessions_endpoint(
    loop_id: int,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TimeSessionListResponse:
    """List time sessions for a loop."""
    with db.core_connection(settings) as conn:
        try:
            result = list_time_sessions(
                loop_id=loop_id,
                limit=limit,
                offset=offset,
                conn=conn,
            )

            return TimeSessionListResponse(
                loop_id=loop_id,
                sessions=[build_timer_session_response(session) for session in result["sessions"]],
                total_count=result["total_count"],
            )
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None
