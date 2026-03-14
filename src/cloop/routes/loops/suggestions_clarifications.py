"""Suggestion and clarification endpoints.

Purpose:
    HTTP endpoints for enrichment follow-up workflows after suggestion generation.

Responsibilities:
    - List and inspect suggestions with linked clarification records
    - Apply or reject suggestions through the shared review service
    - List clarifications for a loop
    - Record clarification answers against existing clarification IDs

Non-scope:
    - Triggering enrichment generation itself
    - Core loop lifecycle mutations
    - Duplicate merge previews or merge execution
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ... import db
from ...loops import enrichment_review
from ...loops import repo as loop_repo
from ...loops.errors import (
    ClarificationNotFoundError,
    LoopNotFoundError,
    SuggestionNotFoundError,
    ValidationError,
)
from ...schemas.loops import (
    ApplySuggestionRequest,
    ApplySuggestionResponse,
    ClarificationListResponse,
    ClarificationSubmitBatchRequest,
    ClarificationSubmitRequest,
    ClarificationSubmitResponse,
    RejectSuggestionResponse,
    SuggestionListResponse,
    SuggestionResponse,
)
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_clarification_responses,
    build_clarification_submit_response,
    build_suggestion_list_response,
    build_suggestion_response,
    map_not_found_to_404,
    map_validation_to_400,
    run_idempotent_loop_route,
)

router = APIRouter()


@router.get("/{loop_id}/suggestions", response_model=SuggestionListResponse)
def get_loop_suggestions(
    loop_id: int,
    settings: SettingsDep,
    pending_only: Annotated[
        bool,
        Query(description="Only include unresolved suggestions", alias="pending_only"),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SuggestionListResponse:
    with db.core_connection(settings) as conn:
        suggestions = enrichment_review.list_loop_suggestions(
            loop_id=loop_id,
            pending_only=pending_only,
            limit=limit,
            conn=conn,
        )
    return build_suggestion_list_response(suggestions)


@router.get("/suggestions/pending", response_model=SuggestionListResponse)
def list_pending_suggestions_endpoint(
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SuggestionListResponse:
    with db.core_connection(settings) as conn:
        suggestions = enrichment_review.list_loop_suggestions(
            pending_only=True,
            limit=limit,
            conn=conn,
        )
    return build_suggestion_list_response(suggestions)


@router.get("/suggestions/{suggestion_id}", response_model=SuggestionResponse)
def get_suggestion_endpoint(
    suggestion_id: int,
    settings: SettingsDep,
) -> SuggestionResponse:
    with db.core_connection(settings) as conn:
        try:
            suggestion = enrichment_review.get_loop_suggestion(
                suggestion_id=suggestion_id,
                conn=conn,
            )
        except SuggestionNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="suggestion") from None
    return build_suggestion_response(suggestion)


@router.post("/suggestions/{suggestion_id}/apply", response_model=ApplySuggestionResponse)
def apply_suggestion_endpoint(
    suggestion_id: int,
    request: ApplySuggestionRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> ApplySuggestionResponse | JSONResponse:
    payload = {
        "suggestion_id": suggestion_id,
        "fields": list(request.fields) if request.fields is not None else None,
    }

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/suggestions/{suggestion_id}/apply",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: enrichment_review.apply_suggestion(
                suggestion_id=suggestion_id,
                fields=request.fields,
                conn=conn,
                settings=settings,
            ),
        )
    except SuggestionNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="suggestion") from None
    except LoopNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="loop") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None

    if isinstance(result, JSONResponse):
        return result
    return ApplySuggestionResponse(**result)


@router.post("/suggestions/{suggestion_id}/reject", response_model=RejectSuggestionResponse)
def reject_suggestion_endpoint(
    suggestion_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RejectSuggestionResponse | JSONResponse:
    payload = {"suggestion_id": suggestion_id}

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/suggestions/{suggestion_id}/reject",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: enrichment_review.reject_suggestion(
                suggestion_id=suggestion_id,
                conn=conn,
            ),
        )
    except SuggestionNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="suggestion") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None

    if isinstance(result, JSONResponse):
        return result
    return RejectSuggestionResponse(**result)


@router.get("/{loop_id}/clarifications", response_model=ClarificationListResponse)
def get_loop_clarifications(
    loop_id: int,
    settings: SettingsDep,
) -> ClarificationListResponse:
    with db.core_connection(settings) as conn:
        try:
            clarifications = enrichment_review.list_loop_clarifications(loop_id=loop_id, conn=conn)
        except LoopNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="loop") from None

    responses = build_clarification_responses(clarifications)
    return ClarificationListResponse(clarifications=responses, count=len(responses))


@router.post(
    "/clarifications/{clarification_id}/answer",
    response_model=ClarificationSubmitResponse,
)
def answer_single_clarification_endpoint(
    clarification_id: int,
    request: ClarificationSubmitRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> ClarificationSubmitResponse | JSONResponse:
    if request.clarification_id != clarification_id:
        raise map_validation_to_400(
            ValidationError(
                "clarification_id",
                "path clarification_id must match request clarification_id",
            )
        )

    with db.core_connection(settings) as conn:
        clarification = loop_repo.read_loop_clarification(
            clarification_id=clarification_id,
            conn=conn,
        )
        if clarification is None:
            raise map_not_found_to_404(
                ClarificationNotFoundError(clarification_id),
                resource_type="clarification",
            )
        loop_id = int(clarification["loop_id"])

    batch_request = ClarificationSubmitBatchRequest(answers=[request])
    return answer_loop_clarifications_endpoint(
        loop_id=loop_id,
        request=batch_request,
        settings=settings,
        idempotency_key=idempotency_key,
    )


@router.post("/{loop_id}/clarifications/answer", response_model=ClarificationSubmitResponse)
def answer_loop_clarifications_endpoint(
    loop_id: int,
    request: ClarificationSubmitBatchRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> ClarificationSubmitResponse | JSONResponse:
    payload = {
        "loop_id": loop_id,
        "answers": [answer.model_dump(mode="json") for answer in request.answers],
    }
    answer_inputs = [
        enrichment_review.ClarificationAnswerInput(
            clarification_id=answer.clarification_id,
            answer=answer.answer,
        )
        for answer in request.answers
    ]

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/{loop_id}/clarifications/answer",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: enrichment_review.submit_clarification_answers(
                loop_id=loop_id,
                answers=answer_inputs,
                conn=conn,
            ).to_payload(),
        )
    except LoopNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="loop") from None
    except ClarificationNotFoundError as exc:
        raise map_not_found_to_404(exc, resource_type="clarification") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None

    if isinstance(result, JSONResponse):
        return result
    return build_clarification_submit_response(result)
