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

    def test_snoozed_loops_excluded_from_due_soon_nudge(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Snoozed loops should not receive due-soon nudges."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_1h = (now + timedelta(hours=1)).isoformat(timespec="seconds")
        snooze_12h = (now + timedelta(hours=12)).isoformat(timespec="seconds")

        # Create loop due in 1h but snoozed for 12h
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                due_at_utc, snooze_until_utc)
               VALUES ('snoozed task', 'actionable', datetime('now'), 0, ?, ?)
            """,
            (due_1h, snooze_12h),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 0
        assert result["loop_ids"] == []

    def test_expired_snooze_allows_due_soon_nudge(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loops with past snooze_until_utc should still get nudged."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_1h = (now + timedelta(hours=1)).isoformat(timespec="seconds")
        snooze_past = (now - timedelta(hours=1)).isoformat(timespec="seconds")

        # Create loop due in 1h with expired snooze
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                due_at_utc, snooze_until_utc)
               VALUES ('was snoozed', 'actionable', datetime('now'), 0, ?, ?)
            """,
            (due_1h, snooze_past),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1

    def test_null_snooze_allows_due_soon_nudge(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loops with NULL snooze_until_utc should get nudged (baseline)."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_1h = (now + timedelta(hours=1)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('unsnoozed task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_1h,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1

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

    def test_due_soon_nudge_orders_by_priority_score(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify due-soon nudges are ordered by priority score, not just due date."""
        settings = get_settings()
        now = datetime.now(timezone.utc)

        # Task A: due in 2h, LOW urgency/importance (should rank lower)
        due_2h = (now + timedelta(hours=2)).isoformat(timespec="seconds")
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                due_at_utc, urgency, importance)
               VALUES ('low priority task', 'actionable', datetime('now'), 0,
                       ?, 0.1, 0.1)
            """,
            (due_2h,),
        )

        # Task B: due in 24h, HIGH urgency/importance (should rank higher despite later due)
        due_24h = (now + timedelta(hours=24)).isoformat(timespec="seconds")
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                due_at_utc, urgency, importance)
               VALUES ('high priority task', 'actionable', datetime('now'), 0,
                       ?, 0.9, 0.9)
            """,
            (due_24h,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 2
        # High-priority task should appear first despite later due date
        # The one with higher score should be first
        assert result["details"][0]["priority_score"] > result["details"][1]["priority_score"]

    def test_due_soon_payload_includes_priority_score_and_bucket(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify payload includes priority_score and bucket fields."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                due_at_utc, urgency, importance)
               VALUES ('test task', 'actionable', datetime('now'), 0, ?, 0.5, 0.5)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1
        detail = result["details"][0]
        assert "priority_score" in detail
        assert "bucket" in detail
        assert isinstance(detail["priority_score"], (float, int))
        assert detail["bucket"] in {"due_soon", "quick_wins", "high_leverage", "standard"}

    def test_due_soon_payload_includes_bucket_summary(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify payload includes bucket_summary for UI categorization."""
        settings = get_settings()
        now = datetime.now(timezone.utc)

        # Create a due_soon bucket item
        due_1h = (now + timedelta(hours=1)).isoformat(timespec="seconds")
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('due soon', 'actionable', datetime('now'), 0, ?)
            """,
            (due_1h,),
        )

        # Create a quick_win bucket item (short time, low activation)
        due_24h = (now + timedelta(hours=24)).isoformat(timespec="seconds")
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                due_at_utc, time_minutes, activation_energy)
               VALUES ('quick win', 'actionable', datetime('now'), 0, ?, 15, 1)
            """,
            (due_24h,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert "bucket_summary" in result
        assert isinstance(result["bucket_summary"], dict)
        # Should have at least one bucket with count
        assert sum(result["bucket_summary"].values()) >= 1


class TestStaleRescue:
    """Tests for stale loop rescue scheduler task."""

    def test_snoozed_loops_excluded_from_stale_rescue(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Snoozed loops should not receive stale rescue nudges."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        snooze_future = (now + timedelta(hours=12)).isoformat(timespec="seconds")

        # Create stale loop that is also snoozed
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at,
                snooze_until_utc)
               VALUES ('stale snoozed task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'), ?)
            """,
            (snooze_future,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert result["rescued"] == 0
        assert result["loop_ids"] == []

    def test_expired_snooze_allows_stale_rescue(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale loops with past snooze_until_utc should still get rescued."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        snooze_past = (now - timedelta(hours=1)).isoformat(timespec="seconds")

        # Create stale loop with expired snooze
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at,
                snooze_until_utc)
               VALUES ('was snoozed', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'), ?)
            """,
            (snooze_past,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert result["rescued"] >= 1

    def test_null_snooze_allows_stale_rescue(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale loops with NULL snooze_until_utc should get rescued (baseline)."""
        settings = get_settings()

        # Create stale loop without snooze
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at)
               VALUES ('stale unsnoozed task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'))
            """
        )
        scheduler_db.commit()

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert result["rescued"] >= 1

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


class TestSchedulerEventPayloads:
    """Tests verifying scheduler event payloads have required notification fields."""

    def test_due_soon_payload_has_notification_fields(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify due-soon nudge payload contains fields needed for UI rendering."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('test task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        # Verify payload structure for UI
        assert "details" in result
        assert len(result["details"]) >= 1

        detail = result["details"][0]
        assert "id" in detail
        assert "title" in detail
        assert "due_at_utc" in detail
        assert "escalation_level" in detail
        assert "is_overdue" in detail

    def test_stale_payload_has_notification_fields(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify stale nudge payload contains fields needed for UI rendering."""
        settings = get_settings()

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at)
               VALUES ('stale task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'))
            """
        )
        scheduler_db.commit()

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert "details" in result
        detail = result["details"][0]
        assert "id" in detail
        assert "title" in detail
        assert "status" in detail

    def test_review_payload_has_notification_fields(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify review generated payload contains fields needed for UI rendering."""
        settings = get_settings()

        # Create a loop without next_action for review
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min)
               VALUES ('review item', 'actionable', datetime('now'), 0)
            """
        )
        scheduler_db.commit()

        result = asyncio.run(run_daily_review(settings, scheduler_db))

        assert "review_type" in result
        assert "total_items" in result
        assert "cohorts" in result


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


class TestDueSoonNudgeEscalation:
    """Tests for due-soon nudge escalation over repeated runs."""

    def test_first_nudge_has_escalation_level_zero(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('due soon task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1
        assert result["details"][0]["escalation_level"] == 0
        assert result["details"][0]["nudge_count"] == 1

        # Verify state persisted
        row = scheduler_db.execute(
            "SELECT * FROM loop_nudges WHERE loop_id = ? AND nudge_type = 'due_soon'",
            (result["loop_ids"][0],),
        ).fetchone()
        assert row is not None
        assert row["escalation_level"] == 0
        assert row["nudge_count"] == 1

    def test_repeated_nudges_escalate_level(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('due soon task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        # Run three times
        for i in range(3):
            result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))
            assert result["nudged"] == 1
            assert result["details"][0]["nudge_count"] == i + 1

        # Third nudge should be escalation level 1
        assert result["details"][0]["escalation_level"] == 1

    def test_overdue_loops_escalate_faster(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        # Due 1 hour ago (overdue)
        overdue = (now - timedelta(hours=1)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('overdue task', 'actionable', datetime('now'), 0, ?)
            """,
            (overdue,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1
        # Overdue loops should start at escalation level 2 or higher
        assert result["details"][0]["escalation_level"] >= 2
        assert result["details"][0]["is_overdue"] is True

    def test_escalation_summary_in_payload(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        # Create two loops
        for i in range(2):
            scheduler_db.execute(
                """INSERT INTO loops
                   (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
                   VALUES (?, 'actionable', datetime('now'), 0, ?)
                """,
                (f"task {i}", due_soon),
            )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert "escalation_summary" in result
        assert result["escalation_summary"].get(0, 0) == 2  # Both at level 0

    def test_nudge_state_resets_when_next_action_set(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('due soon task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        # First nudge
        asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        # Set next_action
        scheduler_db.execute("UPDATE loops SET next_action = 'do it now' WHERE id = 1")
        scheduler_db.commit()

        # Reset nudge state (simulating what service.py would do)
        from cloop.loops.repo import reset_nudge_state

        reset_nudge_state(loop_id=1, nudge_type="due_soon", conn=scheduler_db)
        scheduler_db.commit()

        # Verify state is gone
        row = scheduler_db.execute(
            "SELECT * FROM loop_nudges WHERE loop_id = 1 AND nudge_type = 'due_soon'",
        ).fetchone()
        assert row is None

        # Second nudge should not find this loop (has next_action)
        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))
        assert result["nudged"] == 0

    def test_escalation_caps_at_level_3(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that escalation level never exceeds 3."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        overdue = (now - timedelta(hours=1)).isoformat(timespec="seconds")

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('overdue task', 'actionable', datetime('now'), 0, ?)
            """,
            (overdue,),
        )
        scheduler_db.commit()

        # Run many times to try to exceed max level
        for _ in range(10):
            result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        # Escalation level should be capped at 3
        assert result["details"][0]["escalation_level"] == 3

    def test_empty_result_returns_escalation_summary(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that empty results still include escalation_summary."""
        settings = get_settings()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 0
        assert result["loop_ids"] == []
        assert "escalation_summary" in result
        assert result["escalation_summary"] == {}
