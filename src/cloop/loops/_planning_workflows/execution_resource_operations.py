"""Planning resource-focused execution operations.

Purpose:
    Execute deterministic planning operations that create or update saved
    review sessions, views, and templates.

Responsibilities:
    - Create relationship and enrichment review sessions from planning checkpoints
    - Create and update saved views from planning checkpoints
    - Create and update loop templates from planning checkpoints
    - Build provenance, resource refs, and rollback metadata for created resources

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Non-loop planning resource execution only
    - No direct loop mutation or rollback dispatch logic beyond metadata construction

Usage:
    Imported by the planning execution dispatcher.

Invariants/Assumptions:
    - Saved resource names are uniquified before creation when needed
    - Returned payloads remain transport-agnostic and JSON-serializable
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ...settings import Settings
from .. import repo, review_workflows, template_management
from .. import views as loop_views
from ..errors import ValidationError
from .execution_payloads import (
    _operation_result_payload,
    _resource_ref,
    _template_row_payload,
)
from .execution_rollback import _rollback_action
from .models import (
    CreateEnrichmentReviewSessionOperationModel,
    CreateLoopTemplateFromLoopOperationModel,
    CreateLoopViewOperationModel,
    CreateRelationshipReviewSessionOperationModel,
    UpdateLoopTemplateOperationModel,
    UpdateLoopViewOperationModel,
)
from .snapshot import _unique_saved_session_name


def _execute_create_relationship_review_session_operation(
    *,
    operation: CreateRelationshipReviewSessionOperationModel,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    existing_names = {
        str(session["name"])
        for session in review_workflows.list_relationship_review_sessions(conn=conn)
    }
    session_name = _unique_saved_session_name(
        base_name=operation.name,
        existing_names=existing_names,
    )
    result = review_workflows.create_relationship_review_session(
        name=session_name,
        query=operation.query,
        relationship_kind=operation.relationship_kind,
        candidate_limit=operation.candidate_limit,
        item_limit=operation.item_limit,
        current_loop_id=None,
        conn=conn,
        settings=settings,
    )
    session_id = int(result["session"]["id"])
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        resource_refs=[
            _resource_ref(
                resource_type="review_session",
                resource_id=session_id,
                role="created",
                label=str(result["session"]["name"]),
                metadata={"review_kind": "relationship"},
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="review.relationship.session.delete",
                resource_type="review_session",
                resource_id=session_id,
                summary=f"Delete relationship review session {session_id}",
            )
        ],
        provenance={
            "review_kind": "relationship",
            "query": operation.query,
            "loop_count": int(result.get("loop_count") or 0),
        },
        undoable=False,
    )


def _execute_create_enrichment_review_session_operation(
    *,
    operation: CreateEnrichmentReviewSessionOperationModel,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    existing_names = {
        str(session["name"])
        for session in review_workflows.list_enrichment_review_sessions(conn=conn)
    }
    session_name = _unique_saved_session_name(
        base_name=operation.name,
        existing_names=existing_names,
    )
    result = review_workflows.create_enrichment_review_session(
        name=session_name,
        query=operation.query,
        pending_kind=operation.pending_kind,
        suggestion_limit=operation.suggestion_limit,
        clarification_limit=operation.clarification_limit,
        item_limit=operation.item_limit,
        current_loop_id=None,
        conn=conn,
    )
    session_id = int(result["session"]["id"])
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        resource_refs=[
            _resource_ref(
                resource_type="review_session",
                resource_id=session_id,
                role="created",
                label=str(result["session"]["name"]),
                metadata={"review_kind": "enrichment"},
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="review.enrichment.session.delete",
                resource_type="review_session",
                resource_id=session_id,
                summary=f"Delete enrichment review session {session_id}",
            )
        ],
        provenance={
            "review_kind": "enrichment",
            "query": operation.query,
            "loop_count": int(result.get("loop_count") or 0),
        },
        undoable=False,
    )


def _execute_create_loop_view_operation(
    *,
    operation: CreateLoopViewOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    existing_names = {str(view["name"]) for view in loop_views.list_loop_views(conn=conn)}
    view_name = _unique_saved_session_name(base_name=operation.name, existing_names=existing_names)
    result = loop_views.create_loop_view(
        name=view_name,
        query=operation.query,
        description=operation.description,
        conn=conn,
    )
    view_id = int(result["id"])
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        resource_refs=[
            _resource_ref(
                resource_type="view",
                resource_id=view_id,
                role="created",
                label=str(result["name"]),
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="loop.view.delete",
                resource_type="view",
                resource_id=view_id,
                summary=f"Delete saved view {view_id}",
            )
        ],
        provenance={"query": operation.query},
        undoable=False,
    )


def _execute_update_loop_view_operation(
    *,
    operation: UpdateLoopViewOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    before_view = repo.get_loop_view(view_id=operation.view_id, conn=conn)
    if before_view is None:
        raise ValidationError("view_id", f"view {operation.view_id} not found")
    result = loop_views.update_loop_view(
        view_id=operation.view_id,
        name=operation.name,
        query=operation.query,
        description=operation.description,
        conn=conn,
    )
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        resource_refs=[
            _resource_ref(
                resource_type="view",
                resource_id=operation.view_id,
                role="updated",
                label=str(result["name"]),
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="loop.view.update",
                resource_type="view",
                resource_id=operation.view_id,
                summary=f"Restore saved view {operation.view_id} to its previous definition",
                payload={
                    "name": before_view.get("name"),
                    "query": before_view.get("query"),
                    "description": before_view.get("description"),
                },
            )
        ],
        provenance={"view_id": operation.view_id, "before": dict(before_view)},
        undoable=False,
    )


def _execute_create_loop_template_from_loop_operation(
    *,
    operation: CreateLoopTemplateFromLoopOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    existing_names = {
        str(_template_row_payload(template)["name"])
        for template in repo.list_loop_templates(conn=conn)
    }
    template_name = _unique_saved_session_name(
        base_name=operation.template_name,
        existing_names=existing_names,
    )
    result = _template_row_payload(
        template_management.create_template_from_loop(
            loop_id=operation.loop_id,
            template_name=template_name,
            conn=conn,
        )
    )
    template_id = int(result["id"])
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        resource_refs=[
            _resource_ref(
                resource_type="template",
                resource_id=template_id,
                role="created",
                label=str(result["name"]),
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="loop.template.delete",
                resource_type="template",
                resource_id=template_id,
                summary=f"Delete loop template {template_id}",
            )
        ],
        provenance={"source_loop_id": operation.loop_id},
        undoable=False,
    )


def _execute_update_loop_template_operation(
    *,
    operation: UpdateLoopTemplateOperationModel,
    index: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    before_template_row = repo.get_loop_template(template_id=operation.template_id, conn=conn)
    if before_template_row is None:
        raise ValidationError("template_id", f"template {operation.template_id} not found")
    before_template = _template_row_payload(before_template_row)
    result = _template_row_payload(
        template_management.update_loop_template(
            template_id=operation.template_id,
            name=operation.name,
            description=operation.description,
            raw_text_pattern=operation.raw_text_pattern,
            defaults_json=operation.defaults_json,
            conn=conn,
        )
    )
    return _operation_result_payload(
        index=index,
        operation=operation,
        result=result,
        resource_refs=[
            _resource_ref(
                resource_type="template",
                resource_id=operation.template_id,
                role="updated",
                label=str(result["name"]),
            )
        ],
        rollback_actions=[
            _rollback_action(
                kind="loop.template.update",
                resource_type="template",
                resource_id=operation.template_id,
                summary=(
                    f"Restore loop template {operation.template_id} to its previous definition"
                ),
                payload={
                    "name": before_template.get("name"),
                    "description": before_template.get("description"),
                    "raw_text_pattern": before_template.get("raw_text_pattern"),
                    "defaults_json": before_template.get("defaults_json"),
                },
            )
        ],
        provenance={"template_id": operation.template_id, "before": before_template},
        undoable=False,
    )


def execute_resource_focused_operation(
    *,
    operation: object,
    index: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, object] | None:
    if isinstance(operation, CreateRelationshipReviewSessionOperationModel):
        return _execute_create_relationship_review_session_operation(
            operation=operation,
            index=index,
            conn=conn,
            settings=settings,
        )
    if isinstance(operation, CreateEnrichmentReviewSessionOperationModel):
        return _execute_create_enrichment_review_session_operation(
            operation=operation,
            index=index,
            conn=conn,
            settings=settings,
        )
    if isinstance(operation, CreateLoopViewOperationModel):
        return _execute_create_loop_view_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, UpdateLoopViewOperationModel):
        return _execute_update_loop_view_operation(operation=operation, index=index, conn=conn)
    if isinstance(operation, CreateLoopTemplateFromLoopOperationModel):
        return _execute_create_loop_template_from_loop_operation(
            operation=operation,
            index=index,
            conn=conn,
        )
    if isinstance(operation, UpdateLoopTemplateOperationModel):
        return _execute_update_loop_template_operation(operation=operation, index=index, conn=conn)
    return None


__all__ = [
    "_execute_create_relationship_review_session_operation",
    "_execute_create_enrichment_review_session_operation",
    "_execute_create_loop_view_operation",
    "_execute_update_loop_view_operation",
    "_execute_create_loop_template_from_loop_operation",
    "_execute_update_loop_template_operation",
    "execute_resource_focused_operation",
]
