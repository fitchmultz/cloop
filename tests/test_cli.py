"""Tests for the CLI module."""

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, List

import numpy as np
import pytest

from cloop import cli, db
from cloop.loops.models import LoopStatus, resolve_status_from_flags
from cloop.settings import Settings, get_settings


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create isolated settings with temp database."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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


def _run_cli_subprocess(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run CLI in a subprocess with isolated test settings."""
    env = os.environ.copy()
    env["CLOOP_DATA_DIR"] = str(tmp_path)
    env["CLOOP_AUTOPILOT_ENABLED"] = "false"
    env["CLOOP_LLM_MODEL"] = "mock-llm"
    env["CLOOP_EMBED_MODEL"] = "mock-embed"
    return subprocess.run(
        ["uv", "run", "python", "-m", "cloop.cli", *args],
        check=False,
        capture_output=True,
        text=True,
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
    """Test ask command with ingested documents."""
    settings = _make_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

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
    assert "question" in output
    assert "chunks" in output
    assert len(output["chunks"]) > 0
    # Verify embedding_blob is stripped
    for chunk in output["chunks"]:
        assert "embedding_blob" not in chunk


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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_ORGANIZER_MODEL", "mock-organizer")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    # Mock the request_enrichment function to avoid actual LLM calls
    mock_enrichment = {"id": 1, "title": "Enriched Loop", "status": "inbox"}

    def mock_request_enrichment(*, loop_id: int, conn: sqlite3.Connection) -> dict:
        return mock_enrichment

    monkeypatch.setattr("cloop.cli.request_enrichment", mock_request_enrichment)

    parser = cli.build_parser()
    args = parser.parse_args(["capture", "Test autopilot"])

    exit_code = cli._capture_command(args, settings)

    assert exit_code == 0
    output = _get_last_json(capsys)
    # With autopilot, it returns the enriched record
    assert output == mock_enrichment


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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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


def test_main_capture_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test main() with capture command."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Test"]), settings)
    capsys.readouterr()

    exit_code = cli.main(["loop", "enrich", "1"])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["enrichment_state"] == "pending"


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
    settings = _make_settings(tmp_path, monkeypatch)
    parser = cli.build_parser()

    cli._capture_command(parser.parse_args(["capture", "Loop 1"]), settings)
    cli._loop_update_command(
        parser.parse_args(["loop", "update", "1", "--title", "Test Title", "--tags", "work"]),
        settings,
    )
    cli._capture_command(parser.parse_args(["capture", "Loop 2", "--actionable"]), settings)
    capsys.readouterr()

    export_file = tmp_path / "roundtrip.json"
    exit_code = cli.main(["export", "--output", str(export_file)])
    assert exit_code == 0

    exit_code = cli.main(["import", "--file", str(export_file)])
    assert exit_code == 0
    output = _get_last_json(capsys)
    assert output["imported"] == 2


# =============================================================================
# End-to-End Workflow Tests
# =============================================================================


def test_capture_update_close_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test full capture -> update -> close workflow via main()."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
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
