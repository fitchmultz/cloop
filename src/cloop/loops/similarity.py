"""Shared semantic-search and loop-embedding helpers.

Purpose:
    Provide the canonical embedding-source construction and on-demand loop
    indexing used by first-class semantic loop search.

Responsibilities:
    - Build stable semantic source text for loops
    - Detect missing or stale loop embeddings via source hashes
    - Backfill or refresh loop embeddings on demand
    - Rank loop records by semantic similarity to a free-text query

Non-scope:
    - Transport-specific request/response shaping
    - Related-link insertion or duplicate-link lifecycle management
    - Generic loop CRUD orchestration
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from .. import typingx
from ..embeddings import embed_texts
from ..settings import Settings, get_settings
from . import repo
from .errors import ValidationError

if TYPE_CHECKING:
    from .models import LoopRecord


def build_loop_semantic_text(
    record: "LoopRecord",
    *,
    project: str | None = None,
    tags: Sequence[str] | None = None,
) -> str:
    """Build the canonical semantic-search source text for one loop."""
    normalized_tags = sorted({str(tag).strip() for tag in tags or [] if str(tag).strip()})
    parts = [f"Captured text: {record.raw_text}"]

    if record.title:
        parts.append(f"Title: {record.title}")
    if record.summary:
        parts.append(f"Summary: {record.summary}")
    if record.definition_of_done:
        parts.append(f"Definition of done: {record.definition_of_done}")
    if record.next_action:
        parts.append(f"Next action: {record.next_action}")
    if record.blocked_reason:
        parts.append(f"Blocked reason: {record.blocked_reason}")
    if record.completion_note:
        parts.append(f"Completion note: {record.completion_note}")
    if project:
        parts.append(f"Project: {project}")
    if normalized_tags:
        parts.append(f"Tags: {', '.join(normalized_tags)}")

    return "\n".join(parts)


@typingx.validate_io()
def semantic_source_hash(text: str) -> str:
    """Return the canonical source hash for a semantic-search document."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@typingx.validate_io()
def ensure_loop_embeddings(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> int:
    """Ensure the given loops have current embeddings for semantic search.

    Missing embeddings and embeddings generated from stale loop content are
    recomputed using the configured embedding model. Returns the number of loop
    rows that were newly indexed or refreshed.
    """
    if not loop_ids:
        return 0

    settings = settings or get_settings()
    unique_loop_ids = list(dict.fromkeys(loop_ids))
    records_by_id = repo.read_loops_batch(loop_ids=unique_loop_ids, conn=conn)
    records = [records_by_id[loop_id] for loop_id in unique_loop_ids if loop_id in records_by_id]
    if not records:
        return 0

    project_ids = {record.project_id for record in records if record.project_id is not None}
    projects_map = repo.read_project_names_batch(project_ids=project_ids, conn=conn)
    tags_map = repo.list_loop_tags_batch(loop_ids=[record.id for record in records], conn=conn)
    existing_embeddings = repo.read_loop_embeddings_batch(
        loop_ids=[record.id for record in records],
        conn=conn,
    )

    source_texts: dict[int, str] = {}
    source_hashes: dict[int, str] = {}
    stale_loop_ids: list[int] = []

    for record in records:
        source_text = build_loop_semantic_text(
            record,
            project=projects_map.get(record.project_id) if record.project_id else None,
            tags=tags_map.get(record.id, []),
        )
        source_hash = semantic_source_hash(source_text)
        source_texts[record.id] = source_text
        source_hashes[record.id] = source_hash

        existing = existing_embeddings.get(record.id)
        if existing is None:
            stale_loop_ids.append(record.id)
            continue
        if existing.get("embed_model") != settings.embed_model:
            stale_loop_ids.append(record.id)
            continue
        if str(existing.get("source_text_hash") or "") != source_hash:
            stale_loop_ids.append(record.id)

    if not stale_loop_ids:
        return 0

    try:
        vectors = embed_texts(
            [source_texts[loop_id] for loop_id in stale_loop_ids],
            settings=settings,
        )
    except ValueError as exc:
        raise ValidationError("semantic_search", str(exc)) from None

    if len(vectors) != len(stale_loop_ids):
        raise ValidationError(
            "semantic_search",
            "embedding provider returned an unexpected number of vectors",
        )

    for loop_id, vector in zip(stale_loop_ids, vectors, strict=True):
        normalized_vector = vector.astype(np.float32)
        repo.upsert_loop_embedding(
            loop_id=loop_id,
            embedding_blob=normalized_vector.tobytes(),
            embedding_dim=int(normalized_vector.shape[0]),
            embedding_norm=float(np.linalg.norm(normalized_vector)),
            embed_model=settings.embed_model,
            source_text_hash=source_hashes[loop_id],
            conn=conn,
        )

    return len(stale_loop_ids)


@typingx.validate_io()
def rank_semantic_candidate_records(
    *,
    query: str,
    records: list["LoopRecord"],
    conn: sqlite3.Connection,
    min_score: float | None = None,
    settings: Settings | None = None,
) -> tuple[list[tuple["LoopRecord", float]], int]:
    """Rank candidate loop records by semantic similarity to a query."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("query", "cannot be empty")
    if min_score is not None and not 0.0 <= min_score <= 1.0:
        raise ValidationError("min_score", "must be between 0.0 and 1.0")

    settings = settings or get_settings()
    indexed_count = ensure_loop_embeddings(
        loop_ids=[record.id for record in records],
        conn=conn,
        settings=settings,
    )
    if not records:
        return [], indexed_count

    try:
        query_vectors = embed_texts([normalized_query], settings=settings)
    except ValueError as exc:
        raise ValidationError("semantic_search", str(exc)) from None
    if len(query_vectors) != 1:
        raise ValidationError(
            "semantic_search",
            "embedding provider returned an unexpected query vector count",
        )

    query_vec = query_vectors[0].astype(np.float32)
    query_norm = float(np.linalg.norm(query_vec)) + 1e-12
    embedding_rows = repo.read_loop_embeddings_batch(
        loop_ids=[record.id for record in records],
        conn=conn,
    )

    scored: list[tuple[LoopRecord, float]] = []
    for record in records:
        embedding = embedding_rows.get(record.id)
        if embedding is None:
            continue
        dim = int(embedding["embedding_dim"])
        vector = np.frombuffer(embedding["embedding_blob"], dtype=np.float32, count=dim)
        norm = float(embedding["embedding_norm"]) + 1e-12
        score = float(np.dot(vector, query_vec) / (norm * query_norm))
        if min_score is not None and score < min_score:
            continue
        scored.append((record, score))

    scored.sort(
        key=lambda item: (
            item[1],
            item[0].updated_at_utc,
            item[0].captured_at_utc,
            item[0].id,
        ),
        reverse=True,
    )
    return scored, indexed_count
