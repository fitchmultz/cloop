import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import _now_iso
from fastapi.testclient import TestClient

from cloop import db
from cloop.loops.models import LoopStatus
from cloop.loops.prioritization import bucketize
from cloop.main import app
from cloop.settings import get_settings


def test_next_loops_sql_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that next_loops SQL-level filtering excludes wrong candidates."""
    client = make_test_client()
    captured_at = _now_iso()
    now = datetime.now(timezone.utc)
    future = (now + timedelta(hours=24)).isoformat(timespec="seconds")

    # Create loops with different states
    # 1. Has next_action, no snooze - SHOULD appear
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "task with next action",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_1 = resp.json()["id"]
    client.patch(f"/loops/{loop_id_1}", json={"next_action": "do this"})

    # 2. Has next_action, snoozed in future - should NOT appear
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "snoozed task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_2 = resp.json()["id"]
    client.patch(
        f"/loops/{loop_id_2}",
        json={"next_action": "do later", "snooze_until_utc": future},
    )

    # 3. No next_action - should NOT appear
    client.post(
        "/loops/capture",
        json={
            "raw_text": "inbox item",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )

    # 4. Completed status - should NOT appear (even with next_action)
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "done task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_4 = resp.json()["id"]
    client.patch(f"/loops/{loop_id_4}", json={"next_action": "was doing"})
    client.post(f"/loops/{loop_id_4}/status", json={"status": "completed"})

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # Only the first task should appear in any bucket
    all_titles = []
    for bucket_items in data.values():
        all_titles.extend(item.get("title") or item.get("raw_text", "") for item in bucket_items)

    assert any("task with next action" in t for t in all_titles)
    assert not any("snoozed task" in t for t in all_titles)
    assert not any("inbox item" in t for t in all_titles)
    assert not any("done task" in t for t in all_titles)


def test_next_loops_candidate_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that candidate count respects next_candidates_limit setting."""
    client = make_test_client()
    captured_at = _now_iso()

    # Create more loops than the default cap (500)
    # For testing, we'll create 10 and verify the limit works
    for i in range(10):
        client.post(
            "/loops/capture",
            json={
                "raw_text": f"task {i}",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
                "next_action": f"action {i}",
            },
        )

    # Set a low limit via environment
    monkeypatch.setenv("CLOOP_NEXT_CANDIDATES_LIMIT", "5")
    get_settings.cache_clear()

    response = client.get("/loops/next")
    assert response.status_code == 200

    # Total across all buckets should be at most the cap
    data = response.json()
    total_items = sum(len(items) for items in data.values())
    assert total_items <= 5


def test_next_loops_ranking_preserves_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that SQL filtering returns the same candidates Python filtering would.

    This validates that the SQL-level filters (status, next_action, snooze) correctly
    identify actionable candidates without missing items that would have passed
    the old Python-level filtering.
    """
    client = make_test_client()
    captured_at = _now_iso()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat(timespec="seconds")

    # Create an actionable loop that should appear in results
    resp_actionable = client.post(
        "/loops/capture",
        json={
            "raw_text": "actionable task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "urgency": 0.8,
        },
    )
    actionable_id = resp_actionable.json()["id"]
    client.patch(f"/loops/{actionable_id}", json={"next_action": "do this"})

    # Create an inbox item with next_action - should also appear
    resp_inbox = client.post(
        "/loops/capture",
        json={
            "raw_text": "inbox with action",
            "actionable": False,  # Will be inbox status
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "urgency": 0.5,
        },
    )
    inbox_id = resp_inbox.json()["id"]
    client.patch(f"/loops/{inbox_id}", json={"next_action": "process this"})

    # Create an expired snooze - should appear
    resp_snooze = client.post(
        "/loops/capture",
        json={
            "raw_text": "expired snooze task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "urgency": 0.6,
        },
    )
    snooze_id = resp_snooze.json()["id"]
    client.patch(
        f"/loops/{snooze_id}",
        json={"next_action": "do after snooze", "snooze_until_utc": past},
    )

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # Collect all item IDs from all buckets
    all_ids: set[int] = set()
    for bucket in data.values():
        for item in bucket:
            all_ids.add(item.get("id"))

    # All candidates should be found
    assert actionable_id in all_ids, "Actionable task should be in results"
    assert inbox_id in all_ids, "Inbox item with next_action should be in results"
    assert snooze_id in all_ids, "Expired snooze task should be in results"


def test_next_loops_excludes_non_candidate_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that blocked, scheduled, dropped, and completed loops are excluded."""
    client = make_test_client()
    captured_at = _now_iso()

    # Create loops and transition them to various non-candidate statuses
    for status in ["blocked", "scheduled", "dropped"]:
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"{status} task",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
            },
        )
        loop_id = resp.json()["id"]
        client.patch(f"/loops/{loop_id}", json={"next_action": "some action"})
        client.post(f"/loops/{loop_id}/status", json={"status": status})

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # None of the non-candidate items should appear
    all_titles: list[str] = []
    for bucket_items in data.values():
        all_titles.extend(item.get("title") or item.get("raw_text", "") for item in bucket_items)

    assert not any("blocked" in t for t in all_titles)
    assert not any("scheduled" in t for t in all_titles)
    assert not any("dropped" in t for t in all_titles)


def test_next_loops_snooze_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that snooze boundary conditions are handled correctly."""
    client = make_test_client()
    captured_at = _now_iso()
    now = datetime.now(timezone.utc)

    # 1. Snoozed in past - SHOULD appear (snooze has expired)
    past = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "past snooze task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_past = resp.json()["id"]
    client.patch(
        f"/loops/{loop_id_past}",
        json={"next_action": "do this", "snooze_until_utc": past},
    )

    # 2. Snoozed exactly at now - SHOULD appear (snooze is expired)
    current = now.isoformat(timespec="seconds")
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "current snooze task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_current = resp.json()["id"]
    client.patch(
        f"/loops/{loop_id_current}",
        json={"next_action": "do now", "snooze_until_utc": current},
    )

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    all_titles: list[str] = []
    for bucket_items in data.values():
        all_titles.extend(item.get("title") or item.get("raw_text", "") for item in bucket_items)

    # Both past and current snoozed tasks should appear
    assert any("past snooze task" in t for t in all_titles)
    assert any("current snooze task" in t for t in all_titles)


def test_next_loops_empty_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that empty result is handled gracefully when no candidates match."""
    client = make_test_client()

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # Should return all buckets, even if empty
    assert "due_soon" in data
    assert "quick_wins" in data
    assert "high_leverage" in data
    assert "standard" in data

    # All buckets should be empty lists
    assert data["due_soon"] == []
    assert data["quick_wins"] == []
    assert data["high_leverage"] == []
    assert data["standard"] == []


def test_loop_capture_and_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    captured_at = _now_iso()

    capture_payloads = [
        {"raw_text": "alpha", "actionable": True},
        {"raw_text": "bravo", "blocked": True},
        {"raw_text": "charlie", "scheduled": True},
        {"raw_text": "delta"},
    ]

    loop_ids: list[int] = []
    for payload in capture_payloads:
        payload.update(
            {
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
            }
        )
        response = client.post("/loops/capture", json=payload)
        assert response.status_code == 200
        loop_ids.append(response.json()["id"])

    open_response = client.get("/loops")
    assert open_response.status_code == 200
    open_statuses = {loop["status"] for loop in open_response.json()}
    assert open_statuses.issubset({"inbox", "actionable", "blocked", "scheduled"})

    close_response = client.post(
        f"/loops/{loop_ids[0]}/status",
        json={"status": "completed"},
    )
    assert close_response.status_code == 200

    refreshed = client.get("/loops")
    assert refreshed.status_code == 200
    assert "completed" not in {loop["status"] for loop in refreshed.json()}

    completed = client.get("/loops", params={"status": "completed"})
    assert completed.status_code == 200
    assert any(loop["status"] == "completed" for loop in completed.json())


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


def test_export_import_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "export me",
            "actionable": True,
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    update = client.patch(
        f"/loops/{loop_id}",
        json={"title": "Exported", "tags": ["Backup"], "completion_note": "archived"},
    )
    assert update.status_code == 200

    export_response = client.get("/loops/export")
    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload["loops"]
    assert export_payload["loops"][0]["completion_note"] == "archived"

    fresh_dir = tmp_path / "imported"
    fresh_dir.mkdir()
    fresh_client = make_test_client(data_dir=fresh_dir)
    import_response = fresh_client.post("/loops/import", json={"loops": export_payload["loops"]})
    assert import_response.status_code == 200
    assert import_response.json()["imported"] == len(export_payload["loops"])

    imported_loops = fresh_client.get("/loops", params={"status": "all"})
    assert imported_loops.status_code == 200
    imported_payload = imported_loops.json()
    assert imported_payload
    assert imported_payload[0]["completion_note"] == "archived"


def test_bucketize_returns_standard_for_low_importance(test_settings) -> None:
    """Low importance loops should NOT be classified as high_leverage."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    # Loop with low importance, not due soon, not a quick win
    loop = {
        "importance": 0.1,
        "time_minutes": 120,
        "activation_energy": 3,
        # No due_at_utc, so not due_soon
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard", f"Expected 'standard' for low importance loop, got '{result}'"


def test_bucketize_returns_high_leverage_for_high_importance(test_settings) -> None:
    """High importance loops should be classified as high_leverage."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.8,
        "time_minutes": 120,
        "activation_energy": 3,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "high_leverage"


def test_bucketize_returns_due_soon_for_urgent_due_date(test_settings) -> None:
    """Loops due within 48h should be due_soon regardless of other factors."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.9,  # High importance
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
        "time_minutes": 5,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "due_soon"


def test_bucketize_returns_quick_wins_for_small_tasks(test_settings) -> None:
    """Short, low-energy tasks should be quick_wins."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.9,  # High importance
        "time_minutes": 10,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "quick_wins"


def test_bucketize_handles_none_importance(test_settings) -> None:
    """Loops without importance should default to standard."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard"


def test_bucketize_importance_boundary_high(test_settings) -> None:
    """Loop with importance exactly 0.7 should be high_leverage."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.7,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "high_leverage"


