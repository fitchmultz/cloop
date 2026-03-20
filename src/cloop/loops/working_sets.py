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
from .errors import ValidationError, WorkingSetUndoNotPossibleError

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
_WORKING_SET_CONTEXT_SUBJECT_ID = 1
_WORKING_SET_REVERSIBLE_EVENT_TYPES = frozenset(
    {
        "create",
        "update",
        "delete",
        "add_item",
        "bulk_add_items",
        "remove_item",
        "reorder",
        "context_update",
    }
)


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
    latest_event = repo.get_latest_reversible_working_set_event(
        subject_type="working_set",
        subject_id=working_set_id,
        conn=conn,
    )
    return {
        "id": working_set_id,
        "name": row["name"],
        "description": row.get("description"),
        "item_count": len(items),
        "missing_item_count": missing_count,
        "last_activated_at_utc": row.get("last_activated_at"),
        "created_at_utc": row["created_at"],
        "updated_at_utc": row["updated_at"],
        "latest_reversible_event_id": int(latest_event["id"]) if latest_event is not None else None,
        "latest_reversible_event_type": str(latest_event["event_type"])
        if latest_event is not None
        else None,
        "items": items,
        "launch": _build_launch(state="working_set", working_set_id=working_set_id),
    }


def _working_set_row_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    """Capture one raw working-set row for deterministic restoration."""
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "description": row.get("description"),
        "last_activated_at": row.get("last_activated_at"),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _working_set_item_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    """Capture one raw working-set item row for deterministic restoration."""
    return {
        "id": int(row["id"]),
        "working_set_id": int(row["working_set_id"]),
        "item_type": str(row["item_type"]),
        "item_id": int(row["item_id"]) if row.get("item_id") is not None else None,
        "label": str(row["label"]),
        "description": row.get("description"),
        "metadata": _parse_json(row.get("metadata_json")),
        "position": int(row["position"]),
        "created_at": str(row["created_at"]),
    }


