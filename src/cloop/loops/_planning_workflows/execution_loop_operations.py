"""Planning loop-focused execution operations.

Purpose:
    Execute deterministic planning operations that mutate loops directly or
    through loop-scoped bulk enrichment/update/close/snooze flows.

Responsibilities:
    - Execute loop create/update/transition/close operations
    - Execute loop enrichment and query-scoped bulk loop operations
    - Build before/after snapshots, provenance, resource refs, and rollback metadata

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Loop-focused planning operation execution only
    - No review-session/view/template creation operations

Usage:
    Imported by the planning execution dispatcher.

Invariants/Assumptions:
    - Before/after loop snapshots reflect the deterministic operation boundary
    - Bulk operations use the same shared loop primitives as non-planning flows
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ...settings import Settings
from .. import bulk, enrichment_orchestration, service
from ..models import LoopStatus, format_utc_datetime, utc_now
from .execution_payloads import (
    _normalize_capture_fields,
    _normalize_update_fields,
    _operation_result_payload,
    _resource_label,
    _resource_ref,
)
from .execution_rollback import _loop_undo_action, _rollback_action
from .models import (
    BulkEnrichQueryOperationModel,
    CloseLoopOperationModel,
    CreateLoopOperationModel,
    EnrichLoopOperationModel,
    QueryBulkCloseOperationModel,
    QueryBulkSnoozeOperationModel,
    QueryBulkUpdateOperationModel,
    TransitionLoopOperationModel,
    UpdateLoopOperationModel,
)
from .snapshot import _snapshot_existing_loops


def _loop_rollback_action_from_payload(
    *, loop: dict[str, Any], summary: str
) -> dict[str, Any] | None:
    """Build an exact loop-event rollback action from a mutated loop payload."""
    latest_event_id = loop.get("latest_reversible_event_id")
    if not isinstance(latest_event_id, int):
        return None
    return _loop_undo_action(
        loop_id=int(loop["id"]),
        expected_event_id=latest_event_id,
        summary=summary,
    )


def _execute_create_loop_operation(
    *,
    operation: CreateLoopOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    created = service.capture_loop(
        raw_text=operation.raw_text,
        captured_at_iso=format_utc_datetime(utc_now()),
        client_tz_offset_min=0,
        status=LoopStatus(operation.status),
        capture_fields=_normalize_capture_fields(operation.capture_fields),
        conn=conn,
    )
    created_loop_id = int(created["id"])
    return _operation_result_payload(
        index=index,
        operation=operation,
        result={"loop": created},
        after_loops=[created],
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=created_loop_id,
                role="created",
                label=_resource_label(created),
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="planning.loop.delete",
                resource_type="loop",
                resource_id=created_loop_id,
                summary=f"Delete loop {created_loop_id} created by this checkpoint",
            )
        ],
        provenance={
            "status": operation.status,
            "capture_fields": _normalize_capture_fields(operation.capture_fields) or {},
        },
        undoable=False,
    )


def _execute_update_loop_operation(
    *,
    operation: UpdateLoopOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
    fields = _normalize_update_fields(operation.fields)
    updated = service.update_loop(
        loop_id=operation.loop_id,
        fields=fields,
        conn=conn,
    )
    return _operation_result_payload(
        index=index,
        operation=operation,
        result={"loop": updated},
        before_loops=before,
        after_loops=[updated],
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=operation.loop_id,
                role="updated",
                label=_resource_label(updated),
            )
        ],
        rollback_actions=[
            action
            for action in [
                _loop_rollback_action_from_payload(
                    loop=updated,
                    summary=f"Undo loop update for loop {operation.loop_id}",
                )
            ]
            if action is not None
        ],
        provenance={"loop_ids": [operation.loop_id], "fields": sorted(fields.keys())},
        undoable=True,
    )


def _execute_transition_loop_operation(
    *,
    operation: TransitionLoopOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
    updated = service.transition_status(
        loop_id=operation.loop_id,
        to_status=LoopStatus(operation.status),
        note=operation.note,
        conn=conn,
    )
    return _operation_result_payload(
        index=index,
        operation=operation,
        result={"loop": updated},
        before_loops=before,
        after_loops=[updated],
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=operation.loop_id,
                role="transitioned",
                label=_resource_label(updated),
                metadata={"status": operation.status},
            )
        ],
        rollback_actions=[
            action
            for action in [
                _loop_rollback_action_from_payload(
                    loop=updated,
                    summary=f"Undo loop status transition for loop {operation.loop_id}",
                )
            ]
            if action is not None
        ],
        provenance={
            "loop_ids": [operation.loop_id],
            "to_status": operation.status,
            "note": operation.note,
        },
        undoable=True,
    )


def _execute_close_loop_operation(
    *,
    operation: CloseLoopOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
    updated = service.transition_status(
        loop_id=operation.loop_id,
        to_status=LoopStatus(operation.status),
        note=operation.note,
        conn=conn,
    )
    return _operation_result_payload(
        index=index,
        operation=operation,
        result={"loop": updated},
        before_loops=before,
        after_loops=[updated],
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=operation.loop_id,
                role="closed",
                label=_resource_label(updated),
                metadata={"status": operation.status},
            )
        ],
        rollback_actions=[
            action
            for action in [
                _loop_rollback_action_from_payload(
                    loop=updated,
                    summary=f"Undo loop close for loop {operation.loop_id}",
                )
            ]
            if action is not None
        ],
        provenance={
            "loop_ids": [operation.loop_id],
            "status": operation.status,
            "note": operation.note,
        },
        undoable=True,
    )


def _execute_enrich_loop_operation(
    *,
    operation: EnrichLoopOperationModel,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    before = _snapshot_existing_loops(loop_ids=[operation.loop_id], conn=conn)
    result = enrichment_orchestration.orchestrate_loop_enrichment(
        loop_id=operation.loop_id,
        conn=conn,
        settings=settings,
    ).to_payload()
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        before_loops=before,
        after_loops=[result["loop"]],
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=operation.loop_id,
                role="enriched",
                label=_resource_label(result["loop"]),
                metadata={"suggestion_id": result["suggestion_id"]},
            )
        ],
        provenance={
            "loop_ids": [operation.loop_id],
            "suggestion_id": result["suggestion_id"],
            "applied_fields": list(result.get("applied_fields") or []),
            "needs_clarification": list(result.get("needs_clarification") or []),
        },
        undoable=False,
    )


def _execute_bulk_enrich_query_operation(
    *,
    operation: BulkEnrichQueryOperationModel,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    preview = enrichment_orchestration.preview_query_loop_enrichment_targets(
        query=operation.query,
        limit=operation.limit,
        conn=conn,
    )
    before_loops = list(preview.get("targets") or [])
    result = enrichment_orchestration.orchestrate_query_bulk_loop_enrichment(
        query=operation.query,
        limit=operation.limit,
        dry_run=False,
        conn=conn,
        settings=settings,
    )
    affected_loop_ids = [int(target["id"]) for target in before_loops]
    after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        before_loops=before_loops,
        after_loops=after_loops,
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=loop_id,
                role="enriched",
            )
            for loop_id in affected_loop_ids
        ],
        provenance={
            "query": operation.query,
            "matched_count": int(result.get("matched_count") or 0),
            "limited": bool(result.get("limited", False)),
            "matched_loop_ids": affected_loop_ids,
        },
        undoable=False,
    )


def _execute_query_bulk_update_operation(
    *,
    operation: QueryBulkUpdateOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    fields = _normalize_update_fields(operation.fields)
    preview = bulk.query_bulk_update_loops(
        query=operation.query,
        fields=fields,
        transactional=True,
        dry_run=True,
        limit=operation.limit,
        conn=conn,
    )
    before_loops = list(preview.get("targets") or [])
    result = bulk.query_bulk_update_loops(
        query=operation.query,
        fields=fields,
        transactional=True,
        dry_run=False,
        limit=operation.limit,
        conn=conn,
    )
    affected_loop_ids = [int(target["id"]) for target in before_loops]
    after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        before_loops=before_loops,
        after_loops=after_loops,
        resource_refs=[
            _resource_ref(resource_type="loop", resource_id=loop_id, role="updated")
            for loop_id in affected_loop_ids
        ],
        rollback_actions=[
            action
            for item in list(result.get("results") or [])
            if item.get("ok") and isinstance(item.get("loop"), dict)
            for action in [
                _loop_rollback_action_from_payload(
                    loop=dict(item["loop"]),
                    summary=f"Undo query bulk update for loop {int(item['loop_id'])}",
                )
            ]
            if action is not None
        ],
        provenance={
            "query": operation.query,
            "matched_count": int(result.get("matched_count") or 0),
            "limited": bool(result.get("limited", False)),
            "matched_loop_ids": affected_loop_ids,
            "fields": sorted(fields.keys()),
        },
        undoable=bool(affected_loop_ids),
    )


def _execute_query_bulk_close_operation(
    *,
    operation: QueryBulkCloseOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    preview = bulk.query_bulk_close_loops(
        query=operation.query,
        status=operation.status,
        note=operation.note,
        transactional=True,
        dry_run=True,
        limit=operation.limit,
        conn=conn,
    )
    before_loops = list(preview.get("targets") or [])
    result = bulk.query_bulk_close_loops(
        query=operation.query,
        status=operation.status,
        note=operation.note,
        transactional=True,
        dry_run=False,
        limit=operation.limit,
        conn=conn,
    )
    affected_loop_ids = [int(target["id"]) for target in before_loops]
    after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        before_loops=before_loops,
        after_loops=after_loops,
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=loop_id,
                role="closed",
                metadata={"status": operation.status},
            )
            for loop_id in affected_loop_ids
        ],
        rollback_actions=[
            action
            for item in list(result.get("results") or [])
            if item.get("ok") and isinstance(item.get("loop"), dict)
            for action in [
                _loop_rollback_action_from_payload(
                    loop=dict(item["loop"]),
                    summary=f"Undo query bulk close for loop {int(item['loop_id'])}",
                )
            ]
            if action is not None
        ],
        provenance={
            "query": operation.query,
            "matched_count": int(result.get("matched_count") or 0),
            "limited": bool(result.get("limited", False)),
            "matched_loop_ids": affected_loop_ids,
            "status": operation.status,
            "note": operation.note,
        },
        undoable=bool(affected_loop_ids),
    )


def _execute_query_bulk_snooze_operation(
    *,
    operation: QueryBulkSnoozeOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    preview = bulk.query_bulk_snooze_loops(
        query=operation.query,
        snooze_until_utc=operation.snooze_until_utc,
        transactional=True,
        dry_run=True,
        limit=operation.limit,
        conn=conn,
    )
    before_loops = list(preview.get("targets") or [])
    result = bulk.query_bulk_snooze_loops(
        query=operation.query,
        snooze_until_utc=operation.snooze_until_utc,
        transactional=True,
        dry_run=False,
        limit=operation.limit,
        conn=conn,
    )
    affected_loop_ids = [int(target["id"]) for target in before_loops]
    after_loops = _snapshot_existing_loops(loop_ids=affected_loop_ids, conn=conn)
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        before_loops=before_loops,
        after_loops=after_loops,
        resource_refs=[
            _resource_ref(
                resource_type="loop",
                resource_id=loop_id,
                role="snoozed",
                metadata={"snooze_until_utc": operation.snooze_until_utc},
            )
            for loop_id in affected_loop_ids
        ],
        rollback_actions=[
            action
            for item in list(result.get("results") or [])
            if item.get("ok") and isinstance(item.get("loop"), dict)
            for action in [
                _loop_rollback_action_from_payload(
                    loop=dict(item["loop"]),
                    summary=f"Undo query bulk snooze for loop {int(item['loop_id'])}",
                )
            ]
            if action is not None
        ],
        provenance={
            "query": operation.query,
            "matched_count": int(result.get("matched_count") or 0),
            "limited": bool(result.get("limited", False)),
            "matched_loop_ids": affected_loop_ids,
            "snooze_until_utc": operation.snooze_until_utc,
        },
        undoable=bool(affected_loop_ids),
    )


def execute_loop_focused_operation(
    *,
    operation: object,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
    active_working_set_id: int | None = None,
) -> dict[str, object] | None:
    if isinstance(operation, CreateLoopOperationModel):
        return _execute_create_loop_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, UpdateLoopOperationModel):
        return _execute_update_loop_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, TransitionLoopOperationModel):
        return _execute_transition_loop_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, CloseLoopOperationModel):
        return _execute_close_loop_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, EnrichLoopOperationModel):
        return _execute_enrich_loop_operation(
            operation=operation,
            index=index,
            conn=conn,
            settings=settings,
        )
    if isinstance(operation, BulkEnrichQueryOperationModel):
        return _execute_bulk_enrich_query_operation(
            operation=operation,
            index=index,
            conn=conn,
            settings=settings,
        )
    if isinstance(operation, QueryBulkUpdateOperationModel):
        return _execute_query_bulk_update_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, QueryBulkCloseOperationModel):
        return _execute_query_bulk_close_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, QueryBulkSnoozeOperationModel):
        return _execute_query_bulk_snooze_operation(operation=operation, index=index, conn=conn)
    return None


__all__ = [
    "_execute_create_loop_operation",
    "_execute_update_loop_operation",
    "_execute_transition_loop_operation",
    "_execute_close_loop_operation",
    "_execute_enrich_loop_operation",
    "_execute_bulk_enrich_query_operation",
    "_execute_query_bulk_update_operation",
    "_execute_query_bulk_close_operation",
    "_execute_query_bulk_snooze_operation",
    "execute_loop_focused_operation",
]
