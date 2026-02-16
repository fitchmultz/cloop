# ==============================================================================
# Loop Recurrence and Dependency Tests
# ==============================================================================
#
# Purpose:
#     Tests for recurring loop functionality and loop dependency management.
#
# Responsibilities:
#     - Recurrence lifecycle: capture, completion, next occurrence creation
#     - Recurrence query filtering via search DSL
#     - Dependency creation, cycle detection, and removal
#     - Dependency-based state transitions and blocking behavior
#
# Non-scope:
#     - RAG functionality
#     - Note management
#     - LLM enrichment
#     - Embedding/similarity tests
#
# Invariants:
#     - All tests use isolated test clients with temporary databases
#     - Datetime helpers use conftest._now_iso for consistent UTC handling
# ==============================================================================

import sqlite3
from pathlib import Path

import pytest
from conftest import _now_iso

from cloop.loops import service as loop_service
from cloop.settings import get_settings

# ==============================================================================
# Recurrence Lifecycle Tests
# ==============================================================================


def test_capture_with_recurrence_sets_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Capturing a loop with recurrence sets recurrence fields."""
    client = make_test_client()

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily standup",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 200
    loop = response.json()

    assert loop["recurrence_enabled"] is True
    assert loop["recurrence_rrule"] is not None
    assert "FREQ=DAILY" in loop["recurrence_rrule"]
    assert loop["recurrence_tz"] == "UTC"
    assert loop["next_due_at_utc"] is not None


def test_complete_recurring_creates_next_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Completing a recurring loop creates the next occurrence."""
    client = make_test_client()

    # Create recurring loop with tags
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily standup",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    assert capture_response.status_code == 200
    loop_id = capture_response.json()["id"]

    # Add tags to the loop
    client.patch(f"/loops/{loop_id}", json={"tags": ["work", "meeting"]})

    # Complete the loop
    status_response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "completed"},
    )
    assert status_response.status_code == 200
    completed = status_response.json()

    # Verify original loop is completed with recurrence disabled
    assert completed["status"] == "completed"
    assert completed["recurrence_enabled"] is False

    # Find the next occurrence via query
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]

    # Should have exactly one recurring loop (the next occurrence)
    assert len(results) == 1
    next_loop = results[0]

    # Verify next occurrence has recurrence enabled
    assert next_loop["recurrence_enabled"] is True
    assert next_loop["recurrence_rrule"] is not None
    assert next_loop["next_due_at_utc"] is not None

    # Verify tags were copied
    assert "work" in next_loop["tags"]
    assert "meeting" in next_loop["tags"]

    # Verify raw_text was copied
    assert next_loop["raw_text"] == "Daily standup"


