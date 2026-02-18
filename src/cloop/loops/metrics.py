"""Loop metrics and SLI computation.

Purpose:
    Provide operational metrics for loop workflow health monitoring.

Responsibilities:
    - Compute SLIs from existing loop tables
    - Aggregate metrics by status, time windows
    - Return typed metric payloads for API/CLI/UI

Non-scope:
    - Real-time streaming metrics (compute on-demand)
    - External metrics export (Prometheus, etc.)
"""

from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .models import LoopStatus, format_utc_datetime, utc_now


@dataclass(frozen=True, slots=True)
class StatusCounts:
    inbox: int
    actionable: int
    blocked: int
    scheduled: int
    completed: int
    dropped: int


@dataclass(frozen=True, slots=True)
class LoopMetrics:
    generated_at_utc: str
    total_loops: int
    status_counts: StatusCounts
    stale_open_count: int  # Open loops not updated in 72+ hours
    blocked_too_long_count: int  # Blocked for 48+ hours
    no_next_action_count: int  # Actionable/scheduled without next_action
    enrichment_pending_count: int
    enrichment_failed_count: int
    capture_count_24h: int
    completion_count_24h: int
    avg_age_open_hours: float | None


_STALE_THRESHOLD_HOURS = 72
_BLOCKED_TOO_LONG_HOURS = 48


def compute_loop_metrics(
    *,
    conn: sqlite3.Connection,
    now_utc: datetime | None = None,
    stale_hours: int = _STALE_THRESHOLD_HOURS,
    blocked_hours: int = _BLOCKED_TOO_LONG_HOURS,
) -> LoopMetrics:
    """Compute loop operational metrics.

    Args:
        conn: SQLite connection to core database
        now_utc: Current UTC time (defaults to utc_now())
        stale_hours: Hours threshold for considering open loops stale
        blocked_hours: Hours threshold for considering blocked loops stuck

    Returns:
        LoopMetrics dataclass with all computed SLIs
    """
    now = now_utc or utc_now()
    stale_cutoff = now - timedelta(hours=stale_hours)
    blocked_cutoff = now - timedelta(hours=blocked_hours)
    window_start = now - timedelta(hours=24)

    # Status counts (exclude sentinel loop with id=0)
    status_rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM loops WHERE id > 0 GROUP BY status"
    ).fetchall()
    status_map = {row["status"]: row["cnt"] for row in status_rows}

    status_counts = StatusCounts(
        inbox=status_map.get(LoopStatus.INBOX.value, 0),
        actionable=status_map.get(LoopStatus.ACTIONABLE.value, 0),
        blocked=status_map.get(LoopStatus.BLOCKED.value, 0),
        scheduled=status_map.get(LoopStatus.SCHEDULED.value, 0),
        completed=status_map.get(LoopStatus.COMPLETED.value, 0),
        dropped=status_map.get(LoopStatus.DROPPED.value, 0),
    )

    total_loops = sum(
        [
            status_counts.inbox,
            status_counts.actionable,
            status_counts.blocked,
            status_counts.scheduled,
            status_counts.completed,
            status_counts.dropped,
        ]
    )

    # Stale open count (open = inbox, actionable, blocked, scheduled)
    stale_open_count = conn.execute(
        """
        SELECT COUNT(*) FROM loops
        WHERE id > 0
          AND status IN ('inbox', 'actionable', 'blocked', 'scheduled')
          AND datetime(updated_at) < datetime(?)
        """,
        (stale_cutoff.isoformat(),),
    ).fetchone()[0]

    # Blocked too long
    blocked_too_long_count = conn.execute(
        """
        SELECT COUNT(*) FROM loops
        WHERE id > 0
          AND status = 'blocked'
          AND datetime(updated_at) < datetime(?)
        """,
        (blocked_cutoff.isoformat(),),
    ).fetchone()[0]

    # No next_action among actionable/scheduled
    no_next_action_count = conn.execute(
        """
        SELECT COUNT(*) FROM loops
        WHERE id > 0
          AND status IN ('actionable', 'scheduled')
          AND (next_action IS NULL OR next_action = '')
        """
    ).fetchone()[0]

    # Enrichment state counts
    enrichment_rows = conn.execute(
        "SELECT enrichment_state, COUNT(*) as cnt FROM loops WHERE id > 0 GROUP BY enrichment_state"
    ).fetchall()
    enrichment_map = {row["enrichment_state"]: row["cnt"] for row in enrichment_rows}
    enrichment_pending_count = enrichment_map.get("pending", 0)
    enrichment_failed_count = enrichment_map.get("failed", 0)

    # Capture count in last 24h
    capture_count_24h = conn.execute(
        """
        SELECT COUNT(*) FROM loop_events
        WHERE event_type = 'capture'
          AND datetime(created_at) >= datetime(?)
        """,
        (window_start.isoformat(),),
    ).fetchone()[0]

    # Completion count in last 24h
    completion_count_24h = conn.execute(
        """
        SELECT COUNT(*) FROM loop_events
        WHERE event_type IN ('close', 'status_change')
          AND json_extract(payload_json, '$.to') IN ('completed', 'dropped')
          AND datetime(created_at) >= datetime(?)
        """,
        (window_start.isoformat(),),
    ).fetchone()[0]

    # Average age of open loops in hours
    avg_age_row = conn.execute(
        """
        SELECT AVG((julianday(?) - julianday(captured_at_utc)) * 24) as avg_hours
        FROM loops
        WHERE id > 0
          AND status IN ('inbox', 'actionable', 'blocked', 'scheduled')
        """,
        (now.isoformat(),),
    ).fetchone()
    avg_age_open_hours = (
        avg_age_row["avg_hours"] if avg_age_row and avg_age_row["avg_hours"] else None
    )

    return LoopMetrics(
        generated_at_utc=format_utc_datetime(now),
        total_loops=total_loops,
        status_counts=status_counts,
        stale_open_count=stale_open_count,
        blocked_too_long_count=blocked_too_long_count,
        no_next_action_count=no_next_action_count,
        enrichment_pending_count=enrichment_pending_count,
        enrichment_failed_count=enrichment_failed_count,
        capture_count_24h=capture_count_24h,
        completion_count_24h=completion_count_24h,
        avg_age_open_hours=round(avg_age_open_hours, 1) if avg_age_open_hours else None,
    )


