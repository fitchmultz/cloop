"""Tests for the CLI module."""

import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import numpy as np
import pytest

from cloop import db
from cloop.cli_package._runtime import run_cli_action
from cloop.cli_package.chat_commands import chat_command
from cloop.cli_package.loop_core_commands import (
    capture_command,
    inbox_command,
    loop_enrich_command,
    loop_get_command,
    loop_search_command,
    loop_snooze_command,
    loop_status_command,
    loop_update_command,
    next_command,
)
from cloop.cli_package.loop_misc_commands import import_command
from cloop.cli_package.main import build_parser, main
from cloop.cli_package.rag_commands import ask_command, ingest_command
from cloop.loops.errors import LoopNotFoundError
from cloop.loops.models import LoopStatus, resolve_status_from_flags
from cloop.settings import Settings, get_settings

cli = SimpleNamespace(
    build_parser=build_parser,
    main=main,
    _ask_command=ask_command,
    _chat_command=chat_command,
    _capture_command=capture_command,
    _import_command=import_command,
    _inbox_command=inbox_command,
    _ingest_command=ingest_command,
    _loop_enrich_command=loop_enrich_command,
    _loop_get_command=loop_get_command,
    _loop_search_command=loop_search_command,
    _loop_snooze_command=loop_snooze_command,
    _loop_status_command=loop_status_command,
    _loop_update_command=loop_update_command,
    _next_command=next_command,
)


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create isolated settings with temp database."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock embedding calls for RAG tests."""

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    # Mock at import locations (rag/__init__.py and rag/search.py import embed_texts)
    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)


