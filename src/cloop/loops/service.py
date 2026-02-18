"""Loop service layer for business logic and orchestration.

Purpose:
    Provide high-level business operations for loop lifecycle management,
    including capture, enrichment, status transitions, claims, dependencies,
    and time tracking.

Responsibilities:
    - Enforce business rules and validation constraints
    - Orchestrate multi-step operations (capture + enrich, transition + event)
    - Coordinate between repository layer and external services (LLM, webhooks)
    - Emit domain events for audit trail and webhook delivery

Non-scope:
    - Direct database access (see repo.py)
    - HTTP request/response handling (see routes/loops.py)
    - Query DSL parsing (see query.py)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Mapping

from .. import typingx
from ..settings import Settings, get_settings
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import (
    ClaimExpiredError,
    ClaimNotFoundError,
    DependencyCycleError,
    DependencyNotMetError,
    LoopClaimedError,
    LoopNotFoundError,
    MergeConflictError,
    SuggestionNotFoundError,
    TransitionError,
    UndoNotPossibleError,
    ValidationError,
)
from .metrics import record_capture, record_transition, record_update
from .models import (
    EnrichmentState,
    LoopComment,
    LoopEventType,
    LoopRecord,
    LoopStatus,
    format_utc_datetime,
    is_terminal_status,
    parse_client_datetime,
    parse_utc_datetime,
    utc_now,
)
from .pagination import (
    build_next_cursor,
    prepare_cursor_state,
)
from .prioritization import PriorityWeights, bucketize, compute_priority_score
from .utils import normalize_tag, normalize_tags

if TYPE_CHECKING:
    from .models import TimerStatus, TimeSession

logger = logging.getLogger(__name__)

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


def _handle_recurrence_on_completion(
    *,
    record: LoopRecord,
    conn: sqlite3.Connection,
) -> int | None:
    """Handle recurring loop completion by creating next occurrence.

    When a recurring loop is completed, this creates a new loop for the
    next scheduled occurrence and disables recurrence on the completed loop.

    Args:
        record: The loop being completed
        conn: Database connection

    Returns:
        The next loop ID if created, None otherwise
    """
    if not record.is_recurring():
        return None
    if record.recurrence_rrule is None or record.recurrence_tz is None:
        return None

    from .recurrence import RecurrenceError, compute_next_due

    now = utc_now()
    try:
        next_due = compute_next_due(
            record.recurrence_rrule,
            record.recurrence_tz,
            now,
        )
    except RecurrenceError:
        # If recurrence computation fails (e.g., corrupted RRULE),
        # don't prevent completion - just don't create next occurrence
        return None
    if next_due is None:
        return None

    # Create new loop for next occurrence
    next_captured_at = format_utc_datetime(now)
    next_loop = repo.create_loop(
        raw_text=record.raw_text,
        captured_at_utc=next_captured_at,
        captured_tz_offset_min=record.captured_tz_offset_min,
        status=LoopStatus.INBOX,
        conn=conn,
    )
    # Update new loop with recurrence info and next due date
    next_due_str = format_utc_datetime(next_due)
    repo.update_loop_fields(
        loop_id=next_loop.id,
        fields={
            "title": record.title,
            "summary": record.summary,
            "definition_of_done": record.definition_of_done,
            "time_minutes": record.time_minutes,
            "activation_energy": record.activation_energy,
            "project_id": record.project_id,
            "recurrence_rrule": record.recurrence_rrule,
            "recurrence_tz": record.recurrence_tz,
            "next_due_at_utc": next_due_str,
            "recurrence_enabled": 1,
        },
        conn=conn,
    )
    # Copy tags to new loop
    existing_tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
    if existing_tags:
        repo.replace_loop_tags(loop_id=next_loop.id, tag_names=existing_tags, conn=conn)

    return next_loop.id


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
        "recurrence_rrule": record.recurrence_rrule,
        "recurrence_tz": record.recurrence_tz,
        "next_due_at_utc": (
            format_utc_datetime(record.next_due_at_utc) if record.next_due_at_utc else None
        ),
        "recurrence_enabled": record.recurrence_enabled,
        "parent_loop_id": record.parent_loop_id,
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
    recurrence_rrule: str | None = None,
    recurrence_tz: str | None = None,
    capture_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    captured_at_utc = parse_client_datetime(
        captured_at_iso,
        tz_offset_min=client_tz_offset_min,
    )
    captured_at_utc_str = format_utc_datetime(captured_at_utc)

    # Handle recurrence setup
    recurrence_enabled = False
    next_due_at_utc: str | None = None

    if recurrence_rrule:
        from .recurrence import (
            compute_next_due,
            is_valid_timezone,
            offset_minutes_to_timezone,
            validate_rrule,
        )

        # Validate and normalize RRULE
        validated_rrule = validate_rrule(recurrence_rrule)

        # Determine timezone - use provided or derive from offset
        if recurrence_tz:
            if not is_valid_timezone(recurrence_tz):
                raise ValidationError("recurrence_tz", f"Invalid timezone: {recurrence_tz}")
        else:
            recurrence_tz = offset_minutes_to_timezone(client_tz_offset_min)

        # Compute first due date
        next_due = compute_next_due(validated_rrule, recurrence_tz, captured_at_utc)
        if next_due:
            next_due_at_utc = format_utc_datetime(next_due)
            recurrence_enabled = True
            recurrence_rrule = validated_rrule

    with conn:
        # Create the loop with recurrence fields (single operation)
        record = repo.create_loop(
            raw_text=raw_text,
            captured_at_utc=captured_at_utc_str,
            captured_tz_offset_min=client_tz_offset_min,
            status=status,
            conn=conn,
            recurrence_rrule=recurrence_rrule,
            recurrence_tz=recurrence_tz,
            next_due_at_utc=next_due_at_utc,
            recurrence_enabled=recurrence_enabled,
        )

        record_capture()

        # Store loop_id for later use
        loop_id = record.id

        # Apply capture fields if provided (same pattern as template_defaults)
        if capture_fields:
            # Filter out any None values
            fields_to_apply = {k: v for k, v in capture_fields.items() if v is not None}
            if fields_to_apply:
                record = update_loop(
                    loop_id=loop_id,
                    fields=fields_to_apply,
                    conn=conn,
                )

        event_payload = {
            "raw_text": raw_text,
            "status": status.value,
            "captured_at_utc": captured_at_utc_str,
            "captured_tz_offset_min": client_tz_offset_min,
        }
        if recurrence_rrule:
            event_payload["recurrence_rrule"] = recurrence_rrule
            event_payload["recurrence_tz"] = recurrence_tz

        event_id = repo.insert_loop_event(
            loop_id=loop_id,
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

    # If update_loop was called (capture_fields applied), record is already a dict
    if isinstance(record, dict):
        return record

    # Otherwise, convert LoopRecord to dict with project and tags
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
                normalized_tags = normalize_tags(tags)
                repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
            imported += 1
    return imported


@typingx.validate_io()
def update_loop(
    *,
    loop_id: int,
    fields: Mapping[str, Any],
    conn: sqlite3.Connection,
    claim_token: str | None = None,
) -> dict[str, Any]:
    if "status" in fields:
        raise ValidationError("status", "use /loops/{id}/status or /loops/{id}/close endpoints")

    # Validate claim if loop is claimed
    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)

    # Capture before_state for reversible fields (for undo support)
    reversible_fields = {
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
    }
    before_state: dict[str, Any] = {}
    for field in reversible_fields:
        if field in fields:
            old_value = getattr(record, field, None)
            # Format datetime fields
            if field in ("due_at_utc", "snooze_until_utc") and old_value is not None:
                before_state[field] = format_utc_datetime(old_value)
            else:
                # Capture the value even if None (for restoring to None)
                before_state[field] = old_value

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
        record_update()
        if tags is not None:
            normalized_tags = normalize_tags(tags)
            repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
        event_payload: dict[str, Any] = {"fields": dict(fields)}
        if before_state:
            event_payload["before_state"] = before_state
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
    claim_token: str | None = None,
) -> dict[str, Any]:
    # Validate claim if loop is claimed
    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

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

    # Check for open dependencies when transitioning to actionable
    if to_status == LoopStatus.ACTIONABLE:
        open_deps = repo.list_open_dependencies(loop_id=loop_id, conn=conn)
        if open_deps:
            raise DependencyNotMetError(loop_id, open_deps)

    # Capture before_state for undo support
    before_state: dict[str, Any] = {"status": record.status.value}
    if record.closed_at_utc:
        before_state["closed_at"] = format_utc_datetime(record.closed_at_utc)

    closed_at = None
    if is_terminal_status(to_status):
        closed_at = format_utc_datetime(utc_now())

    # Handle recurring loop completion - create next occurrence
    next_loop_id: int | None = None
    if to_status == LoopStatus.COMPLETED:
        next_loop_id = _handle_recurrence_on_completion(record=record, conn=conn)

    with conn:
        updates = {"status": to_status.value, "closed_at": closed_at}
        if to_status is LoopStatus.COMPLETED and note and note.strip():
            updates["completion_note"] = note.strip()
        # Disable recurrence on completed loop so it doesn't generate more
        if to_status == LoopStatus.COMPLETED and record.is_recurring():
            updates["recurrence_enabled"] = 0
        updated = repo.update_loop_fields(
            loop_id=loop_id,
            fields=updates,
            conn=conn,
        )
        record_transition(record.status.value, to_status.value)
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
        if next_loop_id is not None:
            payload["next_occurrence_loop_id"] = next_loop_id
        # Add before_state for undo support
        payload["before_state"] = before_state
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


# ============================================================================
# Dependency Service Functions
# ============================================================================


@typingx.validate_io()
def add_loop_dependency(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Add a dependency relationship with cycle detection.

    Args:
        loop_id: The loop that is blocked
        depends_on_loop_id: The loop that blocks it
        conn: Database connection

    Returns:
        Updated loop dict with dependencies list

    Raises:
        LoopNotFoundError: If either loop doesn't exist
        DependencyCycleError: If adding would create a cycle
    """
    # Validate both loops exist
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)
    dep_loop = repo.read_loop(loop_id=depends_on_loop_id, conn=conn)
    if dep_loop is None:
        raise LoopNotFoundError(depends_on_loop_id)

    # Check for cycle
    if repo.detect_dependency_cycle(
        loop_id=loop_id,
        depends_on_loop_id=depends_on_loop_id,
        conn=conn,
    ):
        raise DependencyCycleError(loop_id, depends_on_loop_id)

    # Add the dependency
    try:
        repo.add_dependency(
            loop_id=loop_id,
            depends_on_loop_id=depends_on_loop_id,
            conn=conn,
        )
    except sqlite3.IntegrityError:
        # Already exists, that's fine
        pass

    # If loop is actionable and dependency is open, auto-transition to blocked
    if loop.status == LoopStatus.ACTIONABLE:
        if dep_loop.status not in (LoopStatus.COMPLETED, LoopStatus.DROPPED):
            repo.update_loop_fields(
                loop_id=loop_id,
                fields={"status": LoopStatus.BLOCKED.value},
                conn=conn,
            )

    return get_loop_with_dependencies(loop_id=loop_id, conn=conn)


