"""MCP tests for saved review actions and review sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.loops import repo
from cloop.loops.models import LoopStatus
from cloop.mcp_tools.review_workflows import (
    review_enrichment_action_create,
    review_enrichment_session_answer_clarifications,
    review_enrichment_session_apply_action,
    review_enrichment_session_create,
    review_enrichment_session_move,
    review_relationship_action_create,
    review_relationship_session_apply_action,
    review_relationship_session_create,
    review_relationship_session_move,
)
from cloop.settings import Settings, get_settings

VECTORS = {
    "buy milk and eggs before the weekend": np.array([1.0, 0.0, 0.0], dtype=np.float32),
    "pick up groceries like milk and eggs": np.array([0.99, 0.01, 0.0], dtype=np.float32),
    "draft launch email for beta users": np.array([0.0, 1.0, 0.0], dtype=np.float32),
    "write beta launch email draft": np.array([0.0, 0.99, 0.01], dtype=np.float32),
}


def _setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_TTL_SECONDS", "86400")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH", "255")
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


def _create_loop(*, raw_text: str, conn: Any) -> int:
    row = repo.create_loop(
        raw_text=raw_text,
        captured_at_utc="2026-03-14T12:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    return int(row.id)


def test_relationship_review_workflow_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_test_db(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        first_id = _create_loop(raw_text="Buy milk and eggs before the weekend", conn=conn)
        second_id = _create_loop(raw_text="Pick up groceries like milk and eggs", conn=conn)
        third_id = _create_loop(raw_text="Draft launch email for beta users", conn=conn)
        fourth_id = _create_loop(raw_text="Write beta launch email draft", conn=conn)
        conn.commit()

    action = review_relationship_action_create(
        name="dismiss-suggested",
        action_type="dismiss",
        relationship_type="suggested",
    )
    session = review_relationship_session_create(
        name="duplicate-pass",
        query="status:open",
        relationship_kind="duplicate",
        current_loop_id=first_id,
    )
    assert session["current_item"]["loop"]["id"] == first_id

    result = review_relationship_session_apply_action(
        session_id=session["session"]["id"],
        loop_id=first_id,
        candidate_loop_id=second_id,
        candidate_relationship_type="duplicate",
        action_preset_id=action["id"],
    )

    assert result["result"]["link_state"] == "dismissed"
    remaining_loop_ids = {item["loop"]["id"] for item in result["snapshot"]["items"]}
    assert first_id not in remaining_loop_ids
    assert second_id not in remaining_loop_ids
    assert third_id in remaining_loop_ids or fourth_id in remaining_loop_ids


def test_review_session_move_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_test_db(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        rel_first = _create_loop(raw_text="Buy milk and eggs before the weekend", conn=conn)
        _create_loop(raw_text="Pick up groceries like milk and eggs", conn=conn)
        _create_loop(raw_text="Draft launch email for beta users", conn=conn)
        _create_loop(raw_text="Write beta launch email draft", conn=conn)
        enrich_first = _create_loop(raw_text="Clarify launch date", conn=conn)
        enrich_second = _create_loop(raw_text="Clarify owner for launch", conn=conn)
        repo.insert_loop_suggestion(
            loop_id=enrich_first,
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_first,
            question="When should this happen?",
            conn=conn,
        )
        repo.insert_loop_suggestion(
            loop_id=enrich_second,
            suggestion_json={"needs_clarification": ["Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_second,
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

    relationship_session = review_relationship_session_create(
        name="move-rel",
        query="status:open",
        relationship_kind="duplicate",
        current_loop_id=rel_first,
    )
    relationship_direction = "next" if relationship_session["current_index"] == 0 else "previous"
    relationship_step = 1 if relationship_direction == "next" else -1
    relationship_target = relationship_session["items"][
        relationship_session["current_index"] + relationship_step
    ]["loop"]["id"]
    moved_relationship = review_relationship_session_move(
        session_id=relationship_session["session"]["id"],
        direction=relationship_direction,
    )
    assert moved_relationship["current_item"]["loop"]["id"] == relationship_target

    enrichment_session = review_enrichment_session_create(
        name="move-enrich",
        query="status:open",
        pending_kind="clarifications",
        current_loop_id=enrich_first,
    )
    enrichment_direction = "next" if enrichment_session["current_index"] == 0 else "previous"
    enrichment_step = 1 if enrichment_direction == "next" else -1
    enrichment_target = enrichment_session["items"][
        enrichment_session["current_index"] + enrichment_step
    ]["loop"]["id"]
    moved_enrichment = review_enrichment_session_move(
        session_id=enrichment_session["session"]["id"],
        direction=enrichment_direction,
    )
    assert moved_enrichment["current_item"]["loop"]["id"] == enrichment_target


def test_enrichment_review_workflow_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_test_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "cloop.loops.enrichment.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(
                {
                    "title": "Clarified launch checklist owner",
                    "summary": "Operations owns the checklist.",
                    "confidence": {"title": 0.99, "summary": 0.99},
                }
            ),
            {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}},
        ),
    )

    with db.core_connection(settings) as conn:
        suggestion_loop_id = _create_loop(raw_text="Plan launch retrospective", conn=conn)
        clarification_loop_id = _create_loop(raw_text="Clarify launch checklist owner", conn=conn)
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=suggestion_loop_id,
            suggestion_json={
                "title": "Plan launch retrospective meeting",
                "summary": "Collect owners and follow-ups.",
                "confidence": {"title": 0.99, "summary": 0.94},
            },
            model="test-model",
            conn=conn,
        )
        superseded_suggestion_id = repo.insert_loop_suggestion(
            loop_id=clarification_loop_id,
            suggestion_json={"needs_clarification": ["Who owns the checklist?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=clarification_loop_id,
            question="Who owns the checklist?",
            conn=conn,
        )
        conn.commit()

    action = review_enrichment_action_create(
        name="apply-title",
        action_type="apply",
        fields=["title"],
    )
    session = review_enrichment_session_create(
        name="follow-up-pass",
        query="status:open",
        pending_kind="all",
        current_loop_id=suggestion_loop_id,
    )
    assert session["current_item"]["loop"]["id"] == suggestion_loop_id

    apply_result = review_enrichment_session_apply_action(
        session_id=session["session"]["id"],
        suggestion_id=suggestion_id,
        action_preset_id=action["id"],
    )
    assert apply_result["result"]["suggestion_id"] == suggestion_id
    assert apply_result["snapshot"]["session"]["current_loop_id"] == clarification_loop_id

    answer_result = review_enrichment_session_answer_clarifications(
        session_id=session["session"]["id"],
        loop_id=clarification_loop_id,
        answers=[{"clarification_id": clarification_id, "answer": "Operations"}],
    )
    assert answer_result["result"]["loop_id"] == clarification_loop_id
    assert answer_result["result"]["clarification_result"]["superseded_suggestion_ids"] == [
        superseded_suggestion_id
    ]
    assert answer_result["result"]["enrichment_result"]["applied_fields"] == []
    assert answer_result["result"]["enrichment_result"]["suggestion_id"] > superseded_suggestion_id
    assert answer_result["snapshot"]["loop_count"] == 1
    assert answer_result["snapshot"]["session"]["current_loop_id"] == clarification_loop_id
