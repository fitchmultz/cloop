"""Related loop suggestions using vector similarity.

Purpose:
    Suggest related loops based on vector similarity of embeddings.
    Also provides duplicate detection with higher similarity threshold.

Responsibilities:
    - Upsert loop embeddings into vector store
    - Query similar loops by vector distance
    - Provide suggestion links between related items
    - Detect potential duplicate loops with high similarity

Non-scope:
    - Embedding generation (see embeddings.py)
    - Loop storage (see loops/repo.py)

Entrypoints:
    - upsert_loop_embedding(loop_id, text, conn, settings) -> None
    - suggest_links(loop_id, conn, settings) -> List[Dict]
    - find_duplicate_candidates(loop_id, conn, settings) -> List[DuplicateCandidate]
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..embeddings import embed_texts
from ..settings import Settings, get_settings
from . import relationship_review, repo
from .models import LoopStatus
from .similarity import semantic_source_hash


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """A loop identified as a potential duplicate."""

    loop_id: int
    score: float  # cosine similarity 0-1
    title: str | None
    raw_text_preview: str  # first 100 chars
    status: str
    captured_at_utc: str


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
            source_text_hash=semantic_source_hash(text),
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
    """Find loops related to the given query vector by cosine similarity.

    NOTE: This function performs O(n) memory and computation where n is the
    number of candidate embeddings fetched. For large datasets, consider:
    - Reducing 'related_max_candidates' setting to limit memory usage
    - Using vector database or SQLite extensions for approximate NN search

    Current scalability limit: ~5,000-10,000 loops with default settings.

    Args:
        loop_id: The source loop ID to exclude from results
        query_vec: The query embedding vector
        threshold: Minimum cosine similarity score (0-1)
        top_k: Maximum number of results to return
        conn: Database connection
        settings: Optional settings override

    Returns:
        List of dicts with 'loop_id' and 'score' keys, sorted by score desc
    """
    settings = settings or get_settings()

    # Fetch limited candidates to control memory usage
    rows = repo.fetch_loop_embeddings(
        conn=conn,
        limit=settings.related_max_candidates,
        exclude_loop_id=loop_id,
    )

    candidates: list[tuple[int, float]] = []
    query_norm = float(np.linalg.norm(query_vec)) + 1e-12

    for row in rows:
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


def find_duplicate_candidates(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[DuplicateCandidate]:
    """Find loops that are likely duplicates of the given loop."""
    settings = settings or get_settings()
    result = relationship_review.review_loop_relationships(
        loop_id=loop_id,
        statuses=[
            LoopStatus.INBOX,
            LoopStatus.ACTIONABLE,
            LoopStatus.BLOCKED,
            LoopStatus.SCHEDULED,
        ],
        duplicate_limit=10,
        related_limit=1,
        conn=conn,
        settings=settings,
    )

    return [
        DuplicateCandidate(
            loop_id=int(candidate["id"]),
            score=float(candidate["score"]),
            title=(str(candidate["title"]) if candidate["title"] is not None else None),
            raw_text_preview=str(candidate["raw_text_preview"]),
            status=str(candidate["status"]),
            captured_at_utc=str(candidate["captured_at_utc"]),
        )
        for candidate in result["duplicate_candidates"]
    ]


def suggest_links(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Find and link loops related to the given loop by embedding similarity."""
    settings = settings or get_settings()
    synced = relationship_review.sync_relationship_suggestions(
        loop_id=loop_id,
        conn=conn,
        settings=settings,
        related_limit=5,
        duplicate_limit=3,
    )
    return [
        {"loop_id": int(candidate["id"]), "score": float(candidate["score"])}
        for candidate in synced["related"]
    ]