@typingx.validate_io()
def remove_loop_dependency(
    *,
    loop_id: int,
    depends_on_loop_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Remove a dependency relationship.

    Args:
        loop_id: The blocked loop
        depends_on_loop_id: The loop it depended on
        conn: Database connection

    Returns:
        Updated loop dict with dependencies list
    """
    repo.remove_dependency(
        loop_id=loop_id,
        depends_on_loop_id=depends_on_loop_id,
        conn=conn,
    )
    return get_loop_with_dependencies(loop_id=loop_id, conn=conn)


@typingx.validate_io()
def get_loop_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get all dependencies (blockers) for a loop with their status.

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of dependency loop dicts with id, title, status
    """
    dep_ids = repo.list_dependencies(loop_id=loop_id, conn=conn)
    if not dep_ids:
        return []

    result = []
    for dep_id in dep_ids:
        dep_loop = repo.read_loop(loop_id=dep_id, conn=conn)
        if dep_loop:
            result.append(
                {
                    "id": dep_loop.id,
                    "title": dep_loop.title or dep_loop.raw_text[:50],
                    "status": dep_loop.status.value,
                }
            )
    return result


@typingx.validate_io()
def get_loop_blocking(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get all loops that depend on this loop (its dependents).

    Args:
        loop_id: The loop to check
        conn: Database connection

    Returns:
        List of dependent loop dicts with id, title, status
    """
    dependent_ids = repo.list_dependents(loop_id=loop_id, conn=conn)
    if not dependent_ids:
        return []

    result = []
    for dep_id in dependent_ids:
        dep_loop = repo.read_loop(loop_id=dep_id, conn=conn)
        if dep_loop:
            result.append(
                {
                    "id": dep_loop.id,
                    "title": dep_loop.title or dep_loop.raw_text[:50],
                    "status": dep_loop.status.value,
                }
            )
    return result


def get_loop_with_dependencies(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Get a loop with its dependencies and blocking info.

    Args:
        loop_id: The loop to get
        conn: Database connection

    Returns:
        Loop dict with dependencies and blocking lists
    """
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    project = repo.read_project_name(project_id=loop.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=loop.id, conn=conn)
    result = _record_to_dict(loop, project=project, tags=tags)

    result["dependencies"] = get_loop_dependencies(loop_id=loop_id, conn=conn)
    result["blocking"] = get_loop_blocking(loop_id=loop_id, conn=conn)
    result["has_open_dependencies"] = repo.has_open_dependencies(loop_id=loop_id, conn=conn)
    return result


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
    now = utc_now()
    candidates = repo.list_next_loop_candidates(
        limit=settings.next_candidates_limit,
        now_utc=now,
        conn=conn,
    )
    actionable_records: list[LoopRecord] = []
    for record in candidates:
        # Keep dependency check in Python (requires join)
        if repo.has_open_dependencies(loop_id=record.id, conn=conn):
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
    items = _enrich_records_batch(records[:limit], conn=conn)

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
    items = _enrich_records_batch(records[:limit], conn=conn)

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
    view = repo.get_loop_view(view_id=view_id, conn=conn)
    if view is None:
        raise ValidationError("view_id", f"view {view_id} not found")

    query = view["query"]
    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "loop.view.apply", "view_id": view_id, "query": query},
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
    items = _enrich_records_batch(records[:limit], conn=conn)

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

    def _update_single(
        loop_id: int, fields: Mapping[str, Any], claim_token: str | None = None
    ) -> dict[str, Any]:
        if "status" in fields:
            raise ValidationError("status", "use /loops/{id}/status or /loops/{id}/close endpoints")
        # Validate claim if loop is claimed
        _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)
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
        record_update()
        if tags is not None:
            normalized_tags = normalize_tags(tags)
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
                        claim_token = item.get("claim_token")
                        record = _update_single(loop_id, fields, claim_token)
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
                    claim_token = item.get("claim_token")
                    record = _update_single(loop_id, fields, claim_token)
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

    def _close_single(
        loop_id: int, to_status: LoopStatus, note: str | None, claim_token: str | None = None
    ) -> dict[str, Any]:
        # Validate claim if loop is claimed
        _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)
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

        # Check for open dependencies when transitioning to actionable
        if to_status == LoopStatus.ACTIONABLE:
            open_deps = repo.list_open_dependencies(loop_id=loop_id, conn=conn)
            if open_deps:
                raise DependencyNotMetError(loop_id, open_deps)

        closed_at = None
        if is_terminal_status(to_status):
            closed_at = format_utc_datetime(utc_now())

        # Handle recurring loop completion - create next occurrence
        next_loop_id: int | None = None
        if to_status == LoopStatus.COMPLETED:
            next_loop_id = _handle_recurrence_on_completion(record=record, conn=conn)

        updates = {"status": to_status.value, "closed_at": closed_at}
        if to_status is LoopStatus.COMPLETED and note and note.strip():
            updates["completion_note"] = note.strip()
        # Disable recurrence on completed loop so it doesn't generate more
        if to_status == LoopStatus.COMPLETED and record.is_recurring():
            updates["recurrence_enabled"] = 0
        updated = repo.update_loop_fields(
            loop_id=loop_id,
            fields=updates,
            conn=conn,
        )
        record_transition(record.status.value, to_status.value)
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
        if next_loop_id is not None:
            payload["next_occurrence_loop_id"] = next_loop_id
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
                        claim_token = item.get("claim_token")
                        record = _close_single(loop_id, loop_status, note, claim_token)
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
                    claim_token = item.get("claim_token")
                    record = _close_single(loop_id, loop_status, note, claim_token)
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


