"""MCP tools for duplicate/related-loop relationship review.

Purpose:
    Expose first-class relationship review and decision flows to MCP clients.

Responsibilities:
    - Review duplicate/related candidates for one loop
    - List loops with pending relationship-review work
    - Confirm or dismiss relationship candidates with idempotency support

Non-scope:
    - Merge preview and merge execution
    - Generic loop CRUD operations
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..loops import relationship_review
from ..loops.models import LoopStatus
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _parse_loop_status_filter(status: str) -> list[LoopStatus] | None:
    if status == "all":
        return None
    if status == "open":
        return [
            LoopStatus.INBOX,
            LoopStatus.ACTIONABLE,
            LoopStatus.BLOCKED,
            LoopStatus.SCHEDULED,
        ]
    return [LoopStatus(status)]


@with_mcp_error_handling
def loop_relationship_review(
    loop_id: int,
    status: str = "open",
    duplicate_limit: int = 10,
    related_limit: int = 10,
) -> dict[str, Any]:
    """Review duplicate and related-loop candidates for one loop.

    Args:
        loop_id: Loop to review.
        status: Candidate status scope (`open`, `all`, or one concrete status).
        duplicate_limit: Maximum duplicate candidates to return.
        related_limit: Maximum related candidates to return.

    Returns:
        Dict with the source `loop`, candidate counts, indexing info, and both
        `duplicate_candidates` and `related_candidates` lists.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    statuses = _parse_loop_status_filter(status)
    with db.core_connection(settings) as conn:
        return relationship_review.review_loop_relationships(
            loop_id=loop_id,
            statuses=statuses,
            duplicate_limit=duplicate_limit,
            related_limit=related_limit,
            conn=conn,
            settings=settings,
        )


@with_mcp_error_handling
def loop_relationship_queue(
    status: str = "open",
    relationship_kind: str = "all",
    limit: int = 25,
    candidate_limit: int = 3,
) -> dict[str, Any]:
    """List loops with pending duplicate/related-loop review work.

    Args:
        status: Loop status scope (`open`, `all`, or one concrete status).
        relationship_kind: Queue kind (`all`, `duplicate`, or `related`).
        limit: Maximum loops to return.
        candidate_limit: Maximum candidates to preview per loop.

    Returns:
        Dict with indexing metadata plus queue `items`.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    statuses = _parse_loop_status_filter(status)
    with db.core_connection(settings) as conn:
        return relationship_review.list_relationship_review_queue(
            statuses=statuses,
            relationship_kind=relationship_kind,
            limit=limit,
            candidate_limit=candidate_limit,
            conn=conn,
            settings=settings,
        )


@with_mcp_error_handling
def loop_relationship_confirm(
    loop_id: int,
    candidate_loop_id: int,
    relationship_type: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Confirm a duplicate or related-loop relationship.

    Args:
        loop_id: Source loop ID.
        candidate_loop_id: Candidate loop ID.
        relationship_type: `related` or `duplicate`.
        request_id: Optional idempotency key.

    Returns:
        Dict describing the confirmed relationship state.

    Raises:
        ToolError: If validation fails or either loop is missing.
    """
    payload = {
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "relationship_type": relationship_type,
    }
    return run_idempotent_tool_mutation(
        tool_name="loop.relationship_confirm",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: relationship_review.confirm_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=relationship_type,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def loop_relationship_dismiss(
    loop_id: int,
    candidate_loop_id: int,
    relationship_type: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Dismiss a duplicate or related-loop relationship suggestion.

    Args:
        loop_id: Source loop ID.
        candidate_loop_id: Candidate loop ID.
        relationship_type: `related` or `duplicate`.
        request_id: Optional idempotency key.

    Returns:
        Dict describing the dismissed relationship state.

    Raises:
        ToolError: If validation fails or either loop is missing.
    """
    payload = {
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "relationship_type": relationship_type,
    }
    return run_idempotent_tool_mutation(
        tool_name="loop.relationship_dismiss",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: relationship_review.dismiss_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=relationship_type,
            conn=conn,
        ),
    )


def register_loop_relationship_tools(mcp: "FastMCP") -> None:
    """Register loop relationship-review tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="loop.relationship_review")(with_db_init(loop_relationship_review))
    mcp.tool(name="loop.relationship_queue")(with_db_init(loop_relationship_queue))
    mcp.tool(name="loop.relationship_confirm")(with_db_init(loop_relationship_confirm))
    mcp.tool(name="loop.relationship_dismiss")(with_db_init(loop_relationship_dismiss))
