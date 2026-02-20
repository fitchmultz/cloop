"""
RAG (Retrieval-Augmented Generation) operations.

This package provides document ingestion, chunking, embedding, and retrieval
capabilities for the Cloop knowledge base.

Public API:
- ingest_paths: Ingest documents into the RAG database
- retrieve_similar_chunks: Search for similar document chunks
- fetch_all_chunks: Get all chunks from the database
- load_document: Load a document from filesystem
- chunk_text: Split text into chunks
- purge_documents: Remove documents from the database
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence, TypedDict

import numpy as np

from ..db import VectorBackend, get_vector_backend, rag_connection
from ..embeddings import embed_texts
from ..settings import EmbedStorageMode, Settings, get_settings
from .chunking import chunk_text
from .documents import (
    SUPPORTED_INGEST_MODES,
    _needs_hash_recompute,
    purge_documents,
    upsert_document_record,
)
from .loaders import (
    SUPPORTED_EXTENSIONS,
    _check_file_size,
    _document_file_metadata,
    _file_stat_metadata,
    load_document,
)
from .search import (
    _SQL_PY_METRIC,
    _VECLIKE_METRIC,
    RetrievalPath,
    _select_retrieval_order,
    fetch_all_chunks,
    retrieve_similar_chunks,
    vec_backend_search,
)
from .vectors import delete_vector_rows, ensure_vector_index, upsert_vector

logger = logging.getLogger(__name__)


class FailedFile(TypedDict):
    path: str
    error: str


def ingest_paths(
    paths: Sequence[str],
    *,
    mode: str = "add",
    recursive: bool = True,
    force_rehash: bool = False,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    settings = settings or get_settings()
    from .documents import _collect_missing_documents
    from .loaders import _iter_candidate_files, _normalize_path

    normalized_targets = [_normalize_path(Path(path)) for path in paths]
    ingestion_mode = (mode or "add").strip().lower()
    if ingestion_mode not in SUPPORTED_INGEST_MODES:
        raise ValueError(f"Unsupported ingestion mode: {mode}")

    files_processed = 0
    files_skipped = 0
    chunks_processed = 0
    failed_files: List[FailedFile] = []

    vector_backend = get_vector_backend()

    with rag_connection(settings) as conn:
        if ingestion_mode == "purge":
            docs_removed, chunks_removed = purge_documents(
                normalized_targets, conn=conn, backend=vector_backend
            )
            conn.commit()
            return {
                "files": int(docs_removed),
                "chunks": int(chunks_removed),
                "files_skipped": 0,
                "failed_files": [],
            }

        candidate_files = list(_iter_candidate_files(normalized_targets, recursive))
        for file_path in candidate_files:
            _check_file_size(file_path, settings.max_file_size_mb)

            # Get stat-only metadata first for cheap change detection
            stat_meta = _file_stat_metadata(file_path)

            # Check if mtime/size changed (cheap check)
            stat_changed = _needs_hash_recompute(file_path, stat_meta, conn=conn)

            # If stat unchanged and not forcing rehash/reindex, skip entirely
            if not stat_changed and not force_rehash and ingestion_mode != "reindex":
                files_skipped += 1
                continue

            # Compute hash if stat changed, force_rehash, or reindex mode
            compute_hash = stat_changed or force_rehash or ingestion_mode == "reindex"

            # Compute full metadata (with hash as needed)
            metadata = _document_file_metadata(file_path, compute_hash=compute_hash)

            try:
                text = load_document(file_path)
            except (ValueError, OSError) as e:
                from pypdf.errors import PyPdfError

                if not isinstance(e, (ValueError, OSError, PyPdfError)):
                    raise
                error_msg = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Failed to load document %s: %s",
                    file_path,
                    error_msg,
                )
                failed_files.append(FailedFile(path=str(file_path), error=error_msg))
                continue

            chunks = chunk_text(text, chunk_size=settings.chunk_size)
            embeddings = embed_texts(chunks, settings=settings) if chunks else []
            metadata_base = {
                "size_bytes": metadata["size_bytes"],
                "sha256": metadata.get("sha256", ""),
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
            except sqlite3.Error, OSError, ValueError:
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

    return {
        "files": int(files_processed),
        "chunks": int(chunks_processed),
        "files_skipped": int(files_skipped),
        "failed_files": failed_files,
    }


__all__ = [
    "ingest_paths",
    "load_document",
    "chunk_text",
    "purge_documents",
    "retrieve_similar_chunks",
    "fetch_all_chunks",
    "FailedFile",
    "RetrievalPath",
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_INGEST_MODES",
    "_select_retrieval_order",
    "_VECLIKE_METRIC",
    "_SQL_PY_METRIC",
    "ensure_vector_index",
    "upsert_vector",
    "delete_vector_rows",
    "vec_backend_search",
    "get_vector_backend",
]
