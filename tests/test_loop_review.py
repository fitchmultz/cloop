"""Review cohort tests for the loops subsystem.

Purpose:
    Test the /loops/review endpoint and its cohort-based categorization logic.

Responsibilities:
    - Verify each review cohort (stale, no_next_action, blocked_too_long, due_soon_unplanned)
    - Test review settings validation and defaults
    - Test weekly vs daily review modes
    - Test limit parameter for pagination

Non-scope:
    - Loop capture/creation (see test_loop_capture.py)
    - Loop state transitions (see test_loop_transitions.py)
    - Prioritization scoring (see test_loop_prioritization.py)
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import _now_iso

from cloop import db
from cloop.settings import get_settings

# =============================================================================
# Review Cohort Tests
# =============================================================================


def test_review_cohorts_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test stale cohort identifies loops not updated recently."""
    client = make_test_client()
    now = _now_iso()

    # Create a loop and artificially age it
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "old task",
            "actionable": True,
            "captured_at": now,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Update updated_at to be 100 hours ago (exceeds default 72h stale threshold)
    settings = get_settings()
    with sqlite3.connect(str(settings.core_db_path)) as conn:
        conn.execute(
            "UPDATE loops SET updated_at = datetime('now', '-100 hours') WHERE id = ?",
            (loop_id,),
        )
        conn.commit()

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    stale_cohort = next((c for c in data["daily"] if c["cohort"] == "stale"), None)
    assert stale_cohort is not None
    assert stale_cohort["count"] >= 1
    assert any(item["id"] == loop_id for item in stale_cohort["items"])


def test_review_cohorts_no_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test no_next_action cohort identifies actionable loops without next_action."""
    client = make_test_client()
    now = _now_iso()

    # Create actionable loop without next_action
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "do something",
            "actionable": True,
            "captured_at": now,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    no_action = next((c for c in data["daily"] if c["cohort"] == "no_next_action"), None)
    assert no_action is not None
    assert any(item["id"] == loop_id for item in no_action["items"])


def test_review_cohorts_blocked_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test blocked_too_long cohort identifies long-blocked loops."""
    client = make_test_client()
    now = _now_iso()

    # Create blocked loop and age it
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "waiting on X",
            "blocked": True,
            "captured_at": now,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Age the loop 72 hours (exceeds default 48h blocked threshold)
    settings = get_settings()
    with sqlite3.connect(str(settings.core_db_path)) as conn:
        conn.execute(
            "UPDATE loops SET updated_at = datetime('now', '-72 hours') WHERE id = ?",
            (loop_id,),
        )
        conn.commit()

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    blocked = next((c for c in data["daily"] if c["cohort"] == "blocked_too_long"), None)
    assert blocked is not None
    assert any(item["id"] == loop_id for item in blocked["items"])


def test_review_cohorts_due_soon_unplanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test due_soon_unplanned cohort identifies due loops without next_action."""
    client = make_test_client()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    # Create loop due in 24 hours (within 48h window) without next_action
    due_soon = (now + timedelta(hours=24)).isoformat(timespec="seconds")
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "deadline soon",
            "actionable": True,
            "captured_at": now_iso,
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    # Set due date
    client.patch(f"/loops/{loop_id}", json={"due_at_utc": due_soon})

    resp = client.get("/loops/review")
    assert resp.status_code == 200
    data = resp.json()

    due_soon_cohort = next((c for c in data["daily"] if c["cohort"] == "due_soon_unplanned"), None)
    assert due_soon_cohort is not None
    assert any(item["id"] == loop_id for item in due_soon_cohort["items"])


def test_review_cohorts_due_soon_unplanned_recurring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Recurring loops with only next_due_at_utc should appear in due_soon_unplanned."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    next_due_24h = (now + timedelta(hours=24)).isoformat(timespec="seconds")

    conn = sqlite3.connect(str(settings.core_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO loops
           (raw_text, status, captured_at_utc, captured_tz_offset_min,
            next_due_at_utc, recurrence_enabled, recurrence_rrule)
           VALUES ('weekly review', 'actionable', datetime('now'), 0, ?, 1, 'FREQ=WEEKLY')
        """,
        (next_due_24h,),
    )
    conn.commit()

    from cloop.loops.review import compute_review_cohorts

    result = compute_review_cohorts(
        conn=conn, settings=settings, now_utc=now, include_daily=True, include_weekly=False
    )
    conn.close()

    due_soon_cohort = next((c for c in result.daily if c.cohort == "due_soon_unplanned"), None)
    assert due_soon_cohort is not None
    assert due_soon_cohort.count >= 1


def test_review_weekly_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test weekly review only includes stale and blocked_too_long cohorts."""
    client = make_test_client()

    resp = client.get("/loops/review?weekly=true&daily=false")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["daily"]) == 0
    cohort_names = {c["cohort"] for c in data["weekly"]}
    assert cohort_names <= {"stale", "blocked_too_long"}


def test_review_settings_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test review settings validation via environment variables."""
    from cloop.settings import get_settings

    # Test invalid review_stale_hours
    monkeypatch.setenv("CLOOP_REVIEW_STALE_HOURS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_REVIEW_STALE_HOURS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_REVIEW_STALE_HOURS", raising=False)
    get_settings.cache_clear()

    # Test invalid review_blocked_hours
    monkeypatch.setenv("CLOOP_REVIEW_BLOCKED_HOURS", "-1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_REVIEW_BLOCKED_HOURS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_REVIEW_BLOCKED_HOURS", raising=False)
    get_settings.cache_clear()

    # Test invalid review_due_soon_hours
    monkeypatch.setenv("CLOOP_REVIEW_DUE_SOON_HOURS", "0.5")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_REVIEW_DUE_SOON_HOURS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_REVIEW_DUE_SOON_HOURS", raising=False)
    get_settings.cache_clear()


def test_review_cohorts_default_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test review cohorts use default settings correctly."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    # Verify default values
    assert settings.review_stale_hours == 72.0
    assert settings.review_blocked_hours == 48.0
    assert settings.review_due_soon_hours == 48.0


def test_review_endpoint_limit_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test review endpoint respects limit parameter."""
    client = make_test_client()
    now = _now_iso()

    # Create multiple actionable loops without next_action
    for i in range(5):
        client.post(
            "/loops/capture",
            json={
                "raw_text": f"task {i}",
                "actionable": True,
                "captured_at": now,
                "client_tz_offset_min": 0,
            },
        )

    # Get review with limit=2
    resp = client.get("/loops/review?limit=2")
    assert resp.status_code == 200
    data = resp.json()

    # Check that no_next_action cohort has at most 2 items
    no_action = next((c for c in data["daily"] if c["cohort"] == "no_next_action"), None)
    if no_action:
        assert len(no_action["items"]) <= 2
