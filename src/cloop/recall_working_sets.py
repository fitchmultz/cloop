"""Recall working-set scope helpers.

Purpose:
    Resolve optional working-set scope for recall-side chat and document-answer
    flows so backend-authored rerun and follow-through contracts can carry the
    same bounded context across HTTP, CLI, MCP, and continuity surfaces.

Responsibilities:
    - Validate explicit recall working-set ids against durable working sets.
    - Shape compact working-set handoff metadata for recall follow-through payloads.
    - Keep recall transports on one shared working-set summary contract.

Non-scope:
    - Working-set CRUD or focus-mode mutations.
    - Recall answer generation, retrieval, or frontend rendering.
"""

from __future__ import annotations

from typing import Any

from . import db
from .loops import working_sets
from .settings import Settings


def resolve_recall_working_set(
    *, working_set_id: int | None, settings: Settings
) -> dict[str, Any] | None:
    """Resolve one optional recall working-set scope into compact handoff metadata."""
    if working_set_id is None:
        return None
    with db.core_connection(settings) as conn:
        payload = working_sets.get_working_set(working_set_id=working_set_id, conn=conn)
    return {
        "working_set_id": int(payload["id"]),
        "working_set_name": str(payload.get("name") or f"Working set #{working_set_id}"),
        "item_count": int(payload.get("item_count") or 0),
        "missing_item_count": int(payload.get("missing_item_count") or 0),
    }


__all__ = ["resolve_recall_working_set"]