def test_bucketize_importance_boundary_low(test_settings) -> None:
    """Loop with importance just below 0.7 should be standard."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.69,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard"


def test_list_loops_query_count_not_n_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Verify that listing loops uses O(1) queries, not O(n) queries.

    This is a regression test for the N+1 query problem where each loop
    would trigger 2 additional queries (for project and tags).
    """
    import sqlite3

    from cloop.loops import repo, service
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create test data: 10 loops with projects and tags
    project_id = repo.upsert_project(name="TestProject", conn=conn)
    loop_ids: list[int] = []
    for i in range(10):
        record = repo.create_loop(
            raw_text=f"Loop {i}",
            captured_at_utc="2024-01-01T00:00:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        loop_ids.append(record.id)
        # Update with project
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"project_id": project_id},
            conn=conn,
        )
        # Add tags
        repo.replace_loop_tags(loop_id=record.id, tag_names=[f"tag{i}", "common"], conn=conn)

    # Create a connection wrapper to count queries
    class CountingConnection:
        """Wrapper that counts execute calls."""

        def __init__(self, conn: sqlite3.Connection):
            self._conn = conn
            self.execute_count = 0

        def execute(self, *args, **kwargs):
            self.execute_count += 1
            return self._conn.execute(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    counting_conn = CountingConnection(conn)

    # Call list_loops with the counting wrapper
    result = service.list_loops(status=None, limit=100, offset=0, conn=counting_conn)

    # Should have exactly 10 loops
    assert len(result) == 10

    # With batch fetching, we expect:
    # 1 query for loops + 1 query for projects + 1 query for tags = 3 queries
    # Without batch fetching (N+1), we'd have: 1 + 10 + 10 = 21 queries
    assert counting_conn.execute_count <= 3, (
        f"Expected <= 3 queries with batch fetching, got {counting_conn.execute_count}"
    )

    # Verify deterministic ordering (latest/highest id first) and data integrity.
    assert [loop["id"] for loop in result] == sorted(loop_ids, reverse=True)

    for loop in result:
        raw_text = loop["raw_text"]
        suffix = raw_text.split(" ", maxsplit=1)[1]
        tag_number = int(suffix)
        assert raw_text == f"Loop {tag_number}"
        assert loop["project"] == "TestProject"
        assert "common" in loop["tags"]
        assert f"tag{tag_number}" in loop["tags"]

    conn.close()


def test_fetch_loop_embeddings_with_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that fetch_loop_embeddings respects the limit parameter."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create test loops with embeddings
    for i in range(5):
        loop = repo.create_loop(
            raw_text=f"Test loop {i}",
            captured_at_utc="2024-01-01T00:00:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        repo.upsert_loop_embedding(
            loop_id=loop.id,
            embedding_blob=b"\x00" * 16,  # 4 floats
            embedding_dim=4,
            embedding_norm=1.0,
            embed_model="test",
            conn=conn,
        )

    # Test with limit
    limited = repo.fetch_loop_embeddings(conn=conn, limit=3)
    assert len(limited) == 3

    # Test without limit
    all_rows = repo.fetch_loop_embeddings(conn=conn, limit=None)
    assert len(all_rows) == 5

    # Test with exclude_loop_id
    excluded = repo.fetch_loop_embeddings(conn=conn, exclude_loop_id=1)
    assert len(excluded) == 4
    assert all(row["loop_id"] != 1 for row in excluded)

    # Test with both limit and exclude_loop_id
    limited_excluded = repo.fetch_loop_embeddings(conn=conn, limit=2, exclude_loop_id=1)
    assert len(limited_excluded) <= 2
    assert all(row["loop_id"] != 1 for row in limited_excluded)

    conn.close()


def test_find_related_loops_respects_max_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that find_related_loops respects the related_max_candidates setting."""
    import sqlite3

    import numpy as np

    from cloop.db import init_core_db
    from cloop.loops import repo
    from cloop.loops.models import LoopStatus
    from cloop.loops.related import find_related_loops

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_RELATED_MAX_CANDIDATES", "2")
    get_settings.cache_clear()
    settings = get_settings()
    init_core_db(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create test loops with different embeddings
    query_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    for i in range(5):
        loop = repo.create_loop(
            raw_text=f"Test loop {i}",
            captured_at_utc="2024-01-01T00:00:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        # Create embeddings with varying similarity to query
        vec = np.array([0.9 if j == i % 4 else 0.1 for j in range(4)], dtype=np.float32)
        vec = vec / np.linalg.norm(vec)
        repo.upsert_loop_embedding(
            loop_id=loop.id,
            embedding_blob=vec.tobytes(),
            embedding_dim=4,
            embedding_norm=float(np.linalg.norm(vec)),
            embed_model="test",
            conn=conn,
        )

    # With max_candidates=2, we fetch at most 2 embeddings (excluding loop_id=1)
    # With ORDER BY loop_id, we get loops 2 and 3 (since loop 1 is excluded)
    related = find_related_loops(
        loop_id=1,
        query_vec=query_vec,
        threshold=0.0,
        top_k=10,
        conn=conn,
        settings=settings,
    )
    # We should get exactly 2 related loops (loops 2 and 3 from the LIMIT 2)
    assert len(related) == 2

    conn.close()


def test_find_related_loops_scalability_docstring() -> None:
    """Verify find_related_loops has scalability documentation."""
    from cloop.loops.related import find_related_loops

    docstring = find_related_loops.__doc__
    assert docstring is not None
    assert "O(n)" in docstring or "scalability" in docstring.lower()
    assert "memory" in docstring.lower() or "computation" in docstring.lower()


def test_search_loops_escapes_like_wildcards_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that % in search query is escaped and treated literally."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create loops with text containing % and similar patterns
    repo.create_loop(
        raw_text="50% discount on all items",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.create_loop(
        raw_text="500 discount offer",  # Should NOT match "50%"
        captured_at_utc="2024-01-02T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.create_loop(
        raw_text="50 percent off",  # Should NOT match "50%"
        captured_at_utc="2024-01-03T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Search for "50%" - should only match the first loop
    results = repo.search_loops(query="50%", limit=10, offset=0, conn=conn)

    # Should find only the loop with literal "50%"
    assert len(results) == 1
    assert "50%" in results[0].raw_text

    conn.close()


def test_search_loops_escapes_like_wildcards_underscore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that _ in search query is escaped and treated literally."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create loops with text containing _ and similar patterns
    repo.create_loop(
        raw_text="test_file.py needs review",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.create_loop(
        raw_text="testAfile.py is something else",  # Should NOT match "test_file"
        captured_at_utc="2024-01-02T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.create_loop(
        raw_text="testBfile.py is another",  # Should NOT match "test_file"
        captured_at_utc="2024-01-03T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Search for "test_file" - should only match the first loop
    results = repo.search_loops(query="test_file", limit=10, offset=0, conn=conn)

    # Should find only the loop with literal "test_file"
    assert len(results) == 1
    assert "test_file" in results[0].raw_text

    conn.close()


def test_search_loops_escapes_backslash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that backslash in search query is properly escaped."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop with backslash in text
    repo.create_loop(
        raw_text="Path is C:\\Users\\test",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.create_loop(
        raw_text="Some other text",
        captured_at_utc="2024-01-02T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Search for "C:\Users" - should match
    results = repo.search_loops(query="C:\\Users", limit=10, offset=0, conn=conn)

    # Should find the loop with the backslash path
    assert len(results) == 1
    assert "C:\\Users" in results[0].raw_text

    conn.close()


# =============================================================================
# _extract_json() tests for robust JSON extraction from LLM responses
# =============================================================================


def test_extract_json_plain():
    """Plain JSON object."""
    from cloop.loops.enrichment import _extract_json

    assert _extract_json('{"key": "value"}') == {"key": "value"}


def test_extract_json_with_whitespace():
    """JSON with surrounding whitespace."""
    from cloop.loops.enrichment import _extract_json

    assert _extract_json('  {"key": "value"}  ') == {"key": "value"}


def test_extract_json_markdown_block():
    """JSON wrapped in markdown code block."""
    from cloop.loops.enrichment import _extract_json

    payload = """```json
{"key": "value"}
```"""
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_markdown_block_no_lang():
    """Markdown block without language specifier."""
    from cloop.loops.enrichment import _extract_json

    payload = """```
{"key": "value"}
```"""
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_markdown_block_inline():
    """Markdown block on single line."""
    from cloop.loops.enrichment import _extract_json

    assert _extract_json('```json\n{"key": "value"}\n```') == {"key": "value"}
    assert _extract_json('```\n{"key": "value"}\n```') == {"key": "value"}


def test_extract_json_with_text_before():
    """Text before JSON object."""
    from cloop.loops.enrichment import _extract_json

    payload = 'Here is the result: {"key": "value"}'
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_with_brace_in_text():
    """Brace character in text before JSON (the original bug case)."""
    from cloop.loops.enrichment import _extract_json

    payload = 'Here\'s the data: {"key": "value"}'
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_nested_braces():
    """Nested braces in JSON values."""
    from cloop.loops.enrichment import _extract_json

    payload = '{"query": "SELECT * FROM {table}"}'
    assert _extract_json(payload) == {"query": "SELECT * FROM {table}"}


def test_extract_json_with_text_after():
    """Text after JSON object."""
    from cloop.loops.enrichment import _extract_json

    payload = '{"key": "value"} Hope this helps!'
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_with_text_before_and_after():
    """Text before and after JSON object."""
    from cloop.loops.enrichment import _extract_json

    payload = 'Here is the result: {"key": "value"} Hope this helps!'
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_invalid_no_braces():
    """No JSON object in payload."""
    from cloop.loops.enrichment import _extract_json
    from cloop.loops.errors import ValidationError

    with pytest.raises(ValidationError, match="Invalid response"):
        _extract_json("Just some text")


def test_extract_json_invalid_not_dict():
    """JSON that's not a dict."""
    from cloop.loops.enrichment import _extract_json
    from cloop.loops.errors import ValidationError

    with pytest.raises(ValidationError, match="Invalid response"):
        _extract_json('["just", "a", "list"]')


def test_extract_json_markdown_with_text():
    """Markdown block with surrounding text."""
    from cloop.loops.enrichment import _extract_json

    payload = """Here you go:

```json
{"key": "value"}
```

Let me know if you need more help!"""
    assert _extract_json(payload) == {"key": "value"}


def test_extract_json_complex_nested():
    """Complex nested JSON structure."""
    from cloop.loops.enrichment import _extract_json

    payload = """
    Here's a complex response:
    {
        "title": "Test Loop",
        "summary": "This is a summary with {special} characters",
        "nested": {
            "array": [1, 2, 3],
            "object": {"a": "b"}
        },
        "confidence": {
            "title": 0.95,
            "summary": 0.8
        }
    }
    Does this help?
    """
    result = _extract_json(payload)
    assert result["title"] == "Test Loop"
    assert result["nested"]["array"] == [1, 2, 3]
    assert result["confidence"]["title"] == 0.95


def test_extract_json_empty_string():
    """Empty string should raise ValidationError."""
    from cloop.loops.enrichment import _extract_json
    from cloop.loops.errors import ValidationError

    with pytest.raises(ValidationError, match="Invalid response"):
        _extract_json("")


def test_extract_json_whitespace_only():
    """Whitespace only should raise ValidationError."""
    from cloop.loops.enrichment import _extract_json
    from cloop.loops.errors import ValidationError

    with pytest.raises(ValidationError, match="Invalid response"):
        _extract_json("   \n\t  ")


def test_extract_json_unicode_content():
    """Unicode content should be preserved correctly."""
    from cloop.loops.enrichment import _extract_json

    payload = '{"title": "测试", "emoji": "🚀", "text": "café naïve"}'
    result = _extract_json(payload)
    assert result["title"] == "测试"
    assert result["emoji"] == "🚀"
    assert result["text"] == "café naïve"


def test_extract_json_multiple_objects():
    """Multiple JSON objects - should return first valid dict."""
    from cloop.loops.enrichment import _extract_json

    payload = '{"first": 1} {"second": 2}'
    result = _extract_json(payload)
    assert result == {"first": 1}


def test_extract_json_markdown_case_insensitive():
    """Markdown code block language specifier is case insensitive."""
    from cloop.loops.enrichment import _extract_json

    assert _extract_json('```JSON\n{"key": "value"}\n```') == {"key": "value"}
    assert _extract_json('```Json\n{"key": "value"}\n```') == {"key": "value"}


def test_extract_json_malformed_in_markdown():
    """Malformed JSON inside markdown falls back to brace matching."""
    from cloop.loops.enrichment import _extract_json

    # The inner markdown is malformed, but there's valid JSON to find
    payload = """```json
    not valid json here
```
    But here is valid JSON: {"key": "value"}"""
    assert _extract_json(payload) == {"key": "value"}


# =============================================================================
# JSON parsing error handling tests
# =============================================================================


def test_parse_json_list_raises_on_malformed_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that malformed JSON in user_locks_json field raises ValueError."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop with valid JSON initially
    record = repo.create_loop(
        raw_text="test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Directly corrupt the user_locks_json field in the database
    conn.execute(
        "UPDATE loops SET user_locks_json = ? WHERE id = ?",
        ('{"invalid json missing closing', record.id),
    )
    conn.commit()

    # Reading the corrupted record should raise ValueError
    with pytest.raises(ValueError, match="Failed to parse JSON list"):
        repo.read_loop(loop_id=record.id, conn=conn)

    conn.close()


def test_parse_json_dict_raises_on_malformed_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that malformed JSON in provenance_json field raises ValueError."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop with valid JSON initially
    record = repo.create_loop(
        raw_text="test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Directly corrupt the provenance_json field in the database
    conn.execute(
        "UPDATE loops SET provenance_json = ? WHERE id = ?",
        ("[invalid json starts with bracket", record.id),
    )
    conn.commit()

    # Reading the corrupted record should raise ValueError
    with pytest.raises(ValueError, match="Failed to parse JSON dict"):
        repo.read_loop(loop_id=record.id, conn=conn)

    conn.close()


def test_parse_json_list_truncates_long_value_in_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that very long malformed JSON values are truncated in the error message."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Create a very long malformed JSON string (> 200 chars)
    long_malformed = '{"key": "' + "x" * 500 + '" missing closing brace'

    # Corrupt the field
    conn.execute(
        "UPDATE loops SET user_locks_json = ? WHERE id = ?",
        (long_malformed, record.id),
    )
    conn.commit()

    # Reading the corrupted record should raise ValueError with truncated message
    with pytest.raises(ValueError, match="Failed to parse JSON list") as exc_info:
        repo.read_loop(loop_id=record.id, conn=conn)

    # Verify the error message contains truncated raw value
    error_msg = str(exc_info.value)
    assert "Raw value:" in error_msg
    # The raw value should be truncated to ~200 chars
    assert len(error_msg) < 300  # Reasonable upper bound for truncated message

    conn.close()


# =============================================================================
# Timestamp validation tests
# =============================================================================


def test_loop_capture_invalid_timestamp_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid captured_at format returns 400 with clear error."""
    client = make_test_client()

    invalid_timestamps = [
        "not-a-timestamp",
        "2024-13-45T99:99:99",  # Invalid date/time values
        "2024/01/15 10:30:00",  # Wrong format entirely
        "",  # Empty string
        "   ",  # Whitespace only
    ]

    for invalid_ts in invalid_timestamps:
        response = client.post(
            "/loops/capture",
            json={
                "raw_text": "test",
                "captured_at": invalid_ts,
                "client_tz_offset_min": 0,
            },
        )
        assert response.status_code == 400, f"Expected 400 for '{invalid_ts}'"
        error_detail = response.json()
        assert "error" in error_detail
        # Check that the error message mentions validation
        error_str = str(error_detail).lower()
        assert "invalid captured_at" in error_str or "validation" in error_str


def test_loop_update_invalid_due_at_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid due_at_utc format returns 400 with clear error."""
    client = make_test_client()

    # Create a loop first
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Try to update with invalid timestamp
    response = client.patch(
        f"/loops/{loop_id}",
        json={"due_at_utc": "not-a-valid-timestamp"},
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail
    error_str = str(error_detail).lower()
    assert "invalid due_at_utc" in error_str or "validation" in error_str


def test_loop_update_invalid_snooze_until_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid snooze_until_utc format returns 400 with clear error."""
    client = make_test_client()

    # Create a loop first
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Try to update with invalid timestamp
    response = client.patch(
        f"/loops/{loop_id}",
        json={"snooze_until_utc": "2024-13-45T99:99:99"},
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail


def test_loop_capture_valid_timestamp_with_z_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that timestamps with Z suffix are accepted."""
    client = make_test_client()

    # Use Z suffix (UTC indicator)
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test with Z suffix",
            "captured_at": "2024-01-15T10:30:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    assert response.json()["raw_text"] == "test with Z suffix"


def test_loop_capture_valid_timestamp_with_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that timestamps with timezone offset are accepted."""
    client = make_test_client()

    # Use timezone offset
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test with offset",
            "captured_at": "2024-01-15T10:30:00-05:00",
            "client_tz_offset_min": -300,
        },
    )
    assert response.status_code == 200
    assert response.json()["raw_text"] == "test with offset"


# =============================================================================
# Timezone offset validation tests
# =============================================================================


def test_validate_tz_offset_rejects_too_high() -> None:
    """Test that validate_tz_offset rejects values > 1440."""
    import pytest

    from cloop.loops.errors import ValidationError
    from cloop.loops.models import validate_tz_offset

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        validate_tz_offset(999999)

    with pytest.raises(ValidationError, match="Invalid custom_field.*outside valid range"):
        validate_tz_offset(1441, "custom_field")


def test_validate_tz_offset_rejects_too_low() -> None:
    """Test that validate_tz_offset rejects values < -1440."""
    import pytest

    from cloop.loops.errors import ValidationError
    from cloop.loops.models import validate_tz_offset

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        validate_tz_offset(-999999)

    with pytest.raises(ValidationError, match="Invalid custom_field.*outside valid range"):
        validate_tz_offset(-1441, "custom_field")


def test_validate_tz_offset_accepts_valid_boundaries() -> None:
    """Test that validate_tz_offset accepts boundary values."""
    from cloop.loops.models import validate_tz_offset

    # Should not raise
    assert validate_tz_offset(-1439) == -1439
    assert validate_tz_offset(0) == 0
    assert validate_tz_offset(1439) == 1439


def test_parse_client_datetime_rejects_invalid_tz_offset() -> None:
    """Test that parse_client_datetime rejects invalid tz_offset_min values."""
    import pytest

    from cloop.loops.errors import ValidationError
    from cloop.loops.models import parse_client_datetime

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=999999)

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-999999)

    # Also reject exactly ±1440 since Python timezone can't handle it
    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=1440)

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-1440)


def test_parse_client_datetime_accepts_valid_tz_offset() -> None:
    """Test that parse_client_datetime accepts valid tz_offset_min values."""
    from cloop.loops.models import parse_client_datetime

    # Should not raise - returns UTC datetime
    result = parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-300)
    assert result is not None

    # Boundary values (Python timezone max is ±1439 minutes)
    parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-1439)
    parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=1439)


def test_loop_capture_invalid_tz_offset_too_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that tz_offset_min > 1440 is rejected with 400."""
    client = make_test_client()

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 999999,
        },
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail
    error_str = str(error_detail).lower()
    assert "invalid client_tz_offset_min" in error_str or "range" in error_str


def test_loop_capture_invalid_tz_offset_too_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that tz_offset_min < -1439 is rejected with 400."""
    client = make_test_client()

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": -999999,
        },
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail


def test_loop_capture_valid_tz_offset_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that boundary values (-1439, 0, 1439) are accepted."""
    client = make_test_client()

    for offset in [-1439, 0, 1439]:
        response = client.post(
            "/loops/capture",
            json={
                "raw_text": f"test with offset {offset}",
                "captured_at": _now_iso(),
                "client_tz_offset_min": offset,
            },
        )
        assert response.status_code == 200, f"Expected 200 for offset {offset}"


# =============================================================================
# update_loop_fields validation tests
# =============================================================================


def test_update_loop_fields_rejects_invalid_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that update_loop_fields raises ValidationError for invalid field names."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.errors import ValidationError
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Try to update with an invalid field name
    with pytest.raises(ValidationError, match="Invalid fields"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"typo_field": "some value"},
            conn=conn,
        )

    # Try with mix of valid and invalid - should still fail
    with pytest.raises(ValidationError, match="Invalid fields"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"title": "Valid title", "another_typo": "bad"},
            conn=conn,
        )

    conn.close()


def test_update_loop_fields_rejects_multiple_invalid_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that error message includes all invalid fields, sorted alphabetically."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.errors import ValidationError
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Try with multiple invalid fields - should list all, sorted
    with pytest.raises(ValidationError, match="alpha_field, zebra_field"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"zebra_field": "z", "alpha_field": "a"},
            conn=conn,
        )

    conn.close()


