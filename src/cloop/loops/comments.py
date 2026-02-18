"""Loop comment service layer.

Purpose:
    Provide high-level business operations for loop comment management,
    including creation, retrieval, listing, updating, and soft-deletion.

Responsibilities:
    - Enforce business rules for comment operations
    - Validate loop existence and comment relationships
    - Build nested comment tree structures
    - Emit domain events for audit trail and webhook delivery
    - Handle soft-delete semantics

Non-scope:
    - Direct database access (see repo.py)
    - HTTP request/response handling (see routes/loops.py)
    - Raw comment formatting/display (handled by caller)
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from .. import typingx
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import LoopNotFoundError, ValidationError
from .models import LoopEventType, format_utc_datetime

if TYPE_CHECKING:
    from .models import LoopComment


def _comment_to_dict(comment: "LoopComment") -> dict[str, Any]:
    """Convert LoopComment to dict for API response."""
    return {
        "id": comment.id,
        "loop_id": comment.loop_id,
        "parent_id": comment.parent_id,
        "author": comment.author,
        "body_md": comment.body_md,
        "created_at_utc": format_utc_datetime(comment.created_at_utc),
        "updated_at_utc": format_utc_datetime(comment.updated_at_utc),
        "deleted_at_utc": format_utc_datetime(comment.deleted_at_utc)
        if comment.deleted_at_utc
        else None,
        "is_deleted": comment.is_deleted,
        "is_reply": comment.is_reply,
    }


@typingx.validate_io()
def create_loop_comment(
    *,
    loop_id: int,
    author: str,
    body_md: str,
    parent_id: int | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a comment on a loop.

    Args:
        loop_id: Loop to comment on
        author: Comment author
        body_md: Markdown body
        parent_id: Optional parent comment ID for replies
        conn: Database connection

    Returns:
        Comment dict for API response

    Raises:
        LoopNotFoundError: If loop doesn't exist
        ValidationError: If parent comment doesn't belong to same loop
    """
    from .repo import create_comment, get_comment, read_loop

    # Verify loop exists
    loop = read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    # Verify parent belongs to same loop if specified
    if parent_id is not None:
        parent = get_comment(comment_id=parent_id, conn=conn)
        if parent is None or parent.loop_id != loop_id:
            raise ValidationError(
                "parent_id", "Parent comment not found or belongs to different loop"
            )

    comment = create_comment(
        loop_id=loop_id,
        author=author,
        body_md=body_md,
        parent_id=parent_id,
        conn=conn,
    )
    conn.commit()

    # Record event for audit trail
    event_payload = {
        "comment_id": comment.id,
        "author": author,
        "parent_id": parent_id,
    }
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.COMMENT_ADDED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.COMMENT_ADDED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()

    return _comment_to_dict(comment)


@typingx.validate_io()
def list_loop_comments(
    *,
    loop_id: int,
    include_deleted: bool = False,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """List comments for a loop in threaded order.

    Args:
        loop_id: Loop to list comments for
        include_deleted: Whether to include soft-deleted comments
        conn: Database connection

    Returns:
        Dict with loop_id, comments (nested tree), and total_count
    """
    from .repo import count_comments, list_comments, read_loop

    # Verify loop exists
    loop = read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    comments = list_comments(loop_id=loop_id, include_deleted=include_deleted, conn=conn)
    total = count_comments(loop_id=loop_id, include_deleted=include_deleted, conn=conn)

    # Build nested tree structure
    comment_map = {c.id: _comment_to_dict(c) for c in comments}
    root_comments: list[dict[str, Any]] = []

    for comment in comments:
        comment_dict = comment_map[comment.id]
        comment_dict["replies"] = []

        if comment.parent_id is None:
            root_comments.append(comment_dict)
        elif comment.parent_id in comment_map:
            comment_map[comment.parent_id]["replies"].append(comment_dict)

    return {
        "loop_id": loop_id,
        "comments": root_comments,
        "total_count": total,
    }


@typingx.validate_io()
def get_loop_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get a single comment by ID.

    Args:
        comment_id: Comment ID
        conn: Database connection

    Returns:
        Comment dict or None
    """
    from .repo import get_comment

    comment = get_comment(comment_id=comment_id, conn=conn)
    if comment is None:
        return None
    return _comment_to_dict(comment)


@typingx.validate_io()
def update_loop_comment(
    *,
    comment_id: int,
    body_md: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a comment's body.

    Args:
        comment_id: Comment to update
        body_md: New markdown body
        conn: Database connection

    Returns:
        Updated comment dict

    Raises:
        RuntimeError: If comment not found or deleted
    """
    from .repo import update_comment

    comment = update_comment(comment_id=comment_id, body_md=body_md, conn=conn)
    conn.commit()

    # Record event
    event_payload = {"comment_id": comment.id}
    event_id = repo.insert_loop_event(
        loop_id=comment.loop_id,
        event_type=LoopEventType.COMMENT_UPDATED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.COMMENT_UPDATED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()

    return _comment_to_dict(comment)


@typingx.validate_io()
def delete_loop_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Soft-delete a comment.

    Args:
        comment_id: Comment to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found
    """
    from .repo import get_comment, soft_delete_comment

    comment = get_comment(comment_id=comment_id, conn=conn)
    if comment is None:
        return False

    deleted = soft_delete_comment(comment_id=comment_id, conn=conn)

    if deleted:
        # Record event
        event_payload = {"comment_id": comment.id}
        event_id = repo.insert_loop_event(
            loop_id=comment.loop_id,
            event_type=LoopEventType.COMMENT_DELETED.value,
            payload=event_payload,
            conn=conn,
        )
        conn.commit()
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.COMMENT_DELETED.value,
            payload=event_payload,
            conn=conn,
        )
        conn.commit()

    return deleted
