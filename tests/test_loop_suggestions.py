"""Tests for enrichment suggestion and clarification review flows.

Purpose:
    Verify repo, shared service, and HTTP contracts for enrichment follow-up.

Responsibilities:
    - Test repo-layer suggestion and clarification persistence helpers
    - Test shared enrichment-review service operations
    - Test HTTP endpoints for suggestion/clarification review flows

Invariants:
    - All tests use isolated temporary databases
    - Suggestion review flows reuse the shared service contract
    - Clarification answers target existing clarification rows by ID
"""

import pytest

from cloop import db
from cloop.loops import enrichment_review, repo, service
from cloop.loops.enrichment import LoopSuggestion
from cloop.loops.errors import ClarificationNotFoundError, SuggestionNotFoundError, ValidationError
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
    assert read_back["resolution"] is None
    assert read_back["model"] == "test-model"


def test_list_pending_suggestions(fresh_db, test_loop):
    """Test listing pending suggestions."""
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

    success = repo.resolve_loop_suggestion(
        suggestion_id=suggestion_id,
        resolution="rejected",
        conn=fresh_db,
    )
    assert success is True

    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=fresh_db)
    assert suggestion is not None
    assert suggestion["resolution"] == "rejected"
    assert suggestion["resolved_at"] is not None


def test_list_loop_suggestions_with_filters(fresh_db, test_loop):
    """Test listing with loop_id and resolution filters."""
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

    repo.resolve_loop_suggestion(
        suggestion_id=suggestion_id2,
        resolution="applied",
        applied_fields=["title"],
        conn=fresh_db,
    )

    by_loop = repo.list_loop_suggestions(loop_id=test_loop["id"], conn=fresh_db)
    assert len(by_loop) == 2

    resolved = repo.list_loop_suggestions(resolution="applied", conn=fresh_db)
    assert len(resolved) == 1
    assert resolved[0]["id"] == suggestion_id2


def test_service_list_loop_suggestions_links_clarifications(fresh_db, test_loop):
    """Shared suggestion listing should parse payloads and link clarification rows."""
    suggestion_id = repo.insert_loop_suggestion(
        loop_id=test_loop["id"],
        suggestion_json={
            "title": "Test Suggestion",
            "confidence": {"title": 0.95},
            "needs_clarification": ["Who owns this?"],
        },
        model="test",
        conn=fresh_db,
    )
    clarification_id = repo.insert_loop_clarification(
        loop_id=test_loop["id"],
        question="Who owns this?",
        conn=fresh_db,
    )

    suggestions = enrichment_review.list_loop_suggestions(
        loop_id=test_loop["id"],
        pending_only=True,
        conn=fresh_db,
    )

    assert len(suggestions) == 1
    assert suggestions[0]["id"] == suggestion_id
    assert suggestions[0]["parsed"]["title"] == "Test Suggestion"
    assert suggestions[0]["clarifications"][0]["id"] == clarification_id


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

    result = enrichment_review.apply_suggestion(
        suggestion_id=suggestion_id,
        fields=["title"],
        conn=fresh_db,
        settings=get_settings(),
    )

    assert result["applied_fields"] == ["title"]
    assert result["resolution"] == "applied"

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
                "next_action": 0.5,
            },
        },
        model="test",
        conn=fresh_db,
    )

    result = enrichment_review.apply_suggestion(
        suggestion_id=suggestion_id,
        fields=None,
        conn=fresh_db,
        settings=settings,
    )

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

    result = enrichment_review.reject_suggestion(suggestion_id=suggestion_id, conn=fresh_db)
    assert result["resolution"] == "rejected"

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

    enrichment_review.reject_suggestion(suggestion_id=suggestion_id, conn=fresh_db)

    with pytest.raises(ValidationError, match="already resolved"):
        enrichment_review.apply_suggestion(
            suggestion_id=suggestion_id,
            conn=fresh_db,
            settings=get_settings(),
        )


def test_apply_suggestion_not_found(fresh_db):
    """Test applying a non-existent suggestion."""
    with pytest.raises(SuggestionNotFoundError):
        enrichment_review.apply_suggestion(
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
            "confidence": {"title": 0.9, "project": 0.9},
        },
        model="test",
        conn=fresh_db,
    )

    result = enrichment_review.apply_suggestion(
        suggestion_id=suggestion_id,
        conn=fresh_db,
        settings=get_settings(),
    )

    assert "project" in result["applied_fields"]

    updated = repo.read_loop(loop_id=test_loop["id"], conn=fresh_db)
    assert updated is not None
    assert updated.title == "With Project"

    project_id = repo.upsert_project(name="TestProject", conn=fresh_db)
    assert updated.project_id == project_id


