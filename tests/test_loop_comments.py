# =============================================================================
# test_loop_comments.py
#
# Purpose:
#     Test suite for loop comment CRUD operations, threading, events, and
#     idempotency guarantees.
#
# Responsibilities:
#     - Test comment creation, updating, and soft-deletion
#     - Test comment threading (replies and hierarchical ordering)
#     - Test comment event recording
#     - Test idempotency for all comment operations
#
# Non-scope:
#     - Loop CRUD operations (see test_loop_capture.py)
#     - RAG functionality
#     - MCP server behavior
#
# Invariants:
#     - All tests use isolated temporary databases via make_test_client fixture
#     - Comments are always associated with a specific loop
# =============================================================================

from pathlib import Path

import pytest

# =============================================================================
# Comment Tests
# =============================================================================


class TestLoopComments:
    """Tests for loop comment CRUD and threading."""

    def test_create_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test creating a top-level comment on a loop."""
        client = make_test_client()

        # Create a loop first
        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop for comments",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        # Create comment
        resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "This is a **test** comment",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["author"] == "Alice"
        assert data["body_md"] == "This is a **test** comment"
        assert data["parent_id"] is None
        assert data["is_reply"] is False
        assert data["is_deleted"] is False

    def test_create_reply(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test creating a reply to a comment."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        # Create parent comment
        parent_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "Parent comment",
            },
        )
        parent_id = parent_resp.json()["id"]

        # Create reply
        reply_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Bob",
                "body_md": "Reply to Alice",
                "parent_id": parent_id,
            },
        )
        assert reply_resp.status_code == 201
        data = reply_resp.json()
        assert data["parent_id"] == parent_id
        assert data["is_reply"] is True

    def test_list_comments_threaded_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test that comments are returned in proper threaded order."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        # Create comments in non-threaded order
        c1 = client.post(
            f"/loops/{loop_id}/comments", json={"author": "A", "body_md": "First"}
        ).json()
        c2 = client.post(
            f"/loops/{loop_id}/comments", json={"author": "B", "body_md": "Second"}
        ).json()
        client.post(
            f"/loops/{loop_id}/comments",
            json={"author": "C", "body_md": "Reply to First", "parent_id": c1["id"]},
        )
        client.post(
            f"/loops/{loop_id}/comments",
            json={"author": "D", "body_md": "Reply to Second", "parent_id": c2["id"]},
        )

        # List comments
        resp = client.get(f"/loops/{loop_id}/comments")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_count"] == 4
        assert len(data["comments"]) == 2  # Two top-level comments

        # First parent should have one reply
        assert len(data["comments"][0]["replies"]) == 1
        assert data["comments"][0]["replies"][0]["parent_id"] == c1["id"]

        # Second parent should have one reply
        assert len(data["comments"][1]["replies"]) == 1
        assert data["comments"][1]["replies"][0]["parent_id"] == c2["id"]

    def test_update_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test updating a comment's body."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        comment_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "Original text",
            },
        )
        comment_id = comment_resp.json()["id"]

        # Update
        update_resp = client.patch(
            f"/loops/{loop_id}/comments/{comment_id}",
            json={
                "body_md": "Updated text",
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["body_md"] == "Updated text"

    def test_soft_delete_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test soft-deleting a comment."""
        client = make_test_client()

        loop_resp = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test loop",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_id = loop_resp.json()["id"]

        comment_resp = client.post(
            f"/loops/{loop_id}/comments",
            json={
                "author": "Alice",
                "body_md": "To be deleted",
            },
        )
        comment_id = comment_resp.json()["id"]

        # Delete
        delete_resp = client.delete(f"/loops/{loop_id}/comments/{comment_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True

        # Verify it's soft-deleted (not returned by default)
        list_resp = client.get(f"/loops/{loop_id}/comments")
        assert list_resp.json()["total_count"] == 0

        # Verify it shows with include_deleted
        list_resp = client.get(f"/loops/{loop_id}/comments?include_deleted=true")
        assert list_resp.json()["total_count"] == 1
        assert list_resp.json()["comments"][0]["is_deleted"] is True

    def test_comment_on_nonexistent_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test that commenting on a nonexistent loop returns 404."""
        client = make_test_client()

        resp = client.post(
            "/loops/99999/comments",
            json={
                "author": "Alice",
                "body_md": "Test",
            },
        )
        assert resp.status_code == 404

    def test_reply_to_wrong_loop_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
    ) -> None:
        """Test that replying to a comment from a different loop fails."""
        client = make_test_client()

        # Create two loops
        loop1 = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop 1",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        ).json()

        loop2 = client.post(
            "/loops/capture",
            json={
                "raw_text": "Loop 2",
                "captured_at": "2026-02-15T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        ).json()

        # Comment on loop1
        comment = client.post(
            f"/loops/{loop1['id']}/comments",
            json={
                "author": "Alice",
                "body_md": "Comment on loop 1",
            },
        ).json()

        # Try to reply on loop2 using loop1's comment as parent
        resp = client.post(
            f"/loops/{loop2['id']}/comments",
            json={
                "author": "Bob",
                "body_md": "Invalid reply",
                "parent_id": comment["id"],
            },
        )
        assert resp.status_code == 400  # ValidationError


# =============================================================================
# Comment Event Tests
# =============================================================================


def test_comment_events_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that comment events are recorded in loop event history."""
    client = make_test_client()

    # Create a loop
    loop_resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop for comment events",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    loop_id = loop_resp.json()["id"]

    # Add a comment
    comment = client.post(
        f"/loops/{loop_id}/comments",
        json={"author": "Alice", "body_md": "Test comment"},
    ).json()

    # Get events
    events_resp = client.get(f"/loops/{loop_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()["events"]

    # Find comment_added event
    comment_events = [e for e in events if e["event_type"] == "comment_added"]
    assert len(comment_events) == 1
    assert comment_events[0]["payload"]["comment_id"] == comment["id"]
    assert comment_events[0]["payload"]["author"] == "Alice"


# =============================================================================
# Comment Idempotency Tests
# =============================================================================


def test_comment_create_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload returns same comment without duplicate."""
    client = make_test_client()

    # Create a loop
    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    payload = {"author": "Alice", "body_md": "Test comment"}
    headers = {"Idempotency-Key": "comment-key-123"}

    response1 = client.post(f"/loops/{loop['id']}/comments", json=payload, headers=headers)
    assert response1.status_code == 201
    comment1 = response1.json()

    response2 = client.post(f"/loops/{loop['id']}/comments", json=payload, headers=headers)
    assert response2.status_code == 201
    comment2 = response2.json()

    # Same comment returned
    assert comment1["id"] == comment2["id"]

    # Only one comment exists
    list_resp = client.get(f"/loops/{loop['id']}/comments")
    assert len(list_resp.json()["comments"]) == 1


def test_comment_create_idempotency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + different payload returns 409 Conflict."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    payload1 = {"author": "Alice", "body_md": "First comment"}
    payload2 = {"author": "Bob", "body_md": "Different comment"}
    headers = {"Idempotency-Key": "conflict-comment-key"}

    response1 = client.post(f"/loops/{loop['id']}/comments", json=payload1, headers=headers)
    assert response1.status_code == 201

    response2 = client.post(f"/loops/{loop['id']}/comments", json=payload2, headers=headers)
    assert response2.status_code == 409
    assert "idempotency_key_conflict" in str(response2.json())


def test_comment_update_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key + same payload updates comment once."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    comment = client.post(
        f"/loops/{loop['id']}/comments",
        json={"author": "Alice", "body_md": "Original"},
    ).json()

    payload = {"body_md": "Updated content"}
    headers = {"Idempotency-Key": "update-key-456"}

    response1 = client.patch(
        f"/loops/{loop['id']}/comments/{comment['id']}", json=payload, headers=headers
    )
    assert response1.status_code == 200

    response2 = client.patch(
        f"/loops/{loop['id']}/comments/{comment['id']}", json=payload, headers=headers
    )
    assert response2.status_code == 200
    assert response2.json()["body_md"] == "Updated content"


def test_comment_delete_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Same idempotency key replay on delete returns same result."""
    client = make_test_client()

    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2026-02-15T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    comment = client.post(
        f"/loops/{loop['id']}/comments",
        json={"author": "Alice", "body_md": "To delete"},
    ).json()

    headers = {"Idempotency-Key": "delete-key-789"}

    response1 = client.delete(f"/loops/{loop['id']}/comments/{comment['id']}", headers=headers)
    assert response1.status_code == 200
    assert response1.json()["deleted"] is True

    response2 = client.delete(f"/loops/{loop['id']}/comments/{comment['id']}", headers=headers)
    assert response2.status_code == 200
    assert response2.json()["deleted"] is True
