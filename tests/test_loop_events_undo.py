"""Tests for loop event history and undo functionality.

Purpose:
    Verify the event history retrieval, pagination, and undo operations
    for loops work correctly.

Responsibilities:
    - Test event history retrieval and structure
    - Test event pagination with cursor-based navigation
    - Test undo operations for updates and status changes
    - Test error handling for undo edge cases
    - Test undo idempotency support
    - Test before_state capture for reversible events

Non-scope:
    - Comment-related tests (see test_loop_comments.py)
    - General loop CRUD operations (see test_loop_capture.py)
    - Loop enrichment tests (see test_loop_enrichment.py)
"""

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import _now_iso

from cloop import db as db_module
from cloop.loops import repo
from cloop.loops.models import LoopStatus
from cloop.settings import get_settings

# =============================================================================
# Event History Tests
# =============================================================================


def test_loop_events_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that event history is returned correctly."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test events",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Make some updates
    client.patch(f"/loops/{loop_id}", json={"title": "First title"})
    client.patch(f"/loops/{loop_id}", json={"title": "Second title"})

    # Get events
    events_response = client.get(f"/loops/{loop_id}/events")
    assert events_response.status_code == 200
    events_data = events_response.json()

    assert events_data["loop_id"] == loop_id
    assert len(events_data["events"]) >= 2  # At least the two updates

    # Check event structure
    for event in events_data["events"]:
        assert "id" in event
        assert "event_type" in event
        assert "payload" in event
        assert "created_at_utc" in event
        assert "is_reversible" in event

    # Check that update events are marked as reversible
    update_events = [e for e in events_data["events"] if e["event_type"] == "update"]
    assert len(update_events) >= 2
    for event in update_events:
        assert event["is_reversible"] is True


def test_loop_events_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test event history pagination."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "pagination test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Make multiple updates
    for i in range(5):
        client.patch(f"/loops/{loop_id}", json={"title": f"Title {i}"})

    # Get first page
    page1 = client.get(f"/loops/{loop_id}/events?limit=2")
    assert page1.status_code == 200
    data1 = page1.json()

    assert len(data1["events"]) == 2
    assert data1["has_more"] is True
    assert data1["next_cursor"] is not None

    # Get second page
    page2 = client.get(f"/loops/{loop_id}/events?limit=2&before_id={data1['next_cursor']}")
    assert page2.status_code == 200
    data2 = page2.json()

    assert len(data2["events"]) >= 2


def test_loop_events_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test events endpoint returns 404 for nonexistent loop."""
    client = make_test_client()

    response = client.get("/loops/99999/events")
    assert response.status_code == 404


# =============================================================================
# Undo Tests
# =============================================================================


def test_loop_undo_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undoing a loop update."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "undo test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Update with a title
    client.patch(f"/loops/{loop_id}", json={"title": "Original Title"})

    # Update again
    update_response = client.patch(f"/loops/{loop_id}", json={"title": "Changed Title"})
    assert update_response.json()["title"] == "Changed Title"

    # Undo
    undo_response = client.post(f"/loops/{loop_id}/undo")
    assert undo_response.status_code == 200
    undo_data = undo_response.json()

    assert undo_data["undone_event_type"] == "update"
    assert undo_data["loop"]["title"] == "Original Title"


def test_loop_undo_status_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undoing a status change."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "status undo test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]
    assert create_response.json()["status"] == "inbox"

    # Transition to actionable
    client.post(f"/loops/{loop_id}/status", json={"status": "actionable"})

    # Transition to completed
    complete_response = client.post(f"/loops/{loop_id}/status", json={"status": "completed"})
    assert complete_response.json()["status"] == "completed"

    # Undo - should go back to actionable
    undo_response = client.post(f"/loops/{loop_id}/undo")
    assert undo_response.status_code == 200
    undo_data = undo_response.json()

    assert undo_data["undone_event_type"] == "close"
    assert undo_data["loop"]["status"] == "actionable"


def test_loop_undo_no_reversible_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undo fails when no reversible events exist."""
    client = make_test_client()

    # Create a loop (capture event is not reversible)
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "no reversible events",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Undo should fail
    undo_response = client.post(f"/loops/{loop_id}/undo")
    assert undo_response.status_code == 400
    error_data = undo_response.json()
    # Error response format is {'error': {'details': {'code': ...}}}
    assert error_data["error"]["details"]["code"] == "undo_not_possible"


def test_loop_undo_records_undo_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that undo operations are recorded in event history."""
    client = make_test_client()

    # Create and update a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "undo record test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"title": "Test Title"})

    # Undo
    client.post(f"/loops/{loop_id}/undo")

    # Check events include the undo event
    events_response = client.get(f"/loops/{loop_id}/events")
    events = events_response.json()["events"]

    undo_events = [e for e in events if e["event_type"] == "undo"]
    assert len(undo_events) == 1
    assert "undone_event_id" in undo_events[0]["payload"]


def test_loop_undo_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undo endpoint returns 404 for nonexistent loop."""
    client = make_test_client()

    response = client.post("/loops/99999/undo")
    assert response.status_code == 404


def test_loop_undo_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test undo endpoint supports idempotency."""
    client = make_test_client()

    # Create and update a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "idempotency test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"title": "Title"})

    # Undo with idempotency key
    headers = {"Idempotency-Key": "undo-key-1"}
    response1 = client.post(f"/loops/{loop_id}/undo", headers=headers)
    assert response1.status_code == 200

    # Same request should replay
    response2 = client.post(f"/loops/{loop_id}/undo", headers=headers)
    assert response2.status_code == 200
    assert response2.json()["undone_event_id"] == response1.json()["undone_event_id"]


def test_loop_update_captures_before_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that update events capture before_state for undo support."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db_module.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="before state test",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Update with title
    from cloop.loops.service import update_loop

    update_loop(
        loop_id=record.id,
        fields={"title": "New Title"},
        conn=conn,
    )

    # Check that the event has before_state
    events = repo.list_loop_events(loop_id=record.id, conn=conn)
    update_events = [e for e in events if e["event_type"] == "update"]
    assert len(update_events) == 1

    payload = json.loads(update_events[0]["payload_json"])
    assert "before_state" in payload

    conn.close()
