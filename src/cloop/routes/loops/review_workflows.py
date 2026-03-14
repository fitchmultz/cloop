"""Saved review action and session endpoints.

Purpose:
    Expose durable relationship-review and enrichment-review operator workflows
    across HTTP by delegating to the shared review-workflow orchestration.

Responsibilities:
    - CRUD saved relationship and enrichment review actions
    - CRUD relationship and enrichment review sessions
    - Materialize session snapshots with preserved filtered worklists
    - Move guided review cursors through saved sessions
    - Execute saved or inline review actions within a session
    - Record clarification answers and rerun enrichment within an enrichment review session

Non-scope:
    - Low-level relationship scoring or suggestion business rules
    - Transport-specific worklist semantics outside request/response shaping
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ... import db
from ...loops import enrichment_review, review_workflows
from ...loops.errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ...schemas.loops import (
    EnrichmentReviewActionCreateRequest,
    EnrichmentReviewActionResponse,
    EnrichmentReviewActionUpdateRequest,
    EnrichmentReviewSessionActionRequest,
    EnrichmentReviewSessionActionResponse,
    EnrichmentReviewSessionClarificationRequest,
    EnrichmentReviewSessionClarificationResponse,
    EnrichmentReviewSessionCreateRequest,
    EnrichmentReviewSessionResponse,
    EnrichmentReviewSessionSnapshotResponse,
    EnrichmentReviewSessionUpdateRequest,
    RelationshipReviewActionCreateRequest,
    RelationshipReviewActionResponse,
    RelationshipReviewActionUpdateRequest,
    RelationshipReviewSessionActionRequest,
    RelationshipReviewSessionActionResponse,
    RelationshipReviewSessionCreateRequest,
    RelationshipReviewSessionResponse,
    RelationshipReviewSessionSnapshotResponse,
    RelationshipReviewSessionUpdateRequest,
    ReviewSessionMoveRequest,
)
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_enrichment_review_action_response,
    build_enrichment_review_session_action_response,
    build_enrichment_review_session_clarification_response,
    build_enrichment_review_session_response,
    build_enrichment_review_session_snapshot_response,
    build_relationship_review_action_response,
    build_relationship_review_session_action_response,
    build_relationship_review_session_response,
    build_relationship_review_session_snapshot_response,
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


@router.get("/review/enrichment/actions", response_model=list[EnrichmentReviewActionResponse])
def list_enrichment_review_actions_endpoint(
    settings: SettingsDep,
) -> list[EnrichmentReviewActionResponse]:
    with db.core_connection(settings) as conn:
        actions = review_workflows.list_enrichment_review_actions(conn=conn)
    return [build_enrichment_review_action_response(action) for action in actions]


@router.post(
    "/review/enrichment/actions",
    response_model=EnrichmentReviewActionResponse,
    status_code=201,
)
def create_enrichment_review_action_endpoint(
    request: EnrichmentReviewActionCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewActionResponse | JSONResponse:
    payload = request.model_dump(mode="json")
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/review/enrichment/actions",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.create_enrichment_review_action(
                name=request.name,
                action_type=request.action_type,
                fields=request.fields,
                description=request.description,
                conn=conn,
            ),
            response_status=201,
        )
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_enrichment_review_action_response(result)


@router.get(
    "/review/enrichment/actions/{action_preset_id}",
    response_model=EnrichmentReviewActionResponse,
)
def get_enrichment_review_action_endpoint(
    action_preset_id: int,
    settings: SettingsDep,
) -> EnrichmentReviewActionResponse:
    with db.core_connection(settings) as conn:
        try:
            action = review_workflows.get_enrichment_review_action(
                action_preset_id=action_preset_id,
                conn=conn,
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review action") from None
    return build_enrichment_review_action_response(action)


@router.patch(
    "/review/enrichment/actions/{action_preset_id}",
    response_model=EnrichmentReviewActionResponse,
)
def update_enrichment_review_action_endpoint(
    action_preset_id: int,
    request: EnrichmentReviewActionUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewActionResponse | JSONResponse:
    fields = request.model_dump(mode="json", exclude_unset=True)
    if not fields:
        raise no_fields_to_update_http_exception() from None
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="PATCH",
            path=f"/loops/review/enrichment/actions/{action_preset_id}",
            idempotency_key=idempotency_key,
            payload={"action_preset_id": action_preset_id, **fields},
            execute=lambda conn: review_workflows.update_enrichment_review_action(
                action_preset_id=action_preset_id,
                name=fields.get("name"),
                action_type=fields.get("action_type"),
                fields=fields.get("fields"),
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
    return build_enrichment_review_action_response(result)


@router.delete("/review/enrichment/actions/{action_preset_id}", response_model=None)
def delete_enrichment_review_action_endpoint(
    action_preset_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, bool | int] | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="DELETE",
            path=f"/loops/review/enrichment/actions/{action_preset_id}",
            idempotency_key=idempotency_key,
            payload={"action_preset_id": action_preset_id},
            execute=lambda conn: review_workflows.delete_enrichment_review_action(
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
    "/review/enrichment/sessions",
    response_model=list[EnrichmentReviewSessionResponse],
)
def list_enrichment_review_sessions_endpoint(
    settings: SettingsDep,
) -> list[EnrichmentReviewSessionResponse]:
    with db.core_connection(settings) as conn:
        sessions = review_workflows.list_enrichment_review_sessions(conn=conn)
    return [build_enrichment_review_session_response(session) for session in sessions]


@router.post(
    "/review/enrichment/sessions",
    response_model=EnrichmentReviewSessionSnapshotResponse,
    status_code=201,
)
def create_enrichment_review_session_endpoint(
    request: EnrichmentReviewSessionCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewSessionSnapshotResponse | JSONResponse:
    payload = request.model_dump(mode="json")
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/review/enrichment/sessions",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.create_enrichment_review_session(
                name=request.name,
                query=request.query,
                pending_kind=request.pending_kind,
                suggestion_limit=request.suggestion_limit,
                clarification_limit=request.clarification_limit,
                item_limit=request.item_limit,
                current_loop_id=request.current_loop_id,
                conn=conn,
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
    return build_enrichment_review_session_snapshot_response(result)


@router.get(
    "/review/enrichment/sessions/{session_id}",
    response_model=EnrichmentReviewSessionSnapshotResponse,
)
def get_enrichment_review_session_endpoint(
    session_id: int,
    settings: SettingsDep,
) -> EnrichmentReviewSessionSnapshotResponse:
    with db.core_connection(settings) as conn:
        try:
            snapshot = review_workflows.get_enrichment_review_session(
                session_id=session_id,
                conn=conn,
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
    return build_enrichment_review_session_snapshot_response(snapshot)


@router.post(
    "/review/enrichment/sessions/{session_id}/move",
    response_model=EnrichmentReviewSessionSnapshotResponse,
)
def move_enrichment_review_session_endpoint(
    session_id: int,
    request: ReviewSessionMoveRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewSessionSnapshotResponse | JSONResponse:
    payload = {"session_id": session_id, **request.model_dump(mode="json")}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/enrichment/sessions/{session_id}/move",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.move_enrichment_review_session(
                session_id=session_id,
                direction=request.direction,
                conn=conn,
            ),
        )
    except ResourceNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="review session") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None
    if isinstance(result, JSONResponse):
        return result
    return build_enrichment_review_session_snapshot_response(result)


@router.patch(
    "/review/enrichment/sessions/{session_id}",
    response_model=EnrichmentReviewSessionSnapshotResponse,
)
def update_enrichment_review_session_endpoint(
    session_id: int,
    request: EnrichmentReviewSessionUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewSessionSnapshotResponse | JSONResponse:
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
            path=f"/loops/review/enrichment/sessions/{session_id}",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id, **fields},
            execute=lambda conn: review_workflows.update_enrichment_review_session(
                session_id=session_id,
                name=fields.get("name"),
                query=fields.get("query"),
                pending_kind=fields.get("pending_kind"),
                suggestion_limit=fields.get("suggestion_limit"),
                clarification_limit=fields.get("clarification_limit"),
                item_limit=fields.get("item_limit"),
                current_loop_id=current_loop_id,
                conn=conn,
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
    return build_enrichment_review_session_snapshot_response(result)


@router.delete("/review/enrichment/sessions/{session_id}", response_model=None)
def delete_enrichment_review_session_endpoint(
    session_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, bool | int] | JSONResponse:
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="DELETE",
            path=f"/loops/review/enrichment/sessions/{session_id}",
            idempotency_key=idempotency_key,
            payload={"session_id": session_id},
            execute=lambda conn: review_workflows.delete_enrichment_review_session(
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
    "/review/enrichment/sessions/{session_id}/action",
    response_model=EnrichmentReviewSessionActionResponse,
)
def execute_enrichment_review_session_action_endpoint(
    session_id: int,
    request: EnrichmentReviewSessionActionRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewSessionActionResponse | JSONResponse:
    payload = {"session_id": session_id, **request.model_dump(mode="json")}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/enrichment/sessions/{session_id}/action",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.execute_enrichment_review_session_action(
                session_id=session_id,
                suggestion_id=request.suggestion_id,
                action_preset_id=request.action_preset_id,
                action_type=request.action_type,
                fields=request.fields,
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
    return build_enrichment_review_session_action_response(result)


@router.post(
    "/review/enrichment/sessions/{session_id}/clarifications/answer",
    response_model=EnrichmentReviewSessionClarificationResponse,
)
def answer_enrichment_review_session_clarifications_endpoint(
    session_id: int,
    request: EnrichmentReviewSessionClarificationRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> EnrichmentReviewSessionClarificationResponse | JSONResponse:
    answer_inputs = [
        enrichment_review.ClarificationAnswerInput(
            clarification_id=answer.clarification_id,
            answer=answer.answer,
        )
        for answer in request.answers
    ]
    payload = {
        "session_id": session_id,
        "loop_id": request.loop_id,
        "answers": [answer.model_dump(mode="json") for answer in request.answers],
    }
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/review/enrichment/sessions/{session_id}/clarifications/answer",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: review_workflows.answer_enrichment_review_session_clarifications(
                session_id=session_id,
                loop_id=request.loop_id,
                answers=answer_inputs,
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
    return build_enrichment_review_session_clarification_response(result)
