"""Shared idempotency primitives for HTTP and MCP loop mutations.

Purpose:
    Provide deterministic replay/mismatch semantics for write retries.

Responsibilities:
    - Canonical request hashing
    - DB-backed claim/replay/finalize flow
    - TTL cleanup trigger

Non-scope:
    - HTTP-specific handling (see handlers.py)
    - Business logic validation (see loops/service.py)

Non-scope:
- Business mutation logic itself

Invariants:
- Same (scope, key, hash) replays prior response
- Same (scope, key) with different hash is conflict
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from .loops.models import format_utc_datetime, utc_now


@dataclass(frozen=True)
class IdempotencyReplay:
    status_code: int
    response_body: dict[str, Any]


@dataclass(frozen=True)
class IdempotencyClaim:
    is_new: bool
    replay: IdempotencyReplay | None = None


class IdempotencyConflictError(ValueError):
    """Raised when same idempotency key is reused with different payload."""

    pass


def canonical_request_hash(payload: Mapping[str, Any]) -> str:
    """Generate canonical SHA-256 hash of request payload.

    Args:
        payload: Request payload dictionary

    Returns:
        Hex-encoded SHA-256 hash of canonical JSON representation
    """
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def expiry_timestamp(ttl_seconds: int) -> str:
    """Generate ISO8601 expiry timestamp from TTL.

    Args:
        ttl_seconds: Time-to-live in seconds

    Returns:
        ISO8601 formatted expiry timestamp
    """
    return format_utc_datetime(utc_now() + timedelta(seconds=ttl_seconds))


def normalize_idempotency_key(key: str, max_length: int = 255) -> str:
    """Normalize and validate idempotency key.

    Args:
        key: Raw idempotency key string
        max_length: Maximum allowed key length

    Returns:
        Stripped key string

    Raises:
        ValueError: If key is empty or exceeds max length
    """
    normalized = key.strip()
    if not normalized:
        raise ValueError("idempotency_key cannot be empty")
    if len(normalized) > max_length:
        raise ValueError(f"idempotency_key exceeds max length of {max_length}")
    return normalized


def build_http_scope(method: str, path: str) -> str:
    """Build scope string for HTTP requests.

    Args:
        method: HTTP method (POST, PATCH, etc.)
        path: Request path

    Returns:
        Scope string like "http:POST:/loops/capture"
    """
    return f"http:{method.upper()}:{path}"


def build_mcp_scope(tool_name: str) -> str:
    """Build scope string for MCP tool calls.

    Args:
        tool_name: MCP tool name (e.g., "loop.create")

    Returns:
        Scope string like "mcp:loop.create"
    """
    return f"mcp:{tool_name}"
