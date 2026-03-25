"""Review workflow session snapshot helpers.

Purpose:
    Materialize durable relationship and enrichment review sessions into
    queue snapshots with stable cursor behavior.

Responsibilities:
    - Choose and persist the current loop cursor as queues change
    - Build relationship-review session snapshots from filtered candidate queues
    - Build enrichment-review session snapshots from pending follow-up queues
    - Move review cursors to adjacent queued items

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Session snapshot shaping only
    - No saved action CRUD or review decision execution

Usage:
    Imported by review workflow session and execution modules.

Invariants/Assumptions:
    - Session cursor updates are persisted only when the effective loop changes
    - Queue snapshots preserve previous ordering when possible
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from .. import enrichment_review, relationship_review, repo
from ..errors import ResourceNotFoundError, ValidationError
from .shared import (
    ReviewSessionMoveDirection,
    _enrichment_session_payload,
    _relationship_session_payload,
)


def _candidate_loop_ids(items: Sequence[Mapping[str, Any]]) -> list[int]:
    return [int(item["loop"]["id"]) for item in items]


def _choose_current_loop_id(
    *,
    items: Sequence[Mapping[str, Any]],
    stored_current_loop_id: int | None,
    previous_order: Sequence[int] | None = None,
    previous_index: int | None = None,
) -> int | None:
    item_ids = _candidate_loop_ids(items)
    if not item_ids:
        return None
    if stored_current_loop_id in item_ids:
        return stored_current_loop_id
    if previous_order is not None and previous_index is not None:
        for loop_id in previous_order[previous_index + 1 :]:
            if loop_id in item_ids:
                return loop_id
        for loop_id in previous_order[: previous_index + 1]:
            if loop_id in item_ids:
                return loop_id
    return item_ids[0]


def _persist_session_cursor(
    *,
    session_row: dict[str, Any],
    current_loop_id: int | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    stored_current = session_row.get("current_loop_id")
    if stored_current == current_loop_id:
        return session_row
    updated = repo.update_review_session(
        session_id=int(session_row["id"]),
        current_loop_id=current_loop_id,
        conn=conn,
    )
    if updated is None:
        raise ResourceNotFoundError(
            "review session",
            f"Review session not found: {session_row['id']}",
        )
    return updated


def _build_review_session_rerun_action(
    *,
    session: Mapping[str, Any],
    review_focus: str,
) -> dict[str, Any]:
    description = (
        f"Land back in the saved {review_focus} queue with refreshed items and trust copy."
    )
    may_vary = (
        [
            "Queue size and cursor target",
            "Candidate ordering and similarity scores",
            "Strategy path or alternate selector choice behind refreshed AI metadata",
        ]
        if review_focus == "relationship"
        else [
            "Queue size and cursor target",
            "Suggestion ranking or clarification pressure",
            "Strategy path or alternate selector choice behind refreshed AI metadata",
        ]
    )
    strategy_summary = (
        "Reuse the saved review query and rebuild the current relationship queue from live "
        "similarity state."
        if review_focus == "relationship"
        else (
            "Reuse the saved review query and rebuild the current enrichment queue from live "
            "suggestions and clarifications."
        )
    )
    return {
        "label": "Refresh queue" if review_focus == "relationship" else "Refresh enrichment",
        "description": description,
        "rerun": {
            "kind": "review_session",
            "review_focus": review_focus,
            "session_id": int(session["id"]),
            "session_name": str(session["name"]),
        },
        "contract": {
            "mode": "refresh",
            "provenance_label": f"{session['name']} · {session['query']}",
            "freshness_label": f"Updated {session['updated_at_utc']}",
            "strategy_summary": strategy_summary,
            "strict_invariants": [
                "Same saved review session identity",
                f"Same {review_focus} review kind and saved query",
                "Same saved-session landing surface after refresh",
            ],
            "may_vary": may_vary,
            "post_run": {
                "summary": description,
                "location": {
                    "state": "decide",
                    "review_focus": review_focus,
                    "session_id": int(session["id"]),
                },
            },
        },
    }


def _build_relationship_session_snapshot(
    *,
    session_row: dict[str, Any],
    conn: sqlite3.Connection,
    settings: Any,
    previous_order: Sequence[int] | None = None,
    previous_index: int | None = None,
) -> dict[str, Any]:
    session = _relationship_session_payload(session_row)
    queue = relationship_review.list_relationship_review_queue_for_query(
        query=session["query"],
        relationship_kind=session["relationship_kind"],
        limit=session["item_limit"],
        candidate_limit=session["candidate_limit"],
        conn=conn,
        settings=settings,
    )
    current_loop_id = _choose_current_loop_id(
        items=queue["items"],
        stored_current_loop_id=session["current_loop_id"],
        previous_order=previous_order,
        previous_index=previous_index,
    )
    session_row = _persist_session_cursor(
        session_row=session_row, current_loop_id=current_loop_id, conn=conn
    )
    session = _relationship_session_payload(session_row)
    current_index = next(
        (
            index
            for index, item in enumerate(queue["items"])
            if int(item["loop"]["id"]) == current_loop_id
        ),
        None,
    )
    current_item = queue["items"][current_index] if current_index is not None else None
    return {
        "session": session,
        "loop_count": queue["loop_count"],
        "current_index": current_index,
        "current_item": current_item,
        "items": queue["items"],
        "rerun_action": _build_review_session_rerun_action(
            session=session,
            review_focus="relationship",
        ),
    }


def _build_enrichment_session_snapshot(
    *,
    session_row: dict[str, Any],
    conn: sqlite3.Connection,
    previous_order: Sequence[int] | None = None,
    previous_index: int | None = None,
) -> dict[str, Any]:
    session = _enrichment_session_payload(session_row)
    queue = enrichment_review.list_enrichment_review_queue(
        query=session["query"],
        pending_kind=session["pending_kind"],
        limit=session["item_limit"],
        suggestion_limit=session["suggestion_limit"],
        clarification_limit=session["clarification_limit"],
        conn=conn,
    )
    current_loop_id = _choose_current_loop_id(
        items=queue["items"],
        stored_current_loop_id=session["current_loop_id"],
        previous_order=previous_order,
        previous_index=previous_index,
    )
    session_row = _persist_session_cursor(
        session_row=session_row, current_loop_id=current_loop_id, conn=conn
    )
    session = _enrichment_session_payload(session_row)
    current_index = next(
        (
            index
            for index, item in enumerate(queue["items"])
            if int(item["loop"]["id"]) == current_loop_id
        ),
        None,
    )
    current_item = queue["items"][current_index] if current_index is not None else None
    return {
        "session": session,
        "loop_count": queue["loop_count"],
        "current_index": current_index,
        "current_item": current_item,
        "items": queue["items"],
        "rerun_action": _build_review_session_rerun_action(
            session=session,
            review_focus="enrichment",
        ),
    }


def _move_session_loop_id(
    *,
    items: Sequence[Mapping[str, Any]],
    current_index: int | None,
    direction: ReviewSessionMoveDirection,
    field_name: str,
) -> int:
    if not items:
        raise ValidationError(field_name, "review session has no queued items")
    if current_index is None:
        raise ValidationError(field_name, "review session has no current item")

    step = 1 if direction == "next" else -1
    target_index = current_index + step
    if target_index < 0 or target_index >= len(items):
        raise ValidationError(field_name, f"no {direction} item available in this review session")
    return int(items[target_index]["loop"]["id"])


__all__ = [
    "_candidate_loop_ids",
    "_choose_current_loop_id",
    "_persist_session_cursor",
    "_build_relationship_session_snapshot",
    "_build_enrichment_session_snapshot",
    "_move_session_loop_id",
]
