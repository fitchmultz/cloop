"""Loop comment repository operations.

Purpose:
    Persist threaded loop comments and soft-delete state.

Responsibilities:
    - Create, read, list, update, soft-delete, and count comments
    - Convert comment rows into LoopComment domain models
    - Support threaded comment retrieval ordering

Non-scope:
    - Comment-route orchestration or webhook side effects
    - Event-history persistence outside comment rows
    - Core loop CRUD or timer storage
"""

from __future__ import annotations

import sqlite3

from ..errors import CommentNotFoundError
from ..models import LoopComment, parse_utc_datetime


def _row_to_comment(row: sqlite3.Row) -> LoopComment:
    """Convert a database row to a LoopComment."""
    return LoopComment(
        id=row["id"],
        loop_id=row["loop_id"],
        parent_id=row["parent_id"],
        author=row["author"],
        body_md=row["body_md"],
        created_at_utc=parse_utc_datetime(row["created_at"]),
        updated_at_utc=parse_utc_datetime(row["updated_at"]),
        deleted_at_utc=parse_utc_datetime(row["deleted_at"]) if row["deleted_at"] else None,
    )


def create_comment(
    *,
    loop_id: int,
    author: str,
    body_md: str,
    parent_id: int | None = None,
    conn: sqlite3.Connection,
) -> LoopComment:
    """Create a new comment on a loop.

    Args:
        loop_id: Loop to comment on
        author: Comment author identifier
        body_md: Markdown body text
        parent_id: Optional parent comment ID for replies
        conn: Database connection

    Returns:
        The created LoopComment
    """
    cursor = conn.execute(
        """
        INSERT INTO loop_comments (loop_id, parent_id, author, body_md)
        VALUES (?, ?, ?, ?)
        """,
        (loop_id, parent_id, author, body_md),
    )
    comment_id = cursor.lastrowid
    if comment_id is None:
        raise RuntimeError("comment_create_failed")

    row = conn.execute("SELECT * FROM loop_comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise RuntimeError("comment_fetch_failed")

    return _row_to_comment(row)


def list_comments(
    *,
    loop_id: int,
    include_deleted: bool = False,
    conn: sqlite3.Connection,
) -> list[LoopComment]:
    """List all comments for a loop, ordered for thread display.

    Returns comments ordered by:
    1. Parent comments first (parent_id IS NULL)
    2. Then replies grouped under parents
    3. Within each group, by created_at ASC

    Args:
        loop_id: Loop to list comments for
        include_deleted: Whether to include soft-deleted comments
        conn: Database connection

    Returns:
        List of LoopComment objects in thread order
    """
    deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"

    rows = conn.execute(
        f"""
        SELECT * FROM loop_comments
        WHERE loop_id = ? {deleted_filter}
        ORDER BY
            COALESCE(parent_id, id) ASC,
            parent_id IS NULL DESC,
            created_at ASC
        """,
        (loop_id,),
    ).fetchall()

    return [_row_to_comment(row) for row in rows]


def get_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> LoopComment | None:
    """Get a single comment by ID.

    Args:
        comment_id: Comment ID
        conn: Database connection

    Returns:
        LoopComment or None if not found
    """
    row = conn.execute(
        "SELECT * FROM loop_comments WHERE id = ?",
        (comment_id,),
    ).fetchone()
    return _row_to_comment(row) if row else None


def update_comment(
    *,
    comment_id: int,
    body_md: str,
    conn: sqlite3.Connection,
) -> LoopComment:
    """Update a comment's body.

    Args:
        comment_id: Comment to update
        body_md: New markdown body
        conn: Database connection

    Returns:
        Updated LoopComment

    Raises:
        CommentNotFoundError: If comment not found or deleted
    """
    cursor = conn.execute(
        """
        UPDATE loop_comments
        SET body_md = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND deleted_at IS NULL
        """,
        (body_md, comment_id),
    )
    if cursor.rowcount == 0:
        raise CommentNotFoundError(comment_id)

    row = conn.execute("SELECT * FROM loop_comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise RuntimeError("comment_fetch_failed")

    return _row_to_comment(row)


def soft_delete_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Soft-delete a comment (sets deleted_at timestamp).

    Args:
        comment_id: Comment to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found or already deleted
    """
    cursor = conn.execute(
        """
        UPDATE loop_comments
        SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND deleted_at IS NULL
        """,
        (comment_id,),
    )
    return cursor.rowcount > 0


def count_comments(
    *,
    loop_id: int,
    include_deleted: bool = False,
    conn: sqlite3.Connection,
) -> int:
    """Count comments for a loop.

    Args:
        loop_id: Loop to count comments for
        include_deleted: Whether to include soft-deleted comments
        conn: Database connection

    Returns:
        Number of comments
    """
    deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count FROM loop_comments
        WHERE loop_id = ? {deleted_filter}
        """,
        (loop_id,),
    ).fetchone()

    return int(row["count"]) if row else 0
