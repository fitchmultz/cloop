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
from .. import repo, working_sets
from ..errors import ResourceNotFoundError, ValidationError
from ..models import format_utc_datetime, utc_now


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


def _loop_undo_action(*, loop_id: int, expected_event_id: int, summary: str) -> dict[str, Any]:
    return _rollback_action(
        kind="loop.undo",
        resource_type="loop",
        resource_id=loop_id,
        summary=summary,
        payload={"loop_id": loop_id, "expected_event_id": expected_event_id},
    )


def _execute_rollback_action(*, action: Mapping[str, Any], conn: sqlite3.Connection) -> None:
    kind = str(action.get("kind") or "")
    resource_id = int(action["resource_id"])
    payload = dict(action.get("payload") or {})

    if kind == "loop.undo":
        expected_event_id = payload.get("expected_event_id")
        if not isinstance(expected_event_id, int):
            raise ValidationError(
                "rollback_action",
                "loop.undo rollback actions require expected_event_id",
            )
        loop_events.undo_last_event(
            loop_id=resource_id,
            expected_event_id=expected_event_id,
            conn=conn,
        )
        return
    if kind == "planning.loop.delete":
        if not repo.delete_loop(loop_id=resource_id, conn=conn):
            raise ResourceNotFoundError("loop", f"Loop not found for rollback: {resource_id}")
        return
    if kind in {"review.relationship.session.delete", "review.enrichment.session.delete"}:
        working_sets._delete_working_set_items_for_target(
            item_type=(
                "relationship_review_session"
                if kind == "review.relationship.session.delete"
                else "enrichment_review_session"
            ),
            item_id=resource_id,
            conn=conn,
        )
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


def _rollback_summary_payload(
    *,
    attempted: int,
    failed_actions: Sequence[Mapping[str, Any]],
    checkpoint_index: int | None = None,
    checkpoint_title: str | None = None,
    run_id: int | None = None,
) -> dict[str, Any]:
    rollback_complete = len(failed_actions) == 0
    summary_bits: list[str] = []
    if checkpoint_title:
        summary_bits.append(f"Rolled back {checkpoint_title}")
    else:
        summary_bits.append("Rollback attempted")
    if rollback_complete:
        summary_bits.append(f"{attempted} rollback action{'s' if attempted != 1 else ''} completed")
    else:
        summary_bits.append(
            f"{len(failed_actions)} rollback action{'s' if len(failed_actions) != 1 else ''} failed"
        )

    payload = {
        "attempted_action_count": attempted,
        "failed_action_count": len(failed_actions),
        "failed_actions": [dict(action) for action in failed_actions],
        "rollback_complete": rollback_complete,
        "rolled_back_at_utc": format_utc_datetime(utc_now()),
        "summary": "; ".join(summary_bits),
    }
    if checkpoint_index is not None:
        payload["checkpoint_index"] = checkpoint_index
    if checkpoint_title is not None:
        payload["checkpoint_title"] = checkpoint_title
    if run_id is not None:
        payload["run_id"] = run_id
    return payload


def _rollback_execution_results(
    *,
    results: Sequence[Mapping[str, Any]],
    conn: sqlite3.Connection,
    checkpoint_index: int | None = None,
    checkpoint_title: str | None = None,
    run_id: int | None = None,
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
    return _rollback_summary_payload(
        attempted=attempted,
        failed_actions=failed_actions,
        checkpoint_index=checkpoint_index,
        checkpoint_title=checkpoint_title,
        run_id=run_id,
    )


__all__ = [
    "_rollback_action",
    "_loop_undo_action",
    "_execute_rollback_action",
    "_rollback_execution_results",
]