class TestClarificationLifecycle:
    """Tests for clarification submission and enrichment integration."""

    def test_submit_clarification_answers_updates_existing_rows(self, fresh_db, test_loop):
        """Shared clarification submission should answer existing clarification rows."""
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=test_loop["id"],
            suggestion_json={
                "needs_clarification": ["What is the priority?"],
                "confidence": {},
            },
            model="test",
            conn=fresh_db,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=test_loop["id"],
            question="What is the priority?",
            conn=fresh_db,
        )

        result = enrichment_review.submit_clarification_answers(
            loop_id=test_loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=clarification_id,
                    answer="High priority",
                )
            ],
            conn=fresh_db,
        )

        assert result.answered_count == 1
        assert result.superseded_suggestion_ids == [suggestion_id]
        assert result.clarifications[0]["id"] == clarification_id
        assert result.clarifications[0]["answer"] == "High priority"

        unanswered = repo.list_unanswered_clarification_questions(
            loop_id=test_loop["id"],
            conn=fresh_db,
        )
        assert unanswered == set()

    def test_submit_clarification_answers_rejects_missing_row(self, fresh_db, test_loop):
        """Clarification submission should fail for missing clarification IDs."""
        with pytest.raises(ClarificationNotFoundError):
            enrichment_review.submit_clarification_answers(
                loop_id=test_loop["id"],
                answers=[
                    enrichment_review.ClarificationAnswerInput(
                        clarification_id=99999,
                        answer="High priority",
                    )
                ],
                conn=fresh_db,
            )

    def test_clarifications_included_in_enrichment_context(self, fresh_db, test_loop):
        """Answered clarifications are included in enrichment context."""
        from cloop.loops.enrichment import _gather_enrichment_context

        clarification_id = repo.insert_loop_clarification(
            loop_id=test_loop["id"],
            question="Due date?",
            conn=fresh_db,
        )
        enrichment_review.submit_clarification_answers(
            loop_id=test_loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=clarification_id,
                    answer="Tomorrow",
                )
            ],
            conn=fresh_db,
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

        repo.insert_loop_clarification(
            loop_id=test_loop["id"],
            question="Unanswered question?",
            conn=fresh_db,
        )

        context = _gather_enrichment_context(
            loop_id=test_loop["id"],
            loop_text=test_loop["raw_text"],
            conn=fresh_db,
            settings=get_settings(),
        )

        assert len(context.answered_clarifications) == 0

    def test_api_submit_clarification_endpoint(self, monkeypatch):
        """POST /{loop_id}/clarifications/answer answers existing clarification rows."""
        import tempfile

        from fastapi.testclient import TestClient

        from cloop.main import app

        with tempfile.TemporaryDirectory() as tmp_dir:
            monkeypatch.setenv("CLOOP_DATA_DIR", tmp_dir)
            get_settings.cache_clear()
            settings = get_settings()
            db.init_databases(settings)

            with db.core_connection(settings) as conn:
                with conn:
                    loop = service.capture_loop(
                        raw_text="Test loop for clarification API",
                        captured_at_iso="2026-02-18T12:00:00+00:00",
                        client_tz_offset_min=0,
                        status=service.LoopStatus.INBOX,
                        conn=conn,
                    )
                    suggestion_id = repo.insert_loop_suggestion(
                        loop_id=loop["id"],
                        suggestion_json={
                            "needs_clarification": ["Priority?", "Due?"],
                            "confidence": {},
                        },
                        model="test",
                        conn=conn,
                    )
                    first_clarification_id = repo.insert_loop_clarification(
                        loop_id=loop["id"],
                        question="Priority?",
                        conn=conn,
                    )
                    second_clarification_id = repo.insert_loop_clarification(
                        loop_id=loop["id"],
                        question="Due?",
                        conn=conn,
                    )

            client = TestClient(app)
            response = client.post(
                f"/loops/{loop['id']}/clarifications/answer",
                json={
                    "answers": [
                        {"clarification_id": first_clarification_id, "answer": "High"},
                        {"clarification_id": second_clarification_id, "answer": "Friday"},
                    ]
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["loop_id"] == loop["id"]
            assert data["answered_count"] == 2
            assert len(data["clarifications"]) == 2
            assert data["superseded_suggestion_ids"] == [suggestion_id]

    def test_api_get_clarifications_endpoint(self, monkeypatch):
        """GET /{loop_id}/clarifications returns clarification list."""
        import tempfile

        from fastapi.testclient import TestClient

        from cloop.main import app

        with tempfile.TemporaryDirectory() as tmp_dir:
            monkeypatch.setenv("CLOOP_DATA_DIR", tmp_dir)
            get_settings.cache_clear()
            settings = get_settings()
            db.init_databases(settings)

            with db.core_connection(settings) as conn:
                with conn:
                    loop = service.capture_loop(
                        raw_text="Test loop for get clarifications",
                        captured_at_iso="2026-02-18T12:00:00+00:00",
                        client_tz_offset_min=0,
                        status=service.LoopStatus.INBOX,
                        conn=conn,
                    )
                    clarification_id = repo.insert_loop_clarification(
                        loop_id=loop["id"],
                        question="Q1?",
                        conn=conn,
                    )

            client = TestClient(app)
            response = client.get(f"/loops/{loop['id']}/clarifications")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["clarifications"][0]["id"] == clarification_id
            assert data["clarifications"][0]["question"] == "Q1?"
