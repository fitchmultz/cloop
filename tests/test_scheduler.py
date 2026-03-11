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
from typing import Iterator

import pytest

from cloop import db
from cloop.loops.models import LoopEventType
from cloop.scheduler import (
    SchedulerRunContext,
    _emit_scheduler_event,
    _send_scheduler_push_once,
    run_daily_review,
    run_due_soon_nudge,
    run_scheduler_once,
    run_scheduler_task,
    run_stale_rescue,
    run_weekly_review,
    scheduler_loop,
)
from cloop.settings import get_settings
from cloop.storage import scheduler_store


@pytest.fixture
def scheduler_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """Create an isolated database with scheduler tables."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(str(settings.core_db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class TestSchedulerState:
    """Tests for scheduler lease and run-state tables."""

    def test_task_due_returns_true_initially(self, scheduler_db: sqlite3.Connection) -> None:
        assert (
            scheduler_store.task_due(
                task_name="daily_review",
                now_utc=datetime.now(timezone.utc),
                conn=scheduler_db,
            )
            is True
        )

    def test_acquire_task_lease_allows_single_owner(self, scheduler_db: sqlite3.Connection) -> None:
        acquired = scheduler_store.acquire_task_lease(
            task_name="daily_review",
            owner_token="owner-a",
            lease_seconds=180,
            conn=scheduler_db,
        )
        blocked = scheduler_store.acquire_task_lease(
            task_name="daily_review",
            owner_token="owner-b",
            lease_seconds=180,
            conn=scheduler_db,
        )
        assert acquired is True
        assert blocked is False

    def test_update_task_run_state_persists_result(self, scheduler_db: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc)
        scheduler_store.update_task_run_state(
            task_name="daily_review",
            started_at=now,
            finished_at=now,
            success=True,
            next_due_at=now + timedelta(hours=24),
            result={"status": "ok", "count": 5},
            error=None,
            conn=scheduler_db,
        )
        state = scheduler_store.get_task_run_state(task_name="daily_review", conn=scheduler_db)
        assert state is not None
        assert state["runs_count"] == 1
        assert state["last_result"]["count"] == 5

    def test_task_execution_markers_persist_result(self, scheduler_db: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc)
        scheduler_store.start_task_execution(
            run_id="run-1",
            task_name="daily_review",
            owner_token="owner-a",
            started_at=now,
            conn=scheduler_db,
        )
        scheduler_store.finish_task_execution(
            run_id="run-1",
            owner_token="owner-a",
            finished_at=now,
            status="succeeded",
            error=None,
            result={"count": 1},
            conn=scheduler_db,
        )
        row = scheduler_db.execute(
            "SELECT status, result_json FROM scheduler_task_runs WHERE slot_key = ?",
            ("run-1",),
        ).fetchone()
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["result_json"] is not None

    def test_same_slot_cannot_be_reclaimed_after_success(
        self, scheduler_db: sqlite3.Connection
    ) -> None:
        started_at = datetime.now(timezone.utc)
        claimed = scheduler_store.claim_task_run(
            task_name="daily_review",
            slot_key="2026-03-11",
            owner_token="owner-a",
            started_at=started_at,
            lease_seconds=180,
            conn=scheduler_db,
        )
        assert claimed is True

        finished = scheduler_store.finish_task_run(
            task_name="daily_review",
            slot_key="2026-03-11",
            owner_token="owner-a",
            finished_at=started_at,
            status="succeeded",
            result={"ok": True},
            error=None,
            conn=scheduler_db,
        )
        assert finished is True

        reclaimed = scheduler_store.claim_task_run(
            task_name="daily_review",
            slot_key="2026-03-11",
            owner_token="owner-b",
            started_at=started_at + timedelta(minutes=5),
            lease_seconds=180,
            conn=scheduler_db,
        )
        assert reclaimed is False

    def test_same_slot_rerun_reuses_existing_scheduler_event(
        self, scheduler_db: sqlite3.Connection
    ) -> None:
        context = SchedulerRunContext(
            task_name="daily_review",
            slot_key="2026-03-11",
            owner_token="owner-a",
            settings=get_settings(),
            lease_lost=asyncio.Event(),
        )

        event_id_one = _emit_scheduler_event(
            LoopEventType.REVIEW_GENERATED,
            {"review_type": "daily", "total_items": 1},
            context=context,
            conn=scheduler_db,
        )
        event_id_two = _emit_scheduler_event(
            LoopEventType.REVIEW_GENERATED,
            {"review_type": "daily", "total_items": 1},
            context=context,
            conn=scheduler_db,
        )

        row = scheduler_db.execute(
            """
            SELECT COUNT(*) AS count
            FROM loop_events
            WHERE source_task_name = ? AND source_slot_key = ? AND event_type = ?
            """,
            ("daily_review", "2026-03-11", LoopEventType.REVIEW_GENERATED.value),
        ).fetchone()
        assert event_id_one == event_id_two
        assert row is not None
        assert row["count"] == 1

    def test_same_slot_push_is_reserved_before_send(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        send_calls: list[dict[str, object]] = []

        def _fake_send(push_kind, payload, settings, conn):  # noqa: ANN001
            send_calls.append({"push_kind": push_kind, "payload": payload})
            return 3

        monkeypatch.setattr("cloop.scheduler.send_scheduler_push", _fake_send)
        context = SchedulerRunContext(
            task_name="daily_review",
            slot_key="2026-03-11",
            owner_token="owner-a",
            settings=get_settings(),
            lease_lost=asyncio.Event(),
        )

        push_count_one = _send_scheduler_push_once(
            push_kind="review_generated",
            payload={"review_type": "daily"},
            context=context,
            conn=scheduler_db,
        )
        push_count_two = _send_scheduler_push_once(
            push_kind="review_generated",
            payload={"review_type": "daily"},
            context=context,
            conn=scheduler_db,
        )

        row = scheduler_db.execute(
            """
            SELECT push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            ("daily_review", "2026-03-11", "review_generated"),
        ).fetchone()
        assert push_count_one == 3
        assert push_count_two == 3
        assert len(send_calls) == 1
        assert row is not None
        assert row["push_count"] == 3

    def test_same_slot_push_is_not_retried_after_send_crash(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0

        def _crashing_send(push_kind, payload, settings, conn):  # noqa: ANN001
            nonlocal call_count
            call_count += 1
            raise RuntimeError("push send crashed after reservation")

        monkeypatch.setattr("cloop.scheduler.send_scheduler_push", _crashing_send)
        context = SchedulerRunContext(
            task_name="daily_review",
            slot_key="2026-03-12",
            owner_token="owner-a",
            settings=get_settings(),
            lease_lost=asyncio.Event(),
        )

        with pytest.raises(RuntimeError, match="push send crashed"):
            _send_scheduler_push_once(
                push_kind="review_generated",
                payload={"review_type": "daily"},
                context=context,
                conn=scheduler_db,
            )

        push_count = _send_scheduler_push_once(
            push_kind="review_generated",
            payload={"review_type": "daily"},
            context=context,
            conn=scheduler_db,
        )

        row = scheduler_db.execute(
            """
            SELECT push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            ("daily_review", "2026-03-12", "review_generated"),
        ).fetchone()
        assert call_count == 1
        assert push_count == 0
        assert row is not None
        assert row["push_count"] == 0


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

    def test_recurring_loop_with_next_due_at_only_gets_nudged(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Recurring loops with only next_due_at_utc (no due_at_utc) should be nudged."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        next_due_1h = (now + timedelta(hours=1)).isoformat(timespec="seconds")

        # Create a spawned recurring loop with only next_due_at_utc populated
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min,
                next_due_at_utc, recurrence_enabled, recurrence_rrule)
               VALUES ('weekly review', 'actionable', datetime('now'), 0, ?, 1, 'FREQ=WEEKLY')
            """,
            (next_due_1h,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1
        assert len(result["loop_ids"]) == 1
        detail = result["details"][0]
        assert detail["next_due_at_utc"] is not None
        assert detail["bucket"] in {"due_soon", "quick_wins", "high_leverage", "standard"}

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

    def test_due_soon_nudge_caps_at_50_candidates(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Due-soon nudge must cap output at 50 candidates, sorted by priority."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")

        # Create 55 due-soon candidates with varying priority scores
        for i in range(55):
            urgency = 0.9 if i < 10 else 0.5  # First 10 have highest priority
            importance = 0.9 if i < 10 else 0.5
            scheduler_db.execute(
                """INSERT INTO loops
                   (raw_text, status, captured_at_utc, captured_tz_offset_min,
                    due_at_utc, urgency, importance)
                   VALUES (?, 'actionable', datetime('now'), 0, ?, ?, ?)
                """,
                (f"task-{i:02d}", due_soon, urgency, importance),
            )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        # Must cap at exactly 50
        assert result["nudged"] == 50
        assert len(result["loop_ids"]) == 50

        # Must be sorted by score (high-urgency tasks first)
        # First item should have higher score than last
        assert result["details"][0]["priority_score"] > result["details"][-1]["priority_score"]


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

        result = asyncio.run(run_scheduler_once(settings))
        assert result == {}

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

    def test_run_scheduler_task_updates_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "true")
        get_settings.cache_clear()
        settings = get_settings()
        db.init_databases(settings)

        with db.core_connection(settings) as conn:
            conn.execute(
                """INSERT INTO loops (raw_text, status, captured_at_utc, captured_tz_offset_min)
                   VALUES ('review item', 'actionable', datetime('now'), 0)
                """
            )
            conn.commit()

        asyncio.run(
            run_scheduler_task(
                task_name="daily_review",
                settings=settings,
                owner_token="scheduler-test:daily_review",
            )
        )

        with db.core_connection(settings) as conn:
            state = scheduler_store.get_task_run_state(task_name="daily_review", conn=conn)
        assert state is not None
        assert state["runs_count"] == 1

    def test_run_scheduler_task_heartbeats_long_running_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "true")
        monkeypatch.setenv("CLOOP_SCHEDULER_LEASE_SECONDS", "1")
        monkeypatch.setenv("CLOOP_SCHEDULER_POLL_INTERVAL_SECONDS", "1")
        get_settings.cache_clear()
        settings = get_settings()
        db.init_databases(settings)

        heartbeat_times: list[datetime] = []

        async def _slow_runner(settings, conn, context):  # noqa: ANN001
            await asyncio.sleep(1.2)
            return {"ok": True}

        original_heartbeat = scheduler_store.heartbeat_task_run

        def _record_heartbeat(*args, **kwargs):  # noqa: ANN002, ANN003
            heartbeat_times.append(kwargs["heartbeat_at"])
            return original_heartbeat(*args, **kwargs)

        monkeypatch.setattr("cloop.scheduler._task_runner", lambda task_name: _slow_runner)
        monkeypatch.setattr(scheduler_store, "heartbeat_task_run", _record_heartbeat)

        result = asyncio.run(
            run_scheduler_task(
                task_name="daily_review",
                settings=settings,
                owner_token="scheduler-test:daily_review",
            )
        )

        assert result == {"ok": True}
        assert heartbeat_times

        with db.core_connection(settings) as conn:
            row = conn.execute(
                """
                SELECT status, heartbeat_at
                FROM scheduler_task_runs
                WHERE task_name = 'daily_review'
                ORDER BY started_at DESC LIMIT 1
                """
            ).fetchone()
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["heartbeat_at"] is not None


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


class TestDueSoonThresholdAlignment:
    """Tests verifying scheduler and bucketing use same threshold."""

    def test_due_soon_nudge_bucket_alignment(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Due-soon nudged loops must appear in due_soon bucket, not standard."""
        settings = get_settings()
        now = datetime.now(timezone.utc)

        # Create loop due just inside the threshold (e.g., 24h if threshold is 48h)
        due_inside = (now + timedelta(hours=settings.due_soon_hours * 0.5)).isoformat(
            timespec="seconds"
        )
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('inside threshold', 'actionable', datetime('now'), 0, ?)
            """,
            (due_inside,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 1
        # The loop was selected for nudge AND should be in due_soon bucket
        assert result["details"][0]["bucket"] == "due_soon"
        assert result["bucket_summary"].get("due_soon", 0) == 1

    def test_loop_outside_threshold_not_nudged(
        self, scheduler_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loops due outside the threshold should not be nudged."""
        settings = get_settings()
        now = datetime.now(timezone.utc)

        # Create loop due just outside the threshold (e.g., 60h if threshold is 48h)
        due_outside = (now + timedelta(hours=settings.due_soon_hours * 1.25)).isoformat(
            timespec="seconds"
        )
        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('outside threshold', 'actionable', datetime('now'), 0, ?)
            """,
            (due_outside,),
        )
        scheduler_db.commit()

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert result["nudged"] == 0
