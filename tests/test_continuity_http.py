"""Durable continuity HTTP regression tests.

Purpose:
    Verify the continuity HTTP routes expose durable snapshot hydration and write
    contracts for the operator shell.

Responsibilities:
    - Assert snapshot reads succeed from a clean database.
    - Assert outcome writes and anchor upserts return refreshed snapshots.

Non-scope:
    - Frontend ranking or browser-local cache behavior.

Usage:
    Run with `uv run --locked pytest tests/test_continuity_http.py`.

Invariants/Assumptions:
    - Tests use isolated FastAPI clients and SQLite databases.
    - Continuity routes remain mounted under `/loops/continuity`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_get_continuity_snapshot_returns_empty_payload(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    response = test_client.get("/loops/continuity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcomes"] == []
    assert payload["anchors"] == {"planning": None, "review": None}
    assert payload["threads"] == []


def test_post_outcome_and_put_anchor_return_refreshed_snapshot(
    test_client: TestClient,
    tmp_data_dir: Path,
) -> None:
    outcome_response = test_client.post(
        "/loops/continuity/outcomes",
        json={
            "kind": "planning",
            "label": "Created launch queue",
            "description": "The downstream review queue is ready.",
            "occurred_at_utc": "2026-03-21T12:00:00Z",
            "launch_location": {
                "state": "plan",
                "recall_tool": "chat",
                "review_focus": "planning",
                "session_id": 41,
                "loop_id": None,
                "view_id": None,
                "memory_id": None,
                "working_set_id": None,
                "query": None,
            },
            "outcome_card": {
                "id": "receipt-1",
                "kind": "receipt",
                "tone": "progress",
                "eyebrow": "Planning receipt",
                "title": "Created launch queue",
                "summary": "The downstream review queue is ready.",
                "rationale": "Receipt",
                "preview": [],
                "trust": {
                    "contextSources": ["Planning session"],
                    "assumptions": [],
                    "confidenceLabel": "Recorded",
                    "freshnessLabel": "Saved just now",
                    "rollbackLabel": "Undo remains available.",
                },
                "handoff": None,
                "actions": [],
            },
            "resume_location": {
                "state": "operator",
                "recall_tool": "chat",
                "review_focus": None,
                "session_id": None,
                "loop_id": None,
                "view_id": None,
                "memory_id": None,
                "working_set_id": None,
                "query": None,
            },
            "working_set_id": None,
            "workflow_thread": {
                "id": "planning:41:checkpoint:0",
                "kind": "planning_checkpoint",
                "title": "Weekly reset",
                "summary": "Planning checkpoint thread",
                "parent_outcome_id": None,
            },
            "dedupe_key": "planning::queue",
            "source_surface": "review-workspace",
            "signal_level": "high",
            "metadata": {"sessionId": 41},
        },
    )
    assert outcome_response.status_code == 200
    outcome_payload = outcome_response.json()
    assert outcome_payload["outcomes"][0]["label"] == "Created launch queue"
    assert outcome_payload["threads"][0]["workflow_thread"]["id"] == "planning:41:checkpoint:0"

    anchor_response = test_client.put(
        "/loops/continuity/anchors/planning",
        json={
            "anchor_kind": "planning",
            "review_focus": "planning",
            "session_id": 41,
            "visited_at_utc": "2026-03-21T12:05:00Z",
            "launch_location": {
                "state": "plan",
                "recall_tool": "chat",
                "review_focus": "planning",
                "session_id": 41,
                "loop_id": None,
                "view_id": None,
                "memory_id": None,
                "working_set_id": None,
                "query": None,
            },
            "resume_location": {
                "state": "plan",
                "recall_tool": "chat",
                "review_focus": "planning",
                "session_id": 41,
                "loop_id": None,
                "view_id": None,
                "memory_id": None,
                "working_set_id": None,
                "query": None,
            },
            "outcome_title": "Resume weekly reset",
            "outcome_summary": "Continue the saved planning session.",
            "working_set_id": None,
            "workflow_thread_id": "planning:41",
            "metadata": {},
        },
    )
    assert anchor_response.status_code == 200
    anchor_payload = anchor_response.json()
    assert anchor_payload["anchors"]["planning"]["session_id"] == 41
    assert anchor_payload["anchors"]["planning"]["workflow_thread_id"] == "planning:41"
