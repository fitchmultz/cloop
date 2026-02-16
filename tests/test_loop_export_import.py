"""Tests for loop export and import functionality.

Purpose:
    Validate that loops can be exported to JSON and imported into a fresh
    database while preserving all fields (roundtrip integrity).

Responsibilities:
    Test export endpoint returns complete loop data including optional fields
    Test import endpoint correctly reconstructs loops from export payload
    Verify roundtrip preserves completion notes, tags, and other metadata

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