def _mock_rag_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock non-streaming RAG answer generation for CLI tests."""

    def fake_chat_completion(
        messages: List[dict[str, Any]], *, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        return "mock-response", {"model": settings.llm_model, "latency_ms": 12.5}

    monkeypatch.setattr("cloop.rag.ask_orchestration.chat_completion", fake_chat_completion)


def _mock_chat_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock shared chat execution for CLI chat tests."""

    def fake_chat_completion(
        messages: List[dict[str, Any]], *, settings: Settings
    ) -> tuple[str, dict[str, Any]]:
        return "mock-response", {"model": settings.llm_model, "latency_ms": 12.5, "usage": {}}

    def fake_chat_with_tools(
        messages: List[dict[str, Any]], tools: Any, *, settings: Settings
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        return (
            "tool-mode-final",
            {
                "model": f"{settings.llm_model}-tool",
                "latency_ms": 8.0,
                "usage": {},
                "tool_outputs": [{"output": {"action": "write_note", "ok": True}}],
            },
            [{"name": "write_note", "arguments": {"title": "auto", "body": "generated"}}],
        )

    def fake_stream_events(*args: Any, **kwargs: Any):
        for token in ["mock", " ", "stream"]:
            yield {"type": "text_delta", "delta": token}
        yield {
            "type": "done",
            "model": "mock-llm",
            "latency_ms": 1.0,
            "usage": {},
        }

    monkeypatch.setattr("cloop.chat_execution.chat_completion", fake_chat_completion)
    monkeypatch.setattr("cloop.chat_execution.chat_with_tools", fake_chat_with_tools)
    monkeypatch.setattr("cloop.chat_execution.stream_events", fake_stream_events)


def test_run_cli_action_uses_shared_domain_error_mapping(capsys: Any) -> None:
    """CLI runtime should map domain exceptions through the shared error contract."""

    def _raise_not_found() -> None:
        raise LoopNotFoundError(loop_id=42)

    exit_code = run_cli_action(action=_raise_not_found)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Loop not found: 42" in captured.err


def _get_last_json(capsys: Any) -> Any:
    """Get the last JSON object from captured stdout.

    CLI commands may produce multiple outputs (from setup commands),
    so we split by lines and find the last valid JSON object.
    """
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")

    # Try to find the last complete JSON object by looking for closing brace
    # and parsing from the most recent complete object
    for i in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[i:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # If no valid JSON found, try parsing the whole output as a last resort
    return json.loads(captured.out)


def _run_cli_subprocess(
    tmp_path: Path,
    *args: str,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run CLI in a subprocess with isolated test settings."""
    env = os.environ.copy()
    env["CLOOP_DATA_DIR"] = str(tmp_path)
    env["CLOOP_AUTOPILOT_ENABLED"] = "false"
    env["CLOOP_PI_MODEL"] = "mock-llm"
    env["CLOOP_EMBED_MODEL"] = "mock-embed"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "python", "-m", "cloop.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
        env=env,
    )


# =============================================================================
# Argument Parsing Tests
# =============================================================================


def test_build_parser_ingest_command() -> None:
    """Test ingest argument parsing."""
    parser = cli.build_parser()
    args = parser.parse_args(["ingest", "doc.txt", "doc2.txt"])
    assert args.command == "ingest"
    assert args.paths == ["doc.txt", "doc2.txt"]
    assert args.mode == "add"
    assert args.no_recursive is False


def test_build_parser_ingest_mode_options() -> None:
    """Test ingest mode choices."""
    parser = cli.build_parser()
    for mode in ["add", "reindex", "purge", "sync"]:
        args = parser.parse_args(["ingest", "file.txt", "--mode", mode])
        assert args.mode == mode


def test_build_parser_ingest_no_recursive() -> None:
    """Test ingest --no-recursive flag."""
    parser = cli.build_parser()
    args = parser.parse_args(["ingest", "dir/", "--no-recursive"])
    assert args.no_recursive is True


def test_build_parser_ask_command() -> None:
    """Test ask argument parsing."""
    parser = cli.build_parser()
    args = parser.parse_args(["ask", "What is this?"])
    assert args.command == "ask"
    assert args.question == "What is this?"
    assert args.k == 5  # default


def test_build_parser_ask_custom_k() -> None:
    """Test ask with custom top-k."""
    parser = cli.build_parser()
    args = parser.parse_args(["ask", "question", "--k", "10"])
    assert args.k == 10


def test_build_parser_ask_with_scope() -> None:
    """Test ask with scope filter."""
    parser = cli.build_parser()
    args = parser.parse_args(["ask", "question", "--scope", "doc:123"])
    assert args.scope == "doc:123"


def test_build_parser_chat_command() -> None:
    """Test chat argument parsing."""
    parser = cli.build_parser()
    args = parser.parse_args(["chat", "Hello there"])
    assert args.command == "chat"
    assert args.prompt == "Hello there"
    assert args.format == "text"
    assert args.tool_mode is None
    assert args.stream is None


def test_build_parser_chat_with_full_option_set() -> None:
    """Test chat parser with grounding, tool, and transcript options."""
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "chat",
            "--messages-file",
            "transcript.json",
            "--system-message",
            "Stay concise",
            "--tool",
            "loop_create",
            "--tool-arg",
            'raw_text="Pay rent"',
            "--include-loop-context",
            "--include-memory-context",
            "--memory-limit",
            "7",
            "--include-rag-context",
            "--rag-k",
            "3",
            "--rag-scope",
            "project-alpha",
            "--stream",
            "--format",
            "json",
            "What changed?",
        ]
    )
    assert args.command == "chat"
    assert args.messages_file == "transcript.json"
    assert args.system_message == "Stay concise"
    assert args.tool == "loop_create"
    assert args.tool_arg == ['raw_text="Pay rent"']
    assert args.include_loop_context is True
    assert args.include_memory_context is True
    assert args.memory_limit == 7
    assert args.include_rag_context is True
    assert args.rag_k == 3
    assert args.rag_scope == "project-alpha"
    assert args.stream is True
    assert args.format == "json"
    assert args.prompt == "What changed?"


def test_build_parser_capture_command() -> None:
    """Test capture argument parsing."""
    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Buy milk"])
    assert args.command == "capture"
    assert args.text == "Buy milk"


def test_build_parser_capture_status_flags() -> None:
    """Test capture status flag parsing."""
    parser = cli.build_parser()

    # Default (no flags)
    args = parser.parse_args(["capture", "test"])
    assert args.scheduled is False
    assert args.blocked is False
    assert args.actionable is False

    # --actionable flag
    args = parser.parse_args(["capture", "test", "--actionable"])
    assert args.actionable is True

    # --urgent alias
    args = parser.parse_args(["capture", "test", "--urgent"])
    assert args.actionable is True

    # --scheduled flag
    args = parser.parse_args(["capture", "test", "--scheduled"])
    assert args.scheduled is True

    # --blocked flag
    args = parser.parse_args(["capture", "test", "--blocked"])
    assert args.blocked is True

    # --waiting alias
    args = parser.parse_args(["capture", "test", "--waiting"])
    assert args.blocked is True


def test_build_parser_capture_with_timestamp() -> None:
    """Test capture with custom captured-at."""
    parser = cli.build_parser()
    ts = "2024-01-15T10:30:00+00:00"
    args = parser.parse_args(["capture", "test", "--captured-at", ts])
    assert args.captured_at == ts


def test_build_parser_capture_with_tz_offset() -> None:
    """Test capture with explicit timezone offset."""
    parser = cli.build_parser()
    args = parser.parse_args(["capture", "test", "--tz-offset-min", "-480"])
    assert args.tz_offset_min == -480


def test_build_parser_inbox_command() -> None:
    """Test inbox argument parsing."""
    parser = cli.build_parser()
    args = parser.parse_args(["inbox"])
    assert args.command == "inbox"
    assert args.limit == 50  # default


def test_build_parser_inbox_custom_limit() -> None:
    """Test inbox with custom limit."""
    parser = cli.build_parser()
    args = parser.parse_args(["inbox", "--limit", "100"])
    assert args.limit == 100


def test_build_parser_next_command() -> None:
    """Test next argument parsing."""
    parser = cli.build_parser()
    args = parser.parse_args(["next"])
    assert args.command == "next"
    assert args.limit == 5  # default


def test_build_parser_next_custom_limit() -> None:
    """Test next with custom limit."""
    parser = cli.build_parser()
    args = parser.parse_args(["next", "--limit", "10"])
    assert args.limit == 10


def test_ask_help_describes_answer_payload(tmp_path: Path) -> None:
    """Rendered ask help should match the answer-oriented CLI contract."""
    result = _run_cli_subprocess(tmp_path, "ask", "--help")

    assert result.returncode == 0
    assert "generate an answer" in result.stdout


def test_chat_help_describes_grounded_contract(tmp_path: Path) -> None:
    """Rendered chat help should explain the grounded shared chat contract."""
    result = _run_cli_subprocess(tmp_path, "chat", "--help")

    assert result.returncode == 0
    assert "same grounded request/response contract" in result.stdout
    assert "--messages-file" in result.stdout
    assert "--include-loop-context" in result.stdout


def test_next_help_describes_total_limit(tmp_path: Path) -> None:
    """Rendered next help should describe the real total bucket cap."""
    result = _run_cli_subprocess(tmp_path, "next", "--help")

    assert result.returncode == 0
    assert "Max total loops across all buckets" in result.stdout
    assert "Show more items overall" in result.stdout


def test_loop_list_help_describes_open_default(tmp_path: Path) -> None:
    """Rendered list help should document the default open-loop filter."""
    result = _run_cli_subprocess(tmp_path, "loop", "list", "--help")

    assert result.returncode == 0
    assert "List all open loops (default)" in result.stdout


def test_build_parser_memory_command() -> None:
    """Memory parser should accept deterministic CRUD/search arguments."""
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "memory",
            "update",
            "12",
            "--clear-key",
            "--content",
            "Updated memory",
            "--priority",
            "75",
            "--metadata-json",
            '{"source_app":"cli"}',
        ]
    )
    assert args.command == "memory"
    assert args.memory_command == "update"
    assert args.id == 12
    assert args.clear_key is True
    assert args.content == "Updated memory"
    assert args.priority == 75
    assert args.metadata_json == '{"source_app":"cli"}'


# =============================================================================
# Command Function Tests
# =============================================================================


def test_ingest_command_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test successful document ingestion."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    doc = tmp_path / "test.txt"
    doc.write_text("Test content for ingestion", encoding="utf-8")

    parser = cli.build_parser()
    args = parser.parse_args(["ingest", str(doc)])

    exit_code = cli._ingest_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["files"] == 1
    assert output["chunks"] >= 1
    assert output["files_skipped"] == 0

    with db.core_connection(settings) as conn:
        row = conn.execute(
            "SELECT endpoint, request_payload FROM interactions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["endpoint"] == "/cli/ingest"
    request_payload = json.loads(row["request_payload"])
    assert request_payload["paths"] == [str(doc)]


def test_ask_command_no_knowledge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test ask command when no documents are ingested."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["ask", "What is this?"])

    exit_code = cli._ask_command(args, settings)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No knowledge available" in captured.err


def test_ask_command_with_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test ask command returns an answer plus sanitized supporting sources."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)
    _mock_rag_answer(monkeypatch)

    doc = tmp_path / "doc.txt"
    doc.write_text("FastAPI is a modern web framework", encoding="utf-8")
    cli._ingest_command(cli.build_parser().parse_args(["ingest", str(doc)]), settings)
    # Clear the ingest output
    capsys.readouterr()

    parser = cli.build_parser()
    args = parser.parse_args(["ask", "web framework"])

    exit_code = cli._ask_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["answer"] == "mock-response"
    assert output["model"] == "mock-llm"
    assert "chunks" in output
    assert "sources" in output
    assert len(output["chunks"]) > 0
    assert len(output["sources"]) > 0
    # Verify embedding_blob is stripped
    for chunk in output["chunks"]:
        assert "embedding_blob" not in chunk

    with db.core_connection(settings) as conn:
        row = conn.execute(
            "SELECT endpoint, request_payload FROM interactions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["endpoint"] == "/cli/ask"
    request_payload = json.loads(row["request_payload"])
    assert request_payload["question"] == "web framework"


def test_chat_command_json_response_and_interaction_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Chat CLI should emit the canonical JSON response and log the interaction."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_chat_runtime(monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "chat",
            "What should I focus on today?",
            "--include-loop-context",
            "--include-memory-context",
            "--format",
            "json",
        ]
    )

    exit_code = cli._chat_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["message"] == "mock-response"
    assert output["model"] == "mock-llm"
    assert output["options"]["tool_mode"] == "none"
    assert output["options"]["include_loop_context"] is True
    assert output["options"]["include_memory_context"] is True

    with db.core_connection(settings) as conn:
        row = conn.execute(
            "SELECT endpoint, request_payload FROM interactions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["endpoint"] == "/cli/chat"
    request_payload = json.loads(row["request_payload"])
    assert request_payload["effective_options"]["tool_mode"] == "none"


def test_chat_command_streams_text_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Text chat mode should stream token deltas directly to stdout."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_chat_runtime(monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["chat", "Hello", "--stream"])

    exit_code = cli._chat_command(args, settings)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == "mock stream\n"
    assert captured.err == ""


def test_chat_command_manual_tool_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """CLI chat can execute explicit manual tools and return the canonical payload."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_chat_runtime(monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "chat",
            "Create a loop",
            "--tool",
            "loop_create",
            "--tool-arg",
            'raw_text="Pay rent"',
            "--format",
            "json",
        ]
    )

    exit_code = cli._chat_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["message"] == "mock-response"
    assert output["tool_result"]["action"] == "loop_create"
    assert output["tool_result"]["loop"]["raw_text"] == "Pay rent"
    assert output["options"]["tool_mode"] == "manual"


def test_chat_command_reads_prompt_from_stdin_with_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """CLI chat should support explicit stdin prompt input via '-'"""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_chat_runtime(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Prompt from stdin\n"))

    parser = cli.build_parser()
    args = parser.parse_args(["chat", "-", "--format", "json"])

    exit_code = cli._chat_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["message"] == "mock-response"
    assert output["options"]["tool_mode"] == "none"


def test_chat_command_messages_file_appends_new_user_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """CLI chat should allow a saved transcript plus a new one-shot user prompt."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_chat_runtime(monkeypatch)

    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            [
                {"role": "system", "content": "Existing context"},
                {"role": "assistant", "content": "Prior answer"},
            ]
        ),
        encoding="utf-8",
    )

    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "chat",
            "What changed?",
            "--messages-file",
            str(transcript),
            "--format",
            "json",
        ]
    )

    exit_code = cli._chat_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["message"] == "mock-response"

    with db.core_connection(settings) as conn:
        row = conn.execute(
            "SELECT request_payload FROM interactions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    request_payload = json.loads(row["request_payload"])
    assert request_payload["messages"][0]["content"] == "Existing context"
    assert request_payload["messages"][-1]["content"] == "What changed?"


def test_capture_command_default_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture command creates inbox loop by default."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Test loop text"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["raw_text"] == "Test loop text"
    assert output["status"] == "inbox"
    assert "id" in output


def test_capture_command_actionable_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with --actionable flag."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Urgent task", "--actionable"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "actionable"


def test_capture_command_scheduled_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with --scheduled flag."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Scheduled task", "--scheduled"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "scheduled"


def test_capture_command_blocked_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with --blocked flag."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Blocked task", "--blocked"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "blocked"


def test_capture_command_status_flag_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test that scheduled > blocked > actionable in status flag priority."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()

    # Multiple flags - scheduled should win
    args = parser.parse_args(["capture", "test", "--actionable", "--blocked", "--scheduled"])
    exit_code = cli._capture_command(args, settings)
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "scheduled"

    # blocked vs actionable - blocked should win
    capsys.readouterr()  # Clear output from previous capture
    args = parser.parse_args(["capture", "test2", "--actionable", "--blocked"])
    exit_code = cli._capture_command(args, settings)
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "blocked"


def test_capture_command_with_custom_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with explicit captured-at timestamp and timezone."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    ts = "2024-06-15T14:30:00+05:30"
    args = parser.parse_args(["capture", "Test", "--captured-at", ts, "--tz-offset-min", "330"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # The service layer normalizes to UTC: 14:30+05:30 = 09:00+00:00
    assert output["captured_at_utc"] == "2024-06-15T09:00:00+00:00"
    assert output["captured_tz_offset_min"] == 330


def test_capture_command_auto_timezone_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture auto-calculates timezone offset when not provided."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Test with auto tz"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # Should have some timezone offset (varies by test environment)
    assert "captured_tz_offset_min" in output
    assert isinstance(output["captured_tz_offset_min"], int)


def test_capture_command_with_autopilot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture command when autopilot is enabled."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    # Mock the request_enrichment function to avoid actual LLM calls
    mock_enrichment = {"id": 1, "title": "Enriched Loop", "status": "inbox"}

    def mock_request_enrichment(*, loop_id: int, conn: sqlite3.Connection) -> dict:
        return mock_enrichment

    monkeypatch.setattr(
        "cloop.loops.capture_orchestration.service.request_enrichment",
        mock_request_enrichment,
    )

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Test autopilot"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # With autopilot, it returns the enriched record
    assert output == mock_enrichment


def test_capture_command_missing_template_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture command rejects missing templates with a dedicated exit code."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Test", "--template", "missing-template"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "template not found" in captured.err.lower()


def test_inbox_command_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test inbox command with no loops."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["inbox"])

    exit_code = cli._inbox_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output == []


def test_inbox_command_with_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test inbox command returns only inbox loops."""
    settings = _make_settings(tmp_path, monkeypatch)

    # Create loops with different statuses
    parser = cli.build_parser()

    # Inbox loop
    cli._capture_command(parser.parse_args(["capture", "Inbox item"]), settings)
    # Actionable loop
    cli._capture_command(
        parser.parse_args(["capture", "Actionable item", "--actionable"]),
        settings,
    )
    # Blocked loop
    cli._capture_command(
        parser.parse_args(["capture", "Blocked item", "--blocked"]),
        settings,
    )

    # Clear all the capture outputs
    capsys.readouterr()

    args = parser.parse_args(["inbox"])
    exit_code = cli._inbox_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 1
    assert output[0]["raw_text"] == "Inbox item"
    assert output[0]["status"] == "inbox"


def test_inbox_command_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test inbox command respects limit."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()

    # Create multiple inbox loops
    for i in range(5):
        cli._capture_command(parser.parse_args(["capture", f"Item {i}"]), settings)

    # Clear all the capture outputs
    capsys.readouterr()

    args = parser.parse_args(["inbox", "--limit", "3"])
    exit_code = cli._inbox_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 3


def test_next_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test next command returns prioritized loops."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()

    # Create a loop
    cli._capture_command(parser.parse_args(["capture", "Test loop", "--actionable"]), settings)

    # Clear the capture output
    capsys.readouterr()

    args = parser.parse_args(["next"])
    exit_code = cli._next_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # next_loops returns a dict with buckets
    assert isinstance(output, dict)
    assert "due_soon" in output
    assert "quick_wins" in output
    assert "high_leverage" in output
    assert "standard" in output


# =============================================================================
# Main Entry Point Tests - Must be isolated to avoid settings conflicts
# =============================================================================


def test_main_ingest_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with ingest command."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    # Mock embeddings at the module level
    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)

    doc = tmp_path / "doc.txt"
    doc.write_text("content", encoding="utf-8")

    exit_code = cli.main(["ingest", str(doc)])

    assert exit_code == 0


def test_main_ask_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with ask command (no knowledge)."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    # Mock embeddings
    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)

    exit_code = cli.main(["ask", "question"])

    assert exit_code == 1


