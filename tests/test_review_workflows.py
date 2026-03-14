"""Tests for shared saved review actions and review sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.loops import enrichment_review, repo, review_workflows, service
from cloop.loops.models import LoopStatus
from cloop.settings import Settings, get_settings

VECTORS = {
    "buy milk and eggs before the weekend": np.array([1.0, 0.0, 0.0], dtype=np.float32),
    "pick up groceries like milk and eggs": np.array([0.99, 0.01, 0.0], dtype=np.float32),
    "draft launch email for beta users": np.array([0.0, 1.0, 0.0], dtype=np.float32),
    "write beta launch email draft": np.array([0.0, 0.99, 0.01], dtype=np.float32),
}


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _mock_relationship_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        inputs = kwargs.get("input") or []
        data: list[dict[str, list[float]]] = []
        for text in inputs:
            lowered = str(text).lower()
            vector = np.array([0.1, 0.1, 0.1], dtype=np.float32)
            for key, mapped in VECTORS.items():
                if key in lowered:
                    vector = mapped.copy()
                    break
            vector /= np.linalg.norm(vector)
            data.append({"embedding": vector.tolist()})
        return {"data": data}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)


def _capture_loop(raw_text: str, *, status: LoopStatus, conn: Any) -> dict[str, Any]:
    return service.capture_loop(
        raw_text=raw_text,
        captured_at_iso="2026-03-14T12:00:00+00:00",
        client_tz_offset_min=0,
        status=status,
        conn=conn,
    )


def test_relationship_review_session_advances_after_resolving_current_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        first_loop = _capture_loop(
            "Buy milk and eggs before the weekend",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        second_loop = _capture_loop(
            "Pick up groceries like milk and eggs",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        third_loop = _capture_loop(
            "Draft launch email for beta users",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        fourth_loop = _capture_loop(
            "Write beta launch email draft",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        conn.commit()

        action = review_workflows.create_relationship_review_action(
            name="dismiss-current-match",
            action_type="dismiss",
            relationship_type="suggested",
            description="Dismiss the current suggested relationship",
            conn=conn,
        )
        snapshot = review_workflows.create_relationship_review_session(
            name="duplicate-pass",
            query="status:open",
            relationship_kind="duplicate",
            candidate_limit=3,
            item_limit=25,
            current_loop_id=first_loop["id"],
            conn=conn,
            settings=settings,
        )

        assert snapshot["session"]["current_loop_id"] == first_loop["id"]
        assert snapshot["current_item"]["loop"]["id"] == first_loop["id"]

        after = review_workflows.execute_relationship_review_session_action(
            session_id=snapshot["session"]["id"],
            loop_id=first_loop["id"],
            candidate_loop_id=second_loop["id"],
            candidate_relationship_type="duplicate",
            action_preset_id=action["id"],
            action_type=None,
            relationship_type=None,
            conn=conn,
            settings=settings,
        )

    assert after["result"]["link_state"] == "dismissed"
    remaining_loop_ids = {item["loop"]["id"] for item in after["snapshot"]["items"]}
    assert third_loop["id"] in remaining_loop_ids or fourth_loop["id"] in remaining_loop_ids
    assert after["snapshot"]["session"]["current_loop_id"] in remaining_loop_ids
    assert first_loop["id"] not in remaining_loop_ids
    assert second_loop["id"] not in remaining_loop_ids


def test_review_session_move_helpers_step_through_saved_cursors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        rel_first = _capture_loop(
            "Buy milk and eggs before the weekend",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        _capture_loop(
            "Pick up groceries like milk and eggs",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        _capture_loop(
            "Draft launch email for beta users",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        _capture_loop(
            "Write beta launch email draft",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )

        enrich_first = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        enrich_second = _capture_loop(
            "Clarify owner for launch", status=LoopStatus.INBOX, conn=conn
        )
        repo.insert_loop_suggestion(
            loop_id=enrich_first["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_first["id"],
            question="When should this happen?",
            conn=conn,
        )
        repo.insert_loop_suggestion(
            loop_id=enrich_second["id"],
            suggestion_json={"needs_clarification": ["Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_second["id"],
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

        relationship_session = review_workflows.create_relationship_review_session(
            name="move-rel",
            query="status:open",
            relationship_kind="duplicate",
            candidate_limit=3,
            item_limit=25,
            current_loop_id=rel_first["id"],
            conn=conn,
            settings=settings,
        )
        enrichment_session = review_workflows.create_enrichment_review_session(
            name="move-enrich",
            query="status:open",
            pending_kind="clarifications",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=enrich_first["id"],
            conn=conn,
        )

        relationship_direction = (
            "next" if relationship_session["current_index"] == 0 else "previous"
        )
        relationship_step = 1 if relationship_direction == "next" else -1
        relationship_target = relationship_session["items"][
            relationship_session["current_index"] + relationship_step
        ]["loop"]["id"]
        moved_relationship = review_workflows.move_relationship_review_session(
            session_id=relationship_session["session"]["id"],
            direction=relationship_direction,
            conn=conn,
            settings=settings,
        )
        enrichment_direction = "next" if enrichment_session["current_index"] == 0 else "previous"
        enrichment_step = 1 if enrichment_direction == "next" else -1
        enrichment_target = enrichment_session["items"][
            enrichment_session["current_index"] + enrichment_step
        ]["loop"]["id"]
        moved_enrichment = review_workflows.move_enrichment_review_session(
            session_id=enrichment_session["session"]["id"],
            direction=enrichment_direction,
            conn=conn,
        )

    assert moved_relationship["session"]["current_loop_id"] == relationship_target
    assert moved_relationship["current_item"]["loop"]["id"] == relationship_target
    assert moved_enrichment["session"]["current_loop_id"] == enrichment_target
    assert moved_enrichment["current_item"]["loop"]["id"] == enrichment_target


def test_enrichment_review_action_preset_applies_suggestion_and_refreshes_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop_record = _capture_loop(
            "Plan Q2 launch retrospective",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop_record["id"],
            suggestion_json={
                "title": "Plan launch retrospective",
                "summary": "Define owner, agenda, and participants.",
                "confidence": {"title": 0.99, "summary": 0.94},
            },
            model="test-model",
            conn=conn,
        )
        conn.commit()

        action = review_workflows.create_enrichment_review_action(
            name="apply-title-only",
            action_type="apply",
            fields=["title"],
            description="Apply just the title field",
            conn=conn,
        )
        snapshot = review_workflows.create_enrichment_review_session(
            name="pending-suggestions",
            query="status:open",
            pending_kind="suggestions",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=loop_record["id"],
            conn=conn,
        )

        assert snapshot["session"]["current_loop_id"] == loop_record["id"]
        assert snapshot["current_item"]["pending_suggestions"][0]["id"] == suggestion_id

        after = review_workflows.execute_enrichment_review_session_action(
            session_id=snapshot["session"]["id"],
            suggestion_id=suggestion_id,
            action_preset_id=action["id"],
            action_type=None,
            fields=None,
            conn=conn,
            settings=settings,
        )

        updated_loop = repo.read_loop(loop_id=loop_record["id"], conn=conn)

    assert after["result"]["suggestion_id"] == suggestion_id
    assert after["result"]["applied_fields"] == ["title"]
    assert updated_loop is not None
    assert updated_loop.title == "Plan launch retrospective"
    assert after["snapshot"]["loop_count"] == 0
    assert after["snapshot"]["session"]["current_loop_id"] is None


def test_enrichment_review_session_answers_clarifications_reruns_and_reenters_same_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "cloop.loops.enrichment.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(
                {
                    "title": "Schedule launch date",
                    "next_action": "Confirm Friday launch plan",
                    "confidence": {"title": 0.99, "next_action": 0.99},
                }
            ),
            {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}},
        ),
    )

    with db.core_connection(settings) as conn:
        first_loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        second_loop = _capture_loop("Clarify owner for launch", status=LoopStatus.INBOX, conn=conn)

        first_suggestion_id = repo.insert_loop_suggestion(
            loop_id=first_loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        first_clarification_id = repo.insert_loop_clarification(
            loop_id=first_loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        second_suggestion_id = repo.insert_loop_suggestion(
            loop_id=second_loop["id"],
            suggestion_json={"needs_clarification": ["Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        second_clarification_id = repo.insert_loop_clarification(
            loop_id=second_loop["id"],
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

        snapshot = review_workflows.create_enrichment_review_session(
            name="clarification-pass",
            query="status:open",
            pending_kind="all",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=first_loop["id"],
            conn=conn,
        )

        assert snapshot["session"]["current_loop_id"] == first_loop["id"]
        assert snapshot["current_item"]["pending_clarifications"][0]["id"] == first_clarification_id

        after = review_workflows.answer_enrichment_review_session_clarifications(
            session_id=snapshot["session"]["id"],
            loop_id=first_loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=first_clarification_id,
                    answer="Friday",
                )
            ],
            conn=conn,
            settings=settings,
        )

        answered_row = repo.read_loop_clarification(
            clarification_id=first_clarification_id,
            conn=conn,
        )
        remaining_pending = enrichment_review.list_loop_suggestions(
            loop_id=first_loop["id"],
            pending_only=True,
            conn=conn,
        )

    assert after["result"]["loop_id"] == first_loop["id"]
    assert after["result"]["clarification_result"]["answered_count"] == 1
    assert after["result"]["clarification_result"]["superseded_suggestion_ids"] == [
        first_suggestion_id
    ]
    assert after["result"]["enrichment_result"]["loop"]["id"] == first_loop["id"]
    assert after["result"]["enrichment_result"]["applied_fields"] == []
    assert after["result"]["enrichment_result"]["needs_clarification"] == []
    assert answered_row is not None
    assert answered_row["answer"] == "Friday"
    assert {suggestion["id"] for suggestion in remaining_pending} == {
        after["result"]["enrichment_result"]["suggestion_id"]
    }
    assert remaining_pending[0]["parsed"]["title"] == "Schedule launch date"
    remaining_loop_ids = {item["loop"]["id"] for item in after["snapshot"]["items"]}
    assert first_loop["id"] in remaining_loop_ids
    assert second_loop["id"] in remaining_loop_ids
    assert after["snapshot"]["session"]["current_loop_id"] == first_loop["id"]
    assert second_clarification_id in {
        clarification["id"]
        for item in after["snapshot"]["items"]
        for clarification in item.get("pending_clarifications", [])
    }
    assert (
        second_suggestion_id
        not in after["result"]["clarification_result"]["superseded_suggestion_ids"]
    )
