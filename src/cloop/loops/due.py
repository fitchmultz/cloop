"""Canonical due-date helpers for loops.

Purpose:
    Provide one shared abstraction for recurrence-aware due semantics across
    prioritization, review, scheduler, and query compilation.

Responsibilities:
    - Resolve the effective due timestamp from `due_at_utc` and `next_due_at_utc`
    - Provide a reusable SQL expression for due-aware queries

Non-scope:
    - Query execution or persistence
    - Scheduling or prioritization policy
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .models import parse_utc_datetime


def _mapping_value(loop: Mapping[str, Any], key: str) -> Any:
    """Return a key from a mapping or sqlite Row without assuming `.get()` support."""
    try:
        return loop[key]
    except Exception:  # noqa: BLE001
        return None


def effective_due_sql(*, table_alias: str = "loops") -> str:
    """Return the canonical SQL expression for a loop's effective due value."""
    prefix = f"{table_alias}." if table_alias else ""
    return f"COALESCE({prefix}due_at_utc, {prefix}next_due_at_utc)"


def effective_due_iso(loop: Mapping[str, Any]) -> str | None:
    """Return the effective due ISO string from a mapping-like loop payload."""
    due = _mapping_value(loop, "due_at_utc")
    if due:
        return str(due)
    next_due = _mapping_value(loop, "next_due_at_utc")
    return str(next_due) if next_due else None


def effective_due_datetime(loop: Mapping[str, Any]) -> datetime | None:
    """Return the effective due datetime from a mapping-like loop payload."""
    due_iso = effective_due_iso(loop)
    if due_iso is None:
        return None
    return parse_utc_datetime(due_iso)
