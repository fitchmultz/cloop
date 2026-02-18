"""Tests for loop suggestion lifecycle management.

Purpose:
    Test suite for suggestion operations: create, read, list, apply, reject.

Responsibilities:
    - Test repo layer suggestion functions
    - Test service layer apply/reject functionality
    - Test resolution state transitions

Invariants:
    - All tests use isolated temporary databases
    - Tests verify both success and error cases
"""

import pytest

from cloop import db
from cloop.loops import repo, service
from cloop.loops.enrichment import LoopSuggestion
from cloop.loops.errors import SuggestionNotFoundError, ValidationError
from cloop.settings import get_settings


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Create a fresh database with schema for testing."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.init_databases(get_settings())
    with db.core_connection() as conn:
        yield conn


@pytest.fixture
def test_loop(fresh_db):
    """Create a test loop for suggestion tests."""
    return service.capture_loop(
        raw_text="Test loop for suggestions",
        captured_at_iso="2026-02-18T12:00:00+00:00",
        client_tz_offset_min=0,
        status=service.LoopStatus.INBOX,
        conn=fresh_db,
    )


def test_insert_and_read_suggestion(fresh_db, test_loop):
    """Test inserting and reading a suggestion."""
    suggestion = LoopSuggestion(
        title="Suggested title",
        tags=["tag1", "tag2"],
        confidence={"title": 0.9, "tags": 0.8},
        needs_clarification=["What is the priority?"],
    )

    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json=suggestion.model_dump(mode="json"),
        model="test-model",
        conn=fresh_db,
    )

    read_back = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=fresh_db)
    assert read_back is not None
    assert read_back["loop_id"] == test_loop["id"]
    assert read_back["resolution"] is None  # pending
    assert read_back["model"] == "test-model"


def test_list_pending_suggestions(fresh_db, test_loop):
    """Test listing pending suggestions."""
    # Insert suggestion
    repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Sug1"},
        model="test",
        conn=fresh_db,
    )

    pending = repo.list_pending_suggestions(conn=fresh_db)
    assert len(pending) == 1
    assert pending[0]["resolution"] is None


def test_resolve_suggestion(fresh_db, test_loop):
    """Test resolving a suggestion."""
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Test"},
        model="test",
        conn=fresh_db,
    )

    # Reject it
    success = repo.resolve_loop_suggestion(
        suggestion_id=suggestion_id,
        resolution="rejected",
        conn=fresh_db,
    )
    assert success is True

    # Verify it's resolved
    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=fresh_db)
    assert suggestion is not None
    assert suggestion["resolution"] == "rejected"
    assert suggestion["resolved_at"] is not None


def test_list_loop_suggestions_with_filters(fresh_db, test_loop):
    """Test listing with loop_id and resolution filters."""
    # Insert two suggestions
    repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Sug1"},
        model="test",
        conn=fresh_db,
    )
    suggestion_id2 = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Sug2"},
        model="test",
        conn=fresh_db,
    )

    # Resolve one
    repo.resolve_loop_suggestion(
        suggestion_id=suggestion_id2,
        resolution="applied",
        applied_fields=["title"],
        conn=fresh_db,
    )

    # Test filter by loop_id
    by_loop = repo.list_loop_suggestions(loop_id=test_loop["id"], conn=fresh_db)
    assert len(by_loop) == 2

    # Test filter by resolution
    resolved = repo.list_loop_suggestions(resolution="applied", conn=fresh_db)
    assert len(resolved) == 1
    assert resolved[0]["id"] == suggestion_id2


def test_service_list_loop_suggestions(fresh_db, test_loop):
    """Test service layer list function with parsing."""
    repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Test Suggestion", "confidence": {"title": 0.95}},
        model="test",
        conn=fresh_db,
    )

    suggestions = service.list_loop_suggestions(
        loop_id=test_loop["id"],
        pending_only=True,
        conn=fresh_db,
    )

    assert len(suggestions) == 1
    assert "parsed" in suggestions[0]
    assert suggestions[0]["parsed"]["title"] == "Test Suggestion"


