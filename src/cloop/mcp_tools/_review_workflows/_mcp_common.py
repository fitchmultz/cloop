"""Shared helpers for MCP review-workflow tool modules.

Purpose:
    Centralize repeated read-connection wiring and FastMCP registration for
    relationship and enrichment review tools.

Responsibilities:
    - Open core DB connections for read-only review workflow MCP tools
    - Register MCP tools with stable full names and `with_db_init`
    - Validate mutually exclusive session cursor update flags

Non-scope:
    - Idempotency execution (see `mcp_tools._mutation`)
    - Domain-specific undo or clarification orchestration
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

T = TypeVar("T")


def read_review_workflow(work: Callable[[Any, Any], T]) -> T:
    """Run a read callback with `get_settings` and a core DB connection."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return work(conn, settings)


def require_clear_current_loop_xor(
    *,
    clear_current_loop: bool,
    current_loop_id: int | None,
) -> None:
    """Reject invalid combinations of `clear_current_loop` and `current_loop_id`."""
    if clear_current_loop and current_loop_id is not None:
        raise ValueError("provide current_loop_id or clear_current_loop, not both")


def register_review_workflow_mcp_tools(
    mcp: "FastMCP",
    tools: Sequence[tuple[str, Callable[..., Any]]],
) -> None:
    """Register MCP tools using full stable names (e.g. ``review.relationship_action.create``)."""
    from .._runtime import with_db_init

    for tool_name, handler in tools:
        mcp.tool(name=tool_name)(with_db_init(handler))
