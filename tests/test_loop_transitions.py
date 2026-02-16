# Purpose: Test loop status transitions and tag operations.
# Responsibilities:
#   - Validate state machine transitions (inbox -> actionable -> completed, etc.)
#   - Test invalid transition rejection
#   - Verify tag normalization behavior
#   - Ensure efficient query patterns for tag operations
# Non-scope:
#   - Loop enrichment tests (see test_loop_enrichment.py)
#   - RAG integration tests
#   - Prioritization/scoring tests (see test_loop_prioritization.py)
# Invariants/Assumptions:
#   - All tests use isolated test databases via make_test_client fixture
#   - Datetime helpers provided by conftest._now_iso

import sqlite3
from pathlib import Path

import pytest
from conftest import _now_iso

from cloop.loops.models import LoopStatus
from cloop.settings import get_settings


def test_loop_status_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "status test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop_id = response.json()["id"]

    for status in ["actionable", "blocked", "scheduled"]:
        transition = client.post(f"/loops/{loop_id}/status", json={"status": status})
        assert transition.status_code == 200
        assert transition.json()["status"] == status

    completed = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "completed", "note": "shipped"},
    )
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["completion_note"] == "shipped"

    reopened = client.post(f"/loops/{loop_id}/status", json={"status": "inbox"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "inbox"


def test_invalid_status_transition_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid status transitions are rejected with 400 error.

    According to _ALLOWED_TRANSITIONS in service.py, actionable/blocked/scheduled
    cannot transition directly back to inbox. The loop must be closed
    (completed/dropped) first, then reopened.
    """
    client = make_test_client()

    # Create a loop that starts in actionable status
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "test invalid transition",
            "actionable": True,
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]
    assert capture.json()["status"] == "actionable"

    # Attempt invalid transition: actionable -> inbox (not allowed)
    response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "inbox"},
    )

    # Should be rejected with 400 Bad Request (transition_error)
    assert response.status_code == 400
    error = response.json()
    assert "error" in error
    assert error["error"]["type"] == "transition_error"
    # Verify the error message contains both statuses
    assert "actionable" in error["error"]["message"].lower()
    assert "inbox" in error["error"]["message"].lower()


def test_tag_normalization_and_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "tag test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop_id = response.json()["id"]

    update = client.patch(
        f"/loops/{loop_id}",
        json={"tags": ["Feature", "Golf"]},
    )
    assert update.status_code == 200
    assert sorted(update.json()["tags"]) == ["feature", "golf"]

    tags_response = client.get("/loops/tags")
    assert tags_response.status_code == 200
    assert tags_response.json() == ["feature", "golf"]

    filtered = client.get("/loops", params={"tag": "FEATURE"})
    assert filtered.status_code == 200
    assert any(loop["id"] == loop_id for loop in filtered.json())

    cleared = client.patch(f"/loops/{loop_id}", json={"tags": []})
    assert cleared.status_code == 200

    tags_after = client.get("/loops/tags")
    assert tags_after.status_code == 200
    assert tags_after.json() == []


def test_replace_loop_tags_query_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Verify replace_loop_tags uses O(1) queries, not O(n)."""
    from cloop.db import core_connection
    from cloop.loops import repo

    make_test_client()  # Sets up the test database

    class CountingConnection:
        """Wrapper that counts execute and executemany calls."""

        def __init__(self, conn: sqlite3.Connection):
            self._conn = conn
            self.execute_count = 0
            self.executemany_count = 0

        def execute(self, *args, **kwargs):
            self.execute_count += 1
            return self._conn.execute(*args, **kwargs)

        def executemany(self, *args, **kwargs):
            self.executemany_count += 1
            return self._conn.executemany(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    with core_connection(get_settings()) as conn:
        # Create a loop
        record = repo.create_loop(
            raw_text="test loop",
            captured_at_utc=_now_iso(),
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )

        counting_conn = CountingConnection(conn)

        # Replace tags with 10 tags
        tags = [f"tag{i}" for i in range(10)]
        repo.replace_loop_tags(loop_id=record.id, tag_names=tags, conn=counting_conn)  # type: ignore[arg-type]

        # With batch operations, we expect:
        # - 1 DELETE loop_tags
        # - 1 SELECT existing tags
        # - 1 executemany INSERT new tags (or 0 if all exist)
        # - 1 SELECT to get new tag IDs (if any inserted)
        # - 1 executemany INSERT loop_tags
        # - 1 DELETE orphaned tags
        # Total: ~5-6 execute calls + 2 executemany calls

        # Before fix: ~30+ execute calls (N+1 pattern)
        # After fix: <= 6 execute calls
        assert counting_conn.execute_count <= 6, (
            f"Expected <= 6 execute calls with batch operations, "
            f"got {counting_conn.execute_count} (N+1 pattern detected)"
        )
        assert counting_conn.executemany_count >= 1, (
            "Expected executemany to be used for batch inserts"
        )
