"""Planning execution rollback helpers.

Purpose:
    Define rollback metadata and perform best-effort rollback for partially
    executed planning checkpoints.

Responsibilities:
    - Build rollback action payloads for supported resource kinds
    - Execute rollback actions against loops, views, templates, and review sessions
    - Summarize rollback attempts and failures after partial execution

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Rollback metadata and execution only
    - No checkpoint validation or forward execution dispatch

Usage:
    Imported by planning execution operations and the planning service.

Invariants/Assumptions:
    - Rollback actions execute in reverse result/order order
    - Unsupported rollback kinds fail loudly rather than silently skipping
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from .. import events as loop_events
from .. import repo
from ..errors import ResourceNotFoundError


def _rollback_action(
    *,
    kind: str,
    resource_type: str,
    resource_id: int,
    summary: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "kind": kind,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "summary": summary,
    }
    if payload:
        action["payload"] = dict(payload)
    return action


def _loop_undo_action(*, loop_id: int, summary: str) -> dict[str, Any]:
    return _rollback_action(
        kind="loop.undo",
        resource_type="loop",
        resource_id=loop_id,
        summary=summary,
        payload={"loop_id": loop_id},
    )


def _execute_rollback_action(*, action: Mapping[str, Any], conn: sqlite3.Connection) -> None:
    kind = str(action.get("kind") or "")
    resource_id = int(action["resource_id"])
    payload = dict(action.get("payload") or {})

    if kind == "loop.undo":
        loop_events.undo_last_event(loop_id=resource_id, conn=conn)
        return
    if kind == "planning.loop.delete":
        if not repo.delete_loop(loop_id=resource_id, conn=conn):
            raise ResourceNotFoundError("loop", f"Loop not found for rollback: {resource_id}")
        return
    if kind in {"review.relationship.session.delete", "review.enrichment.session.delete"}:
        if not repo.delete_review_session(session_id=resource_id, conn=conn):
            raise ResourceNotFoundError(
                "review session", f"Review session not found for rollback: {resource_id}"
            )
        return
    if kind == "loop.view.delete":
        if not repo.delete_loop_view(view_id=resource_id, conn=conn):
            raise ResourceNotFoundError("view", f"Saved view not found for rollback: {resource_id}")
        return
    if kind == "loop.view.update":
        repo.update_loop_view(
            view_id=resource_id,
            name=payload.get("name"),
            query=payload.get("query"),
            description=payload.get("description"),
            conn=conn,
        )
        return
    if kind == "loop.template.delete":
        if not repo.delete_loop_template(template_id=resource_id, conn=conn):
            raise ResourceNotFoundError(
                "template", f"Loop template not found for rollback: {resource_id}"
            )
        return
    if kind == "loop.template.update":
        repo.update_loop_template(
            template_id=resource_id,
            name=payload.get("name"),
            description=payload.get("description"),
            raw_text_pattern=payload.get("raw_text_pattern"),
            defaults_json=payload.get("defaults_json"),
            conn=conn,
        )
        return

    raise RuntimeError(f"unsupported planning rollback action: {kind}")


def _rollback_execution_results(
    *,
    results: Sequence[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    attempted = 0
    failed_actions: list[dict[str, Any]] = []
    for result in reversed(results):
        for action in reversed(list(result.get("rollback_actions") or [])):
            attempted += 1
            try:
                _execute_rollback_action(action=action, conn=conn)
            except Exception as exc:  # noqa: BLE001
                failed_actions.append(
                    {
                        "kind": action.get("kind"),
                        "resource_type": action.get("resource_type"),
                        "resource_id": action.get("resource_id"),
                        "message": str(exc),
                    }
                )
    return {
        "attempted_action_count": attempted,
        "failed_action_count": len(failed_actions),
        "failed_actions": failed_actions,
        "rollback_complete": len(failed_actions) == 0,
    }


__all__ = [
    "_rollback_action",
    "_loop_undo_action",
    "_execute_rollback_action",
    "_rollback_execution_results",
]