# =============================================================================
# request_enrichment error handling tests
# =============================================================================


def test_request_enrichment_raises_for_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that request_enrichment raises LoopNotFoundError for non-existent loop."""
    import sqlite3

    from cloop.loops import service
    from cloop.loops.errors import LoopNotFoundError

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Try to request enrichment for a loop that doesn't exist
    with pytest.raises(LoopNotFoundError, match="Loop not found: 99999"):
        service.request_enrichment(loop_id=99999, conn=conn)

    conn.close()


# =============================================================================
# Priority weights configuration tests
# =============================================================================


def test_priority_weights_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Verify that next_loops uses priority weights from settings."""
    import sqlite3

    from cloop.loops import repo, service
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    # Set custom priority weights
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_DUE", "2.0")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_URGENCY", "1.5")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_IMPORTANCE", "0.5")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_TIME_PENALTY", "0.1")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_ACTIVATION_PENALTY", "0.2")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create an actionable loop with next_action
    record = repo.create_loop(
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.update_loop_fields(
        loop_id=record.id,
        fields={"status": LoopStatus.ACTIONABLE.value, "next_action": "Do it"},
        conn=conn,
    )

    # Verify settings have the custom weights
    assert settings.priority_weight_due == 2.0
    assert settings.priority_weight_urgency == 1.5
    assert settings.priority_weight_importance == 0.5
    assert settings.priority_weight_time_penalty == 0.1
    assert settings.priority_weight_activation_penalty == 0.2

    # Call next_loops with custom settings - should not raise
    result = service.next_loops(limit=10, conn=conn, settings=settings)

    # Should have buckets
    assert "due_soon" in result
    assert "quick_wins" in result
    assert "high_leverage" in result
    assert "standard" in result

    conn.close()


def test_resolve_status_from_flags() -> None:
    """Test resolve_status_from_flags precedence logic."""
    from cloop.loops.models import resolve_status_from_flags

    # Single flag tests
    assert resolve_status_from_flags(True, False, False) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(False, True, False) == LoopStatus.BLOCKED
    assert resolve_status_from_flags(False, False, True) == LoopStatus.ACTIONABLE
    assert resolve_status_from_flags(False, False, False) == LoopStatus.INBOX

    # Precedence tests
    assert resolve_status_from_flags(True, True, True) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(True, True, False) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(True, False, True) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(False, True, True) == LoopStatus.BLOCKED


def test_is_terminal_status_completed() -> None:
    from cloop.loops.models import is_terminal_status

    assert is_terminal_status(LoopStatus.COMPLETED) is True


def test_is_terminal_status_dropped() -> None:
    from cloop.loops.models import is_terminal_status

    assert is_terminal_status(LoopStatus.DROPPED) is True


def test_is_terminal_status_non_terminal() -> None:
    from cloop.loops.models import is_terminal_status

    for status in (
        LoopStatus.INBOX,
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
    ):
        assert is_terminal_status(status) is False, f"{status} should not be terminal"


def test_terminal_statuses_constant() -> None:
    from cloop.loops.models import TERMINAL_STATUSES

    assert TERMINAL_STATUSES == frozenset({LoopStatus.COMPLETED, LoopStatus.DROPPED})


# =============================================================================
# Idempotency tests
# =============================================================================


def test_loop_capture_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload returns same response without duplicate loop."""
    import sqlite3

    client = make_test_client()

    payload = {
        "raw_text": "idempotent test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "test-key-123"}

    response1 = client.post("/loops/capture", json=payload, headers=headers)
    assert response1.status_code == 200
    loop_id_1 = response1.json()["id"]

    response2 = client.post("/loops/capture", json=payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["id"] == loop_id_1

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_loop_capture_idempotency_concurrent_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Concurrent same-key capture requests replay a single created loop."""
    import sqlite3

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    payload = {
        "raw_text": "concurrent idempotency test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "concurrent-key-1"}

    def _capture_once() -> tuple[int, int]:
        with TestClient(app) as client:
            response = client.post("/loops/capture", json=payload, headers=headers)
        return response.status_code, response.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: _capture_once(), range(4)))

    statuses = [status for status, _loop_id in results]
    ids = [loop_id for _status, loop_id in results]
    assert statuses == [200, 200, 200, 200]
    assert len(set(ids)) == 1

    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_loop_capture_idempotency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + different payload returns 409 Conflict."""
    client = make_test_client()

    payload1 = {
        "raw_text": "first text",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "conflict-key"}

    response1 = client.post("/loops/capture", json=payload1, headers=headers)
    assert response1.status_code == 200

    payload2 = {
        "raw_text": "different text",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    response2 = client.post("/loops/capture", json=payload2, headers=headers)
    assert response2.status_code == 409
    assert "idempotency_key_conflict" in str(response2.json())


def test_loop_update_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload for update returns same response."""
    import sqlite3

    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    update_payload = {"title": "Updated Title"}
    headers = {"Idempotency-Key": "update-key-456"}

    response1 = client.patch(f"/loops/{loop_id}", json=update_payload, headers=headers)
    assert response1.status_code == 200

    response2 = client.patch(f"/loops/{loop_id}", json=update_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["title"] == "Updated Title"

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM loop_events WHERE loop_id = ?", (loop_id,)
        ).fetchone()[0]
    assert count <= 2


def test_loop_status_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload for status change returns same response."""
    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "status test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    status_payload = {"status": "actionable"}
    headers = {"Idempotency-Key": "status-key-789"}

    response1 = client.post(f"/loops/{loop_id}/status", json=status_payload, headers=headers)
    assert response1.status_code == 200
    assert response1.json()["status"] == "actionable"

    response2 = client.post(f"/loops/{loop_id}/status", json=status_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["status"] == "actionable"


def test_loop_close_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload for close returns same response."""
    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "close test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    close_payload = {"status": "completed", "note": "Done"}
    headers = {"Idempotency-Key": "close-key-abc"}

    response1 = client.post(f"/loops/{loop_id}/close", json=close_payload, headers=headers)
    assert response1.status_code == 200
    assert response1.json()["status"] == "completed"
    assert response1.json()["completion_note"] == "Done"

    response2 = client.post(f"/loops/{loop_id}/close", json=close_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["status"] == "completed"
    assert response2.json()["completion_note"] == "Done"


def test_idempotency_key_validation_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Empty idempotency key is rejected."""
    client = make_test_client()

    payload = {
        "raw_text": "test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "   "}

    response = client.post("/loops/capture", json=payload, headers=headers)
    assert response.status_code == 400


def test_no_idempotency_key_creates_separate_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Without idempotency key, same payload creates separate loops."""
    import sqlite3

    client = make_test_client()

    payload = {
        "raw_text": "no key test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }

    response1 = client.post("/loops/capture", json=payload)
    assert response1.status_code == 200
    loop_id_1 = response1.json()["id"]

    response2 = client.post("/loops/capture", json=payload)
    assert response2.status_code == 200
    loop_id_2 = response2.json()["id"]

    assert loop_id_1 != loop_id_2

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 2


def test_different_scopes_allow_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key can be used for different operations."""
    import sqlite3

    client = make_test_client()

    payload = {
        "raw_text": "scope test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "same-key-different-scope"}

    response1 = client.post("/loops/capture", json=payload, headers=headers)
    assert response1.status_code == 200
    loop_id = response1.json()["id"]

    update_payload = {"title": "Updated"}
    response2 = client.patch(f"/loops/{loop_id}", json=update_payload, headers=headers)
    assert response2.status_code == 200

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_idempotency_key_validation_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Very long idempotency key is rejected."""
    client = make_test_client()

    payload = {
        "raw_text": "test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "x" * 300}

    response = client.post("/loops/capture", json=payload, headers=headers)
    assert response.status_code == 400


def test_loop_import_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Idempotency key works for import endpoint."""
    import sqlite3

    client = make_test_client()

    now_iso = _now_iso()
    import_payload = {
        "loops": [
            {
                "raw_text": "imported loop",
                "status": "inbox",
                "captured_at_utc": now_iso,
                "captured_tz_offset_min": 0,
                "created_at_utc": now_iso,
                "updated_at_utc": now_iso,
            }
        ]
    }
    headers = {"Idempotency-Key": "import-key"}

    response1 = client.post("/loops/import", json=import_payload, headers=headers)
    assert response1.status_code == 200
    imported_count_1 = response1.json()["imported"]

    response2 = client.post("/loops/import", json=import_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["imported"] == imported_count_1

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == imported_count_1


def test_loop_enrich_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Idempotency key works for enrich endpoint."""
    from unittest.mock import patch

    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "enrich test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    headers = {"Idempotency-Key": "enrich-key"}

    mock_response = {
        "choices": [{"message": {"content": '{"title": "Test", "confidence": {"title": 0.9}}'}}]
    }

    with patch("cloop.loops.enrichment.litellm.completion", return_value=mock_response):
        response1 = client.post(f"/loops/{loop_id}/enrich", headers=headers)
        assert response1.status_code == 200

        response2 = client.post(f"/loops/{loop_id}/enrich", headers=headers)
        assert response2.status_code == 200


def test_idempotency_expiry_allows_new_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """After idempotency key expires, same key can create new loop."""
    import sqlite3

    client = make_test_client()
    settings = get_settings()

    payload = {
        "raw_text": "expiry test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "expiring-key"}

    response1 = client.post("/loops/capture", json=payload, headers=headers)
    assert response1.status_code == 200
    loop_id_1 = response1.json()["id"]

    with sqlite3.connect(settings.core_db_path) as conn:
        conn.execute(
            """
            UPDATE idempotency_keys
            SET expires_at = '2000-01-01T00:00:00+00:00'
            WHERE scope = 'http:POST:/loops/capture'
              AND idempotency_key = ?
            """,
            ("expiring-key",),
        )
        conn.commit()

    response2 = client.post("/loops/capture", json=payload, headers=headers)
    assert response2.status_code == 200
    loop_id_2 = response2.json()["id"]

    assert loop_id_1 != loop_id_2

    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 2


def test_different_loop_ids_create_different_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key can be used for different loop IDs."""
    client = make_test_client()

    create1 = client.post(
        "/loops/capture",
        json={
            "raw_text": "loop 1",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id_1 = create1.json()["id"]

    create2 = client.post(
        "/loops/capture",
        json={
            "raw_text": "loop 2",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id_2 = create2.json()["id"]

    headers = {"Idempotency-Key": "same-update-key"}

    update_payload = {"title": "Updated"}

    response1 = client.patch(f"/loops/{loop_id_1}", json=update_payload, headers=headers)
    assert response1.status_code == 200

    response2 = client.patch(f"/loops/{loop_id_2}", json=update_payload, headers=headers)
    assert response2.status_code == 200

    get1 = client.get(f"/loops/{loop_id_1}")
    get2 = client.get(f"/loops/{loop_id_2}")
    assert get1.json()["title"] == "Updated"
    assert get2.json()["title"] == "Updated"


# =============================================================================
# SSE Event Stream tests
# =============================================================================


def test_loop_events_sse_endpoint_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test SSE stream endpoint exists (can't test infinite stream easily)."""
    # The SSE stream runs forever with a while True loop, so we just verify
    # the route exists and would return streaming content type by checking the route
    from cloop.routes.loops import router

    route_paths = [route.path for route in router.routes]  # type: ignore[misc]
    assert "/loops/events/stream" in route_paths


# =============================================================================
# Webhook tests
# =============================================================================


def test_webhook_subscription_crud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook subscription CRUD operations."""
    client = make_test_client()

    # Create subscription
    create_response = client.post(
        "/loops/webhooks/subscriptions",
        json={
            "url": "https://example.com/webhook",
            "event_types": ["capture", "update"],
            "description": "Test webhook",
        },
    )
    assert create_response.status_code == 200
    sub = create_response.json()
    assert sub["url"] == "https://example.com/webhook"
    assert sub["event_types"] == ["capture", "update"]
    assert sub["active"] is True
    assert sub["description"] == "Test webhook"
    subscription_id = sub["id"]

    # List subscriptions
    list_response = client.get("/loops/webhooks/subscriptions")
    assert list_response.status_code == 200
    subs = list_response.json()
    assert len(subs) == 1
    assert subs[0]["id"] == subscription_id

    # Update subscription
    update_response = client.patch(
        f"/loops/webhooks/subscriptions/{subscription_id}",
        json={
            "url": "https://example.com/webhook/v2",
            "active": False,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["url"] == "https://example.com/webhook/v2"
    assert updated["active"] is False

    # Delete subscription
    delete_response = client.delete(f"/loops/webhooks/subscriptions/{subscription_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    # Verify deletion
    list_after = client.get("/loops/webhooks/subscriptions")
    assert len(list_after.json()) == 0


def test_webhook_subscription_url_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook subscription URL validation."""
    client = make_test_client()

    # Invalid URL without http/https
    response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "ftp://example.com/webhook"},
    )
    assert response.status_code == 422

    # Valid https URL
    response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "https://example.com/webhook"},
    )
    assert response.status_code == 200