def test_apply_suggestion_partial(fresh_db, test_loop):
    """Test applying only some fields from a suggestion."""
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={
            "title": "New Title",
            "summary": "New Summary",
            "tags": ["new-tag"],
            "confidence": {"title": 0.95, "summary": 0.9, "tags": 0.8},
        },
        model="test",
        conn=fresh_db,
    )

    result = service.apply_suggestion(
        suggestion_id=suggestion_id,
        fields=["title"],  # Only apply title
        conn=fresh_db,
        settings=get_settings(),
    )

    assert result["applied_fields"] == ["title"]
    # When user specifies fields, "applied" means all requested fields were applied
    assert result["resolution"] == "applied"

    # Verify loop was updated
    updated = repo.read_loop(loop_id=test_loop["id"], conn=fresh_db)
    assert updated is not None
    assert updated.title == "New Title"


def test_apply_suggestion_all_fields(fresh_db, test_loop):
    """Test applying all suggestion fields above threshold."""
    settings = get_settings()
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={
            "title": "Complete Title",
            "summary": "Complete Summary",
            "next_action": "Do something",
            "confidence": {
                "title": 0.95,
                "summary": settings.autopilot_autoapply_min_confidence,
                "next_action": 0.5,  # Below threshold
            },
        },
        model="test",
        conn=fresh_db,
    )

    result = service.apply_suggestion(
        suggestion_id=suggestion_id,
        fields=None,  # Apply all above threshold
        conn=fresh_db,
        settings=settings,
    )

    # Should apply title and summary but not next_action
    assert "title" in result["applied_fields"]
    assert "summary" in result["applied_fields"]
    assert "next_action" not in result["applied_fields"]


def test_reject_suggestion(fresh_db, test_loop):
    """Test rejecting a suggestion."""
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Rejected Title"},
        model="test",
        conn=fresh_db,
    )

    result = service.reject_suggestion(suggestion_id=suggestion_id, conn=fresh_db)
    assert result["resolution"] == "rejected"

    # Verify loop was NOT updated
    unchanged = repo.read_loop(loop_id=test_loop["id"], conn=fresh_db)
    assert unchanged is not None
    assert unchanged.title is None


def test_cannot_resolve_twice(fresh_db, test_loop):
    """Test that a suggestion cannot be resolved twice."""
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={"title": "Test"},
        model="test",
        conn=fresh_db,
    )

    # First rejection should work
    service.reject_suggestion(suggestion_id=suggestion_id, conn=fresh_db)

    # Second apply should fail
    with pytest.raises(ValidationError, match="already resolved"):
        service.apply_suggestion(
            suggestion_id=suggestion_id,
            conn=fresh_db,
            settings=get_settings(),
        )


def test_apply_suggestion_not_found(fresh_db):
    """Test applying a non-existent suggestion."""
    with pytest.raises(SuggestionNotFoundError):
        service.apply_suggestion(
            suggestion_id=99999,
            conn=fresh_db,
            settings=get_settings(),
        )


def test_suggestion_with_project(fresh_db, test_loop):
    """Test applying a suggestion that includes a project."""
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={
            "title": "With Project",
            "project": "TestProject",
            "confidence": {"title": 0.9, "project": 0.9},  # Both above default threshold
        },
        model="test",
        conn=fresh_db,
    )

    result = service.apply_suggestion(
        suggestion_id=suggestion_id,
        conn=fresh_db,
        settings=get_settings(),
    )

    assert "project" in result["applied_fields"]

    # Verify loop was updated with project
    updated = repo.read_loop(loop_id=test_loop["id"], conn=fresh_db)
    assert updated is not None
    assert updated.title == "With Project"

    # Verify project exists
    project_id = repo.upsert_project(name="TestProject", conn=fresh_db)
    assert updated.project_id == project_id
