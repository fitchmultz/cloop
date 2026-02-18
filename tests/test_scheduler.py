"""Tests for scheduler periodic routines.

Purpose:
    Verify scheduler task execution, idempotency, and event emission.

Responsibilities:
    - Test each scheduler task runs correctly
    - Test interval enforcement (no duplicate runs)
    - Test event emission to loop_events table

Non-scope:
    - Review cohort computation (see test_loop_review.py)
    - SSE streaming (see test_app.py)
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cloop import db
from cloop.loops.models import LoopEventType
from cloop.scheduler import (
    _get_last_run,
    _record_run,
    _should_run,
    run_daily_review,
    run_due_soon_nudge,
    run_stale_rescue,
    run_weekly_review,
    scheduler_loop,
    start_scheduler,
    stop_scheduler,
)
from cloop.settings import get_settings


@pytest.fixture
def scheduler_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Create an isolated database with scheduler tables."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(str(settings.core_db_path))
    conn.row_factory = sqlite3.Row
    return conn


class TestSchedulerState:
    """Tests for scheduler_runs table state management."""

    def test_get_last_run_returns_none_initially(self, scheduler_db: sqlite3.Connection) -> None:
        result = _get_last_run("daily_review", scheduler_db)
        assert result is None

    def test_record_run_creates_entry(self, scheduler_db: sqlite3.Connection) -> None:
        _record_run("daily_review", {"status": "ok", "count": 5}, scheduler_db)

        row = scheduler_db.execute(
            "SELECT * FROM scheduler_runs WHERE task_name = ?",
            ("daily_review",),
        ).fetchone()

        assert row is not None
        assert row["runs_count"] == 1
        assert row["last_result_json"] is not None

    def test_record_run_updates_existing(self, scheduler_db: sqlite3.Connection) -> None:
        _record_run("daily_review", {"status": "ok"}, scheduler_db)
        _record_run("daily_review", {"status": "ok", "extra": True}, scheduler_db)

        row = scheduler_db.execute(
            "SELECT runs_count FROM scheduler_runs WHERE task_name = ?",
            ("daily_review",),
        ).fetchone()

        assert row["runs_count"] == 2

    def test_should_run_returns_true_initially(self, scheduler_db: sqlite3.Connection) -> None:
        assert _should_run("daily_review", 24.0, scheduler_db) is True

    def test_should_run_returns_false_within_interval(
        self, scheduler_db: sqlite3.Connection
    ) -> None:
        _record_run("daily_review", {"status": "ok"}, scheduler_db)
        assert _should_run("daily_review", 24.0, scheduler_db) is False


class TestDailyReview:
    """Tests for daily review scheduler task."""

    def test_emits_review_generated_event(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()

        # Create a loop without next_action
        scheduler_db.execute(
            """INSERT INTO loops (raw_text, status, captured_at_utc, captured_tz_offset_min)
               VALUES ('test task', 'actionable', datetime('now'), 0)
            """
        )
        scheduler_db.commit()

        result = asyncio.run(run_daily_review(settings, scheduler_db))

        assert "event_id" in result
        assert result["review_type"] == "daily"
        assert result["total_items"] >= 1

        # Verify event was recorded
        row = scheduler_db.execute(
            "SELECT * FROM loop_events WHERE event_type = ?",
            (LoopEventType.REVIEW_GENERATED.value,),
        ).fetchone()
        assert row is not None

    def test_no_items_empty_cohorts(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()

        result = asyncio.run(run_daily_review(settings, scheduler_db))

        assert result["total_items"] == 0
        # Should have 4 cohorts even if empty (all daily cohort types)
        assert len(result["cohorts"]) == 4


class TestWeeklyReview:
    """Tests for weekly review scheduler task."""

    def test_emits_review_generated_event(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()

        # Create a stale loop
        scheduler_db.execute(
            """INSERT INTO loops 
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at)
               VALUES ('stale task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'))
            """
        )
        scheduler_db.commit()

        result = asyncio.run(run_weekly_review(settings, scheduler_db))

        assert "event_id" in result
        assert result["review_type"] == "weekly"
        assert result["total_items"] >= 1

        # Verify event was recorded
        row = scheduler_db.execute(
            "SELECT * FROM loop_events WHERE event_type = ?",
            (LoopEventType.REVIEW_GENERATED.value,),
        ).fetchone()
        assert row is not None


class TestDueSoonNudge:
    """Tests for due-soon nudge scheduler task."""

    def test_nudges_due_soon_without_next_action(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        # Create loop due in 24h without next_action
        scheduler_db.execute(
            """INSERT INTO loops 
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('due soon task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] >= 1
        assert "event_id" in result

        # Verify event type
        row = scheduler_db.execute(
            "SELECT * FROM loop_events WHERE event_type = ?",
            (LoopEventType.NUDGE_DUE_SOON.value,),
        ).fetchone()
        assert row is not None

    def test_no_nudge_when_has_next_action(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        # Create loop due in 24h WITH next_action
        scheduler_db.execute(
            """INSERT INTO loops 
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc, next_action)
               VALUES ('planned task', 'actionable', datetime('now'), 0, ?, 'do it')
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 0


class TestStaleRescue:
    """Tests for stale loop rescue scheduler task."""

    def test_nudges_stale_loops(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()

        # Create a stale loop (updated 100 hours ago)
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at)
               VALUES ('stale task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'))
            """
        )
        scheduler_db.commit()

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert result["rescued"] >= 1

        # Verify event type
        row = scheduler_db.execute(
            "SELECT * FROM loop_events WHERE event_type = ?",
            (LoopEventType.NUDGE_STALE.value,),
        ).fetchone()
        assert row is not None


class TestSchedulerIntegration:
    """Integration tests for scheduler lifecycle."""

    def test_scheduler_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
        get_settings.cache_clear()

        settings = get_settings()
        db.init_databases(settings)

        # Should not raise, should log disabled
        start_scheduler(settings)
        stop_scheduler()

    def test_scheduler_loop_cancellation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "true")
        get_settings.cache_clear()

        settings = get_settings()
        db.init_databases(settings)

        async def run_and_cancel():
            task = asyncio.create_task(scheduler_loop(settings))
            await asyncio.sleep(0.1)  # Let it run briefly
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True

        result = asyncio.run(run_and_cancel())
        assert result is True