def test_webhook_subscription_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook subscription endpoints return 404 for non-existent subscription."""
    client = make_test_client()

    # Update non-existent
    response = client.patch(
        "/loops/webhooks/subscriptions/99999",
        json={"active": False},
    )
    assert response.status_code == 404

    # Delete non-existent
    response = client.delete("/loops/webhooks/subscriptions/99999")
    assert response.status_code == 404

    # Get deliveries for non-existent
    response = client.get("/loops/webhooks/subscriptions/99999/deliveries")
    assert response.status_code == 404


def test_webhook_signature_generation_and_verification() -> None:
    """Test HMAC-SHA256 signature generation and verification."""
    import time

    from cloop.webhooks.signer import generate_signature, verify_signature

    payload = {"loop_id": 123, "event_type": "capture"}
    secret = "test_secret_key"
    timestamp = str(int(time.time()))  # Use current timestamp for replay protection

    # Generate signature
    signature = generate_signature(payload, secret, timestamp)
    assert signature.startswith(f"t={timestamp},v1=")

    # Verify valid signature
    assert verify_signature(payload, secret, signature) is True

    # Verify with wrong secret
    assert verify_signature(payload, "wrong_secret", signature) is False

    # Verify with tampered payload
    tampered_payload = {"loop_id": 999, "event_type": "capture"}
    assert verify_signature(tampered_payload, secret, signature) is False

    # Verify with invalid signature format
    assert verify_signature(payload, secret, "invalid-format") is False

    # Verify with expired timestamp (replay protection)
    old_timestamp = "1707830400"  # Old timestamp from 2024
    old_signature = generate_signature(payload, secret, old_timestamp)
    assert verify_signature(payload, secret, old_signature) is False


def test_webhook_deliveries_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test listing deliveries for a webhook subscription."""
    client = make_test_client()

    # Create subscription
    sub_response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "https://example.com/webhook", "event_types": ["*"]},
    )
    subscription_id = sub_response.json()["id"]

    # Create a loop to trigger event creation (which queues webhook deliveries)
    client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )

    # List deliveries - should include the automatically queued delivery
    deliveries_response = client.get(f"/loops/webhooks/subscriptions/{subscription_id}/deliveries")
    assert deliveries_response.status_code == 200
    deliveries = deliveries_response.json()
    assert len(deliveries) == 1
    assert deliveries[0]["event_type"] == "capture"
    assert deliveries[0]["status"] == "pending"


def test_webhook_update_no_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook update with no fields returns 400."""
    client = make_test_client()

    # Create subscription
    sub_response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "https://example.com/webhook"},
    )
    subscription_id = sub_response.json()["id"]

    # Update with empty body
    response = client.patch(f"/loops/webhooks/subscriptions/{subscription_id}", json={})
    assert response.status_code == 400
    assert "no_fields_to_update" in response.text


def test_webhook_event_type_filtering() -> None:
    """Test webhook event type filtering logic."""
    from cloop.webhooks.service import _should_deliver_event

    # Wildcard accepts all events
    assert _should_deliver_event("capture", ["*"]) is True
    assert _should_deliver_event("update", ["*"]) is True
    assert _should_deliver_event("close", ["*"]) is True

    # Specific event types
    assert _should_deliver_event("capture", ["capture", "update"]) is True
    assert _should_deliver_event("close", ["capture", "update"]) is False
    assert _should_deliver_event("update", ["update"]) is True

    # Empty list accepts nothing (except via wildcard)
    assert _should_deliver_event("capture", []) is False


def test_webhook_retry_delay_calculation(test_settings) -> None:
    """Test exponential backoff delay calculation."""
    from cloop.webhooks.service import _calculate_retry_delay

    settings = test_settings()

    # First retry should be around base delay (2s) ± jitter
    delay0 = _calculate_retry_delay(0, settings)
    assert 1.0 <= delay0 <= 3.0  # 2s ± 25%

    # Second retry should be around 4s ± jitter
    delay1 = _calculate_retry_delay(1, settings)
    assert 3.0 <= delay1 <= 5.0  # 4s ± 25%

    # Third retry should be around 8s ± jitter
    delay2 = _calculate_retry_delay(2, settings)
    assert 6.0 <= delay2 <= 10.0  # 8s ± 25%

    # High retry count should cap at max_delay
    delay_high = _calculate_retry_delay(100, settings)
    assert delay_high <= settings.webhook_retry_max_delay


def test_webhook_repo_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook repository operations directly."""
    import sqlite3

    from cloop.webhooks import repo
    from cloop.webhooks.models import DeliveryStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create subscription
    sub = repo.create_subscription(
        url="https://example.com/webhook",
        secret="test_secret",
        event_types=["capture", "update"],
        description="Test sub",
        conn=conn,
    )
    assert sub.url == "https://example.com/webhook"
    assert sub.event_types == ["capture", "update"]
    assert sub.active is True

    # Get subscription
    fetched = repo.get_subscription(subscription_id=sub.id, conn=conn)
    assert fetched is not None
    assert fetched.id == sub.id

    # Get non-existent
    not_found = repo.get_subscription(subscription_id=99999, conn=conn)
    assert not_found is None

    # List subscriptions
    subs = repo.list_subscriptions(conn=conn)
    assert len(subs) == 1

    # Update subscription
    updated = repo.update_subscription(
        subscription_id=sub.id,
        active=False,
        conn=conn,
    )
    assert updated is not None
    assert updated.active is False

    # Create delivery
    delivery = repo.create_delivery(
        subscription_id=sub.id,
        event_id=1,
        event_type="capture",
        payload={"test": "data"},
        signature="test_sig",
        conn=conn,
    )
    assert delivery.subscription_id == sub.id
    assert delivery.status == DeliveryStatus.PENDING

    # Update delivery status
    repo.update_delivery_status(
        delivery_id=delivery.id,
        status=DeliveryStatus.SUCCESS,
        http_status=200,
        response_body="OK",
        conn=conn,
    )

    # Get delivery
    fetched_delivery = repo.get_delivery(delivery_id=delivery.id, conn=conn)
    assert fetched_delivery is not None
    assert fetched_delivery.status == DeliveryStatus.SUCCESS
    assert fetched_delivery.http_status == 200

    # List deliveries for subscription
    deliveries = repo.list_deliveries_for_subscription(
        subscription_id=sub.id,
        conn=conn,
    )
    assert len(deliveries) == 1

    # Delete subscription
    deleted = repo.delete_subscription(subscription_id=sub.id, conn=conn)
    assert deleted is True

    # Verify deleted
    assert repo.get_subscription(subscription_id=sub.id, conn=conn) is None

    conn.close()


def test_webhook_queue_deliveries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test queueing webhook deliveries for events."""
    import sqlite3

    from cloop.webhooks import repo, service

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create subscriptions with different event types
    repo.create_subscription(
        url="https://example.com/all",
        secret="secret1",
        event_types=["*"],
        description="All events",
        conn=conn,
    )
    repo.create_subscription(
        url="https://example.com/capture-only",
        secret="secret2",
        event_types=["capture"],
        description="Capture only",
        conn=conn,
    )
    repo.create_subscription(
        url="https://example.com/inactive",
        secret="secret3",
        event_types=["*"],
        description="Inactive",
        conn=conn,
    )
    # Deactivate the third subscription
    conn.execute(
        "UPDATE webhook_subscriptions SET active = 0 WHERE url = ?",
        ("https://example.com/inactive",),
    )
    conn.commit()

    # Queue a capture event - should create deliveries for first two subscriptions
    delivery_ids = service.queue_deliveries(
        event_id=1,
        event_type="capture",
        payload={"test": "data"},
        conn=conn,
        settings=settings,
    )
    assert len(delivery_ids) == 2  # All events + capture-only

    # Queue an update event - should only create delivery for wildcard subscription
    delivery_ids = service.queue_deliveries(
        event_id=2,
        event_type="update",
        payload={"test": "data"},
        conn=conn,
        settings=settings,
    )
    assert len(delivery_ids) == 1  # Only all events subscription

    conn.close()


def test_sse_format_functions() -> None:
    """Test SSE formatting functions."""
    from cloop.sse import format_sse_comment, format_sse_event

    # Test event formatting
    event = format_sse_event("test_event", {"key": "value"}, event_id="123")
    assert "id: 123" in event
    assert "event: test_event" in event
    assert 'data: {"key": "value"}' in event
    assert event.endswith("\n\n")

    # Test event without ID
    event_no_id = format_sse_event("simple", {"data": True})
    assert "id:" not in event_no_id
    assert "event: simple" in event_no_id

    # Test comment formatting
    comment = format_sse_comment("heartbeat")
    assert comment == ": heartbeat\n\n"


def test_settings_webhook_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook settings validation via environment variables."""
    from cloop.settings import get_settings

    # Test invalid webhook_max_retries
    monkeypatch.setenv("CLOOP_WEBHOOK_MAX_RETRIES", "-1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_MAX_RETRIES must be non-negative"):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_MAX_RETRIES", raising=False)
    get_settings.cache_clear()

    # Test invalid webhook_retry_base_delay
    monkeypatch.setenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_RETRY_BASE_DELAY must be positive"):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", raising=False)
    get_settings.cache_clear()

    # Test invalid webhook_retry_max_delay < webhook_retry_base_delay
    monkeypatch.setenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", "10")
    monkeypatch.setenv("CLOOP_WEBHOOK_RETRY_MAX_DELAY", "1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_RETRY_MAX_DELAY must be >="):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", raising=False)
    monkeypatch.delenv("CLOOP_WEBHOOK_RETRY_MAX_DELAY", raising=False)
    get_settings.cache_clear()

    # Test invalid webhook_timeout_seconds
    monkeypatch.setenv("CLOOP_WEBHOOK_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_TIMEOUT_SECONDS must be positive"):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_TIMEOUT_SECONDS", raising=False)
    get_settings.cache_clear()


# =============================================================================
# Loop Claim tests
# =============================================================================


def test_loop_claim_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Successfully claim an unclaimed loop."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim the loop
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 200
    claim = claim_response.json()
    assert claim["loop_id"] == loop_id
    assert claim["owner"] == "agent-1"
    assert "claim_token" in claim
    assert len(claim["claim_token"]) == 64  # 32 bytes = 64 hex chars


def test_loop_claim_already_claimed_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot claim a loop already claimed by another agent."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim the loop with agent-1
    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to claim with agent-2
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 409
    error = claim_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"
    assert error["error"]["details"]["owner"] == "agent-1"


def test_loop_update_claimed_without_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot update a claimed loop without the claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to update without token
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title"},
    )
    assert update_response.status_code == 409
    error = update_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"


def test_loop_update_claimed_with_valid_token_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can update a claimed loop with valid claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Update with token
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title", "claim_token": claim_token},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "New title"


def test_loop_update_claimed_with_invalid_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot update with wrong claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to update with wrong token
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title", "claim_token": "wrong_token_1234567890123456"},
    )
    assert update_response.status_code == 403
    error = update_response.json()
    assert error["error"]["details"]["code"] == "invalid_claim_token"


