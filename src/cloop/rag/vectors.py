"""Vector index operations for SQLite extensions.

Purpose:
    Create and manage vector search virtual tables using SQLite extensions.

Responsibilities:
    - Create and manage VEC/VSS virtual tables
    - Handle vector similarity search

Non-scope:
    - Vector generation (see embeddings.py)
    - Document management (see documents.py)
- Upsert and delete vector embeddings

Non-scope:
- Embedding generation (see embeddings.py)
- Search/retrieval (see search.py)
"""

import json
import logging
import sqlite3
from typing import Sequence

import numpy as np

from ..db import VectorBackend, reset_vector_backend

logger = logging.getLogger(__name__)


def ensure_vector_index(conn: sqlite3.Connection, dim: int, backend: VectorBackend) -> None:
    match backend:
        case VectorBackend.VEC:
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[%d])"
                    % dim
                )
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to create vec_chunks index (dimension=%d): %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    dim,
                    e,
                )
                reset_vector_backend()
        case VectorBackend.VSS:
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vss_chunks USING vss0(embedding(%d))" % dim
                )
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to create vss_chunks index (dimension=%d): %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    dim,
                    e,
                )
                reset_vector_backend()
        case _:
            return


def upsert_vector(
    conn: sqlite3.Connection, chunk_id: int, vec: np.ndarray, backend: VectorBackend
) -> None:
    vector = np.asarray(vec, dtype=np.float32)
    match backend:
        case VectorBackend.VEC:
            try:
                conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (chunk_id,))
                conn.execute(
                    "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                    (chunk_id, json.dumps(vector.astype(float).tolist())),
                )
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to upsert vector to vec_chunks (chunk_id=%d): %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    chunk_id,
                    e,
                )
                reset_vector_backend()
        case VectorBackend.VSS:
            try:
                conn.execute("DELETE FROM vss_chunks WHERE rowid = ?", (chunk_id,))
                conn.execute(
                    "INSERT INTO vss_chunks(rowid, embedding) VALUES (?, ?)",
                    (chunk_id, vector.tobytes()),
                )
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to upsert vector to vss_chunks (chunk_id=%d): %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    chunk_id,
                    e,
                )
                reset_vector_backend()
        case _:
            return


def delete_vector_rows(
    conn: sqlite3.Connection,
    chunk_ids: Sequence[int],
    backend: VectorBackend,
) -> None:
    if not chunk_ids:
        return
    placeholders = ",".join("?" for _ in chunk_ids)
    params = tuple(int(chunk_id) for chunk_id in chunk_ids)
    match backend:
        case VectorBackend.VEC:
            try:
                conn.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", params)
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to delete vectors from vec_chunks: %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    e,
                )
                reset_vector_backend()
        case VectorBackend.VSS:
            try:
                conn.execute(f"DELETE FROM vss_chunks WHERE rowid IN ({placeholders})", params)
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to delete vectors from vss_chunks: %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    e,
                )
                reset_vector_backend()
        case _:
            return
