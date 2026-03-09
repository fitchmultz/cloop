"""Common utilities for loop routes.

Purpose:
    Shared dependencies, types, and helper functions used across
    all loop route modules.

Responsibilities:
    - Define common FastAPI dependencies (SettingsDep)
    - Define idempotency key header parameter
    - Provide helpers for idempotent mutation routes
    - Standardize common loop route error payloads and response conversion

Non-scope:
    - Does not contain endpoint implementations
    - Does not define Pydantic schemas or request/response models
    - Does not interact with database directly
"""

from collections.abc import Callable
from typing import Annotated, Any, Mapping, Sequence

from fastapi import Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from ... import db
from ...idempotency_flow import (
    finalize_idempotent_response,
    prepare_http_idempotency,
    replay_http_response,
)
from ...loops.errors import LoopClaimedError
from ...schemas.loops import (
    BulkResultItem,
    LoopCommentResponse,
    LoopResponse,
    LoopTemplateResponse,
    LoopViewResponse,
)
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


def run_idempotent_loop_route(
    *,
    settings: Settings,
    method: str,
    path: str,
    idempotency_key: str | None,
    payload: Mapping[str, Any],
    execute: Callable[[Any], Any],
    response_status: int = 200,
) -> JSONResponse | Any:
    """Run a mutation route with shared connection and idempotency handling."""
    with db.core_connection(settings) as conn:
        idempotency = prepare_http_idempotency(
            method=method,
            path=path,
            idempotency_key=idempotency_key,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_http_response(idempotency)
        if replay is not None:
            return replay

        response_body = execute(conn)
        finalize_idempotent_response(
            state=idempotency,
            response_status=response_status,
            response_body=response_body,
            conn=conn,
        )
        return response_body


def loop_claimed_http_exception(exc: LoopClaimedError) -> HTTPException:
    """Build the standard HTTP 409 payload for an active loop claim."""
    return HTTPException(
        status_code=409,
        detail={
            "code": "loop_claimed",
            "message": str(exc),
            "owner": exc.owner,
            "lease_until": exc.lease_until,
        },
    )


def invalid_claim_token_http_exception() -> HTTPException:
    """Build the standard HTTP 403 payload for a missing or stale claim token."""
    return HTTPException(
        status_code=403,
        detail={
            "code": "invalid_claim_token",
            "message": "Invalid or expired claim token",
        },
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


def build_query_bulk_preview_response(result: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a dry-run bulk result into preview response kwargs."""
    return {
        "query": result["query"],
        "dry_run": True,
        "matched_count": result["matched_count"],
        "limited": result.get("limited", False),
        "targets": [LoopResponse(**item) for item in result.get("targets", [])],
    }


def build_loop_view_response(view: Mapping[str, Any]) -> LoopViewResponse:
    """Convert a saved view record into the route response model."""
    return LoopViewResponse(
        id=view["id"],
        name=view["name"],
        query=view["query"],
        description=view.get("description"),
        created_at_utc=view["created_at"],
        updated_at_utc=view["updated_at"],
    )


def build_loop_template_response(template: Mapping[str, Any]) -> LoopTemplateResponse:
    """Convert a template record into the route response model."""
    import json

    return LoopTemplateResponse(
        id=template["id"],
        name=template["name"],
        description=template["description"],
        raw_text_pattern=template["raw_text_pattern"],
        defaults=json.loads(template["defaults_json"]) if template["defaults_json"] else {},
        is_system=bool(template["is_system"]),
        created_at=template["created_at"],
        updated_at=template["updated_at"],
    )
