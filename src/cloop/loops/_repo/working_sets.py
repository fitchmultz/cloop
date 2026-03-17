"""Working-set repository operations.

Purpose:
    Persist durable working sets, ordered membership rows, and the singleton
    active-focus context used by the operator shell.

Responsibilities:
    - Create, list, update, and delete working sets
    - Create, list, reorder, and delete working-set membership rows
    - Read and update the singleton working-set focus context

Scope:
    - SQLite persistence helpers for working-set tables only

Usage:
    - Imported through `cloop.loops.repo` by the working-set service layer

Invariants/Assumptions:
    - Position ordering is contiguous within each working set
    - The focus context remains a singleton row with `singleton_id = 1`

Non-scope:
    - Resolving loop/planning/review payloads for presentation
    - Shell routing or UI-specific rendering decisions
    - Cross-object validation beyond direct row existence checks
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .shared import _UNSET


def create_working_set(
    *,
    name: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a durable working set and return the stored row."""
    cursor = conn.execute(
        """
        INSERT INTO working_sets (name, description)
        VALUES (?, ?)
        """,
        (name, description),
    )
    row = conn.execute("SELECT * FROM working_sets WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise RuntimeError("working_set_insert_failed")
    return dict(row)


def list_working_sets(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List working sets ordered by last activation and update recency."""
    rows = conn.execute(
        """
        SELECT *
        FROM working_sets
        ORDER BY
            CASE WHEN last_activated_at IS NULL THEN 1 ELSE 0 END ASC,
            last_activated_at DESC,
            updated_at DESC,
            id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_working_set(*, working_set_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get one working set row by id."""
    row = conn.execute("SELECT * FROM working_sets WHERE id = ?", (working_set_id,)).fetchone()
    return dict(row) if row else None


def update_working_set(
    *,
    working_set_id: int,
    name: str | None = None,
    description: str | None | object = _UNSET,
    last_activated_at: str | None | object = _UNSET,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Update working-set metadata and return the updated row."""
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not _UNSET:
        updates.append("description = ?")
        params.append(description)
    if last_activated_at is not _UNSET:
        updates.append("last_activated_at = ?")
        params.append(last_activated_at)
    if not updates:
        return get_working_set(working_set_id=working_set_id, conn=conn)
    params.append(working_set_id)
    conn.execute(
        f"""
        UPDATE working_sets
        SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        params,
    )
    return get_working_set(working_set_id=working_set_id, conn=conn)


def delete_working_set(*, working_set_id: int, conn: sqlite3.Connection) -> bool:
    """Delete one working set row."""
    cursor = conn.execute("DELETE FROM working_sets WHERE id = ?", (working_set_id,))
    return cursor.rowcount > 0


def list_working_set_items(
    *, working_set_id: int, conn: sqlite3.Connection
) -> list[dict[str, Any]]:
    """List ordered working-set items for one set."""
    rows = conn.execute(
        """
        SELECT *
        FROM working_set_items
        WHERE working_set_id = ?
        ORDER BY position ASC, id ASC
        """,
        (working_set_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_working_set_item(
    *,
    working_set_id: int,
    item_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get one working-set item row by parent set and item id."""
    row = conn.execute(
        "SELECT * FROM working_set_items WHERE working_set_id = ? AND id = ?",
        (working_set_id, item_id),
    ).fetchone()
    return dict(row) if row else None


def create_working_set_item(
    *,
    working_set_id: int,
    item_type: str,
    item_id: int | None,
    label: str,
    description: str | None,
    metadata_json: dict[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Insert one item at the front of a working set."""
    conn.execute(
        "UPDATE working_set_items SET position = position + 1 WHERE working_set_id = ?",
        (working_set_id,),
    )
    cursor = conn.execute(
        """
        INSERT INTO working_set_items (
            working_set_id,
            item_type,
            item_id,
            label,
            description,
            metadata_json,
            position
        )
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (working_set_id, item_type, item_id, label, description, json.dumps(metadata_json)),
    )
    row = conn.execute(
        "SELECT * FROM working_set_items WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    if row is None:
        raise RuntimeError("working_set_item_insert_failed")
    return dict(row)


def update_working_set_item(
    *,
    working_set_id: int,
    item_id: int,
    label: str | None = None,
    description: str | None | object = _UNSET,
    metadata_json: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Update one working-set item and return the stored row."""
    updates: list[str] = []
    params: list[Any] = []
    if label is not None:
        updates.append("label = ?")
        params.append(label)
    if description is not _UNSET:
        updates.append("description = ?")
        params.append(description)
    if metadata_json is not None:
        updates.append("metadata_json = ?")
        params.append(json.dumps(metadata_json))
    if not updates:
        return get_working_set_item(working_set_id=working_set_id, item_id=item_id, conn=conn)
    params.extend([working_set_id, item_id])
    conn.execute(
        f"""
        UPDATE working_set_items
        SET {", ".join(updates)}
        WHERE working_set_id = ? AND id = ?
        """,
        params,
    )
    return get_working_set_item(working_set_id=working_set_id, item_id=item_id, conn=conn)


def delete_working_set_item(*, working_set_id: int, item_id: int, conn: sqlite3.Connection) -> bool:
    """Delete one membership row and compact remaining positions."""
    row = conn.execute(
        "SELECT position FROM working_set_items WHERE working_set_id = ? AND id = ?",
        (working_set_id, item_id),
    ).fetchone()
    if row is None:
        return False
    position = int(row["position"])
    cursor = conn.execute(
        "DELETE FROM working_set_items WHERE working_set_id = ? AND id = ?",
        (working_set_id, item_id),
    )
    conn.execute(
        """
        UPDATE working_set_items
        SET position = position - 1
        WHERE working_set_id = ? AND position > ?
        """,
        (working_set_id, position),
    )
    return cursor.rowcount > 0


def reorder_working_set_items(
    *,
    working_set_id: int,
    ordered_item_ids: list[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Rewrite ordered positions for one working set."""
    for position, item_id in enumerate(ordered_item_ids):
        conn.execute(
            "UPDATE working_set_items SET position = ? WHERE working_set_id = ? AND id = ?",
            (position, working_set_id, item_id),
        )
    return list_working_set_items(working_set_id=working_set_id, conn=conn)


def _ensure_working_set_context_row(*, conn: sqlite3.Connection) -> None:
    """Ensure the singleton focus-context row exists."""
    conn.execute(
        """
        INSERT INTO working_set_context (singleton_id, active_working_set_id, focus_mode_enabled)
        VALUES (1, NULL, 0)
        ON CONFLICT(singleton_id) DO NOTHING
        """
    )


def get_working_set_context(*, conn: sqlite3.Connection) -> dict[str, Any]:
    """Read the singleton working-set focus context."""
    _ensure_working_set_context_row(conn=conn)
    row = conn.execute("SELECT * FROM working_set_context WHERE singleton_id = 1").fetchone()
    if row is None:
        raise RuntimeError("working_set_context_missing")
    return dict(row)


def update_working_set_context(
    *,
    active_working_set_id: int | None,
    focus_mode_enabled: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update and return the singleton working-set focus context."""
    _ensure_working_set_context_row(conn=conn)
    conn.execute(
        """
        UPDATE working_set_context
        SET active_working_set_id = ?,
            focus_mode_enabled = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE singleton_id = 1
        """,
        (active_working_set_id, 1 if focus_mode_enabled else 0),
    )
    return get_working_set_context(conn=conn)
