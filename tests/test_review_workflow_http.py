"""HTTP tests for saved review actions and review sessions."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.loops import repo
from cloop.settings import get_settings

VECTORS = {
    "buy milk and eggs before the weekend": np.array([1.0, 0.0, 0.0], dtype=np.float32),
    "pick up groceries like milk and eggs": np.array([0.99, 0.01, 0.0], dtype=np.float32),
    "draft launch email for beta users": np.array([0.0, 1.0, 0.0], dtype=np.float32),
    "write beta launch email draft": np.array([0.0, 0.99, 0.01], dtype=np.float32),
}


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


def _capture(client: Any, raw_text: str, *, actionable: bool = False) -> int:
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": raw_text,
            "captured_at": "2026-03-14T12:00:00+00:00",
            "client_tz_offset_min": 0,
            "actionable": actionable,
        },
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def test_relationship_review_workflow_endpoints(
    make_test_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_relationship_embeddings(monkeypatch)
    client = make_test_client()

    first_id = _capture(client, "Buy milk and eggs before the weekend")
    second_id = _capture(client, "Pick up groceries like milk and eggs", actionable=True)
    third_id = _capture(client, "Draft launch email for beta users")
    fourth_id = _capture(client, "Write beta launch email draft", actionable=True)

    action_response = client.post(
        "/loops/review/relationship/actions",
        json={
            "name": "dismiss-suggested",
            "action_type": "dismiss",
            "relationship_type": "suggested",
            "description": "Dismiss the queued suggestion",
        },
    )
    assert action_response.status_code == 201
    action_payload = action_response.json()

    list_actions = client.get("/loops/review/relationship/actions")
    assert list_actions.status_code == 200
    assert {item["id"] for item in list_actions.json()} == {action_payload["id"]}

    session_response = client.post(
        "/loops/review/relationship/sessions",
        json={
            "name": "duplicate-pass",
            "query": "status:open",
            "relationship_kind": "duplicate",
            "candidate_limit": 3,
            "item_limit": 25,
            "current_loop_id": first_id,
        },
    )
    assert session_response.status_code == 201
    session_payload = session_response.json()
    session_id = session_payload["session"]["id"]
    assert session_payload["current_item"]["loop"]["id"] == first_id

    action_run = client.post(
        f"/loops/review/relationship/sessions/{session_id}/action",
        json={
            "loop_id": first_id,
            "candidate_loop_id": second_id,
            "candidate_relationship_type": "duplicate",
            "action_preset_id": action_payload["id"],
        },
    )
    assert action_run.status_code == 200
    action_result = action_run.json()
    assert action_result["result"]["link_state"] == "dismissed"
    remaining_loop_ids = {item["loop"]["id"] for item in action_result["snapshot"]["items"]}
    assert first_id not in remaining_loop_ids
    assert second_id not in remaining_loop_ids
    assert third_id in remaining_loop_ids or fourth_id in remaining_loop_ids
    assert action_result["snapshot"]["session"]["current_loop_id"] in remaining_loop_ids

    delete_session = client.delete(f"/loops/review/relationship/sessions/{session_id}")
    assert delete_session.status_code == 200
    assert delete_session.json() == {"deleted": True, "session_id": session_id}

    delete_action = client.delete(f"/loops/review/relationship/actions/{action_payload['id']}")
    assert delete_action.status_code == 200
    assert delete_action.json() == {"deleted": True, "action_preset_id": action_payload["id"]}


def test_review_session_move_endpoints(
    make_test_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_relationship_embeddings(monkeypatch)
    client = make_test_client()

    rel_first = _capture(client, "Buy milk and eggs before the weekend")
    _capture(client, "Pick up groceries like milk and eggs", actionable=True)
    _capture(client, "Draft launch email for beta users")
    _capture(client, "Write beta launch email draft", actionable=True)
    enrich_first = _capture(client, "Clarify launch date")
    enrich_second = _capture(client, "Clarify owner for launch")

    with db.core_connection(get_settings()) as conn:
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

    relationship_session = client.post(
        "/loops/review/relationship/sessions",
        json={
            "name": "move-rel",
            "query": "status:open",
            "relationship_kind": "duplicate",
            "candidate_limit": 3,
            "item_limit": 25,
            "current_loop_id": rel_first,
        },
    )
    assert relationship_session.status_code == 201
    relationship_session_payload = relationship_session.json()
    relationship_session_id = relationship_session_payload["session"]["id"]
    relationship_direction = (
        "next" if relationship_session_payload["current_index"] == 0 else "previous"
    )
    relationship_step = 1 if relationship_direction == "next" else -1
    relationship_target = relationship_session_payload["items"][
        relationship_session_payload["current_index"] + relationship_step
    ]["loop"]["id"]

    relationship_move = client.post(
        f"/loops/review/relationship/sessions/{relationship_session_id}/move",
        json={"direction": relationship_direction},
    )
    assert relationship_move.status_code == 200
    assert relationship_move.json()["current_item"]["loop"]["id"] == relationship_target

    enrichment_session = client.post(
        "/loops/review/enrichment/sessions",
        json={
            "name": "move-enrich",
            "query": "status:open",
            "pending_kind": "clarifications",
            "suggestion_limit": 3,
            "clarification_limit": 3,
            "item_limit": 25,
            "current_loop_id": enrich_first,
        },
    )
    assert enrichment_session.status_code == 201
    enrichment_session_payload = enrichment_session.json()
    enrichment_session_id = enrichment_session_payload["session"]["id"]
    enrichment_direction = (
        "next" if enrichment_session_payload["current_index"] == 0 else "previous"
    )
    enrichment_step = 1 if enrichment_direction == "next" else -1
    enrichment_target = enrichment_session_payload["items"][
        enrichment_session_payload["current_index"] + enrichment_step
    ]["loop"]["id"]

    enrichment_move = client.post(
        f"/loops/review/enrichment/sessions/{enrichment_session_id}/move",
        json={"direction": enrichment_direction},
    )
    assert enrichment_move.status_code == 200
    assert enrichment_move.json()["current_item"]["loop"]["id"] == enrichment_target


def test_enrichment_review_workflow_endpoints(
    make_test_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    client = make_test_client()

    suggestion_loop_id = _capture(client, "Plan launch retrospective")
    clarification_loop_id = _capture(client, "Clarify launch checklist owner")

    with db.core_connection(get_settings()) as conn:
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=suggestion_loop_id,
            suggestion_json={
                "title": "Plan launch retrospective meeting",
                "summary": "Collect decisions, owners, and follow-ups.",
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

    action_response = client.post(
        "/loops/review/enrichment/actions",
        json={
            "name": "apply-title",
            "action_type": "apply",
            "fields": ["title"],
            "description": "Apply only the title field",
        },
    )
    assert action_response.status_code == 201
    action_payload = action_response.json()

    session_response = client.post(
        "/loops/review/enrichment/sessions",
        json={
            "name": "follow-up-pass",
            "query": "status:open",
            "pending_kind": "all",
            "suggestion_limit": 3,
            "clarification_limit": 3,
            "item_limit": 25,
            "current_loop_id": suggestion_loop_id,
        },
    )
    assert session_response.status_code == 201
    session_payload = session_response.json()
    session_id = session_payload["session"]["id"]
    assert session_payload["current_item"]["loop"]["id"] == suggestion_loop_id

    apply_response = client.post(
        f"/loops/review/enrichment/sessions/{session_id}/action",
        json={
            "suggestion_id": suggestion_id,
            "action_preset_id": action_payload["id"],
        },
    )
    assert apply_response.status_code == 200
    apply_payload = apply_response.json()
    assert apply_payload["result"]["suggestion_id"] == suggestion_id
    assert apply_payload["result"]["applied_fields"] == ["title"]
    assert apply_payload["snapshot"]["session"]["current_loop_id"] == clarification_loop_id

    answer_response = client.post(
        f"/loops/review/enrichment/sessions/{session_id}/clarifications/answer",
        json={
            "loop_id": clarification_loop_id,
            "answers": [
                {
                    "clarification_id": clarification_id,
                    "answer": "Operations",
                }
            ],
        },
    )
    assert answer_response.status_code == 200
    answer_payload = answer_response.json()
    assert answer_payload["result"]["loop_id"] == clarification_loop_id
    assert answer_payload["result"]["clarification_result"]["answered_count"] == 1
    assert answer_payload["result"]["clarification_result"]["superseded_suggestion_ids"] == [
        superseded_suggestion_id
    ]
    assert answer_payload["result"]["enrichment_result"]["loop"]["id"] == clarification_loop_id
    assert answer_payload["result"]["enrichment_result"]["applied_fields"] == []
    assert answer_payload["result"]["enrichment_result"]["suggestion_id"] > superseded_suggestion_id
    assert answer_payload["snapshot"]["loop_count"] == 1
    assert answer_payload["snapshot"]["session"]["current_loop_id"] == clarification_loop_id
