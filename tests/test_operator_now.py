"""Tests for the canonical operator Now feed.

Purpose:
    Verify the backend-ranked Now feed reuses existing read surfaces, deduplicates
    overlapping launch targets, and stays reachable through the HTTP route.

Responsibilities:
    - Cover backend ranking and dedupe behavior across continuity + session inputs.
    - Confirm `/loops/now` returns launch-ready loop items end to end.

Non-scope:
    - Frontend rendering details.
    - Exhaustive planning/review workflow coverage.
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from cloop.operator_now import read_operator_now_feed
from cloop.schemas.loops import ContinuityLocationResponse


def _continuity_summary() -> SimpleNamespace:
    location = ContinuityLocationResponse(
        state="decide",
        review_focus="enrichment",
        session_id=52,
        working_set_id=7,
    )
    return SimpleNamespace(
        id="planning:41",
        rank=5400,
        working_set_id=7,
        why_now=["Prepared queue is ready"],
        changed_since_last_seen=["Planning execution created a downstream review session"],
        display_card=SimpleNamespace(
            kind="handoff",
            tone="attention",
            eyebrow="Primary next move",
            rationale="Continuity already identified the best durable resume path.",
        ),
        display_title="Launch review queue is ready",
        display_summary="Open the prepared downstream review queue.",
        resolved_resume=SimpleNamespace(resolved_location=location),
        occurred_at_utc="2026-03-21T12:00:00Z",
    )


def test_read_operator_now_feed_prefers_continuity_and_dedupes_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stronger continuity item should suppress a duplicate raw planning-session candidate."""
    planning_snapshot: dict[str, Any] = {
        "session": {
            "id": 41,
            "name": "Weekly reset",
            "status": "in_progress",
            "updated_at_utc": "2026-03-21T12:00:00Z",
        },
        "plan_summary": "Queue the launch follow-up decisions.",
        "context_freshness": {"summary_label": "2 target loops changed", "is_stale": True},
        "target_loops": [{"id": 1}, {"id": 2}],
        "current_checkpoint": {"title": "Create follow-up queue"},
        "execution_history": [
            {
                "launch_surfaces": [
                    {
                        "web": {
                            "surface": "review_session",
                            "review_kind": "enrichment",
                            "session_id": 52,
                            "working_set_id": 7,
                        }
                    }
                ],
                "follow_up_resources": [{"id": 99}],
            }
        ],
    }

    monkeypatch.setattr(
        "cloop.operator_now.db.core_connection",
        lambda _settings: nullcontext(object()),
    )
    monkeypatch.setattr(
        "cloop.operator_now.read_continuity_snapshot",
        lambda **_kwargs: SimpleNamespace(workflow_summaries=[_continuity_summary()]),
    )
    monkeypatch.setattr(
        "cloop.operator_now.working_sets.get_working_set_context",
        lambda **_kwargs: {"active_working_set_id": 7},
    )
    monkeypatch.setattr(
        "cloop.operator_now.loop_read_service.next_loops",
        lambda **_kwargs: {
            "due_soon": [
                {
                    "id": 17,
                    "title": "Review launch checklist",
                    "raw_text": "Review launch checklist",
                    "next_action": "Open the checklist",
                    "updated_at_utc": "2026-03-21T11:59:00Z",
                }
            ],
            "quick_wins": [],
            "high_leverage": [],
            "standard": [],
        },
    )
    monkeypatch.setattr(
        "cloop.operator_now.planning_workflows.list_planning_sessions",
        lambda **_kwargs: [{"id": 41, "updated_at_utc": "2026-03-21T12:00:00Z"}],
    )
    monkeypatch.setattr(
        "cloop.operator_now.planning_workflows.get_planning_session",
        lambda **_kwargs: planning_snapshot,
    )
    monkeypatch.setattr(
        "cloop.operator_now.review_workflows.list_relationship_review_sessions",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "cloop.operator_now.review_workflows.list_enrichment_review_sessions",
        lambda **_kwargs: [],
    )

    feed = read_operator_now_feed(limit=5)

    assert [item.source for item in feed.items] == ["continuity", "loop"]
    assert feed.items[0].title == "Launch review queue is ready"
    assert feed.items[0].launch_location.state == "decide"
    assert feed.items[1].launch_location.loop_id == 17


def test_loops_now_endpoint_returns_launch_ready_items(make_test_client) -> None:
    """The HTTP route should expose the canonical Now-feed contract end to end."""
    client = make_test_client()
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Review launch checklist",
            "captured_at": "2026-03-21T12:00:00Z",
            "client_tz_offset_min": 0,
            "actionable": True,
            "next_action": "Open the checklist",
        },
    )
    assert capture_response.status_code == 200

    now_response = client.get("/loops/now?limit=5")
    assert now_response.status_code == 200
    payload = now_response.json()

    assert payload["items"]
    first = payload["items"][0]
    assert first["source"] == "loop"
    assert first["launch_location"]["state"] == "do"
    assert first["action_label"] == "Open in Do"
