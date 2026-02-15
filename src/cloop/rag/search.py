"""Search and retrieval operations.

Purpose:
    Provide multiple search backends for vector similarity search.

Responsibilities:
    - Multiple search backends (VEC, VSS, SQLite, Python)
    - Rank and return top-k similar chunks

Non-scope:
    - Vector storage (see vectors.py)
    - Embedding generation (see embeddings.py)
- Retrieval path selection
- Similarity scoring

Non-scope:
- Document ingestion (see __init__.py)
- Vector index management (see vectors.py)
"""

import json
import logging
import math
import sqlite3
from enum import StrEnum
from typing import Any, Dict, Iterable, List

import numpy as np

from ..db import VectorBackend, get_vector_backend, rag_connection, reset_vector_backend
from ..embeddings import embed_texts
from ..settings import EmbedStorageMode, Settings, VectorSearchMode, get_settings
from .utils import (
    _assert_embedding_dimension_consistency,
    _assert_embedding_model_alignment,
    _filter_rows_by_scope,
)

logger = logging.getLogger(__name__)

_VECLIKE_METRIC = "1_over_1_plus_distance"
_SQL_PY_METRIC = "cosine"


class RetrievalPath(StrEnum):
    VEC = "vec"
    VSS = "vss"
    SQLITE = "sqlite"
    PYTHON = "python"


def _select_retrieval_order(
    *,
    backend: VectorBackend,
    scope: str | None,
    settings: Settings,
) -> List[RetrievalPath]:
    if scope:
        return [RetrievalPath.PYTHON]

    match settings.vector_search_mode:
        case VectorSearchMode.PYTHON:
            return [RetrievalPath.PYTHON]
        case VectorSearchMode.SQLITE:
            if settings.embed_storage_mode not in {EmbedStorageMode.JSON, EmbedStorageMode.DUAL}:
                raise RuntimeError("SQLITE retrieval requires json or dual embedding storage")
            return [RetrievalPath.SQLITE]
        case VectorSearchMode.AUTO:
            order: List[RetrievalPath] = []
            if backend is VectorBackend.VEC:
                order.append(RetrievalPath.VEC)
            elif backend is VectorBackend.VSS:
                order.append(RetrievalPath.VSS)
            if settings.embed_storage_mode in {EmbedStorageMode.JSON, EmbedStorageMode.DUAL}:
                order.append(RetrievalPath.SQLITE)
            order.append(RetrievalPath.PYTHON)
            return order
    raise RuntimeError(f"Unsupported vector search mode: {settings.vector_search_mode}")


def vec_backend_search(
    conn: sqlite3.Connection,
    query: np.ndarray,
    top_k: int,
    backend: VectorBackend,
) -> List[Dict[str, Any]] | None:
    match backend:
        case VectorBackend.VEC:
            return _vec_extension_search(conn, query, top_k)
        case VectorBackend.VSS:
            return _vss_extension_search(conn, query, top_k)
        case _:
            return None


