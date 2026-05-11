"""Scheduler runtime and storage tests.

Purpose:
    Verify scheduler task execution, slot ownership, deduped side effects, and
    storage persistence through canonical scheduler APIs.

Responsibilities:
    - Exercise scheduler task-run, schedule, and push-dedupe persistence behavior
    - Verify scheduler event/push dedupe and runtime heartbeating
    - Protect scheduler cancellation, escalation, and integration behavior

Scope:
    - Scheduler runtime integration and storage behavior only

Usage:
    - Run with `uv run pytest tests/test_scheduler.py`
    - Fixtures create isolated SQLite databases for each test

Invariants/Assumptions:
    - Scheduler behavior is exercised through canonical slot-based APIs
    - Scheduler slots remain deduped by `(task_name, slot_key)` and push kind

Non-scope:
    - Review cohort computation details (see `test_loop_review.py`)
    - SSE streaming or non-scheduler transport behavior
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, cast

import pytest

from cloop import db
from cloop._scheduler.models import SchedulerPushResult
from cloop.loops import read_service
from cloop.loops.models import LoopEventType
from cloop.push_sender import PushPayload, send_scheduler_push
from cloop.scheduler import (
    SchedulerRunContext,
    _emit_scheduler_event,
    _send_scheduler_push_once,
    run_daily_review,
    run_due_soon_nudge,
    run_life_garden,
    run_scheduler_once,
    run_scheduler_task,
    run_stale_rescue,
    run_weekly_review,
    scheduler_loop,
)
from cloop.schemas.life import LifeLoopGroup, LifeLoopItem, LifeMessageResponse
from cloop.schemas.loops import LoopResponse
from cloop.schemas.memory import MemoryCategory, MemoryResponse, MemorySource
from cloop.settings import get_settings
from cloop.storage import scheduler_store
from cloop.storage._scheduler_store import task_runs as scheduler_task_runs


def _notification_record(
    *,
    notification_id: str = "planning:41:checkpoint:0",
    workflow_thread_id: str | None = None,
    title: str = "Created review queue is ready in your working set",
) -> SimpleNamespace:
    resolved_location = SimpleNamespace(
        state="decide",
        review_focus="enrichment",
        session_id=52,
        loop_id=None,
        working_set_id=None,
        recall_tool="chat",
    )
    return SimpleNamespace(
        id=notification_id,
        title=title,
        body="This workflow has fresh unseen movement.",
        workflow_thread=SimpleNamespace(
            id=workflow_thread_id or notification_id,
            kind="planning_checkpoint",
            title="Weekly reset",
        ),
        resolved_location=resolved_location,
    )


def _life_response_for_first_loop(
    kwargs: dict[str, object],
    *,
    reply: str = "The Life agent picked one item.",
    notify_user: bool = False,
) -> LifeMessageResponse:
    conn = cast(sqlite3.Connection, kwargs["conn"])
    row = conn.execute("SELECT id FROM loops ORDER BY id LIMIT 1").fetchone()
    groups: list[LifeLoopGroup] = []
    if row is not None:
        loop = read_service.get_loop(loop_id=int(row["id"]), conn=conn)
        groups.append(
            LifeLoopGroup(
                name="needs_attention_today",
                title="Agent-picked nudge",
                summary="The background Life agent chose this item from full context.",
                items=[
                    LifeLoopItem(
                        loop=LoopResponse(**loop),
                        life_state="prepared",
                        rationale="The Life agent chose this; Python did not rank it.",
                        prepared_next_action="Review the prepared next step.",
                    )
                ],
            )
        )
    return LifeMessageResponse(
        mode="resurface",
        reply=reply,
        notify_user=notify_user,
        notification_title="Life nudge" if notify_user else None,
        notification_body=reply if notify_user else None,
        groups=groups,
    )


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

    def test_task_ready_returns_true_initially(self, scheduler_db: sqlite3.Connection) -> None:
        assert (
            scheduler_store.task_ready(
                task_name="daily_review",
                now_utc=datetime.now(timezone.utc),
                conn=scheduler_db,
            )
            is True
        )

    def test_claim_task_run_allows_single_owner(self, scheduler_db: sqlite3.Connection) -> None:
        started_at = datetime.now(timezone.utc)
        acquired = scheduler_store.claim_task_run(
            task_name="daily_review",
            slot_key="legacy",
            owner_token="owner-a",
            started_at=started_at,
            lease_seconds=180,
            conn=scheduler_db,
        )
        blocked = scheduler_store.claim_task_run(
            task_name="daily_review",
            slot_key="legacy",
            owner_token="owner-b",
            started_at=started_at,
            lease_seconds=180,
            conn=scheduler_db,
        )
        assert acquired is True
        assert blocked is False

    def test_update_task_schedule_persists_result(self, scheduler_db: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc)
        scheduler_store.update_task_schedule(
            task_name="daily_review",
            started_at=now,
            finished_at=now,
            success=True,
            next_due_at=now + timedelta(hours=24),
            slot_key="legacy",
            result={"status": "ok", "count": 5},
            error=None,
            conn=scheduler_db,
        )
        schedule = scheduler_store.get_task_schedule(task_name="daily_review", conn=scheduler_db)
        assert schedule is not None
        assert schedule["runs_count"] == 1
        assert json.loads(schedule["last_result_json"])["count"] == 5

    def test_task_run_markers_persist_result(self, scheduler_db: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc)
        claimed = scheduler_store.claim_task_run(
            task_name="daily_review",
            slot_key="run-1",
            owner_token="owner-a",
            started_at=now,
            lease_seconds=60,
            conn=scheduler_db,
        )
        assert claimed is True

        finished = scheduler_store.finish_task_run(
            task_name="daily_review",
            slot_key="run-1",
            owner_token="owner-a",
            finished_at=now,
            status="succeeded",
            error=None,
            result={"count": 1},
            conn=scheduler_db,
        )
        assert finished is True

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

    def test_same_slot_push_records_lifecycle_and_provenance(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        send_calls: list[dict[str, Any]] = []
        notification = _notification_record()

        def _fake_send(push_kind, payload, settings, conn):  # noqa: ANN001
            send_calls.append({"push_kind": push_kind, "payload": payload})
            return SchedulerPushResult(push_count=3, delivery_status="sent")

        monkeypatch.setattr(
            "cloop._scheduler.side_effects.read_continuity_notification_records",
            lambda **kwargs: [notification],
        )
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
            SELECT notification_id, workflow_thread_id, delivery_status,
                   claimed_at, send_started_at, send_completed_at, push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            ("daily_review", "2026-03-11", "review_generated"),
        ).fetchone()
        assert push_count_one == 3
        assert push_count_two == 3
        assert len(send_calls) == 1
        assert send_calls[0]["payload"] == {
            "review_type": "daily",
            "notification_id": notification.id,
            "workflow_thread_id": notification.workflow_thread.id,
        }
        assert row is not None
        assert row["notification_id"] == notification.id
        assert row["workflow_thread_id"] == notification.workflow_thread.id
        assert row["delivery_status"] == "sent"
        assert row["claimed_at"] is not None
        assert row["send_started_at"] is not None
        assert row["send_completed_at"] is not None
        assert row["push_count"] == 3

    def test_same_slot_push_crash_persists_attempted_state(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0
        notification = _notification_record(notification_id="planning:41:checkpoint:1")

        def _crashing_send(push_kind, payload, settings, conn):  # noqa: ANN001
            nonlocal call_count
            call_count += 1
            raise RuntimeError("push send crashed after reservation")

        monkeypatch.setattr(
            "cloop._scheduler.side_effects.read_continuity_notification_records",
            lambda **kwargs: [notification],
        )
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
            SELECT notification_id, delivery_status, claimed_at, send_started_at,
                   send_completed_at, push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            ("daily_review", "2026-03-12", "review_generated"),
        ).fetchone()
        assert call_count == 1
        assert push_count == 0
        assert row is not None
        assert row["notification_id"] == notification.id
        assert row["delivery_status"] == "attempted"
        assert row["claimed_at"] is not None
        assert row["send_started_at"] is not None
        assert row["send_completed_at"] is None
        assert row["push_count"] == 0

    def test_same_slot_push_without_sendable_notification_still_invokes_sender(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When continuity has no sendable row, scheduler push still runs the transport sender."""
        monkeypatch.setattr(
            "cloop._scheduler.side_effects.read_continuity_notification_records",
            lambda **kwargs: [],
        )

        def _fallback_send(push_kind, payload, settings, conn):  # noqa: ANN001
            assert push_kind == "review_generated"
            assert "total_items" in payload
            return SchedulerPushResult(push_count=1, delivery_status="sent")

        monkeypatch.setattr("cloop.scheduler.send_scheduler_push", _fallback_send)
        context = SchedulerRunContext(
            task_name="daily_review",
            slot_key="2026-03-13",
            owner_token="owner-a",
            settings=get_settings(),
            lease_lost=asyncio.Event(),
        )

        push_count = _send_scheduler_push_once(
            push_kind="review_generated",
            payload={"review_type": "daily", "total_items": 2, "cohorts": []},
            context=context,
            conn=scheduler_db,
        )

        row = scheduler_db.execute(
            """
            SELECT notification_id, workflow_thread_id, delivery_status,
                   claimed_at, send_started_at, send_completed_at, push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            ("daily_review", "2026-03-13", "review_generated"),
        ).fetchone()
        assert push_count == 1
        assert row is not None
        assert row["notification_id"] is None
        assert row["workflow_thread_id"] is None
        assert row["delivery_status"] == "sent"
        assert row["claimed_at"] is not None
        assert row["send_started_at"] is not None
        assert row["send_completed_at"] is not None
        assert row["push_count"] == 1

    def test_same_slot_push_with_missing_selected_notification_records_terminal_reason(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        notification = _notification_record(notification_id="planning:missing")

        monkeypatch.setattr(
            "cloop._scheduler.side_effects.read_continuity_notification_records",
            lambda **kwargs: [notification],
        )
        monkeypatch.setattr(
            "cloop.scheduler.send_scheduler_push",
            lambda push_kind, payload, settings, conn: SchedulerPushResult(
                push_count=0,
                delivery_status="skipped",
                delivery_reason="notification_missing",
            ),
        )
        context = SchedulerRunContext(
            task_name="daily_review",
            slot_key="2026-03-14",
            owner_token="owner-a",
            settings=get_settings(),
            lease_lost=asyncio.Event(),
        )

        push_count = _send_scheduler_push_once(
            push_kind="review_generated",
            payload={"review_type": "daily"},
            context=context,
            conn=scheduler_db,
        )

        row = scheduler_db.execute(
            """
            SELECT notification_id, workflow_thread_id, delivery_reason, delivery_status,
                   claimed_at, send_started_at, send_completed_at, push_count
            FROM scheduler_push_deliveries
            WHERE task_name = ? AND slot_key = ? AND push_kind = ?
            """,
            ("daily_review", "2026-03-14", "review_generated"),
        ).fetchone()
        assert push_count == 0
        assert row is not None
        assert row["notification_id"] == notification.id
        assert row["workflow_thread_id"] == notification.workflow_thread.id
        assert row["delivery_status"] == "skipped"
        assert row["claimed_at"] is not None
        assert row["send_started_at"] is not None
        assert row["send_completed_at"] is not None
        assert row["push_count"] == 0
        assert row["delivery_reason"] == "notification_missing"

    def test_send_scheduler_push_uses_preselected_notification_provenance(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        selected = _notification_record(notification_id="planning:selected")
        fallback = _notification_record(notification_id="planning:fallback")
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            "cloop.push_sender.read_continuity_snapshot",
            lambda settings=None, limit=48: SimpleNamespace(notification_records=[selected]),
        )
        monkeypatch.setattr(
            "cloop.push_sender.read_continuity_notification_records",
            lambda **kwargs: [fallback],
        )

        def _capture_push(payload, settings, conn):  # noqa: ANN001
            captured["payload"] = payload
            return 1

        monkeypatch.setattr("cloop.push_sender.send_push_notification", _capture_push)
        monkeypatch.setattr(
            "cloop.push_sender.upsert_continuity_notification_state",
            lambda notification_id, payload, *, settings=None: captured.update(
                {"notification_id": notification_id, "state_payload": payload}
            ),
        )

        result = send_scheduler_push(
            "review_generated",
            {
                "review_type": "daily",
                "total_items": 5,
                "cohorts": [],
                "notification_id": selected.id,
            },
            get_settings(),
            scheduler_db,
        )

        assert result.push_count == 1
        assert result.delivery_status == "sent"
        assert captured["notification_id"] == selected.id
        payload = captured["payload"]
        assert isinstance(payload, PushPayload)
        assert payload.data == {
            "workflow_summary_id": selected.id,
            "workflow_thread_id": selected.workflow_thread.id,
            "event_type": "review_generated",
        }


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

    def test_push_failure_log_omits_exception_details(
        self,
        scheduler_db: sqlite3.Connection,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = get_settings()

        def _leaky_push(*args: object, **kwargs: object) -> SchedulerPushResult:
            _ = args, kwargs
            raise RuntimeError("leaked notification body with token=secret")

        monkeypatch.setattr("cloop.scheduler.send_scheduler_push", _leaky_push)
        caplog.set_level(logging.WARNING, logger="cloop._scheduler.task_reviews")

        result = asyncio.run(run_daily_review(settings, scheduler_db))

        assert result["review_type"] == "daily"
        assert "RuntimeError" in caplog.text
        assert "token=secret" not in caplog.text


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
    """Tests for due-soon Life-agent scheduler task."""

    def test_due_soon_nudge_delegates_judgment_to_life_agent(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")
        calls: list[dict[str, object]] = []

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
               VALUES ('due soon task', 'actionable', datetime('now'), 0, ?)
            """,
            (due_soon,),
        )
        scheduler_db.commit()

        def fake_life_message(**kwargs: object) -> LifeMessageResponse:
            calls.append(kwargs)
            return _life_response_for_first_loop(kwargs)

        monkeypatch.setattr("cloop._scheduler.task_nudges.handle_life_message", fake_life_message)

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert calls
        assert calls[0]["settings"] is settings
        assert calls[0]["conn"] is scheduler_db
        assert calls[0]["interaction_source"] == "background"
        assert "Do not use dumb reminder behavior" in str(calls[0]["message"])
        assert result["nudged"] == 1
        assert result["details"][0]["life_state"] == "prepared"
        assert result["details"][0]["rationale"] == (
            "The Life agent chose this; Python did not rank it."
        )
        row = scheduler_db.execute(
            "SELECT event_type, payload_json FROM loop_events WHERE id = ?",
            (result["event_id"],),
        ).fetchone()
        assert row is not None
        assert row["event_type"] == LoopEventType.NUDGE_DUE_SOON.value


