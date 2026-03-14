"""Shared duplicate/related-loop review workflows.

Purpose:
    Own first-class relationship review built on the canonical semantic
    similarity substrate so HTTP, web UI, CLI, and MCP all share one contract.

Responsibilities:
    - Review duplicate and related-loop candidates for one loop
    - Build cross-loop relationship-review queues
    - Persist confirm/dismiss/resolve decisions for relationship pairs
    - Sync AI-generated related/duplicate suggestions without reviving dismissed state

Non-scope:
    - Merge preview and merge execution (see duplicates.py)
    - Transport-specific request/response shaping
    - Embedding source construction (see similarity.py)
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Literal

import numpy as np

from .. import typingx
from ..settings import Settings, get_settings
from . import repo, similarity
from .errors import LoopNotFoundError, ValidationError
from .models import LoopRecord, LoopStatus
from .serialization import enrich_loop_records_batch

RelationshipType = Literal["related", "duplicate"]
LinkState = Literal["active", "dismissed", "resolved"]


def _pair_key(loop_id: int, related_loop_id: int) -> tuple[int, int]:
    return (loop_id, related_loop_id) if loop_id < related_loop_id else (related_loop_id, loop_id)


def _validate_relationship_type(value: str) -> RelationshipType:
    if value == "related":
        return "related"
    if value == "duplicate":
        return "duplicate"
    raise ValidationError("relationship_type", "must be 'related' or 'duplicate'")


def _validate_link_state(value: str) -> LinkState:
    if value == "active":
        return "active"
    if value == "dismissed":
        return "dismissed"
    if value == "resolved":
        return "resolved"
    raise ValidationError("link_state", "must be active, dismissed, or resolved")


def _validate_loop_pair(*, loop_id: int, candidate_loop_id: int, conn: sqlite3.Connection) -> None:
    if loop_id == candidate_loop_id:
        raise ValidationError("candidate_loop_id", "cannot relate a loop to itself")
    if repo.read_loop(loop_id=loop_id, conn=conn) is None:
        raise LoopNotFoundError(loop_id)
    if repo.read_loop(loop_id=candidate_loop_id, conn=conn) is None:
        raise LoopNotFoundError(candidate_loop_id)


PairStateDetails = dict[str, Any]
PairStateMap = dict[tuple[int, int], dict[str, PairStateDetails]]


def _build_pair_state_map(rows: Iterable[dict[str, Any]]) -> PairStateMap:
    pair_state_map: PairStateMap = {}
    for row in rows:
        pair = _pair_key(int(row["loop_id"]), int(row["related_loop_id"]))
        rel_type = str(row["relationship_type"])
        existing = pair_state_map.setdefault(pair, {})
        current = existing.get(rel_type)
        candidate = {
            "state": str(row["link_state"]),
            "confidence": row.get("confidence"),
            "source": row.get("source"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        if current is None:
            existing[rel_type] = candidate
            continue

        state_rank = {"resolved": 3, "active": 2, "dismissed": 1}
        current_rank = state_rank.get(str(current["state"]), 0)
        candidate_rank = state_rank.get(str(candidate["state"]), 0)
        if candidate_rank > current_rank:
            existing[rel_type] = candidate
            continue
        if candidate_rank == current_rank:
            current_conf = float(current["confidence"] or -1.0)
            candidate_conf = float(candidate["confidence"] or -1.0)
            if candidate_conf > current_conf:
                existing[rel_type] = candidate

    return pair_state_map


def _score_records_against_source(
    *,
    source_record: LoopRecord,
    candidate_records: list[LoopRecord],
    conn: sqlite3.Connection,
    settings: Settings,
) -> tuple[list[tuple[LoopRecord, float]], int]:
    indexed_count = similarity.ensure_loop_embeddings(
        loop_ids=[source_record.id, *[record.id for record in candidate_records]],
        conn=conn,
        settings=settings,
    )
    if not candidate_records:
        return [], indexed_count

    embedding_rows = repo.read_loop_embeddings_batch(
        loop_ids=[source_record.id, *[record.id for record in candidate_records]],
        conn=conn,
    )
    source_embedding = embedding_rows.get(source_record.id)
    if source_embedding is None:
        return [], indexed_count

    source_dim = int(source_embedding["embedding_dim"])
    source_vec = np.frombuffer(
        source_embedding["embedding_blob"],
        dtype=np.float32,
        count=source_dim,
    )
    source_norm = float(source_embedding["embedding_norm"]) + 1e-12

    scored: list[tuple[LoopRecord, float]] = []
    for candidate in candidate_records:
        candidate_embedding = embedding_rows.get(candidate.id)
        if candidate_embedding is None:
            continue
        candidate_dim = int(candidate_embedding["embedding_dim"])
        candidate_vec = np.frombuffer(
            candidate_embedding["embedding_blob"],
            dtype=np.float32,
            count=candidate_dim,
        )
        candidate_norm = float(candidate_embedding["embedding_norm"]) + 1e-12
        score = float(np.dot(source_vec, candidate_vec) / (source_norm * candidate_norm))
        scored.append((candidate, score))

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


def _classify_candidate(
    *,
    score: float,
    pair_state: dict[str, dict[str, Any]],
    settings: Settings,
) -> RelationshipType | None:
    active_pair = any(str(details.get("state")) == "active" for details in pair_state.values())
    if active_pair:
        return None

    related_state = str(pair_state.get("related", {}).get("state") or "") or None
    duplicate_state = str(pair_state.get("duplicate", {}).get("state") or "") or None

    if score >= settings.duplicate_similarity_threshold:
        if duplicate_state == "resolved":
            return None
        if duplicate_state == "dismissed":
            if related_state in {"dismissed", "resolved"}:
                return None
            return "related"
        return "duplicate"

    if score >= settings.related_similarity_threshold:
        if related_state in {"dismissed", "resolved"}:
            return None
        return "related"

    return None


def _payload_by_loop_id(
    records: Iterable[LoopRecord],
    *,
    conn: sqlite3.Connection,
) -> dict[int, dict[str, Any]]:
    enriched = enrich_loop_records_batch(list(records), conn=conn)
    return {int(payload["id"]): payload for payload in enriched}


def _relationship_candidate_payload(
    *,
    loop_payload: dict[str, Any],
    relationship_type: RelationshipType,
    score: float,
    existing_state: str | None = None,
    existing_source: str | None = None,
) -> dict[str, Any]:
    return {
        **loop_payload,
        "relationship_type": relationship_type,
        "score": score,
        "raw_text_preview": (
            str(loop_payload["raw_text"])[:100]
            + ("..." if len(str(loop_payload["raw_text"])) > 100 else "")
        ),
        "existing_state": existing_state,
        "existing_source": existing_source,
    }


@typingx.validate_io()
def review_loop_relationships(
    *,
    loop_id: int,
    statuses: list[LoopStatus] | None,
    duplicate_limit: int,
    related_limit: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Review duplicate and related-loop candidates for one loop."""
    if duplicate_limit < 1:
        raise ValidationError("duplicate_limit", "must be positive")
    if related_limit < 1:
        raise ValidationError("related_limit", "must be positive")

    settings = settings or get_settings()
    source_record = repo.read_loop(loop_id=loop_id, conn=conn)
    if source_record is None:
        raise LoopNotFoundError(loop_id)

    if statuses is None:
        candidate_records = repo.list_all_loops(conn=conn)
    elif not statuses:
        candidate_records = []
    else:
        candidate_records = repo.list_loops_by_statuses(statuses=statuses, conn=conn)
    candidate_records = [record for record in candidate_records if record.id != loop_id]

    scored, indexed_count = _score_records_against_source(
        source_record=source_record,
        candidate_records=candidate_records,
        conn=conn,
        settings=settings,
    )

    if indexed_count:
        conn.commit()

    all_records = [source_record, *candidate_records]
    payload_by_id = _payload_by_loop_id(all_records, conn=conn)
    link_rows = repo.list_loop_links_for_loop_ids(
        loop_ids=[record.id for record in all_records],
        relationship_types=["related", "duplicate"],
        link_states=None,
        conn=conn,
    )
    pair_state_map = _build_pair_state_map(link_rows)

    duplicate_candidates: list[dict[str, Any]] = []
    related_candidates: list[dict[str, Any]] = []
    duplicate_count = 0
    related_count = 0

    for candidate_record, score in scored:
        pair_state = pair_state_map.get(_pair_key(loop_id, candidate_record.id), {})
        relationship_type = _classify_candidate(
            score=score,
            pair_state=pair_state,
            settings=settings,
        )
        if relationship_type is None:
            continue

        candidate_payload = _relationship_candidate_payload(
            loop_payload=payload_by_id[candidate_record.id],
            relationship_type=relationship_type,
            score=score,
        )
        if relationship_type == "duplicate":
            duplicate_count += 1
            if len(duplicate_candidates) < duplicate_limit:
                duplicate_candidates.append(candidate_payload)
        else:
            related_count += 1
            if len(related_candidates) < related_limit:
                related_candidates.append(candidate_payload)

    existing_related: list[dict[str, Any]] = []
    existing_duplicates: list[dict[str, Any]] = []
    for pair, rels in pair_state_map.items():
        if loop_id not in pair:
            continue
        candidate_loop_id = pair[1] if pair[0] == loop_id else pair[0]
        candidate_payload = payload_by_id.get(candidate_loop_id)
        if candidate_payload is None:
            continue
        for relationship_type in ("related", "duplicate"):
            details = rels.get(relationship_type)
            if not details or str(details.get("state")) != "active":
                continue
            payload = _relationship_candidate_payload(
                loop_payload=candidate_payload,
                relationship_type=relationship_type,
                score=float(details.get("confidence") or 0.0),
                existing_state=str(details.get("state")),
                existing_source=str(details.get("source") or ""),
            )
            if relationship_type == "related":
                existing_related.append(payload)
            else:
                existing_duplicates.append(payload)

    existing_related.sort(key=lambda item: (float(item["score"]), int(item["id"])), reverse=True)
    existing_duplicates.sort(key=lambda item: (float(item["score"]), int(item["id"])), reverse=True)

    return {
        "loop": payload_by_id[loop_id],
        "indexed_count": indexed_count,
        "candidate_count": len(candidate_records),
        "duplicate_count": duplicate_count,
        "related_count": related_count,
        "duplicate_candidates": duplicate_candidates,
        "related_candidates": related_candidates,
        "existing_duplicates": existing_duplicates,
        "existing_related": existing_related,
    }


