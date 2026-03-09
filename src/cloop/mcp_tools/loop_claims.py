"""Loop claim management MCP tools.

Purpose:
    MCP tools for managing exclusive access claims on loops.

Responsibilities:
    - Claim loops for exclusive access with time-limited leases
    - Renew and release existing claims
    - Query claim status for loops
    - List all active claims with optional filtering
    - Support admin force-release of claims
    - Handle idempotency for claim mutations

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

from .. import db
from ..loops import service as loop_service
from ..settings import get_settings
from ._idempotency import (
    finalize_tool_idempotency,
    prepare_tool_idempotency,
    replay_tool_response,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.claim",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        result = loop_service.claim_loop(
            loop_id=loop_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            conn=conn,
            settings=settings,
        )
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
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

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.renew_claim",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        result = loop_service.renew_claim(
            loop_id=loop_id,
            claim_token=claim_token,
            ttl_seconds=ttl_seconds,
            conn=conn,
            settings=settings,
        )
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
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

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.release_claim",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        loop_service.release_claim(
            loop_id=loop_id,
            claim_token=claim_token,
            conn=conn,
        )
        result = {"ok": True}
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
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

    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name="loop.force_release_claim",
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        released = loop_service.force_release_claim(loop_id=loop_id, conn=conn)
        result = {"ok": True, "released": released}
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
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
