"""Tests for web push notification system.

Purpose:
    Verify push subscription storage and scheduler-triggered push sending.

Responsibilities:
    - Test push subscription upsert
    - Test push sending after scheduler events
    - Test deactivation of invalid subscriptions

Non-scope:
    - SSE streaming (see test_app.py)
    - Scheduler state management (see test_scheduler.py)
"""

import asyncio
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from cloop import db
from cloop.push import repo as push_repo
from cloop.push import service as push_service
from cloop.scheduler import run_due_soon_nudge
from cloop.settings import get_settings


@pytest.fixture
def push_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[sqlite3.Connection, None, None]:
    """Create an isolated database with push subscriptions table."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PUSH_VAPID_PUBLIC_KEY", "TEST_PUBLIC_KEY")
    monkeypatch.setenv("CLOOP_PUSH_VAPID_PRIVATE_KEY", "TEST_PRIVATE_KEY")
    monkeypatch.setenv("CLOOP_PUSH_VAPID_SUBJECT", "mailto:test@localhost")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    # Use context manager to get connection with proper pragmas
    with db.core_connection(settings) as conn:
        yield conn


class TestPushRepo:
    """Tests for push subscription repository."""

    def test_upsert_subscription_inserts_new(self, push_db: sqlite3.Connection) -> None:
        row_id = push_repo.upsert_subscription(
            endpoint="https://example.push/abc",
            p256dh="p256dh_key",
            auth="auth_secret",
            user_agent="pytest",
            conn=push_db,
        )

        assert row_id > 0

        row = push_db.execute(
            "SELECT * FROM push_subscriptions WHERE endpoint = ?",
            ("https://example.push/abc",),
        ).fetchone()
        assert row is not None
        assert row["p256dh"] == "p256dh_key"
        assert row["active"] == 1

    def test_upsert_subscription_updates_existing(self, push_db: sqlite3.Connection) -> None:
        push_repo.upsert_subscription(
            endpoint="https://example.push/abc",
            p256dh="old_key",
            auth="old_auth",
            user_agent="pytest1",
            conn=push_db,
        )

        push_repo.upsert_subscription(
            endpoint="https://example.push/abc",
            p256dh="new_key",
            auth="new_auth",
            user_agent="pytest2",
            conn=push_db,
        )

        rows = push_db.execute(
            "SELECT * FROM push_subscriptions WHERE endpoint = ?",
            ("https://example.push/abc",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["p256dh"] == "new_key"

    def test_list_active_returns_only_active(self, push_db: sqlite3.Connection) -> None:
        push_repo.upsert_subscription(
            endpoint="https://example.push/active",
            p256dh="key1",
            auth="auth1",
            user_agent=None,
            conn=push_db,
        )
        push_repo.upsert_subscription(
            endpoint="https://example.push/inactive",
            p256dh="key2",
            auth="auth2",
            user_agent=None,
            conn=push_db,
        )
        push_repo.deactivate_endpoint(endpoint="https://example.push/inactive", conn=push_db)

        active = push_repo.list_active(conn=push_db)
        assert len(active) == 1
        assert active[0]["endpoint"] == "https://example.push/active"

    def test_deactivate_endpoint(self, push_db: sqlite3.Connection) -> None:
        push_repo.upsert_subscription(
            endpoint="https://example.push/test",
            p256dh="key",
            auth="auth",
            user_agent=None,
            conn=push_db,
        )

        push_repo.deactivate_endpoint(endpoint="https://example.push/test", conn=push_db)

        row = push_db.execute(
            "SELECT active FROM push_subscriptions WHERE endpoint = ?",
            ("https://example.push/test",),
        ).fetchone()
        assert row["active"] == 0


class TestPushService:
    """Tests for push notification service."""

    def test_push_enabled_returns_true_with_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOOP_PUSH_VAPID_PUBLIC_KEY", "public")
        monkeypatch.setenv("CLOOP_PUSH_VAPID_PRIVATE_KEY", "private")
        get_settings.cache_clear()
        settings = get_settings()

        assert push_service.push_enabled(settings) is True

    def test_push_enabled_returns_false_without_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLOOP_PUSH_VAPID_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("CLOOP_PUSH_VAPID_PRIVATE_KEY", raising=False)
        get_settings.cache_clear()
        settings = get_settings()

        assert push_service.push_enabled(settings) is False

    def test_build_push_payload_due_soon(self) -> None:
        payload = {
            "loop_ids": [1, 2, 3],
            "details": [{"title": "Task A"}, {"title": "Task B"}, {"title": "Task C"}],
        }

        result = push_service.build_push_payload_for_scheduler_event(
            event_type="nudge_due_soon", payload=payload
        )

        assert "Due soon" in result["title"]
        assert "3 loops" in result["title"]
        assert result["url"] == "/#review"

    def test_build_push_payload_stale(self) -> None:
        payload = {
            "loop_ids": [1],
            "details": [{"title": "Stale Task"}],
        }

        result = push_service.build_push_payload_for_scheduler_event(
            event_type="nudge_stale", payload=payload
        )

        assert "Stale rescue" in result["title"]
        assert "1 loop" in result["title"]
        assert result["body"] == "Stale Task"

    def test_build_push_payload_review_generated(self) -> None:
        payload = {
            "review_type": "daily",
            "total_items": 15,
        }

        result = push_service.build_push_payload_for_scheduler_event(
            event_type="review_generated", payload=payload
        )

        assert "Daily review" in result["title"]
        assert "15" in result["body"]


class TestSchedulerPushIntegration:
    """Tests for scheduler-triggered push sending."""

    def test_scheduler_due_soon_triggers_push_send(
        self, push_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that scheduler task sends push after emitting event."""
        monkeypatch.setenv("CLOOP_PUSH_VAPID_PUBLIC_KEY", "TEST_PUBLIC_KEY")
        monkeypatch.setenv("CLOOP_PUSH_VAPID_PRIVATE_KEY", "TEST_PRIVATE_KEY")
        monkeypatch.setenv("CLOOP_PUSH_VAPID_SUBJECT", "mailto:test@localhost")
        get_settings.cache_clear()
        settings = get_settings()

        # Insert a push subscription
        push_repo.upsert_subscription(
            endpoint="https://example.pushservice.invalid/abc",
            p256dh="p256dh",
            auth="auth",
            user_agent="pytest",
            conn=push_db,
        )

        # Create due-soon loop with no next_action
        push_db.execute(
            """
            INSERT INTO loops
                (raw_text, status, captured_at_utc, captured_tz_offset_min, due_at_utc)
            VALUES
                ('due soon task', 'actionable', datetime('now'), 0,
                 datetime('now', '+24 hours'))
            """
        )
        push_db.commit()

        calls: dict[str, int | str | None] = {"n": 0, "data": None}

        def fake_webpush(*, subscription_info, data, vapid_private_key, vapid_claims) -> None:
            calls["n"] = calls["n"] + 1 if isinstance(calls["n"], int) else 1
            calls["data"] = data

        # Use the injection mechanism instead of monkeypatching
        push_service.set_webpush_fn(fake_webpush)
        try:
            result = asyncio.run(run_due_soon_nudge(settings, push_db))
            assert result["nudged"] >= 1
            assert calls["n"] == 1
            assert "Due soon" in (calls["data"] or "")
        finally:
            push_service.set_webpush_fn(None)

    def test_send_to_all_deactivates_on_404(
        self, push_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that subscriptions are deactivated when push returns 404."""
        monkeypatch.setenv("CLOOP_PUSH_VAPID_PUBLIC_KEY", "TEST_PUBLIC_KEY")
        monkeypatch.setenv("CLOOP_PUSH_VAPID_PRIVATE_KEY", "TEST_PRIVATE_KEY")
        monkeypatch.setenv("CLOOP_PUSH_VAPID_SUBJECT", "mailto:test@localhost")
        get_settings.cache_clear()
        settings = get_settings()

        push_repo.upsert_subscription(
            endpoint="https://example.push/404",
            p256dh="key",
            auth="auth",
            user_agent=None,
            conn=push_db,
        )

        class FakeResponse:
            status_code = 404

        class FakeWebPushError(Exception):
            response = FakeResponse()

        def fake_webpush_404(*, subscription_info, data, vapid_private_key, vapid_claims):
            raise FakeWebPushError("Gone")

        push_service.set_webpush_fn(fake_webpush_404)
        try:
            sent = push_service.send_to_all(
                message={"title": "Test", "body": "Test"},
                conn=push_db,
                settings=settings,
            )

            assert sent == 0

            row = push_db.execute(
                "SELECT active FROM push_subscriptions WHERE endpoint = ?",
                ("https://example.push/404",),
            ).fetchone()
            assert row["active"] == 0
        finally:
            push_service.set_webpush_fn(None)
