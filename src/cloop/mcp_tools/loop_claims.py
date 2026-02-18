"""Loop claim management MCP tools.

Purpose:
    MCP tools for managing exclusive access claims on loops.

Tools:
    - loop.claim: Claim a loop for exclusive access
    - loop.renew_claim: Renew an existing claim
    - loop.release_claim: Release a claim
    - loop.get_claim: Get claim status for a loop
    - loop.list_claims: List all active claims
    - loop.force_release_claim: Force-release a claim (admin override)

Non-scope:
    - Claim persistence layer (see loops/service.py)
    - Token generation (handled in repo layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..idempotency import (
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ..loops import service as loop_service
from ..settings import get_settings

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _handle_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    settings: Any,
) -> dict[str, Any] | None:
    """Handle idempotency for MCP tool calls."""
    from ..idempotency import IdempotencyConflictError

    if request_id is None:
        return None

    try:
        key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    except ValueError as e:
        raise ToolError(str(e)) from None

    scope = build_mcp_scope(tool_name)
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
            raise ToolError(f"Idempotency conflict: {e}") from None

        if not claim["is_new"] and claim["replay"]:
            return claim["replay"]["response_body"]

        return None


def _finalize_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    response: dict[str, Any],
    settings: Any,
) -> None:
    """Store response for idempotent MCP tool call."""
    if request_id is None:
        return

    key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    scope = build_mcp_scope(tool_name)

    with db.core_connection(settings) as conn:
        db.finalize_idempotency_response(
            scope=scope,
            idempotency_key=key,
            response_status=200,
            response_body=response,
            conn=conn,
        )


def loop_claim(
    loop_id: int,
    owner: str,
    ttl_seconds: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Claim a loop for exclusive access. Returns claim_token required for mutations.

    Args:
        loop_id: Loop ID to claim
        owner: Identifier for the claiming agent
        ttl_seconds: Lease duration in seconds (default 300)
        request_id: Optional idempotency key

    Returns:
        Dict with claim details including claim_token
    """
    settings = get_settings()

    payload = {"loop_id": loop_id, "owner": owner, "ttl_seconds": ttl_seconds}

    replay = _handle_mcp_idempotency(
        tool_name="loop.claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.claim_loop(
            loop_id=loop_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            conn=conn,
            settings=settings,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


def loop_renew_claim(
    loop_id: int,
    claim_token: str,
    ttl_seconds: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Renew an existing claim on a loop.

    Args:
        loop_id: Loop ID
        claim_token: Token from original claim
        ttl_seconds: New lease duration in seconds
        request_id: Optional idempotency key

    Returns:
        Dict with updated claim details
    """
    settings = get_settings()

    payload = {
        "loop_id": loop_id,
        "claim_token": claim_token,
        "ttl_seconds": ttl_seconds,
    }

    replay = _handle_mcp_idempotency(
        tool_name="loop.renew_claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.renew_claim(
            loop_id=loop_id,
            claim_token=claim_token,
            ttl_seconds=ttl_seconds,
            conn=conn,
            settings=settings,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.renew_claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


def loop_release_claim(
    loop_id: int,
    claim_token: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Release a claim on a loop.

    Args:
        loop_id: Loop ID
        claim_token: Token from original claim
        request_id: Optional idempotency key

    Returns:
        Dict with ok status
    """
    settings = get_settings()

    payload = {"loop_id": loop_id, "claim_token": claim_token}

    replay = _handle_mcp_idempotency(
        tool_name="loop.release_claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        loop_service.release_claim(
            loop_id=loop_id,
            claim_token=claim_token,
            conn=conn,
        )

    result = {"ok": True}
    _finalize_mcp_idempotency(
        tool_name="loop.release_claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


def loop_get_claim(loop_id: int) -> dict[str, Any] | None:
    """Get the current claim status for a loop.

    Args:
        loop_id: Loop ID to check

    Returns:
        Dict with claim info (without token) or None if not claimed
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.get_claim_status(loop_id=loop_id, conn=conn)


def loop_list_claims(
    owner: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List all active claims.

    Args:
        owner: Optional owner filter
        limit: Max results (default 100)

    Returns:
        List of claim dicts (without tokens) ordered by lease_until ascending
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.list_active_claims(owner=owner, limit=limit, conn=conn)


def loop_force_release_claim(
    loop_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Force-release any claim on a loop (admin override).

    Args:
        loop_id: Loop ID
        request_id: Optional idempotency key

    Returns:
        Dict with ok and released status
    """
    settings = get_settings()

    payload = {"loop_id": loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.force_release_claim",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        released = loop_service.force_release_claim(loop_id=loop_id, conn=conn)

    result = {"ok": True, "released": released}
    _finalize_mcp_idempotency(
        tool_name="loop.force_release_claim",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


def register_loop_claim_tools(mcp: "FastMCP") -> None:
    """Register loop claim management tools with the MCP server."""
    from ..mcp_server import with_db_init, with_mcp_error_handling

    mcp.tool(name="loop.claim")(with_db_init(with_mcp_error_handling(loop_claim)))
    mcp.tool(name="loop.renew_claim")(with_db_init(with_mcp_error_handling(loop_renew_claim)))
    mcp.tool(name="loop.release_claim")(with_db_init(with_mcp_error_handling(loop_release_claim)))
    mcp.tool(name="loop.get_claim")(with_db_init(with_mcp_error_handling(loop_get_claim)))
    mcp.tool(name="loop.list_claims")(with_db_init(with_mcp_error_handling(loop_list_claims)))
    mcp.tool(name="loop.force_release_claim")(
        with_db_init(with_mcp_error_handling(loop_force_release_claim))
    )
