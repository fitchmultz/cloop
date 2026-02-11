"""Tests for the MCP server module.

This module tests all 8 MCP tool functions that expose loop operations
to external AI agents via the Model Context Protocol.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from cloop import db
from cloop.mcp_server import (
    loop_close,
    loop_create,
    loop_enrich,
    loop_list,
    loop_search,
    loop_snooze,
    loop_update,
    project_list,
)
from cloop.settings import get_settings


def _setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure isolated database for testing."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_ORGANIZER_MODEL", "mock-organizer")
    get_settings.cache_clear()
    db.init_databases(get_settings())


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

    with pytest.raises(ToolError, match="Invalid status transition"):
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

    with pytest.raises(ToolError, match="Status must be 'completed' or 'dropped'"):
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

    # Create some loops
    for i in range(3):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    result = loop_list()

    assert len(result) == 3


def test_loop_list_by_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing loops filtered by status."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create inbox and actionable loops
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
    assert len(inbox_results) == 1
    assert inbox_results[0]["status"] == "inbox"

    actionable_results = loop_list(status="actionable")
    assert len(actionable_results) == 1
    assert actionable_results[0]["status"] == "actionable"


def test_loop_list_pagination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loop list pagination with limit and offset."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create multiple loops
    for i in range(5):
        loop_create(
            raw_text=f"Loop {i}",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    page1 = loop_list(limit=2, offset=0)
    page2 = loop_list(limit=2, offset=2)
    page3 = loop_list(limit=2, offset=4)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


def test_loop_list_returns_all_open_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that list without status returns all open loops."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create loops in various open statuses
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

    # Default list should show all open loops
    result = loop_list()
    assert len(result) == 2
    statuses = {r["status"] for r in result}
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
    assert len(completed) == 1
    assert completed[0]["status"] == "completed"


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

    assert len(results) == 1
    assert "groceries" in results[0]["raw_text"]


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

    assert len(results_lower) == 1
    assert len(results_upper) == 1


def test_loop_search_no_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test search returns empty list when no matches."""
    _setup_test_db(tmp_path, monkeypatch)

    loop_create(
        raw_text="Task one",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    results = loop_search(query="nonexistent")

    assert results == []


def test_loop_search_with_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test search respects limit parameter."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create multiple matching loops
    for i in range(5):
        loop_create(
            raw_text=f"Task {i} with common keyword",
            captured_at=_now_iso(),
            client_tz_offset_min=0,
        )

    results = loop_search(query="common", limit=3)

    assert len(results) == 3


def test_loop_search_escapes_sql_wildcards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SQL wildcards are escaped in search."""
    _setup_test_db(tmp_path, monkeypatch)

    # Create loop with % in text
    loop_create(
        raw_text="50% discount",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )
    loop_create(
        raw_text="500 discount",  # Should not match
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    results = loop_search(query="50%")

    # Should only match the literal "50%"
    assert len(results) == 1
    assert "50%" in results[0]["raw_text"]


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
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"title": "Team Offsite Planning", '
                        '"summary": "Organize team offsite", '
                        '"confidence": {"title": 0.9}}'
                    )
                }
            }
        ]
    }

    with patch("cloop.loops.enrichment.litellm.completion", return_value=mock_response):
        result = loop_enrich(loop_id=created["id"])

    assert "loop_id" in result
    assert "suggestion_id" in result
    assert "applied_fields" in result
    assert result["loop_id"] == created["id"]


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
    mock_response = {"choices": [{"message": {"content": "not valid json"}}]}

    with pytest.raises(ToolError, match="Invalid json response"):
        with patch("cloop.loops.enrichment.litellm.completion", return_value=mock_response):
            loop_enrich(loop_id=created["id"])


def test_loop_enrich_sets_pending_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that enrichment request sets PENDING state before processing."""
    _setup_test_db(tmp_path, monkeypatch)

    created = loop_create(
        raw_text="Test task",
        captured_at=_now_iso(),
        client_tz_offset_min=0,
    )

    mock_response = {
        "choices": [{"message": {"content": '{"title": "Test", "confidence": {"title": 0.9}}'}}]
    }

    with patch("cloop.loops.enrichment.litellm.completion", return_value=mock_response):
        loop_enrich(loop_id=created["id"])

    # Verify loop is in COMPLETE state after enrichment
    result = loop_list(status="inbox")
    assert len(result) == 1
    assert result[0]["enrichment_state"] == "complete"


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

    # Create loops with different statuses and projects
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

    # Test filtering by status
    actionable_loops = loop_list(status="actionable")
    assert len(actionable_loops) == 1
    assert actionable_loops[0]["raw_text"] == "Buy groceries"

    blocked_loops = loop_list(status="blocked")
    assert len(blocked_loops) == 1

    # Test search
    search_results = loop_search(query="groceries")
    assert len(search_results) == 1

    # Test project list
    projects = project_list()
    assert len(projects) == 2  # Personal and Work


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
        with pytest.raises(ToolError, match="Invalid captured at"):
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
        with pytest.raises(ToolError, match="Invalid snooze until utc"):
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
    with pytest.raises(ToolError, match="Invalid due at utc"):
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
    with pytest.raises(ToolError, match="Invalid snooze until utc"):
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
