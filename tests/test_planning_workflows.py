"""Tests for shared AI-native planning sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cloop import db
from cloop.loops import planning_workflows, repo, review_workflows, service
from cloop.loops.models import LoopStatus
from cloop.settings import Settings, get_settings


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _capture_loop(raw_text: str, *, status: LoopStatus, conn: Any) -> dict[str, Any]:
    return service.capture_loop(
        raw_text=raw_text,
        captured_at_iso="2026-03-14T12:00:00+00:00",
        client_tz_offset_min=0,
        status=status,
        conn=conn,
    )


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


def test_planning_sessions_create_move_execute_refresh_and_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        first_loop = _capture_loop("Prepare launch checklist", status=LoopStatus.INBOX, conn=conn)
        second_loop = _capture_loop(
            "Confirm launch owner",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        conn.commit()

    planner_responses = iter(
        [
            _planner_payload(first_loop["id"], second_loop["id"], title="Weekly launch reset"),
            _planner_payload(
                first_loop["id"],
                second_loop["id"],
                title="Refreshed weekly launch reset",
            ),
        ]
    )

    monkeypatch.setattr(
        "cloop.loops.planning_workflows.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(next(planner_responses)),
            {"model": "mock-llm", "latency_ms": 0.0, "usage": {}},
        ),
    )

    with db.core_connection(settings) as conn:
        snapshot = planning_workflows.create_planning_session(
            name="weekly-reset",
            prompt="Build a checkpointed plan for the launch work.",
            query="status:open",
            loop_limit=10,
            include_memory_context=True,
            include_rag_context=False,
            rag_k=5,
            rag_scope=None,
            conn=conn,
            settings=settings,
        )

        assert snapshot["session"]["name"] == "weekly-reset"
        assert snapshot["session"]["status"] == "draft"
        assert snapshot["session"]["checkpoint_count"] == 2
        assert snapshot["current_checkpoint"]["title"] == "Stabilize the active loops"
        assert snapshot["target_loops"]

        listed = planning_workflows.list_planning_sessions(conn=conn)
        assert [item["name"] for item in listed] == ["weekly-reset"]

        moved = planning_workflows.move_planning_session(
            session_id=snapshot["session"]["id"],
            direction="next",
            conn=conn,
        )
        assert moved["session"]["current_checkpoint_index"] == 1

        moved_back = planning_workflows.move_planning_session(
            session_id=snapshot["session"]["id"],
            direction="previous",
            conn=conn,
        )
        assert moved_back["session"]["current_checkpoint_index"] == 0

        first_execution = planning_workflows.execute_planning_session_checkpoint(
            session_id=snapshot["session"]["id"],
            conn=conn,
            settings=settings,
        )
        first_snapshot = first_execution["snapshot"]
        assert first_execution["execution"]["checkpoint_index"] == 0
        assert first_snapshot["session"]["executed_checkpoint_count"] == 1
        assert first_snapshot["session"]["current_checkpoint_index"] == 1

        updated_first = repo.read_loop(loop_id=first_loop["id"], conn=conn)
        updated_second = repo.read_loop(loop_id=second_loop["id"], conn=conn)
        assert updated_first is not None
        assert updated_first.next_action == "Draft the launch readiness checklist"
        assert updated_second is not None
        assert updated_second.status == LoopStatus.BLOCKED
        assert len(first_snapshot["execution_history"]) == 1

        second_execution = planning_workflows.execute_planning_session_checkpoint(
            session_id=snapshot["session"]["id"],
            conn=conn,
            settings=settings,
        )
        second_snapshot = second_execution["snapshot"]
        assert second_snapshot["session"]["status"] == "completed"
        assert second_snapshot["session"]["executed_checkpoint_count"] == 2
        assert len(second_snapshot["execution_history"]) == 2

        created_loop = repo.find_loop_by_raw_text(
            raw_text="Schedule launch retrospective",
            conn=conn,
        )
        assert created_loop is not None
        assert created_loop.status == LoopStatus.ACTIONABLE

        enrichment_sessions = review_workflows.list_enrichment_review_sessions(conn=conn)
        assert [item["name"] for item in enrichment_sessions] == ["launch-follow-up"]

        refreshed = planning_workflows.refresh_planning_session(
            session_id=snapshot["session"]["id"],
            conn=conn,
            settings=settings,
        )
        assert refreshed["plan_title"] == "Refreshed weekly launch reset"
        assert refreshed["session"]["executed_checkpoint_count"] == 0
        assert refreshed["session"]["status"] == "draft"
        assert refreshed["execution_history"] == []

        deleted = planning_workflows.delete_planning_session(
            session_id=snapshot["session"]["id"],
            conn=conn,
        )
        assert deleted == {"deleted": True, "session_id": snapshot["session"]["id"]}
        assert planning_workflows.list_planning_sessions(conn=conn) == []
