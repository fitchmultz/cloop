# =============================================================================
# test_loop_idempotency.py
# =============================================================================
#
# Purpose:
#     Test idempotency behavior for loop operations.
#
# Responsibilities:
#     - Verify idempotency key replay returns same response without duplicates
#     - Test idempotency key validation (empty, too long)
#     - Test idempotency conflict detection (same key, different payload)
#     - Test idempotency scope isolation (different operations, different loop IDs)
#     - Test idempotency expiry behavior
#
# Non-scope:
#     - General loop CRUD operations (see test_loop_capture.py)
#     - Loop state machine transitions (see test_loop_transitions.py)
#     - Performance tests
#
# Invariants:
#     - All tests use the make_test_client fixture for isolated test databases
#     - Datetime helpers use conftest._now_iso for consistent UTC timestamps
# =============================================================================

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import _now_iso
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings

# =============================================================================
# Idempotency tests
# =============================================================================


def test_loop_capture_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload returns same response without duplicate loop."""
    client = make_test_client()

    payload = {
        "raw_text": "idempotent test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "test-key-123"}

    response1 = client.post("/loops/capture", json=payload, headers=headers)
    assert response1.status_code == 200
    loop_id_1 = response1.json()["id"]

    response2 = client.post("/loops/capture", json=payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["id"] == loop_id_1

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_loop_capture_idempotency_concurrent_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Concurrent same-key capture requests replay a single created loop."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    payload = {
        "raw_text": "concurrent idempotency test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "concurrent-key-1"}

    def _capture_once() -> tuple[int, int]:
        with TestClient(app) as client:
            response = client.post("/loops/capture", json=payload, headers=headers)
        return response.status_code, response.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: _capture_once(), range(4)))

    statuses = [status for status, _loop_id in results]
    ids = [loop_id for _status, loop_id in results]
    assert statuses == [200, 200, 200, 200]
    assert len(set(ids)) == 1

    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_loop_capture_idempotency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + different payload returns 409 Conflict."""
    client = make_test_client()

    payload1 = {
        "raw_text": "first text",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "conflict-key"}

    response1 = client.post("/loops/capture", json=payload1, headers=headers)
    assert response1.status_code == 200

    payload2 = {
        "raw_text": "different text",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    response2 = client.post("/loops/capture", json=payload2, headers=headers)
    assert response2.status_code == 409
    assert "idempotency_key_conflict" in str(response2.json())


def test_loop_update_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload for update returns same response."""
    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    update_payload = {"title": "Updated Title"}
    headers = {"Idempotency-Key": "update-key-456"}

    response1 = client.patch(f"/loops/{loop_id}", json=update_payload, headers=headers)
    assert response1.status_code == 200

    response2 = client.patch(f"/loops/{loop_id}", json=update_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["title"] == "Updated Title"

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM loop_events WHERE loop_id = ?", (loop_id,)
        ).fetchone()[0]
    assert count <= 2


def test_loop_status_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload for status change returns same response."""
    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "status test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    status_payload = {"status": "actionable"}
    headers = {"Idempotency-Key": "status-key-789"}

    response1 = client.post(f"/loops/{loop_id}/status", json=status_payload, headers=headers)
    assert response1.status_code == 200
    assert response1.json()["status"] == "actionable"

    response2 = client.post(f"/loops/{loop_id}/status", json=status_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["status"] == "actionable"


def test_loop_close_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload for close returns same response."""
    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "close test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    close_payload = {"status": "completed", "note": "Done"}
    headers = {"Idempotency-Key": "close-key-abc"}

    response1 = client.post(f"/loops/{loop_id}/close", json=close_payload, headers=headers)
    assert response1.status_code == 200
    assert response1.json()["status"] == "completed"
    assert response1.json()["completion_note"] == "Done"

    response2 = client.post(f"/loops/{loop_id}/close", json=close_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["status"] == "completed"
    assert response2.json()["completion_note"] == "Done"


def test_idempotency_key_validation_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Empty idempotency key is rejected."""
    client = make_test_client()

    payload = {
        "raw_text": "test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "   "}

    response = client.post("/loops/capture", json=payload, headers=headers)
    assert response.status_code == 400


def test_no_idempotency_key_creates_separate_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Without idempotency key, same payload creates separate loops."""
    client = make_test_client()

    payload = {
        "raw_text": "no key test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }

    response1 = client.post("/loops/capture", json=payload)
    assert response1.status_code == 200
    loop_id_1 = response1.json()["id"]

    response2 = client.post("/loops/capture", json=payload)
    assert response2.status_code == 200
    loop_id_2 = response2.json()["id"]

    assert loop_id_1 != loop_id_2

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 2


def test_different_scopes_allow_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key can be used for different operations."""
    client = make_test_client()

    payload = {
        "raw_text": "scope test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "same-key-different-scope"}

    response1 = client.post("/loops/capture", json=payload, headers=headers)
    assert response1.status_code == 200
    loop_id = response1.json()["id"]

    update_payload = {"title": "Updated"}
    response2 = client.patch(f"/loops/{loop_id}", json=update_payload, headers=headers)
    assert response2.status_code == 200

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 1


def test_idempotency_key_validation_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Very long idempotency key is rejected."""
    client = make_test_client()

    payload = {
        "raw_text": "test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "x" * 300}

    response = client.post("/loops/capture", json=payload, headers=headers)
    assert response.status_code == 400


def test_loop_import_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Idempotency key works for import endpoint."""
    client = make_test_client()

    now_iso = _now_iso()
    import_payload = {
        "loops": [
            {
                "raw_text": "imported loop",
                "status": "inbox",
                "captured_at_utc": now_iso,
                "captured_tz_offset_min": 0,
                "created_at_utc": now_iso,
                "updated_at_utc": now_iso,
            }
        ]
    }
    headers = {"Idempotency-Key": "import-key"}

    response1 = client.post("/loops/import", json=import_payload, headers=headers)
    assert response1.status_code == 200
    imported_count_1 = response1.json()["imported"]

    response2 = client.post("/loops/import", json=import_payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["imported"] == imported_count_1

    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == imported_count_1


def test_loop_enrich_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Idempotency key works for enrich endpoint."""
    from unittest.mock import patch

    client = make_test_client()

    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "enrich test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    headers = {"Idempotency-Key": "enrich-key"}

    mock_response = {
        "choices": [{"message": {"content": '{"title": "Test", "confidence": {"title": 0.9}}'}}]
    }

    with patch("cloop.loops.enrichment.litellm.completion", return_value=mock_response):
        response1 = client.post(f"/loops/{loop_id}/enrich", headers=headers)
        assert response1.status_code == 200

        response2 = client.post(f"/loops/{loop_id}/enrich", headers=headers)
        assert response2.status_code == 200


def test_idempotency_expiry_allows_new_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """After idempotency key expires, same key can create new loop."""
    client = make_test_client()
    settings = get_settings()

    payload = {
        "raw_text": "expiry test",
        "captured_at": _now_iso(),
        "client_tz_offset_min": 0,
    }
    headers = {"Idempotency-Key": "expiring-key"}

    response1 = client.post("/loops/capture", json=payload, headers=headers)
    assert response1.status_code == 200
    loop_id_1 = response1.json()["id"]

    with sqlite3.connect(settings.core_db_path) as conn:
        conn.execute(
            """
            UPDATE idempotency_keys
            SET expires_at = '2000-01-01T00:00:00+00:00'
            WHERE scope = 'http:POST:/loops/capture'
              AND idempotency_key = ?
            """,
            ("expiring-key",),
        )
        conn.commit()

    response2 = client.post("/loops/capture", json=payload, headers=headers)
    assert response2.status_code == 200
    loop_id_2 = response2.json()["id"]

    assert loop_id_1 != loop_id_2

    with sqlite3.connect(settings.core_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    assert count == 2


def test_different_loop_ids_create_different_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key can be used for different loop IDs."""
    client = make_test_client()

    create1 = client.post(
        "/loops/capture",
        json={
            "raw_text": "loop 1",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id_1 = create1.json()["id"]

    create2 = client.post(
        "/loops/capture",
        json={
            "raw_text": "loop 2",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id_2 = create2.json()["id"]

    headers = {"Idempotency-Key": "same-update-key"}

    update_payload = {"title": "Updated"}

    response1 = client.patch(f"/loops/{loop_id_1}", json=update_payload, headers=headers)
    assert response1.status_code == 200

    response2 = client.patch(f"/loops/{loop_id_2}", json=update_payload, headers=headers)
    assert response2.status_code == 200

    get1 = client.get(f"/loops/{loop_id_1}")
    get2 = client.get(f"/loops/{loop_id_2}")
    assert get1.json()["title"] == "Updated"
    assert get2.json()["title"] == "Updated"
