"""Shared idempotency helpers for MCP loop tools.

Purpose:
    Centralize MCP request replay handling so loop tool modules share one
    consistent idempotency implementation.

Responsibilities:
    - Prepare MCP idempotency state within an existing database connection
    - Expose replay bodies for previously completed tool calls
    - Finalize stored responses after successful tool execution

Non-scope:
    - Does not open database connections
    - Does not validate business payload contents
    - Does not register MCP tools
"""

from __future__ import annotations

from typing import Any, Mapping

from ..idempotency_flow import (
    finalize_idempotent_response,
    prepare_mcp_idempotency,
    replay_mcp_response,
)


def prepare_tool_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: Mapping[str, Any],
    settings: Any,
    conn: Any,
) -> Any | None:
    """Prepare idempotency state for an MCP tool call."""
    return prepare_mcp_idempotency(
        tool_name=tool_name,
        request_id=request_id,
        payload=payload,
        settings=settings,
        conn=conn,
    )


def replay_tool_response(state: Any) -> Any | None:
    """Return the replay body for a previously completed tool call."""
    return replay_mcp_response(state)


def finalize_tool_idempotency(
    *,
    state: Any,
    response: Any,
    conn: Any,
) -> None:
    """Persist a successful MCP response for future replays."""
    finalize_idempotent_response(
        state=state,
        response_status=200,
        response_body=response,
        conn=conn,
    )
