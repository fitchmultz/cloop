"""Loop duplicate detection and merge endpoints.

Purpose:
    HTTP endpoints for detecting duplicate loops and merging them.

Responsibilities:
    - List potential duplicate candidates for a loop using similarity scoring
    - Generate merge previews showing field conflicts and merged values
    - Execute merge operations with idempotency support
    - Handle merge conflicts with detailed error responses

Non-scope:
    - Does not perform automatic duplicate detection/merging
    - Does not manage loop claims or exclusive access
    - Does not handle loop creation or basic CRUD operations

Endpoints:
- GET /{loop_id}/duplicates: List potential duplicate candidates
- GET /{loop_id}/merge-preview/{target_id}: Preview a merge operation
- POST /{loop_id}/merge: Merge this loop into another
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ...loops import duplicates as loop_duplicates
from ...loops.errors import LoopNotFoundError, MergeConflictError, ValidationError
from ...schemas.loops import (
    DuplicateCandidateResponse,
    DuplicatesListResponse,
    MergePreviewResponse,
    MergeRequest,
    MergeResultResponse,
)
from ._common import IdempotencyKeyHeader, SettingsDep, run_idempotent_loop_route

router = APIRouter()


@router.get(
    "/{loop_id}/duplicates",
    response_model=DuplicatesListResponse,
    tags=["loops"],
)
def list_duplicate_candidates(
    loop_id: int,
    settings: SettingsDep,
) -> DuplicatesListResponse:
    """List potential duplicate loops for the given loop.

    Returns loops with similarity score >= CLOOP_DUPLICATE_SIMILARITY_THRESHOLD
    (default 0.95). Only non-terminal loops (not completed/dropped) are included.
    """

    from ... import db

    with db.core_connection(settings) as conn:
        try:
            candidates = loop_duplicates.find_duplicate_candidates_for_loop(
                loop_id=loop_id,
                conn=conn,
                settings=settings,
            )
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None

    return DuplicatesListResponse(
        loop_id=loop_id,
        candidates=[
            DuplicateCandidateResponse(
                loop_id=c["loop_id"],
                score=c["score"],
                title=c["title"],
                raw_text_preview=c["raw_text_preview"],
                status=c["status"],
                captured_at_utc=c["captured_at_utc"],
            )
            for c in candidates
        ],
    )


@router.get(
    "/{loop_id}/merge-preview/{target_id}",
    response_model=MergePreviewResponse,
    tags=["loops"],
)
def get_merge_preview(
    loop_id: int,
    target_id: int,
    settings: SettingsDep,
) -> MergePreviewResponse:
    """Preview what a merge would produce.

    Use this to show users a side-by-side comparison before confirming merge.
    loop_id is the duplicate that will be closed, target_id is the surviving loop.
    """

    from ... import db

    with db.core_connection(settings) as conn:
        try:
            preview = loop_duplicates.preview_merge(
                surviving_loop_id=target_id,
                duplicate_loop_id=loop_id,
                conn=conn,
            )
        except LoopNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"Loop not found: {e.loop_id}") from None
        except ValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message}) from None

    return MergePreviewResponse(
        surviving_loop_id=preview.surviving_loop_id,
        duplicate_loop_id=preview.duplicate_loop_id,
        merged_title=preview.merged_title,
        merged_summary=preview.merged_summary,
        merged_tags=preview.merged_tags,
        merged_next_action=preview.merged_next_action,
        field_conflicts=preview.field_conflicts,
    )


@router.post(
    "/{loop_id}/merge",
    response_model=MergeResultResponse,
    tags=["loops"],
)
def merge_into_loop(
    loop_id: int,
    request: MergeRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> MergeResultResponse | JSONResponse:
    """Merge this loop into another loop and close it as dropped.

    The target loop absorbs non-empty fields from this loop (if target field is empty),
    merges tags (union), and this loop is closed with status 'dropped'.

    This operation is irreversible. Use GET /loops/{id}/merge-preview/{target} first.
    """

    payload = {
        "loop_id": loop_id,
        "target_loop_id": request.target_loop_id,
        "field_overrides": request.field_overrides,
    }

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/{loop_id}/merge",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: _merge_response(
                loop_id=loop_id,
                target_loop_id=request.target_loop_id,
                field_overrides=request.field_overrides or {},
                conn=conn,
                settings=settings,
            ),
        )
    except LoopNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Loop not found: {exc.loop_id}") from None
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail={"message": exc.message}) from None
    except MergeConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "merge_conflict",
                "message": str(exc),
                "reason": exc.reason,
            },
        ) from None

    if isinstance(result, JSONResponse):
        return result
    return MergeResultResponse(**result)


def _merge_response(
    *,
    loop_id: int,
    target_loop_id: int,
    field_overrides: dict[str, str | None],
    conn: Any,
    settings: Any,
) -> dict[str, object]:
    """Execute a merge and normalize the route response body."""
    result = loop_duplicates.merge_loops(
        surviving_loop_id=target_loop_id,
        duplicate_loop_id=loop_id,
        field_overrides=field_overrides,
        conn=conn,
        settings=settings,
    )
    return MergeResultResponse(
        surviving_loop_id=result.surviving_loop.id,
        closed_loop_id=result.closed_loop_id,
        merged_tags=result.merged_tags,
        fields_updated=result.fields_updated,
    ).model_dump()
