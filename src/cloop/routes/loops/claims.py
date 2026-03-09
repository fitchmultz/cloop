"""Loop claim management endpoints.

Purpose:
    HTTP endpoints for managing loop claims (exclusive access leases).

Responsibilities:
    - Create exclusive access claims on loops with configurable TTL
    - Renew existing claims to extend lease duration
    - Release claims when operations complete
    - Query current claim status for a loop
    - Force-release claims via admin override

Non-scope:
    - Does not implement distributed locking across multiple servers
    - Does not notify claim holders when claims expire
    - Does not queue requests waiting for claim release

Endpoints:
- POST /{loop_id}/claim: Claim a loop for exclusive access
- POST /{loop_id}/renew: Renew an existing claim
- DELETE /{loop_id}/claim: Release a claim
- GET /{loop_id}/claim: Get claim status
- DELETE /{loop_id}/claim/force: Force-release a claim (admin)
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ... import db
from ...idempotency_flow import (
    finalize_idempotent_response,
    prepare_http_idempotency,
    replay_http_response,
)
from ...loops import service as loop_service
from ...loops.errors import ClaimNotFoundError, LoopClaimedError
from ...schemas.loops import (
    LoopClaimRequest,
    LoopClaimResponse,
    LoopClaimStatusResponse,
    LoopReleaseClaimRequest,
    LoopRenewClaimRequest,
)
from ._common import IdempotencyKeyHeader, SettingsDep

router = APIRouter()


@router.post("/{loop_id}/claim", response_model=LoopClaimResponse)
def claim_loop_endpoint(
    loop_id: int,
    request: LoopClaimRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopClaimResponse | JSONResponse:
    """Claim a loop for exclusive access.

    The returned claim_token must be provided for subsequent mutation operations
    while the claim is active.
    """
    payload = {"loop_id": loop_id, "owner": request.owner, "ttl_seconds": request.ttl_seconds}

    with db.core_connection(settings) as conn:
        idempotency = prepare_http_idempotency(
            method="POST",
            path=f"/loops/{loop_id}/claim",
            idempotency_key=idempotency_key,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_http_response(idempotency)
        if replay is not None:
            return replay

        try:
            result = loop_service.claim_loop(
                loop_id=loop_id,
                owner=request.owner,
                ttl_seconds=request.ttl_seconds,
                conn=conn,
                settings=settings,
            )
        except LoopClaimedError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "loop_claimed",
                    "message": str(exc),
                    "owner": exc.owner,
                    "lease_until": exc.lease_until,
                },
            ) from None

        finalize_idempotent_response(
            state=idempotency,
            response_status=200,
            response_body=result,
            conn=conn,
        )

    return LoopClaimResponse(**result)


@router.post("/{loop_id}/renew", response_model=LoopClaimResponse)
def renew_claim_endpoint(
    loop_id: int,
    request: LoopRenewClaimRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopClaimResponse | JSONResponse:
    """Renew an existing claim."""
    payload = {
        "loop_id": loop_id,
        "claim_token": request.claim_token,
        "ttl_seconds": request.ttl_seconds,
    }

    with db.core_connection(settings) as conn:
        idempotency = prepare_http_idempotency(
            method="POST",
            path=f"/loops/{loop_id}/renew",
            idempotency_key=idempotency_key,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_http_response(idempotency)
        if replay is not None:
            return replay

        try:
            result = loop_service.renew_claim(
                loop_id=loop_id,
                claim_token=request.claim_token,
                ttl_seconds=request.ttl_seconds,
                conn=conn,
                settings=settings,
            )
        except ClaimNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "claim_not_found",
                    "message": f"No valid claim for loop {loop_id}",
                },
            ) from None

        finalize_idempotent_response(
            state=idempotency,
            response_status=200,
            response_body=result,
            conn=conn,
        )

    return LoopClaimResponse(**result)


@router.delete("/{loop_id}/claim")
def release_claim_endpoint(
    loop_id: int,
    request: LoopReleaseClaimRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> Any:
    """Release a claim on a loop."""
    payload = {"loop_id": loop_id, "claim_token": request.claim_token}

    with db.core_connection(settings) as conn:
        idempotency = prepare_http_idempotency(
            method="DELETE",
            path=f"/loops/{loop_id}/claim",
            idempotency_key=idempotency_key,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_http_response(idempotency)
        if replay is not None:
            return replay

        try:
            loop_service.release_claim(
                loop_id=loop_id,
                claim_token=request.claim_token,
                conn=conn,
            )
        except ClaimNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "claim_not_found",
                    "message": f"No valid claim for loop {loop_id}",
                },
            ) from None

        result = {"ok": True, "loop_id": loop_id}
        finalize_idempotent_response(
            state=idempotency,
            response_status=200,
            response_body=result,
            conn=conn,
        )

    return result


@router.get("/{loop_id}/claim", response_model=LoopClaimStatusResponse | None)
def get_claim_status_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> LoopClaimStatusResponse | None:
    """Get the current claim status for a loop."""
    with db.core_connection(settings) as conn:
        claim = loop_service.get_claim_status(loop_id=loop_id, conn=conn)
    if claim is None:
        return None
    return LoopClaimStatusResponse(**claim)


@router.delete("/{loop_id}/claim/force")
def force_release_claim_endpoint(
    loop_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> Any:
    """Force-release any claim on a loop (admin override).

    This endpoint releases any active claim on the loop without requiring
    the claim token. Use with caution in production.
    """
    payload = {"loop_id": loop_id}

    with db.core_connection(settings) as conn:
        idempotency = prepare_http_idempotency(
            method="DELETE",
            path=f"/loops/{loop_id}/claim/force",
            idempotency_key=idempotency_key,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_http_response(idempotency)
        if replay is not None:
            return replay

        released = loop_service.force_release_claim(loop_id=loop_id, conn=conn)
        result = {"ok": True, "released": released, "loop_id": loop_id}
        finalize_idempotent_response(
            state=idempotency,
            response_status=200,
            response_body=result,
            conn=conn,
        )

    return result
