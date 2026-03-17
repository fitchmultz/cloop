"""Shared tool validation helpers.

Purpose:
    Centralize common validation and schema-normalization helpers for tools.

Responsibilities:
    - Validate required tool arguments
    - Parse raw tool-argument payloads into dictionaries
    - Normalize JSON Schema objects for stricter provider validation

Scope:
    - Generic tool-facing validation only

Non-scope:
    - Domain-specific business validation
    - Tool execution or registry assembly

Usage:
    - Imported by internal tool executor and registry modules

Invariants/Assumptions:
    - Missing required fields raise `ValidationError`
    - Raw tool arguments arrive as either dicts or JSON strings
    - Object schemas are closed recursively with `additionalProperties=False`
"""

from __future__ import annotations

import json
from typing import Any

from ..loops.errors import ValidationError


def _require_fields(payload: dict[str, Any], *fields: str) -> None:
    """Require that the specified keys are present with non-`None` values."""
    missing = [field for field in fields if payload.get(field) is None]
    if missing:
        raise ValidationError("fields", f"missing required: {', '.join(missing)}")


def _closed_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Close object schemas recursively for stricter tool validation."""
    normalized = dict(schema)
    schema_type = normalized.get("type")
    if schema_type == "object":
        properties = normalized.get("properties") or {}
        normalized["properties"] = {
            key: _closed_object_schema(value) if isinstance(value, dict) else value
            for key, value in properties.items()
        }
        normalized.setdefault("additionalProperties", False)
    elif schema_type == "array":
        items = normalized.get("items")
        if isinstance(items, dict):
            normalized["items"] = _closed_object_schema(items)
    return normalized


def normalize_tool_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse raw tool-call arguments into a dictionary."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("arguments", "invalid JSON") from exc
    if isinstance(parsed, dict):
        return parsed
    raise ValidationError("arguments", "invalid JSON")
