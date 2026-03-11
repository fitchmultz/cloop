"""Loop read and query service functions.

Purpose:
    Own read-only loop retrieval, query, prioritization, and cursor pagination
    so mutation orchestration does not share a service module with read paths.

Responsibilities:
    - Retrieve single loops and enriched loop collections
    - Execute status, tag, and DSL-based searches
    - Compute prioritized next-loop buckets
    - Provide cursor-paginated list and query endpoints

Non-scope:
    - Loop mutations and transitions
    - Saved-view or template management
    - Transport-level response shaping

Invariants/Assumptions:
    - Returned loop payloads are enriched with project names and tags
    - Cursor pagination fingerprints must remain stable for each query shape
    - Prioritization uses the shared repo candidate selection and settings weights
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import typingx
from ..settings import Settings, get_settings
from . import repo
from .errors import LoopNotFoundError
from .models import LoopRecord, LoopStatus, utc_now
from .pagination import build_next_cursor, prepare_cursor_state
from .prioritization import PriorityWeights, bucketize, compute_priority_score
from .utils import normalize_tag
from .write_ops import _enrich_records_batch, _record_to_dict


@typingx.validate_io()
def get_loop(*, loop_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Get a single enriched loop by ID."""
    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)
    project = repo.read_project_name(project_id=record.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
    return _record_to_dict(record, project=project, tags=tags)


@typingx.validate_io()
def list_loops(
    *,
    status: LoopStatus | None,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List loops with an optional status filter."""
    records = repo.list_loops(status=status, limit=limit, offset=offset, conn=conn)
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def list_loops_by_statuses(
    *,
    statuses: list[LoopStatus],
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List loops for multiple statuses."""
    records = repo.list_loops_by_statuses(
        statuses=statuses,
        limit=limit,
        offset=offset,
        conn=conn,
    )
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def list_loops_by_tag(
    *,
    tag: str,
    statuses: list[LoopStatus] | None,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List loops with a tag filter and optional status filter."""
    normalized = normalize_tag(tag)
    if not normalized:
        return []
    records = repo.list_loops_by_tag(
        tag=normalized,
        statuses=statuses,
        limit=limit,
        offset=offset,
        conn=conn,
    )
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def list_tags(*, conn: sqlite3.Connection) -> list[str]:
    """List all normalized loop tags."""
    return repo.list_tags(conn=conn)


@typingx.validate_io()
def search_loops(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Search loops using the free-text repo search path."""
    records = repo.search_loops(query=query, limit=limit, offset=offset, conn=conn)
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def next_loops(
    *,
    limit: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return prioritized next-action loops bucketed for action selection."""
    settings = settings or get_settings()
    now = utc_now()
    candidates = repo.list_next_loop_candidates(
        limit=settings.next_candidates_limit,
        now_utc=now,
        conn=conn,
    )
    candidate_ids = [record.id for record in candidates]
    blocked_ids = repo.has_open_dependencies_batch(loop_ids=candidate_ids, conn=conn)
    actionable_records: list[LoopRecord] = [
        record for record in candidates if record.id not in blocked_ids
    ]
    weights = PriorityWeights(
        due_weight=settings.priority_weight_due,
        urgency_weight=settings.priority_weight_urgency,
        importance_weight=settings.priority_weight_importance,
        time_penalty=settings.priority_weight_time_penalty,
        activation_penalty=settings.priority_weight_activation_penalty,
        blocked_penalty=settings.priority_weight_blocked_penalty,
    )
    scored = [
        (
            record,
            compute_priority_score(
                _record_to_dict(record),
                now_utc=now,
                w=weights,
                settings=settings,
            ),
        )
        for record in actionable_records
    ]
    scored_with_buckets: list[tuple[str, LoopRecord, float]] = []
    for record, score in scored:
        label = bucketize(_record_to_dict(record), now_utc=now, settings=settings)
        if label in {"due_soon", "quick_wins", "high_leverage", "standard"}:
            scored_with_buckets.append((label, record, score))
    scored_with_buckets.sort(key=lambda item: item[2], reverse=True)
    top_items = scored_with_buckets[:limit]

    all_loop_ids: list[int] = []
    all_project_ids: set[int] = set()
    for _label, record, _score in top_items:
        all_loop_ids.append(record.id)
        if record.project_id is not None:
            all_project_ids.add(record.project_id)

    projects_map = repo.read_project_names_batch(project_ids=all_project_ids, conn=conn)
    tags_map = repo.list_loop_tags_batch(loop_ids=all_loop_ids, conn=conn)

    response: dict[str, list[dict[str, Any]]] = {
        "due_soon": [],
        "quick_wins": [],
        "high_leverage": [],
        "standard": [],
    }
    for label, record, _score in top_items:
        project = projects_map.get(record.project_id) if record.project_id else None
        tags = tags_map.get(record.id, [])
        response[label].append(_record_to_dict(record, project=project, tags=tags))
    return response


@typingx.validate_io()
def search_loops_by_query(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Search loops using the canonical DSL query path."""
    records = repo.search_loops_by_query(
        query=query,
        limit=limit,
        offset=offset,
        conn=conn,
    )
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def list_loops_page(
    *,
    status: LoopStatus | None,
    limit: int,
    cursor: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """List loops with cursor-based pagination."""
    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "loop.list", "status": status.value if status else None},
        cursor=cursor,
    )
    records = repo.list_loops_cursor(
        status=status,
        limit=limit,
        snapshot_utc=state.snapshot_utc,
        cursor_anchor=state.cursor_anchor,
        conn=conn,
    )
    next_cursor = build_next_cursor(
        records=records,
        limit=limit,
        snapshot_utc=state.snapshot_utc,
        fingerprint=state.fingerprint,
    )
    return {
        "items": _enrich_records_batch(records[:limit], conn=conn),
        "next_cursor": next_cursor,
        "limit": limit,
    }


@typingx.validate_io()
def search_loops_by_query_page(
    *,
    query: str,
    limit: int,
    cursor: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Search loops with cursor-based pagination."""
    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "loop.search", "query": query},
        cursor=cursor,
    )
    records = repo.search_loops_by_query_cursor(
        query=query,
        limit=limit,
        snapshot_utc=state.snapshot_utc,
        cursor_anchor=state.cursor_anchor,
        conn=conn,
    )
    next_cursor = build_next_cursor(
        records=records,
        limit=limit,
        snapshot_utc=state.snapshot_utc,
        fingerprint=state.fingerprint,
    )
    return {
        "items": _enrich_records_batch(records[:limit], conn=conn),
        "next_cursor": next_cursor,
        "limit": limit,
    }
