"""CLI tests for working-set commands.

Purpose:
    Verify the public `cloop working-set` commands reuse the shared working-set
    CRUD/context contract plus exact-handle undo behavior.

Responsibilities:
    - Exercise working-set CRUD, context, membership, and undo through the
      packaged CLI entrypoint
    - Assert CLI output returns the shared working-set payload shapes
    - Keep regression coverage for top-level working-set parser/dispatch wiring

Scope:
    - CLI-level working-set command verification only

Usage:
    - Run `uv run --locked --all-groups pytest tests/test_working_set_undo_cli.py -q`

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
from cloop.settings import Settings, get_settings
from tests.helpers import last_json_from_stdout


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def test_working_set_cli_crud_context_and_undo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    _make_settings(tmp_path, monkeypatch)

    assert (
        main(
            [
                "working-set",
                "create",
                "--name",
                "CLI working set",
                "--description",
                "Undo this through the CLI.",
            ]
        )
        == 0
    )
    created = last_json_from_stdout(capsys)
    working_set_id = int(created["id"])
    assert created["launch"]["state"] == "working_set"

    assert main(["working-set", "list"]) == 0
    listed = last_json_from_stdout(capsys)
    assert [item["id"] for item in listed] == [working_set_id]

    assert main(["working-set", "get", str(working_set_id)]) == 0
    fetched = last_json_from_stdout(capsys)
    assert fetched["name"] == "CLI working set"

    assert (
        main(
            [
                "working-set",
                "add-items-bulk",
                "--working-set",
                str(working_set_id),
                "--items-json",
                json.dumps(
                    [
                        {
                            "item_type": "state_anchor",
                            "label": "Resume session",
                            "description": "Open the dedicated working-set session.",
                            "metadata": {"state": "working_set", "working_set_id": working_set_id},
                        },
                        {
                            "item_type": "state_anchor",
                            "label": "Return home",
                            "description": "Return to the operator workspace.",
                            "metadata": {"state": "operator"},
                        },
                    ]
                ),
            ]
        )
        == 0
    )
    with_items = last_json_from_stdout(capsys)
    first_item_id = int(with_items["items"][0]["id"])
    second_item_id = int(with_items["items"][1]["id"])
    assert with_items["item_count"] == 2

    assert (
        main(
            [
                "working-set",
                "reorder",
                "--working-set",
                str(working_set_id),
                "--item-id",
                str(second_item_id),
                "--item-id",
                str(first_item_id),
            ]
        )
        == 0
    )
    reordered = last_json_from_stdout(capsys)
    assert [item["id"] for item in reordered["items"]] == [second_item_id, first_item_id]

    assert (
        main(
            [
                "working-set",
                "context",
                "update",
                "--focus-mode",
                "on",
                "--active-working-set-id",
                str(working_set_id),
            ]
        )
        == 0
    )
    context = last_json_from_stdout(capsys)
    assert context["active_working_set_id"] == working_set_id
    assert context["focus_mode_enabled"] is True

    assert main(["working-set", "context", "get"]) == 0
    fetched_context = last_json_from_stdout(capsys)
    assert fetched_context["active_working_set"]["id"] == working_set_id

    assert (
        main(["working-set", "update", str(working_set_id), "--name", "CLI working set renamed"])
        == 0
    )
    updated = last_json_from_stdout(capsys)
    assert updated["name"] == "CLI working set renamed"
    event_id = int(updated["latest_reversible_event_id"])

    assert main(["working-set", "undo", "--event-id", str(event_id)]) == 0
    undone = last_json_from_stdout(capsys)
    assert undone["undone_event_id"] == event_id
    assert undone["working_set"]["name"] == "CLI working set"
    assert undone["summary"]

    assert (
        main(
            [
                "working-set",
                "remove-item",
                "--working-set",
                str(working_set_id),
                "--item-id",
                str(first_item_id),
            ]
        )
        == 0
    )
    removed = last_json_from_stdout(capsys)
    assert removed["item_count"] == 1

    assert main(["working-set", "delete", str(working_set_id)]) == 0
    deleted = last_json_from_stdout(capsys)
    assert deleted["deleted"] is True
    assert deleted["deleted_working_set_id"] == working_set_id
