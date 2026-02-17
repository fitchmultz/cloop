# =============================================================================
# test_loop_operation_metrics.py
#
# Purpose:
#   Test suite for loop lifecycle operation metrics collection.
#
# Responsibilities:
#   - Test capture/update/transition counter increments
#   - Test metrics disabled behavior
#   - Test reset functionality
# =============================================================================

from pathlib import Path

import pytest
from conftest import _now_iso

from cloop.loops.metrics import get_operation_metrics


def test_operation_metrics_disabled_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client()
    captured_at = _now_iso()

    resp = client.post(
        "/loops/capture",
        json={"raw_text": "test loop", "captured_at": captured_at, "client_tz_offset_min": 0},
    )
    assert resp.status_code == 200

    metrics_resp = client.get("/loops/metrics")
    assert metrics_resp.status_code == 200
    data = metrics_resp.json()
    assert data["operation_metrics"] is None


def test_operation_metrics_capture_increments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    monkeypatch.setenv("CLOOP_OPERATION_METRICS_ENABLED", "true")
    from cloop.settings import get_settings

    get_settings.cache_clear()

    client = make_test_client()
    get_operation_metrics().reset()
    captured_at = _now_iso()

    resp = client.post(
        "/loops/capture",
        json={"raw_text": "test loop", "captured_at": captured_at, "client_tz_offset_min": 0},
    )
    assert resp.status_code == 200

    metrics_resp = client.get("/loops/metrics")
    data = metrics_resp.json()
    assert data["operation_metrics"]["capture_count"] == 1
    assert data["operation_metrics"]["update_count"] == 0


def test_operation_metrics_update_increments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    monkeypatch.setenv("CLOOP_OPERATION_METRICS_ENABLED", "true")
    from cloop.settings import get_settings

    get_settings.cache_clear()

    client = make_test_client()
    get_operation_metrics().reset()
    captured_at = _now_iso()

    capture_resp = client.post(
        "/loops/capture",
        json={"raw_text": "test loop", "captured_at": captured_at, "client_tz_offset_min": 0},
    )
    loop_id = capture_resp.json()["id"]

    update_resp = client.patch(
        f"/loops/{loop_id}",
        json={"title": "Updated title"},
    )
    assert update_resp.status_code == 200

    metrics_resp = client.get("/loops/metrics")
    data = metrics_resp.json()
    assert data["operation_metrics"]["update_count"] == 1


def test_operation_metrics_transition_increments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    monkeypatch.setenv("CLOOP_OPERATION_METRICS_ENABLED", "true")
    from cloop.settings import get_settings

    get_settings.cache_clear()

    client = make_test_client()
    get_operation_metrics().reset()
    captured_at = _now_iso()

    capture_resp = client.post(
        "/loops/capture",
        json={"raw_text": "test loop", "captured_at": captured_at, "client_tz_offset_min": 0},
    )
    loop_id = capture_resp.json()["id"]

    transition_resp = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "actionable"},
    )
    assert transition_resp.status_code == 200

    metrics_resp = client.get("/loops/metrics")
    data = metrics_resp.json()
    assert "inbox->actionable" in data["operation_metrics"]["transition_counts"]
    assert data["operation_metrics"]["transition_counts"]["inbox->actionable"] == 1


def test_operation_metrics_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    monkeypatch.setenv("CLOOP_OPERATION_METRICS_ENABLED", "true")
    from cloop.settings import get_settings

    get_settings.cache_clear()

    client = make_test_client()
    metrics = get_operation_metrics()
    initial_reset_count = metrics.get_snapshot()["reset_count"]
    metrics.reset()

    captured_at = _now_iso()
    client.post(
        "/loops/capture",
        json={"raw_text": "test", "captured_at": captured_at, "client_tz_offset_min": 0},
    )

    assert metrics.get_snapshot()["capture_count"] == 1
    metrics.reset()
    assert metrics.get_snapshot()["capture_count"] == 0
    assert metrics.get_snapshot()["reset_count"] == initial_reset_count + 2  # reset twice
