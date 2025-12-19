from __future__ import annotations

import sqlite3
from typing import Any

import numpy as np

from ..embeddings import embed_texts
from ..settings import Settings, get_settings
from . import repo


def upsert_loop_embedding(
    *,
    loop_id: int,
    text: str,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    vectors = embed_texts([text], settings=settings)
    if not vectors:
        return
    vector = vectors[0]
    embedding_blob = vector.astype(np.float32).tobytes()
    embedding_norm = float(np.linalg.norm(vector))
    with conn:
        repo.upsert_loop_embedding(
            loop_id=loop_id,
            embedding_blob=embedding_blob,
            embedding_dim=int(vector.shape[0]),
            embedding_norm=embedding_norm,
            embed_model=settings.embed_model,
            conn=conn,
        )


def find_related_loops(
    *,
    loop_id: int,
    query_vec: np.ndarray,
    threshold: float,
    top_k: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    _ = settings or get_settings()
    rows = repo.fetch_loop_embeddings(conn=conn)
    candidates: list[tuple[int, float]] = []
    query_norm = float(np.linalg.norm(query_vec)) + 1e-12
    for row in rows:
        if int(row["loop_id"]) == loop_id:
            continue
        blob = row["embedding_blob"]
        dim = int(row["embedding_dim"])
        vec = np.frombuffer(blob, dtype=np.float32, count=dim)
        norm = float(row["embedding_norm"]) + 1e-12
        score = float(np.dot(vec, query_vec) / (norm * query_norm))
        if score >= threshold:
            candidates.append((int(row["loop_id"]), score))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return [
        {"loop_id": loop_id_value, "score": score} for loop_id_value, score in candidates[:top_k]
    ]


def suggest_links(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    rows = repo.fetch_loop_embeddings(conn=conn)
    if not rows:
        return []
    current = next((row for row in rows if int(row["loop_id"]) == loop_id), None)
    if current is None:
        return []
    dim = int(current["embedding_dim"])
    query_vec = np.frombuffer(current["embedding_blob"], dtype=np.float32, count=dim)
    related = find_related_loops(
        loop_id=loop_id,
        query_vec=query_vec,
        threshold=0.78,
        top_k=5,
        conn=conn,
        settings=settings,
    )
    with conn:
        for item in related:
            repo.insert_loop_link(
                loop_id=loop_id,
                related_loop_id=int(item["loop_id"]),
                relationship_type="related",
                confidence=float(item["score"]),
                source="ai",
                conn=conn,
            )
    return related