def create_template_from_loop(
    *,
    loop_id: int,
    template_name: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a template from an existing loop.

    Args:
        loop_id: ID of loop to use as template source
        template_name: Name for the new template
        conn: Database connection

    Returns:
        Created template record

    Raises:
        LoopNotFoundError: If loop doesn't exist
        ValidationError: If template name is invalid or already exists
    """
    from .repo import create_loop_template, list_loop_tags, read_loop

    loop = read_loop(loop_id=loop_id, conn=conn)
    if not loop:
        raise LoopNotFoundError(loop_id)

    tags = list_loop_tags(loop_id=loop_id, conn=conn)

    # Build defaults from loop fields
    defaults: dict[str, Any] = {}
    if loop.title:
        defaults["title"] = loop.title
    if tags:
        defaults["tags"] = tags
    if loop.time_minutes is not None:
        defaults["time_minutes"] = loop.time_minutes
    if loop.activation_energy is not None:
        defaults["activation_energy"] = loop.activation_energy
    if loop.urgency is not None:
        defaults["urgency"] = loop.urgency
    if loop.importance is not None:
        defaults["importance"] = loop.importance
    if loop.status == LoopStatus.ACTIONABLE:
        defaults["actionable"] = True
    elif loop.status == LoopStatus.SCHEDULED:
        defaults["scheduled"] = True
    elif loop.status == LoopStatus.BLOCKED:
        defaults["blocked"] = True

    return create_loop_template(
        name=template_name,
        description=f"Created from loop #{loop_id}",
        raw_text_pattern=loop.raw_text,
        defaults_json=defaults,
        is_system=False,
        conn=conn,
    )


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

    def _snooze_single(
        loop_id: int, snooze_until_utc: str, claim_token: str | None = None
    ) -> dict[str, Any]:
        # Validate claim if loop is claimed
        _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)
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
                        claim_token = item.get("claim_token")
                        record = _snooze_single(loop_id, snooze_until_utc, claim_token)
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
                    claim_token = item.get("claim_token")
                    record = _snooze_single(loop_id, snooze_until_utc, claim_token)
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
    if isinstance(exc, LoopClaimedError):
        return "loop_claimed"
    if isinstance(exc, ClaimNotFoundError):
        return "claim_not_found"
    if isinstance(exc, ClaimExpiredError):
        return "claim_expired"
    if isinstance(exc, DependencyCycleError):
        return "dependency_cycle"
    if isinstance(exc, DependencyNotMetError):
        return "dependency_not_met"
    if isinstance(exc, MergeConflictError):
        return "merge_conflict"
    if isinstance(exc, SuggestionNotFoundError):
        return "suggestion_not_found"
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


# ============================================================================
# Loop Claim Service Functions
# ============================================================================


def _validate_claim_for_update(
    *,
    loop_id: int,
    claim_token: str | None,
    conn: sqlite3.Connection,
) -> None:
    """Validate that the caller has a valid claim on the loop.

    Call this at the start of mutation operations (update_loop, transition_status, etc.)

    Args:
        loop_id: Loop being modified
        claim_token: Token provided by caller (or None)
        conn: Database connection

    Raises:
        LoopClaimedError: If loop is claimed by someone else
        ClaimNotFoundError: If loop is claimed but no/invalid token provided
    """
    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    if claim is None:
        return  # No claim, proceed

    # Check if claim has expired (don't purge, just check)
    if claim.lease_until_utc <= utc_now():
        return  # Claim expired, proceed

    if claim_token is None:
        raise LoopClaimedError(
            loop_id=loop_id,
            owner=claim.owner,
            lease_until=format_utc_datetime(claim.lease_until_utc),
        )

    if claim.claim_token != claim_token:
        raise ClaimNotFoundError(loop_id)


@typingx.validate_io()
def claim_loop(
    *,
    loop_id: int,
    owner: str,
    ttl_seconds: int | None = None,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Claim a loop for exclusive access.

    Args:
        loop_id: Loop to claim
        owner: Identifier for the claiming agent/client
        ttl_seconds: Lease duration (defaults to claim_default_ttl_seconds)
        conn: Database connection
        settings: Optional settings override

    Returns:
        Dict with claim details including claim_token for subsequent operations

    Raises:
        LoopNotFoundError: If loop doesn't exist
        LoopClaimedError: If loop is already claimed
    """
    settings = settings or get_settings()
    ttl = ttl_seconds or settings.claim_default_ttl_seconds
    ttl = min(ttl, settings.claim_max_ttl_seconds)

    # Verify loop exists
    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)

    # Purge expired claims first
    repo.purge_expired_claims(conn=conn)

    now = utc_now()
    lease_until = now + timedelta(seconds=ttl)

    # Retry loop handles race condition where claim expires between purge and insert
    # Max 3 attempts to prevent theoretical infinite retry on pathological timing
    for attempt in range(3):
        try:
            claim = repo.claim_loop(
                loop_id=loop_id,
                owner=owner,
                lease_until=lease_until,
                conn=conn,
                token_bytes=settings.claim_token_bytes,
            )
            break
        except sqlite3.IntegrityError:
            # Already claimed - get existing claim info
            existing = repo.read_claim(loop_id=loop_id, conn=conn)
            if existing and existing.lease_until_utc > now:
                raise LoopClaimedError(
                    loop_id=loop_id,
                    owner=existing.owner,
                    lease_until=format_utc_datetime(existing.lease_until_utc),
                ) from None
            # Race condition: claim expired between purge and insert
            if attempt < 2:  # Only purge and retry if not last attempt
                repo.purge_expired_claims(conn=conn)
            else:
                # Final attempt also failed - should be extremely rare
                raise RuntimeError(
                    f"Failed to acquire claim on loop {loop_id} after 3 attempts"
                ) from None

    # Record claim event
    event_payload = {
        "owner": owner,
        "lease_until": format_utc_datetime(lease_until),
    }
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.CLAIM.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.CLAIM.value,
        payload=event_payload,
        conn=conn,
    )

    logger.info(
        "Loop claimed successfully: loop_id=%s owner=%s ttl=%s lease_until=%s",
        loop_id,
        owner,
        ttl,
        format_utc_datetime(lease_until),
    )

    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "claim_token": claim.claim_token,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


