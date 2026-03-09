"""Common utilities for loop routes.

Purpose:
    Shared dependencies, types, and helper functions used across
    all loop route modules.

Responsibilities:
    - Define common FastAPI dependencies (SettingsDep)
    - Define idempotency key header parameter
    - Provide helper for idempotency conflict HTTP exceptions

Non-scope:
    - Does not contain endpoint implementations
    - Does not define Pydantic schemas or request/response models
    - Does not interact with database directly
"""

from typing import Annotated, Any, Mapping, Sequence

from fastapi import Depends, Header, HTTPException

from ...schemas.loops import BulkResultItem, LoopCommentResponse, LoopResponse
from ...settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
IdempotencyKeyHeader = Header(
    default=None,
    alias="Idempotency-Key",
    description=(
        "Unique key for idempotent requests. Re-sending the same request "
        "with this key returns the original response. "
        "Format: UUID v4 or prefixed UUID (e.g., 'req_550e8400-e29b-41d4-a716-446655440000'). "
        "Max length: 255 characters."
    ),
)


def _idempotency_conflict(detail: str) -> HTTPException:
    """Create an HTTPException for idempotency key conflicts."""
    return HTTPException(
        status_code=409,
        detail={"message": "idempotency_key_conflict", "detail": detail},
    )


def build_loop_comment_response(comment: Mapping[str, Any]) -> LoopCommentResponse:
    """Convert a nested loop comment payload into the route response model."""
    replies = [build_loop_comment_response(reply) for reply in comment.get("replies", [])]
    return LoopCommentResponse(
        id=comment["id"],
        loop_id=comment["loop_id"],
        parent_id=comment.get("parent_id"),
        author=comment["author"],
        body_md=comment["body_md"],
        created_at_utc=comment["created_at_utc"],
        updated_at_utc=comment["updated_at_utc"],
        deleted_at_utc=comment.get("deleted_at_utc"),
        is_deleted=comment["is_deleted"],
        is_reply=comment["is_reply"],
        replies=replies,
    )


def build_bulk_result_items(results: Sequence[Mapping[str, Any]]) -> list[BulkResultItem]:
    """Convert service bulk-operation results into response envelopes."""
    return [
        BulkResultItem(
            index=result["index"],
            loop_id=result["loop_id"],
            ok=result["ok"],
            loop=LoopResponse(**result["loop"]) if result.get("loop") else None,
            error=result.get("error"),
        )
        for result in results
    ]