def test_bulk_close_recurring_creates_next_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Bulk closing a recurring loop creates the next occurrence."""
    client = make_test_client()

    # Create recurring loop
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily standup",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    assert capture_response.status_code == 200
    loop_id = capture_response.json()["id"]

    # Bulk close it using the service directly (no HTTP endpoint for bulk_close)
    settings = get_settings()
    with sqlite3.connect(settings.core_db_path) as conn:
        conn.row_factory = sqlite3.Row
        bulk_result = loop_service.bulk_close_loops(
            items=[{"loop_id": loop_id, "status": "completed"}],
            transactional=True,
            conn=conn,
        )
    assert bulk_result["ok"] is True
    assert bulk_result["succeeded"] == 1

    # Verify original loop is completed
    get_response = client.get(f"/loops/{loop_id}")
    assert get_response.status_code == 200
    original = get_response.json()
    assert original["status"] == "completed"
    assert original["recurrence_enabled"] is False

    # Find the next occurrence
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]

    # Should have exactly one recurring loop (the next occurrence)
    assert len(results) == 1
    next_loop = results[0]
    assert next_loop["recurrence_enabled"] is True


def test_query_recurring_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Query DSL recurring: filter works correctly."""
    client = make_test_client()

    # Create one recurring and one non-recurring loop
    client.post(
        "/loops/capture",
        json={
            "raw_text": "Daily recurring task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=DAILY",
            "timezone": "UTC",
        },
    )
    client.post(
        "/loops/capture",
        json={
            "raw_text": "One-time task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )

    # Query for recurring
    recurring_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert recurring_response.status_code == 200
    recurring = recurring_response.json()["items"]
    assert len(recurring) == 1
    assert recurring[0]["raw_text"] == "Daily recurring task"

    # Query for non-recurring
    non_recurring_response = client.post(
        "/loops/search",
        json={"query": "recurring:no", "limit": 100, "offset": 0},
    )
    assert non_recurring_response.status_code == 200
    non_recurring = non_recurring_response.json()["items"]
    assert len(non_recurring) == 1
    assert non_recurring[0]["raw_text"] == "One-time task"


def test_multiple_recurrence_completions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Completing a recurring loop multiple times creates a chain of occurrences."""
    client = make_test_client()

    # Create recurring loop
    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Weekly review",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
            "rrule": "FREQ=WEEKLY",
            "timezone": "UTC",
        },
    )
    assert capture_response.status_code == 200
    first_id = capture_response.json()["id"]

    # Complete first occurrence
    client.post(f"/loops/{first_id}/status", json={"status": "completed"})

    # Find the next occurrence
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]
    assert len(results) == 1
    second_id = results[0]["id"]
    assert second_id != first_id

    # Complete second occurrence
    client.post(f"/loops/{second_id}/status", json={"status": "completed"})

    # Find the third occurrence
    search_response = client.post(
        "/loops/search",
        json={"query": "recurring:yes", "limit": 100, "offset": 0},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]
    assert len(results) == 1
    third_id = results[0]["id"]
    assert third_id != first_id
    assert third_id != second_id

    # Verify we have 2 completed and 1 active recurring loop
    all_response = client.get("/loops?status=all&limit=100")
    assert all_response.status_code == 200
    all_loops = all_response.json()
    completed_count = sum(1 for loop in all_loops if loop["status"] == "completed")
    assert completed_count == 2


# ============================================================================
# Loop Dependency Tests
# ============================================================================


class TestLoopDependencies:
    """Tests for loop dependency functionality."""

    def test_add_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Adding a dependency creates the relationship."""
        client = make_test_client()

        # Create two loops
        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Add dependency: B depends on A
        result = client.post(
            f"/loops/{loop_b['id']}/dependencies",
            json={"depends_on_loop_id": loop_a["id"]},
        ).json()

        assert result["id"] == loop_b["id"]
        assert len(result["dependencies"]) == 1
        assert result["dependencies"][0]["id"] == loop_a["id"]
        assert result["has_open_dependencies"] is True

    def test_cycle_detection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Adding a dependency that creates a cycle is rejected."""
        client = make_test_client()

        # Create three loops
        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_c = client.post(
            "/loops/capture",
            json={
                "raw_text": "C",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # A -> B
        client.post(
            f"/loops/{loop_a['id']}/dependencies", json={"depends_on_loop_id": loop_b["id"]}
        )
        # B -> C
        client.post(
            f"/loops/{loop_b['id']}/dependencies", json={"depends_on_loop_id": loop_c["id"]}
        )

        # Try to create cycle: C -> A (should fail)
        result = client.post(
            f"/loops/{loop_c['id']}/dependencies",
            json={"depends_on_loop_id": loop_a["id"]},
        )
        assert result.status_code == 400
        error = result.json()
        assert error["error"]["type"] == "dependency_cycle"

    def test_self_dependency_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """A loop cannot depend on itself."""
        client = make_test_client()

        loop = client.post(
            "/loops/capture",
            json={
                "raw_text": "Self",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        result = client.post(
            f"/loops/{loop['id']}/dependencies",
            json={"depends_on_loop_id": loop["id"]},
        )
        assert result.status_code == 400
        assert result.json()["error"]["type"] == "dependency_cycle"

    def test_transition_to_actionable_blocked_by_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Cannot transition to actionable while dependencies are open."""
        client = make_test_client()

        # Create blocker (inbox = open)
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Create dependent and add dependency
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent task",
                "actionable": True,
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Transition dependent to blocked
        client.post(f"/loops/{dependent['id']}/status", json={"status": "blocked"})

        # Try to transition to actionable (should fail)
        result = client.post(f"/loops/{dependent['id']}/status", json={"status": "actionable"})
        assert result.status_code == 400
        error = result.json()
        assert error["error"]["type"] == "dependency_not_met"
        assert blocker["id"] in error["error"]["details"]["open_dependencies"]

    def test_transition_allowed_after_dependency_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Can transition to actionable after all dependencies are completed."""
        client = make_test_client()

        # Create blocker
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Create dependent
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Transition dependent to blocked
        client.post(f"/loops/{dependent['id']}/status", json={"status": "blocked"})

        # Complete the blocker
        client.post(f"/loops/{blocker['id']}/status", json={"status": "completed"})

        # Now dependent can transition to actionable
        result = client.post(f"/loops/{dependent['id']}/status", json={"status": "actionable"})
        assert result.status_code == 200
        assert result.json()["status"] == "actionable"

    def test_next_loops_excludes_blocked_by_dependencies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """next_loops excludes loops with open dependencies."""
        client = make_test_client()

        # Create blocker with next_action
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker",
                "actionable": True,
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.patch(f"/loops/{blocker['id']}", json={"next_action": "Do blocker"})

        # Create dependent with next_action
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent",
                "actionable": True,
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.patch(f"/loops/{dependent['id']}", json={"next_action": "Do dependent"})

        # Add dependency: dependent -> blocker
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Get next loops
        result = client.get("/loops/next").json()

        # Should only include blocker, not dependent
        next_ids = [loop["id"] for bucket in result.values() for loop in bucket]
        assert blocker["id"] in next_ids
        assert dependent["id"] not in next_ids

    def test_remove_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Removing a dependency works correctly."""
        client = make_test_client()

        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # Add dependency
        client.post(
            f"/loops/{loop_b['id']}/dependencies", json={"depends_on_loop_id": loop_a["id"]}
        )

        # Verify added
        deps = client.get(f"/loops/{loop_b['id']}/dependencies").json()
        assert len(deps) == 1

        # Remove dependency
        client.delete(f"/loops/{loop_b['id']}/dependencies/{loop_a['id']}")

        # Verify removed
        deps = client.get(f"/loops/{loop_b['id']}/dependencies").json()
        assert len(deps) == 0

    def test_blocking_lists_dependents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """blocking endpoint lists loops that depend on this one."""
        client = make_test_client()

        loop_a = client.post(
            "/loops/capture",
            json={
                "raw_text": "A",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_b = client.post(
            "/loops/capture",
            json={
                "raw_text": "B",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        loop_c = client.post(
            "/loops/capture",
            json={
                "raw_text": "C",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()

        # B and C depend on A
        client.post(
            f"/loops/{loop_b['id']}/dependencies", json={"depends_on_loop_id": loop_a["id"]}
        )
        client.post(
            f"/loops/{loop_c['id']}/dependencies", json={"depends_on_loop_id": loop_a["id"]}
        )

        # Get blocking for A
        blocking = client.get(f"/loops/{loop_a['id']}/blocking").json()
        blocking_ids = [b["id"] for b in blocking]

        assert set(blocking_ids) == {loop_b["id"], loop_c["id"]}

    def test_dependency_persists_after_reopen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Dependencies persist after completing and reopening a loop."""
        client = make_test_client()

        # Create loops with dependency
        blocker = client.post(
            "/loops/capture",
            json={
                "raw_text": "Blocker",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        dependent = client.post(
            "/loops/capture",
            json={
                "raw_text": "Dependent",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        ).json()
        client.post(
            f"/loops/{dependent['id']}/dependencies", json={"depends_on_loop_id": blocker["id"]}
        )

        # Complete the blocker
        client.post(f"/loops/{blocker['id']}/status", json={"status": "completed"})

        # Reopen the blocker
        client.post(f"/loops/{blocker['id']}/status", json={"status": "inbox"})

        # Verify dependency still exists and is now open again
        deps = client.get(f"/loops/{dependent['id']}/dependencies").json()
        assert len(deps) == 1
        assert deps[0]["status"] == "inbox"

        # Should not be able to transition to actionable
        result = client.post(f"/loops/{dependent['id']}/status", json={"status": "actionable"})
        assert result.status_code == 400
        assert result.json()["error"]["type"] == "dependency_not_met"
        assert blocker["id"] in result.json()["error"]["details"]["open_dependencies"]
