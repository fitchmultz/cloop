"""Loop comment endpoints.

Purpose:
    HTTP endpoints for managing comments on loops.

Responsibilities:
    - Define FastAPI routes for comment CRUD operations
    - Validate incoming requests using Pydantic schemas
    - Handle idempotency for POST/PATCH/DELETE operations
    - Convert service layer results to HTTP responses
    - Route exceptions to appropriate HTTP status codes

Non-scope:
    - Does not implement comment business logic (delegated to service layer)
    - Does not persist comments directly (uses service layer)
    - Does not handle loop state management or transitions
    - Does not implement authentication or authorization

Endpoints:
- POST /{loop_id}/comments: Create a new comment
- GET /{loop_id}/comments: List comments for a loop
- PATCH /{loop_id}/comments/{comment_id}: Update a comment
- DELETE /{loop_id}/comments/{comment_id}: Soft-delete a comment
"""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
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
from ...loops.errors import LoopNotFoundError, ValidationError
from ...schemas.loops import (
    LoopCommentCreateRequest,
    LoopCommentListResponse,
    LoopCommentResponse,
    LoopCommentUpdateRequest,
)
from ._common import IdempotencyKeyHeader, SettingsDep, _idempotency_conflict

router = APIRouter()


@router.post(
    "/{loop_id}/comments",
    response_model=LoopCommentResponse,
    status_code=201,
    summary="Add a comment to a loop",
)
def create_comment_endpoint(
    loop_id: int,
    request: LoopCommentCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopCommentResponse | JSONResponse:
    """Add a comment to a loop.

    Comments support threading via parent_id. Set parent_id to create a reply.
    The body_md field supports markdown formatting.
    """
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/comments")
        payload = {
            "loop_id": loop_id,
            "author": request.author,
            "body_md": request.body_md,
            "parent_id": request.parent_id,
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
                comment = loop_service.create_loop_comment(
                    loop_id=loop_id,
                    author=request.author,
                    body_md=request.body_md,
                    parent_id=request.parent_id,
                    conn=conn,
                )
            except LoopNotFoundError:
                raise HTTPException(status_code=404, detail="Loop not found") from None
            except ValidationError as e:
                raise HTTPException(status_code=400, detail={"message": e.message}) from None

            response = LoopCommentResponse(**comment, replies=[]).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=201,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            try:
                comment = loop_service.create_loop_comment(
                    loop_id=loop_id,
                    author=request.author,
                    body_md=request.body_md,
                    parent_id=request.parent_id,
                    conn=conn,
                )
            except LoopNotFoundError:
                raise HTTPException(status_code=404, detail="Loop not found") from None
            except ValidationError as e:
                raise HTTPException(status_code=400, detail={"message": e.message}) from None
        response = LoopCommentResponse(**comment, replies=[]).model_dump()

    return LoopCommentResponse(**response)


@router.get(
    "/{loop_id}/comments",
    response_model=LoopCommentListResponse,
    summary="List comments for a loop",
)
def list_comments_endpoint(
    loop_id: int,
    settings: SettingsDep,
    include_deleted: Annotated[bool, Query(description="Include soft-deleted comments")] = False,
) -> LoopCommentListResponse:
    """List all comments for a loop in threaded order.

    Returns comments as a nested tree structure where replies are nested under their parent.
    Comments are ordered by creation time within each thread level.
    """
    with db.core_connection(settings) as conn:
        try:
            result = loop_service.list_loop_comments(
                loop_id=loop_id,
                include_deleted=include_deleted,
                conn=conn,
            )
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None

    def convert_comment(c: dict[str, Any]) -> LoopCommentResponse:
        replies = [convert_comment(r) for r in c.get("replies", [])]
        return LoopCommentResponse(
            id=c["id"],
            loop_id=c["loop_id"],
            parent_id=c.get("parent_id"),
            author=c["author"],
            body_md=c["body_md"],
            created_at_utc=c["created_at_utc"],
            updated_at_utc=c["updated_at_utc"],
            deleted_at_utc=c.get("deleted_at_utc"),
            is_deleted=c["is_deleted"],
            is_reply=c["is_reply"],
            replies=replies,
        )

    return LoopCommentListResponse(
        loop_id=result["loop_id"],
        comments=[convert_comment(c) for c in result["comments"]],
        total_count=result["total_count"],
    )


@router.patch(
    "/{loop_id}/comments/{comment_id}",
    response_model=LoopCommentResponse,
    summary="Update a comment",
)
def update_comment_endpoint(
    loop_id: int,
    comment_id: int,
    request: LoopCommentUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopCommentResponse | JSONResponse:
    """Update a comment's body.

    Only the body_md field can be updated. Author and parent_id are immutable.
    """
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("PATCH", f"/loops/{loop_id}/comments/{comment_id}")
        payload = {"comment_id": comment_id, "body_md": request.body_md}
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
                comment = loop_service.update_loop_comment(
                    comment_id=comment_id,
                    body_md=request.body_md,
                    conn=conn,
                )
            except RuntimeError:
                raise HTTPException(
                    status_code=404, detail="Comment not found or deleted"
                ) from None

            response = LoopCommentResponse(**comment, replies=[]).model_dump()
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
                comment = loop_service.update_loop_comment(
                    comment_id=comment_id,
                    body_md=request.body_md,
                    conn=conn,
                )
            except RuntimeError:
                raise HTTPException(
                    status_code=404, detail="Comment not found or deleted"
                ) from None
        response = LoopCommentResponse(**comment, replies=[]).model_dump()

    return LoopCommentResponse(**response)


@router.delete(
    "/{loop_id}/comments/{comment_id}",
    response_model=None,
    summary="Delete a comment",
)
def delete_comment_endpoint(
    loop_id: int,
    comment_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, Any] | JSONResponse:
    """Soft-delete a comment.

    The comment is marked as deleted but retained for audit trail.
    Deleted comments show is_deleted=true and body_md is replaced with [deleted].
    """
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("DELETE", f"/loops/{loop_id}/comments/{comment_id}")
        payload = {"comment_id": comment_id}
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

            deleted = loop_service.delete_loop_comment(comment_id=comment_id, conn=conn)
            if not deleted:
                raise HTTPException(status_code=404, detail="Comment not found")

            result = {"ok": True, "deleted": True, "comment_id": comment_id}
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=result,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            deleted = loop_service.delete_loop_comment(comment_id=comment_id, conn=conn)
            if not deleted:
                raise HTTPException(status_code=404, detail="Comment not found")
        result = {"ok": True, "deleted": True, "comment_id": comment_id}

    return result
