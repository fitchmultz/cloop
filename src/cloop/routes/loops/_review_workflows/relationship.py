"""Relationship review workflow HTTP endpoints.

Purpose:
    Expose durable relationship-review actions and saved session flows over
    HTTP through the shared review workflow orchestration.

Responsibilities:
    - CRUD relationship-review action presets
    - CRUD and move saved relationship-review sessions
    - Execute queued relationship-review actions within a saved session

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Relationship-review HTTP request/response shaping only
    - No relationship scoring or queue orchestration business logic

Usage:
    Included by `cloop.routes.loops.review_workflows`.

Invariants/Assumptions:
    - Route paths stay under `/loops/review/relationship/*`
    - Shared workflow exceptions map through the standard loop-route helpers
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ....loops import review_workflows
from ....loops.errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ....schemas.loops import (
    RelationshipReviewActionCreateRequest,
    RelationshipReviewActionResponse,
    RelationshipReviewActionUpdateRequest,
    RelationshipReviewSessionActionRequest,
    RelationshipReviewSessionActionResponse,
    RelationshipReviewSessionCreateRequest,
    RelationshipReviewSessionResponse,
    RelationshipReviewSessionSnapshotResponse,
    RelationshipReviewSessionUndoRequest,
    RelationshipReviewSessionUndoResponse,
    RelationshipReviewSessionUpdateRequest,
    ReviewSessionMoveRequest,
)
from ....settings import Settings
from .._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_relationship_review_action_response,
    build_relationship_review_session_action_response,
    build_relationship_review_session_response,
    build_relationship_review_session_snapshot_response,
    build_relationship_review_session_undo_response,
    map_not_found_to_404,
    map_validation_to_400,
    run_idempotent_loop_route,
)
from .http_scaffolding import (
    register_review_workflow_action_routes,
    register_review_workflow_session_routes,
)

router = APIRouter()


def _relationship_update_action_execute(
    conn: Any,
    action_preset_id: int,
    fields: dict[str, Any],
) -> Any:
    return review_workflows.update_relationship_review_action(
        action_preset_id=action_preset_id,
        name=fields.get("name"),
        action_type=fields.get("action_type"),
        relationship_type=fields.get("relationship_type"),
        description=fields.get("description"),
        conn=conn,
    )


def _relationship_delete_action_execute(conn: Any, action_preset_id: int) -> Any:
    return review_workflows.delete_relationship_review_action(
        action_preset_id=action_preset_id,
        conn=conn,
    )


def _relationship_create_session_execute(
    conn: Any,
    req: RelationshipReviewSessionCreateRequest,
    settings: Settings,
) -> Any:
    return review_workflows.create_relationship_review_session(
        name=req.name,
        query=req.query,
        relationship_kind=req.relationship_kind,
        candidate_limit=req.candidate_limit,
        item_limit=req.item_limit,
        current_loop_id=req.current_loop_id,
        conn=conn,
        settings=settings,
    )


def _relationship_move_session_execute(
    conn: Any,
    session_id: int,
    request: ReviewSessionMoveRequest,
    settings: Settings,
) -> Any:
    return review_workflows.move_relationship_review_session(
        session_id=session_id,
        direction=request.direction,
        conn=conn,
        settings=settings,
    )


def _relationship_get_session_snapshot(conn: Any, session_id: int, settings: Settings) -> Any:
    return review_workflows.get_relationship_review_session(
        session_id=session_id,
        conn=conn,
        settings=settings,
    )


def _relationship_refresh_session_execute(conn: Any, session_id: int, settings: Settings) -> Any:
    return review_workflows.refresh_relationship_review_session(
        session_id=session_id,
        conn=conn,
        settings=settings,
    )


def _relationship_patch_session_execute(
    conn: Any,
    session_id: int,
    fields: dict[str, Any],
    current_loop_id: Any,
    settings: Settings,
) -> Any:
    return review_workflows.update_relationship_review_session(
        session_id=session_id,
        name=fields.get("name"),
        query=fields.get("query"),
        relationship_kind=fields.get("relationship_kind"),
        candidate_limit=fields.get("candidate_limit"),
        item_limit=fields.get("item_limit"),
        current_loop_id=current_loop_id,
        conn=conn,
        settings=settings,
    )


def _relationship_session_action_execute(
    conn: Any,
    session_id: int,
    req: RelationshipReviewSessionActionRequest,
    settings: Settings,
) -> Any:
    return review_workflows.execute_relationship_review_session_action(
        session_id=session_id,
        loop_id=req.loop_id,
        candidate_loop_id=req.candidate_loop_id,
        candidate_relationship_type=req.candidate_relationship_type,
        action_preset_id=req.action_preset_id,
        action_type=req.action_type,
        relationship_type=req.relationship_type,
        conn=conn,
        settings=settings,
    )


def _relationship_delete_session_execute(conn: Any, session_id: int) -> Any:
    return review_workflows.delete_relationship_review_session(
        session_id=session_id,
        conn=conn,
    )


_actions = register_review_workflow_action_routes(
    router,
    segment="relationship",
    action_response_model=RelationshipReviewActionResponse,
    action_create_type=RelationshipReviewActionCreateRequest,
    action_update_type=RelationshipReviewActionUpdateRequest,
    list_actions=lambda conn: review_workflows.list_relationship_review_actions(conn=conn),
    build_action_response=build_relationship_review_action_response,
    create_execute=lambda conn, req: review_workflows.create_relationship_review_action(
        name=req.name,
        action_type=req.action_type,
        relationship_type=req.relationship_type,
        description=req.description,
        conn=conn,
    ),
    get_action=lambda conn, action_preset_id: review_workflows.get_relationship_review_action(
        action_preset_id=action_preset_id,
        conn=conn,
    ),
    update_execute=_relationship_update_action_execute,
    delete_execute=_relationship_delete_action_execute,
)

_sessions = register_review_workflow_session_routes(
    router,
    segment="relationship",
    session_row_response_model=RelationshipReviewSessionResponse,
    snapshot_response_model=RelationshipReviewSessionSnapshotResponse,
    session_action_response_model=RelationshipReviewSessionActionResponse,
    session_create_type=RelationshipReviewSessionCreateRequest,
    session_update_type=RelationshipReviewSessionUpdateRequest,
    session_action_request_type=RelationshipReviewSessionActionRequest,
    list_sessions=lambda conn: review_workflows.list_relationship_review_sessions(conn=conn),
    build_session_response=build_relationship_review_session_response,
    build_snapshot_response=build_relationship_review_session_snapshot_response,
    build_session_action_response=build_relationship_review_session_action_response,
    create_session_execute=_relationship_create_session_execute,
    get_session_snapshot=_relationship_get_session_snapshot,
    move_session_execute=_relationship_move_session_execute,
    refresh_session_execute=_relationship_refresh_session_execute,
    patch_session_execute=_relationship_patch_session_execute,
    delete_session_execute=_relationship_delete_session_execute,
    session_action_execute=_relationship_session_action_execute,
)

list_relationship_review_actions_endpoint = _actions.list_actions
create_relationship_review_action_endpoint = _actions.create_action
get_relationship_review_action_endpoint = _actions.get_action
update_relationship_review_action_endpoint = _actions.update_action
delete_relationship_review_action_endpoint = _actions.delete_action

list_relationship_review_sessions_endpoint = _sessions.list_sessions
create_relationship_review_session_endpoint = _sessions.create_session
get_relationship_review_session_endpoint = _sessions.get_session
move_relationship_review_session_endpoint = _sessions.move_session
refresh_relationship_review_session_endpoint = _sessions.refresh_session
update_relationship_review_session_endpoint = _sessions.update_session
delete_relationship_review_session_endpoint = _sessions.delete_session
execute_relationship_review_session_action_endpoint = _sessions.execute_session_action


@router.post(
    "/review/relationship/sessions/{session_id}/undo",
    response_model=RelationshipReviewSessionUndoResponse,
)
def undo_relationship_review_session_action_endpoint(
    session_id: int,
    request: RelationshipReviewSessionUndoRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewSessionUndoResponse | JSONResponse:
    payload = {"session_id": session_id, **request.model_dump(mode="json")}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/relationship/sessions/{session_id}/undo",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.undo_relationship_review_session_action(
                session_id=session_id,
                loop_id=request.undo.loop_id,
                candidate_loop_id=request.undo.candidate_loop_id,
                expected_pair_state=request.undo.expected_pair_state.model_dump(mode="python"),
                restore_pair_state=request.undo.restore_pair_state.model_dump(mode="python"),
                conn=conn,
                settings=settings,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review session") from None
    except LoopNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="loop") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_relationship_review_session_undo_response(result)


__all__ = [
    "router",
    "list_relationship_review_actions_endpoint",
    "create_relationship_review_action_endpoint",
    "get_relationship_review_action_endpoint",
    "update_relationship_review_action_endpoint",
    "delete_relationship_review_action_endpoint",
    "list_relationship_review_sessions_endpoint",
    "create_relationship_review_session_endpoint",
    "get_relationship_review_session_endpoint",
    "move_relationship_review_session_endpoint",
    "refresh_relationship_review_session_endpoint",
    "update_relationship_review_session_endpoint",
    "delete_relationship_review_session_endpoint",
    "execute_relationship_review_session_action_endpoint",
    "undo_relationship_review_session_action_endpoint",
]
