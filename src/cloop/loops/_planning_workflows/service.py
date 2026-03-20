"""Planning workflow service operations.

Purpose:
    Provide durable planning-session CRUD, refresh, movement, and checkpoint
    execution by composing the focused planning helper modules.

Responsibilities:
    - Create and refresh planning sessions from grounded planner output
    - Materialize planning session listings and snapshots
    - Move the current checkpoint cursor through a saved session
    - Execute one checkpoint and persist durable execution history

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Public planning workflow orchestration used by CLI, HTTP, MCP, and web flows
    - No transport-specific response shaping

Usage:
    Imported by `cloop.loops.planning_workflows` and sibling transports.

Invariants/Assumptions:
    - Planning sessions are identified by durable repo rows
    - Each checkpoint may execute at most once per generated plan version
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ... import typingx
from ...settings import Settings
from .. import repo, working_sets
from ..errors import ResourceNotFoundError, ValidationError
from .execution import (
    _execute_plan_operation,
    _rollback_execution_results,
    _validate_checkpoint_for_execution,
)
from .generation import _generate_workflow_plan
from .inputs import (
    _normalize_name,
    _normalize_optional_query,
    _normalize_prompt,
    _validate_move_direction,
    _validate_options,
)
from .models import PlanningCheckpointModel
from .snapshot import (
    _build_execution_summary,
    _build_follow_up_resources,
    _build_launch_surfaces,
    _build_planning_session_snapshot,
    _build_resource_change_summary,
    _build_rollback_cues,
    _move_checkpoint_index,
    _next_checkpoint_index,
    _planning_session_payload,
    _require_planning_session_row,
)


def create_planning_session_impl(
    *,
    name: str,
    prompt: str,
    query: str | None,
    loop_limit: int,
    include_memory_context: bool,
    include_rag_context: bool,
    rag_k: int,
    rag_scope: str | None,
    conn: sqlite3.Connection,
    settings: Settings,
    planner_chat_completion: Any,
) -> dict[str, Any]:
    normalized_name = _normalize_name(name, field="name")
    normalized_prompt = _normalize_prompt(prompt)
    normalized_query = _normalize_optional_query(query)
    options = _validate_options(
        {
            "loop_limit": loop_limit,
            "include_memory_context": include_memory_context,
            "include_rag_context": include_rag_context,
            "rag_k": rag_k,
            "rag_scope": rag_scope,
        }
    )
    generated = _generate_workflow_plan(
        prompt=normalized_prompt,
        query=normalized_query,
        options=options,
        conn=conn,
        settings=settings,
        planner_chat_completion=planner_chat_completion,
    )
    try:
        with conn:
            row = repo.create_planning_session(
                name=normalized_name,
                prompt=normalized_prompt,
                query=normalized_query,
                options_json=options,
                plan_json=generated,
                current_checkpoint_index=0,
                conn=conn,
            )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name",
            f"planning session '{normalized_name}' already exists",
        ) from None
    return _build_planning_session_snapshot(session_row=row, conn=conn)


@typingx.validate_io()
def list_planning_sessions(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for row in repo.list_planning_sessions(conn=conn):
        execution_rows = repo.list_planning_session_runs(session_id=int(row["id"]), conn=conn)
        sessions.append(_planning_session_payload(row, execution_rows=execution_rows))
    return sessions


@typingx.validate_io()
def get_planning_session(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    return _build_planning_session_snapshot(
        session_row=_require_planning_session_row(session_id=session_id, conn=conn),
        conn=conn,
    )


@typingx.validate_io()
def move_planning_session(
    *,
    session_id: int,
    direction: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    session_row = _require_planning_session_row(session_id=session_id, conn=conn)
    plan_json = json.loads(str(session_row.get("plan_json") or "{}"))
    checkpoints = list((plan_json.get("workflow") or {}).get("checkpoints") or [])
    normalized_direction = _validate_move_direction(direction)
    target_index = _move_checkpoint_index(
        current_index=int(session_row.get("current_checkpoint_index") or 0),
        checkpoint_count=len(checkpoints),
        direction=normalized_direction,
    )
    with conn:
        updated = repo.update_planning_session(
            session_id=session_id,
            current_checkpoint_index=target_index,
            conn=conn,
        )
    if updated is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return _build_planning_session_snapshot(session_row=updated, conn=conn)


def refresh_planning_session_impl(
    *,
    session_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
    planner_chat_completion: Any,
) -> dict[str, Any]:
    session_row = _require_planning_session_row(session_id=session_id, conn=conn)
    options = _validate_options(json.loads(str(session_row.get("options_json") or "{}")))
    generated = _generate_workflow_plan(
        prompt=str(session_row["prompt"]),
        query=str(session_row["query"]) if session_row.get("query") is not None else None,
        options=options,
        conn=conn,
        settings=settings,
        planner_chat_completion=planner_chat_completion,
    )
    with conn:
        repo.delete_planning_session_runs(session_id=session_id, conn=conn)
        updated = repo.update_planning_session(
            session_id=session_id,
            plan_json=generated,
            current_checkpoint_index=0,
            conn=conn,
        )
    if updated is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return _build_planning_session_snapshot(session_row=updated, conn=conn)


@typingx.validate_io()
def delete_planning_session(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    _require_planning_session_row(session_id=session_id, conn=conn)
    with conn:
        repo.delete_planning_session(session_id=session_id, conn=conn)
    return {"deleted": True, "session_id": session_id}


@typingx.validate_io()
def execute_planning_session_checkpoint(
    *,
    session_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    session_row = _require_planning_session_row(session_id=session_id, conn=conn)
    snapshot = _build_planning_session_snapshot(session_row=session_row, conn=conn)
    session = snapshot["session"]
    checkpoints = snapshot["checkpoints"]
    if not checkpoints:
        raise ValidationError("session_id", "planning session has no checkpoints")

    checkpoint_index = int(session["current_checkpoint_index"])
    executed_indices = {int(entry["checkpoint_index"]) for entry in snapshot["execution_history"]}
    if checkpoint_index in executed_indices:
        raise ValidationError(
            "session_id",
            (
                f"checkpoint {checkpoint_index + 1} has already been executed "
                "for this planning session"
            ),
        )

    raw_checkpoint = checkpoints[checkpoint_index]
    try:
        checkpoint = PlanningCheckpointModel.model_validate(raw_checkpoint)
    except PydanticValidationError as exc:
        raise ValidationError("checkpoint", f"stored checkpoint is invalid: {exc}") from exc

    _validate_checkpoint_for_execution(checkpoint=checkpoint, conn=conn)

    working_set_context = working_sets.get_working_set_context(conn=conn)
    active_working_set_id = working_set_context.get("active_working_set_id")
    resolved_working_set_id = (
        int(active_working_set_id) if active_working_set_id is not None else None
    )

    results: list[dict[str, Any]] = []
    try:
        for operation_index, operation in enumerate(checkpoint.operations):
            results.append(
                _execute_plan_operation(
                    operation=operation,
                    index=operation_index,
                    conn=conn,
                    settings=settings,
                    active_working_set_id=resolved_working_set_id,
                )
            )
    except Exception as exc:  # noqa: BLE001
        rollback_summary = _rollback_execution_results(
            results=results,
            conn=conn,
            checkpoint_index=checkpoint_index,
            checkpoint_title=checkpoint.title,
        )
        rollback_note = (
            "rollback completed"
            if rollback_summary["rollback_complete"]
            else (
                "rollback incomplete: "
                f"{rollback_summary['failed_action_count']} rollback actions failed"
            )
        )
        raise ValidationError(
            "checkpoint",
            (
                f"checkpoint execution failed after {len(results)} successful operations: {exc}; "
                f"{rollback_note}"
            ),
        ) from exc

    follow_up_resources = _build_follow_up_resources(results)
    resource_change_summary = _build_resource_change_summary(results)
    execution_payload = {
        "session_id": session_id,
        "checkpoint_index": checkpoint_index,
        "checkpoint_title": checkpoint.title,
        "checkpoint_summary": checkpoint.summary,
        "success_criteria": checkpoint.success_criteria,
        "results": results,
        "summary": _build_execution_summary(results),
        "resource_change_summary": resource_change_summary,
        "follow_up_resources": follow_up_resources,
        "launch_surfaces": _build_launch_surfaces(
            results=results,
            follow_up_resources=follow_up_resources,
        ),
        "rollback_cues": _build_rollback_cues(results),
    }

    with conn:
        run_row = repo.create_planning_session_run(
            session_id=session_id,
            checkpoint_index=checkpoint_index,
            result_json=execution_payload,
            conn=conn,
        )
        next_index = _next_checkpoint_index(
            checkpoint_count=len(checkpoints),
            current_index=checkpoint_index,
            executed_indices={*executed_indices, checkpoint_index},
        )
        updated = repo.update_planning_session(
            session_id=session_id,
            current_checkpoint_index=next_index,
            conn=conn,
        )

    if updated is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")

    snapshot_after = _build_planning_session_snapshot(session_row=updated, conn=conn)
    response_execution_payload: dict[str, Any] = {
        **execution_payload,
        "run_id": int(run_row["id"]),
        "executed_at_utc": str(run_row["created_at"]),
        "rollback": None,
        "is_active": True,
    }
    return {"execution": response_execution_payload, "snapshot": snapshot_after}


@typingx.validate_io()
def rollback_planning_session_run(
    *,
    session_id: int,
    run_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    _require_planning_session_row(session_id=session_id, conn=conn)
    execution_rows = repo.list_planning_session_runs(session_id=session_id, conn=conn)
    target_row = next((row for row in execution_rows if int(row["id"]) == run_id), None)
    if target_row is None:
        raise ResourceNotFoundError(
            "planning execution",
            f"Planning execution not found: session={session_id}, run={run_id}",
        )

    active_rows = [
        row
        for row in execution_rows
        if not bool(
            (json.loads(str(row.get("result_json") or "{}")) if row.get("result_json") else {})
            .get("rollback", {})
            .get("rollback_complete", False)
        )
    ]
    latest_active_row = active_rows[-1] if active_rows else None
    if latest_active_row is None or int(latest_active_row["id"]) != run_id:
        latest_active_run_id = (
            int(latest_active_row["id"]) if latest_active_row is not None else None
        )
        latest_active_label = (
            str(latest_active_run_id) if latest_active_run_id is not None else "none"
        )
        raise ValidationError(
            "run_id",
            f"rollback handle is stale; latest active run is {latest_active_label}",
        )

    payload = (
        json.loads(str(target_row.get("result_json") or "{}"))
        if target_row.get("result_json")
        else {}
    )
    if bool((payload.get("rollback") or {}).get("rollback_complete", False)):
        raise ValidationError("run_id", f"planning execution {run_id} has already been rolled back")

    results = list(payload.get("results") or [])
    rollback_action_count = sum(
        len(list(result.get("rollback_actions") or [])) for result in results
    )
    if rollback_action_count < 1:
        raise ValidationError(
            "run_id",
            f"planning execution {run_id} does not have rollback actions",
        )

    checkpoint_index = int(target_row["checkpoint_index"])
    checkpoint_title = str(payload.get("checkpoint_title") or "")

    with conn:
        rollback_summary = _rollback_execution_results(
            results=results,
            conn=conn,
            checkpoint_index=checkpoint_index,
            checkpoint_title=checkpoint_title,
            run_id=run_id,
        )
        updated_payload = {**payload, "rollback": rollback_summary}
        repo.update_planning_session_run(
            run_id=run_id,
            result_json=updated_payload,
            conn=conn,
        )
        if rollback_summary["rollback_complete"]:
            updated_session = repo.update_planning_session(
                session_id=session_id,
                current_checkpoint_index=checkpoint_index,
                conn=conn,
            )
        else:
            updated_session = repo.get_planning_session(session_id=session_id, conn=conn)

    if updated_session is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")

    snapshot_after = _build_planning_session_snapshot(session_row=updated_session, conn=conn)
    return {"rollback": rollback_summary, "snapshot": snapshot_after}


__all__ = [
    "create_planning_session_impl",
    "list_planning_sessions",
    "get_planning_session",
    "move_planning_session",
    "refresh_planning_session_impl",
    "delete_planning_session",
    "execute_planning_session_checkpoint",
    "rollback_planning_session_run",
]