@typingx.validate_io()
def renew_claim(
    *,
    loop_id: int,
    claim_token: str,
    ttl_seconds: int | None = None,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Renew an existing claim.

    Args:
        loop_id: Loop with existing claim
        claim_token: Token from original claim
        ttl_seconds: New lease duration from now
        conn: Database connection
        settings: Optional settings override

    Returns:
        Dict with updated claim details

    Raises:
        ClaimNotFoundError: If token invalid or claim expired
    """
    settings = settings or get_settings()
    ttl = ttl_seconds or settings.claim_default_ttl_seconds
    ttl = min(ttl, settings.claim_max_ttl_seconds)

    now = utc_now()
    new_lease_until = now + timedelta(seconds=ttl)

    claim = repo.renew_claim(
        loop_id=loop_id,
        claim_token=claim_token,
        new_lease_until=new_lease_until,
        conn=conn,
    )
    if claim is None:
        raise ClaimNotFoundError(loop_id)

    logger.info(
        "Claim renewed successfully: loop_id=%s new_lease_until=%s",
        loop_id,
        format_utc_datetime(new_lease_until),
    )

    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "claim_token": claim.claim_token,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


@typingx.validate_io()
def release_claim(
    *,
    loop_id: int,
    claim_token: str,
    conn: sqlite3.Connection,
) -> bool:
    """Release a claim on a loop.

    Args:
        loop_id: Loop to release
        claim_token: Token from original claim
        conn: Database connection

    Returns:
        True if released

    Raises:
        ClaimNotFoundError: If token doesn't match any active claim
    """
    released = repo.release_claim(loop_id=loop_id, claim_token=claim_token, conn=conn)
    if not released:
        raise ClaimNotFoundError(loop_id)

    event_payload = {"release_type": "explicit"}
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.CLAIM_RELEASED.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.CLAIM_RELEASED.value,
        payload=event_payload,
        conn=conn,
    )

    logger.info("Claim released successfully: loop_id=%s", loop_id)

    return True


@typingx.validate_io()
def force_release_claim(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Force-release any claim on a loop (admin override).

    Args:
        loop_id: Loop to release
        conn: Database connection

    Returns:
        True if a claim was released, False if no claim existed
    """
    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    released = repo.release_claim_by_loop_id(loop_id=loop_id, conn=conn)
    if released and claim:
        logger.info(
            "Claim force-released: loop_id=%s original_owner=%s",
            loop_id,
            claim.owner,
        )
        event_payload = {
            "release_type": "forced",
            "original_owner": claim.owner,
        }
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=LoopEventType.CLAIM_RELEASED.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.CLAIM_RELEASED.value,
            payload=event_payload,
            conn=conn,
        )
    return released