def _working_set_state_snapshot(
    *,
    working_set_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Capture the exact persisted state for one working set and its items."""
    row = repo.get_working_set(working_set_id=working_set_id, conn=conn)
    if row is None:
        return {"working_set": None, "items": []}
    item_rows = repo.list_working_set_items(working_set_id=working_set_id, conn=conn)
    return {
        "working_set": _working_set_row_snapshot(row),
        "items": [_working_set_item_snapshot(item_row) for item_row in item_rows],
    }


def _context_state_snapshot(*, conn: sqlite3.Connection) -> dict[str, Any]:
    """Capture the exact persisted working-set context row."""
    context_row = repo.get_working_set_context(conn=conn)
    active_working_set_id = context_row.get("active_working_set_id")
    return {
        "active_working_set_id": (
            int(active_working_set_id) if active_working_set_id is not None else None
        ),
        "focus_mode_enabled": bool(context_row.get("focus_mode_enabled")),
        "updated_at": str(context_row["updated_at"]),
    }


def _working_set_context_payload(*, conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the launch-ready working-set context payload with undo metadata."""
    context_row = repo.get_working_set_context(conn=conn)
    active_id = context_row.get("active_working_set_id")
    active_payload = None
    if active_id is not None:
        active_row = repo.get_working_set(working_set_id=int(active_id), conn=conn)
        if active_row is not None:
            active_payload = _working_set_payload(active_row, conn=conn)
    latest_event = repo.get_latest_reversible_working_set_event(
        subject_type="working_set_context",
        subject_id=_WORKING_SET_CONTEXT_SUBJECT_ID,
        conn=conn,
    )
    return {
        "active_working_set_id": int(active_id) if active_id is not None else None,
        "focus_mode_enabled": bool(context_row.get("focus_mode_enabled"))
        and active_payload is not None,
        "updated_at_utc": str(context_row["updated_at"]),
        "latest_reversible_event_id": int(latest_event["id"]) if latest_event is not None else None,
        "latest_reversible_event_type": str(latest_event["event_type"])
        if latest_event is not None
        else None,
        "active_working_set": active_payload,
    }


def _restore_working_set_state(
    *,
    snapshot: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Restore one working set to an exact prior snapshot."""
    working_set_snapshot = snapshot.get("working_set")
    if not isinstance(working_set_snapshot, Mapping):
        return None
    restored = repo.restore_working_set(snapshot=working_set_snapshot, conn=conn)
    item_snapshots = snapshot.get("items")
    normalized_items = (
        [item for item in item_snapshots if isinstance(item, Mapping)]
        if isinstance(item_snapshots, list)
        else []
    )
    repo.replace_working_set_items(
        working_set_id=int(restored["id"]),
        snapshots=list(normalized_items),
        conn=conn,
    )
    return restored


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


def _record_working_set_event(
    *,
    subject_type: str,
    subject_id: int,
    event_type: str,
    before_state: Mapping[str, Any],
    after_state: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Persist one reversible working-set event and return its event ID."""
    return repo.insert_working_set_event(
        subject_type=subject_type,
        subject_id=subject_id,
        event_type=event_type,
        before_state=before_state,
        after_state=after_state,
        conn=conn,
    )


def _working_set_undo_error(
    *,
    subject_type: str,
    subject_id: int,
    reason: str,
    message: str,
) -> WorkingSetUndoNotPossibleError:
    """Build the canonical working-set undo domain error."""
    return WorkingSetUndoNotPossibleError(
        subject_type=subject_type,
        subject_id=subject_id,
        reason=reason,
        message=message,
    )


@typingx.validate_io()
def undo_working_set_event(
    *,
    expected_event_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Undo one exact latest working-set mutation event."""
    event = repo.get_working_set_event(event_id=expected_event_id, conn=conn)
    if event is None:
        raise _working_set_undo_error(
            subject_type="working_set",
            subject_id=0,
            reason="event_not_found",
            message=f"working-set event {expected_event_id} no longer exists",
        )

    subject_type = str(event["subject_type"])
    subject_id = int(event["subject_id"])
    event_type = str(event["event_type"])
    if event_type not in _WORKING_SET_REVERSIBLE_EVENT_TYPES:
        raise _working_set_undo_error(
            subject_type=subject_type,
            subject_id=subject_id,
            reason="event_not_reversible",
            message=f"working-set event {expected_event_id} is not reversible",
        )

    latest_event = repo.get_latest_reversible_working_set_event(
        subject_type=subject_type,
        subject_id=subject_id,
        conn=conn,
    )
    if latest_event is None:
        raise _working_set_undo_error(
            subject_type=subject_type,
            subject_id=subject_id,
            reason="no_reversible_events",
            message="No reversible working-set events are available",
        )
    if int(latest_event["id"]) != expected_event_id:
        raise _working_set_undo_error(
            subject_type=subject_type,
            subject_id=subject_id,
            reason="stale_event_handle",
            message=(
                f"expected working-set event {expected_event_id}, "
                f"but subject {subject_type}:{subject_id} now requires "
                f"undoing event {int(latest_event['id'])} first"
            ),
        )

    before_state = _parse_json(str(event.get("before_state_json") or "{}"))
    after_state = _parse_json(str(event.get("after_state_json") or "{}"))
    if not before_state and event_type != "create":
        raise _working_set_undo_error(
            subject_type=subject_type,
            subject_id=subject_id,
            reason="missing_before_state",
            message=f"working-set event {expected_event_id} lacks the snapshot needed for undo",
        )

    with conn:
        if subject_type == "working_set":
            if before_state.get("working_set") is None:
                deleted = repo.delete_working_set(working_set_id=subject_id, conn=conn)
                if not deleted:
                    raise _working_set_undo_error(
                        subject_type=subject_type,
                        subject_id=subject_id,
                        reason="target_missing",
                        message=(
                            f"working set {subject_id} is no longer available to delete during undo"
                        ),
                    )
                restored_row = None
            else:
                restored_row = _restore_working_set_state(snapshot=before_state, conn=conn)
                if restored_row is None:
                    raise _working_set_undo_error(
                        subject_type=subject_type,
                        subject_id=subject_id,
                        reason="invalid_before_state",
                        message=(
                            f"working-set event {expected_event_id} has an invalid restore snapshot"
                        ),
                    )
                context_snapshot = before_state.get("context")
                if isinstance(context_snapshot, Mapping):
                    active_working_set_id = context_snapshot.get("active_working_set_id")
                    repo.update_working_set_context(
                        active_working_set_id=(
                            int(active_working_set_id)
                            if active_working_set_id is not None
                            else None
                        ),
                        focus_mode_enabled=bool(context_snapshot.get("focus_mode_enabled")),
                        conn=conn,
                    )
        elif subject_type == "working_set_context":
            active_working_set_id = before_state.get("active_working_set_id")
            if active_working_set_id is not None:
                _required_working_set(working_set_id=int(active_working_set_id), conn=conn)
            repo.update_working_set_context(
                active_working_set_id=(
                    int(active_working_set_id) if active_working_set_id is not None else None
                ),
                focus_mode_enabled=bool(before_state.get("focus_mode_enabled")),
                conn=conn,
            )
            restored_row = None
        else:
            raise _working_set_undo_error(
                subject_type=subject_type,
                subject_id=subject_id,
                reason="unsupported_subject",
                message=f"Unsupported working-set undo subject: {subject_type}",
            )

        restored_after_state = (
            {
                **_working_set_state_snapshot(working_set_id=subject_id, conn=conn),
                **(
                    {"context": _context_state_snapshot(conn=conn)}
                    if isinstance(before_state.get("context"), Mapping)
                    or isinstance(after_state.get("context"), Mapping)
                    else {}
                ),
            }
            if subject_type == "working_set"
            else _context_state_snapshot(conn=conn)
        )
        undo_event_id = repo.insert_working_set_event(
            subject_type=subject_type,
            subject_id=subject_id,
            event_type="undo",
            before_state=after_state,
            after_state=restored_after_state,
            conn=conn,
        )
        repo.mark_working_set_event_undone(
            event_id=expected_event_id,
            undo_event_id=undo_event_id,
            conn=conn,
        )

    context_payload = _working_set_context_payload(conn=conn)
    working_set_payload = (
        _working_set_payload(restored_row, conn=conn) if restored_row is not None else None
    )
    affected_snapshot = before_state.get("working_set") or after_state.get("working_set") or {}
    affected_working_set_id = affected_snapshot.get("id")
    affected_working_set_name = affected_snapshot.get("name")
    if event_type == "create":
        summary = (
            f"Removed working set {affected_working_set_name or f'#{subject_id}'} "
            f"and restored the prior unscoped state."
        )
    elif event_type == "delete":
        summary = (
            f"Restored working set {affected_working_set_name or f'#{subject_id}'} "
            f"and its saved anchors."
        )
    elif event_type == "context_update":
        summary = "Restored the prior active working-set context and focus mode."
    elif event_type == "bulk_add_items":
        summary = (
            "Restored the previous anchor membership for "
            f"{affected_working_set_name or f'working set #{subject_id}'}."
        )
    else:
        summary = (
            f"Restored the previous working-set state for "
            f"{affected_working_set_name or f'working set #{subject_id}'}."
        )

    return {
        "working_set": working_set_payload,
        "context": context_payload,
        "affected_working_set_id": (
            int(affected_working_set_id) if affected_working_set_id is not None else None
        ),
        "affected_working_set_name": (
            str(affected_working_set_name) if affected_working_set_name is not None else None
        ),
        "undone_event_id": expected_event_id,
        "undone_event_type": event_type,
        "undo_event_id": undo_event_id,
        "summary": summary,
    }


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
        event_id = _record_working_set_event(
            subject_type="working_set",
            subject_id=int(row["id"]),
            event_type="create",
            before_state={"working_set": None, "items": []},
            after_state=_working_set_state_snapshot(working_set_id=int(row["id"]), conn=conn),
            conn=conn,
        )
    payload = _working_set_payload(row, conn=conn)
    payload["latest_reversible_event_id"] = event_id
    payload["latest_reversible_event_type"] = "create"
    return payload


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
    before_state = _working_set_state_snapshot(working_set_id=working_set_id, conn=conn)
    with conn:
        updated = repo.update_working_set(
            working_set_id=working_set_id,
            name=name,
            description=description,
            conn=conn,
        )
        if updated is None:
            raise ValidationError("working_set_id", f"working set {working_set_id} not found")
        _record_working_set_event(
            subject_type="working_set",
            subject_id=working_set_id,
            event_type="update",
            before_state=before_state,
            after_state=_working_set_state_snapshot(working_set_id=working_set_id, conn=conn),
            conn=conn,
        )
    return _working_set_payload(updated, conn=conn)


@typingx.validate_io()
def delete_working_set(*, working_set_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """Delete one working set and return undo metadata."""
    row = _required_working_set(working_set_id=working_set_id, conn=conn)
    before_state = {
        **_working_set_state_snapshot(working_set_id=working_set_id, conn=conn),
        "context": _context_state_snapshot(conn=conn),
    }
    with conn:
        deleted = repo.delete_working_set(working_set_id=working_set_id, conn=conn)
        if not deleted:
            raise ValidationError("working_set_id", f"working set {working_set_id} not found")
        event_id = _record_working_set_event(
            subject_type="working_set",
            subject_id=working_set_id,
            event_type="delete",
            before_state=before_state,
            after_state={
                "working_set": None,
                "items": [],
                "context": _context_state_snapshot(conn=conn),
            },
            conn=conn,
        )
    return {
        "deleted": True,
        "deleted_working_set_id": working_set_id,
        "deleted_working_set_name": str(row["name"]),
        "latest_reversible_event_id": event_id,
        "latest_reversible_event_type": "delete",
        "context": _working_set_context_payload(conn=conn),
    }


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
    before_state = _working_set_state_snapshot(working_set_id=working_set_id, conn=conn)
    with conn:
        _add_working_set_item_impl(
            working_set_id=working_set_id,
            item_type=item_type,
            item_id=item_id,
            label=label,
            description=description,
            metadata=metadata,
            conn=conn,
        )
        _record_working_set_event(
            subject_type="working_set",
            subject_id=working_set_id,
            event_type="add_item",
            before_state=before_state,
            after_state=_working_set_state_snapshot(working_set_id=working_set_id, conn=conn),
            conn=conn,
        )
    return get_working_set(working_set_id=working_set_id, conn=conn)


@typingx.validate_io()
def add_working_set_items_bulk(
    *,
    working_set_id: int,
    items: list[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Add multiple items to a working set atomically."""
    _required_working_set(working_set_id=working_set_id, conn=conn)
    before_state = _working_set_state_snapshot(working_set_id=working_set_id, conn=conn)
    with conn:
        for item in items:
            _add_working_set_item_impl(
                working_set_id=working_set_id,
                item_type=str(item["item_type"]),
                item_id=(int(item["item_id"]) if item.get("item_id") is not None else None),
                label=(str(item["label"]) if item.get("label") is not None else None),
                description=(
                    str(item["description"]) if item.get("description") is not None else None
                ),
                metadata=(
                    item.get("metadata") if isinstance(item.get("metadata"), Mapping) else None
                ),
                conn=conn,
            )
        _record_working_set_event(
            subject_type="working_set",
            subject_id=working_set_id,
            event_type="bulk_add_items",
            before_state=before_state,
            after_state=_working_set_state_snapshot(working_set_id=working_set_id, conn=conn),
            conn=conn,
        )
    return get_working_set(working_set_id=working_set_id, conn=conn)


@typingx.validate_io()
def remove_working_set_item(
    *, working_set_id: int, item_id: int, conn: sqlite3.Connection
) -> dict[str, Any]:
    """Remove one membership row from a working set."""
    working_set = _required_working_set(working_set_id=working_set_id, conn=conn)
    before_state = _working_set_state_snapshot(working_set_id=working_set_id, conn=conn)
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
            _record_working_set_event(
                subject_type="working_set",
                subject_id=working_set_id,
                event_type="remove_item",
                before_state=before_state,
                after_state=_working_set_state_snapshot(working_set_id=working_set_id, conn=conn),
                conn=conn,
            )
    if not deleted:
        raise ValidationError("item_id", f"working-set item {item_id} not found")
    return get_working_set(working_set_id=working_set_id, conn=conn)


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
    before_state = _working_set_state_snapshot(working_set_id=working_set_id, conn=conn)
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
        _record_working_set_event(
            subject_type="working_set",
            subject_id=working_set_id,
            event_type="reorder",
            before_state=before_state,
            after_state=_working_set_state_snapshot(working_set_id=working_set_id, conn=conn),
            conn=conn,
        )
    refreshed = _required_working_set(working_set_id=working_set_id, conn=conn)
    return _working_set_payload(refreshed, conn=conn)


@typingx.validate_io()
def get_working_set_context(*, conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the active working-set/focus-mode context."""
    return _working_set_context_payload(conn=conn)


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
    before_state = _context_state_snapshot(conn=conn)
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
        _record_working_set_event(
            subject_type="working_set_context",
            subject_id=_WORKING_SET_CONTEXT_SUBJECT_ID,
            event_type="context_update",
            before_state=before_state,
            after_state=_context_state_snapshot(conn=conn),
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
    "add_working_set_items_bulk",
    "remove_working_set_item",
    "reorder_working_set_items",
    "get_working_set_context",
    "update_working_set_context",
    "undo_working_set_event",
]
