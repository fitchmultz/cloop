"""Saved review action workflow operations.

Purpose:
    Provide shared CRUD operations for durable relationship and enrichment
    review action presets.

Responsibilities:
    - Create, list, fetch, update, and delete relationship review action presets
    - Create, list, fetch, update, and delete enrichment review action presets
    - Enforce normalized action semantics before persistence

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Saved review action orchestration only
    - No queue snapshotting or session action execution

Usage:
    Imported by CLI, HTTP, MCP, and the review workflow facade.

Invariants/Assumptions:
    - Action names are unique per persisted preset row
    - Enrichment reject presets cannot carry apply-field filters
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from ... import typingx
from .. import repo
from ..errors import ResourceNotFoundError, ValidationError
from .shared import (
    _enrichment_action_payload,
    _normalize_name,
    _relationship_action_payload,
    _require_enrichment_action_row,
    _require_relationship_action_row,
    _validate_enrichment_action,
    _validate_relationship_action,
)


@typingx.validate_io()
def create_relationship_review_action(
    *,
    name: str,
    action_type: str,
    relationship_type: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    normalized_name = _normalize_name(name, field="name")
    normalized_action, normalized_relationship_type = _validate_relationship_action(
        action_type=action_type,
        relationship_type=relationship_type,
    )
    try:
        with conn:
            row = repo.create_review_action_preset(
                name=normalized_name,
                review_kind="relationship",
                action_type=normalized_action,
                config_json={"relationship_type": normalized_relationship_type},
                description=description,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError("name", f"review action '{normalized_name}' already exists") from None
    return _relationship_action_payload(row)


@typingx.validate_io()
def list_relationship_review_actions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _relationship_action_payload(row)
        for row in repo.list_review_action_presets(review_kind="relationship", conn=conn)
    ]


@typingx.validate_io()
def get_relationship_review_action(
    *, action_preset_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    return _relationship_action_payload(
        _require_relationship_action_row(action_preset_id=action_preset_id, conn=conn)
    )


@typingx.validate_io()
def update_relationship_review_action(
    *,
    action_preset_id: int,
    name: str | None,
    action_type: str | None,
    relationship_type: str | None,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = _require_relationship_action_row(action_preset_id=action_preset_id, conn=conn)
    current = _relationship_action_payload(row)
    normalized_name = _normalize_name(name, field="name") if name is not None else None
    normalized_action, normalized_relationship_type = _validate_relationship_action(
        action_type=action_type or str(current["action_type"]),
        relationship_type=relationship_type or str(current["relationship_type"]),
    )
    try:
        with conn:
            updated = repo.update_review_action_preset(
                action_preset_id=action_preset_id,
                name=normalized_name,
                action_type=normalized_action,
                config_json={"relationship_type": normalized_relationship_type},
                description=description,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name",
            f"review action '{normalized_name or current['name']}' already exists",
        ) from None
    if updated is None:
        raise ResourceNotFoundError(
            "review action",
            f"Relationship review action not found: {action_preset_id}",
        )
    return _relationship_action_payload(updated)


@typingx.validate_io()
def delete_relationship_review_action(
    *, action_preset_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    _require_relationship_action_row(action_preset_id=action_preset_id, conn=conn)
    with conn:
        repo.delete_review_action_preset(action_preset_id=action_preset_id, conn=conn)
    return {"deleted": True, "action_preset_id": action_preset_id}


@typingx.validate_io()
def create_enrichment_review_action(
    *,
    name: str,
    action_type: str,
    fields: Sequence[str] | None,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    normalized_name = _normalize_name(name, field="name")
    normalized_action, normalized_fields = _validate_enrichment_action(
        action_type=action_type,
        fields=fields,
    )
    try:
        with conn:
            row = repo.create_review_action_preset(
                name=normalized_name,
                review_kind="enrichment",
                action_type=normalized_action,
                config_json={"fields": normalized_fields},
                description=description,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError("name", f"review action '{normalized_name}' already exists") from None
    return _enrichment_action_payload(row)


@typingx.validate_io()
def list_enrichment_review_actions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _enrichment_action_payload(row)
        for row in repo.list_review_action_presets(review_kind="enrichment", conn=conn)
    ]


@typingx.validate_io()
def get_enrichment_review_action(
    *, action_preset_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    return _enrichment_action_payload(
        _require_enrichment_action_row(action_preset_id=action_preset_id, conn=conn)
    )


@typingx.validate_io()
def update_enrichment_review_action(
    *,
    action_preset_id: int,
    name: str | None,
    action_type: str | None,
    fields: Sequence[str] | None,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = _require_enrichment_action_row(action_preset_id=action_preset_id, conn=conn)
    current = _enrichment_action_payload(row)
    normalized_name = _normalize_name(name, field="name") if name is not None else None
    normalized_action, normalized_fields = _validate_enrichment_action(
        action_type=action_type or str(current["action_type"]),
        fields=fields if fields is not None else current.get("fields"),
    )
    try:
        with conn:
            updated = repo.update_review_action_preset(
                action_preset_id=action_preset_id,
                name=normalized_name,
                action_type=normalized_action,
                config_json={"fields": normalized_fields},
                description=description,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name",
            f"review action '{normalized_name or current['name']}' already exists",
        ) from None
    if updated is None:
        raise ResourceNotFoundError(
            "review action",
            f"Enrichment review action not found: {action_preset_id}",
        )
    return _enrichment_action_payload(updated)


@typingx.validate_io()
def delete_enrichment_review_action(
    *, action_preset_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    _require_enrichment_action_row(action_preset_id=action_preset_id, conn=conn)
    with conn:
        repo.delete_review_action_preset(action_preset_id=action_preset_id, conn=conn)
    return {"deleted": True, "action_preset_id": action_preset_id}


__all__ = [
    "create_relationship_review_action",
    "list_relationship_review_actions",
    "get_relationship_review_action",
    "update_relationship_review_action",
    "delete_relationship_review_action",
    "create_enrichment_review_action",
    "list_enrichment_review_actions",
    "get_enrichment_review_action",
    "update_enrichment_review_action",
    "delete_enrichment_review_action",
]