@typingx.validate_io()
def get_claim_status(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get the current claim status for a loop.

    Args:
        loop_id: Loop to check
        conn: Database connection

    Returns:
        Dict with claim info (without token) or None if not claimed
    """
    # Purge expired claims first
    repo.purge_expired_claims(conn=conn)

    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    if claim is None:
        return None
    # Don't expose the token in GET response
    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


@typingx.validate_io()
def list_active_claims(
    *,
    owner: str | None = None,
    limit: int = 100,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List all active (non-expired) claims, optionally filtered by owner.

    Args:
        owner: Optional owner filter
        limit: Max results
        conn: Database connection

    Returns:
        List of claim dicts (without tokens) ordered by lease_until ascending
    """
    # Purge expired claims first
    repo.purge_expired_claims(conn=conn)

    claims = repo.list_active_claims(owner=owner, limit=limit, conn=conn)
    # Don't expose tokens in list response
    return [
        {
            "loop_id": claim.loop_id,
            "owner": claim.owner,
            "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
            "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
        }
        for claim in claims
    ]


# ============================================================================
# Time Tracking Service Functions
# ============================================================================


class TimerError(Exception):
    """Base error for timer operations."""

    pass


class ActiveTimerExistsError(TimerError):
    """Raised when trying to start a timer but one is already active."""

    def __init__(self, loop_id: int, session: "TimeSession"):
        self.loop_id = loop_id
        self.session = session
        super().__init__(
            f"Loop {loop_id} already has an active timer started at {session.started_at_utc}"
        )


class NoActiveTimerError(TimerError):
    """Raised when trying to stop a timer but none is active."""

    def __init__(self, loop_id: int):
        self.loop_id = loop_id
        super().__init__(f"Loop {loop_id} has no active timer to stop")


@typingx.validate_io()
def start_timer(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> "TimeSession":
    """Start a timer for a loop.

    Enforces the single-active-timer-per-loop rule.

    Args:
        loop_id: Loop to start timer for
        conn: Database connection

    Returns:
        The newly created TimeSession

    Raises:
        LoopNotFoundError: If loop doesn't exist
        ActiveTimerExistsError: If a timer is already running for this loop
    """
    from .models import utc_now

    # Verify loop exists
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    # Check for existing active session
    active = repo.get_active_time_session(loop_id=loop_id, conn=conn)
    if active is not None:
        raise ActiveTimerExistsError(loop_id, active)

    # Create new session
    session = repo.create_time_session(
        loop_id=loop_id,
        started_at=utc_now(),
        conn=conn,
    )

    # Record event
    event_payload = {"session_id": session.id}
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.TIMER_STARTED.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.TIMER_STARTED.value,
        payload=event_payload,
        conn=conn,
    )

    return session


@typingx.validate_io()
def stop_timer(
    *,
    loop_id: int,
    notes: str | None = None,
    conn: sqlite3.Connection,
) -> "TimeSession":
    """Stop the active timer for a loop.

    Args:
        loop_id: Loop to stop timer for
        notes: Optional notes for this session
        conn: Database connection

    Returns:
        The completed TimeSession with calculated duration

    Raises:
        LoopNotFoundError: If loop doesn't exist
        NoActiveTimerError: If no timer is running for this loop
    """
    from .models import utc_now

    # Verify loop exists first
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    # Get active session
    active = repo.get_active_time_session(loop_id=loop_id, conn=conn)
    if active is None:
        raise NoActiveTimerError(loop_id)

    # Calculate duration
    now = utc_now()
    duration_seconds = int((now - active.started_at_utc).total_seconds())

    # Stop the session
    session = repo.stop_time_session(
        session_id=active.id,
        ended_at=now,
        duration_seconds=duration_seconds,
        notes=notes,
        conn=conn,
    )

    # Record event
    event_payload = {
        "session_id": session.id,
        "duration_seconds": duration_seconds,
    }
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.TIMER_STOPPED.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.TIMER_STOPPED.value,
        payload=event_payload,
        conn=conn,
    )

    return session


