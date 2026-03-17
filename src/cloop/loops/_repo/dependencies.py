"""Loop dependency-graph repository operations.

Purpose:
    Persist parent/child and depends-on relationships between loops.

Responsibilities:
    - Create and remove dependency edges
    - List dependencies, dependents, and children
    - Support cycle detection and open-dependency checks

Non-scope:
    - Relationship-review links for duplicates/related work
    - Core loop-row CRUD or comments
    - Claims, timers, or review-session persistence
"""

from __future__ import annotations

import sqlite3

from ..models import LoopRecord
from .shared import _row_to_record


def add_dependency(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> int:
    """Add a dependency relationship (loop_id depends_on depends_on_loop_id).

    Args:
        loop_id: The loop that is blocked
        depends_on_loop_id: The loop that blocks it
        conn: Database connection

    Returns:
        The dependency record ID

    Raises:
        sqlite3.IntegrityError: If dependency already exists
    """
    cursor = conn.execute(
        """
        INSERT INTO loop_dependencies (loop_id, depends_on_loop_id)
        VALUES (?, ?)
        """,
        (loop_id, depends_on_loop_id),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("add_dependency_failed")
    return int(cursor.lastrowid)


def remove_dependency(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Remove a dependency relationship.

    Args:
        loop_id: The blocked loop
        depends_on_loop_id: The loop it depended on
        conn: Database connection

    Returns:
        True if removed, False if not found
    """
    cursor = conn.execute(
        """
        DELETE FROM loop_dependencies
        WHERE loop_id = ? AND depends_on_loop_id = ?
        """,
        (loop_id, depends_on_loop_id),
    )
    return cursor.rowcount > 0


def list_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """List all loop IDs that this loop depends on (its blockers).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of loop IDs that this loop depends on
    """
    rows = conn.execute(
        """
        SELECT depends_on_loop_id
        FROM loop_dependencies
        WHERE loop_id = ?
        ORDER BY depends_on_loop_id
        """,
        (loop_id,),
    ).fetchall()
    return [row["depends_on_loop_id"] for row in rows]


def list_dependents(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """List all loop IDs that depend on this loop (its dependents).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of loop IDs that depend on this loop
    """
    rows = conn.execute(
        """
        SELECT loop_id
        FROM loop_dependencies
        WHERE depends_on_loop_id = ?
        ORDER BY loop_id
        """,
        (loop_id,),
    ).fetchall()
    return [row["loop_id"] for row in rows]


def list_open_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """List dependency loop IDs that are NOT closed (completed/dropped).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of open dependency loop IDs
    """
    rows = conn.execute(
        """
        SELECT ld.depends_on_loop_id
        FROM loop_dependencies ld
        JOIN loops l ON l.id = ld.depends_on_loop_id
        WHERE ld.loop_id = ?
          AND l.status NOT IN ('completed', 'dropped')
        ORDER BY ld.depends_on_loop_id
        """,
        (loop_id,),
    ).fetchall()
    return [row["depends_on_loop_id"] for row in rows]


def has_open_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Check if a loop has any open (unsatisfied) dependencies.

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        True if there are open dependencies, False otherwise
    """
    row = conn.execute(
        """
        SELECT 1
        FROM loop_dependencies ld
        JOIN loops l ON l.id = ld.depends_on_loop_id
        WHERE ld.loop_id = ?
          AND l.status NOT IN ('completed', 'dropped')
        LIMIT 1
        """,
        (loop_id,),
    ).fetchone()
    return row is not None


def has_open_dependencies_batch(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
) -> set[int]:
    """Check for open dependencies for multiple loops in a single query.

    Args:
        loop_ids: List of loop IDs to check
        conn: Database connection

    Returns:
        Set of loop IDs that have open dependencies
    """
    if not loop_ids:
        return set()

    placeholders = ", ".join("?" for _ in loop_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT ld.loop_id
        FROM loop_dependencies ld
        JOIN loops l ON l.id = ld.depends_on_loop_id
        WHERE ld.loop_id IN ({placeholders})
          AND l.status NOT IN ('completed', 'dropped')
        """,
        loop_ids,
    ).fetchall()
    return {row["loop_id"] for row in rows}


def detect_dependency_cycle(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Check if adding loop_id -> depends_on_loop_id would create a cycle.

    A cycle exists if depends_on_loop_id can reach loop_id through existing
    dependencies (transitively). Also rejects self-dependencies.

    Args:
        loop_id: The loop that would become blocked
        depends_on_loop_id: The loop that would become the blocker
        conn: Database connection

    Returns:
        True if adding this dependency would create a cycle
    """
    if loop_id == depends_on_loop_id:
        return True

    # BFS/DFS to check if depends_on_loop_id can reach loop_id
    visited: set[int] = set()
    queue = [depends_on_loop_id]

    while queue:
        current = queue.pop(0)
        if current == loop_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        # Find what 'current' depends on (its blockers)
        rows = conn.execute(
            """
            SELECT depends_on_loop_id
            FROM loop_dependencies
            WHERE loop_id = ?
            """,
            (current,),
        ).fetchall()
        for row in rows:
            dep_id = row["depends_on_loop_id"]
            if dep_id not in visited:
                queue.append(dep_id)

    return False


def list_children(
    *,
    parent_loop_id: int,
    conn: sqlite3.Connection,
) -> list[LoopRecord]:
    """List all child loops of a parent loop.

    Args:
        parent_loop_id: The parent loop ID
        conn: Database connection

    Returns:
        List of child LoopRecords
    """
    rows = conn.execute(
        """
        SELECT * FROM loops
        WHERE parent_loop_id = ?
        ORDER BY captured_at_utc ASC, id ASC
        """,
        (parent_loop_id,),
    ).fetchall()
    return [_row_to_record(row) for row in rows]
