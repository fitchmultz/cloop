# =============================================================================
# Test: Loop Timer Operations
# =============================================================================
# Purpose:
#   Verify time tracking functionality for loops including timer start/stop,
#   concurrent timer prevention, session history, and estimation accuracy.
#
# Responsibilities:
#   - Test timer start and stop operations
#   - Test concurrent timer prevention (one active timer per loop)
#   - Test stopping without an active timer
#   - Test session history listing
#   - Test timer status with time estimates
#   - Test timer operations on non-existent loops
#   - Test TimeSession dataclass properties
#
# Non-scope:
#   - Loop capture/update logic (see test_loop_capture.py)
#   - Enrichment and prioritization (see test_loop_enrichment.py, test_loop_prioritization.py)
#   - RAG operations
#
# Invariants:
#   - All tests use TestClient with isolated databases via make_test_client fixture
#   - Datetime handling uses UTC internally via conftest._now_iso
# =============================================================================

from pathlib import Path

import pytest
from conftest import _now_iso

pytestmark = pytest.mark.slow

# ============================================================================
# Time Tracking Tests
# ============================================================================


def test_timer_start_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test starting and stopping a timer."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "timer test",
            "actionable": True,
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Start timer
    start = client.post(f"/loops/{loop_id}/timer/start")
    assert start.status_code == 200
    session = start.json()
    assert session["loop_id"] == loop_id
    assert session["is_active"] is True
    assert session["ended_at_utc"] is None

    # Check status
    status = client.get(f"/loops/{loop_id}/timer/status")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["has_active_session"] is True
    assert status_data["loop_id"] == loop_id

    # Stop timer
    import time

    time.sleep(1)  # Ensure at least 1 second duration
    stop = client.post(f"/loops/{loop_id}/timer/stop", json={"notes": "Done"})
    assert stop.status_code == 200
    stopped = stop.json()
    assert stopped["is_active"] is False
    assert stopped["duration_seconds"] >= 1
    assert stopped["notes"] == "Done"


def test_concurrent_timer_prevention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that only one active timer per loop is allowed."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "concurrent test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Start first timer
    start1 = client.post(f"/loops/{loop_id}/timer/start")
    assert start1.status_code == 200

    # Try to start second timer - should fail
    start2 = client.post(f"/loops/{loop_id}/timer/start")
    assert start2.status_code == 409
    error = start2.json()
    assert "timer_already_active" in str(error) or "already has an active timer" in str(
        error.get("detail", "")
    )


def test_stop_without_active_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that stopping without active timer returns error."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "stop test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Try to stop without starting
    stop = client.post(f"/loops/{loop_id}/timer/stop")
    assert stop.status_code == 400
    error = stop.json()
    assert "no_active_timer" in str(error) or "no active timer" in str(error.get("detail", ""))


def test_session_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test listing time sessions."""
    client = make_test_client()

    # Create a loop
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "history test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Start and stop timer twice
    client.post(f"/loops/{loop_id}/timer/start")
    import time

    time.sleep(1)
    client.post(f"/loops/{loop_id}/timer/stop")

    time.sleep(0.5)
    client.post(f"/loops/{loop_id}/timer/start")
    time.sleep(1)
    client.post(f"/loops/{loop_id}/timer/stop")

    # List sessions
    sessions = client.get(f"/loops/{loop_id}/sessions")
    assert sessions.status_code == 200
    data = sessions.json()
    assert data["loop_id"] == loop_id
    assert len(data["sessions"]) >= 2


def test_session_history_total_count_respects_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Session list total_count should reflect all sessions, not just the page size."""
    client = make_test_client()

    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "pagination history test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    import time

    for _ in range(3):
        client.post(f"/loops/{loop_id}/timer/start")
        time.sleep(1)
        client.post(f"/loops/{loop_id}/timer/stop")

    sessions = client.get(f"/loops/{loop_id}/sessions?limit=1&offset=1")
    assert sessions.status_code == 200
    data = sessions.json()
    assert len(data["sessions"]) == 1
    assert data["total_count"] == 3


def test_timer_status_with_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test timer status shows estimation accuracy."""
    client = make_test_client()

    # Create a loop with time estimate
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "estimate test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = capture.json()["id"]

    # Set time estimate
    client.patch(f"/loops/{loop_id}", json={"time_minutes": 30})

    # Track some time
    client.post(f"/loops/{loop_id}/timer/start")
    import time

    time.sleep(2)
    client.post(f"/loops/{loop_id}/timer/stop")

    # Check status
    status = client.get(f"/loops/{loop_id}/timer/status")
    assert status.status_code == 200
    data = status.json()
    assert data["estimated_minutes"] == 30
    # With 2 seconds tracked (0 min), accuracy should be very low
    assert data["estimation_accuracy"] is not None


def test_timer_for_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test timer operations on non-existent loop."""
    client = make_test_client()

    # Try to start timer on non-existent loop
    start = client.post("/loops/99999/timer/start")
    assert start.status_code == 404

    # Try to stop timer on non-existent loop
    stop = client.post("/loops/99999/timer/stop")
    assert stop.status_code == 404

    # Try to get status on non-existent loop
    status = client.get("/loops/99999/timer/status")
    assert status.status_code == 404


def test_timer_session_properties() -> None:
    """Test TimeSession dataclass properties."""
    from datetime import datetime, timezone

    from cloop.loops.models import TimeSession

    # Active session (no ended_at)
    now = datetime.now(timezone.utc)
    active_session = TimeSession(
        id=1,
        loop_id=42,
        started_at_utc=now,
        ended_at_utc=None,
        duration_seconds=None,
        notes=None,
        created_at_utc=now,
    )
    assert active_session.is_active is True
    assert active_session.elapsed_seconds >= 0  # Should calculate from started_at

    # Completed session
    completed_session = TimeSession(
        id=2,
        loop_id=42,
        started_at_utc=now,
        ended_at_utc=now,
        duration_seconds=300,
        notes="Done",
        created_at_utc=now,
    )
    assert completed_session.is_active is False
    assert completed_session.elapsed_seconds == 300
