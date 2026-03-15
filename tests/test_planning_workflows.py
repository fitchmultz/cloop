"""Tests for shared AI-native planning sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cloop import db
from cloop.loops import planning_workflows, repo, review_workflows, service
from cloop.loops.errors import ValidationError
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


def _expanded_operations_planner_payload(first_loop_id: int, second_loop_id: int) -> dict[str, Any]:
    return {
        "title": "Operator expansion plan",
        "summary": "Use broader deterministic operations with rollback metadata.",
        "assumptions": ["Query-scoped operations should stay transactional within one step."],
        "checkpoints": [
            {
                "title": "Standardize the launch loops",
                "summary": "Bulk-update and snooze the launch loops in one deterministic step.",
                "success_criteria": "Both launch loops share one project and snooze date.",
                "operations": [
                    {
                        "kind": "query_bulk_update",
                        "summary": "Assign the launch project to all open loops.",
                        "query": "status:open",
                        "fields": {"project": "launch"},
                        "limit": 25,
                    },
                    {
                        "kind": "query_bulk_snooze",
                        "summary": "Snooze the launch loops until the next review window.",
                        "query": "project:launch status:open",
                        "snooze_until_utc": "2026-03-20T09:00:00+00:00",
                        "limit": 25,
                    },
                ],
            },
            {
                "title": "Persist reusable operator scaffolding",
                "summary": "Create a saved view and template from the standardized loops.",
                "success_criteria": (
                    "Operators can reopen the same filtered view and reuse the template."
                ),
                "operations": [
                    {
                        "kind": "create_loop_view",
                        "summary": "Save the launch filter as a reusable view.",
                        "name": "launch-open",
                        "query": "project:launch status:open",
                        "description": "Open launch loops for the next planning pass.",
                    },
                    {
                        "kind": "create_loop_template_from_loop",
                        "summary": "Capture the first launch loop as a reusable template.",
                        "loop_id": first_loop_id,
                        "template_name": "launch-template",
                    },
                    {
                        "kind": "create_enrichment_review_session",
                        "summary": "Queue enrichment review for standardized launch work.",
                        "name": "launch-enrichment",
                        "query": "project:launch status:open",
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
        assert snapshot["context_summary"]["generated_at_utc"]

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
        assert first_execution["execution"]["summary"]["touched_loop_ids"] == [
            first_loop["id"],
            second_loop["id"],
        ]
        assert first_execution["execution"]["summary"]["rollback_supported_operation_count"] == 2
        assert first_execution["execution"]["results"][0]["rollback_supported"] is True
        assert (
            first_execution["execution"]["results"][0]["rollback_actions"][0]["kind"] == "loop.undo"
        )
        assert first_snapshot["session"]["executed_checkpoint_count"] == 1
        assert first_snapshot["session"]["current_checkpoint_index"] == 1
        assert first_snapshot["context_freshness"]["generated_at_utc"]
        assert set(first_snapshot["execution_analytics"]["executed_checkpoint_indexes"]) == {0}

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
        assert second_execution["execution"]["summary"]["created_loop_ids"]
        assert second_execution["execution"]["summary"]["created_review_session_ids"]

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


def test_planning_session_executes_expanded_deterministic_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        first_loop = _capture_loop("Prepare launch checklist", status=LoopStatus.INBOX, conn=conn)
        second_loop = _capture_loop("Confirm launch owner", status=LoopStatus.ACTIONABLE, conn=conn)
        conn.commit()

    monkeypatch.setattr(
        "cloop.loops.planning_workflows.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(_expanded_operations_planner_payload(first_loop["id"], second_loop["id"])),
            {"model": "mock-llm", "latency_ms": 0.0, "usage": {}},
        ),
    )

    with db.core_connection(settings) as conn:
        snapshot = planning_workflows.create_planning_session(
            name="operator-expansion",
            prompt="Broaden deterministic operator coverage for the launch work.",
            query="status:open",
            loop_limit=10,
            include_memory_context=True,
            include_rag_context=False,
            rag_k=5,
            rag_scope=None,
            conn=conn,
            settings=settings,
        )
        session_id = int(snapshot["session"]["id"])

        first_execution = planning_workflows.execute_planning_session_checkpoint(
            session_id=session_id,
            conn=conn,
            settings=settings,
        )
        first_summary = first_execution["execution"]["summary"]
        assert set(first_summary["touched_loop_ids"]) == {first_loop["id"], second_loop["id"]}
        assert first_summary["rollback_supported_operation_count"] == 2
        assert first_execution["execution"]["results"][0]["rollback_actions"]
        assert first_execution["execution"]["results"][1]["rollback_actions"]

        first_after = repo.read_loop(loop_id=first_loop["id"], conn=conn)
        second_after = repo.read_loop(loop_id=second_loop["id"], conn=conn)
        assert first_after is not None and first_after.project_id is not None
        assert second_after is not None and second_after.snooze_until_utc is not None

        second_execution = planning_workflows.execute_planning_session_checkpoint(
            session_id=session_id,
            conn=conn,
            settings=settings,
        )
        second_summary = second_execution["execution"]["summary"]
        assert second_summary["created_view_ids"]
        assert second_summary["created_template_ids"]
        assert second_summary["created_review_session_ids"]

        created_view = repo.get_loop_view_by_name(name="launch-open", conn=conn)
        assert created_view is not None
        created_template = repo.get_loop_template_by_name(name="launch-template", conn=conn)
        assert created_template is not None
        enrichment_sessions = review_workflows.list_enrichment_review_sessions(conn=conn)
        assert [session["name"] for session in enrichment_sessions] == ["launch-enrichment"]

        refreshed_snapshot = planning_workflows.get_planning_session(
            session_id=session_id, conn=conn
        )
        assert refreshed_snapshot["execution_analytics"]["follow_up_resource_count"] == 3
        assert refreshed_snapshot["execution_analytics"]["created_view_ids"] == [created_view["id"]]
        assert refreshed_snapshot["execution_analytics"]["created_template_ids"] == [
            created_template["id"]
        ]


def test_planning_session_rolls_back_prior_operations_on_late_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    failing_payload = {
        "title": "Rollback test",
        "summary": "Create a loop, then fail later so rollback must delete it.",
        "assumptions": [],
        "checkpoints": [
            {
                "title": "Rollback-sensitive checkpoint",
                "summary": "The created loop should disappear when the second operation fails.",
                "success_criteria": "No partial side effects remain.",
                "operations": [
                    {
                        "kind": "create_loop",
                        "summary": "Create the transient loop.",
                        "raw_text": "Transient rollback loop",
                        "status": "inbox",
                    },
                    {
                        "kind": "create_loop_view",
                        "summary": "This operation will fail after validation.",
                        "name": "rollback-view",
                        "query": "status:open",
                    },
                ],
            }
        ],
    }

    monkeypatch.setattr(
        "cloop.loops.planning_workflows.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(failing_payload),
            {"model": "mock-llm", "latency_ms": 0.0, "usage": {}},
        ),
    )
    monkeypatch.setattr(
        "cloop.loops.planning_workflows.loop_views.create_loop_view",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("view creation exploded")),
    )

    with db.core_connection(settings) as conn:
        snapshot = planning_workflows.create_planning_session(
            name="rollback-plan",
            prompt="Trigger rollback handling.",
            query="status:open",
            loop_limit=10,
            include_memory_context=True,
            include_rag_context=False,
            rag_k=5,
            rag_scope=None,
            conn=conn,
            settings=settings,
        )

        with pytest.raises(ValidationError) as exc_info:
            planning_workflows.execute_planning_session_checkpoint(
                session_id=int(snapshot["session"]["id"]),
                conn=conn,
                settings=settings,
            )

        assert "rollback completed" in exc_info.value.message
        assert repo.find_loop_by_raw_text(raw_text="Transient rollback loop", conn=conn) is None
        assert (
            repo.list_planning_session_runs(session_id=int(snapshot["session"]["id"]), conn=conn)
            == []
        )
