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

from ...loops import service as loop_service
from ...loops.errors import LoopNotFoundError, ValidationError
from ...schemas.loops import (
    LoopCommentCreateRequest,
    LoopCommentListResponse,
    LoopCommentResponse,
    LoopCommentUpdateRequest,
)
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_loop_comment_response,
    run_idempotent_loop_route,
)

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
    payload = {
        "loop_id": loop_id,
        "author": request.author,
        "body_md": request.body_md,
        "parent_id": request.parent_id,
    }

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/{loop_id}/comments",
            idempotency_key=idempotency_key,
            payload=payload,
            response_status=201,
            execute=lambda conn: LoopCommentResponse(
                **loop_service.create_loop_comment(
                    loop_id=loop_id,
                    author=request.author,
                    body_md=request.body_md,
                    parent_id=request.parent_id,
                    conn=conn,
                ),
                replies=[],
            ).model_dump(),
        )
    except LoopNotFoundError:
        raise HTTPException(status_code=404, detail="Loop not found") from None
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail={"message": exc.message}) from None

    if isinstance(result, JSONResponse):
        return result
    return LoopCommentResponse(**result)


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
    from ... import db

    with db.core_connection(settings) as conn:
        try:
            result = loop_service.list_loop_comments(
                loop_id=loop_id,
                include_deleted=include_deleted,
                conn=conn,
            )
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None

    return LoopCommentListResponse(
        loop_id=result["loop_id"],
        comments=[build_loop_comment_response(comment) for comment in result["comments"]],
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
    payload = {"comment_id": comment_id, "body_md": request.body_md}

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="PATCH",
            path=f"/loops/{loop_id}/comments/{comment_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: LoopCommentResponse(
                **loop_service.update_loop_comment(
                    comment_id=comment_id,
                    body_md=request.body_md,
                    conn=conn,
                ),
                replies=[],
            ).model_dump(),
        )
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Comment not found or deleted") from None

    if isinstance(result, JSONResponse):
        return result
    return LoopCommentResponse(**result)


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
    payload = {"comment_id": comment_id}

    result = run_idempotent_loop_route(
        settings=settings,
        method="DELETE",
        path=f"/loops/{loop_id}/comments/{comment_id}",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: _delete_comment_response(comment_id=comment_id, conn=conn),
    )
    return result


def _delete_comment_response(*, comment_id: int, conn: Any) -> dict[str, Any]:
    """Delete a comment and normalize the route response body."""
    deleted = loop_service.delete_loop_comment(comment_id=comment_id, conn=conn)
    if not deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"ok": True, "deleted": True, "comment_id": comment_id}