class TestStaleRescue:
    """Tests for stale-rescue Life-agent scheduler task."""

    def test_stale_rescue_delegates_judgment_to_life_agent(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        calls: list[dict[str, object]] = []

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at)
               VALUES ('stale task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'))
            """
        )
        scheduler_db.commit()

        def fake_life_message(**kwargs: object) -> LifeMessageResponse:
            calls.append(kwargs)
            return _life_response_for_first_loop(kwargs, reply="This stale loop needs review.")

        monkeypatch.setattr("cloop._scheduler.task_nudges.handle_life_message", fake_life_message)

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert calls
        assert "You decide what stale means from the evidence" in str(calls[0]["message"])
        assert result["rescued"] == 1
        assert result["reply"] == "This stale loop needs review."
        row = scheduler_db.execute(
            "SELECT event_type FROM loop_events WHERE id = ?",
            (result["event_id"],),
        ).fetchone()
        assert row is not None
        assert row["event_type"] == LoopEventType.NUDGE_STALE.value


class TestSchedulerEventPayloads:
    """Tests verifying scheduler event payloads have required notification fields."""

    def test_due_soon_payload_has_notification_fields(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify due-soon nudge payload contains Life-agent display fields."""
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

        def fake_life_message(**kwargs: object) -> LifeMessageResponse:
            return _life_response_for_first_loop(kwargs, notify_user=True)

        monkeypatch.setattr("cloop._scheduler.task_nudges.handle_life_message", fake_life_message)

        result = asyncio.run(run_due_soon_nudge(settings, scheduler_db))

        assert "details" in result
        assert len(result["details"]) >= 1
        detail = result["details"][0]
        assert detail["life_state"] == "prepared"
        assert detail["rationale"] == "The Life agent chose this; Python did not rank it."
        assert result["notify_user"] is True
        assert result["notification_title"] == "Life nudge"

    def test_stale_payload_has_notification_fields(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify stale nudge payload contains Life-agent display fields."""
        settings = get_settings()

        scheduler_db.execute(
            """INSERT INTO loops
               (raw_text, status, captured_at_utc, captured_tz_offset_min, updated_at)
               VALUES ('stale task', 'actionable', datetime('now', '-100 hours'), 0,
                       datetime('now', '-100 hours'))
            """
        )
        scheduler_db.commit()

        def fake_life_message(**kwargs: object) -> LifeMessageResponse:
            return _life_response_for_first_loop(kwargs)

        monkeypatch.setattr("cloop._scheduler.task_nudges.handle_life_message", fake_life_message)

        result = asyncio.run(run_stale_rescue(settings, scheduler_db))

        assert "details" in result
        detail = result["details"][0]
        assert detail["life_state"] == "prepared"
        assert detail["rationale"] == "The Life agent chose this; Python did not rank it."

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

    def test_life_garden_delegates_to_life_agent(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        calls: list[dict[str, object]] = []

        def _fake_life_message(**kwargs: object) -> LifeMessageResponse:
            calls.append(kwargs)
            return LifeMessageResponse(
                mode="cleanup",
                reply="I cleaned up the obvious stuff. One item needs your call.",
            )

        monkeypatch.setattr("cloop._scheduler.task_life.handle_life_message", _fake_life_message)

        result = asyncio.run(run_life_garden(settings, scheduler_db))

        assert calls
        assert calls[0]["settings"] is settings
        assert calls[0]["conn"] is scheduler_db
        assert calls[0]["interaction_source"] == "background"
        assert "background Life garden pass" in str(calls[0]["message"])
        assert "Life authority contract" in str(calls[0]["message"])
        assert "user-visible digest" in str(calls[0]["message"])
        assert result["mode"] == "cleanup"
        assert result["captured_count"] == 0
        assert result["updated_count"] == 0

        row = scheduler_db.execute(
            "SELECT event_type, payload_json FROM loop_events WHERE id = ?",
            (result["event_id"],),
        ).fetchone()
        assert row is not None
        assert row["event_type"] == LoopEventType.LIFE_GARDENED.value
        payload = json.loads(row["payload_json"])
        assert payload["reply"] == "I cleaned up the obvious stuff. One item needs your call."

    def test_life_garden_sends_one_digest_when_agent_requests_notification(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        send_calls: list[dict[str, object]] = []

        def _fake_life_message(**kwargs: object) -> LifeMessageResponse:
            _ = kwargs
            return LifeMessageResponse(
                mode="cleanup",
                reply="I moved stale context cold. One thing needs your call.",
                notify_user=True,
                notification_title="One thing needs your call",
                notification_body="I moved stale context cold and left one decision for you.",
                memories=[
                    MemoryResponse(
                        id=42,
                        key="life.context.stale",
                        content="Stale context moved cold.",
                        category=MemoryCategory.CONTEXT,
                        priority=20,
                        source=MemorySource.INFERRED,
                        metadata={"life_layer": "cold"},
                        created_at="2026-05-07T10:00:00+00:00",
                        updated_at="2026-05-07T10:00:00+00:00",
                    )
                ],
            )

        def _fake_send(push_kind, payload, settings, conn):  # noqa: ANN001
            _ = settings, conn
            send_calls.append({"push_kind": push_kind, "payload": payload})
            return SchedulerPushResult(push_count=2, delivery_status="sent")

        monkeypatch.setattr("cloop._scheduler.task_life.handle_life_message", _fake_life_message)
        monkeypatch.setattr("cloop.scheduler.send_scheduler_push", _fake_send)

        result = asyncio.run(run_life_garden(settings, scheduler_db))

        assert result["push_count"] == 2
        assert len(send_calls) == 1
        assert send_calls[0]["push_kind"] == "life_garden"
        sent_payload = cast("dict[str, Any]", send_calls[0]["payload"])
        assert isinstance(sent_payload, dict)
        assert sent_payload["mode"] == "cleanup"
        assert sent_payload["memory_count"] == 1
        assert sent_payload["notify_user"] is True
        assert sent_payload["notification_title"] == "One thing needs your call"

    def test_life_garden_does_not_digest_from_counts_without_agent_request(
        self, scheduler_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        send_calls: list[dict[str, object]] = []

        def _fake_life_message(**kwargs: object) -> LifeMessageResponse:
            _ = kwargs
            return LifeMessageResponse(
                mode="cleanup",
                reply="I quietly moved stale context cold.",
                notify_user=False,
                memories=[
                    MemoryResponse(
                        id=42,
                        key="life.context.stale",
                        content="Stale context moved cold.",
                        category=MemoryCategory.CONTEXT,
                        priority=20,
                        source=MemorySource.INFERRED,
                        metadata={"life_layer": "cold"},
                        created_at="2026-05-07T10:00:00+00:00",
                        updated_at="2026-05-07T10:00:00+00:00",
                    )
                ],
            )

        def _fake_send(push_kind, payload, settings, conn):  # noqa: ANN001
            _ = settings, conn
            send_calls.append({"push_kind": push_kind, "payload": payload})
            return SchedulerPushResult(push_count=2, delivery_status="sent")

        monkeypatch.setattr("cloop._scheduler.task_life.handle_life_message", _fake_life_message)
        monkeypatch.setattr("cloop.scheduler.send_scheduler_push", _fake_send)

        result = asyncio.run(run_life_garden(settings, scheduler_db))

        assert result["push_count"] == 0
        assert send_calls == []


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

        async def _noop_runner(settings, conn, context):  # noqa: ANN001
            _ = settings, conn, context
            return {"ok": True}

        monkeypatch.setattr("cloop.scheduler._task_runner", lambda task_name: _noop_runner)

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
            schedule = scheduler_store.get_task_schedule(task_name="daily_review", conn=conn)
        assert schedule is not None
        assert schedule["runs_count"] == 1

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
        original_heartbeat = scheduler_task_runs.heartbeat_task_run

        async def _run_task_after_heartbeat() -> dict[str, object] | None:
            heartbeat_seen = asyncio.Event()

            async def _slow_runner(settings, conn, context):  # noqa: ANN001
                await asyncio.wait_for(heartbeat_seen.wait(), timeout=1.0)
                return {"ok": True}

            def _record_heartbeat(*args, **kwargs):  # noqa: ANN002, ANN003
                heartbeat_times.append(kwargs["heartbeat_at"])
                heartbeat_seen.set()
                return original_heartbeat(*args, **kwargs)

            monkeypatch.setattr("cloop.scheduler._task_runner", lambda task_name: _slow_runner)
            monkeypatch.setattr(scheduler_task_runs, "heartbeat_task_run", _record_heartbeat)
            return await run_scheduler_task(
                task_name="daily_review",
                settings=settings,
                owner_token="scheduler-test:daily_review",
            )

        result = asyncio.run(_run_task_after_heartbeat())

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
