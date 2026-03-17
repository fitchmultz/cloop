"""Enrichment review MCP tools.

Purpose:
    Expose saved enrichment-review action and session workflows to MCP
    clients through thin tool wrappers.

Responsibilities:
    - Register enrichment-review action CRUD MCP tools
    - Register enrichment-review session CRUD, movement, apply-action, and clarification MCP tools
    - Reuse shared MCP mutation and error-handling helpers

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Enrichment-review MCP tool wrappers only
    - No suggestion or clarification business logic

Usage:
    Imported by `cloop.mcp_tools.review_workflows`.

Invariants/Assumptions:
    - Tool names remain under `review.enrichment_*`
    - Wrappers delegate to the shared review workflow orchestration module
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ...loops import enrichment_review, review_workflows
from .._mutation import run_idempotent_tool_mutation
from .._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def review_enrichment_action_create(
    name: str,
    action_type: str,
    fields: Sequence[str] | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved enrichment-review action preset."""
    payload = {
        "name": name,
        "action_type": action_type,
        "fields": list(fields) if fields is not None else None,
        "description": description,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_action.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.create_enrichment_review_action(
            name=name,
            action_type=action_type,
            fields=fields,
            description=description,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_action_list() -> list[dict[str, Any]]:
    """List saved enrichment-review actions."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_enrichment_review_actions(conn=conn)


@with_mcp_error_handling
def review_enrichment_action_get(action_preset_id: int) -> dict[str, Any]:
    """Get one saved enrichment-review action."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.get_enrichment_review_action(
            action_preset_id=action_preset_id,
            conn=conn,
        )


@with_mcp_error_handling
def review_enrichment_action_update(
    action_preset_id: int,
    name: str | None = None,
    action_type: str | None = None,
    fields: Sequence[str] | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one saved enrichment-review action."""
    payload = {
        "action_preset_id": action_preset_id,
        "name": name,
        "action_type": action_type,
        "fields": list(fields) if fields is not None else None,
        "description": description,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_action.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.update_enrichment_review_action(
            action_preset_id=action_preset_id,
            name=name,
            action_type=action_type,
            fields=fields,
            description=description,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_action_delete(
    action_preset_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one saved enrichment-review action."""
    payload = {"action_preset_id": action_preset_id}
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_action.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.delete_enrichment_review_action(
            action_preset_id=action_preset_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_session_create(
    name: str,
    query: str,
    pending_kind: str = "all",
    suggestion_limit: int = 3,
    clarification_limit: int = 3,
    item_limit: int = 25,
    current_loop_id: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable enrichment-review session.

    Use this to persist a filtered suggestion/clarification queue so the agent
    can work through enrichment follow-up without reconstructing state.

    Args:
        name: Human-facing session name. Must be unique among enrichment sessions.
        query: DSL query describing which loops should populate the session.
        pending_kind: Follow-up type to include (`all`, `suggestions`, `clarifications`).
        suggestion_limit: Maximum suggestions to retain per loop in the snapshot.
        clarification_limit: Maximum clarifications to retain per loop.
        item_limit: Maximum loops to include in the saved session.
        current_loop_id: Optional loop that should become the initial cursor.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared enrichment-review session snapshot contract with
        durable `session`, saved `items`, `current_item`, and cursor metadata.

    Raises:
        ToolError: If validation fails, the named session already exists, or the
            shared review workflow raises a domain/runtime error.

    Examples:
        - Save a clarification-only queue for `status:open project:launch`.
        - Save a mixed suggestions+clarifications queue before a review pass.
    """
    payload = {
        "name": name,
        "query": query,
        "pending_kind": pending_kind,
        "suggestion_limit": suggestion_limit,
        "clarification_limit": clarification_limit,
        "item_limit": item_limit,
        "current_loop_id": current_loop_id,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_session.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.create_enrichment_review_session(
            name=name,
            query=query,
            pending_kind=pending_kind,
            suggestion_limit=suggestion_limit,
            clarification_limit=clarification_limit,
            item_limit=item_limit,
            current_loop_id=current_loop_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_session_list() -> list[dict[str, Any]]:
    """List saved enrichment-review sessions."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_enrichment_review_sessions(conn=conn)


@with_mcp_error_handling
def review_enrichment_session_get(session_id: int) -> dict[str, Any]:
    """Fetch one full enrichment-review session snapshot.

    Args:
        session_id: Saved enrichment-review session ID.

    Returns:
        Dict matching the shared enrichment-review snapshot contract with the
        durable session metadata, full queued items, pending suggestions,
        clarifications, and the current cursor position.

    Raises:
        ToolError: If the saved session does not exist.
    """
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.get_enrichment_review_session(session_id=session_id, conn=conn)


@with_mcp_error_handling
def review_enrichment_session_move(
    session_id: int,
    direction: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Move the cursor inside an enrichment-review session.

    Args:
        session_id: Saved enrichment-review session ID.
        direction: Cursor movement direction. Valid values are `next` and `previous`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Updated enrichment-review session snapshot with the new current loop.

    Raises:
        ToolError: If the session is missing or no next/previous item exists.
    """
    payload = {"session_id": session_id, "direction": direction}
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_session.move",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.move_enrichment_review_session(
            session_id=session_id,
            direction=direction,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_session_update(
    session_id: int,
    name: str | None = None,
    query: str | None = None,
    pending_kind: str | None = None,
    suggestion_limit: int | None = None,
    clarification_limit: int | None = None,
    item_limit: int | None = None,
    current_loop_id: int | None = None,
    clear_current_loop: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one enrichment-review session."""
    if clear_current_loop and current_loop_id is not None:
        raise ValueError("provide current_loop_id or clear_current_loop, not both")
    payload = {
        "session_id": session_id,
        "name": name,
        "query": query,
        "pending_kind": pending_kind,
        "suggestion_limit": suggestion_limit,
        "clarification_limit": clarification_limit,
        "item_limit": item_limit,
        "current_loop_id": current_loop_id,
        "clear_current_loop": clear_current_loop,
    }
    resolved_current_loop_id = (
        None
        if clear_current_loop
        else review_workflows._UNSET
        if current_loop_id is None
        else current_loop_id
    )
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_session.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.update_enrichment_review_session(
            session_id=session_id,
            name=name,
            query=query,
            pending_kind=pending_kind,
            suggestion_limit=suggestion_limit,
            clarification_limit=clarification_limit,
            item_limit=item_limit,
            current_loop_id=resolved_current_loop_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_session_delete(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one enrichment-review session."""
    payload = {"session_id": session_id}
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_session.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.delete_enrichment_review_session(
            session_id=session_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_enrichment_session_apply_action(
    session_id: int,
    suggestion_id: int,
    action_preset_id: int | None = None,
    action_type: str | None = None,
    fields: Sequence[str] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Apply or reject a suggestion inside a saved enrichment session.

    Args:
        session_id: Saved enrichment-review session ID.
        suggestion_id: Suggestion to resolve inside the saved session.
        action_preset_id: Optional saved action preset to reuse.
        action_type: Inline action override (`apply` or `reject`) when not using
            a preset.
        fields: Optional field subset when applying a suggestion inline.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with:
        - `result`: normalized suggestion resolution payload
        - `snapshot`: refreshed enrichment-review session after the action

    Raises:
        ToolError: If the suggestion is invalid for the session, the requested
            action is incompatible, or the underlying resolution fails.
    """
    payload = {
        "session_id": session_id,
        "suggestion_id": suggestion_id,
        "action_preset_id": action_preset_id,
        "action_type": action_type,
        "fields": list(fields) if fields is not None else None,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_session.apply_action",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.execute_enrichment_review_session_action(
            session_id=session_id,
            suggestion_id=suggestion_id,
            action_preset_id=action_preset_id,
            action_type=action_type,
            fields=fields,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def review_enrichment_session_answer_clarifications(
    session_id: int,
    loop_id: int,
    answers: list[dict[str, Any]],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Answer clarification prompts and rerun enrichment in one session step.

    This is the session-preserving refinement path for enrichment follow-up. It
    records answers against existing clarification rows, reruns the shared
    enrichment orchestration, and returns the refreshed session snapshot.

    Args:
        session_id: Saved enrichment-review session ID.
        loop_id: Loop whose clarification rows are being answered.
        answers: List of `{clarification_id, answer}` dicts.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with:
        - `result`: clarification-answer + rerun-enrichment payload
        - `snapshot`: refreshed enrichment-review session after refinement

    Raises:
        ToolError: If the clarification IDs do not belong to the loop/session or
            the shared refinement flow fails.

    Examples:
        - Answer two clarifications, rerun enrichment, then inspect the updated
          pending suggestions in the returned `snapshot`.
    """
    payload = {"session_id": session_id, "loop_id": loop_id, "answers": answers}

    def _execute(conn: Any, settings: Any) -> dict[str, Any]:
        answer_inputs = [
            enrichment_review.ClarificationAnswerInput(
                clarification_id=int(answer["clarification_id"]),
                answer=str(answer["answer"]),
            )
            for answer in answers
        ]
        return review_workflows.answer_enrichment_review_session_clarifications(
            session_id=session_id,
            loop_id=loop_id,
            answers=answer_inputs,
            conn=conn,
            settings=settings,
        )

    return run_idempotent_tool_mutation(
        tool_name="review.enrichment_session.answer_clarifications",
        request_id=request_id,
        payload=payload,
        execute=_execute,
    )


def register_enrichment_review_workflow_tools(mcp: "FastMCP") -> None:
    """Register enrichment review workflow MCP tools."""
    from .._runtime import with_db_init

    mcp.tool(name="review.enrichment_action.create")(with_db_init(review_enrichment_action_create))
    mcp.tool(name="review.enrichment_action.list")(with_db_init(review_enrichment_action_list))
    mcp.tool(name="review.enrichment_action.get")(with_db_init(review_enrichment_action_get))
    mcp.tool(name="review.enrichment_action.update")(with_db_init(review_enrichment_action_update))
    mcp.tool(name="review.enrichment_action.delete")(with_db_init(review_enrichment_action_delete))
    mcp.tool(name="review.enrichment_session.create")(
        with_db_init(review_enrichment_session_create)
    )
    mcp.tool(name="review.enrichment_session.list")(with_db_init(review_enrichment_session_list))
    mcp.tool(name="review.enrichment_session.get")(with_db_init(review_enrichment_session_get))
    mcp.tool(name="review.enrichment_session.move")(with_db_init(review_enrichment_session_move))
    mcp.tool(name="review.enrichment_session.update")(
        with_db_init(review_enrichment_session_update)
    )
    mcp.tool(name="review.enrichment_session.delete")(
        with_db_init(review_enrichment_session_delete)
    )
    mcp.tool(name="review.enrichment_session.apply_action")(
        with_db_init(review_enrichment_session_apply_action)
    )
    mcp.tool(name="review.enrichment_session.answer_clarifications")(
        with_db_init(review_enrichment_session_answer_clarifications)
    )


__all__ = [
    "review_enrichment_action_create",
    "review_enrichment_action_list",
    "review_enrichment_action_get",
    "review_enrichment_action_update",
    "review_enrichment_action_delete",
    "review_enrichment_session_create",
    "review_enrichment_session_list",
    "review_enrichment_session_get",
    "review_enrichment_session_move",
    "review_enrichment_session_update",
    "review_enrichment_session_delete",
    "review_enrichment_session_apply_action",
    "review_enrichment_session_answer_clarifications",
    "register_enrichment_review_workflow_tools",
]
