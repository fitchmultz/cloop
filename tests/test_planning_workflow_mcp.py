"""MCP tests for saved planning sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cloop import db
from cloop.loops import repo
from cloop.loops.models import LoopStatus
from cloop.mcp_tools.planning_tools import (
    plan_session_create,
    plan_session_delete,
    plan_session_execute,
    plan_session_get,
    plan_session_list,
    plan_session_move,
    plan_session_refresh,
)
from cloop.settings import Settings, get_settings


def _setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_TTL_SECONDS", "86400")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH", "255")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _create_loop(*, raw_text: str, status: LoopStatus, conn: Any) -> int:
    row = repo.create_loop(
        raw_text=raw_text,
        captured_at_utc="2026-03-14T12:00:00+00:00",
        captured_tz_offset_min=0,
        status=status,
        conn=conn,
    )
    return int(row.id)


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


def test_planning_workflow_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_test_db(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        first_id = _create_loop(
            raw_text="Prepare launch checklist",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        second_id = _create_loop(
            raw_text="Confirm launch owner",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        conn.commit()

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

    session = plan_session_create(
        name="weekly-reset",
        prompt="Build a checkpointed plan for the launch work.",
        query="status:open",
    )
    session_id = session["session"]["id"]
    assert session["current_checkpoint"]["title"] == "Stabilize the active loops"
    assert session["context_summary"]["generated_at_utc"]

    listed = plan_session_list()
    assert [item["id"] for item in listed] == [session_id]

    moved = plan_session_move(session_id=session_id, direction="next")
    assert moved["session"]["current_checkpoint_index"] == 1

    moved_back = plan_session_move(session_id=session_id, direction="previous")
    assert moved_back["session"]["current_checkpoint_index"] == 0

    first_execution = plan_session_execute(session_id=session_id)
    assert first_execution["snapshot"]["session"]["executed_checkpoint_count"] == 1
    assert first_execution["snapshot"]["session"]["current_checkpoint_index"] == 1

    second_execution = plan_session_execute(session_id=session_id)
    assert second_execution["snapshot"]["session"]["status"] == "completed"
    assert second_execution["snapshot"]["session"]["executed_checkpoint_count"] == 2

    loaded = plan_session_get(session_id=session_id)
    assert loaded["session"]["status"] == "completed"

    refreshed = plan_session_refresh(session_id=session_id)
    assert refreshed["plan_title"] == "Refreshed weekly launch reset"
    assert refreshed["session"]["executed_checkpoint_count"] == 0

    deleted = plan_session_delete(session_id=session_id)
    assert deleted == {"deleted": True, "session_id": session_id}
