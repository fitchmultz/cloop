"""Shared saved review actions and session-preserving review workflows.

Purpose:
    Centralize saved action presets plus durable, filtered operator review sessions
    so HTTP routes, CLI commands, MCP tools, and the web UI share one contract
    for relationship review and enrichment follow-up.

Responsibilities:
    - Persist and validate saved review action presets
    - Persist and materialize relationship-review sessions
    - Persist and materialize enrichment-review sessions
    - Execute saved or inline review actions within a session and return the
      refreshed session snapshot
    - Keep session cursor/current-loop state stable as worklists change

Non-scope:
    - Raw SQL persistence details (see repo.py)
    - Transport-specific request/response shaping
    - Relationship scoring semantics (see relationship_review.py)
    - Suggestion/clarification business rules (see enrichment_review.py)
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from .. import typingx
from . import enrichment_review, relationship_review, repo
from .errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from .query import parse_loop_query

RelationshipActionType = Literal["confirm", "dismiss"]
RelationshipTargetType = Literal["suggested", "duplicate", "related"]
EnrichmentActionType = Literal["apply", "reject"]
RelationshipReviewKind = Literal["all", "duplicate", "related"]
EnrichmentPendingKind = Literal["all", "suggestions", "clarifications"]

_UNSET = object()

_DEFAULT_RELATIONSHIP_SESSION_OPTIONS = {
    "relationship_kind": "all",
    "candidate_limit": 3,
    "item_limit": 25,
}
_DEFAULT_ENRICHMENT_SESSION_OPTIONS = {
    "pending_kind": "all",
    "suggestion_limit": 3,
    "clarification_limit": 3,
    "item_limit": 25,
}


def _normalize_name(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError(field, f"{field.replace('_', ' ')} must not be empty")
    return normalized


def _validate_query(query: str) -> str:
    parse_loop_query(query)
    return query


def _ensure_loop_exists(*, loop_id: int | None, conn: sqlite3.Connection) -> None:
    if loop_id is None:
        return
    if repo.read_loop(loop_id=loop_id, conn=conn) is None:
        raise LoopNotFoundError(loop_id)


def _resolved_optional_loop_id(value: int | None | object) -> int | None:
    if value is _UNSET:
        raise RuntimeError("review_session_loop_id_unset")
    if value is None or isinstance(value, int):
        return value
    raise TypeError("review session current_loop_id must be int | None")


def _relationship_action_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    config = json.loads(str(row["config_json"])) if row.get("config_json") else {}
    relationship_type = str(config.get("relationship_type") or "suggested")
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "review_kind": "relationship",
        "action_type": str(row["action_type"]),
        "relationship_type": relationship_type,
        "description": row.get("description"),
        "created_at_utc": str(row["created_at"]),
        "updated_at_utc": str(row["updated_at"]),
    }


def _enrichment_action_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    config = json.loads(str(row["config_json"])) if row.get("config_json") else {}
    fields = config.get("fields")
    normalized_fields = [str(field) for field in fields] if isinstance(fields, list) else None
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "review_kind": "enrichment",
        "action_type": str(row["action_type"]),
        "fields": normalized_fields,
        "description": row.get("description"),
        "created_at_utc": str(row["created_at"]),
        "updated_at_utc": str(row["updated_at"]),
    }


def _relationship_session_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    options = json.loads(str(row["options_json"])) if row.get("options_json") else {}
    normalized = _validate_relationship_session_options(options)
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "review_kind": "relationship",
        "query": str(row["query"]),
        "relationship_kind": normalized["relationship_kind"],
        "candidate_limit": normalized["candidate_limit"],
        "item_limit": normalized["item_limit"],
        "current_loop_id": (
            int(row["current_loop_id"]) if row.get("current_loop_id") is not None else None
        ),
        "created_at_utc": str(row["created_at"]),
        "updated_at_utc": str(row["updated_at"]),
    }


def _enrichment_session_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    options = json.loads(str(row["options_json"])) if row.get("options_json") else {}
    normalized = _validate_enrichment_session_options(options)
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "review_kind": "enrichment",
        "query": str(row["query"]),
        "pending_kind": normalized["pending_kind"],
        "suggestion_limit": normalized["suggestion_limit"],
        "clarification_limit": normalized["clarification_limit"],
        "item_limit": normalized["item_limit"],
        "current_loop_id": (
            int(row["current_loop_id"]) if row.get("current_loop_id") is not None else None
        ),
        "created_at_utc": str(row["created_at"]),
        "updated_at_utc": str(row["updated_at"]),
    }


def _validate_relationship_action(
    *,
    action_type: str,
    relationship_type: str,
) -> tuple[RelationshipActionType, RelationshipTargetType]:
    if action_type == "confirm":
        normalized_action: RelationshipActionType = "confirm"
    elif action_type == "dismiss":
        normalized_action = "dismiss"
    else:
        raise ValidationError("action_type", "must be confirm or dismiss")

    if relationship_type == "suggested":
        normalized_relationship_type: RelationshipTargetType = "suggested"
    elif relationship_type == "duplicate":
        normalized_relationship_type = "duplicate"
    elif relationship_type == "related":
        normalized_relationship_type = "related"
    else:
        raise ValidationError("relationship_type", "must be suggested, duplicate, or related")

    return normalized_action, normalized_relationship_type


def _normalize_enrichment_fields(fields: Sequence[str] | None) -> list[str] | None:
    if fields is None:
        return None
    normalized = [str(field).strip() for field in fields if str(field).strip()]
    unique_fields = list(dict.fromkeys(normalized))
    invalid_fields = sorted(
        set(unique_fields).difference(enrichment_review.SUGGESTION_APPLYABLE_FIELDS)
    )
    if invalid_fields:
        raise ValidationError(
            "fields", f"unsupported suggestion fields: {', '.join(invalid_fields)}"
        )
    return unique_fields or None


def _validate_enrichment_action(
    *,
    action_type: str,
    fields: Sequence[str] | None,
) -> tuple[EnrichmentActionType, list[str] | None]:
    if action_type == "apply":
        normalized_action: EnrichmentActionType = "apply"
    elif action_type == "reject":
        normalized_action = "reject"
    else:
        raise ValidationError("action_type", "must be apply or reject")

    normalized_fields = _normalize_enrichment_fields(fields)
    if normalized_action == "reject" and normalized_fields:
        raise ValidationError("fields", "reject actions cannot define fields")
    return normalized_action, normalized_fields


def _validate_relationship_session_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {**_DEFAULT_RELATIONSHIP_SESSION_OPTIONS, **(dict(options) if options else {})}
    relationship_kind = str(merged.get("relationship_kind") or "all")
    if relationship_kind not in {"all", "duplicate", "related"}:
        raise ValidationError(
            "relationship_kind",
            "must be all, duplicate, or related",
        )
    candidate_limit = int(
        merged.get("candidate_limit") or _DEFAULT_RELATIONSHIP_SESSION_OPTIONS["candidate_limit"]
    )
    item_limit = int(
        merged.get("item_limit") or _DEFAULT_RELATIONSHIP_SESSION_OPTIONS["item_limit"]
    )
    if candidate_limit < 1:
        raise ValidationError("candidate_limit", "must be positive")
    if item_limit < 1:
        raise ValidationError("item_limit", "must be positive")
    return {
        "relationship_kind": relationship_kind,
        "candidate_limit": candidate_limit,
        "item_limit": item_limit,
    }


def _validate_enrichment_session_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {**_DEFAULT_ENRICHMENT_SESSION_OPTIONS, **(dict(options) if options else {})}
    pending_kind = str(merged.get("pending_kind") or "all")
    if pending_kind not in {"all", "suggestions", "clarifications"}:
        raise ValidationError(
            "pending_kind",
            "must be all, suggestions, or clarifications",
        )
    suggestion_limit = int(
        merged.get("suggestion_limit") or _DEFAULT_ENRICHMENT_SESSION_OPTIONS["suggestion_limit"]
    )
    clarification_limit = int(
        merged.get("clarification_limit")
        or _DEFAULT_ENRICHMENT_SESSION_OPTIONS["clarification_limit"]
    )
    item_limit = int(merged.get("item_limit") or _DEFAULT_ENRICHMENT_SESSION_OPTIONS["item_limit"])
    if suggestion_limit < 1:
        raise ValidationError("suggestion_limit", "must be positive")
    if clarification_limit < 1:
        raise ValidationError("clarification_limit", "must be positive")
    if item_limit < 1:
        raise ValidationError("item_limit", "must be positive")
    return {
        "pending_kind": pending_kind,
        "suggestion_limit": suggestion_limit,
        "clarification_limit": clarification_limit,
        "item_limit": item_limit,
    }


def _require_relationship_action_row(
    *,
    action_preset_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = repo.get_review_action_preset(action_preset_id=action_preset_id, conn=conn)
    if row is None or str(row["review_kind"]) != "relationship":
        raise ResourceNotFoundError(
            "review action", f"Relationship review action not found: {action_preset_id}"
        )
    return row


def _require_enrichment_action_row(
    *,
    action_preset_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = repo.get_review_action_preset(action_preset_id=action_preset_id, conn=conn)
    if row is None or str(row["review_kind"]) != "enrichment":
        raise ResourceNotFoundError(
            "review action", f"Enrichment review action not found: {action_preset_id}"
        )
    return row


def _require_relationship_session_row(
    *,
    session_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = repo.get_review_session(session_id=session_id, conn=conn)
    if row is None or str(row["review_kind"]) != "relationship":
        raise ResourceNotFoundError(
            "review session", f"Relationship review session not found: {session_id}"
        )
    return row


def _require_enrichment_session_row(
    *,
    session_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    row = repo.get_review_session(session_id=session_id, conn=conn)
    if row is None or str(row["review_kind"]) != "enrichment":
        raise ResourceNotFoundError(
            "review session", f"Enrichment review session not found: {session_id}"
        )
    return row


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
    }


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


@typingx.validate_io()
def execute_relationship_review_session_action(
    *,
    session_id: int,
    loop_id: int,
    candidate_loop_id: int,
    candidate_relationship_type: str,
    action_preset_id: int | None,
    action_type: str | None,
    relationship_type: str | None,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_relationship_session_row(session_id=session_id, conn=conn)
    before = _build_relationship_session_snapshot(
        session_row=session_row, conn=conn, settings=settings
    )
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    item = next((entry for entry in before["items"] if int(entry["loop"]["id"]) == loop_id), None)
    if item is None:
        raise ValidationError(
            "loop_id", f"loop {loop_id} is not present in review session {session_id}"
        )
    candidate = next(
        (
            entry
            for entry in [
                *item.get("duplicate_candidates", []),
                *item.get("related_candidates", []),
            ]
            if int(entry["id"]) == candidate_loop_id
        ),
        None,
    )
    if candidate is None:
        raise ValidationError(
            "candidate_loop_id",
            (
                f"candidate {candidate_loop_id} is not present "
                f"for loop {loop_id} in session {session_id}"
            ),
        )

    if action_preset_id is not None:
        preset = _relationship_action_payload(
            _require_relationship_action_row(action_preset_id=action_preset_id, conn=conn)
        )
        resolved_action_type = str(preset["action_type"])
        resolved_relationship_type = str(preset["relationship_type"])
    else:
        if action_type is None or relationship_type is None:
            raise ValidationError(
                "action",
                "provide action_preset_id or both action_type and relationship_type",
            )
        resolved_action_type, resolved_relationship_type = _validate_relationship_action(
            action_type=action_type,
            relationship_type=relationship_type,
        )

    actual_relationship_type = (
        candidate_relationship_type
        if resolved_relationship_type == "suggested"
        else resolved_relationship_type
    )
    if actual_relationship_type != str(candidate["relationship_type"]):
        raise ValidationError(
            "relationship_type",
            "resolved relationship_type does not match the queued candidate",
        )

    if resolved_action_type == "confirm":
        result = relationship_review.confirm_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=actual_relationship_type,
            conn=conn,
        )
    else:
        result = relationship_review.dismiss_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=actual_relationship_type,
            conn=conn,
        )

    after = _build_relationship_session_snapshot(
        session_row=_require_relationship_session_row(session_id=session_id, conn=conn),
        conn=conn,
        settings=settings,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    return {"result": result, "snapshot": after}


@typingx.validate_io()
def execute_enrichment_review_session_action(
    *,
    session_id: int,
    suggestion_id: int,
    action_preset_id: int | None,
    action_type: str | None,
    fields: Sequence[str] | None,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_enrichment_session_row(session_id=session_id, conn=conn)
    before = _build_enrichment_session_snapshot(session_row=session_row, conn=conn)
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    suggestion_in_session = next(
        (
            suggestion
            for item in before["items"]
            for suggestion in item.get("pending_suggestions", [])
            if int(suggestion["id"]) == suggestion_id
        ),
        None,
    )
    if suggestion_in_session is None:
        raise ValidationError(
            "suggestion_id",
            f"suggestion {suggestion_id} is not present in review session {session_id}",
        )

    if action_preset_id is not None:
        preset = _enrichment_action_payload(
            _require_enrichment_action_row(action_preset_id=action_preset_id, conn=conn)
        )
        resolved_action_type = str(preset["action_type"])
        resolved_fields = preset.get("fields")
    else:
        if action_type is None:
            raise ValidationError("action", "provide action_preset_id or action_type")
        resolved_action_type, resolved_fields = _validate_enrichment_action(
            action_type=action_type,
            fields=fields,
        )

    if resolved_action_type == "apply":
        result = enrichment_review.apply_suggestion(
            suggestion_id=suggestion_id,
            fields=resolved_fields,
            conn=conn,
            settings=settings,
        )
    else:
        result = enrichment_review.reject_suggestion(suggestion_id=suggestion_id, conn=conn)

    after = _build_enrichment_session_snapshot(
        session_row=_require_enrichment_session_row(session_id=session_id, conn=conn),
        conn=conn,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    return {"result": result, "snapshot": after}


@typingx.validate_io()
def answer_enrichment_review_session_clarifications(
    *,
    session_id: int,
    loop_id: int,
    answers: Sequence[enrichment_review.ClarificationAnswerInput],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    session_row = _require_enrichment_session_row(session_id=session_id, conn=conn)
    before = _build_enrichment_session_snapshot(session_row=session_row, conn=conn)
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    item = next((entry for entry in before["items"] if int(entry["loop"]["id"]) == loop_id), None)
    if item is None:
        raise ValidationError(
            "loop_id", f"loop {loop_id} is not present in review session {session_id}"
        )
    allowed_clarification_ids = {
        int(clarification["id"]) for clarification in item.get("pending_clarifications", [])
    }
    for answer in answers:
        if int(answer.clarification_id) not in allowed_clarification_ids:
            raise ValidationError(
                "clarification_id",
                (
                    f"clarification {answer.clarification_id} is not present "
                    f"for loop {loop_id} in session {session_id}"
                ),
            )

    result = enrichment_review.submit_clarification_answers(
        loop_id=loop_id,
        answers=answers,
        conn=conn,
    ).to_payload()
    after = _build_enrichment_session_snapshot(
        session_row=_require_enrichment_session_row(session_id=session_id, conn=conn),
        conn=conn,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    return {"result": result, "snapshot": after}
