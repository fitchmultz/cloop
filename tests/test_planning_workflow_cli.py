"""CLI tests for saved planning sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cloop import db
from cloop.cli_package.main import main
from cloop.loops import repo
from cloop.settings import Settings, get_settings


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _last_json(capsys: Any) -> Any:
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    for index in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[index:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return json.loads(captured.out)


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


def test_planning_workflow_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    settings = _make_settings(tmp_path, monkeypatch)
    assert main(["capture", "Prepare launch checklist"]) == 0
    assert main(["capture", "Confirm launch owner", "--actionable"]) == 0
    capsys.readouterr()

    planner_responses = iter(
        [
            _planner_payload(1, 2, title="Weekly launch reset"),
            _planner_payload(1, 2, title="Refreshed weekly launch reset"),
        ]
    )
    monkeypatch.setattr(
        "cloop.loops.planning_workflows.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(next(planner_responses)),
            {"model": "mock-llm", "latency_ms": 0.0, "usage": {}},
        ),
    )

    assert (
        main(
            [
                "plan",
                "session",
                "create",
                "--name",
                "weekly-reset",
                "--prompt",
                "Build a checkpointed plan for the launch work.",
                "--query",
                "status:open",
            ]
        )
        == 0
    )
    session = _last_json(capsys)
    assert session["session"]["name"] == "weekly-reset"
    assert session["context_summary"]["generated_at_utc"]
    session_id = session["session"]["id"]

    assert main(["plan", "session", "list"]) == 0
    listed = _last_json(capsys)
    assert [item["id"] for item in listed] == [session_id]

    assert (
        main(
            [
                "plan",
                "session",
                "move",
                "--session",
                str(session_id),
                "--direction",
                "next",
            ]
        )
        == 0
    )
    moved = _last_json(capsys)
    assert moved["session"]["current_checkpoint_index"] == 1

    assert (
        main(
            [
                "plan",
                "session",
                "move",
                "--session",
                str(session_id),
                "--direction",
                "previous",
            ]
        )
        == 0
    )
    moved_back = _last_json(capsys)
    assert moved_back["session"]["current_checkpoint_index"] == 0

    assert main(["plan", "session", "execute", "--session", str(session_id)]) == 0
    first_execution = _last_json(capsys)
    assert first_execution["snapshot"]["session"]["executed_checkpoint_count"] == 1
    assert first_execution["snapshot"]["session"]["current_checkpoint_index"] == 1

    assert main(["plan", "session", "execute", "--session", str(session_id)]) == 0
    second_execution = _last_json(capsys)
    assert second_execution["snapshot"]["session"]["status"] == "completed"
    assert second_execution["snapshot"]["session"]["executed_checkpoint_count"] == 2

    with db.core_connection(settings) as conn:
        created_loop = repo.find_loop_by_raw_text(
            raw_text="Schedule launch retrospective",
            conn=conn,
        )
    assert created_loop is not None

    assert main(["plan", "session", "refresh", "--session", str(session_id)]) == 0
    refreshed = _last_json(capsys)
    assert refreshed["plan_title"] == "Refreshed weekly launch reset"
    assert refreshed["session"]["executed_checkpoint_count"] == 0

    assert main(["plan", "session", "delete", str(session_id)]) == 0
    deleted = _last_json(capsys)
    assert deleted == {"deleted": True, "session_id": session_id}
