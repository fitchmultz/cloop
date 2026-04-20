"""Shared helpers for continuity storage internals.

Purpose:
    Centralize JSON serialization, timestamps, and cross-cutting constants used
    by focused continuity storage modules.

Responsibilities:
    - Serialize JSON payloads consistently across continuity tables
    - Provide UTC timestamp parsing/formatting helpers
    - Hold shared tuning constants for dedupe, push cooldowns, and delivery scans

Scope:
    - Internal helper utilities for continuity storage only

Usage:
    - Imported by sibling modules under `cloop.storage._continuity_store`

Invariants/Assumptions:
    - Continuity timestamps are persisted as ISO-8601 UTC strings
    - Optional JSON payloads are stored as text or NULL

Non-scope:
    - Direct SQL ownership for continuity outcomes or notification state
    - Public continuity storage exports
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from ...schemas._loops.continuity import ContinuityLocationResponse

_DEDUPE_WINDOW_SECONDS = 15.0
_PUSH_UNSEEN_RESEND_COOLDOWN = timedelta(hours=6)
_PUSH_SEEN_RESEND_COOLDOWN = timedelta(hours=24)
_HOME_LOCATION = ContinuityLocationResponse(state="operator", recall_tool="chat")

_PUSH_DELIVERY_SCAN_BATCH_SIZE = 24
_PUSH_DELIVERY_MAX_SCAN_OUTCOMES = 96
_DELIVERY_CURSOR_VERSION = 1
_CONTINUITY_FOLLOW_THROUGH_METADATA_KEY = "_continuity_follow_through"


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _dump_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, separators=(",", ":"), sort_keys=True)


def _load_json_map(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cursor_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