def test_main_chat_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with chat command."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    _mock_chat_runtime(monkeypatch)

    exit_code = cli.main(["chat", "Hello", "--format", "json"])

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["message"] == "mock-response"


def test_main_capture_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with capture command."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["capture", "Test capture"])

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["raw_text"] == "Test capture"


def test_main_inbox_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with inbox command."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["inbox"])

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output == []


def test_main_next_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with next command."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["next"])

    assert exit_code == 0


def test_main_no_args_shows_help() -> None:
    """Test main() with no args shows help and exits with error."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])

    assert exc_info.value.code == 2


# =============================================================================
# Edge Case Tests
# =============================================================================


def test_ingest_recursive_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test that ingest is recursive by default."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    doc = subdir / "nested.txt"
    doc.write_text("nested content", encoding="utf-8")

    parser = cli.build_parser()
    args = parser.parse_args(["ingest", str(tmp_path)])

    exit_code = cli._ingest_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["files"] == 1


def test_ingest_no_recursive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test that --no-recursive skips subdirectories."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    doc = subdir / "nested.txt"
    doc.write_text("nested content", encoding="utf-8")

    parser = cli.build_parser()
    args = parser.parse_args(["ingest", str(tmp_path), "--no-recursive"])

    exit_code = cli._ingest_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["files"] == 0  # No files in root, recursion disabled


def test_ask_with_scope_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test ask command with scope filter."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)
    _mock_rag_answer(monkeypatch)

    doc_a = tmp_path / "alpha.txt"
    doc_b = tmp_path / "beta.txt"
    doc_a.write_text("alpha content here", encoding="utf-8")
    doc_b.write_text("beta content here", encoding="utf-8")

    cli._ingest_command(
        cli.build_parser().parse_args(["ingest", str(doc_a), str(doc_b)]),
        settings,
    )
    # Clear ingest output
    capsys.readouterr()

    parser = cli.build_parser()
    args = parser.parse_args(["ask", "content", "--scope", "alpha.txt"])

    exit_code = cli._ask_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert all("alpha.txt" in chunk["document_path"] for chunk in output["chunks"])


def test_capture_status_flag_priority_order() -> None:
    """Verify status flag priority: scheduled > blocked > actionable > inbox."""
    parser = cli.build_parser()

    # Test all flags - scheduled should win
    args = parser.parse_args(["capture", "test", "--actionable", "--blocked", "--scheduled"])
    assert args.scheduled is True
    assert args.blocked is True
    assert args.actionable is True

    # Verify the priority logic in _capture_command
    assert resolve_status_from_flags(True, True, True) == LoopStatus.SCHEDULED

    # Test blocked vs actionable - blocked wins
    args = parser.parse_args(["capture", "test", "--actionable", "--blocked"])
    assert resolve_status_from_flags(False, True, True) == LoopStatus.BLOCKED

    # Test actionable only
    args = parser.parse_args(["capture", "test", "--actionable"])
    assert resolve_status_from_flags(False, False, True) == LoopStatus.ACTIONABLE

    # Test default (no flags)
    args = parser.parse_args(["capture", "test"])
    assert resolve_status_from_flags(False, False, False) == LoopStatus.INBOX


def test_ingest_multiple_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test ingest with multiple file paths."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    doc1 = tmp_path / "doc1.txt"
    doc2 = tmp_path / "doc2.txt"
    doc1.write_text("content 1", encoding="utf-8")
    doc2.write_text("content 2", encoding="utf-8")

    parser = cli.build_parser()
    args = parser.parse_args(["ingest", str(doc1), str(doc2)])

    exit_code = cli._ingest_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["files"] == 2


def test_ingest_directory_with_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test ingest directory with different modes."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    doc = tmp_path / "doc.txt"
    doc.write_text("content", encoding="utf-8")

    parser = cli.build_parser()

    # Test with reindex mode
    args = parser.parse_args(["ingest", str(tmp_path), "--mode", "reindex"])
    exit_code = cli._ingest_command(args, settings)
    assert exit_code == 0

    output = _get_last_json(capsys)
    assert output["files"] == 1


def test_capture_with_negative_tz_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with negative timezone offset (west of UTC)."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    ts = "2024-01-15T10:00:00-08:00"
    args = parser.parse_args(["capture", "Test", "--captured-at", ts, "--tz-offset-min", "-480"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["captured_tz_offset_min"] == -480


def test_capture_with_positive_tz_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with positive timezone offset (east of UTC)."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    ts = "2024-01-15T10:00:00+05:30"
    args = parser.parse_args(["capture", "Test", "--captured-at", ts, "--tz-offset-min", "330"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["captured_tz_offset_min"] == 330


def test_capture_only_tz_offset_no_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with tz-offset but no explicit timestamp."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Test", "--tz-offset-min", "120"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # Should use the provided tz_offset_min
    assert output["captured_tz_offset_min"] == 120
    # Should have a captured_at (auto-generated) - verify it's a valid ISO timestamp
    assert "captured_at_utc" in output
    assert "T" in output["captured_at_utc"]  # ISO format has 'T'


def test_inbox_with_zero_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test inbox command with limit=0."""
    settings = _make_settings(tmp_path, monkeypatch)

    # Create some loops
    parser = cli.build_parser()
    for i in range(3):
        cli._capture_command(parser.parse_args(["capture", f"Item {i}"]), settings)

    # Clear all the capture outputs
    capsys.readouterr()

    args = parser.parse_args(["inbox", "--limit", "0"])
    exit_code = cli._inbox_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 0


