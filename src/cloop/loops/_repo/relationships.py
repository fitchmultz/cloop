"""Loop relationship-link repository operations.

Purpose:
    Persist duplicate/related loop link rows and their review state.

Responsibilities:
    - Insert or authoritatively update loop relationship links
    - List relationship links by loop and state filters
    - Support batch relationship lookups for review workflows

Non-scope:
    - Similarity embedding storage
    - Review-session metadata persistence
    - Core loop CRUD or tag/project metadata
"""

from __future__ import annotations

import sqlite3
from typing import Any


def insert_loop_link(
    *,
    loop_id: int,
    related_loop_id: int,
    relationship_type: str,
    confidence: float | None,
    source: str,
    conn: sqlite3.Connection,
) -> None:
    """Record an AI/background relationship suggestion without reviving dismissed state.

    Existing active suggestions are refreshed in place, but dismissed or resolved
    links stay untouched so product review decisions remain authoritative.
    """
    conn.execute(
        """
        INSERT INTO loop_links (
            loop_id,
            related_loop_id,
            relationship_type,
            link_state,
            confidence,
            source
        )
        VALUES (?, ?, ?, 'active', ?, ?)
        ON CONFLICT(loop_id, related_loop_id, relationship_type) DO UPDATE SET
            confidence = excluded.confidence,
            source = excluded.source,
            updated_at = CURRENT_TIMESTAMP
        WHERE loop_links.link_state = 'active'
        """,
        (loop_id, related_loop_id, relationship_type, confidence, source),
    )


def upsert_loop_link(
    *,
    loop_id: int,
    related_loop_id: int,
    relationship_type: str,
    link_state: str,
    confidence: float | None,
    source: str,
    conn: sqlite3.Connection,
) -> None:
    """Authoritatively set relationship state for a loop pair in one direction."""
    conn.execute(
        """
        INSERT INTO loop_links (
            loop_id,
            related_loop_id,
            relationship_type,
            link_state,
            confidence,
            source
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(loop_id, related_loop_id, relationship_type) DO UPDATE SET
            link_state = excluded.link_state,
            confidence = excluded.confidence,
            source = excluded.source,
            updated_at = CURRENT_TIMESTAMP
        """,
        (loop_id, related_loop_id, relationship_type, link_state, confidence, source),
    )


def delete_loop_link(
    *,
    loop_id: int,
    related_loop_id: int,
    relationship_type: str,
    conn: sqlite3.Connection,
) -> bool:
    """Delete one authoritative relationship row if it exists."""
    cursor = conn.execute(
        """
        DELETE FROM loop_links
        WHERE loop_id = ? AND related_loop_id = ? AND relationship_type = ?
        """,
        (loop_id, related_loop_id, relationship_type),
    )
    return cursor.rowcount > 0


def list_loop_links_by_type(
    *,
    loop_id: int,
    relationship_type: str,
    conn: sqlite3.Connection,
    link_state: str | None = "active",
) -> list[dict[str, Any]]:
    """List loop links of a specific relationship type.

    Args:
        loop_id: Loop to query
        relationship_type: Type of relationship (e.g., 'duplicate', 'related')
        conn: Database connection
        link_state: Optional link state filter (`active`, `dismissed`, `resolved`, or None)

    Returns:
        List of link dicts with related_loop_id, confidence, source, state, and timestamps.
    """
    sql = """
        SELECT related_loop_id,
               relationship_type,
               link_state,
               confidence,
               source,
               created_at,
               updated_at
        FROM loop_links
        WHERE loop_id = ? AND relationship_type = ?
    """
    params: list[Any] = [loop_id, relationship_type]
    if link_state is not None:
        sql += " AND link_state = ?"
        params.append(link_state)
    sql += " ORDER BY confidence DESC, related_loop_id ASC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_loop_links_for_loop_ids(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
    relationship_types: list[str] | None = None,
    link_states: list[str] | None = None,
) -> list[dict[str, Any]]:
    """List relationship rows for a batch of source loop IDs."""
    if not loop_ids:
        return []

    conditions = [f"loop_id IN ({', '.join('?' for _ in loop_ids)})"]
    params: list[Any] = list(loop_ids)

    if relationship_types:
        conditions.append(f"relationship_type IN ({', '.join('?' for _ in relationship_types)})")
        params.extend(relationship_types)
    if link_states:
        conditions.append(f"link_state IN ({', '.join('?' for _ in link_states)})")
        params.extend(link_states)

    sql = f"""
        SELECT loop_id,
               related_loop_id,
               relationship_type,
               link_state,
               confidence,
               source,
               created_at,
               updated_at
        FROM loop_links
        WHERE {" AND ".join(conditions)}
        ORDER BY loop_id ASC, confidence DESC, related_loop_id ASC
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
