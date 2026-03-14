"""Loop relationship-review endpoints.

Purpose:
    Expose first-class duplicate/related-loop review across HTTP by delegating to
    the shared relationship-review contract.

Responsibilities:
    - Review duplicate/related candidates for a single loop
    - Confirm or dismiss one relationship candidate with idempotency support

Non-scope:
    - Queue/list endpoints for all loops (see query.py)
    - Merge preview or merge execution (see duplicates.py)
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ...loops import relationship_review
from ...loops.models import LoopStatus
from ...schemas.loops import (
    LoopRelationshipReviewResponse,
    RelationshipDecisionRequest,
    RelationshipDecisionResponse,
    RelationshipReviewCandidateResponse,
)
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_loop_response,
    run_idempotent_loop_route,
)
from .query import _resolve_statuses_for_search

router = APIRouter()


@router.get(
    "/{loop_id}/relationships/review",
    response_model=LoopRelationshipReviewResponse,
    tags=["loops"],
)
def review_loop_relationships_endpoint(
    loop_id: int,
    settings: SettingsDep,
    status: Annotated[
        LoopStatus | Literal["all", "open"],
        Query(description="Filter candidate loops by status scope, 'open', or 'all'"),
    ] = "open",
    duplicate_limit: Annotated[int, Query(ge=1, le=20)] = 10,
    related_limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> LoopRelationshipReviewResponse:
    status_value = status.value if isinstance(status, LoopStatus) else status
    statuses = _resolve_statuses_for_search(status_value)
    from ... import db

    with db.core_connection(settings) as conn:
        result = relationship_review.review_loop_relationships(
            loop_id=loop_id,
            statuses=statuses,
            duplicate_limit=duplicate_limit,
            related_limit=related_limit,
            conn=conn,
            settings=settings,
        )
    return LoopRelationshipReviewResponse(
        loop=build_loop_response(result["loop"]),
        indexed_count=result["indexed_count"],
        candidate_count=result["candidate_count"],
        duplicate_count=result["duplicate_count"],
        related_count=result["related_count"],
        duplicate_candidates=[
            RelationshipReviewCandidateResponse(**candidate)
            for candidate in result["duplicate_candidates"]
        ],
        related_candidates=[
            RelationshipReviewCandidateResponse(**candidate)
            for candidate in result["related_candidates"]
        ],
        existing_duplicates=[
            RelationshipReviewCandidateResponse(**candidate)
            for candidate in result["existing_duplicates"]
        ],
        existing_related=[
            RelationshipReviewCandidateResponse(**candidate)
            for candidate in result["existing_related"]
        ],
    )


@router.post(
    "/{loop_id}/relationships/{candidate_loop_id}/confirm",
    response_model=RelationshipDecisionResponse,
    tags=["loops"],
)
def confirm_relationship_endpoint(
    loop_id: int,
    candidate_loop_id: int,
    request: RelationshipDecisionRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipDecisionResponse | JSONResponse:
    payload = {
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "relationship_type": request.relationship_type,
    }
    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path=f"/loops/{loop_id}/relationships/{candidate_loop_id}/confirm",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: relationship_review.confirm_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=request.relationship_type,
            conn=conn,
        ),
    )
    if isinstance(result, JSONResponse):
        return result
    return RelationshipDecisionResponse(**result)


@router.post(
    "/{loop_id}/relationships/{candidate_loop_id}/dismiss",
    response_model=RelationshipDecisionResponse,
    tags=["loops"],
)
def dismiss_relationship_endpoint(
    loop_id: int,
    candidate_loop_id: int,
    request: RelationshipDecisionRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> RelationshipDecisionResponse | JSONResponse:
    payload = {
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "relationship_type": request.relationship_type,
    }
    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path=f"/loops/{loop_id}/relationships/{candidate_loop_id}/dismiss",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: relationship_review.dismiss_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=request.relationship_type,
            conn=conn,
        ),
    )
    if isinstance(result, JSONResponse):
        return result
    return RelationshipDecisionResponse(**result)