def test_next_with_zero_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test next command with limit=0."""
    settings = _make_settings(tmp_path, monkeypatch)

    # Create a loop
    parser = cli.build_parser()
    cli._capture_command(parser.parse_args(["capture", "Test", "--actionable"]), settings)

    # Clear the capture output
    capsys.readouterr()

    args = parser.parse_args(["next", "--limit", "0"])
    exit_code = cli._next_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # Should still return the buckets structure
    assert "due_soon" in output


def test_capture_with_empty_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture command with empty text."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", ""])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["raw_text"] == ""


def test_ingest_nonexistent_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test ingest with non-existent path."""
    settings = _make_settings(tmp_path, monkeypatch)

    parser = cli.build_parser()
    args = parser.parse_args(["ingest", "/nonexistent/path"])

    # Should handle gracefully (no files ingested)
    exit_code = cli._ingest_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["files"] == 0
    assert output["chunks"] == 0


def test_main_unknown_command() -> None:
    """Test main() with an unknown command should error."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["unknown_command"])

    assert exc_info.value.code == 2


def test_main_ask_with_empty_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test main() with ask command and empty question."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    # Mock embeddings
    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)

    # Empty question is still a valid question string
    exit_code = cli.main(["ask", ""])

    assert exit_code == 1  # No knowledge available


# =============================================================================
# Loop Lifecycle Command Tests
# =============================================================================


def test_loop_get_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test loop get command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test loop"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "get", "1"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["id"] == 1
    assert output["raw_text"] == "Test loop"


def test_loop_get_command_table_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop get command with table output format."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test loop"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "get", "1", "--format", "table"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "field" in captured.out
    assert "raw_text" in captured.out


def test_loop_get_command_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop get command with non-existent ID."""
    settings = _make_settings(tmp_path, monkeypatch)

    exit_code = cli._loop_get_command(
        cli.build_parser().parse_args(["loop", "get", "999"]), settings
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_loop_list_command_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with default open status."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Inbox item"]), settings)
    cli._capture_command(
        parser.parse_args(["capture", "Actionable item", "--actionable"]), settings
    )
    cli._capture_command(parser.parse_args(["capture", "Completed", "--actionable"]), settings)
    capsys.readouterr()

    cli._loop_status_command(parser.parse_args(["loop", "status", "3", "completed"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 2
    statuses = {loop["status"] for loop in output}
    assert statuses == {"inbox", "actionable"}


def test_loop_list_command_all_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with --status all."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Item 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Item 2", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--status", "all"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 2


def test_loop_list_command_specific_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with specific status filter."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Inbox 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Inbox 2"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Actionable", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--status", "inbox"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 2
    assert all(loop["status"] == "inbox" for loop in output)


def test_loop_list_command_with_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with tag filter."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Item 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Item 2"]), settings)
    capsys.readouterr()

    cli._loop_update_command(
        parser.parse_args(["loop", "update", "1", "--tags", "work,urgent"]), settings
    )
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--tag", "work"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 1
    assert "work" in output[0]["tags"]


