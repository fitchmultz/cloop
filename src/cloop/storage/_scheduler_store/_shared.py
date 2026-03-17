"""Shared helpers for scheduler storage internals.

Purpose:
    Centralize timestamp and JSON serialization helpers shared by focused
    scheduler storage modules.

Responsibilities:
    - Serialize UTC datetimes for scheduler persistence rows
    - Serialize optional JSON payloads consistently across modules
    - Keep common storage helper logic out of SQL-owning modules

Scope:
    - Internal helper utilities for scheduler storage only

Usage:
    - Imported by sibling modules under `cloop.storage._scheduler_store`

Invariants/Assumptions:
    - Scheduler timestamps are persisted as ISO-8601 UTC strings
    - Optional JSON payloads are stored as text or NULL

Non-scope:
    - Direct SQL ownership for task runs, schedules, or push dedupe
    - Public scheduler storage exports
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def iso_utc(value: datetime) -> str:
    """Serialize one UTC datetime for scheduler persistence."""
    return value.isoformat()


def dump_optional_json(value: dict[str, Any] | None) -> str | None:
    """Serialize an optional JSON payload for scheduler persistence."""
    return json.dumps(value) if value is not None else None
