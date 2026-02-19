"""Tests for query-driven bulk loop operations."""

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.settings import get_settings


def _now_iso():
    """Return current UTC time in ISO format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def client_with_loops(tmp_path, monkeypatch):
    """Create test client with sample loops."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.init_databases(get_settings())

    from cloop.main import app

    client = TestClient(app)
    captured_at = _now_iso()

    # Create test loops
    loops = [
        {"raw_text": "Task A", "actionable": True, "tags": ["old"]},
        {"raw_text": "Task B", "actionable": True, "tags": ["old"]},
        {"raw_text": "Task C", "blocked": True, "tags": ["new"]},
    ]
    created = []
    for payload in loops:
        payload.update(
            {
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
            }
        )
        resp = client.post("/loops/capture", json=payload)
        assert resp.status_code == 200, f"Failed to create loop: {resp.text}"
        created.append(resp.json())

    return client, created


class TestQueryBulkUpdate:
    def test_dry_run_returns_preview(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable tag:old",
                "fields": {"urgency": 0.5},
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["matched_count"] == 2
        assert len(data["targets"]) == 2

    def test_applies_update_to_matched(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable tag:old",
                "fields": {"urgency": 0.9},
                "dry_run": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["succeeded"] == 2

    def test_transactional_flag_is_respected(self, client_with_loops):
        client, created = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "transactional": True,
            },
        )
        data = resp.json()
        assert data["transactional"] is True

    def test_empty_query_returns_zero_matches(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "tag:nonexistent",
                "fields": {"urgency": 0.5},
                "dry_run": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched_count"] == 0
        assert data["succeeded"] == 0


class TestQueryBulkClose:
    def test_dry_run_preview(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/close",
            json={
                "query": "tag:old",
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched_count"] == 2

    def test_closes_matched_loops(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/close",
            json={
                "query": "tag:old",
                "status": "completed",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2

    def test_closes_as_dropped(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/close",
            json={
                "query": "tag:old",
                "status": "dropped",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2


class TestQueryBulkSnooze:
    def test_snoozes_matched_loops(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/snooze",
            json={
                "query": "status:actionable",
                "snooze_until_utc": "2026-03-01T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2

    def test_dry_run_preview_snooze(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/snooze",
            json={
                "query": "status:actionable",
                "snooze_until_utc": "2026-03-01T00:00:00Z",
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["matched_count"] == 2


class TestQueryBulkLimit:
    def test_limit_affects_matched_count(self, client_with_loops):
        client, _ = client_with_loops
        # With limit of 1, should only match 1 loop
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "limit": 1,
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched_count"] == 1
        assert data["limited"] is True


class TestQueryBulkValidation:
    def test_empty_query_returns_422(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "",
                "fields": {"urgency": 0.5},
            },
        )
        assert resp.status_code == 422

    def test_missing_query_returns_422(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "fields": {"urgency": 0.5},
            },
        )
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "limit": 0,
            },
        )
        assert resp.status_code == 422

    def test_limit_negative_returns_422(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "limit": -1,
            },
        )
        assert resp.status_code == 422

    def test_close_with_note(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/close",
            json={
                "query": "tag:old",
                "status": "completed",
                "note": "Bulk closed via query",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2


class TestQueryBulkLimitedField:
    def test_limited_field_present_in_dry_run(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "limit": 1,
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "limited" in data
        assert data["limited"] is True

    def test_limited_field_present_in_actual(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "limit": 1,
                "dry_run": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "limited" in data
        assert data["limited"] is True

    def test_limited_false_when_under_limit(self, client_with_loops):
        client, _ = client_with_loops
        resp = client.post(
            "/loops/bulk/query/update",
            json={
                "query": "status:actionable",
                "fields": {"urgency": 0.5},
                "limit": 10,
                "dry_run": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "limited" in data
        assert data["limited"] is False
