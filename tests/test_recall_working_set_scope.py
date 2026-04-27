"""Recall working-set scope regression tests.

Purpose:
    Verify chat and document-recall transports preserve explicit working-set
    scope inside rerun and landed follow-through contracts.

Responsibilities:
    - Cover HTTP, CLI, and MCP recall flows with explicit working-set ids.
    - Assert rerun handles, resume targets, and handoff metadata stay scoped.
    - Guard CLI text output from hiding landed follow-through details.

Scope:
    Recall-side chat and RAG ask contracts only.

Usage:
    Run with `uv run pytest tests/test_recall_working_set_scope.py -q` or via
    the standard repo test targets.

Invariants/Assumptions:
    - Explicit working-set ids must survive into rerun and resume locations.
    - Follow-through handoff metadata should expose the resolved working set.
    - CLI text mode should surface landed follow-through details directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.cli_package.chat_commands import chat_command
from cloop.cli_package.main import build_parser
from cloop.cli_package.rag_commands import ask_command, ingest_command
from cloop.loops import working_sets
from cloop.mcp_tools.chat_tools import chat_complete
from cloop.mcp_tools.rag_tools import rag_ask, rag_ingest
from cloop.schemas.chat import ChatMessage
from cloop.settings import Settings, ToolMode, get_settings
from tests.helpers import last_json_from_stdout


def _configure_isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embed(chunks: list[str], *, settings: Settings | None = None) -> list[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (index + 1) for index, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)


def _mock_rag_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat_completion(
        messages: list[dict[str, Any]], *, surface: Any, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        return "mock-response", {"model": settings.llm_model, "latency_ms": 9.0}

    monkeypatch.setattr("cloop.rag.ask_orchestration.chat_completion", fake_chat_completion)


def _mock_chat_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat_completion(
        messages: list[dict[str, Any]], *, surface: Any, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        return "mock-response", {
            "model": settings.pi_model,
            "latency_ms": 12.5,
            "usage": {},
            "provider": "pi",
            "api": "chat.completions",
            "stop_reason": "stop",
        }

    monkeypatch.setattr("cloop.chat_execution.chat_completion", fake_chat_completion)


def _create_working_set(*, settings: Settings, name: str = "Launch scope") -> int:
    with db.core_connection(settings) as conn:
        payload = working_sets.create_working_set(name=name, description=None, conn=conn)
    return int(payload["id"])


def _create_actionable_loop(*, settings: Settings, title: str, next_action: str) -> int:
    from cloop.loops.models import LoopStatus
    from cloop.loops.service import capture_loop

    with db.core_connection(settings) as conn:
        result = capture_loop(
            raw_text=title,
            captured_at_iso="2026-04-01T12:00:00Z",
            client_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        conn.execute(
            "UPDATE loops SET status = 'actionable', next_action = ? WHERE id = ?",
            (next_action, result["id"]),
        )
        conn.commit()
    return int(result["id"])


def _add_loop_to_working_set(*, settings: Settings, working_set_id: int, loop_id: int) -> None:
    with db.core_connection(settings) as conn:
        working_sets.add_working_set_item(
            working_set_id=working_set_id,
            item_type="loop",
            item_id=loop_id,
            label=None,
            description=None,
            metadata=None,
            conn=conn,
        )


def test_recall_http_preserves_explicit_working_set_scope(
    test_client: TestClient,
    tmp_data_dir: Path,
) -> None:
    settings = get_settings()
    working_set_id = _create_working_set(settings=settings)

    chat_response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What changed?"}],
            "tool_mode": "none",
            "working_set_id": working_set_id,
        },
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["rerun_action"]["rerun"]["working_set_id"] == working_set_id
    assert chat_payload["follow_through"]["resume_location"]["working_set_id"] == working_set_id
    assert chat_payload["follow_through"]["working_set_id"] == working_set_id
    assert (
        chat_payload["follow_through"]["display_card"]["handoff"]["working_set"]["working_set_name"]
        == "Launch scope"
    )

    doc = tmp_data_dir / "launch.txt"
    doc.write_text("Launch notes live in this document.", encoding="utf-8")
    ingest_response = test_client.post(
        "/ingest",
        json={
            "paths": [str(doc)],
            "working_set_id": working_set_id,
            "query": "Where are the launch notes?",
        },
    )
    assert ingest_response.status_code == 200
    ingest_payload = ingest_response.json()
    assert ingest_payload["follow_through"]["resume_location"]["working_set_id"] == working_set_id
    assert (
        ingest_payload["follow_through"]["resume_location"]["query"]
        == "Where are the launch notes?"
    )
    assert ingest_payload["follow_through"]["working_set_id"] == working_set_id

    ask_response = test_client.get(
        "/ask",
        params={"q": "Where are the launch notes?", "working_set_id": working_set_id},
    )
    assert ask_response.status_code == 200
    ask_payload = ask_response.json()
    assert ask_payload["rerun_action"]["rerun"]["working_set_id"] == working_set_id
    assert ask_payload["follow_through"]["resume_location"]["working_set_id"] == working_set_id
    assert ask_payload["follow_through"]["working_set_id"] == working_set_id
    assert (
        ask_payload["follow_through"]["display_card"]["handoff"]["working_set"]["working_set_name"]
        == "Launch scope"
    )


def test_recall_chat_loop_grounding_stays_inside_explicit_working_set(
    test_client: TestClient,
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    working_set_id = _create_working_set(settings=settings)
    scoped_loop_id = _create_actionable_loop(
        settings=settings,
        title="Scoped launch checklist",
        next_action="Send the launch email",
    )
    _create_actionable_loop(
        settings=settings,
        title="Global queue cleanup",
        next_action="Archive stale notes",
    )
    _add_loop_to_working_set(
        settings=settings, working_set_id=working_set_id, loop_id=scoped_loop_id
    )

    captured: dict[str, Any] = {}

    def fake_chat_completion(
        messages: list[dict[str, Any]], *, surface: Any, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        captured["messages"] = messages
        return "mock-response", {
            "model": settings.pi_model,
            "latency_ms": 12.5,
            "usage": {},
            "provider": "pi",
            "api": "chat.completions",
            "stop_reason": "stop",
        }

    monkeypatch.setattr("cloop.chat_execution.chat_completion", fake_chat_completion)

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What changed?"}],
            "tool_mode": "none",
            "include_loop_context": True,
            "working_set_id": working_set_id,
        },
    )
    assert response.status_code == 200

    loop_context = next(
        message["content"]
        for message in captured["messages"]
        if message["role"] == "system" and "## Current Loop Context" in message["content"]
    )
    assert 'Scope: working set "Launch scope"' in loop_context
    assert "Scoped launch checklist" in loop_context
    assert "Send the launch email" in loop_context
    assert "Global queue cleanup" not in loop_context
    assert "Only use loops saved in this working set." in loop_context

    payload = response.json()
    preview = payload["follow_through"]["display_card"]["preview"]
    assert any(
        item["label"] == "Scope" and item["value"] == "Working set · Launch scope"
        for item in preview
    )
    assert payload["follow_through"]["display_card"]["handoff"]["next_step"].endswith(
        'inside "Launch scope".'
    )


def test_recall_chat_does_not_fallback_to_global_loop_snapshot_for_empty_working_set(
    test_client: TestClient,
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    working_set_id = _create_working_set(settings=settings)
    _create_actionable_loop(
        settings=settings,
        title="Global queue cleanup",
        next_action="Archive stale notes",
    )

    captured: dict[str, Any] = {}

    def fake_chat_completion(
        messages: list[dict[str, Any]], *, surface: Any, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        captured["messages"] = messages
        return "mock-response", {
            "model": settings.pi_model,
            "latency_ms": 12.5,
            "usage": {},
            "provider": "pi",
            "api": "chat.completions",
            "stop_reason": "stop",
        }

    monkeypatch.setattr("cloop.chat_execution.chat_completion", fake_chat_completion)

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What changed?"}],
            "tool_mode": "none",
            "include_loop_context": True,
            "working_set_id": working_set_id,
        },
    )
    assert response.status_code == 200

    loop_context = next(
        message["content"]
        for message in captured["messages"]
        if message["role"] == "system" and "## Current Loop Context" in message["content"]
    )
    assert 'Scope: working set "Launch scope"' in loop_context
    assert "No saved loops are currently pinned in this working set." in loop_context
    assert "Global queue cleanup" not in loop_context


def test_recall_cli_preserves_scope_and_surfaces_follow_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    settings = _configure_isolated_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)
    _mock_rag_answer(monkeypatch)
    _mock_chat_runtime(monkeypatch)
    working_set_id = _create_working_set(settings=settings)
    parser = build_parser()

    chat_args = parser.parse_args(["chat", "What changed?", "--working-set", str(working_set_id)])
    assert chat_args.working_set == working_set_id
    assert chat_command(chat_args, settings) == 0
    chat_output = capsys.readouterr().out
    assert "Follow-through:" in chat_output
    assert f"working-set {working_set_id}" in chat_output
    assert "Rerun: Rerun answer" in chat_output

    doc = tmp_path / "launch.txt"
    doc.write_text("FastAPI launch notes.", encoding="utf-8")
    assert ingest_command(parser.parse_args(["ingest", str(doc)]), settings) == 0
    capsys.readouterr()

    ask_args = parser.parse_args(["ask", "launch notes", "--working-set", str(working_set_id)])
    assert ask_args.working_set == working_set_id
    assert ask_command(ask_args, settings) == 0
    ask_output = last_json_from_stdout(capsys)
    assert ask_output["rerun_action"]["rerun"]["working_set_id"] == working_set_id
    assert ask_output["follow_through"]["resume_location"]["working_set_id"] == working_set_id
    assert ask_output["follow_through"]["working_set_id"] == working_set_id


def test_recall_mcp_preserves_explicit_working_set_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _configure_isolated_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)
    _mock_rag_answer(monkeypatch)
    _mock_chat_runtime(monkeypatch)
    working_set_id = _create_working_set(settings=settings)

    doc = tmp_path / "launch.txt"
    doc.write_text("FastAPI launch notes.", encoding="utf-8")
    rag_ingest(paths=[str(doc)])

    chat_payload = chat_complete(
        messages=[ChatMessage(role="user", content="What changed?")],
        tool_mode=ToolMode.NONE,
        working_set_id=working_set_id,
    )
    assert chat_payload["rerun_action"]["rerun"]["working_set_id"] == working_set_id
    assert chat_payload["follow_through"]["resume_location"]["working_set_id"] == working_set_id
    assert chat_payload["follow_through"]["working_set_id"] == working_set_id

    ask_payload = rag_ask(question="launch notes", working_set_id=working_set_id)
    assert ask_payload["rerun_action"]["rerun"]["working_set_id"] == working_set_id
    assert ask_payload["follow_through"]["resume_location"]["working_set_id"] == working_set_id
    assert ask_payload["follow_through"]["working_set_id"] == working_set_id
