"""Tests for loop duplicate detection and merge functionality.

Purpose:
    Validate the duplicate detection and merge operations for loops,
    including endpoint behavior, validation rules, and idempotency.

Responsibilities:
    - Test duplicate threshold settings validation
    - Test duplicate candidates endpoint
    - Test merge preview and execution endpoints
    - Test merge conflict detection and resolution
    - Test merge idempotency guarantees
    - Test tag combination during merge

Non-scope:
    - General loop CRUD operations (see test_loop_capture.py)
    - Loop state transitions (see test_loop_transitions.py)
    - Enrichment logic (see test_loop_enrichment.py)
"""

from pathlib import Path

import pytest
from conftest import _now_iso

from cloop.settings import get_settings

# ============================================================================
# Duplicate Detection and Merge Tests
# ============================================================================


def test_settings_duplicate_threshold_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Settings validation requires duplicate_threshold > related_threshold."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_RELATED_SIMILARITY_THRESHOLD", "0.92")
    monkeypatch.setenv("CLOOP_DUPLICATE_SIMILARITY_THRESHOLD", "0.91")  # Less than related
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="DUPLICATE_SIMILARITY_THRESHOLD must be greater"):
        get_settings()


def test_settings_duplicate_threshold_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Settings validation requires duplicate_threshold between 0.9 and 1.0."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_DUPLICATE_SIMILARITY_THRESHOLD", "0.85")  # Below minimum
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="DUPLICATE_SIMILARITY_THRESHOLD must be between"):
        get_settings()


def test_find_duplicate_candidates_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """GET /loops/{id}/duplicates returns candidates list."""
    client = make_test_client()

    # Create two loops
    loop1 = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test duplicate detection task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Create second loop (potential duplicate)
    _ = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test duplicate detection task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Query duplicates endpoint (may return empty if embeddings not generated)
    resp = client.get(f"/loops/{loop1['id']}/duplicates")
    assert resp.status_code == 200
    data = resp.json()
    assert "loop_id" in data
    assert "candidates" in data
    assert isinstance(data["candidates"], list)


def test_merge_preview_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """GET /loops/{id}/merge-preview/{target} returns merge preview."""
    client = make_test_client()

    # Create two loops
    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Surviving loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Duplicate loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    # Get merge preview (loop2 into loop1)
    resp = client.get(f"/loops/{loop2['id']}/merge-preview/{loop1['id']}")
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["surviving_loop_id"] == loop1["id"]
    assert preview["duplicate_loop_id"] == loop2["id"]
    assert "merged_title" in preview
    assert "merged_summary" in preview
    assert "merged_tags" in preview
    assert "field_conflicts" in preview


def test_merge_preview_same_loop_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge preview fails if trying to merge loop with itself."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={"raw_text": "Test loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    resp = client.get(f"/loops/{loop['id']}/merge-preview/{loop['id']}")
    assert resp.status_code == 400
    assert "Cannot merge" in str(resp.json())


def test_merge_preview_nonexistent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge preview fails if loop doesn't exist."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={"raw_text": "Test loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    resp = client.get(f"/loops/{loop['id']}/merge-preview/99999")
    assert resp.status_code == 404


def test_merge_loops_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """POST /loops/{id}/merge merges duplicate into target."""
    client = make_test_client()

    # Create surviving loop with title and tags
    loop1 = client.post(
        "/loops/capture",
        json={
            "raw_text": "Surviving loop task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Update with title and tags
    client.patch(f"/loops/{loop1['id']}", json={"title": "Surviving Title", "tags": ["work"]})

    # Create duplicate loop with different fields
    loop2 = client.post(
        "/loops/capture",
        json={
            "raw_text": "Duplicate loop task",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    ).json()

    # Update with summary and tags
    client.patch(
        f"/loops/{loop2['id']}",
        json={"summary": "Duplicate Summary", "tags": ["personal"]},
    )

    # Execute merge (loop2 into loop1)
    resp = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["surviving_loop_id"] == loop1["id"]
    assert result["closed_loop_id"] == loop2["id"]
    assert "merged_tags" in result
    assert "fields_updated" in result

    # Verify duplicate is closed
    resp = client.get(f"/loops/{loop2['id']}")
    assert resp.status_code == 200
    closed = resp.json()
    assert closed["status"] == "dropped"


def test_merge_loops_into_closed_loop_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot merge into a closed loop."""
    client = make_test_client()

    # Create and close a loop
    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Completed loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.post(f"/loops/{loop1['id']}/close", json={"status": "completed"})

    # Create another loop
    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Open loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    # Try to merge into closed loop
    resp = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
    )
    assert resp.status_code == 400


def test_merge_loops_nonexistent_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot merge into non-existent loop."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={"raw_text": "Test loop", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    resp = client.post(
        f"/loops/{loop['id']}/merge",
        json={"target_loop_id": 99999},
    )
    assert resp.status_code == 404


def test_merge_loops_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge supports idempotency key for safe retries."""
    client = make_test_client()

    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Surviving", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Duplicate", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    headers = {"Idempotency-Key": "merge-test-key-123"}

    # First merge
    resp1 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
        headers=headers,
    )
    assert resp1.status_code == 200

    # Retry with same key should return same result
    resp2 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["surviving_loop_id"] == resp1.json()["surviving_loop_id"]


def test_merge_loops_conflict_different_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key with different payload returns conflict."""
    client = make_test_client()

    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Surviving", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Duplicate", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    loop3 = client.post(
        "/loops/capture",
        json={"raw_text": "Other", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()

    headers = {"Idempotency-Key": "merge-conflict-key"}

    # First merge
    resp1 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
        headers=headers,
    )
    assert resp1.status_code == 200

    # Different target with same key should conflict
    resp2 = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop3["id"]},  # Different target
        headers=headers,
    )
    assert resp2.status_code == 409
    assert "idempotency_key_conflict" in str(resp2.json())


def test_merge_preview_detects_field_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Preview identifies field conflicts when both loops have different values."""
    client = make_test_client()

    # Create loops with different titles
    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop one", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop1['id']}", json={"title": "Title One"})

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop two", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop2['id']}", json={"title": "Title Two"})

    # Get preview
    resp = client.get(f"/loops/{loop2['id']}/merge-preview/{loop1['id']}")
    assert resp.status_code == 200
    preview = resp.json()

    assert "title" in preview["field_conflicts"]
    assert preview["field_conflicts"]["title"]["surviving"] == "Title One"
    assert preview["field_conflicts"]["title"]["duplicate"] == "Title Two"


def test_merge_combines_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Merge combines tags from both loops."""
    client = make_test_client()

    loop1 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop one", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop1['id']}", json={"tags": ["work", "priority"]})

    loop2 = client.post(
        "/loops/capture",
        json={"raw_text": "Loop two", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    ).json()
    client.patch(f"/loops/{loop2['id']}", json={"tags": ["personal", "work"]})  # "work" overlaps

    # Execute merge
    resp = client.post(
        f"/loops/{loop2['id']}/merge",
        json={"target_loop_id": loop1["id"]},
    )
    assert resp.status_code == 200
    result = resp.json()

    # Tags should be union
    assert "work" in result["merged_tags"]
    assert "priority" in result["merged_tags"]
    assert "personal" in result["merged_tags"]
    assert len(result["merged_tags"]) == 3  # No duplicates
