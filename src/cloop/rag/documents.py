"""Document record management in RAG database.

Purpose:
    Manage document records for RAG ingestion and retrieval.

Responsibilities:
    - CRUD operations for document records
    - Track ingestion status and metadata

Non-scope:
    - File loading (see loaders.py)
    - Vector search (see vectors.py)
- Path normalization and matching
- Purge and sync logic

Non-scope:
- File I/O (see loaders.py)
- Vector operations (see vectors.py)
"""

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

from ..db import VectorBackend
from ..typingx import escape_like_pattern
from .loaders import _normalize_path
from .vectors import delete_vector_rows

SUPPORTED_INGEST_MODES = {"add", "reindex", "purge", "sync"}


def _needs_hash_recompute(
    path: Path,
    stat_meta: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
) -> bool:
    """
    Check if file needs hash computation based on mtime/size comparison.

    Returns True if:
    - File is new (not in database)
    - File mtime or size differs from stored values

    Returns False if:
    - File exists in database AND mtime and size match exactly
    """
    doc_path = str(_normalize_path(path))
    row = conn.execute(
        "SELECT mtime_ns, size_bytes FROM documents WHERE document_path = ?",
        (doc_path,),
    ).fetchone()

    if row is None:
        return True  # New file, needs hash

    stored_mtime = int(row["mtime_ns"])
    stored_size = int(row["size_bytes"])
    current_mtime = int(stat_meta["mtime_ns"])
    current_size = int(stat_meta["size_bytes"])

    return stored_mtime != current_mtime or stored_size != current_size


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
