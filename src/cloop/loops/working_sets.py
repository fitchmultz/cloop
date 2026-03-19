"""Working-set orchestration for the operator shell.

Purpose:
    Own durable working-set CRUD, ordered membership management, and active
    focus-mode context for the operator-first frontend shell.

Responsibilities:
    - Validate and persist named working sets and ordered membership rows
    - Resolve referenced objects into launch-ready shell payloads
    - Maintain the singleton active working-set/focus-mode context
    - Handle missing/deleted referenced objects gracefully for resume flows

Scope:
    - Working-set domain orchestration only

Usage:
    - Reused by HTTP routes and any future CLI/MCP working-set surfaces

Invariants/Assumptions:
    - Working sets reference durable objects by id when one exists
    - Missing referenced rows should not break the containing set
    - Only one active working-set/focus-mode context exists per local database

Non-scope:
    - Shell-specific HTML rendering or browser-only state
    - Loop/planning/review business logic outside working-set orchestration
    - Command palette behavior or chat prompt composition
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Mapping, cast

from .. import typingx
from . import repo
from ._repo.shared import _UNSET
from .errors import ValidationError

_WORKING_SET_ITEM_TYPES = {
    "loop",
    "planning_session",
    "relationship_review_session",
    "enrichment_review_session",
    "view",
    "memory",
    "query_anchor",
    "state_anchor",
}

_SHELL_STATES = {"operator", "capture", "do", "decide", "plan", "review", "recall", "working_set"}
_RECALL_TOOLS = {"chat", "memory", "rag"}
_REVIEW_FOCUSES = {"planning", "relationship", "enrichment", "cohorts"}


def _utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with second precision."""
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_json(raw: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse one JSON object payload safely."""
    if not raw:
        return {} if fallback is None else dict(fallback)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {} if fallback is None else dict(fallback)
    if isinstance(parsed, dict):
        return parsed
    return {} if fallback is None else dict(fallback)


def _field(source: Mapping[str, Any] | object, name: str) -> Any:
    """Read one field from either a mapping payload or an object payload."""
    if isinstance(source, Mapping):
        return cast(Mapping[str, Any], source).get(name)
    return getattr(source, name, None)


def _loop_label(loop_row: Mapping[str, Any] | object, fallback_id: int | None) -> str:
    """Build the canonical loop label for working-set surfaces."""
    title = str(_field(loop_row, "title") or "").strip()
    raw_text = str(_field(loop_row, "raw_text") or "").strip()
    return title or raw_text or (f"Loop #{fallback_id}" if fallback_id is not None else "Loop")


def _memory_row(*, memory_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Read one memory row directly from the core database."""
    row = conn.execute("SELECT * FROM memory_entries WHERE id = ?", (memory_id,)).fetchone()
    return dict(row) if row else None


def _build_launch(
    *,
    state: str,
    recall_tool: str = "chat",
    review_focus: str | None = None,
    session_id: int | None = None,
    loop_id: int | None = None,
    view_id: int | None = None,
    memory_id: int | None = None,
    working_set_id: int | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Create the frontend launch payload for one working-set item."""
    return {
        "state": state,
        "recall_tool": recall_tool,
        "review_focus": review_focus,
        "session_id": session_id,
        "loop_id": loop_id,
        "view_id": view_id,
        "memory_id": memory_id,
        "working_set_id": working_set_id,
        "query": query,
    }


def _required_working_set(*, working_set_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Load one working set or raise the canonical validation error."""
    row = repo.get_working_set(working_set_id=working_set_id, conn=conn)
    if row is None:
        raise ValidationError("working_set_id", f"working set {working_set_id} not found")
    return row


def _row_working_set_id(row: Mapping[str, Any]) -> int | None:
    """Read the parent working-set id from one membership row when present."""
    raw_value = row.get("working_set_id")
    return int(raw_value) if raw_value is not None else None


def _required_metadata_string(
    metadata: Mapping[str, Any],
    *,
    field: str,
    allow_blank: bool = False,
) -> str:
    """Read one required string field from metadata."""
    value = metadata.get(field)
    if not isinstance(value, str):
        raise ValidationError(field, "must be a string")
    trimmed = value.strip()
    if not allow_blank and not trimmed:
        raise ValidationError(field, "must not be empty")
    return trimmed


def _validate_state_anchor_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate stored state-anchor metadata."""
    state = _required_metadata_string(metadata, field="state")
    if state not in _SHELL_STATES:
        raise ValidationError("metadata.state", f"unsupported shell state: {state}")

    recall_tool_raw = metadata.get("recall_tool", "chat")
    recall_tool = recall_tool_raw if isinstance(recall_tool_raw, str) else "chat"
    if recall_tool not in _RECALL_TOOLS:
        raise ValidationError("metadata.recall_tool", f"unsupported recall tool: {recall_tool}")

    review_focus_raw = metadata.get("review_focus")
    review_focus = review_focus_raw if isinstance(review_focus_raw, str) else None
    if review_focus is not None and review_focus not in _REVIEW_FOCUSES:
        raise ValidationError("metadata.review_focus", f"unsupported review focus: {review_focus}")

    parsed: dict[str, Any] = {
        "state": state,
        "recall_tool": recall_tool,
        "review_focus": review_focus,
    }
    for numeric_key in ("session_id", "loop_id", "view_id", "memory_id", "working_set_id"):
        numeric_value = metadata.get(numeric_key)
        if numeric_value is None:
            parsed[numeric_key] = None
            continue
        if not isinstance(numeric_value, int) or numeric_value < 1:
            raise ValidationError(f"metadata.{numeric_key}", "must be a positive integer")
        parsed[numeric_key] = numeric_value

    query_value = metadata.get("query")
    if query_value is not None and not isinstance(query_value, str):
        raise ValidationError("metadata.query", "must be a string when provided")
    parsed["query"] = query_value.strip() if isinstance(query_value, str) else None

    if state == "working_set" and parsed["working_set_id"] is None:
        raise ValidationError(
            "metadata.working_set_id",
            "is required when state is working_set",
        )

    return parsed


def _validate_query_anchor_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate stored query-anchor metadata."""
    query = _required_metadata_string(metadata, field="query")
    state = str(metadata.get("state") or "capture").strip()
    if state not in {"capture", "do", "review", "recall"}:
        raise ValidationError("metadata.state", f"unsupported query-anchor state: {state}")

    recall_tool_raw = metadata.get("recall_tool", "chat")
    recall_tool = recall_tool_raw if isinstance(recall_tool_raw, str) else "chat"
    if state == "recall" and recall_tool not in _RECALL_TOOLS:
        raise ValidationError("metadata.recall_tool", f"unsupported recall tool: {recall_tool}")

    return {
        "query": query,
        "state": state,
        "recall_tool": recall_tool if state == "recall" else "chat",
    }


def _resolve_working_set_item(
    row: Mapping[str, Any], *, conn: sqlite3.Connection
) -> dict[str, Any]:
    """Resolve one stored working-set row into a launch-ready payload."""
    item_type = str(row["item_type"])
    item_id = int(row["item_id"]) if row.get("item_id") is not None else None
    metadata = _parse_json(row.get("metadata_json"))
    working_set_id = _row_working_set_id(row)
    fallback_label = str(row.get("label") or "").strip() or "Untitled working-set item"
    fallback_description = str(row.get("description") or "").strip()

    if item_type == "loop":
        loop_row = repo.read_loop(loop_id=item_id, conn=conn) if item_id is not None else None
        if loop_row is None:
            return {
                "id": row["id"],
                "item_type": item_type,
                "item_id": item_id,
                "kind_label": "Loop",
                "label": fallback_label,
                "description": fallback_description or "This loop is no longer available.",
                "status_label": "Missing loop",
                "missing": True,
                "position": row["position"],
                "created_at_utc": row["created_at"],
                "metadata": metadata,
                "launch": _build_launch(
                    state="do",
                    loop_id=item_id,
                    working_set_id=working_set_id,
                ),
            }
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": item_id,
            "kind_label": "Loop",
            "label": _loop_label(loop_row, item_id),
            "description": str(
                _field(loop_row, "summary")
                or _field(loop_row, "next_action")
                or _field(loop_row, "raw_text")
                or ""
            ).strip(),
            "status_label": str(_field(loop_row, "status") or "").replace("_", " "),
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state="do",
                loop_id=item_id,
                working_set_id=working_set_id,
            ),
        }

    if item_type == "planning_session":
        session_row = (
            repo.get_planning_session(session_id=item_id, conn=conn)
            if item_id is not None
            else None
        )
        if session_row is None:
            return {
                "id": row["id"],
                "item_type": item_type,
                "item_id": item_id,
                "kind_label": "Plan",
                "label": fallback_label,
                "description": fallback_description
                or "This planning session is no longer available.",
                "status_label": "Missing plan",
                "missing": True,
                "position": row["position"],
                "created_at_utc": row["created_at"],
                "metadata": metadata,
                "launch": _build_launch(
                    state="plan",
                    review_focus="planning",
                    session_id=item_id,
                    working_set_id=working_set_id,
                ),
            }
        plan_json = _parse_json(str(session_row.get("plan_json") or "{}"))
        checkpoints_value = plan_json.get("checkpoints")
        checkpoints = checkpoints_value if isinstance(checkpoints_value, list) else []
        checkpoint_count = len(checkpoints)
        current_index = int(session_row.get("current_checkpoint_index") or 0)
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": item_id,
            "kind_label": "Plan",
            "label": str(session_row.get("name") or fallback_label),
            "description": str(
                plan_json.get("summary") or fallback_description or session_row.get("prompt") or ""
            ).strip(),
            "status_label": (
                f"Checkpoint {min(current_index + 1, checkpoint_count or 1)}"
                f" of {checkpoint_count or 1}"
            ),
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state="plan",
                review_focus="planning",
                session_id=item_id,
                working_set_id=working_set_id,
            ),
        }

    if item_type in {"relationship_review_session", "enrichment_review_session"}:
        session_row = (
            repo.get_review_session(session_id=item_id, conn=conn) if item_id is not None else None
        )
        expected_kind = (
            "relationship" if item_type == "relationship_review_session" else "enrichment"
        )
        if session_row is None or str(session_row.get("review_kind")) != expected_kind:
            return {
                "id": row["id"],
                "item_type": item_type,
                "item_id": item_id,
                "kind_label": "Decision queue"
                if expected_kind == "relationship"
                else "Enrichment queue",
                "label": fallback_label,
                "description": fallback_description
                or "This review session is no longer available.",
                "status_label": "Missing review session",
                "missing": True,
                "position": row["position"],
                "created_at_utc": row["created_at"],
                "metadata": metadata,
                "launch": _build_launch(
                    state="decide",
                    review_focus=expected_kind,
                    session_id=item_id,
                    working_set_id=working_set_id,
                ),
            }
        options = _parse_json(str(session_row.get("options_json") or "{}"))
        status_label = (
            f"{options.get('relationship_kind', 'relationship')} queue"
            if expected_kind == "relationship"
            else f"{options.get('pending_kind', 'all')} enrichment queue"
        )
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": item_id,
            "kind_label": "Decision queue"
            if expected_kind == "relationship"
            else "Enrichment queue",
            "label": str(session_row.get("name") or fallback_label),
            "description": str(session_row.get("query") or fallback_description or "").strip(),
            "status_label": status_label,
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state="decide",
                review_focus=expected_kind,
                session_id=item_id,
                working_set_id=working_set_id,
            ),
        }

    if item_type == "view":
        view_row = repo.get_loop_view(view_id=item_id, conn=conn) if item_id is not None else None
        if view_row is None:
            return {
                "id": row["id"],
                "item_type": item_type,
                "item_id": item_id,
                "kind_label": "Saved view",
                "label": fallback_label,
                "description": fallback_description or "This saved view is no longer available.",
                "status_label": "Missing view",
                "missing": True,
                "position": row["position"],
                "created_at_utc": row["created_at"],
                "metadata": metadata,
                "launch": _build_launch(
                    state="capture",
                    view_id=item_id,
                    working_set_id=working_set_id,
                ),
            }
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": item_id,
            "kind_label": "Saved view",
            "label": str(view_row.get("name") or fallback_label),
            "description": str(
                view_row.get("description") or view_row.get("query") or fallback_description or ""
            ).strip(),
            "status_label": "Saved view",
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state="capture",
                view_id=item_id,
                working_set_id=working_set_id,
            ),
        }

    if item_type == "memory":
        memory_row = _memory_row(memory_id=item_id, conn=conn) if item_id is not None else None
        if memory_row is None:
            return {
                "id": row["id"],
                "item_type": item_type,
                "item_id": item_id,
                "kind_label": "Memory",
                "label": fallback_label,
                "description": fallback_description or "This memory entry is no longer available.",
                "status_label": "Missing memory",
                "missing": True,
                "position": row["position"],
                "created_at_utc": row["created_at"],
                "metadata": metadata,
                "launch": _build_launch(
                    state="recall",
                    recall_tool="memory",
                    memory_id=item_id,
                    working_set_id=working_set_id,
                ),
            }
        label = str(memory_row.get("key") or "").strip() or f"Memory #{item_id}"
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": item_id,
            "kind_label": "Memory",
            "label": label,
            "description": str(memory_row.get("content") or fallback_description or "").strip(),
            "status_label": str(memory_row.get("category") or "memory").replace("_", " "),
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state="recall",
                recall_tool="memory",
                memory_id=item_id,
                working_set_id=working_set_id,
            ),
        }

    if item_type == "query_anchor":
        anchor = _validate_query_anchor_metadata(metadata)
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": None,
            "kind_label": "Query anchor",
            "label": fallback_label,
            "description": fallback_description or anchor["query"],
            "status_label": "Query anchor",
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state=anchor["state"],
                recall_tool=anchor["recall_tool"],
                query=anchor["query"],
                working_set_id=working_set_id,
            ),
        }

    if item_type == "state_anchor":
        anchor = _validate_state_anchor_metadata(metadata)
        return {
            "id": row["id"],
            "item_type": item_type,
            "item_id": None,
            "kind_label": "Surface anchor",
            "label": fallback_label,
            "description": fallback_description or "Resume a saved workflow surface.",
            "status_label": "Surface anchor",
            "missing": False,
            "position": row["position"],
            "created_at_utc": row["created_at"],
            "metadata": metadata,
            "launch": _build_launch(
                state=anchor["state"],
                recall_tool=anchor["recall_tool"],
                review_focus=anchor["review_focus"],
                session_id=anchor["session_id"],
                loop_id=anchor["loop_id"],
                view_id=anchor["view_id"],
                memory_id=anchor["memory_id"],
                working_set_id=anchor["working_set_id"] or working_set_id,
                query=anchor["query"],
            ),
        }

    raise ValidationError("item_type", f"unsupported working-set item type: {item_type}")


