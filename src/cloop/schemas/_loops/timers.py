"""Timer and time-session schemas for loops.

Purpose:
    Define timer request/response models and time-session serialization helpers.

Responsibilities:
    - Validate timer stop payloads
    - Convert domain timer/time-session objects into API responses
    - Shape timer status and session-list envelopes

Non-scope:
    - Timer persistence or orchestration logic
    - Core loop CRUD/search schemas
    - Bulk, review, or planning workflow models
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._shared import SUMMARY_MAX, BaseModel, Field

if TYPE_CHECKING:
    from ...loops.models import TimerStatus, TimeSession


class TimerStartRequest(BaseModel):
    """Request to start a timer."""

    pass  # No fields needed - timer starts now


class TimerStopRequest(BaseModel):
    """Request to stop a timer."""

    notes: str | None = Field(
        default=None, max_length=SUMMARY_MAX, description="Optional notes for this session"
    )


class TimeSessionResponse(BaseModel):
    """Response for a time session."""

    id: int
    loop_id: int
    started_at_utc: str
    ended_at_utc: str | None
    duration_seconds: int | None
    is_active: bool
    notes: str | None

    @classmethod
    def from_session(cls, session: "TimeSession") -> "TimeSessionResponse":
        from ...loops.models import format_utc_datetime

        return cls(
            id=session.id,
            loop_id=session.loop_id,
            started_at_utc=format_utc_datetime(session.started_at_utc),
            ended_at_utc=format_utc_datetime(session.ended_at_utc)
            if session.ended_at_utc
            else None,
            duration_seconds=session.duration_seconds,
            is_active=session.is_active,
            notes=session.notes,
        )


class TimerStatusResponse(BaseModel):
    """Response for timer status."""

    loop_id: int
    has_active_session: bool
    active_session: TimeSessionResponse | None
    total_tracked_seconds: int
    total_tracked_minutes: int
    estimated_minutes: int | None
    estimation_accuracy: float | None  # actual/estimate ratio (null if no estimate)

    @classmethod
    def from_status(cls, status: "TimerStatus") -> "TimerStatusResponse":
        total_minutes = status.total_tracked_seconds // 60
        accuracy = None
        if status.estimated_minutes and status.estimated_minutes > 0:
            accuracy = round(total_minutes / status.estimated_minutes, 2)

        return cls(
            loop_id=status.loop_id,
            has_active_session=status.has_active_session,
            active_session=TimeSessionResponse.from_session(status.active_session)
            if status.active_session
            else None,
            total_tracked_seconds=status.total_tracked_seconds,
            total_tracked_minutes=total_minutes,
            estimated_minutes=status.estimated_minutes,
            estimation_accuracy=accuracy,
        )


class TimeSessionListResponse(BaseModel):
    """Response for listing time sessions."""

    loop_id: int
    sessions: list[TimeSessionResponse]
    total_count: int
