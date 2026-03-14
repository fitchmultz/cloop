"""Tests for the MCP server module.

This module tests MCP tool functions that expose loop operations
to external AI agents via the Model Context Protocol.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from conftest import _now_iso
from mcp.server.fastmcp.exceptions import ToolError

from cloop import db
from cloop.mcp_tools._runtime import to_tool_error
from cloop.mcp_tools.loop_bulk import loop_bulk_close, loop_bulk_snooze, loop_bulk_update
from cloop.mcp_tools.loop_claims import (
    loop_claim,
    loop_force_release_claim,
    loop_get_claim,
    loop_list_claims,
    loop_release_claim,
    loop_renew_claim,
)
from cloop.mcp_tools.loop_core import (
    loop_close,
    loop_create,
    loop_get,
    loop_transition,
    loop_update,
)
from cloop.mcp_tools.loop_read import (
    loop_enrich,
    loop_list,
    loop_next,
    loop_search,
    loop_snooze,
    loop_tags,
)
from cloop.mcp_tools.loop_templates import project_list
from cloop.mcp_tools.rag_tools import rag_ask, rag_ingest
from cloop.rag import NO_KNOWLEDGE_MESSAGE
from cloop.settings import Settings, get_settings


def _setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure isolated database for testing."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_TTL_SECONDS", "86400")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH", "255")
    get_settings.cache_clear()
    db.init_databases(get_settings())


def _mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock embedding calls for MCP RAG tests."""

    def fake_embed(chunks: list[str], *, settings: Settings | None = None) -> list[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (index + 1) for index, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)


def _mock_rag_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock non-streaming RAG answer generation for MCP tests."""

    def fake_chat_completion(
        messages: list[dict[str, Any]], *, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        return "mock-response", {"model": settings.llm_model, "latency_ms": 9.0}

    monkeypatch.setattr("cloop.rag.ask_orchestration.chat_completion", fake_chat_completion)


# =============================================================================
# loop.create tests
# =============================================================================


def test_loop_create_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful loop creation with default inbox status."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Test loop creation",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    assert result["raw_text"] == "Test loop creation"
    assert result["status"] == "inbox"
    assert "id" in result
    assert isinstance(result["id"], int)
    assert result["id"] > 0


def test_loop_create_with_explicit_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop creation with explicit actionable status."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Actionable item",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="actionable",
    )

    assert result["status"] == "actionable"


def test_loop_create_with_blocked_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop creation with blocked status."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Blocked item",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="blocked",
    )

    assert result["status"] == "blocked"


def test_loop_create_with_scheduled_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop creation with scheduled status."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Scheduled item",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="scheduled",
    )

    assert result["status"] == "scheduled"


def test_loop_create_invalid_status_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop creation with invalid status raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError):
        loop_create(
            raw_text="Test",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
            status="invalid_status",
        )


def test_loop_create_with_tz_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop creation preserves timezone offset."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Test with TZ",
        captured_at=_now_iso(),
        client_tz_offset_min=-300,  # EST (UTC-5)
    )

    assert result["captured_tz_offset_min"] == -300


# =============================================================================
# loop.update tests
# =============================================================================


def test_loop_update_title_and_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful loop update of title and raw_text."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a loop first
    created = loop_create(
        raw_text="Original text",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Update it
    result = loop_update(
        loop_id=loop_id,
        fields={"title": "Updated Title", "raw_text": "Updated text"},
    )

    assert result["title"] == "Updated Title"
    assert result["raw_text"] == "Updated text"


def test_loop_update_not_found_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test updating non-existent loop raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="Loop not found"):
        loop_update(loop_id=99999, fields={"title": "Test"})


def test_loop_update_rejects_status_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that status cannot be updated directly via loop_update."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    with pytest.raises(ToolError, match="Invalid status"):
        loop_update(loop_id=created["id"], fields={"status": "completed"})


def test_loop_update_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating loop with a project."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_update(loop_id=created["id"], fields={"project": "My Project"})

    assert result["project"] == "My Project"


def test_loop_update_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating loop with tags (normalized to lowercase)."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_update(loop_id=created["id"], fields={"tags": ["Feature", "Golf"]})

    assert sorted(result["tags"]) == ["feature", "golf"]


def test_loop_update_clears_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test clearing all tags from a loop."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Add tags first
    loop_update(loop_id=loop_id, fields={"tags": ["tag1", "tag2"]})

    # Clear tags
    result = loop_update(loop_id=loop_id, fields={"tags": []})

    assert result["tags"] == []


def test_loop_update_fields_locked_after_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that updated fields become locked after update."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_update(loop_id=created["id"], fields={"title": "New Title"})

    # Title should be in user_locks after update
    assert "title" in result["user_locks"]


# =============================================================================
# loop.close tests
# =============================================================================


def test_loop_close_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test closing a loop as completed."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Task to complete",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_close(loop_id=created["id"], status="completed", note="Done!")

    assert result["status"] == "completed"
    assert result["completion_note"] == "Done!"
    assert result["closed_at_utc"] is not None


def test_loop_close_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test closing a loop as dropped."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Task to drop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_close(loop_id=created["id"], status="dropped")

    assert result["status"] == "dropped"
    assert result["closed_at_utc"] is not None


def test_loop_close_invalid_status_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test closing with invalid status raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    with pytest.raises(ToolError, match="Invalid status:"):
        loop_close(loop_id=created["id"], status="inbox")


def test_loop_close_not_found_raises_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test closing non-existent loop raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="Loop not found"):
        loop_close(loop_id=99999, status="completed")


def test_loop_close_without_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test closing a loop without a completion note."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_close(loop_id=created["id"], status="completed")

    assert result["status"] == "completed"


def test_loop_close_default_status_is_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that default status for close is 'completed'."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_close(loop_id=created["id"])

    assert result["status"] == "completed"


# =============================================================================
# loop.list tests
# =============================================================================


def test_loop_list_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing all loops."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(3):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    result = loop_list()

    assert len(result["items"]) == 3
    assert "next_cursor" in result
    assert result["limit"] == 50


def test_loop_list_by_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing loops filtered by status."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="Inbox item",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="inbox",
    )
    loop_create(
        raw_text="Actionable item",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="actionable",
    )

    inbox_results = loop_list(status="inbox")
    assert len(inbox_results["items"]) == 1
    assert inbox_results["items"][0]["status"] == "inbox"

    actionable_results = loop_list(status="actionable")
    assert len(actionable_results["items"]) == 1
    assert actionable_results["items"][0]["status"] == "actionable"


def test_loop_list_cursor_pagination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop list cursor-based pagination."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_list(limit=2, cursor=None)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = loop_list(limit=2, cursor=page1["next_cursor"])
    assert len(page2["items"]) == 2
    assert page2["next_cursor"] is not None

    page3 = loop_list(limit=2, cursor=page2["next_cursor"])
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None

    page1_ids = {item["id"] for item in page1["items"]}
    page2_ids = {item["id"] for item in page2["items"]}
    page3_ids = {item["id"] for item in page3["items"]}
    assert page1_ids.isdisjoint(page2_ids)
    assert page2_ids.isdisjoint(page3_ids)


def test_loop_list_returns_all_open_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that list without status returns all open loops."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="Inbox loop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="inbox",
    )
    loop_create(
        raw_text="Actionable loop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="actionable",
    )

    result = loop_list()
    assert len(result["items"]) == 2
    statuses = {r["status"] for r in result["items"]}
    assert statuses == {"inbox", "actionable"}


def test_loop_list_completed_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing completed loops."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_close(loop_id=created["id"], status="completed")

    completed = loop_list(status="completed")
    assert len(completed["items"]) == 1
    assert completed["items"][0]["status"] == "completed"


# =============================================================================
# loop.search tests
# =============================================================================


def test_loop_search_finds_matching_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test searching loops finds matching text."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="Buy groceries from supermarket",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_create(
        raw_text="Finish quarterly report",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    results = loop_search(query="groceries")

    assert len(results["items"]) == 1
    assert "groceries" in results["items"][0]["raw_text"]


def test_loop_search_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test search is case insensitive."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="Buy GROCERIES from supermarket",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    results_lower = loop_search(query="groceries")
    results_upper = loop_search(query="GROCERIES")

    assert len(results_lower["items"]) == 1
    assert len(results_upper["items"]) == 1


def test_loop_search_no_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test search returns empty list when no matches."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="Task one",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    results = loop_search(query="nonexistent")

    assert results["items"] == []


def test_loop_search_with_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test search respects limit parameter."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Task {i} with common keyword",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    results = loop_search(query="common", limit=3)

    assert len(results["items"]) == 3


def test_loop_search_escapes_sql_wildcards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SQL wildcards are escaped in search."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="50% discount",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_create(
        raw_text="500 discount",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    results = loop_search(query="50%")

    assert len(results["items"]) == 1
    assert "50%" in results["items"][0]["raw_text"]


# =============================================================================
# loop.snooze tests
# =============================================================================


def test_loop_snooze_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test snoozing a loop."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Snooze me",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Use second precision to match DB storage
    snooze_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")
    result = loop_snooze(loop_id=created["id"], snooze_until_utc=snooze_time)

    assert result["snooze_until_utc"] == snooze_time


def test_loop_snooze_not_found_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test snoozing non-existent loop raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    snooze_time = datetime.now(timezone.utc).isoformat()

    with pytest.raises(ToolError, match="Loop not found"):
        loop_snooze(loop_id=99999, snooze_until_utc=snooze_time)


def test_loop_snooze_updates_existing_snooze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test updating an existing snooze."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Snooze me",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # First snooze (using second precision to match DB storage)
    snooze_time1 = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")
    loop_snooze(loop_id=loop_id, snooze_until_utc=snooze_time1)

    # Update snooze
    snooze_time2 = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(timespec="seconds")
    result = loop_snooze(loop_id=loop_id, snooze_until_utc=snooze_time2)

    assert result["snooze_until_utc"] == snooze_time2


# =============================================================================
# loop.enrich tests
# =============================================================================


def test_loop_enrich_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful loop enrichment with mocked LLM."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Plan the team offsite for next month",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Mock the litellm.completion call
    mock_response = (
        '{"title": "Team Offsite Planning", '
        '"summary": "Organize team offsite", '
        '"confidence": {"title": 0.9, "summary": 0.9}}',
        {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}},
    )

    with patch("cloop.loops.enrichment.chat_completion", return_value=mock_response):
        result = loop_enrich(loop_id=created["id"])

    assert "loop" in result
    assert "suggestion_id" in result
    assert "applied_fields" in result
    assert result["loop"]["id"] == created["id"]
    assert result["loop"]["raw_text"] == "Plan the team offsite for next month"
    assert result["loop"]["enrichment_state"] == "complete"


def test_loop_enrich_loop_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test enriching non-existent loop raises error."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="Loop not found"):
        loop_enrich(loop_id=99999)


def test_loop_enrich_invalid_json_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test handling of invalid JSON from LLM."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Mock invalid JSON response
    mock_response = ("not valid json", {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}})

    with pytest.raises(ToolError, match="Invalid response"):
        with patch("cloop.loops.enrichment.chat_completion", return_value=mock_response):
            loop_enrich(loop_id=created["id"])


def test_loop_enrich_sets_pending_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that enrichment request sets PENDING state before processing."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    mock_response = (
        '{"title": "Test", "confidence": {"title": 0.9}}',
        {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}},
    )

    with patch("cloop.loops.enrichment.chat_completion", return_value=mock_response):
        enrich_result = loop_enrich(loop_id=created["id"])

    assert enrich_result["loop"]["enrichment_state"] == "complete"

    result = loop_list(status="inbox")
    assert len(result["items"]) == 1
    assert result["items"][0]["enrichment_state"] == "complete"


# =============================================================================
# project.list tests
# =============================================================================


def test_project_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing projects when none exist."""
    _setup_test_db(tmp_path, monkeypatch)

    result = project_list()

    assert result == []


