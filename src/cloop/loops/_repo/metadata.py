"""Loop metadata repository operations.

Purpose:
    Own project and tag persistence that hangs off the core loop records.

Responsibilities:
    - Upsert and read projects
    - Upsert, batch-read, and replace tags
    - Provide batch helpers for transport/service shaping

Non-scope:
    - Core loop-row CRUD
    - Relationship links or embeddings
    - Saved views, templates, or review sessions
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..errors import ValidationError
from ..utils import normalize_tag, normalize_tags


def upsert_project(*, name: str, conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    if cursor.lastrowid is None:
        raise RuntimeError("project_insert_failed")
    return int(cursor.lastrowid)


def read_project_name(*, project_id: int | None, conn: sqlite3.Connection) -> str | None:
    if project_id is None:
        return None
    row = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row["name"] if row else None


def read_project_names_batch(*, project_ids: set[int], conn: sqlite3.Connection) -> dict[int, str]:
    """Fetch multiple project names in a single query.

    Returns a dict mapping project_id -> project_name.
    Project IDs that don't exist will be omitted from the result.
    """
    if not project_ids:
        return {}
    placeholders = ", ".join("?" for _ in project_ids)
    sql = f"SELECT id, name FROM projects WHERE id IN ({placeholders})"
    rows = conn.execute(sql, list(project_ids)).fetchall()
    return {int(row["id"]): row["name"] for row in rows}


def list_loop_tags_batch(*, loop_ids: list[int], conn: sqlite3.Connection) -> dict[int, list[str]]:
    """Fetch tags for multiple loops in a single query.

    Returns a dict mapping loop_id -> list of tag names.
    Loops with no tags will have an empty list.
    """
    if not loop_ids:
        return {}
    placeholders = ", ".join("?" for _ in loop_ids)
    sql = f"""
        SELECT loop_tags.loop_id, LOWER(tags.name) AS name
        FROM loop_tags
        JOIN tags ON tags.id = loop_tags.tag_id
        WHERE loop_tags.loop_id IN ({placeholders})
        ORDER BY loop_tags.loop_id, name ASC
    """
    rows = conn.execute(sql, loop_ids).fetchall()
    result: dict[int, list[str]] = {loop_id: [] for loop_id in loop_ids}
    for row in rows:
        loop_id = int(row["loop_id"])
        result.setdefault(loop_id, []).append(row["name"])
    return result


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM projects ORDER BY name ASC").fetchall()
    return [dict(row) for row in rows]


def upsert_tag(*, name: str, conn: sqlite3.Connection) -> int:
    normalized = normalize_tag(name)
    if not normalized:
        raise ValidationError("tag_name", "tag name cannot be empty")
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (normalized,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute("INSERT INTO tags (name) VALUES (?)", (normalized,))
    if cursor.lastrowid is None:
        raise RuntimeError("tag_insert_failed")
    return int(cursor.lastrowid)


def list_loop_tags(*, loop_id: int, conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT LOWER(tags.name) AS name
        FROM loop_tags
        JOIN tags ON tags.id = loop_tags.tag_id
        WHERE loop_tags.loop_id = ?
        ORDER BY name ASC
        """,
        (loop_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _upsert_tags_batch(*, tag_names: list[str], conn: sqlite3.Connection) -> dict[str, int]:
    """Batch upsert tags and return mapping of normalized_name -> tag_id.

    Performs O(1) queries regardless of tag count:
    1. SELECT existing tags WHERE name IN (...)
    2. INSERT new tags (if any) using executemany

    Args:
        tag_names: List of tag names (will be normalized)
        conn: Database connection

    Returns:
        Dict mapping normalized tag name to tag_id
    """
    # Normalize first, then dedupe while preserving order
    normalized = list(dict.fromkeys(normalize_tags(tag_names)))

    if not normalized:
        return {}

    # Batch fetch existing tags
    placeholders = ", ".join("?" for _ in normalized)
    rows = conn.execute(
        f"SELECT id, name FROM tags WHERE name IN ({placeholders})",
        normalized,
    ).fetchall()

    existing: dict[str, int] = {row["name"]: int(row["id"]) for row in rows}

    # Find new tags to insert
    new_tags = [name for name in normalized if name not in existing]

    if new_tags:
        # Batch insert new tags
        conn.executemany(
            "INSERT INTO tags (name) VALUES (?)",
            [(name,) for name in new_tags],
        )

        # Fetch IDs of newly inserted tags
        new_placeholders = ", ".join("?" for _ in new_tags)
        new_rows = conn.execute(
            f"SELECT id, name FROM tags WHERE name IN ({new_placeholders})",
            new_tags,
        ).fetchall()
        for row in new_rows:
            existing[row["name"]] = int(row["id"])

    return existing


def replace_loop_tags(*, loop_id: int, tag_names: list[str], conn: sqlite3.Connection) -> None:
    """Replace all tags for a loop with batch operations.

    Uses O(1) queries regardless of tag count:
    1. DELETE existing loop_tags
    2. Batch upsert tags (see _upsert_tags_batch)
    3. Batch insert loop_tags relationships
    4. DELETE orphaned tags

    Args:
        loop_id: Loop to update
        tag_names: New set of tag names
        conn: Database connection
    """
    # Step 1: Remove existing tag associations
    conn.execute("DELETE FROM loop_tags WHERE loop_id = ?", (loop_id,))

    # Step 2: Normalize tags
    normalized = normalize_tags(tag_names)
    if not normalized:
        # Still clean up orphaned tags
        conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM loop_tags)")
        return

    # Step 3: Batch upsert all tags, get name->id mapping
    name_to_id = _upsert_tags_batch(tag_names=normalized, conn=conn)

    # Step 4: Batch insert loop_tags relationships
    conn.executemany(
        "INSERT OR IGNORE INTO loop_tags (loop_id, tag_id) VALUES (?, ?)",
        [(loop_id, name_to_id[name]) for name in normalized],
    )

    # Step 5: Clean up orphaned tags
    conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM loop_tags)")
