"""Review cohort computation for stale-loop cleanup.

Purpose:
    Provide deterministic cohort membership for daily/weekly review workflows.

Responsibilities:
    - Define ReviewCohort enum with four cohort types
    - Compute cohort membership based on configurable thresholds
    - Return cohorts with counts and loop items

Non-scope:
    - UI rendering (see static/index.html)
    - CLI formatting (see cli.py)
    - HTTP routing (see routes/loops.py)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

    from ..settings import Settings


class ReviewCohort(StrEnum):
    """Review cohorts for maintenance workflows."""

    STALE = "stale"  # Not updated in N hours, still open
    NO_NEXT_ACTION = "no_next_action"  # Open with no next_action defined
    BLOCKED_TOO_LONG = "blocked_too_long"  # Blocked status for N+ hours
    DUE_SOON_UNPLANNED = "due_soon_unplanned"  # Due soon but no next_action


@dataclass(frozen=True, slots=True)
class ReviewCohortResult:
    """Result for a single review cohort."""

    cohort: ReviewCohort
    count: int
    items: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Complete review result with all cohorts."""

    daily: list[ReviewCohortResult]
    weekly: list[ReviewCohortResult]
    generated_at_utc: str


def _format_dt(dt: datetime) -> str:
    """Format datetime as ISO8601 string."""
    return dt.isoformat(timespec="seconds")


def compute_review_cohorts(
    *,
    settings: Settings,
    now_utc: datetime,
    conn: sqlite3.Connection,
    include_daily: bool = True,
    include_weekly: bool = True,
    limit_per_cohort: int = 50,
) -> ReviewResult:
    """Compute review cohorts for daily/weekly maintenance.

    Cohort definitions (deterministic):
    - stale: status IN (inbox, actionable, blocked, scheduled)
             AND updated_at < now - stale_hours
    - no_next_action: status IN (actionable, scheduled)
                      AND next_action IS NULL
    - blocked_too_long: status = blocked
                        AND updated_at < now - blocked_hours
    - due_soon_unplanned: due_at IS NOT NULL
                          AND due_at <= now + due_soon_hours
                          AND due_at > now
                          AND next_action IS NULL

    Daily cohorts: all four
    Weekly cohorts: stale, blocked_too_long (items requiring deeper review)

    Args:
        settings: App settings with review thresholds
        now_utc: Current UTC datetime for threshold computation
        conn: Database connection
        include_daily: Include daily cohorts
        include_weekly: Include weekly cohorts
        limit_per_cohort: Max items per cohort

    Returns:
        ReviewResult with daily and weekly cohort lists
    """
    from .models import format_utc_datetime
    from .repo import _row_to_record

    generated_at = _format_dt(now_utc)
    stale_cutoff = format_utc_datetime(now_utc - timedelta(hours=settings.review_stale_hours))
    blocked_cutoff = format_utc_datetime(now_utc - timedelta(hours=settings.review_blocked_hours))
    due_soon_cutoff = format_utc_datetime(now_utc + timedelta(hours=settings.due_soon_hours))
    now_str = format_utc_datetime(now_utc)

    daily: list[ReviewCohortResult] = []
    weekly: list[ReviewCohortResult] = []

    # Helper to execute query and format results
    def _run_cohort(sql: str, params: list[Any], cohort: ReviewCohort) -> ReviewCohortResult:
        rows = conn.execute(sql, params).fetchall()
        items = []
        for row in rows[:limit_per_cohort]:
            record = _row_to_record(row)
            items.append(
                {
                    "id": record.id,
                    "raw_text": record.raw_text,
                    "title": record.title,
                    "status": record.status.value,
                    "next_action": record.next_action,
                    "due_at_utc": format_utc_datetime(record.due_at_utc)
                    if record.due_at_utc
                    else None,
                    "updated_at_utc": format_utc_datetime(record.updated_at_utc),
                }
            )
        return ReviewCohortResult(
            cohort=cohort,
            count=len(rows),  # Total count before limit
            items=items,
        )

    # STALE: Open loops not updated recently
    stale_sql = """
        SELECT * FROM loops
        WHERE status IN ('inbox', 'actionable', 'blocked', 'scheduled')
          AND updated_at < ?
        ORDER BY updated_at ASC
    """
    stale_result = _run_cohort(stale_sql, [stale_cutoff], ReviewCohort.STALE)
    if include_daily:
        daily.append(stale_result)
    if include_weekly:
        weekly.append(stale_result)

    # NO_NEXT_ACTION: Actionable/scheduled without next action
    no_action_sql = """
        SELECT * FROM loops
        WHERE status IN ('actionable', 'scheduled')
          AND next_action IS NULL
        ORDER BY updated_at DESC
    """
    no_action_result = _run_cohort(no_action_sql, [], ReviewCohort.NO_NEXT_ACTION)
    if include_daily:
        daily.append(no_action_result)

    # BLOCKED_TOO_LONG: Blocked for extended period
    blocked_sql = """
        SELECT * FROM loops
        WHERE status = 'blocked'
          AND updated_at < ?
        ORDER BY updated_at ASC
    """
    blocked_result = _run_cohort(blocked_sql, [blocked_cutoff], ReviewCohort.BLOCKED_TOO_LONG)
    if include_daily:
        daily.append(blocked_result)
    if include_weekly:
        weekly.append(blocked_result)

    # DUE_SOON_UNPLANNED: Due soon but no next action
    # Use COALESCE to include recurring loops with only next_due_at_utc
    due_soon_sql = """
        SELECT * FROM loops
        WHERE COALESCE(due_at_utc, next_due_at_utc) IS NOT NULL
          AND COALESCE(due_at_utc, next_due_at_utc) > ?
          AND COALESCE(due_at_utc, next_due_at_utc) <= ?
          AND next_action IS NULL
          AND status IN ('inbox', 'actionable', 'scheduled')
        ORDER BY COALESCE(due_at_utc, next_due_at_utc) ASC
    """
    due_soon_result = _run_cohort(
        due_soon_sql,
        [now_str, due_soon_cutoff],
        ReviewCohort.DUE_SOON_UNPLANNED,
    )
    if include_daily:
        daily.append(due_soon_result)

    return ReviewResult(
        daily=daily,
        weekly=weekly,
        generated_at_utc=generated_at,
    )
