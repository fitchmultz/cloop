"""Duplicate detection and merge functions for loops.

Purpose:
    Provide duplicate detection capabilities and merge operations for loop management.

Responsibilities:
    - Detect duplicate loop candidates
    - Preview merge operations and identify conflicts
    - Execute merge operations with field resolution

Non-scope:
    - Enrichment suggestion and clarification review flows (see enrichment_review.py)
    - Direct database schema management (see db.py)
    - Repository operations (see repo.py)
    - HTTP request/response handling (see routes/)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from .. import typingx
from ..settings import Settings, get_settings
from . import repo
from .claim_state import read_active_claim
from .errors import LoopNotFoundError, ValidationError
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
