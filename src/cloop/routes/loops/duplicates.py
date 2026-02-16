"""Loop duplicate detection and merge endpoints.

Purpose:
    HTTP endpoints for detecting duplicate loops and merging them.

Endpoints:
- GET /{loop_id}/duplicates: List potential duplicate candidates
- GET /{loop_id}/merge-preview/{target_id}: Preview a merge operation
- POST /{loop_id}/merge: Merge this loop into another
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ... import db
from ...idempotency import (
    IdempotencyConflictError,
    build_http_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ...loops import service as loop_service
from ...loops.errors import LoopNotFoundError, MergeConflictError, ValidationError
from ...schemas.loops import (
    DuplicateCandidateResponse,
    DuplicatesListResponse,
    MergePreviewResponse,
    MergeRequest,
    MergeResultResponse,
)
from ._common import IdempotencyKeyHeader, SettingsDep, _idempotency_conflict

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

    with db.core_connection(settings) as conn:
        try:
            candidates = loop_service.find_duplicate_candidates_for_loop(
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

    with db.core_connection(settings) as conn:
        try:
            preview = loop_service.preview_merge(
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

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/merge")
        payload = {
            "loop_id": loop_id,
            "target_loop_id": request.target_loop_id,
            "field_overrides": request.field_overrides,
        }
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            try:
                result = loop_service.merge_loops(
                    surviving_loop_id=request.target_loop_id,
                    duplicate_loop_id=loop_id,
                    field_overrides=request.field_overrides or {},
                    conn=conn,
                    settings=settings,
                )
            except LoopNotFoundError as e:
                raise HTTPException(
                    status_code=404, detail=f"Loop not found: {e.loop_id}"
                ) from None
            except ValidationError as e:
                raise HTTPException(status_code=400, detail={"message": e.message}) from None
            except MergeConflictError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "merge_conflict",
                        "message": str(e),
                        "reason": e.reason,
                    },
                ) from None

            response = MergeResultResponse(
                surviving_loop_id=result.surviving_loop.id,
                closed_loop_id=result.closed_loop_id,
                merged_tags=result.merged_tags,
                fields_updated=result.fields_updated,
            ).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            try:
                result = loop_service.merge_loops(
                    surviving_loop_id=request.target_loop_id,
                    duplicate_loop_id=loop_id,
                    field_overrides=request.field_overrides or {},
                    conn=conn,
                    settings=settings,
                )
            except LoopNotFoundError as e:
                raise HTTPException(
                    status_code=404, detail=f"Loop not found: {e.loop_id}"
                ) from None
            except ValidationError as e:
                raise HTTPException(status_code=400, detail={"message": e.message}) from None
            except MergeConflictError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "merge_conflict",
                        "message": str(e),
                        "reason": e.reason,
                    },
                ) from None
        response = MergeResultResponse(
            surviving_loop_id=result.surviving_loop.id,
            closed_loop_id=result.closed_loop_id,
            merged_tags=result.merged_tags,
            fields_updated=result.fields_updated,
        ).model_dump()

    return MergeResultResponse(**response)
