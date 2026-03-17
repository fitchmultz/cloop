"""Planning workflow snapshot and summary helpers.

Purpose:
    Build durable planning-session payloads, execution history summaries,
    freshness metadata, and operator handoff metadata from stored planning rows.

Responsibilities:
    - Materialize planning session metadata from persisted rows
    - Summarize execution history and operator follow-up resources
    - Build launch-surface and rollback-cue payloads from execution results
    - Evaluate grounding freshness against current loop state
    - Snapshot existing loops for before/after execution reporting

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Planning session snapshot shaping and summary logic
    - No planner invocation or deterministic checkpoint execution

Usage:
    Imported by planning service and execution modules.

Invariants/Assumptions:
    - Execution rows are append-only per checkpoint run
    - Session snapshot payloads remain transport-agnostic and serializable
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from .. import read_service, repo
from ..errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ..models import format_utc_datetime, parse_utc_datetime
from .inputs import _validate_options
from .models import PlanningMoveDirection, PlanningSessionStatus

_FOLLOW_UP_RESOURCE_TYPES = {"review_session", "view", "template"}


def _require_planning_session_row(*, session_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    row = repo.get_planning_session(session_id=session_id, conn=conn)
    if row is None:
        raise ResourceNotFoundError("planning session", f"Planning session not found: {session_id}")
    return row


def _next_unexecuted_checkpoint_index(
    *,
    checkpoint_count: int,
    executed_indices: set[int],
) -> int | None:
    for index in range(checkpoint_count):
        if index not in executed_indices:
            return index
    return None


def _collect_resource_ids(
    *,
    results: Sequence[Mapping[str, Any]],
    resource_type: str,
    roles: set[str] | None = None,
) -> list[int]:
    collected: list[int] = []
    seen_ids: set[int] = set()
    for result in results:
        for resource in result.get("resource_refs", []):
            if str(resource.get("resource_type")) != resource_type:
                continue
            if roles is not None and str(resource.get("role")) not in roles:
                continue
            resource_id = resource.get("resource_id")
            if not isinstance(resource_id, int) or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
    return collected


def _build_execution_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    created_loop_ids = _collect_resource_ids(
        results=results,
        resource_type="loop",
        roles={"created"},
    )
    touched_loop_ids = _collect_resource_ids(
        results=results,
        resource_type="loop",
        roles={"created", "updated", "transitioned", "closed", "enriched", "snoozed"},
    )
    created_review_session_ids = _collect_resource_ids(
        results=results,
        resource_type="review_session",
        roles={"created"},
    )
    created_view_ids = _collect_resource_ids(
        results=results,
        resource_type="view",
        roles={"created"},
    )
    updated_view_ids = _collect_resource_ids(
        results=results,
        resource_type="view",
        roles={"updated"},
    )
    created_template_ids = _collect_resource_ids(
        results=results,
        resource_type="template",
        roles={"created"},
    )
    updated_template_ids = _collect_resource_ids(
        results=results,
        resource_type="template",
        roles={"updated"},
    )
    return {
        "operation_kinds": [str(result.get("kind") or "") for result in results],
        "touched_loop_ids": touched_loop_ids,
        "created_loop_ids": created_loop_ids,
        "created_review_session_ids": created_review_session_ids,
        "created_view_ids": created_view_ids,
        "updated_view_ids": updated_view_ids,
        "created_template_ids": created_template_ids,
        "updated_template_ids": updated_template_ids,
        "undoable_operation_count": sum(1 for result in results if result.get("undoable")),
        "rollback_supported_operation_count": sum(
            1 for result in results if result.get("rollback_supported")
        ),
        "follow_up_resource_count": (
            len(created_review_session_ids)
            + len(created_view_ids)
            + len(updated_view_ids)
            + len(created_template_ids)
            + len(updated_template_ids)
        ),
    }


def _result_payload_mapping(result: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = result.get("result")
    return payload if isinstance(payload, Mapping) else {}


def _result_session_payload(result: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _result_payload_mapping(result)
    session = payload.get("session")
    if isinstance(session, Mapping):
        return session
    snapshot = payload.get("snapshot")
    if isinstance(snapshot, Mapping):
        nested_session = snapshot.get("session")
        if isinstance(nested_session, Mapping):
            return nested_session
    return {}


def _build_follow_up_resource_details(
    *,
    result: Mapping[str, Any],
    resource: Mapping[str, Any],
) -> dict[str, Any]:
    resource_type = str(resource.get("resource_type") or "")
    payload = _result_payload_mapping(result)

    if resource_type == "review_session":
        session = _result_session_payload(result)
        metadata = resource.get("metadata")
        metadata_mapping = metadata if isinstance(metadata, Mapping) else {}
        details: dict[str, Any] = {}
        review_kind = (
            str(metadata_mapping.get("review_kind") or session.get("review_kind") or "").strip()
            or None
        )
        if review_kind is not None:
            details["review_kind"] = review_kind
        if session.get("name") is not None or resource.get("label") is not None:
            details["name"] = session.get("name") or resource.get("label")
        if session.get("query") is not None:
            details["query"] = session.get("query")
        if payload.get("loop_count") is not None:
            details["loop_count"] = int(payload["loop_count"])
        if session.get("current_loop_id") is not None:
            details["current_loop_id"] = int(session["current_loop_id"])
        return details

    if resource_type == "view":
        details = {}
        if payload.get("name") is not None or resource.get("label") is not None:
            details["name"] = payload.get("name") or resource.get("label")
        if payload.get("query") is not None:
            details["query"] = payload.get("query")
        if payload.get("description") is not None:
            details["description"] = payload.get("description")
        return details

    if resource_type == "template":
        details = {}
        if payload.get("name") is not None or resource.get("label") is not None:
            details["name"] = payload.get("name") or resource.get("label")
        if payload.get("description") is not None:
            details["description"] = payload.get("description")
        if payload.get("raw_text_pattern") is not None:
            details["raw_text_pattern"] = payload.get("raw_text_pattern")
        return details

    return {}


def _build_launch_surface(
    *,
    resource: Mapping[str, Any],
    details: Mapping[str, Any],
) -> dict[str, Any] | None:
    resource_type = str(resource.get("resource_type") or "")
    if resource_type != "review_session":
        return None

    resource_id = int(resource["resource_id"])
    review_kind = str(details.get("review_kind") or "").strip()
    label = str(resource.get("label") or details.get("name") or f"Review session #{resource_id}")

    if review_kind == "relationship":
        return {
            "surface": "relationship_review_session",
            "label": label,
            "resource_type": "review_session",
            "resource_id": resource_id,
            "reason": "This checkpoint created the next deterministic relationship-review queue.",
            "http": {
                "method": "GET",
                "path": f"/loops/review/relationship/sessions/{resource_id}",
            },
            "mcp": {
                "tool": "review.relationship_session.get",
                "args": {"session_id": resource_id},
            },
            "web": {
                "surface": "review_session",
                "review_kind": "relationship",
                "session_id": resource_id,
            },
        }

    if review_kind == "enrichment":
        return {
            "surface": "enrichment_review_session",
            "label": label,
            "resource_type": "review_session",
            "resource_id": resource_id,
            "reason": "This checkpoint created the next deterministic enrichment-review queue.",
            "http": {
                "method": "GET",
                "path": f"/loops/review/enrichment/sessions/{resource_id}",
            },
            "mcp": {
                "tool": "review.enrichment_session.get",
                "args": {"session_id": resource_id},
            },
            "web": {
                "surface": "review_session",
                "review_kind": "enrichment",
                "session_id": resource_id,
            },
        }

    return None


def _build_follow_up_resources(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for result in results:
        for raw_resource in result.get("resource_refs", []):
            resource = raw_resource if isinstance(raw_resource, Mapping) else {}
            resource_type = str(resource.get("resource_type") or "")
            role = str(resource.get("role") or "")
            if resource_type not in _FOLLOW_UP_RESOURCE_TYPES or role not in {"created", "updated"}:
                continue

            resource_id = int(resource["resource_id"])
            key = (resource_type, resource_id, role)
            if key in seen:
                continue
            seen.add(key)

            details = _build_follow_up_resource_details(result=result, resource=resource)
            launch_surface = _build_launch_surface(resource=resource, details=details)

            resources.append(
                {
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "role": role,
                    "label": resource.get("label"),
                    "operation_index": int(result.get("index") or 0),
                    "operation_kind": str(result.get("kind") or ""),
                    "operation_summary": str(result.get("summary") or ""),
                    "details": details,
                    "launch_surface": launch_surface,
                }
            )

    return resources


def _build_launch_surfaces(
    *,
    results: Sequence[Mapping[str, Any]],
    follow_up_resources: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    resources = (
        list(follow_up_resources)
        if follow_up_resources is not None
        else _build_follow_up_resources(results)
    )
    surfaces: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for resource in resources:
        launch_surface = resource.get("launch_surface")
        if not isinstance(launch_surface, Mapping):
            continue
        key = (
            str(launch_surface.get("surface") or ""),
            int(launch_surface["resource_id"]),
        )
        if key in seen:
            continue
        seen.add(key)
        surfaces.append(dict(launch_surface))

    return surfaces


def _build_rollback_cues(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    rollback_action_count = 0

    for result in results:
        rollback_actions = list(result.get("rollback_actions") or [])
        rollback_action_count += len(rollback_actions)
        operations.append(
            {
                "index": int(result.get("index") or 0),
                "kind": str(result.get("kind") or ""),
                "summary": str(result.get("summary") or ""),
                "undoable": bool(result.get("undoable", False)),
                "rollback_supported": bool(result.get("rollback_supported", False)),
                "rollback_action_count": len(rollback_actions),
            }
        )

    return {
        "rollback_supported_operation_count": sum(
            1 for operation in operations if operation["rollback_supported"]
        ),
        "undoable_operation_count": sum(1 for operation in operations if operation["undoable"]),
        "rollback_action_count": rollback_action_count,
        "operations": operations,
    }


def _planning_session_payload(
    row: Mapping[str, Any],
    *,
    execution_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    options = _validate_options(json.loads(str(row.get("options_json") or "{}")))
    workflow = json.loads(str(row.get("plan_json") or "{}"))
    workflow_payload = dict(workflow.get("workflow") or {})
    checkpoints = list(workflow_payload.get("checkpoints") or [])
    executed_indices = {int(entry["checkpoint_index"]) for entry in execution_rows}
    executed_checkpoint_count = len(executed_indices)
    status: PlanningSessionStatus = "draft"
    if executed_checkpoint_count >= len(checkpoints):
        status = "completed"
    elif executed_checkpoint_count > 0:
        status = "in_progress"

    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "prompt": str(row["prompt"]),
        "query": str(row["query"]) if row.get("query") is not None else None,
        "loop_limit": int(options["loop_limit"]),
        "include_memory_context": bool(options["include_memory_context"]),
        "include_rag_context": bool(options["include_rag_context"]),
        "rag_k": int(options["rag_k"]),
        "rag_scope": options.get("rag_scope"),
        "current_checkpoint_index": int(row.get("current_checkpoint_index") or 0),
        "checkpoint_count": len(checkpoints),
        "executed_checkpoint_count": executed_checkpoint_count,
        "next_unexecuted_checkpoint_index": _next_unexecuted_checkpoint_index(
            checkpoint_count=len(checkpoints),
            executed_indices=executed_indices,
        ),
        "generated_at_utc": (workflow_payload.get("context_summary") or {}).get("generated_at_utc"),
        "last_executed_at_utc": str(execution_rows[-1]["created_at"]) if execution_rows else None,
        "status": status,
        "created_at_utc": str(row["created_at"]),
        "updated_at_utc": str(row["updated_at"]),
    }


def _build_execution_history(
    execution_rows: Sequence[Mapping[str, Any]],
    *,
    checkpoints: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for row in execution_rows:
        payload = json.loads(str(row["result_json"])) if row.get("result_json") else {}
        checkpoint_index = int(row["checkpoint_index"])
        checkpoint_title = ""
        if 0 <= checkpoint_index < len(checkpoints):
            checkpoint_title = str(checkpoints[checkpoint_index].get("title") or "")

        results = list(payload.get("results") or [])
        follow_up_resources = list(
            payload.get("follow_up_resources") or _build_follow_up_resources(results)
        )
        launch_surfaces = list(
            payload.get("launch_surfaces")
            or _build_launch_surfaces(
                results=results,
                follow_up_resources=follow_up_resources,
            )
        )
        rollback_cues = dict(payload.get("rollback_cues") or _build_rollback_cues(results))

        history.append(
            {
                "checkpoint_index": checkpoint_index,
                "checkpoint_title": checkpoint_title,
                "executed_at_utc": str(row["created_at"]),
                "operation_count": len(results),
                "results": results,
                "summary": dict(payload.get("summary") or _build_execution_summary(results)),
                "follow_up_resources": [dict(item) for item in follow_up_resources],
                "launch_surfaces": [dict(item) for item in launch_surfaces],
                "rollback_cues": rollback_cues,
            }
        )
    return history


def _build_context_freshness(
    *,
    context_summary: Mapping[str, Any],
    target_loops: Sequence[Mapping[str, Any]],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    generated_at_utc = context_summary.get("generated_at_utc")
    if not generated_at_utc:
        return {}

    try:
        generated_at = parse_utc_datetime(str(generated_at_utc))
    except ValueError:
        return {"generated_at_utc": generated_at_utc, "is_stale": False}

    target_loop_ids = [int(loop["id"]) for loop in target_loops if loop.get("id") is not None]
    records = repo.read_loops_batch(loop_ids=target_loop_ids, conn=conn)
    stale_target_loop_ids: list[int] = []
    missing_target_loop_ids: list[int] = []
    latest_target_update = None

    for loop_id in target_loop_ids:
        record = records.get(loop_id)
        if record is None:
            missing_target_loop_ids.append(loop_id)
            continue
        if latest_target_update is None or record.updated_at_utc > latest_target_update:
            latest_target_update = record.updated_at_utc
        if record.updated_at_utc > generated_at:
            stale_target_loop_ids.append(loop_id)

    return {
        "generated_at_utc": str(generated_at_utc),
        "target_loop_count": len(target_loop_ids),
        "stale_target_loop_ids": stale_target_loop_ids,
        "stale_target_loop_count": len(stale_target_loop_ids),
        "missing_target_loop_ids": missing_target_loop_ids,
        "latest_target_loop_update_at_utc": (
            format_utc_datetime(latest_target_update) if latest_target_update is not None else None
        ),
        "is_stale": bool(stale_target_loop_ids or missing_target_loop_ids),
    }


def _build_execution_analytics(
    *,
    execution_history: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    executed_checkpoint_indexes = [int(item["checkpoint_index"]) for item in execution_history]
    all_results = [
        result for item in execution_history for result in list(item.get("results") or [])
    ]
    summary = _build_execution_summary(all_results)
    summary.update(
        {
            "executed_checkpoint_indexes": executed_checkpoint_indexes,
            "remaining_checkpoint_indexes": [
                index
                for index in range(len(checkpoints))
                if index not in executed_checkpoint_indexes
            ],
            "last_executed_at_utc": (
                str(execution_history[-1]["executed_at_utc"]) if execution_history else None
            ),
            "total_operations_executed": len(all_results),
            "completed": bool(checkpoints) and len(executed_checkpoint_indexes) >= len(checkpoints),
        }
    )
    return summary


def _build_planning_session_snapshot(
    *,
    session_row: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    execution_rows = repo.list_planning_session_runs(session_id=int(session_row["id"]), conn=conn)
    session = _planning_session_payload(session_row, execution_rows=execution_rows)
    plan_json = json.loads(str(session_row.get("plan_json") or "{}"))
    workflow = dict(plan_json.get("workflow") or {})
    checkpoints = list(workflow.get("checkpoints") or [])
    current_index = int(session["current_checkpoint_index"]) if checkpoints else 0
    current_checkpoint = checkpoints[current_index] if checkpoints else None
    execution_history = _build_execution_history(execution_rows, checkpoints=checkpoints)
    context_summary = dict(workflow.get("context_summary") or {})
    target_loops = list(workflow.get("target_loops") or [])

    return {
        "session": session,
        "plan_title": str(workflow.get("title") or ""),
        "plan_summary": str(workflow.get("summary") or ""),
        "assumptions": list(workflow.get("assumptions") or []),
        "context_summary": context_summary,
        "context_freshness": _build_context_freshness(
            context_summary=context_summary,
            target_loops=target_loops,
            conn=conn,
        ),
        "execution_analytics": _build_execution_analytics(
            execution_history=execution_history,
            checkpoints=checkpoints,
        ),
        "target_loops": target_loops,
        "sources": list(workflow.get("sources") or []),
        "checkpoints": checkpoints,
        "current_checkpoint": current_checkpoint,
        "execution_history": execution_history,
    }


def _move_checkpoint_index(
    *,
    current_index: int,
    checkpoint_count: int,
    direction: PlanningMoveDirection,
) -> int:
    if checkpoint_count < 1:
        raise ValidationError("direction", "planning session has no checkpoints")
    target_index = current_index + (1 if direction == "next" else -1)
    if target_index < 0 or target_index >= checkpoint_count:
        raise ValidationError(
            "direction",
            f"no {direction} checkpoint available in this planning session",
        )
    return target_index


def _unique_saved_session_name(
    *,
    base_name: str,
    existing_names: set[str],
) -> str:
    normalized = base_name.strip()
    if not normalized:
        normalized = "planning-session"
    if normalized not in existing_names:
        return normalized
    suffix = 2
    while True:
        candidate = f"{normalized} ({suffix})"
        if candidate not in existing_names:
            return candidate
        suffix += 1


def _snapshot_existing_loops(
    *,
    loop_ids: Sequence[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for loop_id in loop_ids:
        if loop_id in seen_ids:
            continue
        seen_ids.add(loop_id)
        try:
            snapshots.append(read_service.get_loop(loop_id=loop_id, conn=conn))
        except LoopNotFoundError:
            continue
    return snapshots


def _next_checkpoint_index(
    *,
    checkpoint_count: int,
    current_index: int,
    executed_indices: set[int],
) -> int:
    for index in range(current_index + 1, checkpoint_count):
        if index not in executed_indices:
            return index
    for index in range(0, checkpoint_count):
        if index not in executed_indices:
            return index
    return max(0, min(current_index, checkpoint_count - 1))


__all__ = [
    "_require_planning_session_row",
    "_next_unexecuted_checkpoint_index",
    "_collect_resource_ids",
    "_build_execution_summary",
    "_build_follow_up_resources",
    "_build_launch_surfaces",
    "_build_rollback_cues",
    "_planning_session_payload",
    "_build_execution_history",
    "_build_context_freshness",
    "_build_execution_analytics",
    "_build_planning_session_snapshot",
    "_move_checkpoint_index",
    "_unique_saved_session_name",
    "_snapshot_existing_loops",
    "_next_checkpoint_index",
]