def _working_set_payload(row: Mapping[str, Any], *, conn: sqlite3.Connection) -> dict[str, Any]:
    """Resolve one working set plus its ordered items."""
    items = [
        _resolve_working_set_item(item_row, conn=conn)
        for item_row in repo.list_working_set_items(working_set_id=int(row["id"]), conn=conn)
    ]
    missing_count = sum(1 for item in items if bool(item.get("missing")))
    working_set_id = int(row["id"])
    return {
        "id": working_set_id,
        "name": row["name"],
        "description": row.get("description"),
        "item_count": len(items),
        "missing_item_count": missing_count,
        "last_activated_at_utc": row.get("last_activated_at"),
        "created_at_utc": row["created_at"],
        "updated_at_utc": row["updated_at"],
        "items": items,
        "launch": _build_launch(state="working_set", working_set_id=working_set_id),
    }


def _default_item_fields(
    *,
    item_type: str,
    item_id: int | None,
    metadata: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> tuple[str, str | None]:
    """Infer default label/description for a new membership row."""
    if item_type == "loop":
        if item_id is None:
            raise ValidationError("item_id", "is required for loop items")
        loop_row = repo.read_loop(loop_id=item_id, conn=conn)
        if loop_row is None:
            raise ValidationError("item_id", f"loop {item_id} not found")
        return _loop_label(loop_row, item_id), str(
            _field(loop_row, "summary")
            or _field(loop_row, "next_action")
            or _field(loop_row, "raw_text")
            or ""
        ).strip() or None

    if item_type == "planning_session":
        if item_id is None:
            raise ValidationError("item_id", "is required for planning-session items")
        session_row = repo.get_planning_session(session_id=item_id, conn=conn)
        if session_row is None:
            raise ValidationError("item_id", f"planning session {item_id} not found")
        plan_json = _parse_json(str(session_row.get("plan_json") or "{}"))
        return str(session_row.get("name") or f"Plan #{item_id}"), str(
            plan_json.get("summary") or session_row.get("prompt") or ""
        ).strip() or None

    if item_type in {"relationship_review_session", "enrichment_review_session"}:
        if item_id is None:
            raise ValidationError("item_id", "is required for review-session items")
        session_row = repo.get_review_session(session_id=item_id, conn=conn)
        expected_kind = (
            "relationship" if item_type == "relationship_review_session" else "enrichment"
        )
        if session_row is None or str(session_row.get("review_kind")) != expected_kind:
            raise ValidationError("item_id", f"{expected_kind} review session {item_id} not found")
        return str(session_row.get("name") or f"Review #{item_id}"), str(
            session_row.get("query") or ""
        ).strip() or None

    if item_type == "view":
        if item_id is None:
            raise ValidationError("item_id", "is required for saved-view items")
        view_row = repo.get_loop_view(view_id=item_id, conn=conn)
        if view_row is None:
            raise ValidationError("item_id", f"view {item_id} not found")
        return str(view_row.get("name") or f"View #{item_id}"), str(
            view_row.get("description") or view_row.get("query") or ""
        ).strip() or None

    if item_type == "memory":
        if item_id is None:
            raise ValidationError("item_id", "is required for memory items")
        memory_row = _memory_row(memory_id=item_id, conn=conn)
        if memory_row is None:
            raise ValidationError("item_id", f"memory {item_id} not found")
        label = str(memory_row.get("key") or "").strip() or f"Memory #{item_id}"
        return label, str(memory_row.get("content") or "").strip() or None

    if item_type == "query_anchor":
        anchor = _validate_query_anchor_metadata(metadata)
        label = str(metadata.get("label") or "").strip() or f"Query · {anchor['query']}"
        description = str(metadata.get("description") or "").strip() or anchor["query"]
        return label, description

    if item_type == "state_anchor":
        anchor = _validate_state_anchor_metadata(metadata)
        label = str(metadata.get("label") or "").strip() or f"Surface · {anchor['state']}"
        description = (
            str(metadata.get("description") or "").strip() or "Resume a saved surface anchor."
        )
        return label, description

    raise ValidationError("item_type", f"unsupported working-set item type: {item_type}")


def _item_signature(row: Mapping[str, Any]) -> tuple[str, int | None, str]:
    """Build a stable de-duplication signature for one membership row."""
    metadata = _parse_json(row.get("metadata_json"))
    normalized_metadata = json.dumps(metadata, sort_keys=True)
    item_id = int(row["item_id"]) if row.get("item_id") is not None else None
    return str(row["item_type"]), item_id, normalized_metadata


def _add_working_set_item_impl(
    *,
    working_set_id: int,
    item_type: str,
    item_id: int | None,
    label: str | None,
    description: str | None,
    metadata: Mapping[str, Any] | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create one membership row inside an existing transaction."""
    if item_type not in _WORKING_SET_ITEM_TYPES:
        raise ValidationError("item_type", f"unsupported working-set item type: {item_type}")
    _required_working_set(working_set_id=working_set_id, conn=conn)
    metadata_dict = dict(metadata or {})
    default_label, default_description = _default_item_fields(
        item_type=item_type,
        item_id=item_id,
        metadata=metadata_dict,
        conn=conn,
    )
    resolved_label = (label or "").strip() or default_label
    resolved_description = (description or "").strip() or default_description

    signature = (item_type, item_id, json.dumps(metadata_dict, sort_keys=True))
    existing_rows = repo.list_working_set_items(working_set_id=working_set_id, conn=conn)
    duplicate_row = next((row for row in existing_rows if _item_signature(row) == signature), None)
    if duplicate_row is not None:
        repo.delete_working_set_item(
            working_set_id=working_set_id,
            item_id=int(duplicate_row["id"]),
            conn=conn,
        )
    row = repo.create_working_set_item(
        working_set_id=working_set_id,
        item_type=item_type,
        item_id=item_id,
        label=resolved_label,
        description=resolved_description,
        metadata_json=metadata_dict,
        conn=conn,
    )
    repo.update_working_set(
        working_set_id=working_set_id,
        last_activated_at=_utc_now_iso(),
        conn=conn,
    )
    return row


def _delete_working_set_items_for_target(
    *,
    item_type: str,
    item_id: int,
    conn: sqlite3.Connection,
) -> None:
    """Remove all working-set memberships for one durable referenced target."""
    for working_set in repo.list_working_sets(conn=conn):
        working_set_id = int(working_set["id"])
        for row in repo.list_working_set_items(working_set_id=working_set_id, conn=conn):
            row_item_id = int(row["item_id"]) if row.get("item_id") is not None else None
            if str(row["item_type"]) != item_type or row_item_id != item_id:
                continue
            repo.delete_working_set_item(
                working_set_id=working_set_id,
                item_id=int(row["id"]),
                conn=conn,
            )


@typingx.validate_io()
def create_working_set(
    *,
    name: str,
    description: str | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a durable working set."""
    with conn:
        row = repo.create_working_set(name=name, description=description, conn=conn)
    return _working_set_payload(row, conn=conn)


@typingx.validate_io()
def list_working_sets(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all working sets with resolved items."""
    return [_working_set_payload(row, conn=conn) for row in repo.list_working_sets(conn=conn)]


@typingx.validate_io()
def get_working_set(*, working_set_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Get one working set with resolved items."""
    return _working_set_payload(
        _required_working_set(working_set_id=working_set_id, conn=conn), conn=conn
    )


@typingx.validate_io()
def update_working_set(
    *,
    working_set_id: int,
    name: str | None = None,
    description: str | None | object = _UNSET,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update working-set metadata."""
    _required_working_set(working_set_id=working_set_id, conn=conn)
    with conn:
        updated = repo.update_working_set(
            working_set_id=working_set_id,
            name=name,
            description=description,
            conn=conn,
        )
    if updated is None:
        raise ValidationError("working_set_id", f"working set {working_set_id} not found")
    return _working_set_payload(updated, conn=conn)


@typingx.validate_io()
def delete_working_set(*, working_set_id: int, conn: sqlite3.Connection) -> bool:
    """Delete one working set."""
    _required_working_set(working_set_id=working_set_id, conn=conn)
    with conn:
        deleted = repo.delete_working_set(working_set_id=working_set_id, conn=conn)
    if not deleted:
        raise ValidationError("working_set_id", f"working set {working_set_id} not found")
    return True


@typingx.validate_io()
def add_working_set_item(
    *,
    working_set_id: int,
    item_type: str,
    item_id: int | None,
    label: str | None,
    description: str | None,
    metadata: Mapping[str, Any] | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Add one item to a working set, de-duplicating identical membership rows."""
    with conn:
        row = _add_working_set_item_impl(
            working_set_id=working_set_id,
            item_type=item_type,
            item_id=item_id,
            label=label,
            description=description,
            metadata=metadata,
            conn=conn,
        )
    return _resolve_working_set_item(row, conn=conn)


@typingx.validate_io()
def remove_working_set_item(*, working_set_id: int, item_id: int, conn: sqlite3.Connection) -> bool:
    """Remove one membership row from a working set."""
    working_set = _required_working_set(working_set_id=working_set_id, conn=conn)
    with conn:
        deleted = repo.delete_working_set_item(
            working_set_id=working_set_id, item_id=item_id, conn=conn
        )
        if deleted:
            repo.update_working_set(
                working_set_id=working_set_id,
                last_activated_at=working_set.get("last_activated_at"),
                conn=conn,
            )
    if not deleted:
        raise ValidationError("item_id", f"working-set item {item_id} not found")
    return True


@typingx.validate_io()
def reorder_working_set_items(
    *,
    working_set_id: int,
    ordered_item_ids: list[int],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Rewrite item ordering for one working set."""
    row = _required_working_set(working_set_id=working_set_id, conn=conn)
    existing_rows = repo.list_working_set_items(working_set_id=working_set_id, conn=conn)
    existing_ids = [int(item_row["id"]) for item_row in existing_rows]
    if sorted(existing_ids) != sorted(ordered_item_ids):
        raise ValidationError(
            "ordered_item_ids", "must contain every working-set item exactly once"
        )
    with conn:
        repo.reorder_working_set_items(
            working_set_id=working_set_id,
            ordered_item_ids=ordered_item_ids,
            conn=conn,
        )
        repo.update_working_set(
            working_set_id=working_set_id,
            last_activated_at=row.get("last_activated_at"),
            conn=conn,
        )
    refreshed = _required_working_set(working_set_id=working_set_id, conn=conn)
    return _working_set_payload(refreshed, conn=conn)


@typingx.validate_io()
def get_working_set_context(*, conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the active working-set/focus-mode context."""
    context_row = repo.get_working_set_context(conn=conn)
    active_id = context_row.get("active_working_set_id")
    active_payload = None
    if active_id is not None:
        active_row = repo.get_working_set(working_set_id=int(active_id), conn=conn)
        if active_row is not None:
            active_payload = _working_set_payload(active_row, conn=conn)
    return {
        "active_working_set_id": active_id,
        "focus_mode_enabled": bool(context_row.get("focus_mode_enabled"))
        and active_payload is not None,
        "updated_at_utc": context_row["updated_at"],
        "active_working_set": active_payload,
    }


@typingx.validate_io()
def update_working_set_context(
    *,
    active_working_set_id: int | None,
    focus_mode_enabled: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update the active working-set/focus-mode context."""
    if active_working_set_id is not None:
        _required_working_set(working_set_id=active_working_set_id, conn=conn)
    with conn:
        repo.update_working_set_context(
            active_working_set_id=active_working_set_id,
            focus_mode_enabled=focus_mode_enabled,
            conn=conn,
        )
        if active_working_set_id is not None:
            repo.update_working_set(
                working_set_id=active_working_set_id,
                last_activated_at=_utc_now_iso(),
                conn=conn,
            )
    return get_working_set_context(conn=conn)


__all__ = [
    "create_working_set",
    "list_working_sets",
    "get_working_set",
    "update_working_set",
    "delete_working_set",
    "add_working_set_item",
    "remove_working_set_item",
    "reorder_working_set_items",
    "get_working_set_context",
    "update_working_set_context",
]
