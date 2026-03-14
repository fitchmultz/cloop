"""Shared direct memory-management workflows.

Purpose:
    Centralize deterministic CRUD and query operations for durable memory entries
    so HTTP routes, the web UI, CLI commands, MCP tools, and chat/tool helpers
    reuse one canonical contract.

Responsibilities:
    - Validate direct memory create/update/query inputs
    - Delegate persistence to `storage/memory_store.py`
    - Raise Cloop-owned domain errors instead of transport-specific failures
    - Preserve explicit field-presence semantics for updates (for example, clearing `key`)

Non-scope:
    - Memory extraction/inference logic used by chat or enrichment
    - Transport-specific response models or rendering
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from . import typingx
from .constants import MEMORY_CONTENT_MAX, MEMORY_KEY_MAX
from .loops.errors import MemoryNotFoundError, ValidationError
from .schemas.memory import MemoryCategory, MemorySource
from .settings import Settings, get_settings
from .storage import memory_store

_ALLOWED_CREATE_FIELDS = frozenset({"key", "content", "category", "priority", "source", "metadata"})
_ALLOWED_UPDATE_FIELDS = _ALLOWED_CREATE_FIELDS


def _normalize_optional_key(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > MEMORY_KEY_MAX:
        raise ValidationError("key", f"exceeds maximum length of {MEMORY_KEY_MAX} characters")
    return normalized


def _normalize_content(value: Any) -> str:
    if value is None:
        raise ValidationError("content", "must not be empty")
    content = str(value)
    if not content.strip():
        raise ValidationError("content", "must not be empty")
    if len(content) > MEMORY_CONTENT_MAX:
        raise ValidationError(
            "content",
            f"exceeds maximum length of {MEMORY_CONTENT_MAX} characters",
        )
    return content


def _normalize_category(value: Any) -> str:
    raw_value = value.value if isinstance(value, MemoryCategory) else str(value)
    try:
        return MemoryCategory(raw_value).value
    except ValueError as exc:
        raise ValidationError("category", f"invalid category: {raw_value}") from exc


def _normalize_source(value: Any) -> str:
    raw_value = value.value if isinstance(value, MemorySource) else str(value)
    try:
        return MemorySource(raw_value).value
    except ValueError as exc:
        raise ValidationError("source", f"invalid source: {raw_value}") from exc


def _normalize_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("priority", "must be an integer") from exc
    if priority < 0 or priority > 100:
        raise ValidationError("priority", "must be between 0 and 100")
    return priority


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError("metadata", "must be an object")
    return dict(value)


def _normalize_limit(value: int) -> int:
    if value < 1:
        raise ValidationError("limit", "must be at least 1")
    return min(value, 100)


def _normalize_min_priority(value: int | None) -> int | None:
    if value is None:
        return None
    return _normalize_priority(value)


def _normalize_create_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    unknown_fields = sorted(set(payload) - _ALLOWED_CREATE_FIELDS)
    if unknown_fields:
        raise ValidationError("fields", f"unknown fields: {', '.join(unknown_fields)}")
    if "content" not in payload:
        raise ValidationError("content", "is required")
    return {
        "key": _normalize_optional_key(payload.get("key")),
        "content": _normalize_content(payload.get("content")),
        "category": _normalize_category(payload.get("category", MemoryCategory.FACT.value)),
        "priority": _normalize_priority(payload.get("priority", 0)),
        "source": _normalize_source(payload.get("source", MemorySource.USER_STATED.value)),
        "metadata": _normalize_metadata(payload.get("metadata")),
    }


def _normalize_update_payload(fields: Mapping[str, Any]) -> dict[str, Any]:
    unknown_fields = sorted(set(fields) - _ALLOWED_UPDATE_FIELDS)
    if unknown_fields:
        raise ValidationError("fields", f"unknown fields: {', '.join(unknown_fields)}")

    normalized: dict[str, Any] = {}
    if "key" in fields:
        normalized["key"] = _normalize_optional_key(fields.get("key"))
    if "content" in fields:
        normalized["content"] = _normalize_content(fields.get("content"))
    if "category" in fields:
        normalized["category"] = _normalize_category(fields.get("category"))
    if "priority" in fields:
        normalized["priority"] = _normalize_priority(fields.get("priority"))
    if "source" in fields:
        normalized["source"] = _normalize_source(fields.get("source"))
    if "metadata" in fields:
        normalized["metadata"] = _normalize_metadata(fields.get("metadata"))
    return normalized


@typingx.validate_io()
def list_memory_entries(
    *,
    category: str | MemoryCategory | None = None,
    source: str | MemorySource | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """List memory entries through the canonical direct-management contract."""
    settings = settings or get_settings()
    normalized_category = _normalize_category(category) if category is not None else None
    normalized_source = _normalize_source(source) if source is not None else None
    return memory_store.list_memory_entries(
        category=normalized_category,
        source=normalized_source,
        min_priority=_normalize_min_priority(min_priority),
        limit=_normalize_limit(limit),
        cursor=cursor,
        settings=settings,
        conn=conn,
    )


@typingx.validate_io()
def search_memory_entries(
    *,
    query: str,
    category: str | MemoryCategory | None = None,
    source: str | MemorySource | None = None,
    min_priority: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Search memory entries through the canonical direct-management contract."""
    settings = settings or get_settings()
    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("query", "must not be empty")
    normalized_category = _normalize_category(category) if category is not None else None
    normalized_source = _normalize_source(source) if source is not None else None
    return memory_store.search_memory_entries(
        query=normalized_query,
        category=normalized_category,
        source=normalized_source,
        min_priority=_normalize_min_priority(min_priority),
        limit=_normalize_limit(limit),
        cursor=cursor,
        settings=settings,
        conn=conn,
    )


@typingx.validate_io()
def get_memory_entry(
    *,
    entry_id: int,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Fetch one memory entry or raise the canonical not-found error."""
    settings = settings or get_settings()
    entry = memory_store.get_memory_entry(entry_id, settings=settings, conn=conn)
    if entry is None:
        raise MemoryNotFoundError(entry_id)
    return entry


@typingx.validate_io()
def create_memory_entry(
    *,
    payload: Mapping[str, Any],
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Create a memory entry through the canonical direct-management contract."""
    settings = settings or get_settings()
    normalized = _normalize_create_payload(payload)
    return memory_store.create_memory_entry(settings=settings, conn=conn, **normalized)


@typingx.validate_io()
def update_memory_entry(
    *,
    entry_id: int,
    fields: Mapping[str, Any],
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Update a memory entry while preserving explicit field presence semantics."""
    settings = settings or get_settings()
    get_memory_entry(entry_id=entry_id, settings=settings, conn=conn)
    normalized_fields = _normalize_update_payload(fields)
    updated = memory_store.update_memory_entry(
        entry_id,
        fields=normalized_fields,
        settings=settings,
        conn=conn,
    )
    if updated is None:
        raise MemoryNotFoundError(entry_id)
    return updated


@typingx.validate_io()
def delete_memory_entry(
    *,
    entry_id: int,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Delete one memory entry and return a canonical mutation payload."""
    settings = settings or get_settings()
    deleted = memory_store.delete_memory_entry(entry_id, settings=settings, conn=conn)
    if not deleted:
        raise MemoryNotFoundError(entry_id)
    return {"entry_id": entry_id, "deleted": True}
