"""HTTP tests for saved planning sessions."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cloop import db
from cloop.loops import repo
from cloop.settings import get_settings


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


def _planner_payload(first_loop_id: int, second_loop_id: int, *, title: str) -> dict[str, Any]:
    return {
        "title": title,
        "summary": "Clean up launch preparation in explicit deterministic stages.",
        "assumptions": ["Human review remains explicit for any follow-up session work."],
        "checkpoints": [
            {
                "title": "Stabilize the active loops",
                "summary": "Clarify next actions and block the waiting item.",
                "success_criteria": "Launch prep loops have clear status and next action.",
                "operations": [
                    {
                        "kind": "update_loop",
                        "summary": "Clarify the first loop's next action.",
                        "loop_id": first_loop_id,
                        "fields": {"next_action": "Draft the launch readiness checklist"},
                    },
                    {
                        "kind": "transition_loop",
                        "summary": "Mark the second loop as blocked pending answers.",
                        "loop_id": second_loop_id,
                        "status": "blocked",
                        "note": "Waiting on owner confirmation.",
                    },
                ],
            },
            {
                "title": "Create follow-up surfaces",
                "summary": "Create one new loop and seed an enrichment review session.",
                "success_criteria": "A follow-up loop and review session both exist.",
                "operations": [
                    {
                        "kind": "create_loop",
                        "summary": "Capture the follow-up retrospective task.",
                        "raw_text": "Schedule launch retrospective",
                        "status": "actionable",
                        "capture_fields": {
                            "next_action": "Send retrospective invite",
                            "project": "launch",
                        },
                    },
                    {
                        "kind": "create_enrichment_review_session",
                        "summary": "Create a follow-up review queue for launch work.",
                        "name": "launch-follow-up",
                        "query": "status:open",
                        "pending_kind": "all",
                        "suggestion_limit": 3,
                        "clarification_limit": 3,
                        "item_limit": 25,
                    },
                ],
            },
        ],
    }


def test_planning_workflow_endpoints(
    make_test_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_test_client()
    first_id = _capture(client, "Prepare launch checklist")
    second_id = _capture(client, "Confirm launch owner", actionable=True)

    planner_responses = iter(
        [
            _planner_payload(first_id, second_id, title="Weekly launch reset"),
            _planner_payload(first_id, second_id, title="Refreshed weekly launch reset"),
        ]
    )
    monkeypatch.setattr(
        "cloop.loops.planning_workflows.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(next(planner_responses)),
            {"model": "mock-llm", "latency_ms": 0.0, "usage": {}},
        ),
    )

    create_response = client.post(
        "/loops/planning/sessions",
        json={
            "name": "weekly-reset",
            "prompt": "Build a checkpointed plan for the launch work.",
            "query": "status:open",
            "loop_limit": 10,
            "include_memory_context": True,
            "include_rag_context": False,
            "rag_k": 5,
        },
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    session_id = create_payload["session"]["id"]
    assert create_payload["current_checkpoint"]["title"] == "Stabilize the active loops"
    assert create_payload["context_summary"]["generated_at_utc"]

    list_response = client.get("/loops/planning/sessions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [session_id]

    move_response = client.post(
        f"/loops/planning/sessions/{session_id}/move",
        json={"direction": "next"},
    )
    assert move_response.status_code == 200
    assert move_response.json()["session"]["current_checkpoint_index"] == 1

    move_back_response = client.post(
        f"/loops/planning/sessions/{session_id}/move",
        json={"direction": "previous"},
    )
    assert move_back_response.status_code == 200
    assert move_back_response.json()["session"]["current_checkpoint_index"] == 0

    first_execute = client.post(f"/loops/planning/sessions/{session_id}/execute")
    assert first_execute.status_code == 200
    first_execute_payload = first_execute.json()
    assert first_execute_payload["execution"]["checkpoint_index"] == 0
    assert first_execute_payload["snapshot"]["session"]["executed_checkpoint_count"] == 1
    assert first_execute_payload["snapshot"]["session"]["current_checkpoint_index"] == 1

    loop_response = client.get(f"/loops/{first_id}")
    assert loop_response.status_code == 200
    assert loop_response.json()["next_action"] == "Draft the launch readiness checklist"

    second_execute = client.post(f"/loops/planning/sessions/{session_id}/execute")
    assert second_execute.status_code == 200
    second_execute_payload = second_execute.json()
    assert second_execute_payload["snapshot"]["session"]["status"] == "completed"
    assert second_execute_payload["snapshot"]["session"]["executed_checkpoint_count"] == 2

    review_sessions = client.get("/loops/review/enrichment/sessions")
    assert review_sessions.status_code == 200
    assert [item["name"] for item in review_sessions.json()] == ["launch-follow-up"]

    refresh_response = client.post(f"/loops/planning/sessions/{session_id}/refresh")
    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    assert refresh_payload["plan_title"] == "Refreshed weekly launch reset"
    assert refresh_payload["session"]["executed_checkpoint_count"] == 0
    assert refresh_payload["execution_history"] == []

    delete_response = client.delete(f"/loops/planning/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "session_id": session_id}

    with db.core_connection(get_settings()) as conn:
        assert repo.get_planning_session(session_id=session_id, conn=conn) is None
