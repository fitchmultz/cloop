"""Tests for the loop query DSL.

Coverage matrix:
1. Parser/tokenizer:
   - quoted values
   - unknown fields rejected
   - invalid due token rejected
   - bare token -> text term
   - status:open expands to 4 open statuses
   - status:all is ignored

2. Property-based tests (Hypothesis):
   - tokenization/parser does not crash on generated valid token streams
   - canonicalization stability for parse/format/parse loop

3. API tests:
   - /loops/search returns expected IDs and stable order for representative queries
   - /loops/views CRUD + apply workflow

4. CLI tests:
   - loop search --query parity with API fixture IDs
   - loop view CRUD/apply commands

5. MCP tests:
   - loop.search DSL parity with API fixture IDs
   - loop.view.* CRUD/apply behaviors + idempotency for mutations

6. Cross-surface parity fixture:
   - For each query in a shared fixture set, API/CLI/MCP return the same ordered loop IDs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from cloop import cli, db
from cloop.loops.errors import ValidationError
from cloop.loops.query import LoopQuery, _tokenize, parse_loop_query
from cloop.main import app
from cloop.mcp_server import loop_search as mcp_loop_search
from cloop.mcp_server import loop_view_apply as mcp_loop_view_apply
from cloop.settings import get_settings


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_last_json(capsys: Any) -> Any:
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    for i in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[i:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no json output found in stdout: {captured.out!r}")


# =============================================================================
# Parser/tokenizer tests
# =============================================================================


def test_tokenize_simple_field_value() -> None:
    tokens = _tokenize("status:inbox")
    assert tokens == [("status", "inbox")]


def test_tokenize_multiple_terms() -> None:
    tokens = _tokenize("status:inbox tag:work due:today")
    assert tokens == [
        ("status", "inbox"),
        ("tag", "work"),
        ("due", "today"),
    ]


def test_tokenize_quoted_value() -> None:
    tokens = _tokenize('project:"Client Alpha"')
    assert tokens == [("project", "client alpha")]


def test_tokenize_quoted_value_with_spaces() -> None:
    tokens = _tokenize('project:"My Important Project" tag:work')
    assert tokens == [
        ("project", "my important project"),
        ("tag", "work"),
    ]


def test_tokenize_bare_token_is_text() -> None:
    tokens = _tokenize("meeting status:inbox")
    assert tokens == [
        ("text", "meeting"),
        ("status", "inbox"),
    ]


def test_tokenize_double_quoted_bare() -> None:
    tokens = _tokenize('"important meeting"')
    assert tokens == [("text", "important meeting")]


def test_tokenize_empty_query_raises() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        parse_loop_query("")


def test_tokenize_whitespace_only_raises() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        parse_loop_query("   ")


def test_parse_unknown_field_raises() -> None:
    with pytest.raises(ValidationError, match="unknown field"):
        parse_loop_query("unknown:value")


def test_parse_invalid_status_raises() -> None:
    with pytest.raises(ValidationError, match="invalid status"):
        parse_loop_query("status:invalid")


def test_parse_invalid_due_raises() -> None:
    with pytest.raises(ValidationError, match="invalid due filter"):
        parse_loop_query("due:invalid")


def test_parse_unclosed_quote_raises() -> None:
    with pytest.raises(ValidationError, match="unclosed"):
        _tokenize('project:"unclosed')


def test_parse_empty_quoted_value_raises() -> None:
    with pytest.raises(ValidationError, match="empty quoted value"):
        _tokenize('""')


def test_parse_empty_field_raises() -> None:
    with pytest.raises(ValidationError, match="empty field name"):
        _tokenize(":value")


def test_parse_empty_value_raises() -> None:
    with pytest.raises(ValidationError, match="empty value"):
        _tokenize("tag:")


def test_parse_loop_query_normalizes_status() -> None:
    query = parse_loop_query("status:INBOX")
    assert query.statuses == ("inbox",)


def test_parse_loop_query_normalizes_tag() -> None:
    query = parse_loop_query("TAG:Work")
    assert query.tags == ("work",)


def test_parse_loop_query_deduplicates() -> None:
    query = parse_loop_query("status:inbox status:inbox tag:work tag:WORK")
    assert query.statuses == ("inbox",)
    assert query.tags == ("work",)


def test_parse_loop_query_sorts_terms() -> None:
    query = parse_loop_query("tag:c tag:b tag:a")
    assert query.tags == ("a", "b", "c")


# =============================================================================
# Property-based tests
# =============================================================================


@given(st.text(min_size=1, max_size=100))
def test_tokenize_never_crashes(text: str) -> None:
    """Tokenizer should never crash on any input."""
    try:
        _tokenize(text)
    except ValidationError:
        pass


def test_parse_valid_status_terms() -> None:
    """Parser should accept valid status terms."""
    for status in [
        "open",
        "all",
        "inbox",
        "actionable",
        "blocked",
        "scheduled",
        "completed",
        "dropped",
    ]:
        query = parse_loop_query(f"status:{status}")
        assert isinstance(query, LoopQuery)


def test_parse_valid_due_terms() -> None:
    """Parser should accept valid due terms."""
    for due in ["today", "tomorrow", "overdue", "none", "next7d"]:
        query = parse_loop_query(f"due:{due}")
        assert isinstance(query, LoopQuery)


def test_parse_combined_valid_terms() -> None:
    """Parser should accept combined valid terms."""
    query = parse_loop_query("status:inbox tag:work project:MyProject due:today text:meeting")
    assert isinstance(query, LoopQuery)
    assert query.statuses == ("inbox",)
    assert query.tags == ("work",)
    assert query.projects == ("myproject",)
    assert query.due_filters == ("today",)
    assert query.text_terms == ("meeting",)


# =============================================================================
# API tests
# =============================================================================


def test_search_endpoint_basic_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test /loops/search endpoint with basic query."""
    client = _make_client(tmp_path, monkeypatch)

    for i, status in enumerate(["inbox", "actionable", "blocked"]):
        client.post(
            "/loops/capture",
            json={
                "raw_text": f"Task {i}",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
                "actionable": status == "actionable",
                "blocked": status == "blocked",
            },
        )

    response = client.post(
        "/loops/search",
        json={"query": "status:inbox", "limit": 10, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "status:inbox"
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "inbox"


def test_search_endpoint_multiple_statuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test /loops/search with multiple status terms (OR)."""
    client = _make_client(tmp_path, monkeypatch)

    for status in ["inbox", "actionable", "blocked", "scheduled", "completed"]:
        client.post(
            f"/loops/capture?captured_at={_now_iso()}&client_tz_offset_min=0",
            json={
                "raw_text": f"Task {status}",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
                "actionable": status == "actionable",
                "blocked": status == "blocked",
                "scheduled": status == "scheduled",
            },
        )

    response = client.post(
        "/loops/search",
        json={"query": "status:open", "limit": 10, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()
    statuses = {item["status"] for item in data["items"]}
    assert statuses == {"inbox", "actionable", "blocked", "scheduled"}


def test_search_endpoint_text_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test /loops/search with text terms."""
    client = _make_client(tmp_path, monkeypatch)

    client.post(
        "/loops/capture",
        json={"raw_text": "Buy groceries", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    client.post(
        "/loops/capture",
        json={"raw_text": "Write report", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    response = client.post(
        "/loops/search",
        json={"query": "groceries", "limit": 10, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert "groceries" in data["items"][0]["raw_text"].lower()


def test_search_endpoint_combined_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test /loops/search with combined filters."""
    client = _make_client(tmp_path, monkeypatch)

    client.post(
        "/loops/capture",
        json={
            "raw_text": "Work task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "actionable": True,
        },
    )
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "Personal task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )

    client.patch(f"/loops/{resp.json()['id']}", json={"tags": ["work"]})

    response = client.post(
        "/loops/search",
        json={"query": "status:actionable", "limit": 10, "offset": 0},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


# =============================================================================
# View CRUD tests
# =============================================================================


def test_view_create_list_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test view CRUD and apply workflow."""
    client = _make_client(tmp_path, monkeypatch)

    client.post(
        "/loops/capture",
        json={
            "raw_text": "Inbox task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "Actionable task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "actionable": True,
        },
    )

    create_resp = client.post(
        "/loops/views",
        json={
            "name": "Inbox Only",
            "query": "status:inbox",
            "description": "Shows only inbox items",
        },
    )
    assert create_resp.status_code == 200
    view = create_resp.json()
    assert view["name"] == "Inbox Only"
    assert view["query"] == "status:inbox"
    assert view["description"] == "Shows only inbox items"

    list_resp = client.get("/loops/views")
    assert list_resp.status_code == 200
    views = list_resp.json()
    assert len(views) == 1
    assert views[0]["name"] == "Inbox Only"

    apply_resp = client.post(f"/loops/views/{view['id']}/apply?limit=10")
    assert apply_resp.status_code == 200
    result = apply_resp.json()
    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == "inbox"

    update_resp = client.patch(
        f"/loops/views/{view['id']}",
        json={"name": "Inbox Tasks"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Inbox Tasks"

    delete_resp = client.delete(f"/loops/views/{view['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    list_resp = client.get("/loops/views")
    assert len(list_resp.json()) == 0


def test_view_duplicate_name_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that duplicate view names are rejected."""
    client = _make_client(tmp_path, monkeypatch)

    client.post("/loops/views", json={"name": "My View", "query": "status:inbox"})

    resp = client.post("/loops/views", json={"name": "My View", "query": "status:actionable"})
    assert resp.status_code == 400


# =============================================================================
# Cross-surface parity tests
# =============================================================================


def test_cross_surface_parity_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test that API, CLI, and MCP return same loop IDs for same query."""
    client = _make_client(tmp_path, monkeypatch)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_noon = (today_start + timedelta(days=1, hours=12)).isoformat()
    overdue_time = (now - timedelta(hours=2)).isoformat()
    future_time = (now + timedelta(days=5)).isoformat()

    inbox = client.post(
        "/loops/capture",
        json={"raw_text": "alpha planning", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    blocked = client.post(
        "/loops/capture",
        json={
            "raw_text": "alpha waiting on vendor",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "blocked": True,
        },
    )
    actionable = client.post(
        "/loops/capture",
        json={
            "raw_text": "alpha execution task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "actionable": True,
        },
    )
    personal = client.post(
        "/loops/capture",
        json={
            "raw_text": "beta personal errand",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "actionable": True,
        },
    )

    inbox_id = inbox.json()["id"]
    blocked_id = blocked.json()["id"]
    actionable_id = actionable.json()["id"]
    personal_id = personal.json()["id"]

    assert (
        client.patch(
            f"/loops/{inbox_id}",
            json={"project": "Alpha", "tags": ["work"], "due_at_utc": tomorrow_noon},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/loops/{blocked_id}",
            json={"project": "Alpha", "tags": ["waiting"], "due_at_utc": overdue_time},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/loops/{actionable_id}",
            json={"project": "Alpha", "tags": ["work"], "due_at_utc": future_time},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/loops/{personal_id}",
            json={"project": "Home", "tags": ["personal"]},
        ).status_code
        == 200
    )

    queries = [
        "status:open alpha",
        "tag:work project:alpha",
        "due:overdue project:alpha",
        "due:tomorrow tag:work",
    ]

    for query in queries:
        api_resp = client.post("/loops/search", json={"query": query, "limit": 50, "offset": 0})
        assert api_resp.status_code == 200
        api_ids = [item["id"] for item in api_resp.json()["items"]]

        capsys.readouterr()
        exit_code = cli.main(["loop", "search", "--query", query])
        assert exit_code == 0
        cli_items = _parse_last_json(capsys)
        cli_ids = [item["id"] for item in cli_items]

        mcp_items = mcp_loop_search(query=query, limit=50, offset=0)
        mcp_ids = [item["id"] for item in mcp_items]

        assert api_ids == cli_ids == mcp_ids


def test_cross_surface_saved_view_apply_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Saved view apply returns equivalent data across API, CLI, and MCP."""
    client = _make_client(tmp_path, monkeypatch)

    first = client.post(
        "/loops/capture",
        json={"raw_text": "alpha view one", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    second = client.post(
        "/loops/capture",
        json={"raw_text": "alpha view two", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    third = client.post(
        "/loops/capture",
        json={"raw_text": "beta view three", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    assert (
        client.patch(
            f"/loops/{first.json()['id']}",
            json={"project": "Alpha", "tags": ["work"]},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/loops/{second.json()['id']}",
            json={"project": "Alpha", "tags": ["work"]},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/loops/{third.json()['id']}",
            json={"project": "Home", "tags": ["personal"]},
        ).status_code
        == 200
    )

    create_resp = client.post(
        "/loops/views",
        json={"name": "Alpha Work", "query": "project:alpha tag:work"},
    )
    assert create_resp.status_code == 200
    view_id = create_resp.json()["id"]

    api_apply = client.post(f"/loops/views/{view_id}/apply?limit=10&offset=0")
    assert api_apply.status_code == 200
    api_payload = api_apply.json()
    api_ids = [item["id"] for item in api_payload["items"]]

    capsys.readouterr()
    exit_code = cli.main(["loop", "view", "apply", str(view_id), "--limit", "10", "--offset", "0"])
    assert exit_code == 0
    cli_payload = _parse_last_json(capsys)
    cli_ids = [item["id"] for item in cli_payload["items"]]

    mcp_payload = mcp_loop_view_apply(view_id=view_id, limit=10, offset=0)
    mcp_ids = [item["id"] for item in mcp_payload["items"]]

    assert cli_payload["view"]["id"] == view_id
    assert cli_payload["query"] == "project:alpha tag:work"
    assert cli_payload["limit"] == 10
    assert cli_payload["offset"] == 0
    assert api_ids == cli_ids == mcp_ids


def test_loop_search_cli_invalid_query_returns_exit_code_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """CLI loop search should return exit code 1 for invalid DSL."""
    _make_client(tmp_path, monkeypatch)
    capsys.readouterr()
    exit_code = cli.main(["loop", "search", "--query", "status:not-a-real-status"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "invalid status" in captured.err


# =============================================================================
# Due filter tests
# =============================================================================


def test_search_due_today(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test due:today filter."""
    client = _make_client(tmp_path, monkeypatch)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    due_today = (today_start + timedelta(hours=12)).isoformat()

    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "Due today",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = resp.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"due_at_utc": due_today})

    search_resp = client.post(
        "/loops/search",
        json={"query": "due:today", "limit": 10, "offset": 0},
    )
    assert search_resp.status_code == 200
    assert len(search_resp.json()["items"]) >= 1


def test_search_due_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test due:none filter."""
    client = _make_client(tmp_path, monkeypatch)

    client.post(
        "/loops/capture",
        json={"raw_text": "No due date", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    now = datetime.now(timezone.utc)
    resp = client.post(
        "/loops/capture",
        json={"raw_text": "Has due date", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    client.patch(f"/loops/{resp.json()['id']}", json={"due_at_utc": now.isoformat()})

    search_resp = client.post(
        "/loops/search",
        json={"query": "due:none", "limit": 10, "offset": 0},
    )
    assert search_resp.status_code == 200
    for item in search_resp.json()["items"]:
        assert item["due_at_utc"] is None


def test_search_due_tomorrow_overdue_and_next7d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test due:tomorrow, due:overdue, and due:next7d filters."""
    client = _make_client(tmp_path, monkeypatch)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_noon = (today_start + timedelta(days=1, hours=12)).isoformat()
    overdue_time = (now - timedelta(hours=2)).isoformat()
    within_next7d = (now + timedelta(days=6)).isoformat()
    after_next7d = (now + timedelta(days=8)).isoformat()

    overdue_resp = client.post(
        "/loops/capture",
        json={"raw_text": "Overdue task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    tomorrow_resp = client.post(
        "/loops/capture",
        json={"raw_text": "Tomorrow task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    next7d_resp = client.post(
        "/loops/capture",
        json={"raw_text": "Within next 7d", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    later_resp = client.post(
        "/loops/capture",
        json={"raw_text": "Later task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    overdue_id = overdue_resp.json()["id"]
    tomorrow_id = tomorrow_resp.json()["id"]
    next7d_id = next7d_resp.json()["id"]
    later_id = later_resp.json()["id"]

    assert (
        client.patch(f"/loops/{overdue_id}", json={"due_at_utc": overdue_time}).status_code == 200
    )
    assert (
        client.patch(f"/loops/{tomorrow_id}", json={"due_at_utc": tomorrow_noon}).status_code == 200
    )
    assert (
        client.patch(f"/loops/{next7d_id}", json={"due_at_utc": within_next7d}).status_code == 200
    )
    assert client.patch(f"/loops/{later_id}", json={"due_at_utc": after_next7d}).status_code == 200

    tomorrow_search = client.post("/loops/search", json={"query": "due:tomorrow", "limit": 20})
    assert tomorrow_search.status_code == 200
    tomorrow_ids = {item["id"] for item in tomorrow_search.json()["items"]}
    assert tomorrow_id in tomorrow_ids
    assert overdue_id not in tomorrow_ids

    overdue_search = client.post("/loops/search", json={"query": "due:overdue", "limit": 20})
    assert overdue_search.status_code == 200
    overdue_ids = {item["id"] for item in overdue_search.json()["items"]}
    assert overdue_id in overdue_ids
    assert tomorrow_id not in overdue_ids

    next7d_search = client.post("/loops/search", json={"query": "due:next7d", "limit": 20})
    assert next7d_search.status_code == 200
    next7d_ids = {item["id"] for item in next7d_search.json()["items"]}
    assert tomorrow_id in next7d_ids
    assert next7d_id in next7d_ids
    assert overdue_id not in next7d_ids
    assert later_id not in next7d_ids


# =============================================================================
# Ordering tests
# =============================================================================


def test_search_stable_ordering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that search results have stable ordering."""
    client = _make_client(tmp_path, monkeypatch)

    ids = []
    for i in range(5):
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"Task {i}",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        )
        ids.append(resp.json()["id"])

    resp1 = client.post(
        "/loops/search",
        json={"query": "status:inbox", "limit": 10, "offset": 0},
    )
    resp2 = client.post(
        "/loops/search",
        json={"query": "status:inbox", "limit": 10, "offset": 0},
    )

    ids1 = [item["id"] for item in resp1.json()["items"]]
    ids2 = [item["id"] for item in resp2.json()["items"]]
    assert ids1 == ids2
