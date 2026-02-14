from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .. import typingx
from ..settings import Settings, get_settings
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import LoopNotFoundError, TransitionError, ValidationError
from .models import (
    EnrichmentState,
    LoopEventType,
    LoopRecord,
    LoopStatus,
    format_utc_datetime,
    is_terminal_status,
    parse_client_datetime,
    parse_utc_datetime,
    utc_now,
)
from .prioritization import PriorityWeights, bucketize, compute_priority_score

_ALLOWED_TRANSITIONS: dict[LoopStatus, set[LoopStatus]] = {
    LoopStatus.INBOX: {
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.ACTIONABLE: {
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.BLOCKED: {
        LoopStatus.ACTIONABLE,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.SCHEDULED: {
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.COMPLETED,
        LoopStatus.DROPPED,
    },
    LoopStatus.COMPLETED: {
        LoopStatus.INBOX,
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.DROPPED,
    },
    LoopStatus.DROPPED: {
        LoopStatus.INBOX,
        LoopStatus.ACTIONABLE,
        LoopStatus.BLOCKED,
        LoopStatus.SCHEDULED,
        LoopStatus.COMPLETED,
    },
}

_LOCKABLE_FIELDS = {
    "raw_text",
    "title",
    "summary",
    "definition_of_done",
    "next_action",
    "due_at_utc",
    "snooze_until_utc",
    "time_minutes",
    "activation_energy",
    "urgency",
    "importance",
    "project_id",
    "blocked_reason",
    "completion_note",
    "tags",
}


def _record_to_dict(
    record: LoopRecord,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "raw_text": record.raw_text,
        "title": record.title,
        "summary": record.summary,
        "definition_of_done": record.definition_of_done,
        "next_action": record.next_action,
        "status": record.status.value,
        "captured_at_utc": format_utc_datetime(record.captured_at_utc),
        "captured_tz_offset_min": record.captured_tz_offset_min,
        "due_at_utc": format_utc_datetime(record.due_at_utc) if record.due_at_utc else None,
        "snooze_until_utc": (
            format_utc_datetime(record.snooze_until_utc) if record.snooze_until_utc else None
        ),
        "time_minutes": record.time_minutes,
        "activation_energy": record.activation_energy,
        "urgency": record.urgency,
        "importance": record.importance,
        "project_id": record.project_id,
        "blocked_reason": record.blocked_reason,
        "completion_note": record.completion_note,
        "project": project,
        "tags": tags or [],
        "user_locks": list(record.user_locks),
        "provenance": dict(record.provenance),
        "enrichment_state": record.enrichment_state.value,
        "created_at_utc": format_utc_datetime(record.created_at_utc),
        "updated_at_utc": format_utc_datetime(record.updated_at_utc),
        "closed_at_utc": (
            format_utc_datetime(record.closed_at_utc) if record.closed_at_utc else None
        ),
    }


def _enrich_records_batch(
    records: list[LoopRecord],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Enrich multiple loop records with project names and tags in batch.

    This avoids the N+1 query problem by fetching all projects and tags
    in just 2 queries total, regardless of the number of records.
    """
    if not records:
        return []

    # Collect all project IDs and loop IDs
    project_ids = {r.project_id for r in records if r.project_id is not None}
    loop_ids = [r.id for r in records]

    # Batch fetch all projects and tags in just 2 queries
    projects_map = repo.read_project_names_batch(project_ids=project_ids, conn=conn)
    tags_map = repo.list_loop_tags_batch(loop_ids=loop_ids, conn=conn)

    # Build the response dicts
    payloads: list[dict[str, Any]] = []
    for record in records:
        project = projects_map.get(record.project_id) if record.project_id else None
        tags = tags_map.get(record.id, [])
        payloads.append(_record_to_dict(record, project=project, tags=tags))

    return payloads


@typingx.validate_io()
def capture_loop(
    *,
    raw_text: str,
    captured_at_iso: str,
    client_tz_offset_min: int,
    status: LoopStatus,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    captured_at_utc = parse_client_datetime(
        captured_at_iso,
        tz_offset_min=client_tz_offset_min,
    )
    captured_at_utc_str = format_utc_datetime(captured_at_utc)
    with conn:
        record = repo.create_loop(
            raw_text=raw_text,
            captured_at_utc=captured_at_utc_str,
            captured_tz_offset_min=client_tz_offset_min,
            status=status,
            conn=conn,
        )
        event_payload = {
            "raw_text": raw_text,
            "status": status.value,
            "captured_at_utc": captured_at_utc_str,
            "captured_tz_offset_min": client_tz_offset_min,
        }
        event_id = repo.insert_loop_event(
            loop_id=record.id,
            event_type=LoopEventType.CAPTURE.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.CAPTURE.value,
            payload=event_payload,
            conn=conn,
        )
    project = repo.read_project_name(project_id=record.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
    return _record_to_dict(record, project=project, tags=tags)


@typingx.validate_io()
def get_loop(*, loop_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
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
    normalized = tag.strip().lower()
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
    return repo.list_tags(conn=conn)


@typingx.validate_io()
def export_loops(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    records = repo.list_all_loops(conn=conn)
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def import_loops(
    *,
    loops: list[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> int:
    imported = 0
    now = utc_now()
    with conn:
        for item in loops:
            if isinstance(item, Mapping):
                item_map = dict(item)
            else:
                item_map = item.model_dump()
            status = LoopStatus(str(item_map.get("status", "inbox")))
            captured_at = item_map.get("captured_at_utc")
            if captured_at:
                captured_at = format_utc_datetime(parse_utc_datetime(captured_at))
            else:
                captured_at = format_utc_datetime(now)
            created_at = item_map.get("created_at_utc") or captured_at
            created_at = format_utc_datetime(parse_utc_datetime(created_at))
            updated_at = item_map.get("updated_at_utc") or created_at
            updated_at = format_utc_datetime(parse_utc_datetime(updated_at))
            closed_at = item_map.get("closed_at_utc")
            closed_at = format_utc_datetime(parse_utc_datetime(closed_at)) if closed_at else None
            project_name = item_map.get("project")
            project_id = None
            if project_name:
                project_id = repo.upsert_project(name=str(project_name).strip(), conn=conn)
            payload = {
                "raw_text": str(item_map.get("raw_text", "")),
                "title": item_map.get("title"),
                "summary": item_map.get("summary"),
                "definition_of_done": item_map.get("definition_of_done"),
                "next_action": item_map.get("next_action"),
                "status": status.value,
                "captured_at_utc": captured_at,
                "captured_tz_offset_min": int(item_map.get("captured_tz_offset_min", 0)),
                "due_at_utc": item_map.get("due_at_utc"),
                "snooze_until_utc": item_map.get("snooze_until_utc"),
                "time_minutes": item_map.get("time_minutes"),
                "activation_energy": item_map.get("activation_energy"),
                "urgency": item_map.get("urgency"),
                "importance": item_map.get("importance"),
                "blocked_reason": item_map.get("blocked_reason"),
                "completion_note": item_map.get("completion_note"),
                "user_locks_json": json.dumps(item_map.get("user_locks") or []),
                "provenance_json": json.dumps(item_map.get("provenance") or {}),
                "enrichment_state": item_map.get("enrichment_state") or EnrichmentState.IDLE.value,
                "created_at": created_at,
                "updated_at": updated_at,
                "closed_at": closed_at,
            }
            loop_id = repo.insert_loop_from_export(
                payload=payload,
                project_id=project_id,
                conn=conn,
            )
            tags = item_map.get("tags") or []
            if tags:
                normalized_tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
                repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
            imported += 1
    return imported


@typingx.validate_io()
def update_loop(
    *,
    loop_id: int,
    fields: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    if "status" in fields:
        raise ValidationError("status", "use /loops/{id}/status or /loops/{id}/close endpoints")
    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)
    locked_fields = set(record.user_locks)
    mutable_fields = dict(fields)
    tags = None
    if "tags" in mutable_fields:
        tags = mutable_fields.pop("tags")
        if tags is not None and not isinstance(tags, list):
            tags = [tags]
    project_name = None
    if "project" in mutable_fields:
        project_name = mutable_fields.pop("project")
        project_name = str(project_name).strip() if project_name else ""
        if project_name:
            mutable_fields["project_id"] = "pending"
        else:
            mutable_fields["project_id"] = None

    for field_name in {**mutable_fields, **({"tags": tags} if tags is not None else {})}.keys():
        if field_name in _LOCKABLE_FIELDS:
            locked_fields.add(field_name)
    updated_fields = dict(mutable_fields)
    updated_fields["user_locks_json"] = json.dumps(sorted(locked_fields))
    with conn:
        if project_name:
            project_id = repo.upsert_project(name=project_name, conn=conn)
            updated_fields["project_id"] = project_id
        updated = repo.update_loop_fields(loop_id=loop_id, fields=updated_fields, conn=conn)
        if tags is not None:
            normalized_tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
            repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
        event_payload = {"fields": dict(fields)}
        event_id = repo.insert_loop_event(
            loop_id=updated.id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
    project = repo.read_project_name(project_id=updated.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
    return _record_to_dict(updated, project=project, tags=tags)


@typingx.validate_io()
def transition_status(
    *,
    loop_id: int,
    to_status: LoopStatus,
    conn: sqlite3.Connection,
    note: str | None = None,
) -> dict[str, Any]:
    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)
    if record.status == to_status:
        project = repo.read_project_name(project_id=record.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
        return _record_to_dict(record, project=project, tags=tags)
    allowed = _ALLOWED_TRANSITIONS.get(record.status, set())
    if to_status not in allowed:
        raise TransitionError(record.status.value, to_status.value)
    closed_at = None
    if is_terminal_status(to_status):
        closed_at = format_utc_datetime(utc_now())
    with conn:
        updates = {"status": to_status.value, "closed_at": closed_at}
        if to_status is LoopStatus.COMPLETED and note and note.strip():
            updates["completion_note"] = note.strip()
        updated = repo.update_loop_fields(
            loop_id=loop_id,
            fields=updates,
            conn=conn,
        )
        event_type = (
            LoopEventType.CLOSE.value
            if is_terminal_status(to_status)
            else LoopEventType.STATUS_CHANGE.value
        )
        payload: dict[str, Any] = {"from": record.status.value, "to": to_status.value}
        if note:
            payload["note"] = note
        if closed_at:
            payload["closed_at_utc"] = closed_at
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
    project = repo.read_project_name(project_id=updated.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
    return _record_to_dict(updated, project=project, tags=tags)


@typingx.validate_io()
def request_enrichment(*, loop_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)
    with conn:
        updated = repo.update_loop_fields(
            loop_id=loop_id,
            fields={"enrichment_state": EnrichmentState.PENDING.value},
            conn=conn,
        )
        event_payload = {"state": EnrichmentState.PENDING.value}
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=LoopEventType.ENRICH_REQUEST.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.ENRICH_REQUEST.value,
            payload=event_payload,
            conn=conn,
        )
    project = repo.read_project_name(project_id=updated.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
    return _record_to_dict(updated, project=project, tags=tags)


@typingx.validate_io()
def search_loops(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    records = repo.search_loops(query=query, limit=limit, offset=offset, conn=conn)
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def next_loops(
    *,
    limit: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, list[dict[str, Any]]]:
    settings = settings or get_settings()
    candidates = repo.list_loops_by_statuses(
        statuses=[LoopStatus.INBOX, LoopStatus.ACTIONABLE],
        conn=conn,
    )
    now = utc_now()
    actionable_records: list[LoopRecord] = []
    for record in candidates:
        if not record.next_action:
            continue
        if record.snooze_until_utc and record.snooze_until_utc > now:
            continue
        actionable_records.append(record)

    weights = PriorityWeights(
        due_weight=settings.priority_weight_due,
        urgency_weight=settings.priority_weight_urgency,
        importance_weight=settings.priority_weight_importance,
        time_penalty=settings.priority_weight_time_penalty,
        activation_penalty=settings.priority_weight_activation_penalty,
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

    buckets = {"due_soon": [], "quick_wins": [], "high_leverage": [], "standard": []}
    for record, score in scored:
        label = bucketize(_record_to_dict(record), now_utc=now, settings=settings)
        if label in buckets:
            buckets[label].append((record, score))

    # Collect all loop IDs and project IDs for batch enrichment
    all_loop_ids: list[int] = []
    all_project_ids: set[int] = set()
    for items in buckets.values():
        for record, _score in items:
            all_loop_ids.append(record.id)
            if record.project_id is not None:
                all_project_ids.add(record.project_id)

    # Batch fetch all projects and tags in just 2 queries
    projects_map = repo.read_project_names_batch(project_ids=all_project_ids, conn=conn)
    tags_map = repo.list_loop_tags_batch(loop_ids=all_loop_ids, conn=conn)

    response: dict[str, list[dict[str, Any]]] = {}
    for label, items in buckets.items():
        items.sort(key=lambda item: item[1], reverse=True)
        payloads = []
        for record, _score in items[:limit]:
            project = projects_map.get(record.project_id) if record.project_id else None
            tags = tags_map.get(record.id, [])
            payloads.append(_record_to_dict(record, project=project, tags=tags))
        response[label] = payloads
    return response


@typingx.validate_io()
def search_loops_by_query(
    *,
    query: str,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Search loops using the DSL query language.

    This is the canonical query path used by API, CLI, MCP, and UI.
    Results are enriched with project names and tags.

    Args:
        query: DSL query string (e.g., 'status:inbox tag:work due:today')
        limit: Maximum number of results
        offset: Pagination offset
        conn: Database connection

    Returns:
        List of enriched loop dicts
    """
    records = repo.search_loops_by_query(
        query=query,
        limit=limit,
        offset=offset,
        conn=conn,
    )
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def create_loop_view(
    *,
    name: str,
    query: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a new saved view.

    Args:
        name: Unique view name
        query: DSL query string
        description: Optional description
        conn: Database connection

    Returns:
        Created view record

    Raises:
        ValidationError: If name already exists or query is invalid
    """
    return repo.create_loop_view(
        name=name,
        query=query,
        description=description,
        conn=conn,
    )


@typingx.validate_io()
def list_loop_views(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all saved views.

    Args:
        conn: Database connection

    Returns:
        List of view records, ordered by name
    """
    return repo.list_loop_views(conn=conn)


@typingx.validate_io()
def get_loop_view(*, view_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Get a saved view by ID.

    Args:
        view_id: View ID
        conn: Database connection

    Returns:
        View record

    Raises:
        ValidationError: If view not found
    """
    view = repo.get_loop_view(view_id=view_id, conn=conn)
    if view is None:
        raise ValidationError("view_id", f"view {view_id} not found")
    return view


@typingx.validate_io()
def update_loop_view(
    *,
    view_id: int,
    name: str | None = None,
    query: str | None = None,
    description: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a saved view.

    Args:
        view_id: View ID
        name: New name (optional)
        query: New query string (optional)
        description: New description (optional)
        conn: Database connection

    Returns:
        Updated view record

    Raises:
        ValidationError: If view not found, name conflict, or query invalid
    """
    return repo.update_loop_view(
        view_id=view_id,
        name=name,
        query=query,
        description=description,
        conn=conn,
    )


@typingx.validate_io()
def delete_loop_view(*, view_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a saved view.

    Args:
        view_id: View ID
        conn: Database connection

    Returns:
        True if deleted

    Raises:
        ValidationError: If view not found
    """
    deleted = repo.delete_loop_view(view_id=view_id, conn=conn)
    if not deleted:
        raise ValidationError("view_id", f"view {view_id} not found")
    return True


@typingx.validate_io()
def apply_loop_view(
    *,
    view_id: int,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Apply a saved view and return matching loops.

    Args:
        view_id: View ID
        limit: Maximum number of results
        offset: Pagination offset
        conn: Database connection

    Returns:
        Dict with view info and matching loops

    Raises:
        ValidationError: If view not found or query invalid
    """
    view = repo.get_loop_view(view_id=view_id, conn=conn)
    if view is None:
        raise ValidationError("view_id", f"view {view_id} not found")

    loops = search_loops_by_query(
        query=view["query"],
        limit=limit,
        offset=offset,
        conn=conn,
    )

    return {
        "view": view,
        "query": view["query"],
        "limit": limit,
        "offset": offset,
        "items": loops,
    }


def _build_list_fingerprint(status: LoopStatus | None) -> str:
    from .pagination import fingerprint_payload

    return fingerprint_payload({"tool": "loop.list", "status": status.value if status else None})


def _build_search_fingerprint(query: str) -> str:
    from .pagination import fingerprint_payload

    return fingerprint_payload({"tool": "loop.search", "query": query})


def _build_view_fingerprint(view_id: int, query: str) -> str:
    from .pagination import fingerprint_payload

    return fingerprint_payload({"tool": "loop.view.apply", "view_id": view_id, "query": query})


def _format_sqlite_timestamp(dt: Any) -> str:
    """Format datetime for SQLite comparison (YYYY-MM-DD HH:MM:SS)."""
    s = format_utc_datetime(dt)
    if "T" in s:
        s = s.replace("T", " ")
    if "+" in s:
        s = s.split("+")[0]
    if s.endswith("Z"):
        s = s[:-1]
    return s.strip()


@typingx.validate_io()
def list_loops_page(
    *,
    status: LoopStatus | None,
    limit: int,
    cursor: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """List loops with cursor-based pagination.

    Args:
        status: Optional status filter
        limit: Maximum number of results
        cursor: Optional cursor token for continuation
        conn: Database connection

    Returns:
        Dict with items, next_cursor (or None), and limit
    """
    from .pagination import LoopCursor, decode_cursor, encode_cursor

    fingerprint = _build_list_fingerprint(status)
    snapshot_utc = _format_sqlite_timestamp(utc_now())

    cursor_anchor: tuple[str, str, int] | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor, expected_fingerprint=fingerprint)
        snapshot_utc = decoded.snapshot_utc
        cursor_anchor = (decoded.updated_at_utc, decoded.captured_at_utc, decoded.loop_id)

    records = repo.list_loops_cursor(
        status=status,
        limit=limit,
        snapshot_utc=snapshot_utc,
        cursor_anchor=cursor_anchor,
        conn=conn,
    )

    has_more = len(records) > limit
    items_records = records[:limit]

    next_cursor: str | None = None
    if has_more and items_records:
        last = items_records[-1]
        loop_cursor = LoopCursor(
            snapshot_utc=snapshot_utc,
            updated_at_utc=_format_sqlite_timestamp(last.updated_at_utc),
            captured_at_utc=_format_sqlite_timestamp(last.captured_at_utc),
            loop_id=last.id,
            fingerprint=fingerprint,
        )
        next_cursor = encode_cursor(loop_cursor)

    items = _enrich_records_batch(items_records, conn=conn)
    return {"items": items, "next_cursor": next_cursor, "limit": limit}


@typingx.validate_io()
def search_loops_by_query_page(
    *,
    query: str,
    limit: int,
    cursor: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Search loops with cursor-based pagination.

    Args:
        query: DSL query string
        limit: Maximum number of results
        cursor: Optional cursor token for continuation
        conn: Database connection

    Returns:
        Dict with items, next_cursor (or None), and limit
    """
    from .pagination import LoopCursor, decode_cursor, encode_cursor

    fingerprint = _build_search_fingerprint(query)
    snapshot_utc = _format_sqlite_timestamp(utc_now())

    cursor_anchor: tuple[str, str, int] | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor, expected_fingerprint=fingerprint)
        snapshot_utc = decoded.snapshot_utc
        cursor_anchor = (decoded.updated_at_utc, decoded.captured_at_utc, decoded.loop_id)

    records = repo.search_loops_by_query_cursor(
        query=query,
        limit=limit,
        snapshot_utc=snapshot_utc,
        cursor_anchor=cursor_anchor,
        conn=conn,
    )

    has_more = len(records) > limit
    items_records = records[:limit]

    next_cursor: str | None = None
    if has_more and items_records:
        last = items_records[-1]
        loop_cursor = LoopCursor(
            snapshot_utc=snapshot_utc,
            updated_at_utc=_format_sqlite_timestamp(last.updated_at_utc),
            captured_at_utc=_format_sqlite_timestamp(last.captured_at_utc),
            loop_id=last.id,
            fingerprint=fingerprint,
        )
        next_cursor = encode_cursor(loop_cursor)

    items = _enrich_records_batch(items_records, conn=conn)
    return {"items": items, "next_cursor": next_cursor, "limit": limit}


@typingx.validate_io()
def apply_loop_view_page(
    *,
    view_id: int,
    limit: int,
    cursor: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Apply a saved view with cursor-based pagination.

    Args:
        view_id: View ID
        limit: Maximum number of results
        cursor: Optional cursor token for continuation
        conn: Database connection

    Returns:
        Dict with view info, query, limit, cursor, next_cursor, and items

    Raises:
        ValidationError: If view not found or query invalid
    """
    from .pagination import LoopCursor, decode_cursor, encode_cursor

    view = repo.get_loop_view(view_id=view_id, conn=conn)
    if view is None:
        raise ValidationError("view_id", f"view {view_id} not found")

    query = view["query"]
    fingerprint = _build_view_fingerprint(view_id, query)
    snapshot_utc = _format_sqlite_timestamp(utc_now())

    cursor_anchor: tuple[str, str, int] | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor, expected_fingerprint=fingerprint)
        snapshot_utc = decoded.snapshot_utc
        cursor_anchor = (decoded.updated_at_utc, decoded.captured_at_utc, decoded.loop_id)

    records = repo.search_loops_by_query_cursor(
        query=query,
        limit=limit,
        snapshot_utc=snapshot_utc,
        cursor_anchor=cursor_anchor,
        conn=conn,
    )

    has_more = len(records) > limit
    items_records = records[:limit]

    next_cursor: str | None = None
    if has_more and items_records:
        last = items_records[-1]
        loop_cursor = LoopCursor(
            snapshot_utc=snapshot_utc,
            updated_at_utc=_format_sqlite_timestamp(last.updated_at_utc),
            captured_at_utc=_format_sqlite_timestamp(last.captured_at_utc),
            loop_id=last.id,
            fingerprint=fingerprint,
        )
        next_cursor = encode_cursor(loop_cursor)

    items = _enrich_records_batch(items_records, conn=conn)
    return {
        "view": view,
        "query": query,
        "limit": limit,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "items": items,
    }


@typingx.validate_io()
def bulk_update_loops(
    *,
    updates: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk update multiple loops.

    Args:
        updates: List of updates, each with loop_id and fields
        transactional: If True, rollback all on any failure
        conn: Database connection

    Returns:
        Dict with ok, transactional, results (per-item), succeeded, failed
    """

    class _Rollback(Exception):
        pass

    def _update_single(loop_id: int, fields: Mapping[str, Any]) -> dict[str, Any]:
        if "status" in fields:
            raise ValidationError("status", "use /loops/{id}/status or /loops/{id}/close endpoints")
        record = repo.read_loop(loop_id=loop_id, conn=conn)
        if record is None:
            raise LoopNotFoundError(loop_id)
        locked_fields = set(record.user_locks)
        mutable_fields = dict(fields)
        tags = None
        if "tags" in mutable_fields:
            tags = mutable_fields.pop("tags")
            if tags is not None and not isinstance(tags, list):
                tags = [tags]
        project_name = None
        if "project" in mutable_fields:
            project_name = mutable_fields.pop("project")
            project_name = str(project_name).strip() if project_name else ""
            if project_name:
                mutable_fields["project_id"] = "pending"
            else:
                mutable_fields["project_id"] = None

        for field_name in {**mutable_fields, **({"tags": tags} if tags is not None else {})}.keys():
            if field_name in _LOCKABLE_FIELDS:
                locked_fields.add(field_name)
        updated_fields = dict(mutable_fields)
        updated_fields["user_locks_json"] = json.dumps(sorted(locked_fields))
        if project_name:
            project_id = repo.upsert_project(name=project_name, conn=conn)
            updated_fields["project_id"] = project_id
        updated = repo.update_loop_fields(loop_id=loop_id, fields=updated_fields, conn=conn)
        if tags is not None:
            normalized_tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
            repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
        event_payload = {"fields": dict(fields)}
        event_id = repo.insert_loop_event(
            loop_id=updated.id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        project = repo.read_project_name(project_id=updated.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
        return _record_to_dict(updated, project=project, tags=tags)

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    if transactional:
        try:
            with conn:
                for idx, item in enumerate(updates):
                    loop_id = item.get("loop_id")
                    fields = item.get("fields", {})

                    if not isinstance(loop_id, int):
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "loop_id must be an integer",
                                },
                            }
                        )
                        failed += 1
                        continue

                    try:
                        record = _update_single(loop_id, fields)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": True,
                                "loop": record,
                            }
                        )
                        succeeded += 1
                    except Exception as exc:
                        error_code = _classify_error(exc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {"code": error_code, "message": str(exc)},
                            }
                        )
                        failed += 1

                if failed > 0:
                    raise _Rollback()
        except _Rollback:
            return {
                "ok": False,
                "transactional": True,
                "results": _rollback_transaction_results(results),
                "succeeded": 0,
                "failed": len(updates),
            }
    else:
        for idx, item in enumerate(updates):
            loop_id = item.get("loop_id")
            fields = item.get("fields", {})

            if not isinstance(loop_id, int):
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "loop_id must be an integer",
                        },
                    }
                )
                failed += 1
                continue

            try:
                with conn:
                    record = _update_single(loop_id, fields)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": True,
                        "loop": record,
                    }
                )
                succeeded += 1
            except Exception as exc:
                error_code = _classify_error(exc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                failed += 1

    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": succeeded,
        "failed": failed,
    }


@typingx.validate_io()
def bulk_close_loops(
    *,
    items: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk close multiple loops.

    Args:
        items: List of items with loop_id, optional status (default completed), optional note
        transactional: If True, rollback all on any failure
        conn: Database connection

    Returns:
        Dict with ok, transactional, results (per-item), succeeded, failed
    """

    class _Rollback(Exception):
        pass

    def _close_single(loop_id: int, to_status: LoopStatus, note: str | None) -> dict[str, Any]:
        record = repo.read_loop(loop_id=loop_id, conn=conn)
        if record is None:
            raise LoopNotFoundError(loop_id)
        if record.status == to_status:
            project = repo.read_project_name(project_id=record.project_id, conn=conn)
            tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
            return _record_to_dict(record, project=project, tags=tags)
        allowed = _ALLOWED_TRANSITIONS.get(record.status, set())
        if to_status not in allowed:
            raise TransitionError(record.status.value, to_status.value)
        closed_at = None
        if is_terminal_status(to_status):
            closed_at = format_utc_datetime(utc_now())
        updates = {"status": to_status.value, "closed_at": closed_at}
        if to_status is LoopStatus.COMPLETED and note and note.strip():
            updates["completion_note"] = note.strip()
        updated = repo.update_loop_fields(
            loop_id=loop_id,
            fields=updates,
            conn=conn,
        )
        event_type = (
            LoopEventType.CLOSE.value
            if is_terminal_status(to_status)
            else LoopEventType.STATUS_CHANGE.value
        )
        payload: dict[str, Any] = {"from": record.status.value, "to": to_status.value}
        if note:
            payload["note"] = note
        if closed_at:
            payload["closed_at_utc"] = closed_at
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
        project = repo.read_project_name(project_id=updated.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
        return _record_to_dict(updated, project=project, tags=tags)

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    if transactional:
        try:
            with conn:
                for idx, item in enumerate(items):
                    loop_id = item.get("loop_id")
                    status_str = item.get("status", "completed")
                    note = item.get("note")

                    if not isinstance(loop_id, int):
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "loop_id must be an integer",
                                },
                            }
                        )
                        failed += 1
                        continue

                    try:
                        loop_status = LoopStatus(status_str)
                        if not is_terminal_status(loop_status):
                            raise ValidationError("status", "must be completed or dropped")
                        record = _close_single(loop_id, loop_status, note)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": True,
                                "loop": record,
                            }
                        )
                        succeeded += 1
                    except Exception as exc:
                        error_code = _classify_error(exc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {"code": error_code, "message": str(exc)},
                            }
                        )
                        failed += 1

                if failed > 0:
                    raise _Rollback()
        except _Rollback:
            return {
                "ok": False,
                "transactional": True,
                "results": _rollback_transaction_results(results),
                "succeeded": 0,
                "failed": len(items),
            }
    else:
        for idx, item in enumerate(items):
            loop_id = item.get("loop_id")
            status_str = item.get("status", "completed")
            note = item.get("note")

            if not isinstance(loop_id, int):
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "loop_id must be an integer",
                        },
                    }
                )
                failed += 1
                continue

            try:
                with conn:
                    loop_status = LoopStatus(status_str)
                    if not is_terminal_status(loop_status):
                        raise ValidationError("status", "must be completed or dropped")
                    record = _close_single(loop_id, loop_status, note)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": True,
                        "loop": record,
                    }
                )
                succeeded += 1
            except Exception as exc:
                error_code = _classify_error(exc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                failed += 1

    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": succeeded,
        "failed": failed,
    }


