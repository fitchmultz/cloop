"""Shared loop-repository helpers.

Purpose:
    Hold row-conversion helpers and repository-local constants shared across
    focused loop persistence modules.

Responsibilities:
    - Parse JSON payload columns into Python containers
    - Convert loop rows into LoopRecord models
    - Centralize repository-local sentinel/constants used across submodules

Non-scope:
    - Executing SQL CRUD statements
    - Business-rule validation above repository concerns
    - Public repository re-export wiring
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..models import EnrichmentState, LoopRecord, LoopStatus, parse_utc_datetime

_UNSET: object = object()

_ALLOWED_UPDATE_FIELDS = {
    "raw_text",
    "title",
    "status",
    "captured_at_utc",
    "captured_tz_offset_min",
    "closed_at",
    "due_date",
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
    "user_locks_json",
    "provenance_json",
    "enrichment_state",
    "recurrence_rrule",
    "recurrence_tz",
    "next_due_at_utc",
    "recurrence_enabled",
    "parent_loop_id",
}


def _parse_json_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON list: {e}. Raw value: {repr(value)[:200]}") from e
    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected JSON list, got {type(parsed).__name__}. Raw value: {repr(value)[:200]}"
        )
    return [str(item) for item in parsed]


def _parse_json_dict(value: Any) -> dict[str, object]:
    if value is None or value == "":
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON dict: {e}. Raw value: {repr(value)[:200]}") from e
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Expected JSON dict, got {type(parsed).__name__}. Raw value: {repr(value)[:200]}"
        )
    return parsed


def _row_to_record(row: sqlite3.Row) -> LoopRecord:
    return LoopRecord(
        id=row["id"],
        raw_text=row["raw_text"],
        title=row["title"] if row["title"] is not None else None,
        summary=row["summary"] if row["summary"] is not None else None,
        definition_of_done=(
            row["definition_of_done"] if row["definition_of_done"] is not None else None
        ),
        next_action=row["next_action"] if row["next_action"] is not None else None,
        status=LoopStatus(row["status"]),
        captured_at_utc=parse_utc_datetime(row["captured_at_utc"]),
        captured_tz_offset_min=row["captured_tz_offset_min"],
        due_date=row["due_date"] if "due_date" in row.keys() and row["due_date"] else None,
        due_at_utc=parse_utc_datetime(row["due_at_utc"]) if row["due_at_utc"] else None,
        snooze_until_utc=(
            parse_utc_datetime(row["snooze_until_utc"]) if row["snooze_until_utc"] else None
        ),
        time_minutes=row["time_minutes"] if row["time_minutes"] is not None else None,
        activation_energy=(
            row["activation_energy"] if row["activation_energy"] is not None else None
        ),
        urgency=row["urgency"] if row["urgency"] is not None else None,
        importance=row["importance"] if row["importance"] is not None else None,
        project_id=row["project_id"] if row["project_id"] is not None else None,
        blocked_reason=row["blocked_reason"] if row["blocked_reason"] is not None else None,
        completion_note=row["completion_note"] if row["completion_note"] is not None else None,
        user_locks=_parse_json_list(row["user_locks_json"]),
        provenance=_parse_json_dict(row["provenance_json"]),
        enrichment_state=EnrichmentState(row["enrichment_state"] or EnrichmentState.IDLE.value),
        recurrence_rrule=(
            row["recurrence_rrule"]
            if "recurrence_rrule" in row.keys() and row["recurrence_rrule"] is not None
            else None
        ),
        recurrence_tz=(
            row["recurrence_tz"]
            if "recurrence_tz" in row.keys() and row["recurrence_tz"] is not None
            else None
        ),
        next_due_at_utc=(
            parse_utc_datetime(row["next_due_at_utc"])
            if "next_due_at_utc" in row.keys() and row["next_due_at_utc"]
            else None
        ),
        recurrence_enabled=(
            bool(row["recurrence_enabled"]) if "recurrence_enabled" in row.keys() else False
        ),
        parent_loop_id=(
            row["parent_loop_id"]
            if "parent_loop_id" in row.keys() and row["parent_loop_id"] is not None
            else None
        ),
        created_at_utc=parse_utc_datetime(row["created_at"]),
        updated_at_utc=parse_utc_datetime(row["updated_at"]),
        closed_at_utc=parse_utc_datetime(row["closed_at"]) if row["closed_at"] else None,
    )
