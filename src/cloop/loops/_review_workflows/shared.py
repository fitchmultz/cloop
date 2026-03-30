"""Shared review workflow validation and payload helpers.

Purpose:
    Centralize saved review action/session validation, row normalization,
    and lookup helpers used across relationship and enrichment workflows.

Responsibilities:
    - Define shared review workflow type aliases and sentinel values
    - Normalize saved action/session row payloads
    - Validate review action/session configuration inputs
    - Require typed review action/session repo rows

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Shared review workflow helper logic only
    - No queue materialization or action execution side effects

Usage:
    Imported by review workflow snapshot, action, session, and execution modules.

Invariants/Assumptions:
    - Review rows are distinguished by persisted `review_kind`
    - Normalized payloads remain transport-agnostic and serializable
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from .. import enrichment_review, repo
from ..errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ..query import parse_loop_query

RelationshipActionType = Literal["confirm", "dismiss"]


RelationshipTargetType = Literal["suggested", "duplicate", "related"]


EnrichmentActionType = Literal["apply", "reject"]


RelationshipReviewKind = Literal["all", "duplicate", "related"]


EnrichmentPendingKind = Literal["all", "suggestions", "clarifications"]


ReviewSessionMoveDirection = Literal["next", "previous"]


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


def _validate_move_direction(value: str) -> ReviewSessionMoveDirection:
    if value == "next":
        return "next"
    if value == "previous":
        return "previous"
    raise ValidationError("direction", "must be next or previous")


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
        set(unique_fields).difference(enrichment_review.SUGGESTION_APPLICABLE_FIELDS)
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
    if normalized_action == "apply" and fields is not None and normalized_fields is None:
        raise ValidationError("fields", "at least one suggestion field must be selected")
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


__all__ = [
    "RelationshipActionType",
    "RelationshipTargetType",
    "EnrichmentActionType",
    "RelationshipReviewKind",
    "EnrichmentPendingKind",
    "ReviewSessionMoveDirection",
    "_UNSET",
    "_DEFAULT_RELATIONSHIP_SESSION_OPTIONS",
    "_DEFAULT_ENRICHMENT_SESSION_OPTIONS",
    "_normalize_name",
    "_validate_query",
    "_ensure_loop_exists",
    "_resolved_optional_loop_id",
    "_validate_move_direction",
    "_relationship_action_payload",
    "_enrichment_action_payload",
    "_relationship_session_payload",
    "_enrichment_session_payload",
    "_validate_relationship_action",
    "_normalize_enrichment_fields",
    "_validate_enrichment_action",
    "_validate_relationship_session_options",
    "_validate_enrichment_session_options",
    "_require_relationship_action_row",
    "_require_enrichment_action_row",
    "_require_relationship_session_row",
    "_require_enrichment_session_row",
]