def _vec_extension_search(
    conn: sqlite3.Connection,
    query: np.ndarray,
    top_k: int,
) -> List[Dict[str, Any]] | None:
    try:
        payload = json.dumps(np.asarray(query, dtype=float).tolist())
        matches = conn.execute(
            (
                "SELECT rowid, distance FROM vec_chunks "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
            ),
            (payload, top_k),
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning(
            "Failed to search vec_chunks index: %s. "
            "Vector search will fall back to SQLite/Python mode.",
            e,
        )
        reset_vector_backend()
        return None

    return _chunk_rows_with_scores(conn, matches)


def _vss_extension_search(
    conn: sqlite3.Connection,
    query: np.ndarray,
    top_k: int,
) -> List[Dict[str, Any]] | None:
    try:
        payload = np.asarray(query, dtype=np.float32).tobytes()
        matches = conn.execute(
            (
                "SELECT rowid, distance FROM vss_chunks "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
            ),
            (payload, top_k),
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning(
            "Failed to search vss_chunks index: %s. "
            "Vector search will fall back to SQLite/Python mode.",
            e,
        )
        reset_vector_backend()
        return None

    return _chunk_rows_with_scores(conn, matches)


def _chunk_rows_with_scores(
    conn: sqlite3.Connection,
    matches: Iterable[sqlite3.Row],
) -> List[Dict[str, Any]]:
    # Convert matches to list to iterate multiple times
    matches_list = list(matches)
    if not matches_list:
        return []

    # Collect chunk IDs and their distances
    chunk_ids: List[int] = []
    distances: Dict[int, float] = {}
    for row in matches_list:
        chunk_id = int(row["rowid"])
        chunk_ids.append(chunk_id)
        distances[chunk_id] = float(row["distance"])

    # Build single parameterized query with placeholders
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""
        SELECT
            id,
            document_path,
            chunk_index,
            content,
            embedding,
            embedding_dim,
            metadata,
            embedding_blob,
            embedding_norm,
            doc_id
        FROM chunks
        WHERE id IN ({placeholders})
        """,
        chunk_ids,
    ).fetchall()

    # Create lookup dict for O(1) access
    chunk_by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        chunk = dict(row)
        chunk.pop("embedding_blob", None)
        chunk_by_id[chunk["id"]] = chunk

    # Rebuild results in original match order, preserving scores
    results: List[Dict[str, Any]] = []
    for chunk_id in chunk_ids:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            continue
        chunk["score"] = 1.0 / (1.0 + distances[chunk_id])
        results.append(chunk)

    return results


def fetch_all_chunks(settings: Settings | None = None) -> List[Dict[str, Any]]:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                document_path,
                chunk_index,
                content,
                embedding,
                embedding_dim,
                metadata,
                embedding_blob,
                embedding_norm,
                doc_id
            FROM chunks
            """
        ).fetchall()
    return [dict(row) for row in rows]


def retrieve_similar_chunks(
    query: str,
    *,
    top_k: int,
    scope: str | None = None,
    settings: Settings | None = None,
) -> List[Dict[str, Any]]:
    settings = settings or get_settings()
    vectors = embed_texts([query], settings=settings)
    if not vectors:
        return []
    query_vec = np.asarray(vectors[0], dtype=np.float32)
    _assert_embedding_model_alignment(settings=settings)
    _assert_embedding_dimension_consistency(
        settings=settings, expected_dim=int(query_vec.shape[0]), scope=scope
    )
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    vector_backend = get_vector_backend()
    paths = _select_retrieval_order(backend=vector_backend, scope=scope, settings=settings)

    for path in paths:
        try:
            if path is RetrievalPath.VEC:
                with rag_connection(settings) as conn:
                    rows = vec_backend_search(conn, query_vec, top_k, VectorBackend.VEC)
                if rows:
                    return rows
                continue
            if path is RetrievalPath.VSS:
                with rag_connection(settings) as conn:
                    rows = vec_backend_search(conn, query_vec, top_k, VectorBackend.VSS)
                if rows:
                    return rows
                continue
            if path is RetrievalPath.SQLITE:
                rows = _sqlite_similar_chunks(query_vec, top_k, settings=settings)
                if rows is not None:
                    return rows
                continue
            if path is RetrievalPath.PYTHON:
                rows = fetch_all_chunks(settings=settings)
                if scope:
                    rows = _filter_rows_by_scope(rows, scope)
                if not rows:
                    return []
                return _python_similar_chunks(query_vec, rows, top_k, settings.embed_storage_mode)
        except RuntimeError:
            raise
        except sqlite3.Error:
            if settings.vector_search_mode is VectorSearchMode.SQLITE:
                raise
            continue

    return []


def _python_similar_chunks(
    query_vec: np.ndarray,
    rows: List[Dict[str, Any]],
    top_k: int,
    mode: EmbedStorageMode,
) -> List[Dict[str, Any]]:
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm <= 1e-12:
        return []

    scored_rows: List[Dict[str, Any]] = []
    for row in rows:
        vector = _row_embedding(row, mode=mode)
        if vector.size == 0:
            continue
        doc_norm = row.get("embedding_norm")
        norm_value = float(doc_norm) if doc_norm is not None else float(np.linalg.norm(vector))
        denominator = (norm_value * query_norm) + 1e-12
        score = float(np.dot(query_vec, vector) / denominator)
        row_with_score = dict(row)
        row_with_score["score"] = score
        row_with_score.pop("embedding_blob", None)
        scored_rows.append(row_with_score)

    scored_rows.sort(key=lambda item: item["score"], reverse=True)
    return scored_rows[:top_k]


def _row_embedding(row: Dict[str, Any], *, mode: EmbedStorageMode) -> np.ndarray:
    match mode:
        case EmbedStorageMode.BLOB:
            blob = row.get("embedding_blob")
            if blob is None:
                raise RuntimeError("embedding_blob missing for blob storage mode")
            buffer = memoryview(blob)
            dim = int(row.get("embedding_dim", len(buffer) // 4))
            return np.frombuffer(buffer, dtype=np.float32, count=dim)
        case EmbedStorageMode.JSON:
            embedding_text = row.get("embedding")
            if not embedding_text:
                raise RuntimeError("embedding text missing for json storage mode")
            return np.array(json.loads(embedding_text), dtype=np.float32)
        case EmbedStorageMode.DUAL:
            blob = row.get("embedding_blob")
            if blob is None:
                raise RuntimeError("embedding_blob missing for dual storage mode")
            buffer = memoryview(blob)
            dim = int(row.get("embedding_dim", len(buffer) // 4))
            return np.frombuffer(buffer, dtype=np.float32, count=dim)
    raise RuntimeError(f"Unsupported embed storage mode: {mode}")


def _sqlite_similar_chunks(
    query_vec: np.ndarray,
    top_k: int,
    *,
    settings: Settings,
) -> List[Dict[str, Any]] | None:
    if settings.embed_storage_mode is EmbedStorageMode.BLOB:
        raise RuntimeError("SQL retrieval requires json or dual embedding storage")
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm <= 1e-12:
        return []
    with rag_connection(settings) as conn:
        try:
            conn.execute("DROP TABLE IF EXISTS temp_query")
            conn.execute("CREATE TEMP TABLE temp_query(idx INTEGER PRIMARY KEY, value REAL)")
            conn.executemany(
                "INSERT INTO temp_query(idx, value) VALUES (?, ?)",
                ((idx, float(value)) for idx, value in enumerate(query_vec.tolist())),
            )
            rows = conn.execute(
                """
                WITH flattened AS (
                    SELECT
                        c.id,
                        c.document_path,
                        c.chunk_index,
                        c.content,
                        c.embedding,
                        c.embedding_dim,
                        c.metadata,
                        temp.idx AS q_idx,
                        temp.value AS q_val,
                        CAST(json_extract(c.embedding, '$[' || temp.idx || ']') AS REAL) AS e_val
                    FROM chunks c
                    JOIN temp_query temp ON temp.idx < c.embedding_dim
                ),
                stats AS (
                    SELECT
                        id,
                        SUM(q_val * e_val) AS dot,
                        SUM(e_val * e_val) AS chunk_norm_sq
                    FROM flattened
                    GROUP BY id
                )
                SELECT
                    c.id,
                    c.document_path,
                    c.chunk_index,
                    c.content,
                    c.embedding,
                    c.embedding_dim,
                    c.metadata,
                    stats.dot,
                    stats.chunk_norm_sq
                FROM stats
                JOIN chunks c ON c.id = stats.id
                ORDER BY stats.dot DESC
                LIMIT ?
                """,
                (top_k,),
            ).fetchall()
        finally:
            conn.execute("DROP TABLE IF EXISTS temp_query")

    results: List[Dict[str, Any]] = []
    for row in rows:
        chunk = dict(row)
        dot = float(chunk.pop("dot", 0.0))
        chunk_norm_sq = float(chunk.pop("chunk_norm_sq", 0.0))
        denom = (query_norm * math.sqrt(chunk_norm_sq)) + 1e-12
        chunk["score"] = dot / denom if denom > 0 else 0.0
        results.append(chunk)
    return results
