from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np
from pypdf import PdfReader

from .db import rag_connection, vector_extension_available
from .embeddings import cosine_similarities, embed_texts
from .settings import Settings, get_settings

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
PDF_EXTENSIONS = {".pdf"}


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


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


def ingest_paths(
    paths: Sequence[str],
    *,
    settings: Settings | None = None,
) -> Dict[str, int]:
    settings = settings or get_settings()
    ingested_files = 0
    ingested_chunks = 0

    with rag_connection(settings) as conn:
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            if not path.exists():
                continue
            try:
                text = load_document(path)
            except ValueError:
                continue
            file_bytes = path.read_bytes()
            chunks = chunk_text(text, chunk_size=settings.chunk_size)
            if not chunks:
                continue
            embeddings = embed_texts(chunks, settings=settings)
            metadata_base = {
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
            }
            for idx, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True)):
                payload = {
                    "document_path": str(path),
                    "chunk_index": idx,
                    "content": chunk,
                    "embedding": json.dumps(vector.tolist()),
                    "embedding_dim": int(vector.shape[0]),
                    "metadata": json.dumps({**metadata_base, "chunk_length": len(chunk)}),
                }
                conn.execute(
                    """
                    INSERT INTO chunks (
                        document_path,
                        chunk_index,
                        content,
                        embedding,
                        embedding_dim,
                        metadata
                    )
                    VALUES (
                        :document_path,
                        :chunk_index,
                        :content,
                        :embedding,
                        :embedding_dim,
                        :metadata
                    )
                    """,
                    payload,
                )
                ingested_chunks += 1
            ingested_files += 1
        conn.commit()

    return {"files": ingested_files, "chunks": ingested_chunks}


def fetch_all_chunks(settings: Settings | None = None) -> List[Dict[str, Any]]:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        rows = conn.execute(
            """
            SELECT id, document_path, chunk_index, content, embedding, embedding_dim, metadata
            FROM chunks
            """
        ).fetchall()
    return [dict(row) for row in rows]


def retrieve_similar_chunks(
    query: str,
    *,
    top_k: int,
    settings: Settings | None = None,
) -> List[Dict[str, Any]]:
    settings = settings or get_settings()
    vectors = embed_texts([query], settings=settings)
    if not vectors:
        return []
    query_vec = vectors[0]
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    should_try_sqlite = settings.vector_search_mode == "sqlite" or (
        settings.vector_search_mode == "auto" and vector_extension_available()
    )
    if should_try_sqlite:
        try:
            sqlite_rows = _sqlite_similar_chunks(query_vec, top_k, settings=settings)
            if sqlite_rows is not None:
                return sqlite_rows
        except sqlite3.Error:
            pass

    rows = fetch_all_chunks(settings=settings)
    if not rows:
        return []

    return _python_similar_chunks(query_vec, rows, top_k)


def _python_similar_chunks(
    query_vec: np.ndarray,
    rows: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    embeddings = [np.array(json.loads(row["embedding"]), dtype=np.float32) for row in rows]
    similarities = cosine_similarities(query_vec, embeddings)
    ranked = sorted(
        zip(rows, similarities, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    top_rows = []
    for row, score in ranked[:top_k]:
        row = dict(row)
        row["score"] = float(score)
        top_rows.append(row)
    return top_rows


def _sqlite_similar_chunks(
    query_vec: np.ndarray,
    top_k: int,
    *,
    settings: Settings,
) -> List[Dict[str, Any]] | None:
    if not vector_extension_available() and settings.vector_search_mode == "sqlite":
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
