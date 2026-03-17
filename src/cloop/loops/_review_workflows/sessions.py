"""Saved review session workflow operations.

Purpose:
    Provide shared CRUD and cursor movement operations for durable
    relationship and enrichment review sessions.

Responsibilities:
    - Create, list, fetch, update, move, and delete relationship review sessions
    - Create, list, fetch, update, move, and delete enrichment review sessions
    - Materialize durable session snapshots after persistence changes

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Saved review session orchestration only
    - No review decision execution within queued items

Usage:
    Imported by CLI, HTTP, MCP, planning execution, and the review facade.

Invariants/Assumptions:
    - Session names are unique within each review kind
    - Session snapshots stay transport-agnostic and preserve queued state
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ... import typingx
from .. import repo
from ..errors import ResourceNotFoundError, ValidationError
from .shared import (
    _UNSET,
    _enrichment_session_payload,
    _ensure_loop_exists,
    _normalize_name,
    _relationship_session_payload,
    _require_enrichment_session_row,
    _require_relationship_session_row,
    _resolved_optional_loop_id,
    _validate_enrichment_session_options,
    _validate_move_direction,
    _validate_query,
    _validate_relationship_session_options,
)
from .snapshots import (
    _build_enrichment_session_snapshot,
    _build_relationship_session_snapshot,
    _move_session_loop_id,
)


@typingx.validate_io()
def create_relationship_review_session(
    *,
    name: str,
    query: str,
    relationship_kind: str,
    candidate_limit: int,
    item_limit: int,
    current_loop_id: int | None,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    normalized_name = _normalize_name(name, field="name")
    normalized_query = _validate_query(query)
    options = _validate_relationship_session_options(
        {
            "relationship_kind": relationship_kind,
            "candidate_limit": candidate_limit,
            "item_limit": item_limit,
        }
    )
    _ensure_loop_exists(loop_id=current_loop_id, conn=conn)
    try:
        with conn:
            row = repo.create_review_session(
                name=normalized_name,
                review_kind="relationship",
                query=normalized_query,
                options_json=options,
                current_loop_id=current_loop_id,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name", f"review session '{normalized_name}' already exists"
        ) from None
    return _build_relationship_session_snapshot(session_row=row, conn=conn, settings=settings)


@typingx.validate_io()
def list_relationship_review_sessions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _relationship_session_payload(row)
        for row in repo.list_review_sessions(review_kind="relationship", conn=conn)
    ]


@typingx.validate_io()
def get_relationship_review_session(
    *,
    session_id: int,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    return _build_relationship_session_snapshot(
        session_row=_require_relationship_session_row(session_id=session_id, conn=conn),
        conn=conn,
        settings=settings,
    )


@typingx.validate_io()
def move_relationship_review_session(
    *,
    session_id: int,
    direction: str,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_relationship_session_row(session_id=session_id, conn=conn)
    normalized_direction = _validate_move_direction(direction)
    snapshot = _build_relationship_session_snapshot(
        session_row=session_row,
        conn=conn,
        settings=settings,
    )
    target_loop_id = _move_session_loop_id(
        items=snapshot["items"],
        current_index=snapshot["current_index"],
        direction=normalized_direction,
        field_name="direction",
    )
    with conn:
        updated = repo.update_review_session(
            session_id=session_id,
            current_loop_id=target_loop_id,
            conn=conn,
        )
    if updated is None:
        raise ResourceNotFoundError(
            "review session",
            f"Relationship review session not found: {session_id}",
        )
    return _build_relationship_session_snapshot(session_row=updated, conn=conn, settings=settings)


@typingx.validate_io()
def update_relationship_review_session(
    *,
    session_id: int,
    name: str | None,
    query: str | None,
    relationship_kind: str | None,
    candidate_limit: int | None,
    item_limit: int | None,
    current_loop_id: int | None | object,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    row = _require_relationship_session_row(session_id=session_id, conn=conn)
    current = _relationship_session_payload(row)
    normalized_name = _normalize_name(name, field="name") if name is not None else None
    normalized_query = _validate_query(query) if query is not None else None
    options = _validate_relationship_session_options(
        {
            "relationship_kind": relationship_kind or current["relationship_kind"],
            "candidate_limit": (
                candidate_limit if candidate_limit is not None else current["candidate_limit"]
            ),
            "item_limit": item_limit if item_limit is not None else current["item_limit"],
        }
    )
    if current_loop_id is not _UNSET:
        _ensure_loop_exists(loop_id=_resolved_optional_loop_id(current_loop_id), conn=conn)
    try:
        with conn:
            updated = repo.update_review_session(
                session_id=session_id,
                name=normalized_name,
                query=normalized_query,
                options_json=options,
                current_loop_id=current_loop_id,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name",
            f"review session '{normalized_name or current['name']}' already exists",
        ) from None
    if updated is None:
        raise ResourceNotFoundError(
            "review session",
            f"Relationship review session not found: {session_id}",
        )
    return _build_relationship_session_snapshot(session_row=updated, conn=conn, settings=settings)


@typingx.validate_io()
def delete_relationship_review_session(
    *, session_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    _require_relationship_session_row(session_id=session_id, conn=conn)
    with conn:
        repo.delete_review_session(session_id=session_id, conn=conn)
    return {"deleted": True, "session_id": session_id}


@typingx.validate_io()
def create_enrichment_review_session(
    *,
    name: str,
    query: str,
    pending_kind: str,
    suggestion_limit: int,
    clarification_limit: int,
    item_limit: int,
    current_loop_id: int | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    normalized_name = _normalize_name(name, field="name")
    normalized_query = _validate_query(query)
    options = _validate_enrichment_session_options(
        {
            "pending_kind": pending_kind,
            "suggestion_limit": suggestion_limit,
            "clarification_limit": clarification_limit,
            "item_limit": item_limit,
        }
    )
    _ensure_loop_exists(loop_id=current_loop_id, conn=conn)
    try:
        with conn:
            row = repo.create_review_session(
                name=normalized_name,
                review_kind="enrichment",
                query=normalized_query,
                options_json=options,
                current_loop_id=current_loop_id,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name", f"review session '{normalized_name}' already exists"
        ) from None
    return _build_enrichment_session_snapshot(session_row=row, conn=conn)


@typingx.validate_io()
def list_enrichment_review_sessions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _enrichment_session_payload(row)
        for row in repo.list_review_sessions(review_kind="enrichment", conn=conn)
    ]


@typingx.validate_io()
def get_enrichment_review_session(
    *,
    session_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    return _build_enrichment_session_snapshot(
        session_row=_require_enrichment_session_row(session_id=session_id, conn=conn),
        conn=conn,
    )


@typingx.validate_io()
def move_enrichment_review_session(
    *,
    session_id: int,
    direction: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    session_row = _require_enrichment_session_row(session_id=session_id, conn=conn)
    normalized_direction = _validate_move_direction(direction)
    snapshot = _build_enrichment_session_snapshot(session_row=session_row, conn=conn)
    target_loop_id = _move_session_loop_id(
        items=snapshot["items"],
        current_index=snapshot["current_index"],
        direction=normalized_direction,
        field_name="direction",
    )
    with conn:
        updated = repo.update_review_session(
            session_id=session_id,
            current_loop_id=target_loop_id,
            conn=conn,
        )
    if updated is None:
        raise ResourceNotFoundError(
            "review session",
            f"Enrichment review session not found: {session_id}",
        )
    return _build_enrichment_session_snapshot(session_row=updated, conn=conn)


@typingx.validate_io()
def update_enrichment_review_session(
    *,
    session_id: int,
    name: str | None,
    query: str | None,
    pending_kind: str | None,
    suggestion_limit: int | None,
    clarification_limit: int | None,
    item_limit: int | None,
    current_loop_id: int | None | object,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = _require_enrichment_session_row(session_id=session_id, conn=conn)
    current = _enrichment_session_payload(row)
    normalized_name = _normalize_name(name, field="name") if name is not None else None
    normalized_query = _validate_query(query) if query is not None else None
    options = _validate_enrichment_session_options(
        {
            "pending_kind": pending_kind or current["pending_kind"],
            "suggestion_limit": (
                suggestion_limit if suggestion_limit is not None else current["suggestion_limit"]
            ),
            "clarification_limit": (
                clarification_limit
                if clarification_limit is not None
                else current["clarification_limit"]
            ),
            "item_limit": item_limit if item_limit is not None else current["item_limit"],
        }
    )
    if current_loop_id is not _UNSET:
        _ensure_loop_exists(loop_id=_resolved_optional_loop_id(current_loop_id), conn=conn)
    try:
        with conn:
            updated = repo.update_review_session(
                session_id=session_id,
                name=normalized_name,
                query=normalized_query,
                options_json=options,
                current_loop_id=current_loop_id,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name",
            f"review session '{normalized_name or current['name']}' already exists",
        ) from None
    if updated is None:
        raise ResourceNotFoundError(
            "review session",
            f"Enrichment review session not found: {session_id}",
        )
    return _build_enrichment_session_snapshot(session_row=updated, conn=conn)


@typingx.validate_io()
def delete_enrichment_review_session(
    *, session_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    _require_enrichment_session_row(session_id=session_id, conn=conn)
    with conn:
        repo.delete_review_session(session_id=session_id, conn=conn)
    return {"deleted": True, "session_id": session_id}


__all__ = [
    "create_relationship_review_session",
    "list_relationship_review_sessions",
    "get_relationship_review_session",
    "move_relationship_review_session",
    "update_relationship_review_session",
    "delete_relationship_review_session",
    "create_enrichment_review_session",
    "list_enrichment_review_sessions",
    "get_enrichment_review_session",
    "move_enrichment_review_session",
    "update_enrichment_review_session",
    "delete_enrichment_review_session",
]
