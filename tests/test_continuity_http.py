"""Durable continuity HTTP regression tests.

Purpose:
    Verify the continuity HTTP routes expose durable snapshot hydration and write
    contracts for the operator shell.

Responsibilities:
    - Assert snapshot and debug delivery-inspection reads succeed from a clean database.
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

from conftest import insert_planning_session, insert_scheduler_push_delivery
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


def _planning_undo_action_payload() -> dict[str, object]:
    return {
        "label": "Undo checkpoint",
        "description": "Undo the checkpoint execution.",
        "undo": {
            "kind": "planning_run",
            "session_id": 41,
            "run_id": 8,
            "checkpoint_index": 1,
            "checkpoint_title": "Create queue",
            "action_count": 2,
            "best_effort": False,
        },
        "requires_confirmation": False,
        "confirm_title": None,
        "confirm_description": None,
        "success_location": None,
    }


def _planning_rerun_action_payload() -> dict[str, object]:
    return {
        "label": "Refresh plan",
        "description": "Refresh the saved planning session.",
        "rerun": {
            "kind": "planning_session",
            "session_id": 41,
            "session_name": "Weekly reset",
        },
        "contract": {
            "mode": "refresh",
            "provenance_label": "Planning session: Weekly reset",
            "freshness_label": "1 target changed",
            "strategy_summary": "Reuse the saved planning session.",
            "strict_invariants": ["Same planning session identity"],
            "may_vary": ["Checkpoint wording"],
            "post_run": {
                "summary": "Land back in the saved planning session.",
                "location": None,
            },
        },
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
        "display_card": {
            "kind": "receipt",
            "tone": "progress",
            "eyebrow": "Planning receipt",
            "title": label,
            "summary": description,
            "rationale": "Receipt",
            "preview": [],
            "trust": {
                "context_sources": ["Planning session"],
                "assumptions": [],
                "confidence_label": "Recorded",
                "freshness_label": "Saved just now",
                "rollback_label": "Undo remains available.",
            },
            "handoff": None,
            "action_context_label": None,
            "action_warning": None,
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
    assert payload["workflow_summaries"] == []
    assert payload["notification_records"] == []
    assert payload["recovery_acknowledgements"] == []


def test_get_continuity_delivery_decisions_returns_debug_payload(
    test_client: TestClient,
    tmp_data_dir: Path,
) -> None:
    test_client.post(
        "/loops/continuity/outcomes",
        json=_planning_outcome_payload(
            label="Created launch queue",
            description="The downstream review queue is ready.",
            occurred_at_utc="2026-03-21T12:00:00Z",
            session_id=41,
            workflow_thread_id="planning:41:checkpoint:0",
            workflow_thread_summary="Planning checkpoint thread",
            dedupe_key="planning::queue",
            resume_state="operator",
        ),
    )
    test_client.put(
        "/loops/continuity/notifications/planning%3A41%3Acheckpoint%3A0/state",
        json={
            "inboxed_at_utc": "2026-03-21T12:01:00Z",
            "seen_at_utc": "2026-03-21T12:02:00Z",
        },
    )
    insert_scheduler_push_delivery(
        notification_id="planning:41:checkpoint:0",
        workflow_thread_id="planning:41:checkpoint:0",
        delivery_status="skipped",
        delivery_reason="notification_missing",
        push_count=0,
    )

    response = test_client.get("/loops/continuity/debug/delivery-decisions?limit=1&channel=all")

    assert response.status_code == 200
    payload = response.json()
    assert payload["channel"] == "all"
    assert payload["limit"] == 1
    assert payload["truncated"] is False
    assert payload["continuation"] is None
    assert payload["decisions"][0]["reason"] == "sent"
    assert payload["decisions"][0]["record"]["id"] == "planning:41:checkpoint:0"
    assert payload["decisions"][0]["record"]["state"] == {
        "inboxed_at_utc": "2026-03-21T12:01:00Z",
        "seen_at_utc": "2026-03-21T12:02:00Z",
        "acknowledged_at_utc": None,
        "suppressed_until_utc": None,
    }
    assert payload["decisions"][0]["resend_ready_at_utc"] is None
    assert payload["decisions"][0]["latest_push_delivery"] == {
        "task_name": "daily_review",
        "slot_key": "2026-03-21T12:00:00Z",
        "push_kind": "review_generated",
        "notification_id": "planning:41:checkpoint:0",
        "workflow_thread_id": "planning:41:checkpoint:0",
        "claimed_at_utc": "2026-03-21T12:00:10Z",
        "send_started_at_utc": "2026-03-21T12:00:11Z",
        "send_completed_at_utc": "2026-03-21T12:00:12Z",
        "delivery_status": "skipped",
        "delivery_reason": "notification_missing",
        "push_count": 0,
    }


def test_get_continuity_delivery_decisions_uses_cursor_pagination(
    test_client: TestClient,
    tmp_data_dir: Path,
) -> None:
    for label, occurred_at_utc in (
        ("Newest queue", "2026-03-21T12:03:00Z"),
        ("Older queue", "2026-03-21T12:02:00Z"),
    ):
        response = test_client.post(
            "/loops/continuity/outcomes",
            json=_planning_outcome_payload(
                label=label,
                description="The downstream review queue is ready.",
                occurred_at_utc=occurred_at_utc,
                session_id=41,
                workflow_thread_id=f"planning:41:{label.lower().replace(' ', '-')}",
                workflow_thread_summary="Planning checkpoint thread",
                dedupe_key=f"planning::{label.lower().replace(' ', '-')}",
                resume_state="operator",
            ),
        )
        assert response.status_code == 200

    first_page = test_client.get("/loops/continuity/debug/delivery-decisions?limit=1&channel=all")

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["truncated"] is True
    assert isinstance(first_payload["continuation"]["cursor"], str)
    assert first_payload["decisions"][0]["record"]["id"] == "planning:41:newest-queue"

    second_page = test_client.get(
        "/loops/continuity/debug/delivery-decisions",
        params={
            "limit": 1,
            "channel": "all",
            "cursor": first_payload["continuation"]["cursor"],
        },
    )

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert second_payload["truncated"] is False
    assert second_payload["continuation"] is None
    assert second_payload["decisions"][0]["record"]["id"] == "planning:41:older-queue"


def test_post_outcome_and_put_last_seen_return_refreshed_snapshot(
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
            "undo_action": _planning_undo_action_payload(),
            "rerun_action": _planning_rerun_action_payload(),
            "metadata": {"sessionId": 41},
        },
    )
    assert outcome_response.status_code == 200
    outcome_payload = outcome_response.json()
    assert outcome_payload["outcomes"][0]["label"] == "Created launch queue"
    assert outcome_payload["outcomes"][0]["undo_action"]["undo"]["kind"] == "planning_run"
    assert outcome_payload["outcomes"][0]["rerun_action"]["rerun"]["kind"] == "planning_session"
    assert (
        outcome_payload["workflow_summaries"][0]["workflow_thread"]["id"]
        == "planning:41:checkpoint:0"
    )
    assert outcome_payload["workflow_summaries"][0]["undo_action"]["undo"]["kind"] == "planning_run"
    assert (
        outcome_payload["workflow_summaries"][0]["rerun_action"]["rerun"]["kind"]
        == "planning_session"
    )
    assert outcome_payload["notification_records"][0]["id"] == "planning:41:checkpoint:0"
    assert outcome_payload["notification_records"][0]["state"] == {
        "inboxed_at_utc": None,
        "seen_at_utc": None,
        "acknowledged_at_utc": None,
        "suppressed_until_utc": None,
    }

    notification_state_response = test_client.put(
        "/loops/continuity/notifications/planning%3A41%3Acheckpoint%3A0/state",
        json={
            "inboxed_at_utc": "2026-03-21T12:01:00Z",
            "seen_at_utc": "2026-03-21T12:02:00Z",
        },
    )
    assert notification_state_response.status_code == 200
    notification_payload = notification_state_response.json()
    assert (
        notification_payload["notification_records"][0]["state"]["inboxed_at_utc"]
        == "2026-03-21T12:01:00Z"
    )
    assert (
        notification_payload["notification_records"][0]["state"]["seen_at_utc"]
        == "2026-03-21T12:02:00Z"
    )

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
    assert payload["notification_records"][0]["id"] == "planning:99"

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