def _list_relationship_review_queue_for_records(
    *,
    records: list[LoopRecord],
    relationship_kind: str,
    limit: int,
    candidate_limit: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    if relationship_kind not in {"all", "duplicate", "related"}:
        raise ValidationError("relationship_kind", "must be all, duplicate, or related")
    if limit < 1:
        raise ValidationError("limit", "must be positive")
    if candidate_limit < 1:
        raise ValidationError("candidate_limit", "must be positive")

    indexed_count = similarity.ensure_loop_embeddings(
        loop_ids=[record.id for record in records],
        conn=conn,
        settings=settings,
    )
    if indexed_count:
        conn.commit()
    if not records:
        return {
            "indexed_count": indexed_count,
            "loop_count": 0,
            "items": [],
        }

    payload_by_id = _payload_by_loop_id(records, conn=conn)
    embedding_rows = repo.read_loop_embeddings_batch(
        loop_ids=[record.id for record in records],
        conn=conn,
    )
    link_rows = repo.list_loop_links_for_loop_ids(
        loop_ids=[record.id for record in records],
        relationship_types=["related", "duplicate"],
        link_states=None,
        conn=conn,
    )
    pair_state_map = _build_pair_state_map(link_rows)

    duplicate_candidates_by_loop: dict[int, list[tuple[LoopRecord, float]]] = defaultdict(list)
    related_candidates_by_loop: dict[int, list[tuple[LoopRecord, float]]] = defaultdict(list)
    duplicate_counts_by_loop: dict[int, int] = defaultdict(int)
    related_counts_by_loop: dict[int, int] = defaultdict(int)

    for index, source_record in enumerate(records):
        source_embedding = embedding_rows.get(source_record.id)
        if source_embedding is None:
            continue
        source_dim = int(source_embedding["embedding_dim"])
        source_vec = np.frombuffer(
            source_embedding["embedding_blob"],
            dtype=np.float32,
            count=source_dim,
        )
        source_norm = float(source_embedding["embedding_norm"]) + 1e-12

        for candidate_record in records[index + 1 :]:
            candidate_embedding = embedding_rows.get(candidate_record.id)
            if candidate_embedding is None:
                continue
            candidate_dim = int(candidate_embedding["embedding_dim"])
            candidate_vec = np.frombuffer(
                candidate_embedding["embedding_blob"],
                dtype=np.float32,
                count=candidate_dim,
            )
            candidate_norm = float(candidate_embedding["embedding_norm"]) + 1e-12
            score = float(np.dot(source_vec, candidate_vec) / (source_norm * candidate_norm))
            pair_state = pair_state_map.get(_pair_key(source_record.id, candidate_record.id), {})
            bucket = _classify_candidate(score=score, pair_state=pair_state, settings=settings)
            if bucket is None:
                continue

            if bucket == "duplicate":
                duplicate_counts_by_loop[source_record.id] += 1
                duplicate_counts_by_loop[candidate_record.id] += 1
                duplicate_candidates_by_loop[source_record.id].append((candidate_record, score))
                duplicate_candidates_by_loop[candidate_record.id].append((source_record, score))
            else:
                related_counts_by_loop[source_record.id] += 1
                related_counts_by_loop[candidate_record.id] += 1
                related_candidates_by_loop[source_record.id].append((candidate_record, score))
                related_candidates_by_loop[candidate_record.id].append((source_record, score))

    items: list[dict[str, Any]] = []
    for record in records:
        duplicate_candidates = sorted(
            duplicate_candidates_by_loop.get(record.id, []),
            key=lambda item: (item[1], item[0].updated_at_utc, item[0].id),
            reverse=True,
        )
        related_candidates = sorted(
            related_candidates_by_loop.get(record.id, []),
            key=lambda item: (item[1], item[0].updated_at_utc, item[0].id),
            reverse=True,
        )

        if relationship_kind == "duplicate":
            has_pending = bool(duplicate_candidates)
        elif relationship_kind == "related":
            has_pending = bool(related_candidates)
        else:
            has_pending = bool(duplicate_candidates or related_candidates)
        if not has_pending:
            continue

        item = {
            "loop": payload_by_id[record.id],
            "duplicate_count": duplicate_counts_by_loop.get(record.id, 0),
            "related_count": related_counts_by_loop.get(record.id, 0),
            "duplicate_candidates": [
                _relationship_candidate_payload(
                    loop_payload=payload_by_id[candidate.id],
                    relationship_type="duplicate",
                    score=score,
                )
                for candidate, score in duplicate_candidates[:candidate_limit]
            ],
            "related_candidates": [
                _relationship_candidate_payload(
                    loop_payload=payload_by_id[candidate.id],
                    relationship_type="related",
                    score=score,
                )
                for candidate, score in related_candidates[:candidate_limit]
            ],
        }
        item["top_score"] = max(
            [candidate[1] for candidate in duplicate_candidates[:1]]
            + [candidate[1] for candidate in related_candidates[:1]]
            or [0.0]
        )
        items.append(item)

    items.sort(
        key=lambda item: (
            float(item["top_score"]),
            str(item["loop"]["updated_at_utc"]),
            int(item["loop"]["id"]),
        ),
        reverse=True,
    )

    return {
        "indexed_count": indexed_count,
        "loop_count": len(items),
        "items": items[:limit],
    }


@typingx.validate_io()
def list_relationship_review_queue(
    *,
    statuses: list[LoopStatus] | None,
    relationship_kind: str,
    limit: int,
    candidate_limit: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List loops that currently have pending duplicate/related review work."""
    settings = settings or get_settings()
    if statuses is None:
        records = repo.list_all_loops(conn=conn)
    elif not statuses:
        records = []
    else:
        records = repo.list_loops_by_statuses(statuses=statuses, conn=conn)
    return _list_relationship_review_queue_for_records(
        records=records,
        relationship_kind=relationship_kind,
        limit=limit,
        candidate_limit=candidate_limit,
        conn=conn,
        settings=settings,
    )


@typingx.validate_io()
def list_relationship_review_queue_for_query(
    *,
    query: str,
    relationship_kind: str,
    limit: int,
    candidate_limit: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List loops with pending relationship-review work within a DSL query scope."""
    settings = settings or get_settings()
    records = repo.search_loops_by_query(query=query, limit=None, conn=conn)
    return _list_relationship_review_queue_for_records(
        records=records,
        relationship_kind=relationship_kind,
        limit=limit,
        candidate_limit=candidate_limit,
        conn=conn,
        settings=settings,
    )


def _set_bidirectional_relationship_state(
    *,
    loop_id: int,
    candidate_loop_id: int,
    relationship_type: RelationshipType,
    link_state: LinkState,
    confidence: float | None,
    source: str,
    conn: sqlite3.Connection,
) -> None:
    repo.upsert_loop_link(
        loop_id=loop_id,
        related_loop_id=candidate_loop_id,
        relationship_type=relationship_type,
        link_state=link_state,
        confidence=confidence,
        source=source,
        conn=conn,
    )
    repo.upsert_loop_link(
        loop_id=candidate_loop_id,
        related_loop_id=loop_id,
        relationship_type=relationship_type,
        link_state=link_state,
        confidence=confidence,
        source=source,
        conn=conn,
    )


@typingx.validate_io()
def confirm_relationship(
    *,
    loop_id: int,
    candidate_loop_id: int,
    relationship_type: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Confirm a relationship pair as active in both directions."""
    normalized_type = _validate_relationship_type(relationship_type)
    _validate_loop_pair(loop_id=loop_id, candidate_loop_id=candidate_loop_id, conn=conn)

    _set_bidirectional_relationship_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        relationship_type=normalized_type,
        link_state="active",
        confidence=None,
        source="user",
        conn=conn,
    )
    other_type: RelationshipType = "related" if normalized_type == "duplicate" else "duplicate"
    _set_bidirectional_relationship_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        relationship_type=other_type,
        link_state="dismissed",
        confidence=None,
        source="user",
        conn=conn,
    )

    return {
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "relationship_type": normalized_type,
        "link_state": "active",
    }


@typingx.validate_io()
def dismiss_relationship(
    *,
    loop_id: int,
    candidate_loop_id: int,
    relationship_type: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Dismiss a suggested relationship pair in both directions."""
    normalized_type = _validate_relationship_type(relationship_type)
    _validate_loop_pair(loop_id=loop_id, candidate_loop_id=candidate_loop_id, conn=conn)
    _set_bidirectional_relationship_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        relationship_type=normalized_type,
        link_state="dismissed",
        confidence=None,
        source="user",
        conn=conn,
    )
    return {
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "relationship_type": normalized_type,
        "link_state": "dismissed",
    }


@typingx.validate_io()
def resolve_relationship(
    *,
    loop_id: int,
    candidate_loop_id: int,
    relationship_type: str,
    conn: sqlite3.Connection,
    source: str = "system",
) -> None:
    """Resolve a relationship pair in both directions."""
    normalized_type = _validate_relationship_type(relationship_type)
    _validate_loop_pair(loop_id=loop_id, candidate_loop_id=candidate_loop_id, conn=conn)
    _set_bidirectional_relationship_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        relationship_type=normalized_type,
        link_state="resolved",
        confidence=None,
        source=source,
        conn=conn,
    )


@typingx.validate_io()
def sync_relationship_suggestions(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
    duplicate_limit: int = 3,
    related_limit: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Persist AI-suggested related/duplicate links for one loop."""
    settings = settings or get_settings()
    result = review_loop_relationships(
        loop_id=loop_id,
        statuses=[
            LoopStatus.INBOX,
            LoopStatus.ACTIONABLE,
            LoopStatus.BLOCKED,
            LoopStatus.SCHEDULED,
        ],
        duplicate_limit=duplicate_limit,
        related_limit=related_limit,
        conn=conn,
        settings=settings,
    )

    for candidate in result["related_candidates"]:
        insert_confidence = float(candidate["score"])
        repo.insert_loop_link(
            loop_id=loop_id,
            related_loop_id=int(candidate["id"]),
            relationship_type="related",
            confidence=insert_confidence,
            source="ai",
            conn=conn,
        )
        repo.insert_loop_link(
            loop_id=int(candidate["id"]),
            related_loop_id=loop_id,
            relationship_type="related",
            confidence=insert_confidence,
            source="ai",
            conn=conn,
        )

    for candidate in result["duplicate_candidates"]:
        insert_confidence = float(candidate["score"])
        repo.insert_loop_link(
            loop_id=loop_id,
            related_loop_id=int(candidate["id"]),
            relationship_type="duplicate",
            confidence=insert_confidence,
            source="ai",
            conn=conn,
        )
        repo.insert_loop_link(
            loop_id=int(candidate["id"]),
            related_loop_id=loop_id,
            relationship_type="duplicate",
            confidence=insert_confidence,
            source="ai",
            conn=conn,
        )

    return {
        "related": result["related_candidates"],
        "duplicates": result["duplicate_candidates"],
    }