@typingx.validate_io()
def get_timer_status(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> "TimerStatus":
    """Get the current timer status for a loop.

    Args:
        loop_id: Loop to get status for
        conn: Database connection

    Returns:
        TimerStatus with active session (if any) and totals

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    from .models import TimerStatus

    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    active = repo.get_active_time_session(loop_id=loop_id, conn=conn)
    total_seconds = repo.get_total_tracked_time(loop_id=loop_id, conn=conn)

    return TimerStatus(
        loop_id=loop_id,
        has_active_session=active is not None,
        active_session=active,
        total_tracked_seconds=total_seconds,
        estimated_minutes=loop.time_minutes,
    )


@typingx.validate_io()
def list_time_sessions(
    *,
    loop_id: int,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection,
) -> list["TimeSession"]:
    """List time sessions for a loop.

    Args:
        loop_id: Loop to list sessions for
        limit: Maximum number of sessions
        offset: Pagination offset
        conn: Database connection

    Returns:
        List of TimeSession objects

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    return repo.list_time_sessions(
        loop_id=loop_id,
        limit=limit,
        offset=offset,
        conn=conn,
    )


# ============================================================================
# Event History and Undo Service Functions
# ============================================================================

_REVERSIBLE_EVENT_TYPES = frozenset({"update", "status_change", "close"})


@typingx.validate_io()
def get_loop_events(
    *,
    loop_id: int,
    limit: int = 50,
    before_id: int | None = None,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get event history for a loop.

    Args:
        loop_id: Loop to query
        limit: Max results (default 50)
        before_id: Pagination cursor - only events with id < before_id
        conn: Database connection

    Returns:
        List of event dicts with human-readable timestamps and parsed payloads

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    # Verify loop exists
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    events = repo.list_loop_events_paginated(
        loop_id=loop_id,
        limit=limit,
        before_id=before_id,
        conn=conn,
    )

    # Parse payloads and format for API response
    result = []
    for event in events:
        payload = json.loads(event["payload_json"]) if event["payload_json"] else {}
        result.append(
            {
                "id": event["id"],
                "loop_id": event["loop_id"],
                "event_type": event["event_type"],
                "payload": payload,
                "created_at_utc": event["created_at"],
                "is_reversible": event["event_type"] in _REVERSIBLE_EVENT_TYPES,
            }
        )

    return result


@typingx.validate_io()
def undo_last_event(
    *,
    loop_id: int,
    claim_token: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Undo the most recent reversible event for a loop.

    This performs a one-step rollback by:
    1. Finding the latest reversible event
    2. Extracting the before_state from its payload
    3. Applying the inverse mutation
    4. Recording an undo event for audit trail

    Args:
        loop_id: Loop to modify
        claim_token: Required if loop is claimed
        conn: Database connection

    Returns:
        Dict with updated loop and undo details:
        - loop: The updated loop dict
        - undone_event_id: ID of the event that was undone
        - undone_event_type: Type of the undone event

    Raises:
        LoopNotFoundError: If loop doesn't exist
        UndoNotPossibleError: If no reversible event exists
        LoopClaimedError: If loop is claimed and token is invalid
        ClaimNotFoundError: If claim_token is invalid
    """
    # Verify loop exists and check claim
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)

    # Find latest reversible event
    event = repo.get_latest_reversible_event(loop_id=loop_id, conn=conn)
    if event is None:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="no_reversible_events",
            message="No reversible events found for this loop",
        )

    payload = json.loads(event["payload_json"]) if event["payload_json"] else {}
    before_state = payload.get("before_state", {})

    if not before_state:
        raise UndoNotPossibleError(
            loop_id=loop_id,
            reason="missing_before_state",
            message=f"Event {event['id']} lacks before_state needed for undo",
        )

    event_type = event["event_type"]

    with conn:
        if event_type == "status_change" or event_type == "close":
            # Restore previous status
            old_status = before_state.get("status")
            if old_status:
                restore_fields: dict[str, Any] = {"status": old_status}
                # Restore closed_at if it was set before
                old_closed_at = before_state.get("closed_at")
                restore_fields["closed_at"] = old_closed_at
                updated = repo.update_loop_fields(
                    loop_id=loop_id,
                    fields=restore_fields,
                    conn=conn,
                )
            else:
                raise UndoNotPossibleError(
                    loop_id=loop_id,
                    reason="invalid_before_state",
                    message="Status change event missing previous status",
                )

        elif event_type == "update":
            # Restore all changed fields
            restore_fields = {}
            for field, old_value in before_state.items():
                restore_fields[field] = old_value

            if not restore_fields:
                raise UndoNotPossibleError(
                    loop_id=loop_id,
                    reason="empty_before_state",
                    message="Update event has no fields to restore",
                )

            updated = repo.update_loop_fields(
                loop_id=loop_id,
                fields=restore_fields,
                conn=conn,
            )

        else:
            # Should not reach here if _REVERSIBLE_EVENT_TYPES is correct
            raise UndoNotPossibleError(
                loop_id=loop_id,
                reason="unsupported_event_type",
                message=f"Event type '{event_type}' is not supported for undo",
            )

        # Record undo event for audit trail
        undo_event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type="undo",
            payload={
                "undone_event_id": event["id"],
                "undone_event_type": event_type,
                "restored_fields": before_state,
            },
            conn=conn,
        )

        # Queue webhook delivery if configured
        queue_deliveries(
            event_id=undo_event_id,
            event_type="undo",
            payload={
                "undone_event_id": event["id"],
                "undone_event_type": event_type,
            },
            conn=conn,
        )

    project = repo.read_project_name(project_id=updated.project_id, conn=conn)
    tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)

    return {
        "loop": _record_to_dict(updated, project=project, tags=tags),
        "undone_event_id": event["id"],
        "undone_event_type": event_type,
    }


# ============================================================================
# Comment Service Functions
# ============================================================================


def _comment_to_dict(comment: "LoopComment") -> dict[str, Any]:
    """Convert LoopComment to dict for API response."""
    return {
        "id": comment.id,
        "loop_id": comment.loop_id,
        "parent_id": comment.parent_id,
        "author": comment.author,
        "body_md": comment.body_md,
        "created_at_utc": format_utc_datetime(comment.created_at_utc),
        "updated_at_utc": format_utc_datetime(comment.updated_at_utc),
        "deleted_at_utc": format_utc_datetime(comment.deleted_at_utc)
        if comment.deleted_at_utc
        else None,
        "is_deleted": comment.is_deleted,
        "is_reply": comment.is_reply,
    }


@typingx.validate_io()
def create_loop_comment(
    *,
    loop_id: int,
    author: str,
    body_md: str,
    parent_id: int | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a comment on a loop.

    Args:
        loop_id: Loop to comment on
        author: Comment author
        body_md: Markdown body
        parent_id: Optional parent comment ID for replies
        conn: Database connection

    Returns:
        Comment dict for API response

    Raises:
        LoopNotFoundError: If loop doesn't exist
        ValidationError: If parent comment doesn't belong to same loop
    """
    from .repo import create_comment, get_comment, read_loop

    # Verify loop exists
    loop = read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    # Verify parent belongs to same loop if specified
    if parent_id is not None:
        parent = get_comment(comment_id=parent_id, conn=conn)
        if parent is None or parent.loop_id != loop_id:
            raise ValidationError(
                "parent_id", "Parent comment not found or belongs to different loop"
            )

    comment = create_comment(
        loop_id=loop_id,
        author=author,
        body_md=body_md,
        parent_id=parent_id,
        conn=conn,
    )
    conn.commit()

    # Record event for audit trail
    event_payload = {
        "comment_id": comment.id,
        "author": author,
        "parent_id": parent_id,
    }
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.COMMENT_ADDED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.COMMENT_ADDED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()

    return _comment_to_dict(comment)


@typingx.validate_io()
def list_loop_comments(
    *,
    loop_id: int,
    include_deleted: bool = False,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """List comments for a loop in threaded order.

    Args:
        loop_id: Loop to list comments for
        include_deleted: Whether to include soft-deleted comments
        conn: Database connection

    Returns:
        Dict with loop_id, comments (nested tree), and total_count
    """
    from .repo import count_comments, list_comments, read_loop

    # Verify loop exists
    loop = read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    comments = list_comments(loop_id=loop_id, include_deleted=include_deleted, conn=conn)
    total = count_comments(loop_id=loop_id, include_deleted=include_deleted, conn=conn)

    # Build nested tree structure
    comment_map = {c.id: _comment_to_dict(c) for c in comments}
    root_comments: list[dict[str, Any]] = []

    for comment in comments:
        comment_dict = comment_map[comment.id]
        comment_dict["replies"] = []

        if comment.parent_id is None:
            root_comments.append(comment_dict)
        elif comment.parent_id in comment_map:
            comment_map[comment.parent_id]["replies"].append(comment_dict)

    return {
        "loop_id": loop_id,
        "comments": root_comments,
        "total_count": total,
    }


@typingx.validate_io()
def get_loop_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get a single comment by ID.

    Args:
        comment_id: Comment ID
        conn: Database connection

    Returns:
        Comment dict or None
    """
    from .repo import get_comment

    comment = get_comment(comment_id=comment_id, conn=conn)
    if comment is None:
        return None
    return _comment_to_dict(comment)


@typingx.validate_io()
def update_loop_comment(
    *,
    comment_id: int,
    body_md: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a comment's body.

    Args:
        comment_id: Comment to update
        body_md: New markdown body
        conn: Database connection

    Returns:
        Updated comment dict

    Raises:
        RuntimeError: If comment not found or deleted
    """
    from .repo import update_comment

    comment = update_comment(comment_id=comment_id, body_md=body_md, conn=conn)
    conn.commit()

    # Record event
    event_payload = {"comment_id": comment.id}
    event_id = repo.insert_loop_event(
        loop_id=comment.loop_id,
        event_type=LoopEventType.COMMENT_UPDATED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.COMMENT_UPDATED.value,
        payload=event_payload,
        conn=conn,
    )
    conn.commit()

    return _comment_to_dict(comment)


@typingx.validate_io()
def delete_loop_comment(
    *,
    comment_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Soft-delete a comment.

    Args:
        comment_id: Comment to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found
    """
    from .repo import get_comment, soft_delete_comment

    comment = get_comment(comment_id=comment_id, conn=conn)
    if comment is None:
        return False

    deleted = soft_delete_comment(comment_id=comment_id, conn=conn)

    if deleted:
        # Record event
        event_payload = {"comment_id": comment.id}
        event_id = repo.insert_loop_event(
            loop_id=comment.loop_id,
            event_type=LoopEventType.COMMENT_DELETED.value,
            payload=event_payload,
            conn=conn,
        )
        conn.commit()
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.COMMENT_DELETED.value,
            payload=event_payload,
            conn=conn,
        )
        conn.commit()

    return deleted


# ... (existing content up to line 3106)


# ============================================================================
# Duplicate Detection and Merge Service Functions
# ============================================================================


@dataclass(frozen=True, slots=True)
class MergePreview:
    """Preview of what a merge would produce."""

    surviving_loop_id: int
    duplicate_loop_id: int
    merged_title: str | None
    merged_summary: str | None
    merged_tags: list[str]
    merged_next_action: str | None
    field_conflicts: dict[str, dict[str, Any]]  # field -> {surviving: v, duplicate: v}


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Result of a completed merge operation."""

    surviving_loop: LoopRecord
    closed_loop_id: int
    merged_tags: list[str]
    fields_updated: list[str]


@typingx.validate_io()
def preview_merge(
    *,
    surviving_loop_id: int,
    duplicate_loop_id: int,
    conn: sqlite3.Connection,
) -> MergePreview:
    """Preview what a merge would produce without executing it.

    Args:
        surviving_loop_id: The loop that will absorb content
        duplicate_loop_id: The loop that will be closed
        conn: Database connection

    Returns:
        MergePreview showing merged field values and any conflicts

    Raises:
        LoopNotFoundError: If either loop doesn't exist
        ValidationError: If loops have same ID or same status conflicts
    """
    if surviving_loop_id == duplicate_loop_id:
        raise ValidationError("loop_id", "Cannot merge a loop with itself")

    surviving = repo.read_loop(loop_id=surviving_loop_id, conn=conn)
    if surviving is None:
        raise LoopNotFoundError(surviving_loop_id)

    duplicate = repo.read_loop(loop_id=duplicate_loop_id, conn=conn)
    if duplicate is None:
        raise LoopNotFoundError(duplicate_loop_id)

    if is_terminal_status(surviving.status):
        raise ValidationError("surviving_loop_id", "Cannot merge into a closed loop")

    # Calculate merged values: prefer surviving, but use duplicate if surviving is empty
    merged_title = surviving.title or duplicate.title
    merged_summary = surviving.summary or duplicate.summary
    merged_next_action = surviving.next_action or duplicate.next_action

    # Merge tags: union of both
    surviving_tags = set(repo.list_loop_tags(loop_id=surviving_loop_id, conn=conn))
    duplicate_tags = set(repo.list_loop_tags(loop_id=duplicate_loop_id, conn=conn))
    merged_tags = sorted(surviving_tags | duplicate_tags)

    # Identify conflicts: both loops have non-empty, different values
    conflicts: dict[str, dict[str, Any]] = {}
    if surviving.title and duplicate.title and surviving.title != duplicate.title:
        conflicts["title"] = {"surviving": surviving.title, "duplicate": duplicate.title}
    if surviving.summary and duplicate.summary and surviving.summary != duplicate.summary:
        conflicts["summary"] = {"surviving": surviving.summary, "duplicate": duplicate.summary}
    if (
        surviving.next_action
        and duplicate.next_action
        and surviving.next_action != duplicate.next_action
    ):
        conflicts["next_action"] = {
            "surviving": surviving.next_action,
            "duplicate": duplicate.next_action,
        }

    return MergePreview(
        surviving_loop_id=surviving_loop_id,
        duplicate_loop_id=duplicate_loop_id,
        merged_title=merged_title,
        merged_summary=merged_summary,
        merged_tags=list(merged_tags),
        merged_next_action=merged_next_action,
        field_conflicts=conflicts,
    )


@typingx.validate_io()
def merge_loops(
    *,
    surviving_loop_id: int,
    duplicate_loop_id: int,
    field_overrides: Mapping[str, str | None] | None = None,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> MergeResult:
    """Merge a duplicate loop into the surviving loop.

    This operation:
    1. Copies non-empty fields from duplicate to surviving (if surviving field is empty)
    2. Merges tags (union of both)
    3. Closes the duplicate as 'dropped' with a completion note
    4. Emits merge events for audit trail

    Args:
        surviving_loop_id: The loop that will absorb content
        duplicate_loop_id: The loop that will be closed
        field_overrides: Optional explicit values for conflicting fields
        conn: Database connection
        settings: Optional settings override

    Returns:
        MergeResult with the updated surviving loop

    Raises:
        LoopNotFoundError: If either loop doesn't exist
        ValidationError: If loops have same ID or surviving is closed
        MergeConflictError: If loops are claimed by different owners
    """
    from .errors import MergeConflictError

    settings = settings or get_settings()
    field_overrides = field_overrides or {}

    # Validate and get preview
    preview = preview_merge(
        surviving_loop_id=surviving_loop_id,
        duplicate_loop_id=duplicate_loop_id,
        conn=conn,
    )

    # Check for claim conflicts
    surviving_claim = repo.read_claim(loop_id=surviving_loop_id, conn=conn)
    duplicate_claim = repo.read_claim(loop_id=duplicate_loop_id, conn=conn)
    if surviving_claim and duplicate_claim and surviving_claim.owner != duplicate_claim.owner:
        raise MergeConflictError(
            loop_id=duplicate_loop_id,
            target_id=surviving_loop_id,
            reason=(
                f"Loops claimed by different owners: {surviving_claim.owner} "
                f"vs {duplicate_claim.owner}"
            ),
        )

    # Build update fields, applying overrides for conflicts
    updates: dict[str, Any] = {}
    fields_updated: list[str] = []

    if preview.merged_title and (
        preview.field_conflicts.get("title") or field_overrides.get("title")
    ):
        title = field_overrides.get("title", preview.merged_title)
        if title:
            updates["title"] = title
            fields_updated.append("title")

    if preview.merged_summary and (
        preview.field_conflicts.get("summary") or field_overrides.get("summary")
    ):
        summary = field_overrides.get("summary", preview.merged_summary)
        if summary:
            updates["summary"] = summary
            fields_updated.append("summary")

    if preview.merged_next_action and (
        preview.field_conflicts.get("next_action") or field_overrides.get("next_action")
    ):
        next_action = field_overrides.get("next_action", preview.merged_next_action)
        if next_action:
            updates["next_action"] = next_action
            fields_updated.append("next_action")

    # Apply updates to surviving loop
    with conn:
        if updates:
            repo.update_loop_fields(loop_id=surviving_loop_id, fields=updates, conn=conn)

        # Replace tags with merged set
        if preview.merged_tags:
            repo.replace_loop_tags(
                loop_id=surviving_loop_id,
                tag_names=preview.merged_tags,
                conn=conn,
            )
            fields_updated.append("tags")

        # Close duplicate as dropped
        now = utc_now()
        repo.update_loop_fields(
            loop_id=duplicate_loop_id,
            fields={
                "status": LoopStatus.DROPPED.value,
                "closed_at": format_utc_datetime(now),
                "completion_note": f"Merged into loop #{surviving_loop_id}",
            },
            conn=conn,
        )

        # Emit events for audit trail
        repo.insert_loop_event(
            loop_id=surviving_loop_id,
            event_type=LoopEventType.UPDATE.value,
            payload={
                "action": "merge_absorbed",
                "from_loop_id": duplicate_loop_id,
                "fields": fields_updated,
            },
            conn=conn,
        )
        repo.insert_loop_event(
            loop_id=duplicate_loop_id,
            event_type=LoopEventType.CLOSE.value,
            payload={
                "action": "merged_into",
                "target_loop_id": surviving_loop_id,
                "status": "dropped",
            },
            conn=conn,
        )

        # Update duplicate link to mark as resolved
        conn.execute(
            """
            UPDATE loop_links
            SET relationship_type = 'duplicate_resolved'
            WHERE loop_id = ? AND related_loop_id = ? AND relationship_type = 'duplicate'
            """,
            (duplicate_loop_id, surviving_loop_id),
        )

    # Fetch updated surviving loop
    surviving = repo.read_loop(loop_id=surviving_loop_id, conn=conn)
    if surviving is None:
        raise LoopNotFoundError(surviving_loop_id)

    return MergeResult(
        surviving_loop=surviving,
        closed_loop_id=duplicate_loop_id,
        merged_tags=preview.merged_tags,
        fields_updated=fields_updated,
    )


@typingx.validate_io()
def find_duplicate_candidates_for_loop(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Find potential duplicate loops for a given loop.

    This is a service wrapper around related.find_duplicate_candidates()
    that returns plain dicts for API responses.

    Args:
        loop_id: The loop to check for duplicates
        conn: Database connection
        settings: Optional settings override

    Returns:
        List of duplicate candidate dicts

    Raises:
        LoopNotFoundError: If loop doesn't exist
    """
    from . import related

    # Verify loop exists
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

    candidates = related.find_duplicate_candidates(
        loop_id=loop_id,
        conn=conn,
        settings=settings,
    )

    return [
        {
            "loop_id": c.loop_id,
            "score": c.score,
            "title": c.title,
            "raw_text_preview": c.raw_text_preview,
            "status": c.status,
            "captured_at_utc": c.captured_at_utc,
        }
        for c in candidates
    ]


@typingx.validate_io()
def list_loop_suggestions(
    *,
    loop_id: int | None = None,
    pending_only: bool = False,
    limit: int = 50,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List suggestions with parsed suggestion_json for convenience.

    Args:
        loop_id: Optional loop ID to filter by
        pending_only: If True, only return suggestions awaiting resolution
        limit: Maximum number of results
        conn: Database connection

    Returns:
        List of suggestion dicts with 'parsed' field containing the JSON
    """
    if pending_only:
        suggestions = repo.list_pending_suggestions(conn=conn, limit=limit)
    else:
        suggestions = repo.list_loop_suggestions(loop_id=loop_id, limit=limit, conn=conn)

    for s in suggestions:
        s["parsed"] = json.loads(s["suggestion_json"])
    return suggestions


@typingx.validate_io()
def apply_suggestion(
    *,
    suggestion_id: int,
    fields: list[str] | None = None,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    """Apply a suggestion to its loop. If fields specified, only apply those.

    Args:
        suggestion_id: The suggestion ID to apply
        fields: Optional list of field names to apply (if None, apply all above threshold)
        conn: Database connection
        settings: Application settings for thresholds

    Returns:
        Dict with loop, suggestion_id, applied_fields, and resolution

    Raises:
        SuggestionNotFoundError: If suggestion doesn't exist
        ValidationError: If suggestion already resolved
        LoopNotFoundError: If the target loop doesn't exist
    """
    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)
    if not suggestion:
        raise SuggestionNotFoundError(suggestion_id)

    if suggestion.get("resolution"):
        raise ValidationError(
            "suggestion", f"Suggestion already resolved: {suggestion['resolution']}"
        )

    loop_id = suggestion["loop_id"]
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if not loop:
        raise LoopNotFoundError(loop_id)

    parsed = json.loads(suggestion["suggestion_json"])
    applied_fields: list[str] = []

    # Determine which fields to apply
    if fields:
        # User specified fields
        apply_set = set(fields)
    else:
        # Apply all fields above confidence threshold
        apply_set = {
            f
            for f, c in parsed.get("confidence", {}).items()
            if c >= settings.autopilot_autoapply_min_confidence
        }

    # Build update dict
    update_fields: dict[str, Any] = {}
    field_mapping = {
        "title": ("title", parsed.get("title")),
        "summary": ("summary", parsed.get("summary")),
        "definition_of_done": ("definition_of_done", parsed.get("definition_of_done")),
        "next_action": ("next_action", parsed.get("next_action")),
        "due_at": ("due_at_utc", parsed.get("due_at")),
        "snooze_until": ("snooze_until_utc", parsed.get("snooze_until")),
        "activation_energy": ("activation_energy", parsed.get("activation_energy")),
        "time_minutes": ("time_minutes", parsed.get("time_minutes")),
        "urgency": ("urgency", parsed.get("urgency")),
        "importance": ("importance", parsed.get("importance")),
    }

    for field_name, (db_field, value) in field_mapping.items():
        if field_name in apply_set and value is not None:
            update_fields[db_field] = value
            applied_fields.append(field_name)

    # Handle project separately (needs upsert)
    if "project" in apply_set and parsed.get("project"):
        project_id = repo.upsert_project(name=parsed["project"], conn=conn)
        update_fields["project_id"] = project_id
        applied_fields.append("project")

    # Handle tags separately (needs tag table)
    if "tags" in apply_set and parsed.get("tags"):
        repo.replace_loop_tags(loop_id=loop_id, tag_names=parsed["tags"], conn=conn)
        applied_fields.append("tags")

    # Update loop
    if update_fields:
        repo.update_loop_fields(loop_id=loop_id, fields=update_fields, conn=conn)

    # Mark suggestion resolved
    resolution = "applied" if len(applied_fields) == len(apply_set) else "partial"
    repo.resolve_loop_suggestion(
        suggestion_id=suggestion_id,
        resolution=resolution,
        applied_fields=applied_fields,
        conn=conn,
    )

    # Return updated loop
    updated_loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if updated_loop:
        project = repo.read_project_name(project_id=updated_loop.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=loop_id, conn=conn)
        loop_dict = _record_to_dict(updated_loop, project=project, tags=tags)
    else:
        loop_dict = None

    return {
        "loop": loop_dict,
        "suggestion_id": suggestion_id,
        "applied_fields": applied_fields,
        "resolution": resolution,
    }


@typingx.validate_io()
def reject_suggestion(
    *,
    suggestion_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Reject a suggestion without applying any fields.

    Args:
        suggestion_id: The suggestion ID to reject
        conn: Database connection

    Returns:
        Dict with suggestion_id and resolution

    Raises:
        SuggestionNotFoundError: If suggestion doesn't exist
        ValidationError: If suggestion already resolved
    """
    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)
    if not suggestion:
        raise SuggestionNotFoundError(suggestion_id)

    if suggestion.get("resolution"):
        raise ValidationError(
            "suggestion", f"Suggestion already resolved: {suggestion['resolution']}"
        )

    repo.resolve_loop_suggestion(
        suggestion_id=suggestion_id,
        resolution="rejected",
        conn=conn,
    )

    return {
        "suggestion_id": suggestion_id,
        "resolution": "rejected",
    }
