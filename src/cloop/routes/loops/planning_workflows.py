"""Planning workflow endpoints.

Purpose:
    Expose durable AI-native planning sessions across HTTP by delegating to the
    shared planning workflow orchestration module.

Responsibilities:
    - CRUD planning sessions
    - Materialize saved planning session snapshots
    - Move a planning checkpoint cursor through a saved session
    - Refresh an existing plan against current grounded context
    - Execute the current checkpoint with explicit idempotent mutation handling

Non-scope:
    - Planning generation business logic
    - Transport-specific plan semantics outside request/response shaping
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ... import db
from ...loops import planning_workflows
from ...loops.errors import ResourceNotFoundError, ValidationError
from ...schemas.loops import (
    PlanningSessionCreateRequest,
    PlanningSessionExecuteResponse,
    PlanningSessionResponse,
    PlanningSessionSnapshotResponse,
    ReviewSessionMoveRequest,
)
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_planning_session_execute_response,
    build_planning_session_response,
    build_planning_session_snapshot_response,
    map_not_found_to_404,
    map_validation_to_400,
    run_idempotent_loop_route,
)

router = APIRouter()


@router.get(
    "/planning/sessions",
    response_model=list[PlanningSessionResponse],
)
def list_planning_sessions_endpoint(
    settings: SettingsDep,
) -> list[PlanningSessionResponse]:
    with db.core_connection(settings) as conn:
        sessions = planning_workflows.list_planning_sessions(conn=conn)
    return [build_planning_session_response(session) for session in sessions]


@router.post(
    "/planning/sessions",
    response_model=PlanningSessionSnapshotResponse,
    status_code=201,
)
def create_planning_session_endpoint(
    request: PlanningSessionCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> PlanningSessionSnapshotResponse | JSONResponse:
    payload = request.model_dump(mode="json")
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/planning/sessions",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: planning_workflows.create_planning_session(
                name=request.name,
                prompt=request.prompt,
                query=request.query,
                loop_limit=request.loop_limit,
                include_memory_context=request.include_memory_context,
                include_rag_context=request.include_rag_context,
                rag_k=request.rag_k,
                rag_scope=request.rag_scope,
                conn=conn,
                settings=settings,
            ),
            response_status=201,
        )
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_planning_session_snapshot_response(result)


@router.get(
    "/planning/sessions/{session_id}",
    response_model=PlanningSessionSnapshotResponse,
)
def get_planning_session_endpoint(
    session_id: int,
    settings: SettingsDep,
) -> PlanningSessionSnapshotResponse:
    with db.core_connection(settings) as conn:
        try:
            snapshot = planning_workflows.get_planning_session(
                session_id=session_id,
                conn=conn,
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="planning session") from None
    return build_planning_session_snapshot_response(snapshot)


@router.post(
    "/planning/sessions/{session_id}/move",
    response_model=PlanningSessionSnapshotResponse,
)
def move_planning_session_endpoint(
    session_id: int,
    request: ReviewSessionMoveRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> PlanningSessionSnapshotResponse | JSONResponse:
    payload = {"session_id": session_id, **request.model_dump(mode="json")}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/planning/sessions/{session_id}/move",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: planning_workflows.move_planning_session(
                session_id=session_id,
                direction=request.direction,
                conn=conn,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="planning session") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_planning_session_snapshot_response(result)


@router.post(
    "/planning/sessions/{session_id}/refresh",
    response_model=PlanningSessionSnapshotResponse,
)
def refresh_planning_session_endpoint(
    session_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> PlanningSessionSnapshotResponse | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/planning/sessions/{session_id}/refresh",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id},
            execute=lambda conn: planning_workflows.refresh_planning_session(
                session_id=session_id,
                conn=conn,
                settings=settings,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="planning session") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_planning_session_snapshot_response(result)


@router.post(
    "/planning/sessions/{session_id}/execute",
    response_model=PlanningSessionExecuteResponse,
)
def execute_planning_session_endpoint(
    session_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> PlanningSessionExecuteResponse | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/planning/sessions/{session_id}/execute",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id},
            execute=lambda conn: planning_workflows.execute_planning_session_checkpoint(
                session_id=session_id,
                conn=conn,
                settings=settings,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="planning session") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_planning_session_execute_response(result)


@router.delete("/planning/sessions/{session_id}", response_model=None)
def delete_planning_session_endpoint(
    session_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, bool | int] | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="DELETE",
            path=f"/loops/planning/sessions/{session_id}",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id},
            execute=lambda conn: planning_workflows.delete_planning_session(
                session_id=session_id,
                conn=conn,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="planning session") from None
    if isinstance(result, JSONResponse):
        return result
    return result
