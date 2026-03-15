"""MCP tools for AI-native planning sessions.

Purpose:
    Expose durable checkpointed planning workflows to MCP clients through thin
    tool wrappers.

Responsibilities:
    - Register MCP tools for planning session CRUD
    - Register MCP tools for planning session refresh, movement, and execution
    - Reuse shared MCP idempotency and error-handling helpers around
      `loops/planning_workflows.py`

Non-scope:
    - Planning workflow business logic
    - MCP server assembly
    - Domain validation beyond translating MCP inputs into shared contracts
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..loops import planning_workflows
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def plan_session_create(
    name: str,
    prompt: str,
    query: str | None = None,
    loop_limit: int = 10,
    include_memory_context: bool = True,
    include_rag_context: bool = False,
    rag_k: int = 5,
    rag_scope: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved planning session snapshot."""
    payload = {
        "name": name,
        "prompt": prompt,
        "query": query,
        "loop_limit": loop_limit,
        "include_memory_context": include_memory_context,
        "include_rag_context": include_rag_context,
        "rag_k": rag_k,
        "rag_scope": rag_scope,
    }
    return run_idempotent_tool_mutation(
        tool_name="plan.session.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: planning_workflows.create_planning_session(
            name=name,
            prompt=prompt,
            query=query,
            loop_limit=loop_limit,
            include_memory_context=include_memory_context,
            include_rag_context=include_rag_context,
            rag_k=rag_k,
            rag_scope=rag_scope,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def plan_session_list() -> list[dict[str, Any]]:
    """List saved planning sessions."""
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return planning_workflows.list_planning_sessions(conn=conn)


@with_mcp_error_handling
def plan_session_get(session_id: int) -> dict[str, Any]:
    """Get one planning session snapshot."""
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return planning_workflows.get_planning_session(session_id=session_id, conn=conn)


@with_mcp_error_handling
def plan_session_move(
    session_id: int,
    direction: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Move a planning session checkpoint cursor."""
    payload = {"session_id": session_id, "direction": direction}
    return run_idempotent_tool_mutation(
        tool_name="plan.session.move",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: planning_workflows.move_planning_session(
            session_id=session_id,
            direction=direction,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def plan_session_refresh(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Refresh one planning session against current grounded context."""
    payload = {"session_id": session_id}
    return run_idempotent_tool_mutation(
        tool_name="plan.session.refresh",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: planning_workflows.refresh_planning_session(
            session_id=session_id,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def plan_session_execute(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Execute the current checkpoint in a planning session."""
    payload = {"session_id": session_id}
    return run_idempotent_tool_mutation(
        tool_name="plan.session.execute",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: planning_workflows.execute_planning_session_checkpoint(
            session_id=session_id,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def plan_session_delete(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one planning session."""
    payload = {"session_id": session_id}
    return run_idempotent_tool_mutation(
        tool_name="plan.session.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: planning_workflows.delete_planning_session(
            session_id=session_id,
            conn=conn,
        ),
    )


def register_planning_tools(mcp: "FastMCP") -> None:
    """Register planning workflow MCP tools."""
    from ._runtime import with_db_init

    mcp.tool(name="plan.session.create")(with_db_init(plan_session_create))
    mcp.tool(name="plan.session.list")(with_db_init(plan_session_list))
    mcp.tool(name="plan.session.get")(with_db_init(plan_session_get))
    mcp.tool(name="plan.session.move")(with_db_init(plan_session_move))
    mcp.tool(name="plan.session.refresh")(with_db_init(plan_session_refresh))
    mcp.tool(name="plan.session.execute")(with_db_init(plan_session_execute))
    mcp.tool(name="plan.session.delete")(with_db_init(plan_session_delete))
