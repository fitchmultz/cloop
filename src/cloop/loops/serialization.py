"""Shared serializers for loop-domain records.

Purpose:
    Centralize conversion of loop-domain records into response-ready dicts so
    every service path returns the same shape and field set.

Responsibilities:
    - Serialize LoopRecord instances into canonical dict payloads
    - Batch-enrich loop records with project names and tags efficiently
    - Keep response field coverage consistent across services

Non-scope:
    - Does not orchestrate business mutations
    - Does not define HTTP or MCP schema classes
    - Does not own database connection lifecycle
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import repo
from .models import LoopRecord, format_utc_datetime


def loop_record_to_dict(
    record: LoopRecord,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Convert a LoopRecord into the canonical loop payload shape."""
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
        "due_date": record.due_date,
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


def enrich_loop_records_batch(
    records: list[LoopRecord],
    *,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Enrich loop records with projects and tags using batched lookups."""
    if not records:
        return []

    project_ids = {record.project_id for record in records if record.project_id is not None}
    loop_ids = [record.id for record in records]

    projects_map = repo.read_project_names_batch(project_ids=project_ids, conn=conn)
    tags_map = repo.list_loop_tags_batch(loop_ids=loop_ids, conn=conn)

    return [
        loop_record_to_dict(
            record,
            project=projects_map.get(record.project_id) if record.project_id else None,
            tags=tags_map.get(record.id, []),
        )
        for record in records
    ]
