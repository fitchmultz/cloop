"""CLI tests for working-set undo.

Purpose:
    Verify the public `cloop working-set undo` command reuses the shared
    exact-handle working-set undo contract.

Responsibilities:
    - Exercise working-set undo through the packaged CLI entrypoint
    - Assert CLI output returns the restored working-set payload
    - Keep regression coverage for top-level working-set parser/dispatch wiring

Scope:
    - CLI-level working-set undo verification only

Usage:
    - Run `uv run --locked pytest tests/test_working_set_undo_cli.py -q`

Invariants/Assumptions:
    - Tests use isolated temporary SQLite databases
    - Working-set undo requires an explicit latest reversible event handle
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cloop import db
from cloop.cli_package.main import main
from cloop.loops import working_sets
from cloop.settings import Settings, get_settings


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
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


def test_working_set_undo_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    settings = _make_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        created = working_sets.create_working_set(
            name="CLI working set",
            description="Undo this through the CLI.",
            conn=conn,
        )
        updated = working_sets.update_working_set(
            working_set_id=int(created["id"]),
            name="CLI working set renamed",
            conn=conn,
        )
        assert updated["latest_reversible_event_id"] is not None
        conn.commit()

    event_id = int(updated["latest_reversible_event_id"])
    assert main(["working-set", "undo", "--event-id", str(event_id)]) == 0

    payload = _last_json(capsys)
    assert payload["undone_event_id"] == event_id
    assert payload["working_set"]["name"] == "CLI working set"
    assert payload["summary"]
