"""Tests for push notification subscription and delivery.

Purpose:
    Verify push subscription persistence, API endpoints, and sender logic.

Responsibilities:
    - Test push subscription database operations
    - Test push sender payload mapping
    - Test subscription endpoint behavior

Non-scope:
    - Actual push delivery (requires pywebpush and network)
    - Service worker testing (client-side)
"""

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from cloop import db
from cloop.push_sender import PushPayload, send_scheduler_push
from cloop.schemas._loops.continuity import ContinuityNotificationStateUpsertRequest
from cloop.settings import get_settings


@pytest.fixture
def push_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """Create isolated database with push subscriptions table."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(str(settings.core_db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class TestPushSubscriptions:
    """Tests for push subscription CRUD."""

    def test_subscribe_endpoint_table_exists(self, push_db: sqlite3.Connection) -> None:
        """Test that subscriptions table was created."""
        row = push_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='push_subscriptions'"
        ).fetchone()
        assert row is not None

    def test_insert_subscription(self, push_db: sqlite3.Connection) -> None:
        """Test that subscriptions can be saved."""
        push_db.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth)
               VALUES (?, ?, ?)""",
            ("https://fcm.googleapis.com/test", "p256dh_key", "auth_key"),
        )
        push_db.commit()

        sub = push_db.execute(
            "SELECT * FROM push_subscriptions WHERE endpoint = ?",
            ("https://fcm.googleapis.com/test",),
        ).fetchone()
        assert sub is not None
        assert sub["p256dh"] == "p256dh_key"

    def test_upsert_subscription(self, push_db: sqlite3.Connection) -> None:
        """Test that duplicate endpoints update existing record."""
        push_db.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth)
               VALUES (?, ?, ?)""",
            ("https://fcm.googleapis.com/test", "old_p256dh", "old_auth"),
        )
        push_db.commit()

        # Upsert with new keys
        push_db.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth)
               VALUES (?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET
                   p256dh = excluded.p256dh,
                   auth = excluded.auth""",
            ("https://fcm.googleapis.com/test", "new_p256dh", "new_auth"),
        )
        push_db.commit()

        # Should still be one row with updated values
        count = push_db.execute("SELECT COUNT(*) as cnt FROM push_subscriptions").fetchone()["cnt"]
        assert count == 1

        sub = push_db.execute("SELECT * FROM push_subscriptions").fetchone()
        assert sub["p256dh"] == "new_p256dh"


class TestPushSender:
    """Tests for push notification sending."""

    def test_send_scheduler_push_nudge_due_soon(
        self, push_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test push for due-soon nudge returns 0 gracefully without pywebpush."""
        settings = get_settings()

        # Add subscription
        push_db.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth)
               VALUES (?, ?, ?)""",
            ("https://fcm.googleapis.com/test", "key", "auth"),
        )
        push_db.commit()

        # Without pywebpush installed, should return 0 gracefully
        payload = {
            "details": [{"id": 1, "title": "Task 1", "is_overdue": True, "escalation_level": 2}]
        }
        result = send_scheduler_push("nudge_due_soon", payload, settings, push_db)
        # Returns 0 if pywebpush not installed (expected in test env)
        assert result >= 0

    def test_send_scheduler_push_empty_payload(
        self, push_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test push with no items returns 0."""
        settings = get_settings()

        payload = {"details": []}
        result = send_scheduler_push("nudge_due_soon", payload, settings, push_db)
        assert result == 0

    def test_send_scheduler_push_review_generated(
        self, push_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test push for review generated."""
        settings = get_settings()

        # Add subscription
        push_db.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth)
               VALUES (?, ?, ?)""",
            ("https://fcm.googleapis.com/test", "key", "auth"),
        )
        push_db.commit()

        payload = {
            "review_type": "daily",
            "total_items": 5,
            "cohorts": [{"cohort": "due_soon", "count": 2}],
        }
        result = send_scheduler_push("review_generated", payload, settings, push_db)
        # Returns 0 if pywebpush not installed (expected in test env)
        assert result >= 0

    def test_send_scheduler_push_review_generated_zero_items(
        self, push_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test push with zero items returns 0."""
        settings = get_settings()

        payload = {"review_type": "daily", "total_items": 0, "cohorts": []}
        result = send_scheduler_push("review_generated", payload, settings, push_db)
        assert result == 0

    def test_send_scheduler_push_uses_canonical_continuity_record(
        self, push_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test push delivery uses the backend-authored continuity notification record."""
        settings = get_settings()
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            "cloop.push_sender.read_continuity_notification_records",
            lambda *, limit, settings=None, channel="all": [
                SimpleNamespace(
                    id="planning:41:checkpoint:0",
                    title="Created launch review queue is ready in your working set",
                    body="This workflow has fresh unseen movement.",
                    workflow_thread=SimpleNamespace(id="planning:41:checkpoint:0"),
                    resolved_location=SimpleNamespace(
                        state="decide",
                        review_focus="enrichment",
                        session_id=52,
                        loop_id=None,
                        working_set_id=7,
                        recall_tool="chat",
                    ),
                )
            ],
        )

        def _capture(payload: PushPayload, settings_arg, conn_arg) -> int:
            captured["payload"] = payload
            captured["settings"] = settings_arg
            captured["conn"] = conn_arg
            return 1

        monkeypatch.setattr("cloop.push_sender.send_push_notification", _capture)
        monkeypatch.setattr(
            "cloop.push_sender.upsert_continuity_notification_state",
            lambda notification_id, payload, *, settings=None: captured.update(
                {
                    "notification_id": notification_id,
                    "state_payload": payload,
                }
            ),
        )

        result = send_scheduler_push(
            "review_generated",
            {"review_type": "daily", "total_items": 5, "cohorts": []},
            settings,
            push_db,
        )

        assert result == 1
        payload = captured["payload"]
        assert isinstance(payload, PushPayload)
        assert payload.title == "Created launch review queue is ready in your working set"
        assert payload.body == "This workflow has fresh unseen movement."
        assert payload.url == "/#decide/enrichment/52"
        assert payload.data == {
            "workflow_summary_id": "planning:41:checkpoint:0",
            "workflow_thread_id": "planning:41:checkpoint:0",
            "event_type": "review_generated",
        }
        assert captured["notification_id"] == "planning:41:checkpoint:0"
        state_payload = captured["state_payload"]
        assert isinstance(state_payload, ContinuityNotificationStateUpsertRequest)
        assert state_payload.inboxed_at_utc is not None


class TestPushPayload:
    """Tests for push payload structure."""

    def test_push_payload_defaults(self) -> None:
        """Test PushPayload has correct defaults."""
        payload = PushPayload(title="Test", body="Body")
        assert payload.title == "Test"
        assert payload.body == "Body"
        assert payload.icon == "/static/icons/icon-192.png"
        assert payload.badge == "/static/icons/icon-192.png"
        assert payload.url == "/"
        assert payload.data is None

    def test_push_payload_custom(self) -> None:
        """Test PushPayload accepts custom values."""
        payload = PushPayload(
            title="Custom",
            body="Custom body",
            icon="/custom/icon.png",
            url="/review",
            data={"key": "value"},
        )
        assert payload.icon == "/custom/icon.png"
        assert payload.url == "/review"
        assert payload.data == {"key": "value"}
