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
from cloop.loops import duplicates as loop_duplicates
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

    suggestions = loop_duplicates.list_loop_suggestions(
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

    result = loop_duplicates.apply_suggestion(
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

    result = loop_duplicates.apply_suggestion(
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

    result = loop_duplicates.reject_suggestion(suggestion_id=suggestion_id, conn=fresh_db)
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
    loop_duplicates.reject_suggestion(suggestion_id=suggestion_id, conn=fresh_db)

    # Second apply should fail
    with pytest.raises(ValidationError, match="already resolved"):
        loop_duplicates.apply_suggestion(
            suggestion_id=suggestion_id,
            conn=fresh_db,
            settings=get_settings(),
        )


def test_apply_suggestion_not_found(fresh_db):
    """Test applying a non-existent suggestion."""
    with pytest.raises(SuggestionNotFoundError):
        loop_duplicates.apply_suggestion(
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

    result = loop_duplicates.apply_suggestion(
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


class TestClarificationLifecycle:
    """Tests for clarification submission and enrichment integration."""

    def test_submit_clarification_creates_record(self, fresh_db, test_loop):
        """Submitting clarification creates a record with answer."""
        # Simulate what the endpoint does
        with fresh_db:
            fresh_db.execute(
                """
                INSERT INTO loop_clarifications (loop_id, question, answer, answered_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (test_loop["id"], "What is the priority?", "High priority"),
            )

        clars = repo.list_answered_clarifications(loop_id=test_loop["id"], conn=fresh_db)
        assert len(clars) == 1
        assert clars[0]["question"] == "What is the priority?"
        assert clars[0]["answer"] == "High priority"

    def test_clarifications_included_in_enrichment_context(self, fresh_db, test_loop):
        """Answered clarifications are included in enrichment context."""
        from cloop.loops.enrichment import _gather_enrichment_context

        # Add a clarification with answer
        with fresh_db:
            fresh_db.execute(
                """
                INSERT INTO loop_clarifications (loop_id, question, answer, answered_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (test_loop["id"], "Due date?", "Tomorrow"),
            )

        context = _gather_enrichment_context(
            loop_id=test_loop["id"],
            loop_text=test_loop["raw_text"],
            conn=fresh_db,
            settings=get_settings(),
        )

        assert len(context.answered_clarifications) == 1
        assert context.answered_clarifications[0]["question"] == "Due date?"
        assert context.answered_clarifications[0]["answer"] == "Tomorrow"

    def test_unanswered_clarifications_excluded_from_context(self, fresh_db, test_loop):
        """Only answered clarifications are included in enrichment context."""
        from cloop.loops.enrichment import _gather_enrichment_context

        # Add an unanswered clarification
        with fresh_db:
            fresh_db.execute(
                """
                INSERT INTO loop_clarifications (loop_id, question)
                VALUES (?, ?)
                """,
                (test_loop["id"], "Unanswered question?"),
            )

        context = _gather_enrichment_context(
            loop_id=test_loop["id"],
            loop_text=test_loop["raw_text"],
            conn=fresh_db,
            settings=get_settings(),
        )

        assert len(context.answered_clarifications) == 0

    def test_api_submit_clarification_endpoint(self, fresh_db, test_loop, monkeypatch):
        """POST /{loop_id}/clarify creates clarification records."""

        # Configure test database
        import tempfile

        from fastapi.testclient import TestClient

        from cloop import db
        from cloop.main import app
        from cloop.settings import get_settings

        with tempfile.TemporaryDirectory() as tmp_dir:
            monkeypatch.setenv("CLOOP_DATA_DIR", tmp_dir)
            get_settings.cache_clear()
            settings = get_settings()
            db.init_databases(settings)

            # Create a test loop in the temp database
            with db.core_connection(settings) as conn:
                loop = service.capture_loop(
                    raw_text="Test loop for clarification API",
                    captured_at_iso="2026-02-18T12:00:00+00:00",
                    client_tz_offset_min=0,
                    status=service.LoopStatus.INBOX,
                    conn=conn,
                )

            client = TestClient(app)

            response = client.post(
                f"/loops/{loop['id']}/clarify",
                json={
                    "answers": [
                        {"question": "Priority?", "answer": "High"},
                        {"question": "Due?", "answer": "Friday"},
                    ]
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["loop_id"] == loop["id"]
            assert data["answered_count"] == 2
            assert len(data["clarifications"]) == 2

    def test_api_get_clarifications_endpoint(self, fresh_db, test_loop, monkeypatch):
        """GET /{loop_id}/clarifications returns clarification list."""

        # Configure test database
        import tempfile

        from fastapi.testclient import TestClient

        from cloop import db
        from cloop.main import app
        from cloop.settings import get_settings

        with tempfile.TemporaryDirectory() as tmp_dir:
            monkeypatch.setenv("CLOOP_DATA_DIR", tmp_dir)
            get_settings.cache_clear()
            settings = get_settings()
            db.init_databases(settings)

            # Create a test loop in the temp database
            with db.core_connection(settings) as conn:
                loop = service.capture_loop(
                    raw_text="Test loop for get clarifications",
                    captured_at_iso="2026-02-18T12:00:00+00:00",
                    client_tz_offset_min=0,
                    status=service.LoopStatus.INBOX,
                    conn=conn,
                )

            client = TestClient(app)

            # Submit clarifications first
            client.post(
                f"/loops/{loop['id']}/clarify",
                json={"answers": [{"question": "Q1?", "answer": "A1"}]},
            )

            # Now fetch them
            response = client.get(f"/loops/{loop['id']}/clarifications")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] >= 1
