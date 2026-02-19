# =============================================================================
# test_loop_capture.py
#
# Purpose:
#   Test suite for loop capture endpoint validation and behavior.
#
# Responsibilities:
#   - Test capture endpoint with various payload combinations
#   - Test timestamp format validation (valid and invalid formats)
#   - Test timezone offset validation (boundary values and invalid ranges)
#   - Test filter behavior after capture
#
# Non-scope:
#   - Loop status transitions (see test_loop_transitions.py)
#   - Loop enrichment (see test_loop_enrichment.py)
#   - Loop prioritization (see test_loop_prioritization.py)
#
# Invariants/Assumptions:
#   - Uses make_test_client fixture for isolated test client
#   - Uses _now_iso from conftest for consistent datetime helpers
#   - All datetime values are in UTC internally
# =============================================================================

from pathlib import Path

import pytest
from conftest import _now_iso

from cloop.loops.errors import ValidationError
from cloop.loops.models import parse_client_datetime


def test_loop_capture_and_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    captured_at = _now_iso()

    capture_payloads = [
        {"raw_text": "alpha", "actionable": True},
        {"raw_text": "bravo", "blocked": True},
        {"raw_text": "charlie", "scheduled": True},
        {"raw_text": "delta"},
    ]

    loop_ids: list[int] = []
    for payload in capture_payloads:
        payload.update(
            {
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
            }
        )
        response = client.post("/loops/capture", json=payload)
        assert response.status_code == 200
        loop_ids.append(response.json()["id"])

    open_response = client.get("/loops")
    assert open_response.status_code == 200
    open_statuses = {loop["status"] for loop in open_response.json()}
    assert open_statuses.issubset({"inbox", "actionable", "blocked", "scheduled"})

    close_response = client.post(
        f"/loops/{loop_ids[0]}/status",
        json={"status": "completed"},
    )
    assert close_response.status_code == 200

    refreshed = client.get("/loops")
    assert refreshed.status_code == 200
    assert "completed" not in {loop["status"] for loop in refreshed.json()}

    completed = client.get("/loops", params={"status": "completed"})
    assert completed.status_code == 200
    assert any(loop["status"] == "completed" for loop in completed.json())


def test_loop_capture_invalid_timestamp_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid captured_at format returns 400 with clear error."""
    client = make_test_client()

    invalid_timestamps = [
        "not-a-timestamp",
        "2024-13-45T99:99:99",  # Invalid date/time values
        "2024/01/15 10:30:00",  # Wrong format entirely
        "",  # Empty string
        "   ",  # Whitespace only
    ]

    for invalid_ts in invalid_timestamps:
        response = client.post(
            "/loops/capture",
            json={
                "raw_text": "test",
                "captured_at": invalid_ts,
                "client_tz_offset_min": 0,
            },
        )
        assert response.status_code == 400, f"Expected 400 for '{invalid_ts}'"
        error_detail = response.json()
        assert "error" in error_detail
        # Check that the error message mentions validation
        error_str = str(error_detail).lower()
        assert "invalid captured_at" in error_str or "validation" in error_str


def test_loop_capture_valid_timestamp_with_z_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that timestamps with Z suffix are accepted."""
    client = make_test_client()

    # Use Z suffix (UTC indicator)
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test with Z suffix",
            "captured_at": "2024-01-15T10:30:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    assert response.json()["raw_text"] == "test with Z suffix"


def test_loop_capture_valid_timestamp_with_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that timestamps with timezone offset are accepted."""
    client = make_test_client()

    # Use timezone offset
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test with offset",
            "captured_at": "2024-01-15T10:30:00-05:00",
            "client_tz_offset_min": -300,
        },
    )
    assert response.status_code == 200
    assert response.json()["raw_text"] == "test with offset"


def test_parse_client_datetime_rejects_invalid_tz_offset() -> None:
    """Test that parse_client_datetime rejects invalid tz_offset_min values."""
    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=999999)

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-999999)

    # Also reject exactly ±1440 since Python timezone can't handle it
    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=1440)

    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-1440)


def test_parse_client_datetime_accepts_valid_tz_offset() -> None:
    """Test that parse_client_datetime accepts valid tz_offset_min values."""
    # Should not raise - returns UTC datetime
    result = parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-300)
    assert result is not None

    # Boundary values (Python timezone max is ±1439 minutes)
    parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=-1439)
    parse_client_datetime("2024-01-15T10:30:00", tz_offset_min=1439)


def test_loop_capture_invalid_tz_offset_too_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that tz_offset_min > 1440 is rejected with 400."""
    client = make_test_client()

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 999999,
        },
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail
    error_str = str(error_detail).lower()
    assert "invalid client_tz_offset_min" in error_str or "range" in error_str


