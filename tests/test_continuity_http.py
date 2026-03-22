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

from conftest import insert_planning_session
from fastapi.testclient import TestClient


def _location_payload(
    *, state: str, review_focus: str | None = None, session_id: int | None = None
) -> dict[str, object | None]:
    return {
        "state": state,
        "recall_tool": "chat",
        "review_focus": review_focus,
        "session_id": session_id,
        "loop_id": None,
        "view_id": None,
        "memory_id": None,
        "working_set_id": None,
        "query": None,
    }


def _planning_outcome_payload(
    *,
    label: str,
    description: str,
    occurred_at_utc: str,
    session_id: int,
    workflow_thread_id: str,
    workflow_thread_summary: str,
    dedupe_key: str,
    resume_state: str = "plan",
) -> dict[str, object]:
    return {
        "kind": "planning",
        "label": label,
        "description": description,
        "occurred_at_utc": occurred_at_utc,
        "launch_location": _location_payload(
            state="plan",
            review_focus="planning",
            session_id=session_id,
        ),
        "outcome_card": {
            "id": f"receipt-{label.lower().replace(' ', '-')}",
            "kind": "receipt",
            "tone": "progress",
            "eyebrow": "Planning receipt",
            "title": label,
            "summary": description,
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
        "resume_location": _location_payload(
            state=resume_state,
            review_focus="planning" if resume_state == "plan" else None,
            session_id=session_id if resume_state == "plan" else None,
        ),
        "working_set_id": None,
        "workflow_thread": {
            "id": workflow_thread_id,
            "kind": "planning_checkpoint",
            "title": label,
            "summary": workflow_thread_summary,
            "parent_outcome_id": None,
        },
        "dedupe_key": dedupe_key,
        "source_surface": "review-workspace",
        "signal_level": "high",
        "metadata": {},
    }


def test_get_continuity_snapshot_returns_empty_payload(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    response = test_client.get("/loops/continuity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcomes"] == []
    assert payload["anchors"] == {"planning": None, "review": None}
    assert payload["workflow_summaries"] == []
    assert payload["recovery_acknowledgements"] == []


def test_post_outcome_and_put_anchor_return_refreshed_snapshot(
    test_client: TestClient,
    tmp_data_dir: Path,
) -> None:
    outcome_response = test_client.post(
        "/loops/continuity/outcomes",
        json={
            **_planning_outcome_payload(
                label="Created launch queue",
                description="The downstream review queue is ready.",
                occurred_at_utc="2026-03-21T12:00:00Z",
                session_id=41,
                workflow_thread_id="planning:41:checkpoint:0",
                workflow_thread_summary="Planning checkpoint thread",
                dedupe_key="planning::queue",
                resume_state="operator",
            ),
            "workflow_thread": {
                "id": "planning:41:checkpoint:0",
                "kind": "planning_checkpoint",
                "title": "Weekly reset",
                "summary": "Planning checkpoint thread",
                "parent_outcome_id": None,
            },
            "metadata": {"sessionId": 41},
        },
    )
    assert outcome_response.status_code == 200
    outcome_payload = outcome_response.json()
    assert outcome_payload["outcomes"][0]["label"] == "Created launch queue"
    assert (
        outcome_payload["workflow_summaries"][0]["workflow_thread"]["id"]
        == "planning:41:checkpoint:0"
    )

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

    marker_response = test_client.put(
        "/loops/continuity/last-seen",
        json={
            "markers": [
                {
                    "entity_kind": "planning_session",
                    "entity_key": "planning:41",
                    "observed_at_utc": "2026-03-21T12:06:00Z",
                    "observed_fingerprint": '{"status":"in_progress"}',
                    "working_set_id": None,
                    "workflow_thread_id": "planning:41",
                    "observed_state": {"status": "in_progress", "latestOutcomeId": 1},
                    "metadata": {},
                }
            ]
        },
    )
    assert marker_response.status_code == 200
    marker_payload = marker_response.json()
    assert marker_payload["last_seen_markers"][0]["entity_key"] == "planning:41"


def test_snapshot_includes_successor_and_recovery_acknowledgements(
    test_client: TestClient,
    tmp_data_dir: Path,
) -> None:
    insert_planning_session(99, name="Replacement plan")

    old_plan = test_client.post(
        "/loops/continuity/outcomes",
        json=_planning_outcome_payload(
            label="Old plan",
            description="The prior planning path.",
            occurred_at_utc="2026-03-21T12:00:00Z",
            session_id=41,
            workflow_thread_id="planning:41",
            workflow_thread_summary="Prior planning thread",
            dedupe_key="planning::41",
        ),
    )
    assert old_plan.status_code == 200

    replacement = test_client.post(
        "/loops/continuity/outcomes",
        json=_planning_outcome_payload(
            label="Replacement plan",
            description="The refreshed planning path.",
            occurred_at_utc="2026-03-21T12:05:00Z",
            session_id=99,
            workflow_thread_id="planning:99",
            workflow_thread_summary="New planning thread",
            dedupe_key="planning::99",
        ),
    )
    assert replacement.status_code == 200

    payload = replacement.json()
    old_plan_payload = next(item for item in payload["outcomes"] if item["label"] == "Old plan")
    assert old_plan_payload["resolved_resume"]["successor"]["kind"] == "replacement"
    assert old_plan_payload["resolved_resume"]["successor"]["resolved_location"]["session_id"] == 99
    top_summary = payload["workflow_summaries"][0]
    assert top_summary["workflow_thread"]["id"] == "planning:99"
    assert top_summary["why_now"]
    assert top_summary["changed_since_last_seen"]

    recovery_key = "replacement::planning:41::location:null::plan|chat|planning|99|-|-|-|-|-"
    ack_response = test_client.put(
        "/loops/continuity/recovery-acks",
        json={
            "recovery_key": recovery_key,
            "acknowledged_at_utc": "2026-03-21T12:10:00Z",
            "metadata": {},
        },
    )
    assert ack_response.status_code == 200
    assert ack_response.json()["recovery_acknowledgements"][0]["recovery_key"].startswith(
        "replacement::"
    )
