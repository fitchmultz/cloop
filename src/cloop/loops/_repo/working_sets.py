"""Working-set repository operations.

Purpose:
    Persist durable working sets, ordered membership rows, and the singleton
    active-focus context used by the operator shell.

Responsibilities:
    - Create, list, update, and delete working sets
    - Create, list, reorder, and delete working-set membership rows
    - Read and update the singleton working-set focus context
    - Persist working-set mutation events used for deterministic undo

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
from collections.abc import Mapping
from typing import Any

from ..errors import ValidationError
from .shared import _UNSET


def _raise_working_set_name_conflict(name: str) -> None:
    """Raise the canonical duplicate-name validation error."""
    raise ValidationError("name", f"working set '{name}' already exists") from None


def create_working_set(
    *,
    name: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a durable working set and return the stored row."""
    try:
        cursor = conn.execute(
            """
            INSERT INTO working_sets (name, description)
            VALUES (?, ?)
            """,
            (name, description),
        )
    except sqlite3.IntegrityError:
        _raise_working_set_name_conflict(name)
    row = conn.execute("SELECT * FROM working_sets WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise RuntimeError("working_set_insert_failed")
    return dict(row)


def restore_working_set(
    *,
    snapshot: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Insert or replace one working-set row from an exact snapshot."""
    try:
        conn.execute(
            """
            INSERT INTO working_sets (
                id,
                name,
                description,
                last_activated_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                last_activated_at = excluded.last_activated_at,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                snapshot["id"],
                snapshot["name"],
                snapshot.get("description"),
                snapshot.get("last_activated_at"),
                snapshot["created_at"],
                snapshot["updated_at"],
            ),
        )
    except sqlite3.IntegrityError:
        _raise_working_set_name_conflict(str(snapshot["name"]))
    row = conn.execute("SELECT * FROM working_sets WHERE id = ?", (snapshot["id"],)).fetchone()
    if row is None:
        raise RuntimeError("working_set_restore_failed")
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
    try:
        conn.execute(
            f"""
            UPDATE working_sets
            SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            params,
        )
    except sqlite3.IntegrityError:
        if name is not None:
            _raise_working_set_name_conflict(name)
        raise
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


def restore_working_set_item(
    *,
    snapshot: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Insert or replace one working-set membership row from a snapshot."""
    conn.execute(
        """
        INSERT INTO working_set_items (
            id,
            working_set_id,
            item_type,
            item_id,
            label,
            description,
            metadata_json,
            position,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            working_set_id = excluded.working_set_id,
            item_type = excluded.item_type,
            item_id = excluded.item_id,
            label = excluded.label,
            description = excluded.description,
            metadata_json = excluded.metadata_json,
            position = excluded.position,
            created_at = excluded.created_at
        """,
        (
            snapshot["id"],
            snapshot["working_set_id"],
            snapshot["item_type"],
            snapshot.get("item_id"),
            snapshot["label"],
            snapshot.get("description"),
            json.dumps(dict(snapshot.get("metadata") or {})),
            snapshot["position"],
            snapshot["created_at"],
        ),
    )
    row = conn.execute("SELECT * FROM working_set_items WHERE id = ?", (snapshot["id"],)).fetchone()
    if row is None:
        raise RuntimeError("working_set_item_restore_failed")
    return dict(row)


def replace_working_set_items(
    *,
    working_set_id: int,
    snapshots: list[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Replace one working set's membership rows with an exact ordered snapshot."""
    conn.execute("DELETE FROM working_set_items WHERE working_set_id = ?", (working_set_id,))
    restored = [restore_working_set_item(snapshot=snapshot, conn=conn) for snapshot in snapshots]
    return sorted(restored, key=lambda row: (int(row["position"]), int(row["id"])))


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


def insert_working_set_event(
    *,
    subject_type: str,
    subject_id: int,
    event_type: str,
    before_state: Mapping[str, Any],
    after_state: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Insert one working-set mutation event and return its ID."""
    cursor = conn.execute(
        """
        INSERT INTO working_set_events (
            subject_type,
            subject_id,
            event_type,
            before_state_json,
            after_state_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            subject_type,
            subject_id,
            event_type,
            json.dumps(dict(before_state)),
            json.dumps(dict(after_state)),
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("working_set_event_insert_failed")
    return int(cursor.lastrowid)


def get_working_set_event(*, event_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Read one working-set mutation event by ID."""
    row = conn.execute(
        "SELECT * FROM working_set_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    return dict(row) if row else None


def mark_working_set_event_undone(
    *,
    event_id: int,
    undo_event_id: int,
    conn: sqlite3.Connection,
) -> None:
    """Mark one working-set event as already undone by another event."""
    conn.execute(
        "UPDATE working_set_events SET undone_by_event_id = ? WHERE id = ?",
        (undo_event_id, event_id),
    )


def get_latest_reversible_working_set_event(
    *,
    subject_type: str,
    subject_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Read the latest reversible event for one working-set subject."""
    row = conn.execute(
        """
        SELECT *
        FROM working_set_events
        WHERE subject_type = ?
          AND subject_id = ?
          AND event_type != 'undo'
          AND undone_by_event_id IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (subject_type, subject_id),
    ).fetchone()
    return dict(row) if row else None
