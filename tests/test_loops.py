from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.loops.prioritization import bucketize
from cloop.main import app
from cloop.settings import Settings, get_settings


def _test_settings() -> Settings:
    """Create a Settings object with default test values."""
    return Settings(
        root_dir=Path.cwd(),
        core_db_path=Path("./data/core.db"),
        rag_db_path=Path("./data/rag.db"),
        llm_model="ollama/llama3",
        embed_model="ollama/nomic-embed-text",
        default_top_k=5,
        chunk_size=800,
        llm_timeout=30.0,
        ingest_timeout=60.0,
        embedding_timeout=30.0,
        sqlite_vector_extension=None,
        vector_search_mode="python",  # type: ignore[arg-type]
        tool_mode_default="manual",  # type: ignore[arg-type]
        embed_storage_mode="dual",  # type: ignore[arg-type]
        openai_api_base=None,
        openai_api_key=None,
        google_api_key=None,
        ollama_api_base=None,
        lmstudio_api_base=None,
        openrouter_api_base=None,
        stream_default=False,
        organizer_model="gemini/gemini-3-flash-preview",
        organizer_timeout=20.0,
        autopilot_enabled=False,
        autopilot_autoapply_min_confidence=0.85,
        max_file_size_mb=50,
        prioritization_due_window_hours=72.0,
        prioritization_due_soon_hours=48.0,
        prioritization_quick_win_minutes=15,
        prioritization_high_leverage_threshold=0.7,
        related_similarity_threshold=0.78,
        related_max_candidates=1000,
    )


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
    settings = _test_settings()

    # Loop with low importance, not due soon, not a quick win
    loop = {
        "importance": 0.1,
        "time_minutes": 120,
        "activation_energy": 3,
        # No due_at_utc, so not due_soon
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard", f"Expected 'standard' for low importance loop, got '{result}'"


def test_bucketize_returns_high_leverage_for_high_importance() -> None:
    """High importance loops should be classified as high_leverage."""
    now = datetime.now(timezone.utc)
    settings = _test_settings()

    loop = {
        "importance": 0.8,
        "time_minutes": 120,
        "activation_energy": 3,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "high_leverage"


def test_bucketize_returns_due_soon_for_urgent_due_date() -> None:
    """Loops due within 48h should be due_soon regardless of other factors."""
    now = datetime.now(timezone.utc)
    settings = _test_settings()

    loop = {
        "importance": 0.9,  # High importance
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
        "time_minutes": 5,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "due_soon"


def test_bucketize_returns_quick_wins_for_small_tasks() -> None:
    """Short, low-energy tasks should be quick_wins."""
    now = datetime.now(timezone.utc)
    settings = _test_settings()

    loop = {
        "importance": 0.9,  # High importance
        "time_minutes": 10,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "quick_wins"


def test_bucketize_handles_none_importance() -> None:
    """Loops without importance should default to standard."""
    now = datetime.now(timezone.utc)
    settings = _test_settings()

    loop = {
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard"


def test_bucketize_importance_boundary_high() -> None:
    """Loop with importance exactly 0.7 should be high_leverage."""
    now = datetime.now(timezone.utc)
    settings = _test_settings()

    loop = {
        "importance": 0.7,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "high_leverage"


def test_bucketize_importance_boundary_low() -> None:
    """Loop with importance just below 0.7 should be standard."""
    now = datetime.now(timezone.utc)
    settings = _test_settings()

    loop = {
        "importance": 0.69,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
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


def test_fetch_loop_embeddings_with_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


# =============================================================================
# JSON parsing error handling tests
# =============================================================================


def test_parse_json_list_raises_on_malformed_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that invalid captured_at format returns 422 with clear error."""
    client = _make_client(tmp_path, monkeypatch)

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
        assert response.status_code == 422, f"Expected 422 for '{invalid_ts}'"
        error_detail = response.json()
        assert "error" in error_detail
        # Check that the error message mentions validation
        error_str = str(error_detail).lower()
        assert "invalid_captured_at" in error_str or "validation" in error_str


def test_loop_update_invalid_due_at_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid due_at_utc format returns 422 with clear error."""
    client = _make_client(tmp_path, monkeypatch)

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
    assert response.status_code == 422
    error_detail = response.json()
    assert "error" in error_detail
    error_str = str(error_detail).lower()
    assert "invalid_due_at_utc" in error_str or "validation" in error_str


def test_loop_update_invalid_snooze_until_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that invalid snooze_until_utc format returns 422 with clear error."""
    client = _make_client(tmp_path, monkeypatch)

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
    assert response.status_code == 422
    error_detail = response.json()
    assert "error" in error_detail


def test_loop_capture_valid_timestamp_with_z_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that timestamps with Z suffix are accepted."""
    client = _make_client(tmp_path, monkeypatch)

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that timestamps with timezone offset are accepted."""
    client = _make_client(tmp_path, monkeypatch)

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
# update_loop_fields validation tests
# =============================================================================


def test_update_loop_fields_rejects_invalid_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that update_loop_fields raises ValueError for invalid field names."""
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
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Try to update with an invalid field name
    with pytest.raises(ValueError, match="invalid_field:typo_field"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"typo_field": "some value"},
            conn=conn,
        )

    # Try with mix of valid and invalid - should still fail
    with pytest.raises(ValueError, match="invalid_field"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"title": "Valid title", "another_typo": "bad"},
            conn=conn,
        )

    conn.close()


def test_update_loop_fields_rejects_multiple_invalid_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that error message includes all invalid fields, sorted alphabetically."""
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
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Try with multiple invalid fields - should list all, sorted
    with pytest.raises(ValueError, match=r"invalid_field:alpha_field, zebra_field"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"zebra_field": "z", "alpha_field": "a"},
            conn=conn,
        )

    conn.close()
