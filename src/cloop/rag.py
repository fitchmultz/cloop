from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np
from pypdf import PdfReader

from .db import rag_connection
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
    rows = fetch_all_chunks(settings=settings)
    if not rows:
        return []

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