def test_loop_unclaimed_allows_update_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Unclaimed loops can be updated without token."""
    client = make_test_client()

    # Create a loop (not claimed)
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Update without token should work
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "New title"


def test_loop_renew_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can renew an existing claim."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 60},
    )
    claim_token = claim_response.json()["claim_token"]

    # Renew the claim
    renew_response = client.post(
        f"/loops/{loop_id}/renew",
        json={"claim_token": claim_token, "ttl_seconds": 300},
    )
    assert renew_response.status_code == 200
    renewed = renew_response.json()
    assert renewed["claim_token"] == claim_token
    assert renewed["owner"] == "agent-1"


def test_loop_release_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """After releasing, another agent can claim."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Release the claim
    release_response = client.request(
        "DELETE",
        f"/loops/{loop_id}/claim",
        json={"claim_token": claim_token},
    )
    assert release_response.status_code == 200
    assert release_response.json()["ok"] is True

    # Another agent can now claim
    claim2_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim2_response.status_code == 200
    assert claim2_response.json()["owner"] == "agent-2"


def test_loop_get_claim_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Get claim status returns claim info without token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Get claim status
    status_response = client.get(f"/loops/{loop_id}/claim")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["loop_id"] == loop_id
    assert status["owner"] == "agent-1"
    assert "claim_token" not in status  # Token should NOT be exposed


def test_loop_get_claim_status_unclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Get claim status returns null for unclaimed loop."""
    client = make_test_client()

    # Create a loop (not claimed)
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Get claim status
    status_response = client.get(f"/loops/{loop_id}/claim")
    assert status_response.status_code == 200
    assert status_response.json() is None


def test_loop_list_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """List active claims."""
    client = make_test_client()

    # Create and claim two loops
    create1 = client.post(
        "/loops/capture",
        json={"raw_text": "loop 1", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    loop_id_1 = create1.json()["id"]

    create2 = client.post(
        "/loops/capture",
        json={"raw_text": "loop 2", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    loop_id_2 = create2.json()["id"]

    client.post(f"/loops/{loop_id_1}/claim", json={"owner": "agent-alpha", "ttl_seconds": 300})
    client.post(f"/loops/{loop_id_2}/claim", json={"owner": "agent-beta", "ttl_seconds": 300})

    # List all claims
    list_response = client.get("/loops/claims")
    assert list_response.status_code == 200
    claims = list_response.json()
    assert len(claims) == 2

    # Filter by owner
    alpha_response = client.get("/loops/claims?owner=agent-alpha")
    assert alpha_response.status_code == 200
    alpha_claims = alpha_response.json()
    assert len(alpha_claims) == 1
    assert alpha_claims[0]["owner"] == "agent-alpha"


def test_loop_force_release_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Force-release allows admin to unstick a loop."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Force-release without token
    force_response = client.delete(f"/loops/{loop_id}/claim/force")
    assert force_response.status_code == 200
    assert force_response.json()["released"] is True

    # Verify loop can now be claimed by another
    claim2_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim2_response.status_code == 200


def test_loop_claim_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim operations return 404 for non-existent loop."""
    client = make_test_client()

    claim_response = client.post(
        "/loops/99999/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 404


def test_loop_claim_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim supports idempotency keys for replay protection."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    headers = {"Idempotency-Key": "claim-key-1"}

    # First claim
    claim1 = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
        headers=headers,
    )
    assert claim1.status_code == 200
    token1 = claim1.json()["claim_token"]
    lease_until_1 = claim1.json()["lease_until_utc"]

    # Second claim with same idempotency key and same payload should return original
    claim2 = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
        headers=headers,
    )
    assert claim2.status_code == 200
    # Should be the replayed response with original token
    assert claim2.json()["claim_token"] == token1
    assert claim2.json()["lease_until_utc"] == lease_until_1


def test_settings_claim_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test claim settings validation."""
    from cloop.settings import get_settings

    # Test invalid claim_default_ttl_seconds
    monkeypatch.setenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_CLAIM_DEFAULT_TTL_SECONDS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", raising=False)
    get_settings.cache_clear()

    # Test claim_max_ttl_seconds < claim_default_ttl_seconds
    monkeypatch.setenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", "3600")
    monkeypatch.setenv("CLOOP_CLAIM_MAX_TTL_SECONDS", "60")
    get_settings.cache_clear()
    with pytest.raises(
        ValueError, match="CLOOP_CLAIM_MAX_TTL_SECONDS must be >= CLOOP_CLAIM_DEFAULT_TTL_SECONDS"
    ):
        get_settings()

    monkeypatch.delenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", raising=False)
    monkeypatch.delenv("CLOOP_CLAIM_MAX_TTL_SECONDS", raising=False)
    get_settings.cache_clear()

    # Test invalid claim_token_bytes
    monkeypatch.setenv("CLOOP_CLAIM_TOKEN_BYTES", "8")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_CLAIM_TOKEN_BYTES must be at least 16"):
        get_settings()

    monkeypatch.delenv("CLOOP_CLAIM_TOKEN_BYTES", raising=False)
    get_settings.cache_clear()


def test_loop_claim_expired_allows_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Expired claims allow updates without token (lazy expiration check)."""
    client = make_test_client()

    # Create and claim a loop with short TTL
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim with 1 second TTL (minimum allowed)
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 1},
    )
    assert claim_response.status_code == 200

    # Wait for claim to expire
    import time

    time.sleep(1.5)

    # Update should work without token (claim expired)
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "New title"


def test_loop_claim_expired_allows_new_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """After claim expires, another agent can claim it."""
    client = make_test_client()

    # Create and claim a loop with short TTL
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim with 1 second TTL
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 1},
    )
    assert claim_response.status_code == 200

    # Wait for claim to expire
    import time

    time.sleep(1.5)

    # Another agent can now claim (expired claims are purged on new claim attempt)
    claim2_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim2_response.status_code == 200
    assert claim2_response.json()["owner"] == "agent-2"


def test_loop_claim_token_length_uses_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim token length respects claim_token_bytes setting."""
    # Set custom token length
    monkeypatch.setenv("CLOOP_CLAIM_TOKEN_BYTES", "64")
    from cloop.settings import get_settings

    get_settings.cache_clear()

    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim the loop
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 200
    claim_token = claim_response.json()["claim_token"]

    # Token should be 128 hex characters (64 bytes = 128 hex chars)
    assert len(claim_token) == 128

    # Cleanup
    monkeypatch.delenv("CLOOP_CLAIM_TOKEN_BYTES", raising=False)
    get_settings.cache_clear()


def test_loop_close_claimed_with_valid_token_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can close a claimed loop with valid claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Close with token
    close_response = client.post(
        f"/loops/{loop_id}/close",
        json={"status": "completed", "claim_token": claim_token},
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "completed"


def test_loop_close_claimed_without_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot close a claimed loop without the claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to close without token
    close_response = client.post(
        f"/loops/{loop_id}/close",
        json={"status": "completed"},
    )
    assert close_response.status_code == 409
    error = close_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"


def test_loop_status_claimed_with_valid_token_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can transition status of a claimed loop with valid claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Transition status with token
    status_response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "actionable", "claim_token": claim_token},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "actionable"


def test_loop_status_claimed_without_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot transition status of a claimed loop without the claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to transition without token
    status_response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "actionable"},
    )
    assert status_response.status_code == 409
    error = status_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"


def test_loop_claim_token_not_exposed_in_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim tokens should not be exposed in list_active_claims response."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # List claims
    list_response = client.get("/loops/claims")
    assert list_response.status_code == 200
    claims = list_response.json()
    assert len(claims) == 1

    # Token should NOT be exposed
    assert "claim_token" not in claims[0]
    assert claims[0]["owner"] == "agent-1"
    assert claims[0]["loop_id"] == loop_id


# ==============================================================================
# Recurrence Lifecycle Tests
# ==============================================================================


def test_capture_with_recurrence_sets_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Capturing a loop with recurrence sets recurrence fields."""
    client = make_test_client()

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily standup",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 200
    loop = response.json()

    assert loop["recurrence_enabled"] is True
    assert loop["recurrence_rrule"] is not None
    assert "FREQ=DAILY" in loop["recurrence_rrule"]
    assert loop["recurrence_tz"] == "UTC"
    assert loop["next_due_at_utc"] is not None


def test_complete_recurring_creates_next_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Completing a recurring loop creates the next occurrence."""
    client = make_test_client()

    # Create recurring loop with tags
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily standup",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    assert capture_response.status_code == 200
    loop_id = capture_response.json()["id"]

    # Add tags to the loop
    client.patch(f"/loops/{loop_id}", json={"tags": ["work", "meeting"]})

    # Complete the loop
    status_response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "completed"},
    )
    assert status_response.status_code == 200
    completed = status_response.json()

    # Verify original loop is completed with recurrence disabled
    assert completed["status"] == "completed"
    assert completed["recurrence_enabled"] is False

    # Find the next occurrence via query
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]

    # Should have exactly one recurring loop (the next occurrence)
    assert len(results) == 1
    next_loop = results[0]

    # Verify next occurrence has recurrence enabled
    assert next_loop["recurrence_enabled"] is True
    assert next_loop["recurrence_rrule"] is not None
    assert next_loop["next_due_at_utc"] is not None

    # Verify tags were copied
    assert "work" in next_loop["tags"]
    assert "meeting" in next_loop["tags"]

    # Verify raw_text was copied
    assert next_loop["raw_text"] == "Daily standup"


def test_bulk_close_recurring_creates_next_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Bulk closing a recurring loop creates the next occurrence."""
    import sqlite3

    from cloop.loops import service as loop_service

    client = make_test_client()

    # Create recurring loop
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily standup",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    assert capture_response.status_code == 200
    loop_id = capture_response.json()["id"]

    # Bulk close it using the service directly (no HTTP endpoint for bulk_close)
    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        conn.row_factory = sqlite3.Row
        bulk_result = loop_service.bulk_close_loops(
            items=[{"loop_id": loop_id, "status": "completed"}],
            transactional=True,
            conn=conn,
        )
    assert bulk_result["ok"] is True
    assert bulk_result["succeeded"] == 1

    # Verify original loop is completed
    get_response = client.get(f"/loops/{loop_id}")
    assert get_response.status_code == 200
    original = get_response.json()
    assert original["status"] == "completed"
    assert original["recurrence_enabled"] is False

    # Find the next occurrence
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]

    # Should have exactly one recurring loop (the next occurrence)
    assert len(results) == 1
    next_loop = results[0]
    assert next_loop["recurrence_enabled"] is True


def test_query_recurring_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Query DSL recurring: filter works correctly."""
    client = make_test_client()

    # Create one recurring and one non-recurring loop
    client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily recurring task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "One-time task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )

    # Query for recurring
    recurring_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert recurring_response.status_code == 200
    recurring = recurring_response.json()["items"]
    assert len(recurring) == 1
    assert recurring[0]["raw_text"] == "Daily recurring task"

    # Query for non-recurring
    non_recurring_response = client.post(
        "/loops/search",
        json={"query": "recurring:no", "limit": 100, "offset": 0},
    )
    assert non_recurring_response.status_code == 200
    non_recurring = non_recurring_response.json()["items"]
    assert len(non_recurring) == 1
    assert non_recurring[0]["raw_text"] == "One-time task"


def test_multiple_recurrence_completions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Completing a recurring loop multiple times creates a chain of occurrences."""
    client = make_test_client()

    # Create recurring loop
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Weekly review",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=WEEKLY",
            "timezone": "UTC",
        },
    )
    assert capture_response.status_code == 200
    first_id = capture_response.json()["id"]

    # Complete first occurrence
    client.post(f"/loops/{first_id}/status", json={"status": "completed"})

    # Find the next occurrence
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]
    assert len(results) == 1
    second_id = results[0]["id"]
    assert second_id != first_id

    # Complete second occurrence
    client.post(f"/loops/{second_id}/status", json={"status": "completed"})

    # Find the third occurrence
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]
    assert len(results) == 1
    third_id = results[0]["id"]
    assert third_id != first_id
    assert third_id != second_id

    # Verify we have 2 completed and 1 active recurring loop
    all_response = client.get("/loops?status=all&limit=100")
    assert all_response.status_code == 200
    all_loops = all_response.json()
    completed_count = sum(1 for loop in all_loops if loop["status"] == "completed")
    assert completed_count == 2


# ============================================================================
# Loop Dependency Tests
# ============================================================================


