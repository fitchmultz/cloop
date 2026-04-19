"""Planning execution validation helpers.

Purpose:
    Validate stored planning operations and checkpoints before deterministic
    execution begins.

Responsibilities:
    - Verify referenced loops, views, and templates exist and are mutable
    - Validate query-bearing operations against the loop DSL
    - Enforce checkpoint rollback-ordering constraints

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Pre-execution validation only
    - No persistence, rollback execution, or forward dispatch

Usage:
    Imported by the planning service before executing a checkpoint.

Invariants/Assumptions:
    - Enrichment operations (no checkpoint rollback) must be the final operations
    - Validation errors should surface before any forward mutations occur
"""

from __future__ import annotations

import sqlite3

from .. import repo
from ..errors import LoopNotFoundError, ValidationError
from ..query import parse_loop_query
from .execution_payloads import _normalize_capture_fields, _normalize_update_fields
from .models import (
    BulkEnrichQueryOperationModel,
    CloseLoopOperationModel,
    CreateEnrichmentReviewSessionOperationModel,
    CreateLoopOperationModel,
    CreateLoopTemplateFromLoopOperationModel,
    CreateLoopViewOperationModel,
    CreateRelationshipReviewSessionOperationModel,
    EnrichLoopOperationModel,
    PlanningCheckpointModel,
    PlanningOperationModel,
    QueryBulkCloseOperationModel,
    QueryBulkSnoozeOperationModel,
    QueryBulkUpdateOperationModel,
    TransitionLoopOperationModel,
    UpdateLoopOperationModel,
    UpdateLoopTemplateOperationModel,
    UpdateLoopViewOperationModel,
)


def _validate_operation_for_execution(
    *,
    operation: PlanningOperationModel,
    conn: sqlite3.Connection,
) -> None:
    if isinstance(operation, CreateLoopOperationModel):
        _normalize_capture_fields(operation.capture_fields)
        return
    if isinstance(operation, UpdateLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        _normalize_update_fields(operation.fields)
        return
    if isinstance(operation, TransitionLoopOperationModel | CloseLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        return
    if isinstance(operation, EnrichLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        return
    if isinstance(
        operation,
        BulkEnrichQueryOperationModel
        | QueryBulkUpdateOperationModel
        | QueryBulkCloseOperationModel
        | QueryBulkSnoozeOperationModel,
    ):
        parse_loop_query(operation.query)
        if isinstance(operation, QueryBulkUpdateOperationModel):
            _normalize_update_fields(operation.fields)
        return
    if isinstance(
        operation,
        CreateRelationshipReviewSessionOperationModel
        | CreateEnrichmentReviewSessionOperationModel
        | CreateLoopViewOperationModel,
    ):
        parse_loop_query(operation.query)
        return
    if isinstance(operation, UpdateLoopViewOperationModel):
        if repo.get_loop_view(view_id=operation.view_id, conn=conn) is None:
            raise ValidationError("view_id", f"view {operation.view_id} not found")
        if operation.query is not None:
            parse_loop_query(operation.query)
        return
    if isinstance(operation, CreateLoopTemplateFromLoopOperationModel):
        if repo.read_loop(loop_id=operation.loop_id, conn=conn) is None:
            raise LoopNotFoundError(operation.loop_id)
        return
    if isinstance(operation, UpdateLoopTemplateOperationModel):
        template = repo.get_loop_template(template_id=operation.template_id, conn=conn)
        if template is None:
            raise ValidationError("template_id", f"template {operation.template_id} not found")
        if bool(template.get("is_system")):
            raise ValidationError("template_id", "system templates cannot be modified")
        return

    raise RuntimeError(f"unsupported planning operation kind: {operation.kind}")


def _validate_checkpoint_for_execution(
    *,
    checkpoint: PlanningCheckpointModel,
    conn: sqlite3.Connection,
) -> None:
    rollback_unsupported_seen = False
    for op_index, operation in enumerate(checkpoint.operations):
        _validate_operation_for_execution(operation=operation, conn=conn)
        if operation.kind in {"enrich_loop", "bulk_enrich_query"}:
            rollback_unsupported_seen = True
            continue
        if rollback_unsupported_seen:
            op_num = op_index + 1
            raise ValidationError(
                "checkpoint",
                (
                    f"Operation {op_num} ({operation.kind}) cannot follow an enrichment operation: "
                    "enrich_loop and bulk_enrich_query are not included in checkpoint rollback, "
                    "so they must be the final operations in this checkpoint. "
                    "Reorder reversible steps before any enrichment, or end this checkpoint "
                    "after enrichment."
                ),
            )


__all__ = [
    "_validate_operation_for_execution",
    "_validate_checkpoint_for_execution",
]
