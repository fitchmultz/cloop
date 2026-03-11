"""Saved view service functions for loops.

Purpose:
    Own saved-view CRUD and application behavior so view-specific business
    rules do not live in the general loop service module.

Responsibilities:
    - Create, list, read, update, and delete saved views
    - Apply saved views to loop queries with offset and cursor pagination
    - Validate missing-view cases consistently

Non-scope:
    - Generic loop lifecycle operations
    - HTTP, CLI, or MCP transport handling
    - Raw SQL persistence details beyond repo delegation

Invariants/Assumptions:
    - Transaction ownership stays with this module for view mutations
    - View queries are executed through the canonical query + enrichment path
    - Missing views surface as ValidationError on the `view_id` field
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import typingx
from . import repo
from .errors import ValidationError
from .pagination import build_next_cursor, prepare_cursor_state
from .write_ops import _enrich_records_batch


def _get_required_view(*, view_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Load a saved view or raise the canonical validation error."""
    view = repo.get_loop_view(view_id=view_id, conn=conn)
    if view is None:
        raise ValidationError("view_id", f"view {view_id} not found")
    return view


@typingx.validate_io()
def create_loop_view(
    *,
    name: str,
    query: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a new saved view within a caller-owned transaction."""
    with conn:
        return repo.create_loop_view(
            name=name,
            query=query,
            description=description,
            conn=conn,
        )


@typingx.validate_io()
def list_loop_views(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all saved views ordered by name."""
    return repo.list_loop_views(conn=conn)


@typingx.validate_io()
def get_loop_view(*, view_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Get a saved view by ID."""
    return _get_required_view(view_id=view_id, conn=conn)


@typingx.validate_io()
def update_loop_view(
    *,
    view_id: int,
    name: str | None = None,
    query: str | None = None,
    description: str | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a saved view within a caller-owned transaction."""
    with conn:
        return repo.update_loop_view(
            view_id=view_id,
            name=name,
            query=query,
            description=description,
            conn=conn,
        )


@typingx.validate_io()
def delete_loop_view(*, view_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a saved view within a caller-owned transaction."""
    with conn:
        deleted = repo.delete_loop_view(view_id=view_id, conn=conn)
    if not deleted:
        raise ValidationError("view_id", f"view {view_id} not found")
    return True


@typingx.validate_io()
def apply_loop_view(
    *,
    view_id: int,
    limit: int,
    offset: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Apply a saved view and return matching loops with offset pagination."""
    view = _get_required_view(view_id=view_id, conn=conn)
    records = repo.search_loops_by_query(
        query=view["query"],
        limit=limit,
        offset=offset,
        conn=conn,
    )
    return {
        "view": view,
        "query": view["query"],
        "limit": limit,
        "offset": offset,
        "items": _enrich_records_batch(records, conn=conn),
    }


@typingx.validate_io()
def apply_loop_view_page(
    *,
    view_id: int,
    limit: int,
    cursor: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Apply a saved view with cursor pagination."""
    view = _get_required_view(view_id=view_id, conn=conn)
    query = view["query"]
    state = prepare_cursor_state(
        fingerprint_payload_dict={"tool": "loop.view.apply", "view_id": view_id, "query": query},
        cursor=cursor,
    )
    records = repo.search_loops_by_query_cursor(
        query=query,
        limit=limit,
        snapshot_utc=state.snapshot_utc,
        cursor_anchor=state.cursor_anchor,
        conn=conn,
    )
    next_cursor = build_next_cursor(
        records=records,
        limit=limit,
        snapshot_utc=state.snapshot_utc,
        fingerprint=state.fingerprint,
    )
    return {
        "view": view,
        "query": query,
        "limit": limit,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "items": _enrich_records_batch(records[:limit], conn=conn),
    }
