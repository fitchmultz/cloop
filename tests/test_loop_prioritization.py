"""Tests for loop prioritization and next_loops functionality.

Purpose:
    Test the prioritization system including SQL filtering, bucket assignment,
    and status resolution for loop candidates.

Responsibilities:
    - Validate next_loops SQL-level filtering logic
    - Test bucketize function for priority classification
    - Verify priority weights from settings
    - Test status flag resolution and terminal status detection

Non-scope:
    - Loop capture or lifecycle transitions (see test_loop_capture.py, test_loop_transitions.py)
    - Enrichment or AI-powered features (see test_loop_enrichment.py)
    - RAG or document-related functionality
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import _now_iso

from cloop import db
from cloop.loops import read_service, repo
from cloop.loops.models import LoopStatus
from cloop.loops.prioritization import bucketize
from cloop.settings import get_settings

# =============================================================================
# next_loops SQL filtering tests
# =============================================================================


def test_next_loops_sql_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that next_loops SQL-level filtering excludes wrong candidates."""
    client = make_test_client()
    captured_at = _now_iso()
    now = datetime.now(timezone.utc)
    future = (now + timedelta(hours=24)).isoformat(timespec="seconds")

    # Create loops with different states
    # 1. Has next_action, no snooze - SHOULD appear
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "task with next action",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_1 = resp.json()["id"]
    client.patch(f"/loops/{loop_id_1}", json={"next_action": "do this"})

    # 2. Has next_action, snoozed in future - should NOT appear
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "snoozed task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_2 = resp.json()["id"]
    client.patch(
        f"/loops/{loop_id_2}",
        json={"next_action": "do later", "snooze_until_utc": future},
    )

    # 3. No next_action - should NOT appear
    client.post(
        "/loops/capture",
        json={
            "raw_text": "inbox item",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )

    # 4. Completed status - should NOT appear (even with next_action)
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "done task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_4 = resp.json()["id"]
    client.patch(f"/loops/{loop_id_4}", json={"next_action": "was doing"})
    client.post(f"/loops/{loop_id_4}/status", json={"status": "completed"})

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # Only the first task should appear in any bucket
    all_titles = []
    for bucket_items in data.values():
        all_titles.extend(item.get("title") or item.get("raw_text", "") for item in bucket_items)

    assert any("task with next action" in t for t in all_titles)
    assert not any("snoozed task" in t for t in all_titles)
    assert not any("inbox item" in t for t in all_titles)
    assert not any("done task" in t for t in all_titles)


def test_next_loops_candidate_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that candidate count respects next_candidates_limit setting."""
    client = make_test_client()
    captured_at = _now_iso()

    # Create more loops than the default cap (500)
    # For testing, we'll create 10 and verify the limit works
    for i in range(10):
        client.post(
            "/loops/capture",
            json={
                "raw_text": f"task {i}",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
                "next_action": f"action {i}",
            },
        )

    # Set a low limit via environment
    monkeypatch.setenv("CLOOP_NEXT_CANDIDATES_LIMIT", "5")
    get_settings.cache_clear()

    response = client.get("/loops/next")
    assert response.status_code == 200

    # Total across all buckets should be at most the cap
    data = response.json()
    total_items = sum(len(items) for items in data.values())
    assert total_items <= 5


def test_next_loops_ranking_preserves_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that SQL filtering returns the same candidates Python filtering would.

    This validates that the SQL-level filters (status, next_action, snooze) correctly
    identify actionable candidates without missing items that would have passed
    the old Python-level filtering.
    """
    client = make_test_client()
    captured_at = _now_iso()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat(timespec="seconds")

    # Create an actionable loop that should appear in results
    resp_actionable = client.post(
        "/loops/capture",
        json={
            "raw_text": "actionable task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "urgency": 0.8,
        },
    )
    actionable_id = resp_actionable.json()["id"]
    client.patch(f"/loops/{actionable_id}", json={"next_action": "do this"})

    # Create an inbox item with next_action - should also appear
    resp_inbox = client.post(
        "/loops/capture",
        json={
            "raw_text": "inbox with action",
            "actionable": False,  # Will be inbox status
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "urgency": 0.5,
        },
    )
    inbox_id = resp_inbox.json()["id"]
    client.patch(f"/loops/{inbox_id}", json={"next_action": "process this"})

    # Create an expired snooze - should appear
    resp_snooze = client.post(
        "/loops/capture",
        json={
            "raw_text": "expired snooze task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
            "urgency": 0.6,
        },
    )
    snooze_id = resp_snooze.json()["id"]
    client.patch(
        f"/loops/{snooze_id}",
        json={"next_action": "do after snooze", "snooze_until_utc": past},
    )

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # Collect all item IDs from all buckets
    all_ids: set[int] = set()
    for bucket in data.values():
        for item in bucket:
            all_ids.add(item.get("id"))

    # All candidates should be found
    assert actionable_id in all_ids, "Actionable task should be in results"
    assert inbox_id in all_ids, "Inbox item with next_action should be in results"
    assert snooze_id in all_ids, "Expired snooze task should be in results"


def test_next_loops_excludes_non_candidate_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that blocked, scheduled, dropped, and completed loops are excluded."""
    client = make_test_client()
    captured_at = _now_iso()

    # Create loops and transition them to various non-candidate statuses
    for status in ["blocked", "scheduled", "dropped"]:
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"{status} task",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
            },
        )
        loop_id = resp.json()["id"]
        client.patch(f"/loops/{loop_id}", json={"next_action": "some action"})
        client.post(f"/loops/{loop_id}/status", json={"status": status})

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # None of the non-candidate items should appear
    all_titles: list[str] = []
    for bucket_items in data.values():
        all_titles.extend(item.get("title") or item.get("raw_text", "") for item in bucket_items)

    assert not any("blocked" in t for t in all_titles)
    assert not any("scheduled" in t for t in all_titles)
    assert not any("dropped" in t for t in all_titles)


def test_next_loops_snooze_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that snooze boundary conditions are handled correctly."""
    client = make_test_client()
    captured_at = _now_iso()
    now = datetime.now(timezone.utc)

    # 1. Snoozed in past - SHOULD appear (snooze has expired)
    past = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "past snooze task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_past = resp.json()["id"]
    client.patch(
        f"/loops/{loop_id_past}",
        json={"next_action": "do this", "snooze_until_utc": past},
    )

    # 2. Snoozed exactly at now - SHOULD appear (snooze is expired)
    current = now.isoformat(timespec="seconds")
    resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "current snooze task",
            "actionable": True,
            "captured_at": captured_at,
            "client_tz_offset_min": 0,
        },
    )
    loop_id_current = resp.json()["id"]
    client.patch(
        f"/loops/{loop_id_current}",
        json={"next_action": "do now", "snooze_until_utc": current},
    )

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    all_titles: list[str] = []
    for bucket_items in data.values():
        all_titles.extend(item.get("title") or item.get("raw_text", "") for item in bucket_items)

    # Both past and current snoozed tasks should appear
    assert any("past snooze task" in t for t in all_titles)
    assert any("current snooze task" in t for t in all_titles)


