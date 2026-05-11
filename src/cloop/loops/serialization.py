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

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from . import repo
from .models import LoopEventType, LoopRecord, format_utc_datetime

EnrichmentStatusTone = Literal["neutral", "working", "success", "attention"]


@dataclass(frozen=True, slots=True)
class EnrichmentEventSummary:
    """Latest enrichment event details used to explain loop-card status."""

    event_id: int
    event_type: str
    payload: dict[str, Any]
    created_at_utc: str | None


def _safe_event_payload(payload_json: object) -> dict[str, Any]:
    if not isinstance(payload_json, str) or not payload_json.strip():
        return {}
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sanitize_enrichment_reason(raw_error: object) -> str:
    error = str(raw_error or "").strip()
    lowered = error.lower()
    if not error:
        return "AI organization could not finish."
    if any(
        token in lowered
        for token in (
            "api key",
            "auth",
            "unauthorized",
            "forbidden",
            "provider",
            "model",
            "selector",
            "misconfigured",
            "configuration",
            "configured",
        )
    ):
        return "AI provider settings need attention."
    if "timeout" in lowered or "timed out" in lowered:
        return "The AI provider did not respond in time."
    if "json" in lowered or "validation" in lowered or "schema" in lowered:
        return "The AI response could not be understood."
    return "AI organization could not finish."


def build_enrichment_status(
    *,
    state: str | None,
    latest_event: EnrichmentEventSummary | None = None,
) -> dict[str, Any]:
    """Build the user-facing enrichment status contract for a loop."""
    resolved = (state or "idle").strip() or "idle"
    base: dict[str, Any] = {
        "state": resolved,
        "last_event_id": latest_event.event_id if latest_event else None,
        "last_event_at_utc": latest_event.created_at_utc if latest_event else None,
        "reason": None,
    }
    if resolved == "pending":
        return {
            **base,
            "label": "AI organization running",
            "message": "This loop is usable while AI organization works in the background.",
            "tone": "working",
            "retryable": False,
            "action_label": None,
        }
    if resolved == "complete":
        return {
            **base,
            "label": "AI organization complete",
            "message": "AI organization finished for this loop.",
            "tone": "success",
            "retryable": False,
            "action_label": "Run again",
        }
    if resolved == "failed":
        reason = _sanitize_enrichment_reason(
            (latest_event.payload if latest_event else {}).get("error")
        )
        return {
            **base,
            "label": "AI organization needs attention",
            "message": "This loop is usable, but AI organization could not finish.",
            "tone": "attention",
            "retryable": True,
            "action_label": "Retry AI organization",
            "reason": reason,
        }
    return {
        **base,
        "label": "AI organization optional",
        "message": "This loop is usable. AI organization has not run yet.",
        "tone": "neutral",
        "retryable": True,
        "action_label": "Run AI organization",
    }


def latest_enrichment_events_by_loop(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
) -> dict[int, EnrichmentEventSummary]:
    """Return each loop's latest enrichment event using one bounded query."""
    if not loop_ids:
        return {}
    placeholders = ", ".join("?" for _ in loop_ids)
    event_types = (
        LoopEventType.ENRICH_FAILURE.value,
        LoopEventType.ENRICH_SUCCESS.value,
        LoopEventType.ENRICH_REQUEST.value,
    )
    event_placeholders = ", ".join("?" for _ in event_types)
    rows = conn.execute(
        f"""
        SELECT id, loop_id, event_type, payload_json, created_at
        FROM loop_events
        WHERE loop_id IN ({placeholders})
          AND event_type IN ({event_placeholders})
        ORDER BY loop_id ASC, id DESC
        """,
        [*loop_ids, *event_types],
    ).fetchall()
    summaries: dict[int, EnrichmentEventSummary] = {}
    for row in rows:
        loop_id = int(row["loop_id"])
        if loop_id in summaries:
            continue
        summaries[loop_id] = EnrichmentEventSummary(
            event_id=int(row["id"]),
            event_type=str(row["event_type"]),
            payload=_safe_event_payload(row["payload_json"]),
            created_at_utc=str(row["created_at"]) if row["created_at"] is not None else None,
        )
    return summaries


def loop_record_to_dict(
    record: LoopRecord,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    enrichment_event: EnrichmentEventSummary | None = None,
) -> dict[str, Any]:
    """Convert a LoopRecord into the canonical loop payload shape."""
    enrichment_state = record.enrichment_state.value
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
        "emotional_weight": record.emotional_weight,
        "confidence": record.confidence,
        "project_id": record.project_id,
        "blocked_reason": record.blocked_reason,
        "completion_note": record.completion_note,
        "project": project,
        "tags": tags or [],
        "user_locks": list(record.user_locks),
        "provenance": dict(record.provenance),
        "enrichment_state": enrichment_state,
        "enrichment_status": build_enrichment_status(
            state=enrichment_state,
            latest_event=enrichment_event,
        ),
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
    enrichment_events = latest_enrichment_events_by_loop(loop_ids=loop_ids, conn=conn)

    return [
        loop_record_to_dict(
            record,
            project=projects_map.get(record.project_id) if record.project_id else None,
            tags=tags_map.get(record.id, []),
            enrichment_event=enrichment_events.get(record.id),
        )
        for record in records
    ]