def test_loop_list_command_with_tag_and_all_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with tag filter and --status all."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Item 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Item 2", "--actionable"]), settings)
    capsys.readouterr()

    cli._loop_update_command(parser.parse_args(["loop", "update", "1", "--tags", "work"]), settings)
    cli._loop_update_command(parser.parse_args(["loop", "update", "2", "--tags", "work"]), settings)
    cli._loop_status_command(parser.parse_args(["loop", "status", "2", "completed"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--tag", "work", "--status", "all"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 2
    statuses = {loop["status"] for loop in output}
    assert statuses == {"inbox", "completed"}


def test_loop_list_command_with_tag_and_specific_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with tag filter and specific status."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Item 1", "--actionable"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Item 2", "--actionable"]), settings)
    capsys.readouterr()

    cli._loop_update_command(parser.parse_args(["loop", "update", "1", "--tags", "work"]), settings)
    cli._loop_update_command(parser.parse_args(["loop", "update", "2", "--tags", "work"]), settings)
    cli._loop_status_command(parser.parse_args(["loop", "status", "1", "completed"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--tag", "work", "--status", "completed"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 1
    assert output[0]["status"] == "completed"


def test_loop_list_command_invalid_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with invalid status value."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Inbox item"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--status", "unknown"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "invalid status" in captured.err


def test_loop_list_command_table_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with table output format."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Item 1"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--format", "table"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "id" in captured.out
    assert "status" in captured.out


def test_loop_list_command_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop list command with limit and offset."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    for i in range(5):
        cli._capture_command(parser.parse_args(["capture", f"Item {i}"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "list", "--limit", "2", "--offset", "1"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 2


def test_loop_search_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test loop search command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Buy groceries"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Read book"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "search", "groceries"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output) == 1
    assert "groceries" in output[0]["raw_text"].lower()


def test_loop_update_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test loop update command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "update", "1", "--title", "New Title", "--next-action", "Do it"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["title"] == "New Title"
    assert output["next_action"] == "Do it"


def test_loop_update_command_no_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop update command with no fields."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli._loop_update_command(parser.parse_args(["loop", "update", "1"]), settings)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "no fields to update" in captured.err


def test_loop_update_command_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop update command with non-existent ID."""
    settings = _make_settings(tmp_path, monkeypatch)

    exit_code = cli._loop_update_command(
        cli.build_parser().parse_args(["loop", "update", "999", "--title", "Test"]), settings
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_loop_update_command_with_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop update command with tags."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "update", "1", "--tags", "work,urgent"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert set(output["tags"]) == {"work", "urgent"}


def test_loop_status_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test loop status command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "status", "1", "actionable"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "actionable"


def test_loop_status_command_invalid_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop status command with invalid status."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli._loop_status_command(
        parser.parse_args(["loop", "status", "1", "invalid_status"]), settings
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "invalid status" in captured.err


def test_loop_status_command_with_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop status command with completion note."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "status", "1", "completed", "--note", "All done!"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "completed"
    assert output["completion_note"] == "All done!"


def test_loop_status_command_transition_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop status command with invalid transition."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "status", "1", "inbox"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Invalid status transition" in captured.err


def test_loop_close_command_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop close command as completed."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "close", "1", "--note", "Done"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "completed"
    assert output["completion_note"] == "Done"


def test_loop_close_command_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop close command as dropped."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "close", "1", "--dropped", "--note", "No longer needed"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "dropped"


def test_loop_enrich_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test loop enrich command."""
    from unittest.mock import patch

    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    mock_response = (
        json.dumps(
            {
                "title": "Enriched Test",
                "summary": "Summarized test task",
                "next_action": "Do the test thing",
                "confidence": {
                    "title": 0.95,
                    "summary": 0.95,
                    "next_action": 0.95,
                },
                "needs_clarification": ["What is the deadline?"],
            }
        ),
        {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}},
    )

    with patch("cloop.loops.enrichment.chat_completion", return_value=mock_response):
        exit_code = cli.main(["loop", "enrich", "1"])

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["suggestion_id"] > 0
    assert output["needs_clarification"] == ["What is the deadline?"]
    assert output["applied_fields"] == []
    assert output["loop"]["id"] == 1
    assert output["loop"]["raw_text"] == "Test"
    assert output["loop"]["enrichment_state"] == "complete"


def test_loop_enrich_command_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop enrich command with non-existent ID."""
    settings = _make_settings(tmp_path, monkeypatch)

    exit_code = cli._loop_enrich_command(
        cli.build_parser().parse_args(["loop", "enrich", "999"]), settings
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_suggestion_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Suggestion CLI commands should review and resolve shared suggestion records."""
    from cloop.loops import repo

    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Review roadmap"]), settings)
    capsys.readouterr()

    with db.core_connection(settings) as conn:
        with conn:
            suggestion_id = repo.insert_loop_suggestion(
                loop_id=1,
                suggestion_json={
                    "title": "Roadmap review",
                    "confidence": {"title": 0.95},
                },
                model="mock-organizer",
                conn=conn,
            )
            rejected_suggestion_id = repo.insert_loop_suggestion(
                loop_id=1,
                suggestion_json={
                    "summary": "Stale summary",
                    "confidence": {"summary": 0.95},
                },
                model="mock-organizer",
                conn=conn,
            )

    exit_code = cli.main(["suggestion", "list", "--loop-id", "1"])
    assert exit_code == 0
    listed = _get_last_json(capsys)
    assert {item["id"] for item in listed} == {suggestion_id, rejected_suggestion_id}

    exit_code = cli.main(["suggestion", "show", str(suggestion_id)])
    assert exit_code == 0
    shown = _get_last_json(capsys)
    assert shown["parsed"]["title"] == "Roadmap review"

    exit_code = cli.main(["suggestion", "apply", str(suggestion_id)])
    assert exit_code == 0
    applied = _get_last_json(capsys)
    assert applied["loop"]["title"] == "Roadmap review"
    assert applied["resolution"] == "applied"

    exit_code = cli.main(["suggestion", "reject", str(rejected_suggestion_id)])
    assert exit_code == 0
    rejected = _get_last_json(capsys)
    assert rejected == {"suggestion_id": rejected_suggestion_id, "resolution": "rejected"}


def test_clarification_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    """Clarification CLI commands should list and answer existing clarification rows."""
    from cloop.loops import repo

    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Plan budget review"]), settings)
    capsys.readouterr()

    with db.core_connection(settings) as conn:
        with conn:
            first_suggestion_id = repo.insert_loop_suggestion(
                loop_id=1,
                suggestion_json={
                    "needs_clarification": ["What is the deadline?"],
                    "confidence": {},
                },
                model="mock-organizer",
                conn=conn,
            )
            first_clarification_id = repo.insert_loop_clarification(
                loop_id=1,
                question="What is the deadline?",
                conn=conn,
            )
            second_suggestion_id = repo.insert_loop_suggestion(
                loop_id=1,
                suggestion_json={
                    "needs_clarification": ["Who owns it?", "How much will it cost?"],
                    "confidence": {},
                },
                model="mock-organizer",
                conn=conn,
            )
            second_clarification_id = repo.insert_loop_clarification(
                loop_id=1,
                question="Who owns it?",
                conn=conn,
            )
            third_clarification_id = repo.insert_loop_clarification(
                loop_id=1,
                question="How much will it cost?",
                conn=conn,
            )

    exit_code = cli.main(["clarification", "list", "--loop-id", "1"])
    assert exit_code == 0
    listed = _get_last_json(capsys)
    assert {item["id"] for item in listed} == {
        first_clarification_id,
        second_clarification_id,
        third_clarification_id,
    }

    exit_code = cli.main(
        [
            "clarification",
            "answer",
            str(first_clarification_id),
            "--loop-id",
            "1",
            "--answer",
            "Friday",
        ]
    )
    assert exit_code == 0
    single = _get_last_json(capsys)
    assert single["answered_count"] == 1
    assert single["superseded_suggestion_ids"] == [first_suggestion_id]

    exit_code = cli.main(
        [
            "clarification",
            "answer-many",
            "--loop-id",
            "1",
            "--item",
            f"{second_clarification_id}=Finance",
            "--item",
            f"{third_clarification_id}=$500",
        ]
    )
    assert exit_code == 0
    batch = _get_last_json(capsys)
    assert batch["answered_count"] == 2
    assert batch["superseded_suggestion_ids"] == [second_suggestion_id]

    exit_code = cli.main(["suggestion", "list", "--loop-id", "1", "--pending"])
    assert exit_code == 0
    pending = _get_last_json(capsys)
    assert pending == []


def test_memory_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    """Memory CLI commands should reuse the shared direct-memory contract."""
    _make_settings(tmp_path, monkeypatch)

    exit_code = cli.main(
        [
            "memory",
            "create",
            "User prefers dark mode",
            "--key",
            "theme",
            "--category",
            "preference",
            "--priority",
            "45",
            "--metadata-json",
            '{"source_app":"cli"}',
        ]
    )
    assert exit_code == 0
    created = _get_last_json(capsys)
    entry_id = created["id"]
    assert created["key"] == "theme"
    assert created["category"] == "preference"
    assert created["metadata"] == {"source_app": "cli"}

    exit_code = cli.main(["memory", "list"])
    assert exit_code == 0
    listed = _get_last_json(capsys)
    assert listed["items"][0]["id"] == entry_id

    exit_code = cli.main(["memory", "search", "dark mode"])
    assert exit_code == 0
    searched = _get_last_json(capsys)
    assert searched["items"][0]["id"] == entry_id
    assert searched["query"] == "dark mode"

    exit_code = cli.main(
        [
            "memory",
            "update",
            str(entry_id),
            "--clear-key",
            "--content",
            "User prefers light mode now",
            "--priority",
            "60",
            "--metadata-json",
            '{"source_app":"cli","updated":true}',
        ]
    )
    assert exit_code == 0
    updated = _get_last_json(capsys)
    assert updated["key"] is None
    assert updated["content"] == "User prefers light mode now"
    assert updated["priority"] == 60

    exit_code = cli.main(["memory", "get", str(entry_id)])
    assert exit_code == 0
    fetched = _get_last_json(capsys)
    assert fetched["id"] == entry_id
    assert fetched["key"] is None

    exit_code = cli.main(["memory", "delete", str(entry_id)])
    assert exit_code == 0
    deleted = _get_last_json(capsys)
    assert deleted == {"entry_id": entry_id, "deleted": True}


def test_loop_snooze_command_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop snooze command with duration."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "snooze", "1", "2h"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["snooze_until_utc"] is not None


def test_loop_snooze_command_iso_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop snooze command with ISO timestamp."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    iso_ts = "2026-02-20T10:00:00+00:00"
    exit_code = cli.main(["loop", "snooze", "1", iso_ts])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["snooze_until_utc"] == iso_ts


def test_loop_snooze_command_invalid_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop snooze command with invalid duration."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli._loop_snooze_command(
        parser.parse_args(["loop", "snooze", "1", "invalid"]), settings
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "invalid duration" in captured.err


def test_tags_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test tags command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Test 2"]), settings)
    capsys.readouterr()

    cli._loop_update_command(
        parser.parse_args(["loop", "update", "1", "--tags", "work,urgent"]), settings
    )
    cli._loop_update_command(
        parser.parse_args(["loop", "update", "2", "--tags", "personal"]), settings
    )
    capsys.readouterr()

    exit_code = cli.main(["tags"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert set(output) == {"personal", "urgent", "work"}


def test_projects_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test projects command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Test 2"]), settings)
    capsys.readouterr()

    cli._loop_update_command(
        parser.parse_args(["loop", "update", "1", "--project", "Project A"]), settings
    )
    cli._loop_update_command(
        parser.parse_args(["loop", "update", "2", "--project", "Project B"]), settings
    )
    capsys.readouterr()

    exit_code = cli.main(["projects"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    project_names = {p["name"] for p in output}
    assert project_names == {"Project A", "Project B"}


def test_loop_get_claim_command_unclaimed_returns_structured_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Unclaimed loops should return a successful structured payload, not stderr text."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Unclaimed loop"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "get-claim", "1"])

    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output == {"loop_id": 1, "claimed": False}


def test_template_delete_command_emits_structured_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Template delete should follow the shared structured CLI output contract."""
    _make_settings(tmp_path, monkeypatch)

    create_exit = cli.main(
        [
            "template",
            "create",
            "Cleanup Template",
            "--pattern",
            "Template pattern",
        ]
    )
    assert create_exit == 0
    created = _get_last_json(capsys)

    delete_exit = cli.main(["template", "delete", str(created["id"])])

    assert delete_exit == 0
    deleted = _get_last_json(capsys)
    assert deleted["deleted"] is True
    assert deleted["id"] == created["id"]


def test_export_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test export command."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Loop 1"]), settings)
    cli._capture_command(parser.parse_args(["capture", "Loop 2", "--actionable"]), settings)
    capsys.readouterr()

    export_file = tmp_path / "export.json"
    exit_code = cli.main(["export", "--output", str(export_file)])
    assert exit_code == 0
    assert export_file.exists()

    data = json.loads(export_file.read_text())
    assert data["version"] == 1
    assert len(data["loops"]) == 2


def test_export_command_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test export command to stdout."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Loop 1"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["export"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["version"] == 1
    assert len(output["loops"]) == 1


def test_import_command_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test import command from file."""
    _make_settings(tmp_path, monkeypatch)

    export_data = {
        "version": 1,
        "loops": [
            {
                "raw_text": "Imported Loop 1",
                "status": "inbox",
                "captured_at_utc": "2026-02-13T10:00:00+00:00",
                "tags": ["work"],
            },
            {
                "raw_text": "Imported Loop 2",
                "status": "actionable",
                "captured_at_utc": "2026-02-13T11:00:00+00:00",
                "tags": ["personal"],
            },
        ],
    }

    import_file = tmp_path / "import.json"
    import_file.write_text(json.dumps(export_data))

    exit_code = cli.main(["import", "--file", str(import_file)])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["imported"] == 2


def test_import_command_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test import command from stdin."""
    settings = _make_settings(tmp_path, monkeypatch)

    export_data = {
        "version": 1,
        "loops": [
            {
                "raw_text": "Imported Loop",
                "status": "inbox",
                "captured_at_utc": "2026-02-13T10:00:00+00:00",
            }
        ],
    }

    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(export_data)))

    exit_code = cli._import_command(cli.build_parser().parse_args(["import"]), settings)
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["imported"] == 1


def test_import_command_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test import command with invalid JSON."""
    _make_settings(tmp_path, monkeypatch)

    import_file = tmp_path / "invalid.json"
    import_file.write_text("not json")

    exit_code = cli.main(["import", "--file", str(import_file)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "invalid JSON" in captured.err


def test_export_import_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test export -> import roundtrip preserves data."""
    # Create loops in primary database
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path / "primary"))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    cli.main(["capture", "Loop 1"])
    cli.main(["loop", "update", "1", "--title", "Test Title", "--tags", "work"])
    cli.main(["capture", "Loop 2", "--actionable"])
    capsys.readouterr()

    export_file = tmp_path / "roundtrip.json"
    exit_code = cli.main(["export", "--output", str(export_file)])
    assert exit_code == 0

    # Import into fresh database
    fresh_dir = tmp_path / "imported"
    fresh_dir.mkdir()
    monkeypatch.setenv("CLOOP_DATA_DIR", str(fresh_dir))
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["import", "--file", str(export_file)])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["imported"] == 2


def test_export_with_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test export command with filters."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    # Create loops
    cli.main(["capture", "inbox item"])
    cli.main(["capture", "actionable item", "--actionable"])
    capsys.readouterr()

    exit_code = cli.main(["export", "--status", "actionable"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert len(output["loops"]) == 1
    assert output["loops"][0]["status"] == "actionable"
    assert output["filtered"] is True


def test_import_dry_run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test import command with --dry-run flag."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    import_file = tmp_path / "import.json"
    import_file.write_text(
        json.dumps({"version": 1, "loops": [{"raw_text": "dry run test", "status": "inbox"}]})
    )

    exit_code = cli.main(["import", "--file", str(import_file), "--dry-run"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["dry_run"] is True
    assert output["imported"] == 0
    assert "preview" in output
    assert output["preview"]["would_create"] == 1


def test_import_conflict_policy_skip_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test import command with --conflict-policy skip."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    # Create existing loop
    cli.main(["capture", "existing task"])
    capsys.readouterr()

    import_file = tmp_path / "import.json"
    import_file.write_text(
        json.dumps(
            {
                "version": 1,
                "loops": [
                    {"raw_text": "existing task", "status": "actionable"},
                    {"raw_text": "new task", "status": "inbox"},
                ],
            }
        )
    )

    exit_code = cli.main(["import", "--file", str(import_file), "--conflict-policy", "skip"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["skipped"] == 1
    assert output["imported"] == 1


# =============================================================================
# End-to-End Workflow Tests
# =============================================================================


def test_capture_update_close_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test full capture -> update -> close workflow via main()."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["capture", "Buy groceries", "--actionable"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "actionable"
    loop_id = output["id"]

    exit_code = cli.main(
        [
            "loop",
            "update",
            str(loop_id),
            "--next-action",
            "Go to store",
            "--due-at",
            "2026-02-15T18:00:00Z",
        ]
    )
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["next_action"] == "Go to store"

    exit_code = cli.main(["loop", "close", str(loop_id), "--note", "Done"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["status"] == "completed"
    assert output["completion_note"] == "Done"


def test_capture_snooze_get_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture -> snooze -> get workflow via main()."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["capture", "Review PR", "--actionable"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    loop_id = output["id"]

    exit_code = cli.main(["loop", "snooze", str(loop_id), "1h"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["snooze_until_utc"] is not None

    exit_code = cli.main(["loop", "get", str(loop_id)])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["snooze_until_utc"] is not None


def test_full_lifecycle_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test complete lifecycle: capture -> list -> update -> status -> close."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())

    exit_code = cli.main(["capture", "Task 1"])
    assert exit_code == 0
    loop1 = _get_last_json(capsys)

    exit_code = cli.main(["capture", "Task 2", "--actionable"])
    assert exit_code == 0
    loop2 = _get_last_json(capsys)

    exit_code = cli.main(["loop", "list", "--status", "open"])
    assert exit_code == 0
    loops = _get_last_json(capsys)
    assert len(loops) == 2

    exit_code = cli.main(["loop", "status", str(loop1["id"]), "actionable"])
    assert exit_code == 0

    exit_code = cli.main(["loop", "update", str(loop2["id"]), "--title", "Updated Task 2"])
    assert exit_code == 0

    exit_code = cli.main(["loop", "search", "Task"])
    assert exit_code == 0
    results = _get_last_json(capsys)
    assert len(results) == 2

    exit_code = cli.main(["loop", "close", str(loop1["id"])])
    assert exit_code == 0

    exit_code = cli.main(["loop", "close", str(loop2["id"]), "--dropped"])
    assert exit_code == 0

    exit_code = cli.main(["loop", "list", "--status", "completed"])
    assert exit_code == 0
    completed = _get_last_json(capsys)
    assert len(completed) == 1

    exit_code = cli.main(["loop", "list", "--status", "dropped"])
    assert exit_code == 0
    dropped = _get_last_json(capsys)
    assert len(dropped) == 1


def test_subprocess_cli_lifecycle_and_export_import_roundtrip(tmp_path: Path) -> None:
    """Test end-to-end lifecycle and export/import using subprocess CLI calls."""
    primary_data_dir = tmp_path / "primary"
    primary_data_dir.mkdir()

    capture_result = _run_cli_subprocess(
        primary_data_dir, "capture", "Subprocess task", "--actionable"
    )
    assert capture_result.returncode == 0
    captured_loop = json.loads(capture_result.stdout)
    loop_id = str(captured_loop["id"])

    update_result = _run_cli_subprocess(
        primary_data_dir,
        "loop",
        "update",
        loop_id,
        "--next-action",
        "Finish subprocess workflow",
        "--tags",
        "subprocess,regression",
    )
    assert update_result.returncode == 0

    close_result = _run_cli_subprocess(
        primary_data_dir,
        "loop",
        "close",
        loop_id,
        "--note",
        "Completed in subprocess",
    )
    assert close_result.returncode == 0
    closed_loop = json.loads(close_result.stdout)
    assert closed_loop["status"] == "completed"

    export_file = tmp_path / "subprocess-export.json"
    export_result = _run_cli_subprocess(primary_data_dir, "export", "--output", str(export_file))
    assert export_result.returncode == 0
    assert export_file.exists()

    imported_data_dir = tmp_path / "imported"
    imported_data_dir.mkdir()
    import_result = _run_cli_subprocess(imported_data_dir, "import", "--file", str(export_file))
    assert import_result.returncode == 0
    import_payload = json.loads(import_result.stdout)
    assert import_payload["imported"] == 1

    list_result = _run_cli_subprocess(imported_data_dir, "loop", "list", "--status", "all")
    assert list_result.returncode == 0
    imported_loops = json.loads(list_result.stdout)
    assert len(imported_loops) == 1
    assert imported_loops[0]["raw_text"] == "Subprocess task"


# =============================================================================
# Review Cohort CLI Tests
# =============================================================================


def test_loop_review_command_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop review command with default (daily) cohorts."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    # Create actionable loop without next_action
    cli._capture_command(parser.parse_args(["capture", "Test task", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "review"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert "generated_at_utc" in output
    assert "daily" in output
    # Check that at least no_next_action cohort exists
    cohort_names = {c["cohort"] for c in output["daily"]}
    assert "no_next_action" in cohort_names


def test_loop_review_command_weekly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop review command with --weekly flag."""
    _make_settings(tmp_path, monkeypatch)

    exit_code = cli.main(["loop", "review", "--weekly"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert "weekly" in output
    # Weekly should only have stale and blocked_too_long
    cohort_names = {c["cohort"] for c in output.get("weekly", [])}
    assert "no_next_action" not in cohort_names
    assert "due_soon_unplanned" not in cohort_names


def test_loop_review_command_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop review command with --all flag includes both daily and weekly."""
    _make_settings(tmp_path, monkeypatch)

    exit_code = cli.main(["loop", "review", "--all"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert "daily" in output
    assert "weekly" in output


def test_loop_review_command_cohort_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop review command with --cohort filter."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    # Create actionable loop without next_action
    cli._capture_command(parser.parse_args(["capture", "Test task", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "review", "--cohort", "no_next_action"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    # Should only have no_next_action cohort
    for cohort_list in [output.get("daily", []), output.get("weekly", [])]:
        for cohort in cohort_list:
            assert cohort["cohort"] == "no_next_action"


def test_loop_review_command_with_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop review command respects --limit."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    # Create multiple actionable loops without next_action
    for i in range(5):
        cli._capture_command(parser.parse_args(["capture", f"Task {i}", "--actionable"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "review", "--limit", "2"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    # Check that no cohort has more than 2 items
    for cohort_list in [output.get("daily", []), output.get("weekly", [])]:
        for cohort in cohort_list:
            assert len(cohort["items"]) <= 2


def test_loop_review_command_table_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test loop review command with table output format."""
    _make_settings(tmp_path, monkeypatch)

    exit_code = cli.main(["loop", "review", "--format", "table"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "generated_at_utc" in captured.out


def test_capture_with_due_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with --due flag."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Task with due date", "--due", "2026-04-15"])
    exit_code = cli._capture_command(args, settings)
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["due_at_utc"] is not None


def test_capture_with_multiple_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with multiple --tag flags."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Tagged task", "--tag", "urgent", "--tag", "work"])
    exit_code = cli._capture_command(args, settings)
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert set(output["tags"]) == {"urgent", "work"}


def test_capture_with_all_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test capture with all rich metadata flags."""
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "capture",
            "Complete task",
            "--due",
            "2026-04-15T17:00:00",
            "--next-action",
            "Start here",
            "--time",
            "60",
            "--effort",
            "2",
            "--project",
            "work",
            "--tag",
            "urgent",
        ]
    )
    exit_code = cli._capture_command(args, settings)
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["next_action"] == "Start here"
    assert output["time_minutes"] == 60
    assert output["activation_energy"] == 2
    assert output["project"] == "work"