class TestLoopDependencies:
    """Tests for loop dependency functionality."""

    def test_add_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Adding a dependency creates the relationship."""
        client = make_test_client()

        # Create two loops
        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Add dependency: B depends on A
        result = client.post(
            f"/loops/{loop_b['id']}/dependencies",
            json={"depends_on_loop_id": loop_a["id"]},
        ).json()

        assert result["id"] == loop_b["id"]
        assert len(result["dependencies"]) == 1
        assert result["dependencies"][0]["id"] == loop_a["id"]
        assert result["has_open_dependencies"] is True

    def test_cycle_detection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Adding a dependency that creates a cycle is rejected."""
        client = make_test_client()

        # Create three loops
        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_c = client.post(
            "/loops/capture",
            json={
                "raw_text": "C",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # A -> B
        client.post(
            f"/loops/{loop_a['id']}/dependencies", json={"depends_on_loop_id": loop_b["id"]}
        )
        # B -> C
        client.post(
            f"/loops/{loop_b['id']}/dependencies", json={"depends_on_loop_id": loop_c["id"]}
        )

        # Try to create cycle: C -> A (should fail)
        result = client.post(
            f"/loops/{loop_c['id']}/dependencies",
            json={"depends_on_loop_id": loop_a["id"]},
        )
        assert result.status_code == 400
        error = result.json()
        assert error["error"]["type"] == "dependency_cycle"

    def test_self_dependency_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """A loop cannot depend on itself."""
        client = make_test_client()

        loop = client.post(
            "/loops/capture",
            json={
                "raw_text": "Self",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        result = client.post(
            f"/loops/{loop['id']}/dependencies",
            json={"depends_on_loop_id": loop["id"]},
        )
        assert result.status_code == 400
        assert result.json()["error"]["type"] == "dependency_cycle"

    def test_transition_to_actionable_blocked_by_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Cannot transition to actionable while dependencies are open."""
        client = make_test_client()

        # Create blocker (inbox = open)
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Create dependent and add dependency
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent task",
                "actionable": True,
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Transition dependent to blocked
        client.post(f"/loops/{dependent['id']}/status", json={"status": "blocked"})

        # Try to transition to actionable (should fail)
        result = client.post(f"/loops/{dependent['id']}/status", json={"status": "actionable"})
        assert result.status_code == 400
        error = result.json()
        assert error["error"]["type"] == "dependency_not_met"
        assert blocker["id"] in error["error"]["details"]["open_dependencies"]

    def test_transition_allowed_after_dependency_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Can transition to actionable after all dependencies are completed."""
        client = make_test_client()

        # Create blocker
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Create dependent
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Transition dependent to blocked
        client.post(f"/loops/{dependent['id']}/status", json={"status": "blocked"})

        # Complete the blocker
        client.post(f"/loops/{blocker['id']}/status", json={"status": "completed"})

        # Now dependent can transition to actionable
        result = client.post(f"/loops/{dependent['id']}/status", json={"status": "actionable"})
        assert result.status_code == 200
        assert result.json()["status"] == "actionable"

    def test_next_loops_excludes_blocked_by_dependencies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """next_loops excludes loops with open dependencies."""
        client = make_test_client()

        # Create blocker with next_action
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker",
                "actionable": True,
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.patch(f"/loops/{blocker['id']}", json={"next_action": "Do blocker"})

        # Create dependent with next_action
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent",
                "actionable": True,
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.patch(f"/loops/{dependent['id']}", json={"next_action": "Do dependent"})

        # Add dependency: dependent -> blocker
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Get next loops
        result = client.get("/loops/next").json()

        # Should only include blocker, not dependent
        next_ids = [loop["id"] for bucket in result.values() for loop in bucket]
        assert blocker["id"] in next_ids
        assert dependent["id"] not in next_ids

    def test_remove_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Removing a dependency works correctly."""
        client = make_test_client()

        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Add dependency
        client.post(
            f"/loops/{loop_b['id']}/dependencies", json={"depends_on_loop_id": loop_a["id"]}
        )

        # Verify added
        deps = client.get(f"/loops/{loop_b['id']}/dependencies").json()
        assert len(deps) == 1

        # Remove dependency
        client.delete(f"/loops/{loop_b['id']}/dependencies/{loop_a['id']}")

        # Verify removed
        deps = client.get(f"/loops/{loop_b['id']}/dependencies").json()
        assert len(deps) == 0

    def test_blocking_lists_dependents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """blocking endpoint lists loops that depend on this one."""
        client = make_test_client()

        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_c = client.post(
            "/loops/capture",
            json={
                "raw_text": "C",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # B and C depend on A
        client.post(
            f"/loops/{loop_b['id']}/dependencies", json={"depends_on_loop_id": loop_a["id"]}
        )
        client.post(
            f"/loops/{loop_c['id']}/dependencies", json={"depends_on_loop_id": loop_a["id"]}
        )

        # Get blocking for A
        blocking = client.get(f"/loops/{loop_a['id']}/blocking").json()
        blocking_ids = [b["id"] for b in blocking]

        assert set(blocking_ids) == {loop_b["id"], loop_c["id"]}

    def test_dependency_persists_after_reopen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Dependencies persist after completing and reopening a loop."""
        client = make_test_client()

        # Create loops with dependency
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Complete the blocker
        client.post(f"/loops/{blocker['id']}/status", json={"status": "completed"})

        # Reopen the blocker
        client.post(f"/loops/{blocker['id']}/status", json={"status": "inbox"})

        # Verify dependency still exists and is now open again
        deps = client.get(f"/loops/{dependent['id']}/dependencies").json()
        assert len(deps) == 1
        assert deps[0]["status"] == "inbox"

        # Should not be able to transition to actionable
        result = client.post(f"/loops/{dependent['id']}/status", json={"status": "actionable"})
        assert result.status_code == 400
        assert result.json()["error"]["type"] == "dependency_not_met"
        assert blocker["id"] in result.json()["error"]["details"]["open_dependencies"]


# ============================================================================
# Time Tracking Tests
# ============================================================================


def test_timer_start_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test starting and stopping a timer."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "timer test",
            "actionable": True,
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Start timer
    start = client.post(f"/loops/{loop_id}/timer/start")
    assert start.status_code == 200
    session = start.json()
    assert session["loop_id"] == loop_id
    assert session["is_active"] is True
    assert session["ended_at_utc"] is None

    # Check status
    status = client.get(f"/loops/{loop_id}/timer/status")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["has_active_session"] is True
    assert status_data["loop_id"] == loop_id

    # Stop timer
    import time

    time.sleep(1)  # Ensure at least 1 second duration
    stop = client.post(f"/loops/{loop_id}/timer/stop", json={"notes": "Done"})
    assert stop.status_code == 200
    stopped = stop.json()
    assert stopped["is_active"] is False
    assert stopped["duration_seconds"] >= 1
    assert stopped["notes"] == "Done"


def test_concurrent_timer_prevention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that only one active timer per loop is allowed."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "concurrent test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Start first timer
    start1 = client.post(f"/loops/{loop_id}/timer/start")
    assert start1.status_code == 200

    # Try to start second timer - should fail
    start2 = client.post(f"/loops/{loop_id}/timer/start")
    assert start2.status_code == 409
    error = start2.json()
    assert "timer_already_active" in str(error) or "already has an active timer" in str(
        error.get("detail", "")
    )


def test_stop_without_active_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that stopping without active timer returns error."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "stop test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Try to stop without starting
    stop = client.post(f"/loops/{loop_id}/timer/stop")
    assert stop.status_code == 400
    error = stop.json()
    assert "no_active_timer" in str(error) or "no active timer" in str(error.get("detail", ""))


def test_session_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test listing time sessions."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "history test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Start and stop timer twice
    client.post(f"/loops/{loop_id}/timer/start")
    import time

    time.sleep(1)
    client.post(f"/loops/{loop_id}/timer/stop")

    time.sleep(0.5)
    client.post(f"/loops/{loop_id}/timer/start")
    time.sleep(1)
    client.post(f"/loops/{loop_id}/timer/stop")

    # List sessions
    sessions = client.get(f"/loops/{loop_id}/sessions")
    assert sessions.status_code == 200
    data = sessions.json()
    assert data["loop_id"] == loop_id
    assert len(data["sessions"]) >= 2


def test_timer_status_with_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test timer status shows estimation accuracy."""
    client = make_test_client()

    # Create a loop with time estimate
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "estimate test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Set time estimate
    client.patch(f"/loops/{loop_id}", json={"time_minutes": 30})

    # Track some time
    client.post(f"/loops/{loop_id}/timer/start")
    import time

    time.sleep(2)
    client.post(f"/loops/{loop_id}/timer/stop")

    # Check status
    status = client.get(f"/loops/{loop_id}/timer/status")
    assert status.status_code == 200
    data = status.json()
    assert data["estimated_minutes"] == 30
    # With 2 seconds tracked (0 min), accuracy should be very low
    assert data["estimation_accuracy"] is not None


def test_timer_for_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test timer operations on non-existent loop."""
    client = make_test_client()

    # Try to start timer on non-existent loop
    start = client.post("/loops/99999/timer/start")
    assert start.status_code == 404

    # Try to stop timer on non-existent loop
    stop = client.post("/loops/99999/timer/stop")
    assert stop.status_code == 404

    # Try to get status on non-existent loop
    status = client.get("/loops/99999/timer/status")
    assert status.status_code == 404


def test_timer_session_properties() -> None:
    """Test TimeSession dataclass properties."""
    from datetime import datetime, timezone

    from cloop.loops.models import TimeSession

    # Active session (no ended_at)
    now = datetime.now(timezone.utc)
    active_session = TimeSession(
        id=1,
        loop_id=42,
        started_at_utc=now,
        ended_at_utc=None,
        duration_seconds=None,
        notes=None,
        created_at_utc=now,
    )
    assert active_session.is_active is True
    assert active_session.elapsed_seconds >= 0  # Should calculate from started_at

    # Completed session
    completed_session = TimeSession(
        id=2,
        loop_id=42,
        started_at_utc=now,
        ended_at_utc=now,
        duration_seconds=300,
        notes="Done",
        created_at_utc=now,
    )
    assert completed_session.is_active is False
    assert completed_session.elapsed_seconds == 300


# ============================================================================
# Loop Template Tests
# ============================================================================


def test_template_create_and_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test creating a template and listing templates."""
    import sqlite3

    from cloop.loops import repo

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Test Template",
        description="A test template",
        raw_text_pattern="Task for {{date}}",
        defaults_json={"tags": ["test"], "time_minutes": 30},
        is_system=False,
        conn=conn,
    )

    assert template["name"] == "Test Template"
    assert template["description"] == "A test template"
    assert template["is_system"] == 0

    # List templates
    templates = repo.list_loop_templates(conn=conn)
    assert any(t["name"] == "Test Template" for t in templates)

    conn.close()


def test_template_get_by_id_and_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test getting a template by ID and by name."""
    import sqlite3

    from cloop.loops import repo

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Get Test",
        description="Testing get methods",
        raw_text_pattern="Pattern",
        defaults_json={},
        conn=conn,
    )
    template_id = template["id"]

    # Get by ID
    by_id = repo.get_loop_template(template_id=template_id, conn=conn)
    assert by_id is not None
    assert by_id["name"] == "Get Test"

    # Get by name (case insensitive)
    by_name = repo.get_loop_template_by_name(name="get test", conn=conn)
    assert by_name is not None
    assert by_name["id"] == template_id

    conn.close()


def test_template_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test updating a template."""
    import sqlite3

    from cloop.loops import repo

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Update Test",
        description="Before update",
        raw_text_pattern="Old pattern",
        defaults_json={},
        conn=conn,
    )

    # Update the template
    updated = repo.update_loop_template(
        template_id=template["id"],
        name="Updated Name",
        description="After update",
        conn=conn,
    )

    assert updated["name"] == "Updated Name"
    assert updated["description"] == "After update"

    conn.close()


def test_template_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test deleting a template."""
    import sqlite3

    from cloop.loops import repo

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Delete Test",
        description="To be deleted",
        raw_text_pattern="",
        defaults_json={},
        conn=conn,
    )
    template_id = template["id"]

    # Delete the template
    deleted = repo.delete_loop_template(template_id=template_id, conn=conn)
    assert deleted is True

    # Verify it's gone
    by_id = repo.get_loop_template(template_id=template_id, conn=conn)
    assert by_id is None

    conn.close()


def test_system_template_cannot_be_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that system templates cannot be modified or deleted."""
    import sqlite3

    from cloop.loops import repo
    from cloop.loops.errors import ValidationError

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Get a system template (created by migration)
    templates = repo.list_loop_templates(conn=conn)
    system_template = next((t for t in templates if t["is_system"]), None)
    assert system_template is not None

    # Try to update
    with pytest.raises(ValidationError, match="system templates cannot be modified"):
        repo.update_loop_template(
            template_id=system_template["id"],
            name="New Name",
            conn=conn,
        )

    # Try to delete
    with pytest.raises(ValidationError, match="system templates cannot be deleted"):
        repo.delete_loop_template(template_id=system_template["id"], conn=conn)

    conn.close()


def test_template_variable_substitution() -> None:
    """Test template variable substitution."""
    from datetime import datetime, timezone

    from cloop.loops.templates import substitute_template_variables

    text = "Date: {{date}}, Day: {{day}}, Week: {{week}}, Month: {{month}}, Year: {{year}}"
    result = substitute_template_variables(
        text,
        now_utc=datetime(2026, 2, 14, 10, 30, 0, tzinfo=timezone.utc),
        tz_offset_min=0,
    )

    assert "Date: 2026-02-14" in result
    assert "Day: Saturday" in result
    assert "Week: 7" in result  # ISO week
    assert "Month: February" in result
    assert "Year: 2026" in result


def test_apply_template_to_capture() -> None:
    """Test applying a template to capture request defaults."""
    from datetime import datetime, timezone

    from cloop.loops.templates import apply_template_to_capture

    template = {
        "raw_text_pattern": "Meeting on {{date}}\n\nNotes:",
        "defaults_json": '{"tags": ["meeting"], "actionable": true, "time_minutes": 30}',
    }

    result = apply_template_to_capture(
        template=template,
        raw_text_override="Discuss project roadmap",
        now_utc=datetime(2026, 2, 14, 10, 30, 0, tzinfo=timezone.utc),
        tz_offset_min=0,
    )

    assert "Meeting on 2026-02-14" in result["raw_text"]
    assert "Discuss project roadmap" in result["raw_text"]
    assert result["tags"] == ["meeting"]
    assert result["actionable"] is True
    assert result["time_minutes"] == 30


def test_extract_update_fields_from_template() -> None:
    """Test extracting update fields from applied template defaults."""
    from cloop.loops.templates import extract_update_fields_from_template

    # Test with all fields populated
    applied = {
        "raw_text": "Some text",
        "tags": ["work", "urgent"],
        "time_minutes": 45,
        "activation_energy": 3,
        "urgency": 0.8,
        "importance": 0.9,
        "project": "my-project",
        "actionable": True,
        "scheduled": False,
        "blocked": False,
    }
    update_fields = extract_update_fields_from_template(applied)
    assert update_fields["tags"] == ["work", "urgent"]
    assert update_fields["time_minutes"] == 45
    assert update_fields["activation_energy"] == 3
    assert update_fields["urgency"] == 0.8
    assert update_fields["importance"] == 0.9
    assert update_fields["project"] == "my-project"
    # status flags should NOT be in update_fields
    assert "actionable" not in update_fields

    # Test with empty/None values - should not include those fields
    applied_empty = {
        "raw_text": "Some text",
        "tags": None,
        "time_minutes": None,
        "project": "",
        "actionable": False,
    }
    update_fields_empty = extract_update_fields_from_template(applied_empty)
    assert update_fields_empty == {}


def test_create_template_from_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test creating a template from an existing loop."""
    import sqlite3

    from cloop.loops import repo, service
    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop with tags
    loop = repo.create_loop(
        raw_text="Weekly review task",
        captured_at_utc="2026-02-14T10:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.ACTIONABLE,
        conn=conn,
    )
    repo.replace_loop_tags(loop_id=loop.id, tag_names=["weekly", "review"], conn=conn)
    repo.update_loop_fields(
        loop_id=loop.id,
        fields={"time_minutes": 30},
        conn=conn,
    )

    # Create template from loop
    template = service.create_template_from_loop(
        loop_id=loop.id,
        template_name="Weekly Review Template",
        conn=conn,
    )

    assert template["name"] == "Weekly Review Template"
    assert template["raw_text_pattern"] == "Weekly review task"
    assert "weekly" in template["defaults_json"]
    assert "review" in template["defaults_json"]

    conn.close()


def test_template_api_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test template API endpoints."""
    client = make_test_client()

    # List templates (should include system templates)
    response = client.get("/loops/templates")
    assert response.status_code == 200
    templates = response.json()["templates"]
    assert any(t["name"] == "Daily Standup" for t in templates)
    assert any(t["name"] == "Quick Task" for t in templates)

    # Create a template
    response = client.post(
        "/loops/templates",
        json={
            "name": "API Test Template",
            "description": "Created via API",
            "raw_text_pattern": "Task: {{date}}",
            "defaults": {"tags": ["api-test"], "time_minutes": 15},
        },
    )
    assert response.status_code == 201
    template_id = response.json()["id"]

    # Get template by ID
    response = client.get(f"/loops/templates/{template_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "API Test Template"

    # Capture with template
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "My task",
            "template_id": template_id,
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop = response.json()
    assert "api-test" in loop["tags"]


def test_capture_with_template_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test capturing a loop using a template by name."""
    client = make_test_client()

    # Capture with template by name
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Standup notes",
            "template_name": "Daily Standup",
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop = response.json()
    assert "standup" in loop["tags"]
    assert "daily" in loop["tags"]


def test_save_loop_as_template_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test the save-as-template endpoint."""
    client = make_test_client()

    # Create a loop
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Weekly task to review",
            "actionable": True,
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    loop_id = response.json()["id"]

    # Add tags
    client.patch(f"/loops/{loop_id}", json={"tags": ["weekly"]})

    # Save as template
    response = client.post(
        f"/loops/{loop_id}/save-as-template",
        json={
            "name": "My Weekly Template",
        },
    )
    assert response.status_code == 201
    template = response.json()
    assert template["name"] == "My Weekly Template"
    assert template["is_system"] is False


# =============================================================================
# Review Cohort Tests
# =============================================================================


def test_review_cohorts_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test stale cohort identifies loops not updated recently."""
    import sqlite3

    client = make_test_client()
    now = _now_iso()

    # Create a loop and artificially age it
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "old task",
            "actionable": True,
            "captured_at": now,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Update updated_at to be 100 hours ago (exceeds default 72h stale threshold)
    settings = get_settings()
    with sqlite3.connect(str(settings.core_db_path)) as conn:
        conn.execute(
            "UPDATE loops SET updated_at = datetime('now', '-100 hours') WHERE id = ?",
            (loop_id,),
        )
        conn.commit()

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    stale_cohort = next((c for c in data["daily"] if c["cohort"] == "stale"), None)
    assert stale_cohort is not None
    assert stale_cohort["count"] >= 1
    assert any(item["id"] == loop_id for item in stale_cohort["items"])


def test_review_cohorts_no_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test no_next_action cohort identifies actionable loops without next_action."""
    client = make_test_client()
    now = _now_iso()

    # Create actionable loop without next_action
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "do something",
            "actionable": True,
            "captured_at": now,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    no_action = next((c for c in data["daily"] if c["cohort"] == "no_next_action"), None)
    assert no_action is not None
    assert any(item["id"] == loop_id for item in no_action["items"])


def test_review_cohorts_blocked_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test blocked_too_long cohort identifies long-blocked loops."""
    import sqlite3

    client = make_test_client()
    now = _now_iso()

    # Create blocked loop and age it
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "waiting on X",
            "blocked": True,
            "captured_at": now,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Age the loop 72 hours (exceeds default 48h blocked threshold)
    settings = get_settings()
    with sqlite3.connect(str(settings.core_db_path)) as conn:
        conn.execute(
            "UPDATE loops SET updated_at = datetime('now', '-72 hours') WHERE id = ?",
            (loop_id,),
        )
        conn.commit()

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    blocked = next((c for c in data["daily"] if c["cohort"] == "blocked_too_long"), None)
    assert blocked is not None
    assert any(item["id"] == loop_id for item in blocked["items"])


def test_review_cohorts_due_soon_unplanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test due_soon_unplanned cohort identifies due loops without next_action."""
    client = make_test_client()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    # Create loop due in 24 hours (within 48h window) without next_action
    due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "deadline soon",
            "actionable": True,
            "captured_at": now_iso,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Set due date
    client.patch(f"/loops/{loop_id}", json={"due_at_utc": due_soon})

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    due_soon_cohort = next((c for c in data["daily"] if c["cohort"] == "due_soon_unplanned"), None)
    assert due_soon_cohort is not None
    assert any(item["id"] == loop_id for item in due_soon_cohort["items"])


def test_review_weekly_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test weekly review only includes stale and blocked_too_long cohorts."""
    client = make_test_client()

    resp = client.get("/loops/review?weekly=true&daily=false")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["daily"]) == 0
    cohort_names = {c["cohort"] for c in data["weekly"]}
    assert cohort_names <= {"stale", "blocked_too_long"}


def test_review_settings_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test review settings validation via environment variables."""
    from cloop.settings import get_settings

    # Test invalid review_stale_hours
    monkeypatch.setenv("CLOOP_REVIEW_STALE_HOURS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_REVIEW_STALE_HOURS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_REVIEW_STALE_HOURS", raising=False)
    get_settings.cache_clear()

    # Test invalid review_blocked_hours
    monkeypatch.setenv("CLOOP_REVIEW_BLOCKED_HOURS", "-1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_REVIEW_BLOCKED_HOURS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_REVIEW_BLOCKED_HOURS", raising=False)
    get_settings.cache_clear()

    # Test invalid review_due_soon_hours
    monkeypatch.setenv("CLOOP_REVIEW_DUE_SOON_HOURS", "0.5")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_REVIEW_DUE_SOON_HOURS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_REVIEW_DUE_SOON_HOURS", raising=False)
    get_settings.cache_clear()


def test_review_cohorts_default_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test review cohorts use default settings correctly."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    # Verify default values
    assert settings.review_stale_hours == 72.0
    assert settings.review_blocked_hours == 48.0
    assert settings.review_due_soon_hours == 48.0


def test_review_endpoint_limit_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test review endpoint respects limit parameter."""
    client = make_test_client()
    now = _now_iso()

    # Create multiple actionable loops without next_action
    for i in range(5):
        client.post(
            "/loops/capture",
            json={
                "raw_text": f"task {i}",
                "actionable": True,
                "captured_at": now,
                "client_tz_offset_min": 0,
            },
        )

    # Get review with limit=2
    resp = client.get("/loops/review?limit=2")
    assert resp.status_code == 200
    data = resp.json()

    # Check that no_next_action cohort has at most 2 items
    no_action = next((c for c in data["daily"] if c["cohort"] == "no_next_action"), None)
    if no_action:
        assert len(no_action["items"]) <= 2


# =============================================================================
# Event History and Undo Tests
# =============================================================================


def test_loop_events_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that event history is returned correctly."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test events",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Make some updates
    client.patch(f"/loops/{loop_id}", json={"title": "First title"})
    client.patch(f"/loops/{loop_id}", json={"title": "Second title"})

    # Get events
    events_response = client.get(f"/loops/{loop_id}/events")
    assert events_response.status_code == 200
    events_data = events_response.json()

    assert events_data["loop_id"] == loop_id
    assert len(events_data["events"]) >= 2  # At least the two updates

    # Check event structure
    for event in events_data["events"]:
        assert "id" in event
        assert "event_type" in event
        assert "payload" in event
        assert "created_at_utc" in event
        assert "is_reversible" in event

    # Check that update events are marked as reversible
    update_events = [e for e in events_data["events"] if e["event_type"] == "update"]
    assert len(update_events) >= 2
    for event in update_events:
        assert event["is_reversible"] is True


def test_loop_events_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test event history pagination."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "pagination test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Make multiple updates
    for i in range(5):
        client.patch(f"/loops/{loop_id}", json={"title": f"Title {i}"})

    # Get first page
    page1 = client.get(f"/loops/{loop_id}/events?limit=2")
    assert page1.status_code == 200
    data1 = page1.json()

    assert len(data1["events"]) == 2
    assert data1["has_more"] is True
    assert data1["next_cursor"] is not None

    # Get second page
    page2 = client.get(f"/loops/{loop_id}/events?limit=2&before_id={data1['next_cursor']}")
    assert page2.status_code == 200
    data2 = page2.json()

    assert len(data2["events"]) >= 2


def test_loop_undo_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undoing a loop update."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "undo test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Update with a title
    client.patch(f"/loops/{loop_id}", json={"title": "Original Title"})

    # Update again
    update_response = client.patch(f"/loops/{loop_id}", json={"title": "Changed Title"})
    assert update_response.json()["title"] == "Changed Title"

    # Undo
    undo_response = client.post(f"/loops/{loop_id}/undo")
    assert undo_response.status_code == 200
    undo_data = undo_response.json()

    assert undo_data["undone_event_type"] == "update"
    assert undo_data["loop"]["title"] == "Original Title"


def test_loop_undo_status_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undoing a status change."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "status undo test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]
    assert create_response.json()["status"] == "inbox"

    # Transition to actionable
    client.post(f"/loops/{loop_id}/status", json={"status": "actionable"})

    # Transition to completed
    complete_response = client.post(f"/loops/{loop_id}/status", json={"status": "completed"})
    assert complete_response.json()["status"] == "completed"

    # Undo - should go back to actionable
    undo_response = client.post(f"/loops/{loop_id}/undo")
    assert undo_response.status_code == 200
    undo_data = undo_response.json()

    assert undo_data["undone_event_type"] == "close"
    assert undo_data["loop"]["status"] == "actionable"


