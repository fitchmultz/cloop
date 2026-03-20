"""MCP tools for AI-native planning sessions.

Purpose:
    Expose durable checkpointed planning workflows to MCP clients through thin
    tool wrappers.

Responsibilities:
    - Register MCP tools for planning session CRUD
    - Register MCP tools for planning session refresh, movement, execution, and rollback
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
    """Create a durable checkpointed planning session.

    Use this when you want pi to turn a grounded prompt plus current loop state
    into an explicit multi-step workflow. The returned snapshot includes the
    saved session metadata, generated checkpoints, grounded target loops, plan-
    freshness metadata, and the current checkpoint ready for operator review.

    Args:
        name: Human-facing session name. Must be unique among planning sessions.
        prompt: Planning request describing the outcome you want the plan to reach.
        query: Optional DSL query for which loops should ground the plan. When
            omitted, the planner falls back to the shared next-loop prioritization.
        loop_limit: Maximum number of target loops to include in grounded context.
        include_memory_context: Include durable memory entries in the grounding payload.
        include_rag_context: Include retrieved document context in the grounding payload.
        rag_k: Number of document chunks to retrieve when RAG grounding is enabled.
        rag_scope: Optional path/doc filter for RAG grounding (for example
            `launch-notes` or `doc:12`).
        request_id: Optional idempotency key. Reusing the same key with the same
            arguments replays the original snapshot instead of creating a new one.

    Returns:
        Dict matching the shared planning-session snapshot contract with:
        - `session`: durable planning session metadata
        - `plan_title` / `plan_summary`: generated plan overview
        - `checkpoints`: ordered checkpoint list with deterministic operations
        - `current_checkpoint`: the checkpoint currently ready for review/execution
        - `target_loops`, `context_summary`, `context_freshness`: grounded context
        - `execution_history`, `execution_analytics`: durable execution metadata

    Raises:
        ToolError: If validation fails, the grounded planner response is invalid,
            or the shared planning workflow raises a domain/runtime error.

    Examples:
        - Create a weekly reset plan for all open launch loops.
        - Create a query-scoped plan, inspect `current_checkpoint`, execute it,
          then continue into any saved review queue advertised by
          `execution.launch_surfaces`.
        - Regenerate the same request safely by reusing `request_id`.
    """
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
    """List saved planning sessions.

    Use this to discover resumable planning work before fetching a full snapshot.

    Args:
        None.

    Returns:
        List of planning-session metadata dicts ordered by most recently updated
        session first. Each item includes status, checkpoint counts, cursor, and
        grounding options.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return planning_workflows.list_planning_sessions(conn=conn)


@with_mcp_error_handling
def plan_session_get(session_id: int) -> dict[str, Any]:
    """Fetch one full planning-session snapshot.

    Use this after listing sessions or after executing/refreshing elsewhere when
    you need the latest checkpoints, grounding snapshot, and execution history.

    Args:
        session_id: Planning session ID returned by `plan.session.create` or
            `plan.session.list`.

    Returns:
        Dict matching the shared planning-session snapshot contract, including
        the current checkpoint and all prior execution-history entries. Each
        execution-history entry preserves `summary`, `follow_up_resources`,
        `launch_surfaces`, and `rollback_cues`, so MCP clients can resume from
        a previously created saved review session without bespoke bookkeeping.

    Raises:
        ToolError: If the planning session does not exist.
    """
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
    """Move the checkpoint cursor inside a planning session.

    Use this to step to the next or previous checkpoint without changing the
    saved plan itself.

    Args:
        session_id: Planning session ID.
        direction: Cursor movement direction. Valid values are `next` and
            `previous`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Updated planning-session snapshot with the new `current_checkpoint`
        selected.

    Raises:
        ToolError: If the session is missing or the requested movement would go
            beyond the available checkpoints.

    Examples:
        - Move from checkpoint 1 to checkpoint 2 before execution.
        - Move backward after reviewing later checkpoints and deciding to resume
          an earlier deterministic step.
    """
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
    """Regenerate a saved plan against the latest grounded context.

    Refresh preserves the durable session identity but replaces the generated
    workflow, resets checkpoint execution history, and captures a fresh grounded
    loop/memory/RAG snapshot.

    Args:
        session_id: Planning session ID.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Fresh planning-session snapshot with new checkpoints, cleared execution
        history, and an updated planning context summary.

    Raises:
        ToolError: If the session is missing or the planner cannot produce a
            valid structured workflow.

    Examples:
        - Refresh after major loop edits changed the work mix.
        - Refresh after completing a plan outside the session and wanting a new
          checkpoint sequence.
    """
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
    """Execute the current deterministic checkpoint.

    This runs every operation in the current checkpoint through the shared
    planning workflow contract, records durable execution history, advances the
    checkpoint cursor when appropriate, and returns the canonical operator
    handoff payload for what changed and what should happen next.

    Args:
        session_id: Planning session ID.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with:
        - `execution.summary`: aggregate touched-loop and created-resource counts/IDs
        - `execution.follow_up_resources`: structured created/updated review sessions,
          saved views, and templates emitted by this checkpoint
        - `execution.launch_surfaces`: direct handoff affordances for next operator
          surfaces. When a saved review session becomes the next queue, each launch
          surface includes the HTTP session path, the exact MCP follow-up tool +
          args, and web-launch metadata.
        - `execution.rollback_cues`: per-operation undo/rollback hints so clients
          can surface reversible vs best-effort changes clearly
        - `snapshot`: updated planning-session snapshot after execution

    Raises:
        ToolError: If the session is missing, the checkpoint was already
            executed, or one of the shared deterministic operations fails.

    Examples:
        - Execute a checkpoint, then immediately continue into the next saved
          review queue:
          `launch = result["execution"]["launch_surfaces"][0]`
          `review = call_tool(launch["mcp"]["tool"], **launch["mcp"]["args"])`
        - Execute a checkpoint that creates a saved view/template and show those
          resources from `execution.follow_up_resources` without re-deriving them.
        - If `execution.rollback_cues.rollback_supported_operation_count > 0`,
          surface those cues before automatically moving on to later checkpoints.
    """
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
def plan_session_rollback(
    session_id: int,
    run_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Roll back the latest active planning execution for a session.

    Use this when a recently executed checkpoint produced a reversible outcome
    and you want to run the shared rollback contract instead of manually
    reversing each downstream change.

    Args:
        session_id: Planning session ID.
        run_id: Execution run ID returned by `plan.session.execute` or stored in
            `execution_history[*].run_id`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with:
        - `rollback`: attempted/failed action counts plus explicit failure detail
        - `snapshot`: updated planning-session snapshot after rollback

    Raises:
        ToolError: If the rollback handle is stale, the run does not exist, or
            the target execution has no rollback actions.
    """
    payload = {"session_id": session_id, "run_id": run_id}
    return run_idempotent_tool_mutation(
        tool_name="plan.session.rollback",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: planning_workflows.rollback_planning_session_run(
            session_id=session_id,
            run_id=run_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def plan_session_delete(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete a saved planning session.

    Args:
        session_id: Planning session ID.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict containing `deleted=true` plus the removed `session_id`.

    Raises:
        ToolError: If the planning session does not exist.
    """
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
    mcp.tool(name="plan.session.rollback")(with_db_init(plan_session_rollback))
    mcp.tool(name="plan.session.delete")(with_db_init(plan_session_delete))