class LoopOperationMetrics:
    """Thread-safe in-memory counters for loop lifecycle operations."""

    __slots__ = ("_lock", "_capture_count", "_update_count", "_transition_counts", "_reset_count")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capture_count: int = 0
        self._update_count: int = 0
        self._transition_counts: dict[str, int] = defaultdict(int)
        self._reset_count: int = 0

    def increment_capture(self) -> None:
        with self._lock:
            self._capture_count += 1

    def increment_update(self) -> None:
        with self._lock:
            self._update_count += 1

    def increment_transition(self, from_status: str, to_status: str) -> None:
        key = f"{from_status}->{to_status}"
        with self._lock:
            self._transition_counts[key] += 1

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "capture_count": self._capture_count,
                "update_count": self._update_count,
                "transition_counts": dict(self._transition_counts),
                "reset_count": self._reset_count,
            }

    def reset(self) -> None:
        with self._lock:
            self._capture_count = 0
            self._update_count = 0
            self._transition_counts.clear()
            self._reset_count += 1


_global_metrics: LoopOperationMetrics | None = None


def get_operation_metrics() -> LoopOperationMetrics:
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = LoopOperationMetrics()
    return _global_metrics


def record_capture() -> None:
    get_operation_metrics().increment_capture()


def record_update() -> None:
    get_operation_metrics().increment_update()


def record_transition(from_status: str, to_status: str) -> None:
    get_operation_metrics().increment_transition(from_status, to_status)
