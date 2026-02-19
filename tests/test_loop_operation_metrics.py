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


def test_project_metrics_breakdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test per-project metrics are computed correctly."""
    client = make_test_client()
    captured_at = _now_iso()

    # Create loops in different projects
    client.post(
        "/loops/capture",
        json={
            "raw_text": "project A task 1",
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "project": "project-a",
        },
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "project A task 2",
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "project": "project-a",
        },
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "project B task",
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "project": "project-b",
        },
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "no project task",
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )

    # Request metrics with project breakdown
    resp = client.get("/loops/metrics?include_project=true")
    assert resp.status_code == 200
    data = resp.json()

    assert data["project_breakdown"] is not None
    assert len(data["project_breakdown"]) >= 2  # At least project-a and project-b

    # Find project-a (should have 2 loops)
    project_a = next(
        (p for p in data["project_breakdown"] if p["project_name"] == "project-a"),
        None,
    )
    assert project_a is not None
    assert project_a["total_loops"] == 2

    # Find project-b (should have 1 loop)
    project_b = next(
        (p for p in data["project_breakdown"] if p["project_name"] == "project-b"),
        None,
    )
    assert project_b is not None
    assert project_b["total_loops"] == 1


def test_trend_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test time-series trend metrics structure is correct."""
    client = make_test_client()

    # Request metrics with trend (default 7-day window)
    resp = client.get("/loops/metrics?include_trend=true")
    assert resp.status_code == 200
    data = resp.json()

    # Verify trend metrics structure
    assert data["trend_metrics"] is not None
    assert data["trend_metrics"]["window_days"] == 7
    assert len(data["trend_metrics"]["points"]) == 7

    # Verify each point has required fields
    for point in data["trend_metrics"]["points"]:
        assert "date" in point
        assert "capture_count" in point
        assert "completion_count" in point
        assert "open_count" in point

    # Verify summary fields exist
    assert "total_captures" in data["trend_metrics"]
    assert "total_completions" in data["trend_metrics"]
    assert "avg_daily_captures" in data["trend_metrics"]
    assert "avg_daily_completions" in data["trend_metrics"]


def test_trend_custom_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test trend metrics with custom window."""
    client = make_test_client()

    # Request 3-day trend
    resp = client.get("/loops/metrics?include_trend=true&trend_window_days=3")
    assert resp.status_code == 200
    data = resp.json()

    assert data["trend_metrics"]["window_days"] == 3
    assert len(data["trend_metrics"]["points"]) == 3


def test_metrics_without_optional_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that optional dimensions are null when not requested."""
    client = make_test_client()

    resp = client.get("/loops/metrics")
    assert resp.status_code == 200
    data = resp.json()

    # These should be None (or absent) when not requested
    assert data.get("project_breakdown") is None
    assert data.get("trend_metrics") is None
