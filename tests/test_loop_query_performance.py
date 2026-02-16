"""Tests for loop query performance and correctness.

Purpose:
    Verify query performance characteristics and SQL correctness including
    N+1 query prevention, LIKE wildcard escaping, and related loop scalability.

Responsibilities:
    - Test N+1 query prevention in list_loops
    - Test embedding fetch limits and exclusions
    - Test find_related_loops respects max_candidates setting
    - Test LIKE wildcard escaping (%, _, backslash)
    - Verify scalability documentation exists

Non-scope:
    - Query DSL parsing (see test_loops_query.py)
    - CLI/MCP query interfaces (see test_loops_query.py)
    - Loop CRUD operations (see test_loop_capture.py)
"""

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from cloop import db
from cloop.loops import repo, service
from cloop.loops.models import LoopStatus
from cloop.loops.related import find_related_loops
from cloop.settings import get_settings


def test_list_loops_query_count_not_n_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Verify that listing loops uses O(1) queries, not O(n) queries.

    This is a regression test for the N+1 query problem where each loop
    would trigger 2 additional queries (for project and tags).
    """
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
    from cloop.db import init_core_db

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
    docstring = find_related_loops.__doc__
    assert docstring is not None
    assert "O(n)" in docstring or "scalability" in docstring.lower()
    assert "memory" in docstring.lower() or "computation" in docstring.lower()


def test_search_loops_escapes_like_wildcards_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that % in search query is escaped and treated literally."""
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
