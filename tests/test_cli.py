"""Tests for the CLI module."""

import json
import sqlite3
from pathlib import Path
from typing import Any, List

import numpy as np
import pytest

from cloop import cli, db
from cloop.loops.models import LoopStatus
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

    # Mock at rag module level since that's where embed_texts is imported and used
    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)


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
    status = LoopStatus.INBOX
    if args.scheduled:
        status = LoopStatus.SCHEDULED
    elif args.blocked:
        status = LoopStatus.BLOCKED
    elif args.actionable:
        status = LoopStatus.ACTIONABLE
    assert status == LoopStatus.SCHEDULED

    # Test blocked vs actionable - blocked wins
    args = parser.parse_args(["capture", "test", "--actionable", "--blocked"])
    status = LoopStatus.INBOX
    if args.scheduled:
        status = LoopStatus.SCHEDULED
    elif args.blocked:
        status = LoopStatus.BLOCKED
    elif args.actionable:
        status = LoopStatus.ACTIONABLE
    assert status == LoopStatus.BLOCKED

    # Test actionable only
    args = parser.parse_args(["capture", "test", "--actionable"])
    status = LoopStatus.INBOX
    if args.scheduled:
        status = LoopStatus.SCHEDULED
    elif args.blocked:
        status = LoopStatus.BLOCKED
    elif args.actionable:
        status = LoopStatus.ACTIONABLE
    assert status == LoopStatus.ACTIONABLE

    # Test default (no flags)
    args = parser.parse_args(["capture", "test"])
    status = LoopStatus.INBOX
    if args.scheduled:
        status = LoopStatus.SCHEDULED
    elif args.blocked:
        status = LoopStatus.BLOCKED
    elif args.actionable:
        status = LoopStatus.ACTIONABLE
    assert status == LoopStatus.INBOX


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

    # Empty question is still a valid question string
    exit_code = cli.main(["ask", ""])

    assert exit_code == 1  # No knowledge available