def test_loop_capture_invalid_tz_offset_too_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that tz_offset_min < -1439 is rejected with 400."""
    client = make_test_client()

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": -999999,
        },
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail


def test_loop_capture_valid_tz_offset_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that boundary values (-1439, 0, 1439) are accepted."""
    client = make_test_client()

    for offset in [-1439, 0, 1439]:
        response = client.post(
            "/loops/capture",
            json={
                "raw_text": f"test with offset {offset}",
                "captured_at": _now_iso(),
                "client_tz_offset_min": offset,
            },
        )
        assert response.status_code == 200, f"Expected 200 for offset {offset}"


def test_capture_with_due_date(make_test_client) -> None:
    """Test capture with due_at_utc field."""
    client = make_test_client()
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Task with due date",
            "captured_at": "2026-02-17T10:00:00Z",
            "client_tz_offset_min": 0,
            "due_at_utc": "2026-04-15T17:00:00Z",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["due_at_utc"] is not None


def test_capture_with_all_fields(make_test_client) -> None:
    """Test capture with all rich metadata fields."""
    client = make_test_client()
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Complete task",
            "captured_at": "2026-02-17T10:00:00Z",
            "client_tz_offset_min": 0,
            "due_at_utc": "2026-04-15T17:00:00Z",
            "next_action": "Start with step 1",
            "time_minutes": 60,
            "activation_energy": 2,
            "project": "work",
            "tags": ["urgent", "quarterly"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["due_at_utc"] is not None
    assert data["next_action"] == "Start with step 1"
    assert data["time_minutes"] == 60
    assert data["activation_energy"] == 2
    assert data["project"] == "work"
    assert set(data["tags"]) == {"urgent", "quarterly"}


def test_capture_with_invalid_activation_energy(make_test_client) -> None:
    """Test capture rejects invalid activation_energy."""
    client = make_test_client()
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Task",
            "captured_at": "2026-02-17T10:00:00Z",
            "client_tz_offset_min": 0,
            "activation_energy": 5,  # Invalid: > 3
        },
    )
    assert response.status_code == 422  # Validation error


def test_capture_returns_200_when_background_enrichment_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: /loops/capture returns 200 even if background enrichment raises."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from cloop import db
    from cloop.main import app
    from cloop.settings import get_settings

    # Set up isolated environment with autopilot enabled
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    # Mock enrich_loop to raise an exception
    with patch("cloop.loops.enrichment.enrich_loop") as mock_enrich:
        mock_enrich.side_effect = RuntimeError("Simulated enrichment failure")

        client = TestClient(app)
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test task",
                "actionable": True,
                "captured_at": "2026-02-19T10:00:00Z",
                "client_tz_offset_min": 0,
            },
        )

        # Capture should succeed despite background enrichment failure
        assert resp.status_code == 200
        data = resp.json()
        assert data["raw_text"] == "Test task"
        assert data["id"] is not None

        # Background task should have been called
        mock_enrich.assert_called_once()


def test_capture_with_blocked_reason(make_test_client) -> None:
    """Test that blocked_reason is preserved during capture."""
    client = make_test_client()
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Blocked task",
            "captured_at": "2026-02-19T10:00:00Z",
            "client_tz_offset_min": 0,
            "blocked": True,
            "blocked_reason": "Waiting for API key from ops team",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "blocked"
    assert data["blocked_reason"] == "Waiting for API key from ops team"