@typingx.validate_io()
def bulk_snooze_loops(
    *,
    items: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk snooze multiple loops.

    Args:
        items: List of items with loop_id and snooze_until_utc
        transactional: If True, rollback all on any failure
        conn: Database connection

    Returns:
        Dict with ok, transactional, results (per-item), succeeded, failed
    """

    class _Rollback(Exception):
        pass

    def _snooze_single(loop_id: int, snooze_until_utc: str) -> dict[str, Any]:
        record = repo.read_loop(loop_id=loop_id, conn=conn)
        if record is None:
            raise LoopNotFoundError(loop_id)
        locked_fields = set(record.user_locks)
        if "snooze_until_utc" in _LOCKABLE_FIELDS:
            locked_fields.add("snooze_until_utc")
        updated_fields = {
            "snooze_until_utc": snooze_until_utc,
            "user_locks_json": json.dumps(sorted(locked_fields)),
        }
        updated = repo.update_loop_fields(loop_id=loop_id, fields=updated_fields, conn=conn)
        event_payload = {"fields": {"snooze_until_utc": snooze_until_utc}}
        event_id = repo.insert_loop_event(
            loop_id=updated.id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        project = repo.read_project_name(project_id=updated.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
        return _record_to_dict(updated, project=project, tags=tags)

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    if transactional:
        try:
            with conn:
                for idx, item in enumerate(items):
                    loop_id = item.get("loop_id")
                    snooze_until_utc = item.get("snooze_until_utc")

                    if not isinstance(loop_id, int):
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "loop_id must be an integer",
                                },
                            }
                        )
                        failed += 1
                        continue

                    if not snooze_until_utc:
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "snooze_until_utc is required",
                                },
                            }
                        )
                        failed += 1
                        continue

                    try:
                        record = _snooze_single(loop_id, snooze_until_utc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": True,
                                "loop": record,
                            }
                        )
                        succeeded += 1
                    except Exception as exc:
                        error_code = _classify_error(exc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {"code": error_code, "message": str(exc)},
                            }
                        )
                        failed += 1

                if failed > 0:
                    raise _Rollback()
        except _Rollback:
            return {
                "ok": False,
                "transactional": True,
                "results": _rollback_transaction_results(results),
                "succeeded": 0,
                "failed": len(items),
            }
    else:
        for idx, item in enumerate(items):
            loop_id = item.get("loop_id")
            snooze_until_utc = item.get("snooze_until_utc")

            if not isinstance(loop_id, int):
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "loop_id must be an integer",
                        },
                    }
                )
                failed += 1
                continue

            if not snooze_until_utc:
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "snooze_until_utc is required",
                        },
                    }
                )
                failed += 1
                continue

            try:
                with conn:
                    record = _snooze_single(loop_id, snooze_until_utc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": True,
                        "loop": record,
                    }
                )
                succeeded += 1
            except Exception as exc:
                error_code = _classify_error(exc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                failed += 1

    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": succeeded,
        "failed": failed,
    }


def _classify_error(exc: Exception) -> str:
    """Classify exception into a stable error code."""
    if isinstance(exc, LoopNotFoundError):
        return "not_found"
    if isinstance(exc, TransitionError):
        return "transition_error"
    if isinstance(exc, ValidationError):
        return "validation_error"
    return "internal_error"


def _rollback_transaction_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark transactional results as rolled back while preserving root-cause failures."""
    rolled_back: list[dict[str, Any]] = []
    for result in results:
        if result.get("ok", False):
            rolled_back.append(
                {
                    "index": result["index"],
                    "loop_id": result["loop_id"],
                    "ok": False,
                    "error": {
                        "code": "transaction_rollback",
                        "message": "rolled back due to other failures",
                        "rolled_back": True,
                    },
                }
            )
            continue

        error = result.get("error")
        if isinstance(error, Mapping):
            merged_error = dict(error)
        else:
            merged_error = {
                "code": "internal_error",
                "message": "operation failed and transaction was rolled back",
            }
        merged_error["rolled_back"] = True
        rolled_back.append(
            {
                "index": result["index"],
                "loop_id": result["loop_id"],
                "ok": False,
                "error": merged_error,
            }
        )
    return rolled_back