def test_next_loops_empty_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that empty result is handled gracefully when no candidates match."""
    client = make_test_client()

    response = client.get("/loops/next")
    assert response.status_code == 200
    data = response.json()

    # Should return all buckets, even if empty
    assert "due_soon" in data
    assert "quick_wins" in data
    assert "high_leverage" in data
    assert "standard" in data

    # All buckets should be empty lists
    assert data["due_soon"] == []
    assert data["quick_wins"] == []
    assert data["high_leverage"] == []
    assert data["standard"] == []


# =============================================================================
# bucketize tests
# =============================================================================


def test_bucketize_returns_standard_for_low_importance(test_settings) -> None:
    """Low importance loops should NOT be classified as high_leverage."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    # Loop with low importance, not due soon, not a quick win
    loop = {
        "importance": 0.1,
        "time_minutes": 120,
        "activation_energy": 3,
        # No due_at_utc, so not due_soon
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard", f"Expected 'standard' for low importance loop, got '{result}'"


def test_bucketize_returns_high_leverage_for_high_importance(test_settings) -> None:
    """High importance loops should be classified as high_leverage."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.8,
        "time_minutes": 120,
        "activation_energy": 3,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "high_leverage"


def test_bucketize_returns_due_soon_for_urgent_due_date(test_settings) -> None:
    """Loops due within 48h should be due_soon regardless of other factors."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.9,  # High importance
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
        "time_minutes": 5,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "due_soon"


def test_bucketize_returns_quick_wins_for_small_tasks(test_settings) -> None:
    """Short, low-energy tasks should be quick_wins."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.9,  # High importance
        "time_minutes": 10,
        "activation_energy": 1,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "quick_wins"


def test_bucketize_handles_none_importance(test_settings) -> None:
    """Loops without importance should default to standard."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard"


def test_bucketize_importance_boundary_high(test_settings) -> None:
    """Loop with importance exactly 0.7 should be high_leverage."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.7,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "high_leverage"


def test_bucketize_importance_boundary_low(test_settings) -> None:
    """Loop with importance just below 0.7 should be standard."""
    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {
        "importance": 0.69,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    result = bucketize(loop, now_utc=now, settings=settings)
    assert result == "standard"


# =============================================================================
# Priority weights and status resolution tests
# =============================================================================


def test_priority_weights_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Verify that next_loops uses priority weights from settings."""
    import sqlite3

    from cloop.loops.models import LoopStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    # Set custom priority weights
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_DUE", "2.0")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_URGENCY", "1.5")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_IMPORTANCE", "0.5")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_TIME_PENALTY", "0.1")
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_ACTIVATION_PENALTY", "0.2")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create an actionable loop with next_action
    record = repo.create_loop(
        raw_text="Test loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    repo.update_loop_fields(
        loop_id=record.id,
        fields={"status": LoopStatus.ACTIONABLE.value, "next_action": "Do it"},
        conn=conn,
    )

    # Verify settings have the custom weights
    assert settings.priority_weight_due == 2.0
    assert settings.priority_weight_urgency == 1.5
    assert settings.priority_weight_importance == 0.5
    assert settings.priority_weight_time_penalty == 0.1
    assert settings.priority_weight_activation_penalty == 0.2

    # Call next_loops with custom settings - should not raise
    result = read_service.next_loops(limit=10, conn=conn, settings=settings)

    # Should have buckets
    assert "due_soon" in result
    assert "quick_wins" in result
    assert "high_leverage" in result
    assert "standard" in result

    conn.close()