def test_loop_undo_no_reversible_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undo fails when no reversible events exist."""
    client = make_test_client()

    # Create a loop (capture event is not reversible)
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "no reversible events",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Undo should fail
    undo_response = client.post(f"/loops/{loop_id}/undo")
    assert undo_response.status_code == 400
    error_data = undo_response.json()
    # Error response format is {'error': {'details': {'code': ...}}}
    assert error_data["error"]["details"]["code"] == "undo_not_possible"


def test_loop_undo_records_undo_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that undo operations are recorded in event history."""
    client = make_test_client()

    # Create and update a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "undo record test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"title": "Test Title"})

    # Undo
    client.post(f"/loops/{loop_id}/undo")

    # Check events include the undo event
    events_response = client.get(f"/loops/{loop_id}/events")
    events = events_response.json()["events"]

    undo_events = [e for e in events if e["event_type"] == "undo"]
    assert len(undo_events) == 1
    assert "undone_event_id" in undo_events[0]["payload"]


def test_loop_events_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test events endpoint returns 404 for nonexistent loop."""
    client = make_test_client()

    response = client.get("/loops/99999/events")
    assert response.status_code == 404


def test_loop_undo_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undo endpoint returns 404 for nonexistent loop."""
    client = make_test_client()

    response = client.post("/loops/99999/undo")
    assert response.status_code == 404


def test_loop_undo_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undo endpoint supports idempotency."""
    client = make_test_client()

    # Create and update a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "idempotency test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"title": "Title"})

    # Undo with idempotency key
    headers = {"Idempotency-Key": "undo-key-1"}
    response1 = client.post(f"/loops/{loop_id}/undo", headers=headers)
    assert response1.status_code == 200

    # Same request should replay
    response2 = client.post(f"/loops/{loop_id}/undo", headers=headers)
    assert response2.status_code == 200
    assert response2.json()["undone_event_id"] == response1.json()["undone_event_id"]


def test_loop_update_captures_before_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that update events capture before_state for undo support."""
    import sqlite3

    from cloop import db as db_module
    from cloop.loops import repo

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db_module.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="before state test",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Update with title
    from cloop.loops.service import update_loop

    update_loop(
        loop_id=record.id,
        fields={"title": "New Title"},
        conn=conn,
    )

    # Check that the event has before_state
    events = repo.list_loop_events(loop_id=record.id, conn=conn)
    update_events = [e for e in events if e["event_type"] == "update"]
    assert len(update_events) == 1

    import json

    payload = json.loads(update_events[0]["payload_json"])
    assert "before_state" in payload

    conn.close()


