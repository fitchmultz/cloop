"""Cursor pagination helpers for loop keyset paging.

Purpose:
- Encode/decode opaque cursor tokens for MCP list/search/view pagination.

Responsibilities:
- Validate cursor structure and version.
- Preserve stable paging anchors and query fingerprints.

Non-scope:
- SQL query construction.

Invariants:
- Cursor is opaque base64url JSON.
- Cursor must include snapshot and fingerprint.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .errors import ValidationError

_CURSOR_VERSION = 3


@dataclass(frozen=True, slots=True)
class LoopCursor:
    snapshot_utc: str
    updated_at_utc: str
    captured_at_utc: str
    loop_id: int
    fingerprint: str


def fingerprint_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _format_for_sqlite(dt_iso: str) -> str:
    """Convert ISO timestamp to SQLite-compatible format for comparison.

    SQLite CURRENT_TIMESTAMP format: YYYY-MM-DD HH:MM:SS
    Input can be: YYYY-MM-DDTHH:MM:SS+00:00 or YYYY-MM-DDTHH:MM:SSZ
    """
    if "T" in dt_iso:
        dt_iso = dt_iso.replace("T", " ")
    if "+" in dt_iso:
        dt_iso = dt_iso.split("+")[0]
    if dt_iso.endswith("Z"):
        dt_iso = dt_iso[:-1]
    return dt_iso.strip()


def encode_cursor(cursor: LoopCursor) -> str:
    raw = {
        "v": _CURSOR_VERSION,
        "snapshot_utc": _format_for_sqlite(cursor.snapshot_utc),
        "updated_at_utc": _format_for_sqlite(cursor.updated_at_utc),
        "captured_at_utc": _format_for_sqlite(cursor.captured_at_utc),
        "loop_id": cursor.loop_id,
        "fingerprint": cursor.fingerprint,
    }
    packed = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def decode_cursor(token: str, *, expected_fingerprint: str) -> LoopCursor:
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValidationError("cursor", "invalid cursor") from exc

    version = payload.get("v")
    if version not in (1, 2, 3):
        raise ValidationError("cursor", "unsupported cursor version")
    if payload.get("fingerprint") != expected_fingerprint:
        raise ValidationError("cursor", "cursor does not match this query")

    try:
        return LoopCursor(
            snapshot_utc=str(payload["snapshot_utc"]),
            updated_at_utc=str(payload["updated_at_utc"]),
            captured_at_utc=(
                str(payload["captured_at_utc"])
                if version == 3 and "captured_at_utc" in payload
                else str(payload["updated_at_utc"])
            ),
            loop_id=int(payload["loop_id"]),
            fingerprint=str(payload["fingerprint"]),
        )
    except Exception as exc:
        raise ValidationError("cursor", "cursor missing required fields") from exc
