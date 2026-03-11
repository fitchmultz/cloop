"""Loop query and listing endpoints.

Purpose:
    HTTP endpoints for loop listing, tag lookup, next-loop prioritization,
    review cohorts, and DSL-based search.

Responsibilities:
    - List loops by status/tag
    - Return loop tags
    - Compute prioritized next-loop buckets
    - Return review cohorts
    - Execute canonical DSL search

Non-scope:
    - Loop mutations and enrichment requests
    - Import/export and metrics responses
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from ... import db
from ...constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
from ...loops import read_service as loop_read_service
from ...loops.models import LoopStatus
from ...loops.review import compute_review_cohorts
from ...loops.utils import normalize_tag
from ...schemas.loops import (
    LoopNextResponse,
    LoopResponse,
    LoopReviewCohortItem,
    LoopReviewCohortResponse,
    LoopReviewResponse,
    LoopSearchRequest,
    LoopSearchResponse,
)
from ._common import SettingsDep

router = APIRouter()


@router.get("/", response_model=list[LoopResponse])
def loop_list_endpoint(
    settings: SettingsDep,
    status: Annotated[
        LoopStatus | Literal["all", "open"] | None,
        Query(description="Filter by loop status, 'open', or 'all'"),
    ] = "open",
    tag: Annotated[str | None, Query(description="Filter by tag")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_LOOP_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LoopResponse]:
    tag_value = normalize_tag(tag)
    with db.core_connection(settings) as conn:
        if status == "open":
            statuses = [
                LoopStatus.INBOX,
                LoopStatus.ACTIONABLE,
                LoopStatus.BLOCKED,
                LoopStatus.SCHEDULED,
            ]
            if tag_value:
                loops = loop_read_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_read_service.list_loops_by_statuses(
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
        else:
            resolved_status = None if status is None or status == "all" else status
            if tag_value:
                statuses = [resolved_status] if resolved_status else None
                loops = loop_read_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_read_service.list_loops(
                    status=resolved_status,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
    return [LoopResponse(**loop_item) for loop_item in loops]


@router.get("/tags", response_model=list[str])
def loop_tags_endpoint(settings: SettingsDep) -> list[str]:
    with db.core_connection(settings) as conn:
        return loop_read_service.list_tags(conn=conn)


@router.get("/next", response_model=LoopNextResponse)
def loop_next_endpoint(
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=20)] = DEFAULT_LOOP_NEXT_LIMIT,
) -> LoopNextResponse:
    with db.core_connection(settings) as conn:
        result: dict[str, list[dict[str, object]]] = loop_read_service.next_loops(
            limit=limit,
            conn=conn,
        )
    return LoopNextResponse(
        due_soon=[LoopResponse(**item) for item in result["due_soon"]],
        quick_wins=[LoopResponse(**item) for item in result["quick_wins"]],
        high_leverage=[LoopResponse(**item) for item in result["high_leverage"]],
        standard=[LoopResponse(**item) for item in result["standard"]],
    )


@router.get("/review", response_model=LoopReviewResponse)
def loop_review_endpoint(
    settings: SettingsDep,
    daily: Annotated[bool, Query(description="Include daily cohorts")] = True,
    weekly: Annotated[bool, Query(description="Include weekly cohorts")] = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LoopReviewResponse:
    from ...loops.models import utc_now

    with db.core_connection(settings) as conn:
        result = compute_review_cohorts(
            settings=settings,
            now_utc=utc_now(),
            conn=conn,
            include_daily=daily,
            include_weekly=weekly,
            limit_per_cohort=limit,
        )

    return LoopReviewResponse(
        daily=[
            LoopReviewCohortResponse(
                cohort=c.cohort.value,
                count=c.count,
                items=[LoopReviewCohortItem(**item) for item in c.items],
            )
            for c in result.daily
        ],
        weekly=[
            LoopReviewCohortResponse(
                cohort=c.cohort.value,
                count=c.count,
                items=[LoopReviewCohortItem(**item) for item in c.items],
            )
            for c in result.weekly
        ],
        generated_at_utc=result.generated_at_utc,
    )


@router.post("/search", response_model=LoopSearchResponse)
def loop_search_endpoint(
    request: LoopSearchRequest,
    settings: SettingsDep,
) -> LoopSearchResponse:
    with db.core_connection(settings) as conn:
        items = loop_read_service.search_loops_by_query(
            query=request.query,
            limit=request.limit,
            offset=request.offset,
            conn=conn,
        )
    return LoopSearchResponse(
        query=request.query,
        limit=request.limit,
        offset=request.offset,
        items=[LoopResponse(**item) for item in items],
    )
