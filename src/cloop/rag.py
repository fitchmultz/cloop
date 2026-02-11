import hashlib
import json
import logging
import math
import os
import re
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

import numpy as np
from pypdf import PdfReader

from .db import (
    VectorBackend,
    get_vector_backend,
    rag_connection,
    reset_vector_backend,
    vector_extension_available,
)
from .embeddings import embed_texts
from .settings import EmbedStorageMode, Settings, VectorSearchMode, get_settings
from .typingx import escape_like_pattern

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS
SUPPORTED_INGEST_MODES = {"add", "reindex", "purge", "sync"}

_VECLIKE_METRIC = "1_over_1_plus_distance"
_SQL_PY_METRIC = "cosine"


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _check_file_size(path: Path, max_size_mb: int) -> None:
    """Raise ValueError if file exceeds max size limit."""
    max_bytes = max_size_mb * 1024 * 1024
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"File too large: {path.name} ({size / (1024 * 1024):.1f} MB) "
            f"exceeds maximum allowed size of {max_size_mb} MB"
        )


def load_document(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _read_text_file(path)
    if ext in PDF_EXTENSIONS:
        return _read_pdf(path)
    raise ValueError(f"Unsupported file type: {ext}")


def chunk_text(text: str, *, chunk_size: int) -> List[str]:
    tokens = re.split(r"\s+", text.strip())
    if not tokens:
        return []
    chunks = []
    for idx in range(0, len(tokens), chunk_size):
        chunk_tokens = tokens[idx : idx + chunk_size]
        chunks.append(" ".join(chunk_tokens))
    return chunks


def _normalize_path(value: Path) -> Path:
    return value.expanduser().resolve(strict=False)


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _iter_candidate_files(targets: Sequence[Path], recursive: bool) -> Iterable[Path]:
    seen: Set[str] = set()
    for target in targets:
        normalized = _normalize_path(target)
        if normalized.exists() and normalized.is_dir():
            iterator = normalized.rglob("*") if recursive else normalized.iterdir()
            for entry in iterator:
                if entry.is_file() and _is_supported_file(entry):
                    resolved = _normalize_path(entry)
                    key = str(resolved)
                    if key not in seen:
                        seen.add(key)
                        yield resolved
        elif normalized.exists() and normalized.is_file():
            if _is_supported_file(normalized):
                key = str(normalized)
                if key not in seen:
                    seen.add(key)
                    yield normalized


def _document_file_metadata(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    file_bytes = path.read_bytes()
    return {
        "path": str(_normalize_path(path)),
        "mtime_ns": int(stat.st_mtime_ns),
        "size_bytes": int(stat.st_size),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
    }


def upsert_document_record(
    path: Path,
    *,
    metadata: Dict[str, Any],
    conn: sqlite3.Connection,
) -> Tuple[int, bool]:
    normalized = _normalize_path(path)
    doc_path = str(normalized)
    row_obj = conn.execute(
        "SELECT id, mtime_ns, size_bytes, sha256 FROM documents WHERE document_path = ?",
        (doc_path,),
    ).fetchone()
    if row_obj:
        row = dict(row_obj)
        changed = (
            int(row["mtime_ns"]) != int(metadata["mtime_ns"])
            or int(row["size_bytes"]) != int(metadata["size_bytes"])
            or str(row["sha256"]) != str(metadata["sha256"])
        )
        if changed:
            conn.execute(
                """
                UPDATE documents
                SET mtime_ns = ?, size_bytes = ?, sha256 = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    metadata["mtime_ns"],
                    metadata["size_bytes"],
                    metadata["sha256"],
                    row["id"],
                ),
            )
        return int(row["id"]), changed

    cursor = conn.execute(
        """
        INSERT INTO documents (document_path, mtime_ns, size_bytes, sha256)
        VALUES (?, ?, ?, ?)
        """,
        (doc_path, metadata["mtime_ns"], metadata["size_bytes"], metadata["sha256"]),
    )
    new_id = cursor.lastrowid
    if new_id is None:
        raise RuntimeError("Failed to insert document record")
    return int(new_id), True


def _directory_like_pattern(path_str: str) -> str:
    normalized = path_str.rstrip(os.sep)
    # Escape LIKE wildcards in path before adding the directory wildcard
    escaped = escape_like_pattern(normalized)
    return f"{escaped}{os.sep}%"


def _select_document_ids_for_target(
    conn: sqlite3.Connection,
    target: Path,
) -> Set[int]:
    doc_path = str(_normalize_path(target))
    rows = []
    potential_dir = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE document_path LIKE ?",
        (_directory_like_pattern(doc_path),),
    ).fetchone()[0]
    if target.exists() and target.is_dir():
        rows = conn.execute(
            "SELECT id FROM documents WHERE document_path LIKE ?",
            (_directory_like_pattern(doc_path),),
        ).fetchall()
    elif potential_dir and not target.exists():
        rows = conn.execute(
            "SELECT id FROM documents WHERE document_path LIKE ?",
            (_directory_like_pattern(doc_path),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM documents WHERE document_path = ?",
            (doc_path,),
        ).fetchall()
    return {int(dict(row)["id"]) for row in rows}


def purge_documents(
    paths: List[Path],
    *,
    conn: sqlite3.Connection,
    backend: VectorBackend,
) -> Tuple[int, int]:
    unique_targets = list(
        {str(_normalize_path(path)): _normalize_path(path) for path in paths}.values()
    )
    doc_ids: Set[int] = set()
    for target in unique_targets:
        doc_ids.update(_select_document_ids_for_target(conn, target))

    if not doc_ids:
        return 0, 0

    placeholders = ",".join("?" for _ in doc_ids)
    id_params = tuple(doc_ids)
    if backend in {VectorBackend.VEC, VectorBackend.VSS}:
        chunk_rows = conn.execute(
            f"SELECT id FROM chunks WHERE doc_id IN ({placeholders})",
            id_params,
        ).fetchall()
        chunk_ids = [int(row["id"]) for row in chunk_rows]
        delete_vector_rows(conn, chunk_ids, backend)
    chunks_removed = conn.execute(
        f"SELECT COUNT(*) FROM chunks WHERE doc_id IN ({placeholders})",
        id_params,
    ).fetchone()[0]
    conn.execute(
        f"DELETE FROM chunks WHERE doc_id IN ({placeholders})",
        id_params,
    )
    conn.execute(
        f"DELETE FROM documents WHERE id IN ({placeholders})",
        id_params,
    )
    return len(doc_ids), int(chunks_removed)


def _collect_missing_documents(
    targets: Sequence[Path],
    *,
    conn: sqlite3.Connection,
) -> List[Path]:
    normalized_targets = [_normalize_path(target) for target in targets]
    target_files = {path for path in normalized_targets if not path.is_dir()}
    target_dirs = [path for path in normalized_targets if path.is_dir()]
    rows = conn.execute("SELECT document_path FROM documents").fetchall()
    missing: List[Path] = []
    for row in rows:
        doc_map = dict(row)
        doc_path = _normalize_path(Path(doc_map["document_path"]))
        if doc_path.exists():
            continue
        if doc_path in target_files:
            missing.append(doc_path)
            continue
        for directory in target_dirs:
            if doc_path.is_relative_to(directory):
                missing.append(doc_path)
                break
    return list(dict.fromkeys(missing))


def _assert_embedding_dimension_consistency(
    *, settings: Settings, expected_dim: int, scope: str | None
) -> None:
    with rag_connection(settings) as conn:
        if scope and scope.startswith("doc:"):
            try:
                doc_id = int(scope.split(":", 1)[1])
            except ValueError:
                rows: list[sqlite3.Row] = []
            else:
                rows = conn.execute(
                    "SELECT DISTINCT embedding_dim FROM chunks WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
        elif scope:
            escaped_scope = escape_like_pattern(scope)
            rows = conn.execute(
                "SELECT DISTINCT embedding_dim FROM chunks WHERE document_path LIKE ? ESCAPE '\\'",
                (f"%{escaped_scope}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT DISTINCT embedding_dim FROM chunks").fetchall()
    dims = {int(row[0]) for row in rows}
    if not dims:
        return
    if len(dims) != 1 or expected_dim not in dims:
        raise RuntimeError(
            f"embedding_dim mismatch: query={expected_dim}, db={sorted(dims)}; "
            "re-ingest with the current embed model"
        )


def _assert_embedding_model_alignment(*, settings: Settings) -> None:
    with rag_connection(settings) as conn:
        row = conn.execute("SELECT metadata FROM chunks LIMIT 1").fetchone()
    if not row:
        return
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except json.JSONDecodeError:
        logger.debug("Chunk metadata is not valid JSON, skipping model alignment check")
        return
    except (TypeError, KeyError) as e:
        logger.warning("Unexpected error parsing chunk metadata: %s", e)
        return
    stored = metadata.get("embed_model")
    if stored and stored != settings.embed_model:
        raise RuntimeError(
            f"Stored embed_model={stored} != configured={settings.embed_model}; re-ingest required"
        )


def _filter_rows_by_scope(rows: List[Dict[str, Any]], scope: str) -> List[Dict[str, Any]]:
    if not scope:
        return rows
    scope = scope.strip()
    if scope.startswith("doc:"):
        try:
            doc_id = int(scope.split(":", 1)[1])
        except ValueError:
            return []
        return [row for row in rows if int(row.get("doc_id") or 0) == doc_id]
    return [row for row in rows if scope in str(row.get("document_path", ""))]


def ensure_vector_index(conn: sqlite3.Connection, dim: int, backend: VectorBackend) -> None:
    match backend:
        case VectorBackend.VEC:
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[%d])"
                    % dim
                )
            except sqlite3.Error:
                reset_vector_backend()
        case VectorBackend.VSS:
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vss_chunks USING vss0(embedding(%d))" % dim
                )
            except sqlite3.Error:
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
            except sqlite3.Error:
                reset_vector_backend()
        case VectorBackend.VSS:
            try:
                conn.execute("DELETE FROM vss_chunks WHERE rowid = ?", (chunk_id,))
                conn.execute(
                    "INSERT INTO vss_chunks(rowid, embedding) VALUES (?, ?)",
                    (chunk_id, vector.tobytes()),
                )
            except sqlite3.Error:
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
            except sqlite3.Error:
                reset_vector_backend()
        case VectorBackend.VSS:
            try:
                conn.execute(f"DELETE FROM vss_chunks WHERE rowid IN ({placeholders})", params)
            except sqlite3.Error:
                reset_vector_backend()
        case _:
            return


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
    except sqlite3.Error:
        reset_vector_backend()
        return None

    # Map extension distance to similarity using _VECLIKE_METRIC semantics.
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
    except sqlite3.Error:
        reset_vector_backend()
        return None

    # Map extension distance to similarity using _VECLIKE_METRIC semantics.
    return _chunk_rows_with_scores(conn, matches)


def _chunk_rows_with_scores(
    conn: sqlite3.Connection,
    matches: Iterable[sqlite3.Row],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for row in matches:
        chunk_id = int(row["rowid"])
        chunk_row = conn.execute(
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
            WHERE id = ?
            """,
            (chunk_id,),
        ).fetchone()
        if chunk_row is None:
            continue
        chunk = dict(chunk_row)
        chunk.pop("embedding_blob", None)
        distance = float(row["distance"])
        # Extensions return a distance metric; map to similarity as documented by _VECLIKE_METRIC.
        chunk["score"] = 1.0 / (1.0 + distance)
        results.append(chunk)
    return results


def ingest_paths(
    paths: Sequence[str],
    *,
    mode: str = "add",
    recursive: bool = True,
    settings: Settings | None = None,
) -> Dict[str, int]:
    settings = settings or get_settings()
    normalized_targets = [_normalize_path(Path(path)) for path in paths]
    ingestion_mode = (mode or "add").strip().lower()
    if ingestion_mode not in SUPPORTED_INGEST_MODES:
        raise ValueError(f"Unsupported ingestion mode: {mode}")

    files_processed = 0
    chunks_processed = 0

    vector_backend = get_vector_backend()

    with rag_connection(settings) as conn:
        if ingestion_mode == "purge":
            docs_removed, chunks_removed = purge_documents(
                normalized_targets, conn=conn, backend=vector_backend
            )
            conn.commit()
            return {"files": int(docs_removed), "chunks": int(chunks_removed)}

        candidate_files = list(_iter_candidate_files(normalized_targets, recursive))
        for file_path in candidate_files:
            # Check file size before reading to prevent DoS
            _check_file_size(file_path, settings.max_file_size_mb)
            metadata = _document_file_metadata(file_path)

            try:
                text = load_document(file_path)
            except ValueError:
                continue

            chunks = chunk_text(text, chunk_size=settings.chunk_size)
            embeddings = embed_texts(chunks, settings=settings) if chunks else []
            metadata_base = {
                "size_bytes": metadata["size_bytes"],
                "sha256": metadata["sha256"],
                "embed_model": settings.embed_model,
            }
            should_store_blob = settings.embed_storage_mode in {
                EmbedStorageMode.BLOB,
                EmbedStorageMode.DUAL,
            }
            should_store_json = settings.embed_storage_mode in {
                EmbedStorageMode.JSON,
                EmbedStorageMode.DUAL,
            }
            vector_index_ready = False
            inserted_chunks = 0

            try:
                conn.execute("BEGIN IMMEDIATE")
                doc_id, is_changed = upsert_document_record(file_path, metadata=metadata, conn=conn)

                if not chunks:
                    purge_documents([file_path], conn=conn, backend=vector_backend)
                    conn.commit()
                    continue

                should_process = is_changed or ingestion_mode == "reindex"
                if not should_process:
                    conn.commit()
                    continue

                if vector_backend in {VectorBackend.VEC, VectorBackend.VSS}:
                    existing_rows = conn.execute(
                        "SELECT id FROM chunks WHERE doc_id = ?",
                        (doc_id,),
                    ).fetchall()
                    delete_vector_rows(
                        conn, [int(row["id"]) for row in existing_rows], vector_backend
                    )
                conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

                for idx, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True)):
                    vector = np.asarray(vector, dtype=np.float32)
                    if (
                        vector_backend in {VectorBackend.VEC, VectorBackend.VSS}
                        and not vector_index_ready
                    ):
                        ensure_vector_index(conn, vector.shape[0], vector_backend)
                        vector_index_ready = True
                    embedding_blob = vector.tobytes() if should_store_blob else None
                    embedding_norm = float(np.linalg.norm(vector))
                    payload = {
                        "document_path": metadata["path"],
                        "chunk_index": idx,
                        "content": chunk,
                        "embedding": json.dumps(vector.tolist()) if should_store_json else "[]",
                        "embedding_dim": int(vector.shape[0]),
                        "metadata": json.dumps({**metadata_base, "chunk_length": len(chunk)}),
                        "doc_id": doc_id,
                        "embedding_blob": embedding_blob,
                        "embedding_norm": embedding_norm,
                    }
                    cursor = conn.execute(
                        """
                        INSERT INTO chunks (
                            document_path,
                            chunk_index,
                            content,
                            embedding,
                            embedding_dim,
                            metadata,
                            doc_id,
                            embedding_blob,
                            embedding_norm
                        )
                        VALUES (
                            :document_path,
                            :chunk_index,
                            :content,
                            :embedding,
                            :embedding_dim,
                            :metadata,
                            :doc_id,
                            :embedding_blob,
                            :embedding_norm
                        )
                        """,
                        payload,
                    )
                    chunk_id = cursor.lastrowid
                    if chunk_id is not None and vector_backend in {
                        VectorBackend.VEC,
                        VectorBackend.VSS,
                    }:
                        upsert_vector(conn, int(chunk_id), vector, vector_backend)
                    inserted_chunks += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            chunks_processed += inserted_chunks
            files_processed += 1

        if ingestion_mode == "sync":
            missing_targets = _collect_missing_documents(normalized_targets, conn=conn)
            if missing_targets:
                docs_removed, removed_chunks = purge_documents(
                    missing_targets, conn=conn, backend=vector_backend
                )
                files_processed += docs_removed
                chunks_processed += removed_chunks

        conn.commit()

    return {"files": int(files_processed), "chunks": int(chunks_processed)}


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
    if not vector_extension_available() and settings.vector_search_mode is VectorSearchMode.SQLITE:
        # Even without an external extension we can run the SQL implementation.
        pass
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
