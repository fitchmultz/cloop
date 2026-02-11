from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.loops.prioritization import bucketize
from cloop.main import app
from cloop.settings import get_settings


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def test_loop_capture_and_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
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


def test_loop_status_transitions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "status test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop_id = response.json()["id"]

    for status in ["actionable", "blocked", "scheduled"]:
        transition = client.post(f"/loops/{loop_id}/status", json={"status": status})
        assert transition.status_code == 200
        assert transition.json()["status"] == status

    completed = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "completed", "note": "shipped"},
    )
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["completion_note"] == "shipped"

    reopened = client.post(f"/loops/{loop_id}/status", json={"status": "inbox"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "inbox"


def test_tag_normalization_and_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "tag test",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop_id = response.json()["id"]

    update = client.patch(
        f"/loops/{loop_id}",
        json={"tags": ["Feature", "Golf"]},
    )
    assert update.status_code == 200
    assert sorted(update.json()["tags"]) == ["feature", "golf"]

    tags_response = client.get("/loops/tags")
    assert tags_response.status_code == 200
    assert tags_response.json() == ["feature", "golf"]

    filtered = client.get("/loops", params={"tag": "FEATURE"})
    assert filtered.status_code == 200
    assert any(loop["id"] == loop_id for loop in filtered.json())

    cleared = client.patch(f"/loops/{loop_id}", json={"tags": []})
    assert cleared.status_code == 200

    tags_after = client.get("/loops/tags")
    assert tags_after.status_code == 200
    assert tags_after.json() == []


def test_export_import_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
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
    fresh_client = _make_client(fresh_dir, monkeypatch)
    import_response = fresh_client.post("/loops/import", json={"loops": export_payload["loops"]})
    assert import_response.status_code == 200
    assert import_response.json()["imported"] == len(export_payload["loops"])

    imported_loops = fresh_client.get("/loops", params={"status": "all"})
    assert imported_loops.status_code == 200
    imported_payload = imported_loops.json()
    assert imported_payload
    assert imported_payload[0]["completion_note"] == "archived"


def test_bucketize_returns_standard_for_low_importance() -> None:
    """Low importance loops should NOT be classified as high_leverage."""
    now = datetime.now(timezone.utc)

    # Loop with low importance, not due soon, not a quick win
    loop = {
        "importance": 0.1,
        "time_minutes": 120,
        "activation_energy": 3,
        # No due_at_utc, so not due_soon
    }

    result = bucketize(loop, now_utc=now)
    assert result == "standard", f"Expected 'standard' for low importance loop, got '{result}'"


def test_bucketize_returns_high_leverage_for_high_importance() -> None:
    """High importance loops should be classified as high_leverage."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.8,
        "time_minutes": 120,
        "activation_energy": 3,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "high_leverage"


def test_bucketize_returns_due_soon_for_urgent_due_date() -> None:
    """Loops due within 48h should be due_soon regardless of other factors."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.9,  # High importance
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
        "time_minutes": 5,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "due_soon"


def test_bucketize_returns_quick_wins_for_small_tasks() -> None:
    """Short, low-energy tasks should be quick_wins."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.9,  # High importance
        "time_minutes": 10,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "quick_wins"


def test_bucketize_handles_none_importance() -> None:
    """Loops without importance should default to standard."""
    now = datetime.now(timezone.utc)

    loop = {
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "standard"


def test_bucketize_importance_boundary_high() -> None:
    """Loop with importance exactly 0.7 should be high_leverage."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.7,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "high_leverage"


def test_bucketize_importance_boundary_low() -> None:
    """Loop with importance just below 0.7 should be standard."""
    now = datetime.now(timezone.utc)

    loop = {
        "importance": 0.69,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now)
    assert result == "standard"