def test_resolve_status_from_flags() -> None:
    """Test resolve_status_from_flags precedence logic."""
    from cloop.loops.models import resolve_status_from_flags

    # Single flag tests
    assert resolve_status_from_flags(True, False, False) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(False, True, False) == LoopStatus.BLOCKED
    assert resolve_status_from_flags(False, False, True) == LoopStatus.ACTIONABLE
    assert resolve_status_from_flags(False, False, False) == LoopStatus.INBOX

    # Precedence tests
    assert resolve_status_from_flags(True, True, True) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(True, True, False) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(True, False, True) == LoopStatus.SCHEDULED
    assert resolve_status_from_flags(False, True, True) == LoopStatus.BLOCKED


def test_is_terminal_status_completed() -> None:
    from cloop.loops.models import is_terminal_status

    assert is_terminal_status(LoopStatus.COMPLETED) is True


def test_is_terminal_status_dropped() -> None:
    from cloop.loops.models import is_terminal_status

    assert is_terminal_status(LoopStatus.DROPPED) is True


def test_is_terminal_status_non_terminal() -> None:
    from cloop.loops.models import is_terminal_status

    for status in (
        LoopStatus.INBOX,
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
    ):
        assert is_terminal_status(status) is False, f"{status} should not be terminal"


def test_terminal_statuses_constant() -> None:
    from cloop.loops.models import TERMINAL_STATUSES

    assert TERMINAL_STATUSES == frozenset({LoopStatus.COMPLETED, LoopStatus.DROPPED})


