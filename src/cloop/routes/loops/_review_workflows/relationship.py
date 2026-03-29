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

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .... import db
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
    no_fields_to_update_http_exception,
    run_idempotent_loop_route,
)

router = APIRouter()


@router.get("/review/relationship/actions", response_model=list[RelationshipReviewActionResponse])
def list_relationship_review_actions_endpoint(
    settings: SettingsDep,
) -> list[RelationshipReviewActionResponse]:
    with db.core_connection(settings) as conn:
        actions = review_workflows.list_relationship_review_actions(conn=conn)
    return [build_relationship_review_action_response(action) for action in actions]


@router.post(
    "/review/relationship/actions",
    response_model=RelationshipReviewActionResponse,
    status_code=201,
)
def create_relationship_review_action_endpoint(
    request: RelationshipReviewActionCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewActionResponse | JSONResponse:
    payload = request.model_dump(mode="json")
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/review/relationship/actions",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.create_relationship_review_action(
                name=request.name,
                action_type=request.action_type,
                relationship_type=request.relationship_type,
                description=request.description,
                conn=conn,
            ),
            response_status=201,
        )
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_relationship_review_action_response(result)


@router.get(
    "/review/relationship/actions/{action_preset_id}",
    response_model=RelationshipReviewActionResponse,
)
def get_relationship_review_action_endpoint(
    action_preset_id: int,
    settings: SettingsDep,
) -> RelationshipReviewActionResponse:
    with db.core_connection(settings) as conn:
        try:
            action = review_workflows.get_relationship_review_action(
                action_preset_id=action_preset_id,
                conn=conn,
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review action") from None
    return build_relationship_review_action_response(action)


@router.patch(
    "/review/relationship/actions/{action_preset_id}",
    response_model=RelationshipReviewActionResponse,
)
def update_relationship_review_action_endpoint(
    action_preset_id: int,
    request: RelationshipReviewActionUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewActionResponse | JSONResponse:
    fields = request.model_dump(mode="json", exclude_unset=True)
    if not fields:
        raise no_fields_to_update_http_exception() from None
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="PATCH",
            path=f"/loops/review/relationship/actions/{action_preset_id}",
            idempotency_key=idempotency_key,
            payload={"action_preset_id": action_preset_id, **fields},
            execute=lambda conn: review_workflows.update_relationship_review_action(
                action_preset_id=action_preset_id,
                name=fields.get("name"),
                action_type=fields.get("action_type"),
                relationship_type=fields.get("relationship_type"),
                description=fields.get("description"),
                conn=conn,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review action") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_relationship_review_action_response(result)


@router.delete("/review/relationship/actions/{action_preset_id}", response_model=None)
def delete_relationship_review_action_endpoint(
    action_preset_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, bool | int] | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="DELETE",
            path=f"/loops/review/relationship/actions/{action_preset_id}",
            idempotency_key=idempotency_key,
            payload={"action_preset_id": action_preset_id},
            execute=lambda conn: review_workflows.delete_relationship_review_action(
                action_preset_id=action_preset_id,
                conn=conn,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review action") from None
    if isinstance(result, JSONResponse):
        return result
    return result


@router.get(
    "/review/relationship/sessions",
    response_model=list[RelationshipReviewSessionResponse],
)
def list_relationship_review_sessions_endpoint(
    settings: SettingsDep,
) -> list[RelationshipReviewSessionResponse]:
    with db.core_connection(settings) as conn:
        sessions = review_workflows.list_relationship_review_sessions(conn=conn)
    return [build_relationship_review_session_response(session) for session in sessions]


@router.post(
    "/review/relationship/sessions",
    response_model=RelationshipReviewSessionSnapshotResponse,
    status_code=201,
)
def create_relationship_review_session_endpoint(
    request: RelationshipReviewSessionCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewSessionSnapshotResponse | JSONResponse:
    payload = request.model_dump(mode="json")
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/review/relationship/sessions",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.create_relationship_review_session(
                name=request.name,
                query=request.query,
                relationship_kind=request.relationship_kind,
                candidate_limit=request.candidate_limit,
                item_limit=request.item_limit,
                current_loop_id=request.current_loop_id,
                conn=conn,
                settings=settings,
            ),
            response_status=201,
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review session") from None
    except LoopNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="loop") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_relationship_review_session_snapshot_response(result)


@router.get(
    "/review/relationship/sessions/{session_id}",
    response_model=RelationshipReviewSessionSnapshotResponse,
)
def get_relationship_review_session_endpoint(
    session_id: int,
    settings: SettingsDep,
) -> RelationshipReviewSessionSnapshotResponse:
    with db.core_connection(settings) as conn:
        try:
            snapshot = review_workflows.get_relationship_review_session(
                session_id=session_id,
                conn=conn,
                settings=settings,
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
    return build_relationship_review_session_snapshot_response(snapshot)


@router.post(
    "/review/relationship/sessions/{session_id}/move",
    response_model=RelationshipReviewSessionSnapshotResponse,
)
def move_relationship_review_session_endpoint(
    session_id: int,
    request: ReviewSessionMoveRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewSessionSnapshotResponse | JSONResponse:
    payload = {"session_id": session_id, **request.model_dump(mode="json")}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/relationship/sessions/{session_id}/move",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.move_relationship_review_session(
                session_id=session_id,
                direction=request.direction,
                conn=conn,
                settings=settings,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review session") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_relationship_review_session_snapshot_response(result)


@router.post(
    "/review/relationship/sessions/{session_id}/refresh",
    response_model=RelationshipReviewSessionSnapshotResponse,
)
def refresh_relationship_review_session_endpoint(
    session_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewSessionSnapshotResponse | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/relationship/sessions/{session_id}/refresh",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id},
            execute=lambda conn: review_workflows.refresh_relationship_review_session(
                session_id=session_id,
                conn=conn,
                settings=settings,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review session") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_relationship_review_session_snapshot_response(result)


@router.patch(
    "/review/relationship/sessions/{session_id}",
    response_model=RelationshipReviewSessionSnapshotResponse,
)
def update_relationship_review_session_endpoint(
    session_id: int,
    request: RelationshipReviewSessionUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewSessionSnapshotResponse | JSONResponse:
    fields = request.model_dump(mode="json", exclude_unset=True)
    if not fields:
        raise no_fields_to_update_http_exception() from None
    current_loop_id = (
        fields["current_loop_id"] if "current_loop_id" in fields else review_workflows._UNSET
    )
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="PATCH",
            path=f"/loops/review/relationship/sessions/{session_id}",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id, **fields},
            execute=lambda conn: review_workflows.update_relationship_review_session(
                session_id=session_id,
                name=fields.get("name"),
                query=fields.get("query"),
                relationship_kind=fields.get("relationship_kind"),
                candidate_limit=fields.get("candidate_limit"),
                item_limit=fields.get("item_limit"),
                current_loop_id=current_loop_id,
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
    return build_relationship_review_session_snapshot_response(result)


@router.delete("/review/relationship/sessions/{session_id}", response_model=None)
def delete_relationship_review_session_endpoint(
    session_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, bool | int] | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="DELETE",
            path=f"/loops/review/relationship/sessions/{session_id}",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id},
            execute=lambda conn: review_workflows.delete_relationship_review_session(
                session_id=session_id,
                conn=conn,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review session") from None
    if isinstance(result, JSONResponse):
        return result
    return result


@router.post(
    "/review/relationship/sessions/{session_id}/action",
    response_model=RelationshipReviewSessionActionResponse,
)
def execute_relationship_review_session_action_endpoint(
    session_id: int,
    request: RelationshipReviewSessionActionRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipReviewSessionActionResponse | JSONResponse:
    payload = {"session_id": session_id, **request.model_dump(mode="json")}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/relationship/sessions/{session_id}/action",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.execute_relationship_review_session_action(
                session_id=session_id,
                loop_id=request.loop_id,
                candidate_loop_id=request.candidate_loop_id,
                candidate_relationship_type=request.candidate_relationship_type,
                action_preset_id=request.action_preset_id,
                action_type=request.action_type,
                relationship_type=request.relationship_type,
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
    return build_relationship_review_session_action_response(result)


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
