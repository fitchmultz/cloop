"""Loop service layer for business logic and orchestration.

Purpose:
    Provide high-level business operations for loop lifecycle management.

Responsibilities:
    - Core CRUD operations (capture, get, update, list, search)
    - Status transitions and state machine enforcement
    - Orchestration between repo layer and external services

Non-scope:
    - Direct database access (see repo.py)
    - HTTP request/response handling (see routes/loops.py)
    - Read/query retrieval and prioritization concerns
    - Saved-view and template management concerns
    - Domain-specific operations handled by focused loop modules
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, Mapping

from .. import typingx
from ..schemas.export_import import (
    ConflictInfo,
    ConflictPolicy,
    ExportFilters,
    ImportOptions,
    ImportPreview,
    ImportResult,
)
from ..webhooks.service import queue_deliveries
from . import repo
from .due_contract import normalize_due_fields
from .errors import (
    DependencyCycleError,
    LoopNotFoundError,
    ValidationError,
)
from .metrics import record_capture
from .models import (
    EnrichmentState,
    LoopEventType,
    LoopStatus,
    format_utc_datetime,
    parse_client_datetime,
    parse_utc_datetime,
    utc_now,
)
from .utils import normalize_tags
from .write_ops import (
    _apply_loop_update,
    _apply_status_transition,
    _enrich_record,
    _enrich_records_batch,
    _handle_recurrence_on_completion,
    _record_to_dict,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Make exports explicit
__all__ = [
    # Core CRUD
    "capture_loop",
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

        event_payload: dict[str, Any] = {
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
def export_loops(
    *,
    conn: sqlite3.Connection,
    filters: ExportFilters | None = None,
) -> list[dict[str, Any]]:
    """Export loops with optional filters."""
    if filters is None:
        records = repo.list_all_loops(conn=conn)
    else:
        status_list = None
        if filters.status:
            status_list = [LoopStatus(s) for s in filters.status]

        records = repo.export_loops_filtered(
            status=status_list,
            project_name=filters.project,
            tag=filters.tag,
            created_after=filters.created_after.isoformat() if filters.created_after else None,
            created_before=filters.created_before.isoformat() if filters.created_before else None,
            updated_after=filters.updated_after.isoformat() if filters.updated_after else None,
            conn=conn,
        )
    return _enrich_records_batch(records, conn=conn)


@typingx.validate_io()
def import_loops(
    *,
    loops: list[Mapping[str, Any]],
    conn: sqlite3.Connection,
    options: ImportOptions | None = None,
) -> ImportResult:
    """Import loops with dry-run and conflict handling support."""
    if options is None:
        options = ImportOptions()

    now = utc_now()
    conflicts: list[ConflictInfo] = []
    validation_errors: list[dict[str, Any]] = []
    to_create: list[dict[str, Any]] = []
    to_update: list[tuple[int, dict[str, Any]]] = []  # (existing_id, imported_data)

    # First pass: detect conflicts and validate
    for idx, item in enumerate(loops):
        if isinstance(item, Mapping):
            item_map = dict(item)
        else:
            item_map = item.model_dump()

        # Validate required fields
        if not item_map.get("raw_text"):
            validation_errors.append(
                {
                    "index": idx,
                    "error": "missing required field: raw_text",
                }
            )
            continue

        # Check for conflicts
        existing = repo.find_loop_by_raw_text(
            raw_text=str(item_map.get("raw_text", "")),
            conn=conn,
        )
        match_field = "raw_text"

        if not existing and item_map.get("title"):
            existing = repo.find_loop_by_title(
                title=str(item_map.get("title")),
                conn=conn,
            )
            match_field = "title"

        if existing:
            conflicts.append(
                ConflictInfo(
                    imported_loop=item_map,
                    existing_loop_id=existing.id,
                    match_field=match_field,
                )
            )

            if options.conflict_policy == ConflictPolicy.SKIP:
                continue
            elif options.conflict_policy == ConflictPolicy.UPDATE:
                to_update.append((existing.id, item_map))
                continue
            elif options.conflict_policy == ConflictPolicy.FAIL:
                if not options.dry_run:
                    msg = (
                        f"Import conflict detected: loop matches "
                        f"existing loop {existing.id} by {match_field}"
                    )
                    raise ValidationError("conflict", msg)
        else:
            to_create.append(item_map)

    # If dry-run, return preview without writing
    if options.dry_run:
        return ImportResult(
            imported=0,
            skipped=len(conflicts) if options.conflict_policy == ConflictPolicy.SKIP else 0,
            updated=0,
            conflicts_detected=len(conflicts),
            dry_run=True,
            preview=ImportPreview(
                total_loops=len(loops),
                would_create=len(to_create),
                would_skip=len(conflicts) if options.conflict_policy == ConflictPolicy.SKIP else 0,
                would_update=len(to_update),
                conflicts=conflicts,
                validation_errors=validation_errors,
            ),
        )

    # Actually perform the import
    imported = 0
    updated = 0
    skipped = len([c for c in conflicts if options.conflict_policy == ConflictPolicy.SKIP])

    with conn:
        # Create new loops
        for item_map in to_create:
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
                "due_date": item_map.get("due_date"),
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
            normalize_due_fields(payload)
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

        # Update existing loops (for conflict_policy=update)
        for existing_id, item_map in to_update:
            # Build update fields from imported data
            update_fields: dict[str, Any] = {}
            for field in [
                "title",
                "summary",
                "definition_of_done",
                "next_action",
                "due_date",
                "due_at_utc",
                "snooze_until_utc",
                "time_minutes",
                "activation_energy",
                "urgency",
                "importance",
                "blocked_reason",
                "completion_note",
            ]:
                if field in item_map and item_map[field] is not None:
                    update_fields[field] = item_map[field]

            if update_fields:
                normalize_due_fields(update_fields)
                repo.update_loop_fields(loop_id=existing_id, fields=update_fields, conn=conn)

            # Update tags if provided
            tags = item_map.get("tags")
            if tags:
                normalized_tags = normalize_tags(tags)
                repo.replace_loop_tags(loop_id=existing_id, tag_names=normalized_tags, conn=conn)

            updated += 1

    return ImportResult(
        imported=imported,
        skipped=skipped,
        updated=updated,
        conflicts_detected=len(conflicts),
        dry_run=False,
    )


@typingx.validate_io()
def update_loop(
    *,
    loop_id: int,
    fields: Mapping[str, Any],
    conn: sqlite3.Connection,
    claim_token: str | None = None,
) -> dict[str, Any]:
    with conn:
        updated = _apply_loop_update(
            loop_id=loop_id,
            fields=fields,
            conn=conn,
            claim_token=claim_token,
        )
    return _enrich_record(record=updated, conn=conn)


@typingx.validate_io()
def transition_status(
    *,
    loop_id: int,
    to_status: LoopStatus,
    conn: sqlite3.Connection,
    note: str | None = None,
    claim_token: str | None = None,
) -> dict[str, Any]:
    with conn:
        updated = _apply_status_transition(
            loop_id=loop_id,
            to_status=to_status,
            note=note,
            conn=conn,
            claim_token=claim_token,
        )
    return _enrich_record(record=updated, conn=conn)


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

    with conn:
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
    with conn:
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
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

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
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if loop is None:
        raise LoopNotFoundError(loop_id)

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
