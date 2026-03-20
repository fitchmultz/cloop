"""MCP tests for working-set undo.

Purpose:
    Verify the working-set MCP tool exposes the shared exact-handle undo
    contract without transport-specific drift.

Responsibilities:
    - Exercise `working_set.undo` through the direct MCP tool wrapper
    - Assert the restored working-set payload matches the shared service output
    - Keep regression coverage for MCP tool registration wiring

Scope:
    - MCP-level working-set undo verification only

Usage:
    - Run `uv run --locked pytest tests/test_working_set_undo_mcp.py -q`

Invariants/Assumptions:
    - Tests use isolated temporary SQLite databases
    - MCP undo retries should be handled by the shared idempotent mutation helper
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloop import db
from cloop.loops import working_sets
from cloop.mcp_tools.working_set_tools import working_set_undo
from cloop.settings import Settings, get_settings


def _setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_TTL_SECONDS", "86400")
    monkeypatch.setenv("CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH", "255")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def test_working_set_undo_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_test_db(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        created = working_sets.create_working_set(
            name="MCP working set",
            description="Undo this through MCP.",
            conn=conn,
        )
        updated = working_sets.update_working_set(
            working_set_id=int(created["id"]),
            name="MCP working set renamed",
            conn=conn,
        )
        assert updated["latest_reversible_event_id"] is not None
        conn.commit()

    payload = working_set_undo(expected_event_id=int(updated["latest_reversible_event_id"]))
    assert payload["undone_event_type"] == "update"
    assert payload["working_set"]["name"] == "MCP working set"
    assert payload["summary"]
