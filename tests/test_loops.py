from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.loops.prioritization import bucketize
from cloop.main import app
from cloop.settings import get_settings


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def test_loop_capture_and_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
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


def test_loop_status_transitions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
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


def test_tag_normalization_and_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
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


def test_export_import_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
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
    fresh_client = _make_client(fresh_dir, monkeypatch)
    import_response = fresh_client.post("/loops/import", json={"loops": export_payload["loops"]})
    assert import_response.status_code == 200
    assert import_response.json()["imported"] == len(export_payload["loops"])

    imported_loops = fresh_client.get("/loops", params={"status": "all"})
    assert imported_loops.status_code == 200
    imported_payload = imported_loops.json()
    assert imported_payload
    assert imported_payload[0]["completion_note"] == "archived"


def test_bucketize_returns_standard_for_low_importance() -> None:
    """Low importance loops should NOT be classified as high_leverage."""
    now = datetime.now(timezone.utc)

    # Loop with low importance, not due soon, not a quick win
    loop = {
        "importance": 0.1,
        "time_minutes": 120,
        "activation_energy": 3,
        # No due_at_utc, so not due_soon
    }

    result = bucketize(loop, now_utc=now)
    assert result == "standard", f"Expected 'standard' for low importance loop, got '{result}'"


def test_bucketize_returns_high_leverage_for_high_importance() -> None:
    """High importance loops should be classified as high_leverage."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.8,
        "time_minutes": 120,
        "activation_energy": 3,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "high_leverage"


def test_bucketize_returns_due_soon_for_urgent_due_date() -> None:
    """Loops due within 48h should be due_soon regardless of other factors."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.9,  # High importance
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
        "time_minutes": 5,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "due_soon"


def test_bucketize_returns_quick_wins_for_small_tasks() -> None:
    """Short, low-energy tasks should be quick_wins."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.9,  # High importance
        "time_minutes": 10,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "quick_wins"


def test_bucketize_handles_none_importance() -> None:
    """Loops without importance should default to standard."""
    now = datetime.now(timezone.utc)

    loop = {
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "standard"


def test_bucketize_importance_boundary_high() -> None:
    """Loop with importance exactly 0.7 should be high_leverage."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.7,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "high_leverage"


def test_bucketize_importance_boundary_low() -> None:
    """Loop with importance just below 0.7 should be standard."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.69,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "standard"


def test_list_loops_query_count_not_n_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    # Verify the data is correct
    for i, loop in enumerate(result):
        assert loop["raw_text"] == f"Loop {i}"
        assert loop["project"] == "TestProject"
        assert "common" in loop["tags"]
        assert f"tag{i}" in loop["tags"]

    conn.close()


def test_search_loops_escapes_like_wildcards_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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


def test_search_loops_escapes_backslash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    with pytest.raises(ValueError, match="invalid_json_response"):
        _extract_json("Just some text")


def test_extract_json_invalid_not_dict():
    """JSON that's not a dict."""
    from cloop.loops.enrichment import _extract_json

    with pytest.raises(ValueError, match="invalid_json_response"):
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
    """Empty string should raise ValueError."""
    from cloop.loops.enrichment import _extract_json

    with pytest.raises(ValueError, match="invalid_json_response"):
        _extract_json("")


def test_extract_json_whitespace_only():
    """Whitespace only should raise ValueError."""
    from cloop.loops.enrichment import _extract_json

    with pytest.raises(ValueError, match="invalid_json_response"):
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