# =============================================================================
# Comment Tests
# =============================================================================


class TestLoopComments:
    """Tests for loop comment CRUD and threading."""

    def test_create_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test creating a top-level comment on a loop."""
        client = make_test_client()

        # Create a loop first
        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop for comments",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        # Create comment
        resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "This is a **test** comment",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["author"] == "Alice"
        assert data["body_md"] == "This is a **test** comment"
        assert data["parent_id"] is None
        assert data["is_reply"] is False
        assert data["is_deleted"] is False

    def test_create_reply(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test creating a reply to a comment."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        # Create parent comment
        parent_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "Parent comment",
            },
        )
        parent_id = parent_resp.json()["id"]

        # Create reply
        reply_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Bob",
                "body_md": "Reply to Alice",
                "parent_id": parent_id,
            },
        )
        assert reply_resp.status_code == 201
        data = reply_resp.json()
        assert data["parent_id"] == parent_id
        assert data["is_reply"] is True

    def test_list_comments_threaded_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test that comments are returned in proper threaded order."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        # Create comments in non-threaded order
        c1 = client.post(
            f"/loops/{loop_id}/comments", json={"author": "A", "body_md": "First"}
        ).json()
        c2 = client.post(
            f"/loops/{loop_id}/comments", json={"author": "B", "body_md": "Second"}
        ).json()
        client.post(
            f"/loops/{loop_id}/comments",
            json={"author": "C", "body_md": "Reply to First", "parent_id": c1["id"]},
        )
        client.post(
            f"/loops/{loop_id}/comments",
            json={"author": "D", "body_md": "Reply to Second", "parent_id": c2["id"]},
        )

        # List comments
        resp = client.get(f"/loops/{loop_id}/comments")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_count"] == 4
        assert len(data["comments"]) == 2  # Two top-level comments

        # First parent should have one reply
        assert len(data["comments"][0]["replies"]) == 1
        assert data["comments"][0]["replies"][0]["parent_id"] == c1["id"]

        # Second parent should have one reply
        assert len(data["comments"][1]["replies"]) == 1
        assert data["comments"][1]["replies"][0]["parent_id"] == c2["id"]

    def test_update_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test updating a comment's body."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        comment_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "Original text",
            },
        )
        comment_id = comment_resp.json()["id"]

        # Update
        update_resp = client.patch(
            f"/loops/{loop_id}/comments/{comment_id}",
            json={
                "body_md": "Updated text",
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["body_md"] == "Updated text"

    def test_soft_delete_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test soft-deleting a comment."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        comment_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "To be deleted",
            },
        )
        comment_id = comment_resp.json()["id"]

        # Delete
        delete_resp = client.delete(f"/loops/{loop_id}/comments/{comment_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True

        # Verify it's soft-deleted (not returned by default)
        list_resp = client.get(f"/loops/{loop_id}/comments")
        assert list_resp.json()["total_count"] == 0

        # Verify it shows with include_deleted
        list_resp = client.get(f"/loops/{loop_id}/comments?include_deleted=true")
        assert list_resp.json()["total_count"] == 1
        assert list_resp.json()["comments"][0]["is_deleted"] is True

    def test_comment_on_nonexistent_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test that commenting on a nonexistent loop returns 404."""
        client = make_test_client()

        resp = client.post(
            "/loops/99999/comments",
            json={
                "author": "Alice",
                "body_md": "Test",
            },
        )
        assert resp.status_code == 404

    def test_reply_to_wrong_loop_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test that replying to a comment from a different loop fails."""
        client = make_test_client()

        # Create two loops
        loop1 = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop 1",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        ).json()

        loop2 = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop 2",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        ).json()

        # Comment on loop1
        comment = client.post(
            f"/loops/{loop1['id']}/comments",
            json={
                "author": "Alice",
                "body_md": "Comment on loop 1",
            },
        ).json()

        # Try to reply on loop2 using loop1's comment as parent
        resp = client.post(
            f"/loops/{loop2['id']}/comments",
            json={
                "author": "Bob",
                "body_md": "Invalid reply",
                "parent_id": comment["id"],
            },
        )
        assert resp.status_code == 400  # ValidationError


# =============================================================================
# Comment Event Tests
# =============================================================================


def test_comment_events_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that comment events are recorded in loop event history."""
    client = make_test_client()

    # Create a loop
    loop_resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop for comment events",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    loop_id = loop_resp.json()["id"]

    # Add a comment
    comment = client.post(
        f"/loops/{loop_id}/comments",
        json={"author": "Alice", "body_md": "Test comment"},
    ).json()

    # Get events
    events_resp = client.get(f"/loops/{loop_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()["events"]

    # Find comment_added event
    comment_events = [e for e in events if e["event_type"] == "comment_added"]
    assert len(comment_events) == 1
    assert comment_events[0]["payload"]["comment_id"] == comment["id"]
    assert comment_events[0]["payload"]["author"] == "Alice"


# =============================================================================
# Comment Idempotency Tests
# =============================================================================


def test_comment_create_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload returns same comment without duplicate."""
    client = make_test_client()

    # Create a loop
    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    payload = {"author": "Alice", "body_md": "Test comment"}
    headers = {"Idempotency-Key": "comment-key-123"}

    response1 = client.post(f"/loops/{loop['id']}/comments", json=payload, headers=headers)
    assert response1.status_code == 201
    comment1 = response1.json()

    response2 = client.post(f"/loops/{loop['id']}/comments", json=payload, headers=headers)
    assert response2.status_code == 201
    comment2 = response2.json()

    # Same comment returned
    assert comment1["id"] == comment2["id"]

    # Only one comment exists
    list_resp = client.get(f"/loops/{loop['id']}/comments")
    assert len(list_resp.json()["comments"]) == 1


def test_comment_create_idempotency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + different payload returns 409 Conflict."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    payload1 = {"author": "Alice", "body_md": "First comment"}
    payload2 = {"author": "Bob", "body_md": "Different comment"}
    headers = {"Idempotency-Key": "conflict-comment-key"}

    response1 = client.post(f"/loops/{loop['id']}/comments", json=payload1, headers=headers)
    assert response1.status_code == 201

    response2 = client.post(f"/loops/{loop['id']}/comments", json=payload2, headers=headers)
    assert response2.status_code == 409
    assert "idempotency_key_conflict" in str(response2.json())


def test_comment_update_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload updates comment once."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    comment = client.post(
        f"/loops/{loop['id']}/comments",
        json={"author": "Alice", "body_md": "Original"},
    ).json()

    payload = {"body_md": "Updated content"}
    headers = {"Idempotency-Key": "update-key-456"}

    response1 = client.patch(
        f"/loops/{loop['id']}/comments/{comment['id']}", json=payload, headers=headers
    )
    assert response1.status_code == 200

    response2 = client.patch(
        f"/loops/{loop['id']}/comments/{comment['id']}", json=payload, headers=headers
    )
    assert response2.status_code == 200
    assert response2.json()["body_md"] == "Updated content"


def test_comment_delete_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key replay on delete returns same result."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    comment = client.post(
        f"/loops/{loop['id']}/comments",
        json={"author": "Alice", "body_md": "To delete"},
    ).json()

    headers = {"Idempotency-Key": "delete-key-789"}

    response1 = client.delete(f"/loops/{loop['id']}/comments/{comment['id']}", headers=headers)
    assert response1.status_code == 200
    assert response1.json()["deleted"] is True

    response2 = client.delete(f"/loops/{loop['id']}/comments/{comment['id']}", headers=headers)
    assert response2.status_code == 200
    assert response2.json()["deleted"] is True


# ============================================================================
# Duplicate Detection and Merge Tests
# ============================================================================


def test_settings_duplicate_threshold_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Settings validation requires duplicate_threshold > related_threshold."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_RELATED_SIMILARITY_THRESHOLD", "0.92")
    monkeypatch.setenv("CLOOP_DUPLICATE_SIMILARITY_THRESHOLD", "0.91")  # Less than related
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="DUPLICATE_SIMILARITY_THRESHOLD must be greater"):
        get_settings()


def test_settings_duplicate_threshold_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Settings validation requires duplicate_threshold between 0.9 and 1.0."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_DUPLICATE_SIMILARITY_THRESHOLD", "0.85")  # Below minimum
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="DUPLICATE_SIMILARITY_THRESHOLD must be between"):
        get_settings()


def test_find_duplicate_candidates_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """GET /loops/{id}/duplicates returns candidates list."""
    client = make_test_client()

    # Create two loops
    loop1 = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test duplicate detection task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Create second loop (potential duplicate)
    _ = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test duplicate detection task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Query duplicates endpoint (may return empty if embeddings not generated)
    resp = client.get(f"/loops/{loop1['id']}/duplicates")
    assert resp.status_code == 200
    data = resp.json()
    assert "loop_id" in data
    assert "candidates" in data
    assert isinstance(data["candidates"], list)


def test_merge_preview_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """GET /loops/{id}/merge-preview/{target} returns merge preview."""
    client = make_test_client()

    # Create two loops
    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Surviving loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Duplicate loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    # Get merge preview (loop2 into loop1)
    resp = client.get(f"/loops/{loop2['id']}/merge-preview/{loop1['id']}")
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["surviving_loop_id"] == loop1["id"]
    assert preview["duplicate_loop_id"] == loop2["id"]
    assert "merged_title" in preview
    assert "merged_summary" in preview
    assert "merged_tags" in preview
    assert "field_conflicts" in preview


def test_merge_preview_same_loop_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge preview fails if trying to merge loop with itself."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={"raw_text": "Test loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    resp = client.get(f"/loops/{loop['id']}/merge-preview/{loop['id']}")
    assert resp.status_code == 400
    assert "Cannot merge" in str(resp.json())


def test_merge_preview_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge preview fails if loop doesn't exist."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={"raw_text": "Test loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    resp = client.get(f"/loops/{loop['id']}/merge-preview/99999")
    assert resp.status_code == 404


def test_merge_loops_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """POST /loops/{id}/merge merges duplicate into target."""
    client = make_test_client()

    # Create surviving loop with title and tags
    loop1 = client.post(
        "/loops/capture",
        json={
            "raw_text": "Surviving loop task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Update with title and tags
    client.patch(f"/loops/{loop1['id']}", json={"title": "Surviving Title", "tags": ["work"]})

    # Create duplicate loop with different fields
    loop2 = client.post(
        "/loops/capture",
        json={
            "raw_text": "Duplicate loop task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Update with summary and tags
    client.patch(
        f"/loops/{loop2['id']}",
        json={"summary": "Duplicate Summary", "tags": ["personal"]},
    )

    # Execute merge (loop2 into loop1)
    resp = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["surviving_loop_id"] == loop1["id"]
    assert result["closed_loop_id"] == loop2["id"]
    assert "merged_tags" in result
    assert "fields_updated" in result

    # Verify duplicate is closed
    resp = client.get(f"/loops/{loop2['id']}")
    assert resp.status_code == 200
    closed = resp.json()
    assert closed["status"] == "dropped"


def test_merge_loops_into_closed_loop_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot merge into a closed loop."""
    client = make_test_client()

    # Create and close a loop
    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Completed loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.post(f"/loops/{loop1['id']}/close", json={"status": "completed"})

    # Create another loop
    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Open loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    # Try to merge into closed loop
    resp = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
    )
    assert resp.status_code == 400


def test_merge_loops_nonexistent_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot merge into non-existent loop."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={"raw_text": "Test loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    resp = client.post(
        f"/loops/{loop['id']}/merge",
        json={"target_loop_id": 99999},
    )
    assert resp.status_code == 404


def test_merge_loops_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge supports idempotency key for safe retries."""
    client = make_test_client()

    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Surviving", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Duplicate", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    headers = {"Idempotency-Key": "merge-test-key-123"}

    # First merge
    resp1 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
        headers=headers,
    )
    assert resp1.status_code == 200

    # Retry with same key should return same result
    resp2 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["surviving_loop_id"] == resp1.json()["surviving_loop_id"]


def test_merge_loops_conflict_different_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key with different payload returns conflict."""
    client = make_test_client()

    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Surviving", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Duplicate", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop3 = client.post(
        "/loops/capture",
        json={"raw_text": "Other", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    headers = {"Idempotency-Key": "merge-conflict-key"}

    # First merge
    resp1 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
        headers=headers,
    )
    assert resp1.status_code == 200

    # Different target with same key should conflict
    resp2 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop3["id"]},  # Different target
        headers=headers,
    )
    assert resp2.status_code == 409
    assert "idempotency_key_conflict" in str(resp2.json())


def test_merge_preview_detects_field_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Preview identifies field conflicts when both loops have different values."""
    client = make_test_client()

    # Create loops with different titles
    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop one", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop1['id']}", json={"title": "Title One"})

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop two", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop2['id']}", json={"title": "Title Two"})

    # Get preview
    resp = client.get(f"/loops/{loop2['id']}/merge-preview/{loop1['id']}")
    assert resp.status_code == 200
    preview = resp.json()

    assert "title" in preview["field_conflicts"]
    assert preview["field_conflicts"]["title"]["surviving"] == "Title One"
    assert preview["field_conflicts"]["title"]["duplicate"] == "Title Two"


def test_merge_combines_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge combines tags from both loops."""
    client = make_test_client()

    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop one", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop1['id']}", json={"tags": ["work", "priority"]})

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop two", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop2['id']}", json={"tags": ["personal", "work"]})  # "work" overlaps

    # Execute merge
    resp = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
    )
    assert resp.status_code == 200
    result = resp.json()

    # Tags should be union
    assert "work" in result["merged_tags"]
    assert "priority" in result["merged_tags"]
    assert "personal" in result["merged_tags"]
    assert len(result["merged_tags"]) == 3  # No duplicates
