"""Loop service layer for business logic and orchestration.

Purpose:
    Provide high-level business operations for loop lifecycle management.

Responsibilities:
    - Core CRUD operations (capture, get, update, list, search)
    - Status transitions and state machine enforcement
    - Orchestration between repo layer and external services
    - Re-export of domain module functions for backwards compatibility

Non-scope:
    - Direct database access (see repo.py)
    - HTTP request/response handling (see routes/loops.py)
    - Domain-specific operations (see claims.py, timers.py, etc.)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, Mapping

from .. import typingx
from ..settings import Settings, get_settings
from ..webhooks.service import queue_deliveries
from . import repo
from .bulk import (
    _classify_error,
    _rollback_transaction_results,
    bulk_close_loops,
    bulk_snooze_loops,
    bulk_update_loops,
    create_template_from_loop,
)
from .claims import (
    claim_loop,
    force_release_claim,
    get_claim_status,
    list_active_claims,
    release_claim,
    renew_claim,
)
from .comments import (
    create_loop_comment,
    delete_loop_comment,
    get_loop_comment,
    list_loop_comments,
    update_loop_comment,
)
from .duplicates import (
    MergePreview,
    MergeResult,
    apply_suggestion,
    find_duplicate_candidates_for_loop,
    list_loop_suggestions,
    merge_loops,
    preview_merge,
    reject_suggestion,
)
from .errors import (
    DependencyCycleError,
    DependencyNotMetError,
    LoopNotFoundError,
    TransitionError,
    ValidationError,
)
from .events import (
    get_loop_events,
    undo_last_event,
)
from .metrics import record_capture, record_transition, record_update
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
from .pagination import (
    build_next_cursor,
    prepare_cursor_state,
)
from .prioritization import PriorityWeights, bucketize, compute_priority_score
from .service_helpers import (
    _ALLOWED_TRANSITIONS,
    _LOCKABLE_FIELDS,
    _enrich_records_batch,
    _handle_recurrence_on_completion,
    _record_to_dict,
    _validate_claim_for_update,
)
from .timers import (
    ActiveTimerExistsError,
    NoActiveTimerError,
    TimerError,
    get_timer_status,
    list_time_sessions,
    start_timer,
    stop_timer,
)
from .utils import normalize_tag, normalize_tags

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Make exports explicit
__all__ = [
    # Core CRUD
    "capture_loop",
    "get_loop",
    "list_loops",
    "list_loops_by_statuses",
    "list_loops_by_tag",
    "list_tags",
    "export_loops",
    "import_loops",
    "update_loop",
    "transition_status",
    # Dependencies
    "add_loop_dependency",
    "remove_loop_dependency",
    "get_loop_dependencies",
    "get_loop_blocking",
    "get_loop_with_dependencies",
    # Enrichment/Search
    "request_enrichment",
    "search_loops",
    "next_loops",
    "search_loops_by_query",
    # Views
    "create_loop_view",
    "list_loop_views",
    "get_loop_view",
    "update_loop_view",
    "delete_loop_view",
    "apply_loop_view",
    # Pagination
    "list_loops_page",
    "search_loops_by_query_page",
    "apply_loop_view_page",
    # Claims (re-exported)
    "claim_loop",
    "renew_claim",
    "release_claim",
    "force_release_claim",
    "get_claim_status",
    "list_active_claims",
    # Timers (re-exported)
    "start_timer",
    "stop_timer",
    "get_timer_status",
    "list_time_sessions",
    "TimerError",
    "ActiveTimerExistsError",
    "NoActiveTimerError",
    # Events (re-exported)
    "get_loop_events",
    "undo_last_event",
    # Comments (re-exported)
    "create_loop_comment",
    "list_loop_comments",
    "get_loop_comment",
    "update_loop_comment",
    "delete_loop_comment",
    # Duplicates (re-exported)
    "preview_merge",
    "merge_loops",
    "find_duplicate_candidates_for_loop",
    "list_loop_suggestions",
    "apply_suggestion",
    "reject_suggestion",
    "MergePreview",
    "MergeResult",
    # Bulk (re-exported)
    "bulk_update_loops",
    "bulk_close_loops",
    "bulk_snooze_loops",
    "create_template_from_loop",
    "_classify_error",
    "_rollback_transaction_results",
    # Constants
    "_ALLOWED_TRANSITIONS",
    "_LOCKABLE_FIELDS",
    # Internal helpers (for use by other modules)
    "_handle_recurrence_on_completion",
    "_record_to_dict",
    "_enrich_records_batch",
]


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
        # Reset due_soon nudge state when next_action is set (user has taken action)
        if "next_action" in fields and fields["next_action"] is not None:
            repo.reset_nudge_state(loop_id=loop_id, nudge_type="due_soon", conn=conn)
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

    # Bucketize and collect all items with (bucket_label, record, score)
    scored_with_buckets: list[tuple[str, LoopRecord, float]] = []
    for record, score in scored:
        label = bucketize(_record_to_dict(record), now_utc=now, settings=settings)
        if label in {"due_soon", "quick_wins", "high_leverage", "standard"}:
            scored_with_buckets.append((label, record, score))

    # Sort all items globally by score (descending)
    scored_with_buckets.sort(key=lambda x: x[2], reverse=True)

    # Take only top N items globally
    top_items = scored_with_buckets[:limit]

    # Collect loop IDs and project IDs for batch enrichment
    all_loop_ids: list[int] = []
    all_project_ids: set[int] = set()
    for _label, record, _score in top_items:
        all_loop_ids.append(record.id)
        if record.project_id is not None:
            all_project_ids.add(record.project_id)

    # Batch fetch all projects and tags
    projects_map = repo.read_project_names_batch(project_ids=all_project_ids, conn=conn)
    tags_map = repo.list_loop_tags_batch(loop_ids=all_loop_ids, conn=conn)

    # Reconstruct buckets from top items only
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
