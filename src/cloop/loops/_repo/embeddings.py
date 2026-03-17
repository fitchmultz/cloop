"""Loop embedding repository operations.

Purpose:
    Persist and retrieve loop embedding vectors and source-text metadata.

Responsibilities:
    - Read embeddings for one or many loops
    - Upsert embedding vectors and source hashes
    - Support semantic-search orchestration helpers

Non-scope:
    - Similarity scoring or embedding generation
    - Relationship-link persistence
    - Core loop CRUD and metadata writes
"""

from __future__ import annotations

import sqlite3
from typing import Any


def read_loop_embeddings_batch(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
) -> dict[int, dict[str, Any]]:
    """Read embedding rows for a batch of loop IDs."""
    if not loop_ids:
        return {}

    placeholders = ", ".join("?" for _ in loop_ids)
    rows = conn.execute(
        f"""
        SELECT loop_id, embedding_blob, embedding_dim, embedding_norm, embed_model, source_text_hash
        FROM loop_embeddings
        WHERE loop_id IN ({placeholders})
        """,
        loop_ids,
    ).fetchall()
    return {int(row["loop_id"]): dict(row) for row in rows}


def fetch_loop_embeddings(
    *,
    conn: sqlite3.Connection,
    limit: int | None = None,
    exclude_loop_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch loop embeddings with optional pagination.

    Args:
        conn: Database connection
        limit: Maximum number of embeddings to fetch (None = no limit)
        exclude_loop_id: Optional loop ID to exclude from results

    Returns:
        List of embedding records as dictionaries
    """
    sql = """
        SELECT loop_id, embedding_blob, embedding_dim, embedding_norm, embed_model, source_text_hash
        FROM loop_embeddings
    """
    params: list[Any] = []

    if exclude_loop_id is not None:
        sql += " WHERE loop_id != ?"
        params.append(exclude_loop_id)

    # Order by loop_id for deterministic results when using LIMIT
    sql += " ORDER BY loop_id"

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def upsert_loop_embedding(
    *,
    loop_id: int,
    embedding_blob: bytes,
    embedding_dim: int,
    embedding_norm: float,
    embed_model: str,
    conn: sqlite3.Connection,
    source_text_hash: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO loop_embeddings (
            loop_id,
            embedding_blob,
            embedding_dim,
            embedding_norm,
            embed_model,
            source_text_hash
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(loop_id) DO UPDATE SET
            embedding_blob = excluded.embedding_blob,
            embedding_dim = excluded.embedding_dim,
            embedding_norm = excluded.embedding_norm,
            embed_model = excluded.embed_model,
            source_text_hash = excluded.source_text_hash,
            created_at = CURRENT_TIMESTAMP
        """,
        (loop_id, embedding_blob, embedding_dim, embedding_norm, embed_model, source_text_hash),
    )
