"""Enrichment review workflow HTTP endpoints.

Purpose:
    Expose durable enrichment-review actions and saved session flows over
    HTTP through the shared review workflow orchestration.

Responsibilities:
    - CRUD enrichment-review action presets
    - CRUD and move saved enrichment-review sessions
    - Execute queued enrichment actions and clarification refinements within a saved session

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Enrichment-review HTTP request/response shaping only
    - No suggestion-generation or clarification business logic

Usage:
    Included by `cloop.routes.loops.review_workflows`.

Invariants/Assumptions:
    - Route paths stay under `/loops/review/enrichment/*`
    - Shared workflow exceptions map through the standard loop-route helpers
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ....loops import enrichment_review, review_workflows
from ....loops.errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ....schemas.loops import (
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
    ReviewSessionMoveRequest,
)
from ....settings import Settings
from .._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_enrichment_review_action_response,
    build_enrichment_review_session_action_response,
    build_enrichment_review_session_clarification_response,
    build_enrichment_review_session_response,
    build_enrichment_review_session_snapshot_response,
    map_not_found_to_404,
    map_validation_to_400,
    run_idempotent_loop_route,
)
from .http_scaffolding import (
    register_review_workflow_action_routes,
    register_review_workflow_session_routes,
)

router = APIRouter()


def _enrichment_update_action_execute(
    conn: Any,
    action_preset_id: int,
    fields: dict[str, Any],
) -> Any:
    return review_workflows.update_enrichment_review_action(
        action_preset_id=action_preset_id,
        name=fields.get("name"),
        action_type=fields.get("action_type"),
        fields=fields.get("fields"),
        description=fields.get("description"),
        conn=conn,
    )


def _enrichment_create_session_execute(
    conn: Any,
    req: EnrichmentReviewSessionCreateRequest,
    _settings: Settings,
) -> Any:
    return review_workflows.create_enrichment_review_session(
        name=req.name,
        query=req.query,
        pending_kind=req.pending_kind,
        suggestion_limit=req.suggestion_limit,
        clarification_limit=req.clarification_limit,
        item_limit=req.item_limit,
        current_loop_id=req.current_loop_id,
        conn=conn,
    )


def _enrichment_get_session_snapshot(conn: Any, session_id: int, _settings: Settings) -> Any:
    return review_workflows.get_enrichment_review_session(session_id=session_id, conn=conn)


def _enrichment_move_session_execute(
    conn: Any,
    session_id: int,
    request: ReviewSessionMoveRequest,
    _settings: Settings,
) -> Any:
    return review_workflows.move_enrichment_review_session(
        session_id=session_id,
        direction=request.direction,
        conn=conn,
    )


def _enrichment_refresh_session_execute(conn: Any, session_id: int, _settings: Settings) -> Any:
    return review_workflows.refresh_enrichment_review_session(session_id=session_id, conn=conn)


def _enrichment_patch_session_execute(
    conn: Any,
    session_id: int,
    fields: dict[str, Any],
    current_loop_id: Any,
    _settings: Settings,
) -> Any:
    return review_workflows.update_enrichment_review_session(
        session_id=session_id,
        name=fields.get("name"),
        query=fields.get("query"),
        pending_kind=fields.get("pending_kind"),
        suggestion_limit=fields.get("suggestion_limit"),
        clarification_limit=fields.get("clarification_limit"),
        item_limit=fields.get("item_limit"),
        current_loop_id=current_loop_id,
        conn=conn,
    )


def _enrichment_session_action_execute(
    conn: Any,
    session_id: int,
    req: EnrichmentReviewSessionActionRequest,
    settings: Settings,
) -> Any:
    return review_workflows.execute_enrichment_review_session_action(
        session_id=session_id,
        suggestion_id=req.suggestion_id,
        action_preset_id=req.action_preset_id,
        action_type=req.action_type,
        fields=req.fields,
        conn=conn,
        settings=settings,
    )


def _enrichment_delete_action_execute(conn: Any, action_preset_id: int) -> Any:
    return review_workflows.delete_enrichment_review_action(
        action_preset_id=action_preset_id,
        conn=conn,
    )


def _enrichment_delete_session_execute(conn: Any, session_id: int) -> Any:
    return review_workflows.delete_enrichment_review_session(session_id=session_id, conn=conn)


_actions = register_review_workflow_action_routes(
    router,
    segment="enrichment",
    action_response_model=EnrichmentReviewActionResponse,
    action_create_type=EnrichmentReviewActionCreateRequest,
    action_update_type=EnrichmentReviewActionUpdateRequest,
    list_actions=lambda conn: review_workflows.list_enrichment_review_actions(conn=conn),
    build_action_response=build_enrichment_review_action_response,
    create_execute=lambda conn, req: review_workflows.create_enrichment_review_action(
        name=req.name,
        action_type=req.action_type,
        fields=req.fields,
        description=req.description,
        conn=conn,
    ),
    get_action=lambda conn, action_preset_id: review_workflows.get_enrichment_review_action(
        action_preset_id=action_preset_id,
        conn=conn,
    ),
    update_execute=_enrichment_update_action_execute,
    delete_execute=_enrichment_delete_action_execute,
)

_sessions = register_review_workflow_session_routes(
    router,
    segment="enrichment",
    session_row_response_model=EnrichmentReviewSessionResponse,
    snapshot_response_model=EnrichmentReviewSessionSnapshotResponse,
    session_action_response_model=EnrichmentReviewSessionActionResponse,
    session_create_type=EnrichmentReviewSessionCreateRequest,
    session_update_type=EnrichmentReviewSessionUpdateRequest,
    session_action_request_type=EnrichmentReviewSessionActionRequest,
    list_sessions=lambda conn: review_workflows.list_enrichment_review_sessions(conn=conn),
    build_session_response=build_enrichment_review_session_response,
    build_snapshot_response=build_enrichment_review_session_snapshot_response,
    build_session_action_response=build_enrichment_review_session_action_response,
    create_session_execute=_enrichment_create_session_execute,
    get_session_snapshot=_enrichment_get_session_snapshot,
    move_session_execute=_enrichment_move_session_execute,
    refresh_session_execute=_enrichment_refresh_session_execute,
    patch_session_execute=_enrichment_patch_session_execute,
    delete_session_execute=_enrichment_delete_session_execute,
    session_action_execute=_enrichment_session_action_execute,
)

list_enrichment_review_actions_endpoint = _actions.list_actions
create_enrichment_review_action_endpoint = _actions.create_action
get_enrichment_review_action_endpoint = _actions.get_action
update_enrichment_review_action_endpoint = _actions.update_action
delete_enrichment_review_action_endpoint = _actions.delete_action

list_enrichment_review_sessions_endpoint = _sessions.list_sessions
create_enrichment_review_session_endpoint = _sessions.create_session
get_enrichment_review_session_endpoint = _sessions.get_session
move_enrichment_review_session_endpoint = _sessions.move_session
refresh_enrichment_review_session_endpoint = _sessions.refresh_session
update_enrichment_review_session_endpoint = _sessions.update_session
delete_enrichment_review_session_endpoint = _sessions.delete_session
execute_enrichment_review_session_action_endpoint = _sessions.execute_session_action


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


__all__ = [
    "router",
    "list_enrichment_review_actions_endpoint",
    "create_enrichment_review_action_endpoint",
    "get_enrichment_review_action_endpoint",
    "update_enrichment_review_action_endpoint",
    "delete_enrichment_review_action_endpoint",
    "list_enrichment_review_sessions_endpoint",
    "create_enrichment_review_session_endpoint",
    "get_enrichment_review_session_endpoint",
    "move_enrichment_review_session_endpoint",
    "refresh_enrichment_review_session_endpoint",
    "update_enrichment_review_session_endpoint",
    "delete_enrichment_review_session_endpoint",
    "execute_enrichment_review_session_action_endpoint",
    "answer_enrichment_review_session_clarifications_endpoint",
]