def test_next_loops_total_limit_not_per_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that limit caps TOTAL items across all buckets, not per bucket."""
    client = make_test_client()
    captured_at = _now_iso()

    # Create loops that will populate all 4 buckets
    now = datetime.now(timezone.utc)

    # due_soon bucket: due within 48h
    for i in range(5):
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"due soon task {i}",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
                "due_at_utc": (now + timedelta(hours=24)).isoformat(),
            },
        )
        client.patch(f"/loops/{resp.json()['id']}", json={"next_action": f"do {i}"})

    # quick_wins bucket: time_minutes <= 15, activation_energy <= 1
    for i in range(5):
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"quick win {i}",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
                "time_minutes": 10,
                "activation_energy": 1,
            },
        )
        client.patch(f"/loops/{resp.json()['id']}", json={"next_action": f"quick {i}"})

    # high_leverage bucket: importance >= 0.7
    for i in range(5):
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"high leverage {i}",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
                "importance": 0.8,
                "time_minutes": 60,
                "activation_energy": 2,
            },
        )
        client.patch(f"/loops/{resp.json()['id']}", json={"next_action": f"leverage {i}"})

    # standard bucket: low importance, not quick win
    for i in range(5):
        resp = client.post(
            "/loops/capture",
            json={
                "raw_text": f"standard task {i}",
                "actionable": True,
                "captured_at": captured_at,
                "client_tz_offset_min": 0,
                "importance": 0.3,
                "time_minutes": 60,
                "activation_energy": 2,
            },
        )
        client.patch(f"/loops/{resp.json()['id']}", json={"next_action": f"standard {i}"})

    # Request with limit=3
    response = client.get("/loops/next?limit=3")
    assert response.status_code == 200
    data = response.json()

    # CRITICAL: Total across ALL buckets must be <= limit
    total_items = sum(len(items) for items in data.values())
    assert total_items <= 3, f"Expected at most 3 total items, got {total_items}"

    # All bucket keys should be present
    assert "due_soon" in data
    assert "quick_wins" in data
    assert "high_leverage" in data
    assert "standard" in data


# =============================================================================
# Dependency/blocker state integration tests
# =============================================================================


def test_compute_priority_score_blocked_penalty(test_settings) -> None:
    """Blocked loops should score lower than identical unblocked loops."""
    from cloop.loops.prioritization import PriorityWeights, compute_priority_score

    now = datetime.now(timezone.utc)
    settings = test_settings()

    # Create identical loops
    loop = {
        "urgency": 0.8,
        "importance": 0.9,
        "time_minutes": 30,
        "activation_energy": 2,
    }

    weights = PriorityWeights(
        due_weight=1.0,
        urgency_weight=0.7,
        importance_weight=0.9,
        time_penalty=0.2,
        activation_penalty=0.3,
        blocked_penalty=10.0,
    )

    # Score unblocked loop
    unblocked_score = compute_priority_score(
        loop, now_utc=now, w=weights, settings=settings, has_open_dependencies=False
    )

    # Score blocked loop
    blocked_score = compute_priority_score(
        loop, now_utc=now, w=weights, settings=settings, has_open_dependencies=True
    )

    # Blocked loop should have lower score
    assert blocked_score < unblocked_score
    # Difference should be the blocked penalty
    assert unblocked_score - blocked_score == pytest.approx(10.0)


def test_compute_priority_score_blocked_penalty_configurable(test_settings) -> None:
    """The blocked penalty should be configurable via weights."""
    from cloop.loops.prioritization import PriorityWeights, compute_priority_score

    now = datetime.now(timezone.utc)
    settings = test_settings()

    loop = {"urgency": 0.5, "importance": 0.5}

    # Test with different penalty values
    for penalty in [5.0, 10.0, 20.0]:
        weights = PriorityWeights(
            due_weight=1.0,
            urgency_weight=0.7,
            importance_weight=0.9,
            time_penalty=0.2,
            activation_penalty=0.3,
            blocked_penalty=penalty,
        )

        unblocked_score = compute_priority_score(
            loop, now_utc=now, w=weights, settings=settings, has_open_dependencies=False
        )
        blocked_score = compute_priority_score(
            loop, now_utc=now, w=weights, settings=settings, has_open_dependencies=True
        )

        assert unblocked_score - blocked_score == pytest.approx(penalty)


def test_bucketize_blocked_demotes_to_standard(test_settings) -> None:
    """Blocked loops should be demoted to 'standard' bucket regardless of other factors."""
    from cloop.loops.prioritization import bucketize

    now = datetime.now(timezone.utc)
    settings = test_settings()

    # Loop that would normally be "due_soon"
    due_soon_loop = {
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
        "importance": 0.9,
    }

    # Loop that would normally be "quick_wins"
    quick_win_loop = {
        "time_minutes": 10,
        "activation_energy": 1,
        "importance": 0.9,
    }

    # Loop that would normally be "high_leverage"
    high_leverage_loop = {
        "importance": 0.8,
        "time_minutes": 60,
        "activation_energy": 2,
    }

    # All should return "standard" when blocked
    assert (
        bucketize(due_soon_loop, now_utc=now, settings=settings, has_open_dependencies=True)
        == "standard"
    )
    assert (
        bucketize(quick_win_loop, now_utc=now, settings=settings, has_open_dependencies=True)
        == "standard"
    )
    assert (
        bucketize(high_leverage_loop, now_utc=now, settings=settings, has_open_dependencies=True)
        == "standard"
    )


def test_bucketize_unblocked_uses_normal_logic(test_settings) -> None:
    """Unblocked loops should use normal bucketize logic."""
    from cloop.loops.prioritization import bucketize

    now = datetime.now(timezone.utc)
    settings = test_settings()

    # Due soon loop
    due_soon_loop = {
        "due_at_utc": (now + timedelta(hours=24)).isoformat(),
    }
    assert (
        bucketize(due_soon_loop, now_utc=now, settings=settings, has_open_dependencies=False)
        == "due_soon"
    )

    # Quick win loop
    quick_win_loop = {
        "time_minutes": 10,
        "activation_energy": 1,
    }
    assert (
        bucketize(quick_win_loop, now_utc=now, settings=settings, has_open_dependencies=False)
        == "quick_wins"
    )

    # High leverage loop
    high_leverage_loop = {
        "importance": 0.8,
        "time_minutes": 60,
        "activation_energy": 2,
    }
    assert (
        bucketize(high_leverage_loop, now_utc=now, settings=settings, has_open_dependencies=False)
        == "high_leverage"
    )


def test_next_loops_excludes_blocked_by_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """next_loops should exclude loops with open dependencies."""
    import sqlite3

    from cloop import db
    from cloop.loops import repo
    from cloop.loops.models import LoopStatus
    from cloop.settings import get_settings

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create two loops
    blocker = repo.create_loop(
        raw_text="Blocker loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.ACTIONABLE,
        conn=conn,
    )
    repo.update_loop_fields(
        loop_id=blocker.id,
        fields={"next_action": "Blocker action", "urgency": 0.9},
        conn=conn,
    )

    blocked = repo.create_loop(
        raw_text="Blocked loop",
        captured_at_utc="2024-01-01T00:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.ACTIONABLE,
        conn=conn,
    )
    repo.update_loop_fields(
        loop_id=blocked.id,
        fields={"next_action": "Blocked action", "urgency": 0.9},
        conn=conn,
    )

    # Create dependency relationship
    repo.add_dependency(
        loop_id=blocked.id,
        depends_on_loop_id=blocker.id,
        conn=conn,
    )

    # Call next_loops
    result = read_service.next_loops(limit=10, conn=conn, settings=settings)

    # Blocked loop should not appear
    all_titles = []
    for bucket in result.values():
        for item in bucket:
            all_titles.append(item.get("title") or item.get("raw_text", ""))

    assert any("Blocker" in t for t in all_titles), "Blocker should appear"
    assert not any("Blocked" in t for t in all_titles), "Blocked should not appear"

    conn.close()


def test_priority_weights_include_blocked_penalty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings should include the blocked_penalty weight."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_BLOCKED_PENALTY", "15.0")
    get_settings.cache_clear()

    settings = get_settings()
    assert hasattr(settings, "priority_weight_blocked_penalty")
    assert settings.priority_weight_blocked_penalty == 15.0
