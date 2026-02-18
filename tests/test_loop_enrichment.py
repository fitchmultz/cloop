"""Tests for loop enrichment functionality.

Purpose:
    Test suite for the loop enrichment system, including JSON extraction,
    parsing, and enrichment request handling.

Responsibilities:
    - Test _extract_json function with various input formats (plain JSON,
      markdown-wrapped, malformed, unicode, etc.)
    - Test JSON parsing error handling for list and dict fields
    - Test enrichment request behavior for non-existent loops

Non-scope:
    - HTTP API endpoint tests (see test_loop_capture.py, test_loop_transitions.py)
    - Database schema tests (see test_db_schema.py)
    - Embedding/similarity tests (see test_rag.py)

Invariants:
    - All tests use isolated temporary databases
    - Tests that need database access use make_test_client or manual setup
"""

import json
import sqlite3
from pathlib import Path

import pytest

from cloop import db
from cloop.loops import repo
from cloop.loops.enrichment import (
    EnrichmentContext,
    _build_prompt,
    _gather_enrichment_context,
)
from cloop.loops.models import LoopStatus
from cloop.settings import get_settings

# =============================================================================
# JSON extraction tests
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
    from cloop.loops import repo

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
    from cloop.loops import repo

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
    from cloop.loops import repo

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
# Enrichment request tests
# =============================================================================


def test_request_enrichment_raises_for_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that request_enrichment raises LoopNotFoundError for non-existent loop."""
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
# Context-aware enrichment tests
# =============================================================================


def test_gather_enrichment_context_returns_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_gather_enrichment_context returns EnrichmentContext with expected fields."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="test loop for context",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    conn.commit()

    context = _gather_enrichment_context(
        loop_id=record.id,
        loop_text=record.raw_text,
        conn=conn,
        settings=settings,
    )

    assert isinstance(context, EnrichmentContext)
    assert isinstance(context.related_loops, list)
    assert isinstance(context.duplicate_candidates, list)
    assert isinstance(context.workload_snapshot, list)
    assert isinstance(context.existing_links, list)

    conn.close()


def test_build_prompt_includes_context_when_provided() -> None:
    """_build_prompt includes context section in user message when context is available."""
    loop = {"raw_text": "test", "status": "inbox"}
    context = EnrichmentContext(
        related_loops=[{"id": 1, "title": "Related", "status": "actionable"}],
        duplicate_candidates=[],
        workload_snapshot=[{"id": 2, "title": "Workload"}],
        existing_links=[],
    )

    messages = _build_prompt(loop, context=context)

    user_message = json.loads(messages[1]["content"])
    assert "context" in user_message
    assert "related_loops" in user_message["context"]
    assert "current_workload" in user_message["context"]


def test_build_prompt_omits_context_when_empty() -> None:
    """_build_prompt omits context section when context has no data."""

    loop = {"raw_text": "test", "status": "inbox"}
    context = EnrichmentContext(
        related_loops=[],
        duplicate_candidates=[],
        workload_snapshot=[],
        existing_links=[],
    )

    messages = _build_prompt(loop, context=context)

    user_message = json.loads(messages[1]["content"])
    assert "context" not in user_message


def test_build_prompt_works_without_context() -> None:
    """_build_prompt works without context parameter (backward compatibility)."""

    loop = {"raw_text": "test", "status": "inbox"}

    messages = _build_prompt(loop)

    user_message = json.loads(messages[1]["content"])
    assert "context" not in user_message
    assert user_message["raw_text"] == "test"


def test_context_gathering_gracefully_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Context gathering returns empty lists on errors rather than failing."""

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Query for non-existent loop should return empty context
    context = _gather_enrichment_context(
        loop_id=99999,
        loop_text="test",
        conn=conn,
        settings=settings,
    )

    assert context.related_loops == []
    assert context.duplicate_candidates == []
    # Workload may have items from other tests, but shouldn't error
    assert isinstance(context.workload_snapshot, list)

    conn.close()


def test_build_prompt_includes_duplicate_candidates() -> None:
    """_build_prompt includes duplicate candidates when provided."""

    loop = {"raw_text": "test", "status": "inbox"}
    context = EnrichmentContext(
        related_loops=[],
        duplicate_candidates=[{"loop_id": 3, "title": "Duplicate", "score": 0.95}],
        workload_snapshot=[],
        existing_links=[],
    )

    messages = _build_prompt(loop, context=context)

    user_message = json.loads(messages[1]["content"])
    assert "context" in user_message
    assert "potential_duplicates" in user_message["context"]


def test_build_prompt_includes_existing_links() -> None:
    """_build_prompt includes existing links when provided."""

    loop = {"raw_text": "test", "status": "inbox"}
    context = EnrichmentContext(
        related_loops=[],
        duplicate_candidates=[],
        workload_snapshot=[],
        existing_links=[{"related_loop_id": 4, "relationship_type": "depends_on"}],
    )

    messages = _build_prompt(loop, context=context)

    user_message = json.loads(messages[1]["content"])
    assert "context" in user_message
    assert "existing_links" in user_message["context"]


def test_context_in_prompt_contains_all_sections() -> None:
    """_build_prompt includes all context sections when provided."""

    loop = {"raw_text": "test", "status": "inbox"}
    context = EnrichmentContext(
        related_loops=[{"id": 1, "title": "Related"}],
        duplicate_candidates=[{"loop_id": 2, "title": "Duplicate"}],
        workload_snapshot=[{"id": 3, "title": "Workload"}],
        existing_links=[{"related_loop_id": 4, "relationship_type": "blocks"}],
    )

    messages = _build_prompt(loop, context=context)

    user_message = json.loads(messages[1]["content"])
    ctx = user_message["context"]
    assert "related_loops" in ctx
    assert "potential_duplicates" in ctx
    assert "current_workload" in ctx
    assert "existing_links" in ctx
