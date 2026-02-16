"""Loop validation tests for Cloop.

Purpose:
    Test input validation and error handling for loop operations.

Responsibilities:
    - Test timestamp format validation (due_at_utc, snooze_until_utc)
    - Test timezone offset validation boundaries
    - Test field name validation in update operations

Non-scope:
    - End-to-end loop lifecycle tests (see test_loop_capture.py, test_loop_transitions.py)
    - Database failure tests (see test_db_failures.py)
    - MCP server validation (see test_mcp_server.py)

Invariants:
    - All datetime validation errors return HTTP 400 with clear error messages
    - Timezone offsets must be within [-1439, 1439] minutes
    - Invalid field names in updates raise ValidationError with all invalid fields listed
"""

import sqlite3
from pathlib import Path

import pytest
from conftest import _now_iso

from cloop import db
from cloop.loops import repo
from cloop.loops.errors import ValidationError
from cloop.loops.models import LoopStatus, validate_tz_offset
from cloop.settings import get_settings

# =============================================================================
# Timestamp format validation tests
# =============================================================================


def test_loop_update_invalid_due_at_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid due_at_utc format returns 400 with clear error."""
    client = make_test_client()

    # Create a loop first
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Try to update with invalid timestamp
    response = client.patch(
        f"/loops/{loop_id}",
        json={"due_at_utc": "not-a-valid-timestamp"},
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail
    error_str = str(error_detail).lower()
    assert "invalid due_at_utc" in error_str or "validation" in error_str


def test_loop_update_invalid_snooze_until_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that invalid snooze_until_utc format returns 400 with clear error."""
    client = make_test_client()

    # Create a loop first
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Try to update with invalid timestamp
    response = client.patch(
        f"/loops/{loop_id}",
        json={"snooze_until_utc": "2024-13-45T99:99:99"},
    )
    assert response.status_code == 400
    error_detail = response.json()
    assert "error" in error_detail


# =============================================================================
# Timezone offset validation tests
# =============================================================================


def test_validate_tz_offset_rejects_too_high() -> None:
    """Test that validate_tz_offset rejects values > 1440."""
    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        validate_tz_offset(999999)

    with pytest.raises(ValidationError, match="Invalid custom_field.*outside valid range"):
        validate_tz_offset(1441, "custom_field")


def test_validate_tz_offset_rejects_too_low() -> None:
    """Test that validate_tz_offset rejects values < -1440."""
    with pytest.raises(ValidationError, match="Invalid tz_offset_min.*outside valid range"):
        validate_tz_offset(-999999)

    with pytest.raises(ValidationError, match="Invalid custom_field.*outside valid range"):
        validate_tz_offset(-1441, "custom_field")


def test_validate_tz_offset_accepts_valid_boundaries() -> None:
    """Test that validate_tz_offset accepts boundary values."""
    # Should not raise
    assert validate_tz_offset(-1439) == -1439
    assert validate_tz_offset(0) == 0
    assert validate_tz_offset(1439) == 1439


# =============================================================================
# update_loop_fields validation tests
# =============================================================================


def test_update_loop_fields_rejects_invalid_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that update_loop_fields raises ValidationError for invalid field names."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Try to update with an invalid field name
    with pytest.raises(ValidationError, match="Invalid fields"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"typo_field": "some value"},
            conn=conn,
        )

    # Try with mix of valid and invalid - should still fail
    with pytest.raises(ValidationError, match="Invalid fields"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"title": "Valid title", "another_typo": "bad"},
            conn=conn,
        )

    conn.close()


def test_update_loop_fields_rejects_multiple_invalid_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that error message includes all invalid fields, sorted alphabetically."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop
    record = repo.create_loop(
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )

    # Try with multiple invalid fields - should list all, sorted
    with pytest.raises(ValidationError, match="alpha_field, zebra_field"):
        repo.update_loop_fields(
            loop_id=record.id,
            fields={"zebra_field": "z", "alpha_field": "a"},
            conn=conn,
        )

    conn.close()