def test_project_list_with_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing projects after creating loops with projects."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a loop with a project via update
    created = loop_create(
        raw_text="Project task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Update with project
    loop_update(loop_id=created["id"], fields={"project": "My Project"})

    result = project_list()

    assert len(result) == 1
    assert result[0]["name"] == "My Project"


def test_project_list_multiple_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing multiple projects."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create loops with different projects
    for project_name in ["Alpha", "Beta", "Gamma"]:
        created = loop_create(
            raw_text=f"Task for {project_name}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )
        loop_update(loop_id=created["id"], fields={"project": project_name})

    result = project_list()
    project_names = {p["name"] for p in result}

    assert len(result) == 3
    assert project_names == {"Alpha", "Beta", "Gamma"}


def test_project_list_sorted_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test projects are sorted alphabetically by name."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create projects in reverse order
    for project_name in ["Zebra", "Apple", "Mango"]:
        created = loop_create(
            raw_text=f"Task for {project_name}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )
        loop_update(loop_id=created["id"], fields={"project": project_name})

    result = project_list()
    names = [p["name"] for p in result]

    assert names == ["Apple", "Mango", "Zebra"]


# =============================================================================
# Integration tests - workflow scenarios
# =============================================================================


def test_full_loop_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test complete lifecycle: create -> update -> snooze -> close."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create
    created = loop_create(
        raw_text="Full lifecycle test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]
    assert created["status"] == "inbox"

    # Update
    updated = loop_update(loop_id=loop_id, fields={"title": "Updated Title"})
    assert updated["title"] == "Updated Title"

    # Snooze (using second precision to match DB storage)
    snooze_time = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(timespec="seconds")
    snoozed = loop_snooze(loop_id=loop_id, snooze_until_utc=snooze_time)
    assert snoozed["snooze_until_utc"] == snooze_time

    # Close
    closed = loop_close(loop_id=loop_id, status="completed", note="Done")
    assert closed["status"] == "completed"
    assert closed["completion_note"] == "Done"


def test_multiple_loops_search_and_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test creating multiple loops and filtering/searching them."""
    _setup_test_db(tmp_path, monkeypatch)

    loop1 = loop_create(
        raw_text="Buy groceries",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="actionable",
    )
    loop_update(loop_id=loop1["id"], fields={"project": "Personal", "tags": ["shopping"]})

    loop2 = loop_create(
        raw_text="Write code review",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="blocked",
    )
    loop_update(loop_id=loop2["id"], fields={"project": "Work", "tags": ["dev"]})

    loop3 = loop_create(
        raw_text="Schedule team meeting",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="scheduled",
    )
    loop_update(loop_id=loop3["id"], fields={"project": "Work", "tags": ["meeting"]})

    actionable_loops = loop_list(status="actionable")
    assert len(actionable_loops["items"]) == 1
    assert actionable_loops["items"][0]["raw_text"] == "Buy groceries"

    blocked_loops = loop_list(status="blocked")
    assert len(blocked_loops["items"]) == 1

    search_results = loop_search(query="groceries")
    assert len(search_results["items"]) == 1

    projects = project_list()
    assert len(projects) == 2


# =============================================================================
# Error handling tests
# =============================================================================


def test_invalid_status_enum_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid status enum values are rejected."""
    _setup_test_db(tmp_path, monkeypatch)

    invalid_statuses = ["", "INBOX", "unknown", "deleted", "archived", "pending"]

    for invalid_status in invalid_statuses:
        with pytest.raises(ToolError):
            loop_create(
                raw_text="Test",
                captured_at=_now_iso(),
                client_tz_offset_min=0,
                status=invalid_status,
            )


# =============================================================================
# Timestamp validation tests
# =============================================================================


def test_loop_create_invalid_timestamp_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_create with invalid timestamp raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    invalid_timestamps = [
        "not-a-timestamp",
        "2024-13-45T99:99:99",
        "",
        "   ",
        "2024/01/15 10:30:00",
    ]

    for invalid_ts in invalid_timestamps:
        with pytest.raises(ToolError, match="Invalid captured_at:"):
            loop_create(
                raw_text="Test",
                captured_at=invalid_ts,
                client_tz_offset_min=0,
            )


def test_loop_snooze_invalid_timestamp_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_snooze with invalid timestamp raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a valid loop first
    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    invalid_timestamps = [
        "not-a-timestamp",
        "2024-13-45T99:99:99",
        "",
    ]

    for invalid_ts in invalid_timestamps:
        with pytest.raises(ToolError, match="Invalid snooze_until_utc:"):
            loop_snooze(loop_id=created["id"], snooze_until_utc=invalid_ts)


def test_loop_create_valid_timestamp_with_z_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_create accepts timestamps with Z suffix."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Test with Z suffix",
        captured_at="2024-01-15T10:30:00Z",
        client_tz_offset_min=0,
    )

    assert result["raw_text"] == "Test with Z suffix"


def test_loop_create_valid_timestamp_with_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_create accepts timestamps with timezone offset."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="Test with offset",
        captured_at="2024-01-15T10:30:00-05:00",
        client_tz_offset_min=-300,
    )

    assert result["raw_text"] == "Test with offset"


def test_loop_snooze_valid_timestamp_with_z_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_snooze accepts timestamps with Z suffix."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    snooze_time = (
        (datetime.now(timezone.utc) + timedelta(days=7))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    result = loop_snooze(loop_id=created["id"], snooze_until_utc=snooze_time)

    assert result["snooze_until_utc"] is not None


def test_loop_update_invalid_due_at_timestamp_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_update with invalid due_at_utc in fields raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a valid loop first
    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Try to update with invalid due_at_utc timestamp
    with pytest.raises(ToolError, match="Invalid due_at_utc:"):
        loop_update(loop_id=created["id"], fields={"due_at_utc": "not-a-timestamp"})


def test_loop_update_invalid_snooze_until_timestamp_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that loop_update with invalid snooze_until_utc in fields raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a valid loop first
    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Try to update with invalid snooze_until_utc timestamp
    with pytest.raises(ToolError, match="Invalid snooze_until_utc:"):
        loop_update(loop_id=created["id"], fields={"snooze_until_utc": "2024-13-45T99:99:99"})


def test_loop_update_valid_timestamps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that loop_update accepts valid timestamp fields."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a valid loop first
    created = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Update with valid timestamps
    due_time = (
        (datetime.now(timezone.utc) + timedelta(days=7))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    snooze_time = (
        (datetime.now(timezone.utc) + timedelta(days=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    result = loop_update(
        loop_id=created["id"],
        fields={"due_at_utc": due_time, "snooze_until_utc": snooze_time},
    )

    assert result["due_at_utc"] is not None
    assert result["snooze_until_utc"] is not None


# =============================================================================
# _to_tool_error unit tests
# =============================================================================


def test_to_tool_error_not_found_error() -> None:
    """Test _to_tool_error correctly maps LoopNotFoundError."""
    from cloop.loops.errors import LoopNotFoundError

    exc = LoopNotFoundError(loop_id=123)
    result = to_tool_error(exc)

    assert isinstance(result, ToolError)
    assert "Loop not found" in str(result)


def test_to_tool_error_validation_error() -> None:
    """Test _to_tool_error correctly maps ValidationError."""
    from cloop.loops.errors import ValidationError

    exc = ValidationError("status", "must be completed or dropped")
    result = to_tool_error(exc)

    assert isinstance(result, ToolError)
    assert "Invalid status" in str(result)


def test_to_tool_error_transition_error() -> None:
    """Test _to_tool_error correctly maps TransitionError."""
    from cloop.loops.errors import TransitionError

    exc = TransitionError("inbox", "completed")
    result = to_tool_error(exc)

    assert isinstance(result, ToolError)
    assert "Invalid status transition" in str(result)
    assert "inbox" in str(result)
    assert "completed" in str(result)


def test_to_tool_error_unknown_exception() -> None:
    """Test _to_tool_error handles unknown exceptions gracefully."""
    exc = RuntimeError("Something unexpected happened")
    result = to_tool_error(exc)

    assert isinstance(result, ToolError)
    assert "Something unexpected happened" in str(result)


# =============================================================================
# Idempotency tests for MCP tools
# =============================================================================


def test_loop_create_idempotency_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + same args returns same response without duplicate loop."""
    import sqlite3

    _setup_test_db(tmp_path, monkeypatch)
    captured_at = _now_iso()

    result1 = loop_create(
        raw_text="idempotent test",
        captured_at=captured_at,
        client_tz_offset_min=0,
        request_id="mcp-key-123",
    )

    result2 = loop_create(
        raw_text="idempotent test",
        captured_at=captured_at,
        client_tz_offset_min=0,
        request_id="mcp-key-123",
    )

    assert result1["id"] == result2["id"]

    settings = get_settings()
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_loop_create_idempotency_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + different args raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)
    captured_at = _now_iso()

    loop_create(
        raw_text="first text",
        captured_at=captured_at,
        client_tz_offset_min=0,
        request_id="mcp-conflict-key",
    )

    with pytest.raises(ToolError, match="Idempotency conflict"):
        loop_create(
            raw_text="different text",
            captured_at=captured_at,
            client_tz_offset_min=0,
            request_id="mcp-conflict-key",
        )


def test_loop_create_idempotency_concurrent_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent same-key MCP create calls replay one created loop."""
    import sqlite3

    _setup_test_db(tmp_path, monkeypatch)
    captured_at = _now_iso()

    def _create_once() -> dict[str, Any]:
        return loop_create(
            raw_text="concurrent create test",
            captured_at=captured_at,
            client_tz_offset_min=0,
            request_id="mcp-concurrent-key",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: _create_once(), range(4)))

    ids = [result["id"] for result in results]
    assert len(set(ids)) == 1

    settings = get_settings()
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_loop_update_idempotency_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + same args for update returns same response."""
    import sqlite3

    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result1 = loop_update(
        loop_id=loop_id,
        fields={"title": "Updated Title"},
        request_id="mcp-update-key",
    )

    result2 = loop_update(
        loop_id=loop_id,
        fields={"title": "Updated Title"},
        request_id="mcp-update-key",
    )

    assert result1["title"] == result2["title"]

    settings = get_settings()
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM loop_events WHERE loop_id = ?", (loop_id,)
        ).fetchone()[0]
    assert count <= 2


def test_loop_update_idempotency_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + different update fields raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="update conflict",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_update(
        loop_id=loop_id,
        fields={"title": "first"},
        request_id="mcp-update-conflict-key",
    )

    with pytest.raises(ToolError, match="Idempotency conflict"):
        loop_update(
            loop_id=loop_id,
            fields={"title": "second"},
            request_id="mcp-update-conflict-key",
        )


def test_loop_close_idempotency_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + same args for close returns same response."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="close test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result1 = loop_close(
        loop_id=created["id"],
        status="completed",
        note="Done",
        request_id="mcp-close-key",
    )

    result2 = loop_close(
        loop_id=created["id"],
        status="completed",
        note="Done",
        request_id="mcp-close-key",
    )

    assert result1["status"] == result2["status"]
    assert result1["completion_note"] == result2["completion_note"]


def test_loop_close_idempotency_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + different close payload raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="close conflict",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_close(
        loop_id=loop_id,
        status="completed",
        note="first-note",
        request_id="mcp-close-conflict-key",
    )

    with pytest.raises(ToolError, match="Idempotency conflict"):
        loop_close(
            loop_id=loop_id,
            status="completed",
            note="different-note",
            request_id="mcp-close-conflict-key",
        )


def test_loop_snooze_idempotency_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + same args for snooze returns same response."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="snooze test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    snooze_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")

    result1 = loop_snooze(
        loop_id=created["id"],
        snooze_until_utc=snooze_time,
        request_id="mcp-snooze-key",
    )

    result2 = loop_snooze(
        loop_id=created["id"],
        snooze_until_utc=snooze_time,
        request_id="mcp-snooze-key",
    )

    assert result1["snooze_until_utc"] == result2["snooze_until_utc"]


def test_loop_snooze_idempotency_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + different snooze time raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="snooze conflict",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    first_snooze = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds")
    second_snooze = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")

    loop_snooze(
        loop_id=loop_id,
        snooze_until_utc=first_snooze,
        request_id="mcp-snooze-conflict-key",
    )

    with pytest.raises(ToolError, match="Idempotency conflict"):
        loop_snooze(
            loop_id=loop_id,
            snooze_until_utc=second_snooze,
            request_id="mcp-snooze-conflict-key",
        )


def test_loop_enrich_idempotency_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id + same args for enrich replays without rerunning enrichment."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="enrich replay",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    class FakeEnrichmentResult:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def to_payload(self) -> dict[str, Any]:
            return self.payload

    mock_response = FakeEnrichmentResult(
        {
            "loop": {"id": loop_id, "status": "inbox", "raw_text": "enrich replay"},
            "suggestion_id": 42,
            "applied_fields": [],
            "needs_clarification": [],
        }
    )

    with patch(
        "cloop.mcp_tools.loop_read.orchestrate_loop_enrichment",
        return_value=mock_response,
    ) as enrich_mock:
        result1 = loop_enrich(loop_id=loop_id, request_id="mcp-enrich-key")
        result2 = loop_enrich(loop_id=loop_id, request_id="mcp-enrich-key")

    assert result1 == result2
    assert enrich_mock.call_count == 1


def test_loop_enrich_idempotency_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request_id on different loop_id values raises ToolError conflict."""
    _setup_test_db(tmp_path, monkeypatch)

    created1 = loop_create(
        raw_text="enrich conflict 1",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    created2 = loop_create(
        raw_text="enrich conflict 2",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    class FakeEnrichmentResult:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def to_payload(self) -> dict[str, Any]:
            return self.payload

    mock_response = FakeEnrichmentResult(
        {
            "loop": {"id": created1["id"], "status": "inbox", "raw_text": "enrich conflict 1"},
            "suggestion_id": 99,
            "applied_fields": [],
            "needs_clarification": [],
        }
    )
    with patch(
        "cloop.mcp_tools.loop_read.orchestrate_loop_enrichment",
        return_value=mock_response,
    ):
        loop_enrich(loop_id=created1["id"], request_id="mcp-enrich-conflict-key")
        with pytest.raises(ToolError, match="Idempotency conflict"):
            loop_enrich(loop_id=created2["id"], request_id="mcp-enrich-conflict-key")


def test_mcp_no_request_id_creates_separate_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without request_id, same args creates separate loops."""
    import sqlite3

    _setup_test_db(tmp_path, monkeypatch)

    result1 = loop_create(
        raw_text="no key test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result2 = loop_create(
        raw_text="no key test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    assert result1["id"] != result2["id"]

    settings = get_settings()
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 2


def test_mcp_different_tools_allow_same_request_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id can be used for different tools."""
    import sqlite3

    _setup_test_db(tmp_path, monkeypatch)

    result = loop_create(
        raw_text="scope test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        request_id="same-tool-key",
    )
    loop_id = result["id"]

    update_result = loop_update(
        loop_id=loop_id,
        fields={"title": "Updated"},
        request_id="same-tool-key",
    )
    assert update_result["title"] == "Updated"

    settings = get_settings()
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


# =============================================================================
# Cursor pagination tests
# =============================================================================


def test_loop_list_cursor_first_page_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor first page returns items, next_cursor, limit."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(3):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    result = loop_list(limit=2, cursor=None)

    assert "items" in result
    assert "next_cursor" in result
    assert "limit" in result
    assert result["limit"] == 2
    assert len(result["items"]) == 2
    assert result["next_cursor"] is not None


def test_loop_list_cursor_subsequent_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Subsequent page with cursor returns non-overlapping segment."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_list(limit=2, cursor=None)
    page2 = loop_list(limit=2, cursor=page1["next_cursor"])

    page1_ids = {item["id"] for item in page1["items"]}
    page2_ids = {item["id"] for item in page2["items"]}
    assert page1_ids.isdisjoint(page2_ids)


def test_loop_list_cursor_final_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Final page yields next_cursor is None."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(3):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_list(limit=2, cursor=None)
    page2 = loop_list(limit=2, cursor=page1["next_cursor"])

    assert page2["next_cursor"] is None


def test_loop_list_malformed_cursor_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed cursor raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="invalid cursor"):
        loop_list(cursor="not-a-valid-cursor")


def test_loop_list_cursor_query_mismatch_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor/query mismatch raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page_inbox = loop_list(status="inbox", limit=2, cursor=None)

    with pytest.raises(ToolError, match="cursor does not match"):
        loop_list(status="actionable", cursor=page_inbox["next_cursor"])


def test_loop_list_cursor_stability_under_concurrent_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor pagination is deterministic under concurrent writes."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_list(limit=3, cursor=None)

    loop_create(
        raw_text="New loop inserted",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    page2 = loop_list(limit=3, cursor=page1["next_cursor"])

    page1_ids = [item["id"] for item in page1["items"]]
    page2_ids = [item["id"] for item in page2["items"]]

    assert page1_ids == sorted(page1_ids, reverse=True)
    assert page2_ids == sorted(page2_ids, reverse=True)
    assert set(page1_ids).isdisjoint(set(page2_ids))


def test_loop_list_cursor_includes_imported_same_day_iso_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor list includes imported rows whose updated_at uses ISO8601 format."""
    _setup_test_db(tmp_path, monkeypatch)

    from cloop.loops import service as loop_service

    settings = get_settings()
    same_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    with db.core_connection(settings) as conn:
        loop_service.import_loops(
            loops=[
                {
                    "raw_text": "Imported same-day",
                    "status": "inbox",
                    "captured_at_utc": same_day.isoformat(),
                    "created_at_utc": same_day.isoformat(),
                    "updated_at_utc": same_day.isoformat(),
                }
            ],
            conn=conn,
        )

    result = loop_list(limit=10, cursor=None)
    assert [item["raw_text"] for item in result["items"]] == ["Imported same-day"]


def test_loop_search_cursor_pagination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Search uses cursor-based pagination."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Task {i} with keyword",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_search(query="keyword", limit=2, cursor=None)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = loop_search(query="keyword", limit=2, cursor=page1["next_cursor"])
    assert len(page2["items"]) == 2
    assert page2["next_cursor"] is not None

    page3 = loop_search(query="keyword", limit=2, cursor=page2["next_cursor"])
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None

    page1_ids = {item["id"] for item in page1["items"]}
    page2_ids = {item["id"] for item in page2["items"]}
    page3_ids = {item["id"] for item in page3["items"]}
    assert page1_ids.isdisjoint(page2_ids)
    assert page1_ids.isdisjoint(page3_ids)
    assert page2_ids.isdisjoint(page3_ids)


def test_loop_search_cursor_mismatch_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Search cursor/query mismatch raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    for i in range(5):
        loop_create(
            raw_text=f"Task {i} keyword",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_search(query="keyword", limit=2, cursor=None)

    with pytest.raises(ToolError, match="cursor does not match"):
        loop_search(query="different", cursor=page1["next_cursor"])


def test_loop_search_status_all_enforces_snapshot_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Search status:all still applies snapshot filter at row level."""
    _setup_test_db(tmp_path, monkeypatch)

    from cloop.loops import service as loop_service

    loop_create(
        raw_text="Visible now",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    settings = get_settings()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    future = now + timedelta(days=1)
    with db.core_connection(settings) as conn:
        loop_service.import_loops(
            loops=[
                {
                    "raw_text": "Future imported",
                    "status": "inbox",
                    "captured_at_utc": now.isoformat(),
                    "created_at_utc": now.isoformat(),
                    "updated_at_utc": future.isoformat(),
                }
            ],
            conn=conn,
        )

    result = loop_search(query="status:all", limit=50, cursor=None)
    texts = {item["raw_text"] for item in result["items"]}
    assert "Visible now" in texts
    assert "Future imported" not in texts


# =============================================================================
# Bulk mutation tests
# =============================================================================


def test_loop_bulk_update_mixed_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bulk update with mixed valid/invalid returns mixed results."""
    _setup_test_db(tmp_path, monkeypatch)

    valid1 = loop_create(
        raw_text="Valid 1",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    valid2 = loop_create(
        raw_text="Valid 2",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_bulk_update(
        updates=[
            {"loop_id": valid1["id"], "fields": {"title": "Updated 1"}},
            {"loop_id": 99999, "fields": {"title": "Invalid"}},
            {"loop_id": valid2["id"], "fields": {"title": "Updated 2"}},
        ],
        transactional=False,
    )

    assert result["ok"] is False
    assert result["transactional"] is False
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert len(result["results"]) == 3

    assert result["results"][0]["ok"] is True
    assert result["results"][0]["loop"]["title"] == "Updated 1"

    assert result["results"][1]["ok"] is False
    assert result["results"][1]["error"]["code"] == "not_found"

    assert result["results"][2]["ok"] is True


def test_loop_bulk_update_transactional_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bulk update transactional mode rolls back all on single invalid."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Valid",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_bulk_update(
        updates=[
            {"loop_id": valid["id"], "fields": {"title": "Should Rollback"}},
            {"loop_id": 99999, "fields": {"title": "Invalid"}},
        ],
        transactional=True,
    )

    assert result["ok"] is False
    assert result["transactional"] is True
    assert result["succeeded"] == 0
    assert result["failed"] == 2

    assert result["results"][0]["ok"] is False
    assert result["results"][0]["error"]["code"] == "transaction_rollback"
    assert result["results"][0]["error"]["rolled_back"] is True
    assert result["results"][1]["ok"] is False
    assert result["results"][1]["error"]["code"] == "not_found"
    assert result["results"][1]["error"]["rolled_back"] is True

    check = loop_list(status="inbox")
    assert len(check["items"]) == 1
    assert check["items"][0]["title"] is None


def test_loop_bulk_close_mixed_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bulk close with mixed valid/invalid returns mixed results."""
    _setup_test_db(tmp_path, monkeypatch)

    valid1 = loop_create(
        raw_text="Valid 1",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    valid2 = loop_create(
        raw_text="Valid 2",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_bulk_close(
        items=[
            {"loop_id": valid1["id"], "status": "completed", "note": "Done 1"},
            {"loop_id": 99999, "status": "completed"},
            {"loop_id": valid2["id"], "status": "dropped"},
        ],
        transactional=False,
    )

    assert result["ok"] is False
    assert result["succeeded"] == 2
    assert result["failed"] == 1

    assert result["results"][0]["ok"] is True
    assert result["results"][0]["loop"]["status"] == "completed"
    assert result["results"][0]["loop"]["completion_note"] == "Done 1"

    assert result["results"][1]["ok"] is False
    assert result["results"][1]["error"]["code"] == "not_found"

    assert result["results"][2]["ok"] is True
    assert result["results"][2]["loop"]["status"] == "dropped"


def test_loop_bulk_close_transactional_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bulk close transactional mode rolls back all on single invalid."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Valid",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result = loop_bulk_close(
        items=[
            {"loop_id": valid["id"], "status": "completed"},
            {"loop_id": 99999, "status": "completed"},
        ],
        transactional=True,
    )

    assert result["ok"] is False
    assert result["transactional"] is True
    assert result["succeeded"] == 0
    assert result["failed"] == 2

    assert result["results"][0]["error"]["code"] == "transaction_rollback"
    assert result["results"][0]["error"]["rolled_back"] is True
    assert result["results"][1]["error"]["code"] == "not_found"
    assert result["results"][1]["error"]["rolled_back"] is True

    check = loop_list(status="inbox")
    assert len(check["items"]) == 1


def test_loop_bulk_snooze_mixed_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bulk snooze with mixed valid/invalid returns mixed results."""
    _setup_test_db(tmp_path, monkeypatch)

    valid1 = loop_create(
        raw_text="Valid 1",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    valid2 = loop_create(
        raw_text="Valid 2",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    snooze_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")

    result = loop_bulk_snooze(
        items=[
            {"loop_id": valid1["id"], "snooze_until_utc": snooze_time},
            {"loop_id": 99999, "snooze_until_utc": snooze_time},
            {"loop_id": valid2["id"], "snooze_until_utc": snooze_time},
        ],
        transactional=False,
    )

    assert result["ok"] is False
    assert result["succeeded"] == 2
    assert result["failed"] == 1

    assert result["results"][0]["ok"] is True
    assert result["results"][0]["loop"]["snooze_until_utc"] == snooze_time

    assert result["results"][1]["ok"] is False
    assert result["results"][1]["error"]["code"] == "not_found"

    assert result["results"][2]["ok"] is True


def test_loop_bulk_snooze_transactional_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bulk snooze transactional mode rolls back all on single invalid."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Valid",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    snooze_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")

    result = loop_bulk_snooze(
        items=[
            {"loop_id": valid["id"], "snooze_until_utc": snooze_time},
            {"loop_id": 99999, "snooze_until_utc": snooze_time},
        ],
        transactional=True,
    )

    assert result["ok"] is False
    assert result["transactional"] is True
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["results"][0]["error"]["code"] == "transaction_rollback"
    assert result["results"][0]["error"]["rolled_back"] is True
    assert result["results"][1]["error"]["code"] == "not_found"
    assert result["results"][1]["error"]["rolled_back"] is True

    check = loop_list(status="inbox")
    assert len(check["items"]) == 1
    assert check["items"][0]["snooze_until_utc"] is None


def test_loop_bulk_update_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id + same args for bulk_update replays."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result1 = loop_bulk_update(
        updates=[{"loop_id": valid["id"], "fields": {"title": "Updated"}}],
        transactional=False,
        request_id="bulk-update-key",
    )

    result2 = loop_bulk_update(
        updates=[{"loop_id": valid["id"], "fields": {"title": "Updated"}}],
        transactional=False,
        request_id="bulk-update-key",
    )

    assert result1 == result2


def test_loop_bulk_update_idempotency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id + different bulk_update args raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    loop_bulk_update(
        updates=[{"loop_id": valid["id"], "fields": {"title": "First"}}],
        transactional=False,
        request_id="bulk-update-conflict",
    )

    with pytest.raises(ToolError, match="Idempotency conflict"):
        loop_bulk_update(
            updates=[{"loop_id": valid["id"], "fields": {"title": "Different"}}],
            transactional=False,
            request_id="bulk-update-conflict",
        )


def test_loop_bulk_close_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id + same args for bulk_close replays."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    result1 = loop_bulk_close(
        items=[{"loop_id": valid["id"], "status": "completed"}],
        transactional=False,
        request_id="bulk-close-key",
    )

    result2 = loop_bulk_close(
        items=[{"loop_id": valid["id"], "status": "completed"}],
        transactional=False,
        request_id="bulk-close-key",
    )

    assert result1 == result2


def test_loop_bulk_snooze_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id + same args for bulk_snooze replays."""
    _setup_test_db(tmp_path, monkeypatch)

    valid = loop_create(
        raw_text="Test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    snooze_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")

    result1 = loop_bulk_snooze(
        items=[{"loop_id": valid["id"], "snooze_until_utc": snooze_time}],
        transactional=False,
        request_id="bulk-snooze-key",
    )

    result2 = loop_bulk_snooze(
        items=[{"loop_id": valid["id"], "snooze_until_utc": snooze_time}],
        transactional=False,
        request_id="bulk-snooze-key",
    )

    assert result1 == result2


def test_loop_bulk_update_exceeds_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP bulk_update with more than limit items should raise ToolError."""
    from mcp.server.fastmcp.exceptions import ToolError

    from cloop.constants import BULK_OPERATION_MAX_ITEMS

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    from cloop.settings import get_settings

    get_settings.cache_clear()
    from cloop import db

    db.init_databases(get_settings())

    # Create more items than the limit
    updates = [
        {"loop_id": i, "fields": {"next_action": f"action {i}"}}
        for i in range(BULK_OPERATION_MAX_ITEMS + 10)
    ]

    with pytest.raises(ToolError) as exc_info:
        loop_bulk_update(updates=updates)

    assert "exceeds maximum items limit" in str(exc_info.value)


def test_loop_bulk_close_exceeds_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP bulk_close with more than limit items should raise ToolError."""
    from mcp.server.fastmcp.exceptions import ToolError

    from cloop.constants import BULK_OPERATION_MAX_ITEMS

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    from cloop.settings import get_settings

    get_settings.cache_clear()
    from cloop import db

    db.init_databases(get_settings())

    # Create more items than the limit
    items = [{"loop_id": i, "status": "completed"} for i in range(BULK_OPERATION_MAX_ITEMS + 10)]

    with pytest.raises(ToolError) as exc_info:
        loop_bulk_close(items=items)

    assert "exceeds maximum items limit" in str(exc_info.value)


def test_loop_bulk_snooze_exceeds_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP bulk_snooze with more than limit items should raise ToolError."""
    from mcp.server.fastmcp.exceptions import ToolError

    from cloop.constants import BULK_OPERATION_MAX_ITEMS

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    from cloop.settings import get_settings

    get_settings.cache_clear()
    from cloop import db

    db.init_databases(get_settings())

    # Create more items than the limit
    items = [
        {"loop_id": i, "snooze_until_utc": "2024-02-01T12:00:00Z"}
        for i in range(BULK_OPERATION_MAX_ITEMS + 10)
    ]

    with pytest.raises(ToolError) as exc_info:
        loop_bulk_snooze(items=items)

    assert "exceeds maximum items limit" in str(exc_info.value)


# =============================================================================
# loop.claim tests
# =============================================================================


def test_loop_claim_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful loop claim via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    assert result["loop_id"] == loop_id
    assert result["owner"] == "agent-alpha"
    assert "claim_token" in result
    assert len(result["claim_token"]) == 64  # 32 bytes = 64 hex chars


def test_loop_claim_already_claimed_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that claiming an already-claimed loop fails."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test claim conflict",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # First claim succeeds
    loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    # Second claim fails
    with pytest.raises(ToolError, match="claimed by"):
        loop_claim(loop_id=loop_id, owner="agent-beta", ttl_seconds=300)


def test_loop_update_with_claim_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating a claimed loop with valid token."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test update with claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    claim = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    result = loop_update(
        loop_id=loop_id,
        fields={"title": "Updated title"},
        claim_token=claim["claim_token"],
    )

    assert result["title"] == "Updated title"


def test_loop_update_without_claim_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that updating a claimed loop without token fails."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test update without claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    with pytest.raises(ToolError, match="claimed by"):
        loop_update(loop_id=loop_id, fields={"title": "Updated title"})


def test_loop_renew_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test renewing a claim via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test renew",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    claim = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=60)

    renewed = loop_renew_claim(
        loop_id=loop_id,
        claim_token=claim["claim_token"],
        ttl_seconds=300,
    )

    assert renewed["claim_token"] == claim["claim_token"]
    assert renewed["owner"] == "agent-alpha"


def test_loop_release_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test releasing a claim via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test release",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    claim = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    result = loop_release_claim(loop_id=loop_id, claim_token=claim["claim_token"])

    assert result["ok"] is True

    # Another agent can now claim
    new_claim = loop_claim(loop_id=loop_id, owner="agent-beta", ttl_seconds=300)
    assert new_claim["owner"] == "agent-beta"


def test_loop_get_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test getting claim status via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test get claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    result = loop_get_claim(loop_id=loop_id)

    assert result is not None
    assert result["loop_id"] == loop_id
    assert result["owner"] == "agent-alpha"
    assert "claim_token" not in result  # Token should NOT be exposed


def test_loop_get_claim_unclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test getting claim status for unclaimed loop."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test unclaimed",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result = loop_get_claim(loop_id=loop_id)

    assert result is None


def test_loop_list_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing claims via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created1 = loop_create(
        raw_text="Test list 1",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    created2 = loop_create(
        raw_text="Test list 2",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    loop_claim(loop_id=created1["id"], owner="agent-alpha", ttl_seconds=300)
    loop_claim(loop_id=created2["id"], owner="agent-beta", ttl_seconds=300)

    # List all
    all_claims = loop_list_claims()
    assert len(all_claims) == 2

    # Filter by owner
    alpha_claims = loop_list_claims(owner="agent-alpha")
    assert len(alpha_claims) == 1
    assert alpha_claims[0]["owner"] == "agent-alpha"


def test_loop_claim_idempotency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test claim idempotency via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test idempotency",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result1 = loop_claim(
        loop_id=loop_id,
        owner="agent-alpha",
        ttl_seconds=300,
        request_id="claim-key-1",
    )

    result2 = loop_claim(
        loop_id=loop_id,
        owner="agent-alpha",
        ttl_seconds=300,
        request_id="claim-key-1",
    )

    # Should return same result
    assert result1["claim_token"] == result2["claim_token"]


def test_loop_force_release_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test force-releasing a claim via MCP (admin override)."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test force release",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Claim with agent-alpha
    claim = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)
    assert claim["owner"] == "agent-alpha"

    # Force release (no token required)
    result = loop_force_release_claim(loop_id=loop_id)

    assert result["ok"] is True
    assert result["released"] is True

    # Another agent can now claim
    new_claim = loop_claim(loop_id=loop_id, owner="agent-beta", ttl_seconds=300)
    assert new_claim["owner"] == "agent-beta"


def test_loop_force_release_unclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force-releasing an unclaimed loop returns released=False."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test force release unclaimed",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Force release without any claim
    result = loop_force_release_claim(loop_id=loop_id)

    assert result["ok"] is True
    assert result["released"] is False


def test_loop_close_with_claim_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test closing a claimed loop with valid token via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test close with claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    claim = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    result = loop_close(
        loop_id=loop_id,
        status="completed",
        claim_token=claim["claim_token"],
    )

    assert result["status"] == "completed"


def test_loop_close_without_claim_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that closing a claimed loop without token fails via MCP."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test close without claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    with pytest.raises(ToolError, match="claimed by"):
        loop_close(loop_id=loop_id, status="completed")


# =============================================================================
# loop.get tests
# =============================================================================


def test_loop_get_existing_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.get retrieves an existing loop by ID."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test loop for retrieval",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result = loop_get(loop_id=loop_id)

    assert result["id"] == loop_id
    assert result["raw_text"] == "Test loop for retrieval"
    assert result["status"] == "inbox"


def test_loop_get_nonexistent_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.get returns error for nonexistent loop."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="Loop not found"):
        loop_get(loop_id=99999)


def test_loop_get_returns_full_loop_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.get returns all loop fields including tags and project."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Full data test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Update with project and tags
    loop_update(
        loop_id=loop_id,
        fields={"project": "My Project", "tags": ["work", "urgent"]},
    )

    result = loop_get(loop_id=loop_id)

    assert result["id"] == loop_id
    assert result["raw_text"] == "Full data test"
    assert result["project"] == "My Project"
    assert sorted(result["tags"]) == ["urgent", "work"]
    assert "created_at_utc" in result
    assert "updated_at_utc" in result


# =============================================================================
# loop.next tests
# =============================================================================


def test_loop_next_returns_buckets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.next returns prioritized buckets."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create some loops with next_action to make them actionable candidates
    for i in range(3):
        created = loop_create(
            raw_text=f"Actionable loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )
        # Update with next_action to make them actionable for next_loops
        loop_update(
            loop_id=created["id"],
            fields={"next_action": f"Do step {i}"},
        )

    result = loop_next(limit=5)

    # Should have all bucket keys
    assert "due_soon" in result
    assert "quick_wins" in result
    assert "high_leverage" in result
    assert "standard" in result

    # Each bucket should be a list
    for _bucket_name, items in result.items():
        assert isinstance(items, list)

    # Total items across all buckets should be 3
    total = sum(len(items) for items in result.values())
    assert total == 3


def test_loop_next_respects_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.next respects the limit parameter globally across all buckets."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create 5 loops with next_action
    for i in range(5):
        created = loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )
        loop_update(
            loop_id=created["id"],
            fields={"next_action": f"Step {i}"},
        )

    result = loop_next(limit=2)

    # Total across all buckets should be <= limit
    total = sum(len(items) for items in result.values())
    assert total <= 2, f"Expected at most 2 total items, got {total}"


def test_loop_next_empty_when_no_actionable_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.next returns empty buckets when no actionable loops."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create loops WITHOUT next_action - they won't appear in next_loops
    for i in range(3):
        loop_create(
            raw_text=f"Inbox loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
            status="inbox",
        )

    result = loop_next(limit=5)

    # All buckets should be empty since none have next_action
    for _bucket_name, items in result.items():
        assert items == []


def test_loop_next_skips_snoozed_loops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.next skips snoozed loops."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a normal loop with next_action
    created1 = loop_create(
        raw_text="Active loop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_update(
        loop_id=created1["id"],
        fields={"next_action": "Do something"},
    )

    # Create a snoozed loop with next_action
    created2 = loop_create(
        raw_text="Snoozed loop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_update(
        loop_id=created2["id"],
        fields={"next_action": "Do something later"},
    )

    # Snooze the second loop
    snooze_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")
    loop_snooze(loop_id=created2["id"], snooze_until_utc=snooze_time)

    result = loop_next(limit=5)

    # Only the active loop should appear
    total = sum(len(items) for items in result.values())
    assert total == 1

    # Verify it's the active loop
    all_items = [item for bucket in result.values() for item in bucket]
    assert len(all_items) == 1
    assert all_items[0]["raw_text"] == "Active loop"


# =============================================================================
# loop.transition tests
# =============================================================================


def test_loop_transition_inbox_to_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition changes loop status from inbox to actionable."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create a loop (starts in inbox)
    created = loop_create(
        raw_text="Transition test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]
    assert created["status"] == "inbox"

    # Transition to actionable
    result = loop_transition(loop_id=loop_id, status="actionable")

    assert result["status"] == "actionable"


def test_loop_transition_actionable_to_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition from actionable to blocked."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Block test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="actionable",
    )
    loop_id = created["id"]

    result = loop_transition(loop_id=loop_id, status="blocked")

    assert result["status"] == "blocked"


def test_loop_transition_blocked_to_scheduled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition from blocked to scheduled."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Schedule test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="blocked",
    )
    loop_id = created["id"]

    result = loop_transition(loop_id=loop_id, status="scheduled")

    assert result["status"] == "scheduled"


def test_loop_transition_scheduled_to_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition from scheduled to actionable."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Unschedule test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
        status="scheduled",
    )
    loop_id = created["id"]

    result = loop_transition(loop_id=loop_id, status="actionable")

    assert result["status"] == "actionable"


def test_loop_transition_reopens_completed_to_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition can reopen completed loop to inbox."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Reopen test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Close first
    loop_close(loop_id=loop_id, status="completed")

    # Reopen to inbox
    result = loop_transition(loop_id=loop_id, status="inbox")

    assert result["status"] == "inbox"
    assert result["closed_at_utc"] is None


def test_loop_transition_reopens_dropped_to_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition can reopen dropped loop to actionable."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Reopen dropped test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Close as dropped
    loop_close(loop_id=loop_id, status="dropped")

    # Reopen to actionable
    result = loop_transition(loop_id=loop_id, status="actionable")

    assert result["status"] == "actionable"


def test_loop_transition_invalid_status_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition rejects invalid status values."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Invalid transition test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    with pytest.raises(ToolError):
        loop_transition(loop_id=loop_id, status="invalid_status")


def test_loop_transition_rejects_terminal_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loop.transition rejects terminal statuses (completed/dropped)."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Terminal transition test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    # Should fail for completed
    with pytest.raises(ToolError, match="use loop.close"):
        loop_transition(loop_id=loop_id, status="completed")

    # Should fail for dropped
    with pytest.raises(ToolError, match="use loop.close"):
        loop_transition(loop_id=loop_id, status="dropped")


def test_loop_transition_nonexistent_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.transition raises error for nonexistent loop."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="Loop not found"):
        loop_transition(loop_id=99999, status="actionable")


def test_loop_transition_with_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.transition with a transition note."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Note transition test",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result = loop_transition(
        loop_id=loop_id,
        status="blocked",
        note="Waiting for external approval",
    )

    assert result["status"] == "blocked"
    # The note may be stored in the event but not necessarily in the loop record


def test_loop_transition_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id + same args for transition returns same response."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Idempotent transition",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    result1 = loop_transition(
        loop_id=loop_id,
        status="actionable",
        request_id="transition-key",
    )

    result2 = loop_transition(
        loop_id=loop_id,
        status="actionable",
        request_id="transition-key",
    )

    assert result1["id"] == result2["id"]
    assert result1["status"] == result2["status"]


def test_loop_transition_idempotency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same request_id + different transition args raises ToolError."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Conflict transition",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_transition(
        loop_id=loop_id,
        status="actionable",
        request_id="transition-conflict-key",
    )

    with pytest.raises(ToolError, match="Idempotency conflict"):
        loop_transition(
            loop_id=loop_id,
            status="blocked",
            request_id="transition-conflict-key",
        )


def test_loop_transition_with_claim_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test transitioning a claimed loop with valid token."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Transition with claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    claim = loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    result = loop_transition(
        loop_id=loop_id,
        status="actionable",
        claim_token=claim["claim_token"],
    )

    assert result["status"] == "actionable"


def test_loop_transition_without_claim_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that transitioning a claimed loop without token fails."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Transition without claim",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_id = created["id"]

    loop_claim(loop_id=loop_id, owner="agent-alpha", ttl_seconds=300)

    with pytest.raises(ToolError, match="claimed by"):
        loop_transition(loop_id=loop_id, status="actionable")


# =============================================================================
# loop.tags tests
# =============================================================================


def test_loop_tags_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.tags returns empty list when no tags exist."""
    _setup_test_db(tmp_path, monkeypatch)

    result = loop_tags()

    assert result == []


def test_loop_tags_returns_unique_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.tags returns unique tags across all loops."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create loops with overlapping tags
    created1 = loop_create(
        raw_text="First loop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_update(loop_id=created1["id"], fields={"tags": ["work", "urgent", "feature"]})

    created2 = loop_create(
        raw_text="Second loop",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_update(loop_id=created2["id"], fields={"tags": ["work", "personal", "bug"]})

    result = loop_tags()

    # Should be a list
    assert isinstance(result, list)

    # Should include all unique tags (normalized to lowercase)
    assert "work" in result  # common tag
    assert "urgent" in result
    assert "feature" in result
    assert "personal" in result
    assert "bug" in result

    # Should be sorted alphabetically
    assert result == sorted(result)


def test_loop_tags_are_lowercase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.tags returns tags in lowercase."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Mixed case tags",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_update(loop_id=created["id"], fields={"tags": ["WORK", "Urgent", "Feature"]})

    result = loop_tags()

    assert "work" in result
    assert "urgent" in result
    assert "feature" in result
    assert "WORK" not in result
    assert "Urgent" not in result


def test_loop_tags_excludes_empty_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop.tags excludes loops without tags."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create loop without tags
    loop_create(
        raw_text="No tags",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    # Create loop with tags
    created = loop_create(
        raw_text="Has tags",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_update(loop_id=created["id"], fields={"tags": ["tagged"]})

    result = loop_tags()

    assert result == ["tagged"]


# =============================================================================
# rag.ask / rag.ingest tests
# =============================================================================


def test_rag_ingest_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rag.ingest should index supported files and report skipped counts."""
    _setup_test_db(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    doc = tmp_path / "knowledge.txt"
    doc.write_text("FastAPI helps build APIs quickly.", encoding="utf-8")

    result = rag_ingest(paths=[str(doc)])

    assert result["files"] == 1
    assert result["chunks"] >= 1
    assert result["files_skipped"] == 0
    assert result["failed_files"] == []

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT endpoint, request_payload FROM interactions "
            "WHERE endpoint = '/mcp/rag.ingest' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["endpoint"] == "/mcp/rag.ingest"


def test_rag_ingest_rejects_empty_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rag.ingest should reject empty path lists."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="paths cannot be empty"):
        rag_ingest(paths=[])


def test_rag_ask_without_knowledge_returns_shared_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rag.ask should return the shared no-knowledge payload instead of failing."""
    _setup_test_db(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    result = rag_ask(question="What do I know?")

    assert result["answer"] == NO_KNOWLEDGE_MESSAGE
    assert result["chunks"] == []
    assert result["sources"] == []
    assert result["model"] is None


def test_rag_ask_returns_answer_chunks_and_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rag.ask should reuse the shared ask contract and log the MCP interaction."""
    _setup_test_db(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)
    _mock_rag_answer(monkeypatch)

    doc = tmp_path / "faq.txt"
    doc.write_text("FastAPI is a modern web framework.", encoding="utf-8")
    rag_ingest(paths=[str(doc)])

    result = rag_ask(question="What is FastAPI?", top_k=5)

    assert result["answer"] == "mock-response"
    assert result["model"] == "mock-llm"
    assert result["chunks"]
    assert result["sources"]
    for chunk in result["chunks"]:
        assert "embedding_blob" not in chunk

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload, selected_chunks FROM interactions "
            "WHERE endpoint = '/mcp/rag.ask' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    response_payload = row["response_payload"]
    selected_chunks = row["selected_chunks"]
    assert "mock-response" in response_payload
    assert "faq.txt" in selected_chunks


def test_rag_ask_rejects_non_positive_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rag.ask should reject non-positive retrieval limits."""
    _setup_test_db(tmp_path, monkeypatch)

    with pytest.raises(ToolError, match="top_k must be positive"):
        rag_ask(question="test", top_k=0)
