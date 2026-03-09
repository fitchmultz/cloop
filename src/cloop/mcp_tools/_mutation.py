"""Shared execution helpers for idempotent MCP mutations.

Purpose:
    Remove repeated connection and idempotency boilerplate from MCP mutation
    tools while preserving consistent replay behavior.

Responsibilities:
    - Open the core database connection for mutation tools
    - Prepare, replay, and finalize idempotent MCP responses
    - Pass shared settings into mutation callbacks

Non-scope:
    - Does not register MCP tools
    - Does not perform domain validation for individual tools
    - Does not handle read-only tool execution
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .. import db
from ..settings import get_settings
from ._idempotency import (
    finalize_tool_idempotency,
    prepare_tool_idempotency,
    replay_tool_response,
)


def run_idempotent_tool_mutation(
    *,
    tool_name: str,
    request_id: str | None,
    payload: Mapping[str, Any],
    execute: Callable[..., Any],
) -> Any:
    """Run a mutation tool with shared connection and idempotency handling."""
    settings = get_settings()
    with db.core_connection(settings) as conn:
        idempotency = prepare_tool_idempotency(
            tool_name=tool_name,
            request_id=request_id,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_tool_response(idempotency)
        if replay is not None:
            return replay

        result = execute(conn=conn, settings=settings)
        finalize_tool_idempotency(state=idempotency, response=result, conn=conn)
        return result
