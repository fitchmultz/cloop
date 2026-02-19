"""Tests for loop export and import functionality.

Purpose:
    Validate that loops can be exported to JSON and imported into a fresh
    database while preserving all fields (roundtrip integrity).

Responsibilities:
    Test export endpoint returns complete loop data including optional fields
    Test import endpoint correctly reconstructs loops from export payload
    Verify roundtrip preserves completion notes, tags, and other metadata
    Test export filters (status, project, tag, date)
    Test import dry-run mode
    Test import conflict policies (skip, update, fail)

Non-scope:
    Export/import of other entities (notes, documents)
    Performance benchmarks for large exports
    Incremental/delta export mechanisms
"""

from pathlib import Path

import pytest
from conftest import _now_iso


def test_export_import_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    capture = client.post(
        "/loops/capture",
        json={
            "raw_text": "export me",
            "actionable": True,
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert capture.status_code == 200
    loop_id = capture.json()["id"]

    update = client.patch(
        f"/loops/{loop_id}",
        json={"title": "Exported", "tags": ["Backup"], "completion_note": "archived"},
    )
    assert update.status_code == 200

    export_response = client.get("/loops/export")
    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload["loops"]
    assert export_payload["loops"][0]["completion_note"] == "archived"

    fresh_dir = tmp_path / "imported"
    fresh_dir.mkdir()
    fresh_client = make_test_client(data_dir=fresh_dir)
    import_response = fresh_client.post("/loops/import", json={"loops": export_payload["loops"]})
    assert import_response.status_code == 200
    assert import_response.json()["imported"] == len(export_payload["loops"])

    imported_loops = fresh_client.get("/loops", params={"status": "all"})
    assert imported_loops.status_code == 200
    imported_payload = imported_loops.json()
    assert imported_payload
    assert imported_payload[0]["completion_note"] == "archived"


def test_export_with_status_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test export filters by status."""
    client = make_test_client()

    # Create loops with different statuses
    client.post(
        "/loops/capture",
        json={"raw_text": "inbox item", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "actionable",
            "actionable": True,
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )

    # Export only actionable
    export_response = client.get("/loops/export", params={"status": ["actionable"]})
    assert export_response.status_code == 200
    data = export_response.json()
    assert data["filtered"] is True
    loops = data["loops"]
    assert len(loops) == 1
    assert loops[0]["status"] == "actionable"


def test_export_with_project_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test export filters by project."""
    client = make_test_client()

    capture = client.post(
        "/loops/capture",
        json={"raw_text": "task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    loop_id = capture.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"project": "Project A"})

    export_response = client.get("/loops/export", params={"project": "Project A"})
    assert export_response.status_code == 200
    data = export_response.json()
    assert data["filtered"] is True
    loops = data["loops"]
    assert len(loops) == 1
    assert loops[0]["project"] == "Project A"


def test_export_with_tag_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test export filters by tag."""
    client = make_test_client()

    capture = client.post(
        "/loops/capture",
        json={"raw_text": "task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    loop_id = capture.json()["id"]
    client.patch(f"/loops/{loop_id}", json={"tags": ["urgent"]})

    export_response = client.get("/loops/export", params={"tag": "urgent"})
    assert export_response.status_code == 200
    data = export_response.json()
    assert data["filtered"] is True
    loops = data["loops"]
    assert len(loops) == 1
    assert "urgent" in loops[0]["tags"]


def test_export_unfiltered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test export without filters returns all loops."""
    client = make_test_client()

    client.post(
        "/loops/capture",
        json={"raw_text": "task1", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    client.post(
        "/loops/capture",
        json={"raw_text": "task2", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    export_response = client.get("/loops/export")
    assert export_response.status_code == 200
    data = export_response.json()
    assert data["filtered"] is False
    assert len(data["loops"]) == 2


def test_import_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test import dry-run does not write to database."""
    client = make_test_client()

    loop_data = {
        "raw_text": "dry run test",
        "status": "inbox",
        "captured_at_utc": "2026-02-18T10:00:00+00:00",
        "captured_tz_offset_min": 0,
        "created_at_utc": "2026-02-18T10:00:00+00:00",
        "updated_at_utc": "2026-02-18T10:00:00+00:00",
    }

    import_response = client.post(
        "/loops/import?dry_run=true",
        json={"loops": [loop_data]},
    )
    assert import_response.status_code == 200
    result = import_response.json()
    assert result["dry_run"] is True
    assert result["imported"] == 0  # Nothing actually imported
    assert "preview" in result
    assert result["preview"]["would_create"] == 1

    # Verify no loops were created
    list_response = client.get("/loops", params={"status": "all"})
    assert len(list_response.json()) == 0


def test_import_conflict_policy_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test import with conflict_policy=skip."""
    client = make_test_client()

    # Create existing loop
    client.post(
        "/loops/capture",
        json={"raw_text": "existing task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    # Import with skip policy
    import_response = client.post(
        "/loops/import?conflict_policy=skip",
        json={
            "loops": [
                {
                    "raw_text": "existing task",
                    "status": "actionable",
                    "captured_at_utc": "2026-02-18T10:00:00+00:00",
                    "captured_tz_offset_min": 0,
                    "created_at_utc": "2026-02-18T10:00:00+00:00",
                    "updated_at_utc": "2026-02-18T10:00:00+00:00",
                },  # Conflict
                {
                    "raw_text": "new task",
                    "status": "inbox",
                    "captured_at_utc": "2026-02-18T10:00:00+00:00",
                    "captured_tz_offset_min": 0,
                    "created_at_utc": "2026-02-18T10:00:00+00:00",
                    "updated_at_utc": "2026-02-18T10:00:00+00:00",
                },  # New
            ],
        },
    )
    assert import_response.status_code == 200
    result = import_response.json()
    assert result["skipped"] == 1
    assert result["imported"] == 1
    assert result["conflicts_detected"] == 1

    # Verify original loop unchanged
    loops = client.get("/loops", params={"status": "all"}).json()
    existing = [loop for loop in loops if loop["raw_text"] == "existing task"][0]
    assert existing["status"] == "inbox"  # Not updated to actionable


def test_import_conflict_policy_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test import with conflict_policy=update."""
    client = make_test_client()

    # Create existing loop
    client.post(
        "/loops/capture",
        json={"raw_text": "existing task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    # Import with update policy
    import_response = client.post(
        "/loops/import?conflict_policy=update",
        json={
            "loops": [
                {
                    "raw_text": "existing task",
                    "status": "actionable",
                    "title": "Updated Title",
                    "captured_at_utc": "2026-02-18T10:00:00+00:00",
                    "captured_tz_offset_min": 0,
                    "created_at_utc": "2026-02-18T10:00:00+00:00",
                    "updated_at_utc": "2026-02-18T10:00:00+00:00",
                },
            ],
        },
    )
    assert import_response.status_code == 200
    result = import_response.json()
    assert result["updated"] == 1

    # Verify loop was updated
    loops = client.get("/loops", params={"status": "all"}).json()
    existing = [loop for loop in loops if loop["raw_text"] == "existing task"][0]
    assert existing["title"] == "Updated Title"


def test_import_conflict_policy_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test import with conflict_policy=fail (default)."""
    client = make_test_client()

    # Create existing loop
    client.post(
        "/loops/capture",
        json={"raw_text": "existing task", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )

    # Import should fail
    import_response = client.post(
        "/loops/import",
        json={
            "loops": [
                {
                    "raw_text": "existing task",
                    "status": "actionable",
                    "captured_at_utc": "2026-02-18T10:00:00+00:00",
                    "captured_tz_offset_min": 0,
                    "created_at_utc": "2026-02-18T10:00:00+00:00",
                    "updated_at_utc": "2026-02-18T10:00:00+00:00",
                },
            ],
        },
    )
    assert import_response.status_code == 400
    error_msg = import_response.json().get(
        "detail", import_response.json().get("error", {}).get("message", "")
    )
    assert "conflict" in error_msg.lower()
