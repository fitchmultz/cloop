"""Duplicate detection and merge functions for loops.

Purpose:
    Provide duplicate detection capabilities and merge operations for loop management,
    including merge previews, conflict detection, and suggestion handling.

Responsibilities:
    - Detect duplicate loop candidates
    - Preview merge operations and identify conflicts
    - Execute merge operations with field resolution
    - Manage loop suggestions (apply/reject)

Non-scope:
    - Direct database schema management (see db.py)
    - Repository operations (see repo.py)
    - HTTP request/response handling (see routes/)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from .. import typingx
from ..settings import Settings, get_settings
from . import repo
from .claim_state import read_active_claim
from .errors import LoopNotFoundError, SuggestionNotFoundError, ValidationError
from .models import (
    LoopEventType,
    LoopRecord,
    LoopStatus,
    format_utc_datetime,
    is_terminal_status,
    utc_now,
)
from .serialization import loop_record_to_dict


def _record_to_dict(
    record: LoopRecord,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return loop_record_to_dict(record, project=project, tags=tags)


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
    surviving_claim = read_active_claim(loop_id=surviving_loop_id, conn=conn)
    duplicate_claim = read_active_claim(loop_id=duplicate_loop_id, conn=conn)
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
