"""Canonical due-date normalization helpers.

Purpose:
    Keep date-only due values explicit while still supporting exact timestamps.

Responsibilities:
    - Validate ISO date strings used for date-only due values
    - Normalize incoming due field payloads before persistence
    - Provide helpers for legacy/backfill inference

Non-scope:
    - Query ordering/filter semantics (see due.py)
    - Transport-layer schema definitions
"""

from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime
from typing import Any

from .errors import ValidationError

_DATE_ONLY_SUFFIXES = frozenset({"T23:59:59Z", "T23:59:00Z"})


def validate_due_date(value: str | None, field_name: str = "due_date") -> str | None:
    """Validate an ISO calendar date string."""
    if value is None:
        return None

    raw_value = str(value).strip()
    if not raw_value:
        raise ValidationError(field_name, "value cannot be empty")

    try:
        parsed = datetime.strptime(raw_value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError(
            field_name,
            f"'{raw_value}' is not a valid ISO date. Expected format: 2026-03-15",
        ) from exc

    return parsed.strftime("%Y-%m-%d")


def due_date_to_utc_timestamp(due_date: str) -> str:
    """Derive the internal effective timestamp for a date-only due value."""
    return f"{due_date}T23:59:59Z"


def normalize_due_fields(fields: MutableMapping[str, Any]) -> None:
    """Normalize due_date/due_at_utc combinations for persistence."""
    due_date_provided = "due_date" in fields
    due_at_provided = "due_at_utc" in fields
    if not due_date_provided and not due_at_provided:
        return

    if due_date_provided and fields.get("due_date") not in {None, ""}:
        normalized_due_date = validate_due_date(str(fields["due_date"]))
        assert normalized_due_date is not None
        fields["due_date"] = normalized_due_date
        fields["due_at_utc"] = due_date_to_utc_timestamp(normalized_due_date)
        return

    if due_at_provided and fields.get("due_at_utc"):
        fields["due_date"] = None
        return

    # Explicitly clearing either field clears the full due contract.
    fields["due_date"] = None
    fields["due_at_utc"] = None


def infer_legacy_due_date(due_at_utc: str | None) -> str | None:
    """Infer a date-only due string from the legacy end-of-day timestamp contract."""
    if not due_at_utc:
        return None
    if any(str(due_at_utc).endswith(suffix) for suffix in _DATE_ONLY_SUFFIXES):
        return str(due_at_utc)[:10]
    return None
