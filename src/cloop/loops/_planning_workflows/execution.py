"""Planning checkpoint execution facade.

Purpose:
    Re-export focused planning execution helper modules behind the stable
    `_planning_workflows.execution` namespace.

Responsibilities:
    - Preserve one internal import surface for payload, rollback, validation, and dispatch helpers
    - Dispatch planning operations to loop-focused and resource-focused executors

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Internal execution facade only
    - No inline operation implementation beyond top-level dispatch

Usage:
    Imported by planning service and the public planning workflow facade.

Invariants/Assumptions:
    - All operation kinds must be handled by one focused executor branch
    - Helper re-exports remain stable for sibling planning modules
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ...settings import Settings
from .execution_loop_operations import execute_loop_focused_operation
from .execution_payloads import (
    _normalize_capture_fields,
    _normalize_update_fields,
    _operation_payload,
    _operation_result_payload,
    _resource_label,
    _resource_ref,
    _template_row_payload,
)
from .execution_resource_operations import execute_resource_focused_operation
from .execution_rollback import (
    _execute_rollback_action,
    _loop_undo_action,
    _rollback_action,
    _rollback_execution_results,
)
from .execution_validation import (
    _validate_checkpoint_for_execution,
    _validate_operation_for_execution,
)
from .models import PlanningOperationModel


def _execute_plan_operation(
    *,
    operation: PlanningOperationModel,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
    active_working_set_id: int | None = None,
) -> dict[str, Any]:
    loop_result = execute_loop_focused_operation(
        operation=operation,
        index=index,
        conn=conn,
        settings=settings,
        active_working_set_id=active_working_set_id,
    )
    if loop_result is not None:
        return dict(loop_result)

    resource_result = execute_resource_focused_operation(
        operation=operation,
        index=index,
        conn=conn,
        settings=settings,
        active_working_set_id=active_working_set_id,
    )
    if resource_result is not None:
        return dict(resource_result)

    raise RuntimeError(f"unsupported planning operation kind: {operation.kind}")


__all__ = [
    "_normalize_capture_fields",
    "_normalize_update_fields",
    "_operation_payload",
    "_operation_result_payload",
    "_resource_label",
    "_resource_ref",
    "_template_row_payload",
    "_rollback_action",
    "_loop_undo_action",
    "_execute_rollback_action",
    "_rollback_execution_results",
    "_validate_operation_for_execution",
    "_validate_checkpoint_for_execution",
    "_execute_plan_operation",
]
