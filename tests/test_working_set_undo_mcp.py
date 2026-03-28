"""MCP tests for working-set tools.

Purpose:
    Verify the working-set MCP tools reuse the shared working-set and exact-
    handle undo contracts without transport-specific drift.

Responsibilities:
    - Exercise working-set CRUD, context, membership, and undo through the
      direct MCP tool wrappers
    - Assert MCP payloads match the shared service output shape
    - Keep regression coverage for MCP working-set tool wiring

Scope:
    - MCP-level working-set tool verification only

Usage:
    - Run `uv run --locked pytest tests/test_working_set_undo_mcp.py -q`

Invariants/Assumptions:
    - Tests use isolated temporary SQLite databases
    - MCP mutation retries should be handled by the shared idempotent mutation helper
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloop import db
from cloop.loops import working_sets
from cloop.mcp_tools.working_set_tools import (
    working_set_add_item,
    working_set_context_get,
    working_set_context_update,
    working_set_create,
    working_set_delete,
    working_set_get,
    working_set_list,
    working_set_remove_item,
    working_set_reorder,
    working_set_undo,
    working_set_update,
)
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


def test_working_set_mcp_tools_cover_shared_crud_and_context_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_test_db(tmp_path, monkeypatch)

    created = working_set_create(
        name="MCP working set",
        description="Preserve this description when renaming.",
        request_id="mcp-working-set-create",
    )
    assert created["launch"]["state"] == "working_set"

    listed = working_set_list()
    assert [item["id"] for item in listed] == [created["id"]]

    renamed = working_set_update(
        working_set_id=int(created["id"]),
        name="MCP working set renamed",
        request_id="mcp-working-set-update",
    )
    assert renamed["name"] == "MCP working set renamed"
    assert renamed["description"] == "Preserve this description when renaming."

    fetched = working_set_get(int(created["id"]))
    assert fetched["name"] == "MCP working set renamed"

    with_item = working_set_add_item(
        working_set_id=int(created["id"]),
        item_type="state_anchor",
        label="Resume session",
        description="Open the dedicated working-set session.",
        metadata={"state": "working_set", "working_set_id": int(created["id"])},
        request_id="mcp-working-set-add-item",
    )
    assert with_item["item_count"] == 1
    assert with_item["items"][0]["launch"]["state"] == "working_set"

    reordered = working_set_reorder(
        working_set_id=int(created["id"]),
        ordered_item_ids=[int(with_item["items"][0]["id"])],
        request_id="mcp-working-set-reorder",
    )
    assert reordered["items"][0]["label"] == "Resume session"

    context = working_set_context_update(
        active_working_set_id=int(created["id"]),
        focus_mode_enabled=True,
        request_id="mcp-working-set-context-update",
    )
    assert context["active_working_set_id"] == created["id"]
    assert context["focus_mode_enabled"] is True

    fetched_context = working_set_context_get()
    assert fetched_context["active_working_set"]["name"] == "MCP working set renamed"

    removed = working_set_remove_item(
        working_set_id=int(created["id"]),
        item_id=int(with_item["items"][0]["id"]),
        request_id="mcp-working-set-remove-item",
    )
    assert removed["items"] == []

    deleted = working_set_delete(
        working_set_id=int(created["id"]),
        request_id="mcp-working-set-delete",
    )
    assert deleted["deleted"] is True
    assert deleted["deleted_working_set_name"] == "MCP working set renamed"
    assert deleted["context"]["active_working_set_id"] is None


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
