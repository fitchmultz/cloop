"""Relationship review MCP tools.

Purpose:
    Expose saved relationship-review action and session workflows to MCP
    clients through thin tool wrappers.

Responsibilities:
    - Register relationship-review action CRUD MCP tools
    - Register relationship-review session CRUD, movement, and apply-action MCP tools
    - Reuse shared MCP mutation and error-handling helpers

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Relationship-review MCP tool wrappers only
    - No review workflow business logic

Usage:
    Imported by `cloop.mcp_tools.review_workflows`.

Invariants/Assumptions:
    - Tool names remain under `review.relationship_*`
    - Wrappers delegate to the shared review workflow orchestration module
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...loops import review_workflows
from .._mutation import run_idempotent_tool_mutation
from .._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def review_relationship_action_create(
    name: str,
    action_type: str,
    relationship_type: str = "suggested",
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved relationship-review action preset."""
    payload = {
        "name": name,
        "action_type": action_type,
        "relationship_type": relationship_type,
        "description": description,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_action.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.create_relationship_review_action(
            name=name,
            action_type=action_type,
            relationship_type=relationship_type,
            description=description,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_relationship_action_list() -> list[dict[str, Any]]:
    """List saved relationship-review actions."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_relationship_review_actions(conn=conn)


@with_mcp_error_handling
def review_relationship_action_get(action_preset_id: int) -> dict[str, Any]:
    """Get one saved relationship-review action."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.get_relationship_review_action(
            action_preset_id=action_preset_id,
            conn=conn,
        )


@with_mcp_error_handling
def review_relationship_action_update(
    action_preset_id: int,
    name: str | None = None,
    action_type: str | None = None,
    relationship_type: str | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one saved relationship-review action."""
    payload = {
        "action_preset_id": action_preset_id,
        "name": name,
        "action_type": action_type,
        "relationship_type": relationship_type,
        "description": description,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_action.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.update_relationship_review_action(
            action_preset_id=action_preset_id,
            name=name,
            action_type=action_type,
            relationship_type=relationship_type,
            description=description,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_relationship_action_delete(
    action_preset_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one saved relationship-review action."""
    payload = {"action_preset_id": action_preset_id}
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_action.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.delete_relationship_review_action(
            action_preset_id=action_preset_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_relationship_session_create(
    name: str,
    query: str,
    relationship_kind: str = "all",
    candidate_limit: int = 3,
    item_limit: int = 25,
    current_loop_id: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable relationship-review session.

    Use this to persist a filtered duplicate/related-loop review queue so an MCP
    client can pause and resume without rebuilding candidate state.

    Args:
        name: Human-facing session name. Must be unique among relationship sessions.
        query: DSL query describing which loops belong in the saved review queue.
        relationship_kind: Candidate type to queue (`all`, `duplicate`, `related`).
        candidate_limit: Maximum duplicate/related candidates to retain per loop.
        item_limit: Maximum loops to include in the saved session snapshot.
        current_loop_id: Optional loop that should become the initial cursor.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared relationship-review session snapshot contract,
        including the durable `session`, saved `items`, `current_item`, and
        `current_index` cursor metadata.

    Raises:
        ToolError: If validation fails, the named session already exists, or the
            shared review workflow raises a domain/runtime error.

    Examples:
        - Save a duplicate-only review queue for `project:launch status:open`.
        - Resume a previously identified hot loop first by providing
          `current_loop_id`.
    """
    payload = {
        "name": name,
        "query": query,
        "relationship_kind": relationship_kind,
        "candidate_limit": candidate_limit,
        "item_limit": item_limit,
        "current_loop_id": current_loop_id,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_session.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.create_relationship_review_session(
            name=name,
            query=query,
            relationship_kind=relationship_kind,
            candidate_limit=candidate_limit,
            item_limit=item_limit,
            current_loop_id=current_loop_id,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def review_relationship_session_list() -> list[dict[str, Any]]:
    """List saved relationship-review sessions."""
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_relationship_review_sessions(conn=conn)


@with_mcp_error_handling
def review_relationship_session_get(session_id: int) -> dict[str, Any]:
    """Fetch one full relationship-review session snapshot.

    Args:
        session_id: Saved relationship-review session ID.

    Returns:
        Dict matching the shared relationship-review snapshot contract with the
        durable session metadata, full queued items, and the currently selected
        loop plus duplicate/related candidates.

    Raises:
        ToolError: If the saved session does not exist.
    """
    from ... import db
    from ...settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.get_relationship_review_session(
            session_id=session_id,
            conn=conn,
            settings=settings,
        )


@with_mcp_error_handling
def review_relationship_session_move(
    session_id: int,
    direction: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Move the cursor inside a relationship-review session.

    Args:
        session_id: Saved relationship-review session ID.
        direction: Cursor movement direction. Valid values are `next` and `previous`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Updated relationship-review session snapshot with the new current loop.

    Raises:
        ToolError: If the session is missing or no next/previous item exists.
    """
    payload = {"session_id": session_id, "direction": direction}
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_session.move",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.move_relationship_review_session(
            session_id=session_id,
            direction=direction,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def review_relationship_session_update(
    session_id: int,
    name: str | None = None,
    query: str | None = None,
    relationship_kind: str | None = None,
    candidate_limit: int | None = None,
    item_limit: int | None = None,
    current_loop_id: int | None = None,
    clear_current_loop: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update one relationship-review session."""
    if clear_current_loop and current_loop_id is not None:
        raise ValueError("provide current_loop_id or clear_current_loop, not both")
    payload = {
        "session_id": session_id,
        "name": name,
        "query": query,
        "relationship_kind": relationship_kind,
        "candidate_limit": candidate_limit,
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
        tool_name="review.relationship_session.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.update_relationship_review_session(
            session_id=session_id,
            name=name,
            query=query,
            relationship_kind=relationship_kind,
            candidate_limit=candidate_limit,
            item_limit=item_limit,
            current_loop_id=resolved_current_loop_id,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def review_relationship_session_delete(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one relationship-review session."""
    payload = {"session_id": session_id}
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_session.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.delete_relationship_review_session(
            session_id=session_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def review_relationship_session_apply_action(
    session_id: int,
    loop_id: int,
    candidate_loop_id: int,
    candidate_relationship_type: str,
    action_preset_id: int | None = None,
    action_type: str | None = None,
    relationship_type: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Apply a duplicate/related decision inside a saved relationship session.

    Use this when the agent has inspected the current candidate and is ready to
    confirm or dismiss it while preserving the saved-session cursor.

    Args:
        session_id: Saved relationship-review session ID.
        loop_id: Primary loop under review.
        candidate_loop_id: Candidate loop being confirmed or dismissed.
        candidate_relationship_type: Candidate type as queued in the session.
        action_preset_id: Optional saved action preset to reuse.
        action_type: Inline action override (`confirm` or `dismiss`) when not
            using a preset.
        relationship_type: Optional explicit relationship outcome (`duplicate`
            or `related`) when not using a preset.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with:
        - `result`: normalized relationship decision payload
        - `snapshot`: refreshed relationship-review session after the action

    Raises:
        ToolError: If the candidate is invalid for the session, the action is
            incompatible, or the underlying relationship decision fails.
    """
    payload = {
        "session_id": session_id,
        "loop_id": loop_id,
        "candidate_loop_id": candidate_loop_id,
        "candidate_relationship_type": candidate_relationship_type,
        "action_preset_id": action_preset_id,
        "action_type": action_type,
        "relationship_type": relationship_type,
    }
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_session.apply_action",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.execute_relationship_review_session_action(
            session_id=session_id,
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            candidate_relationship_type=candidate_relationship_type,
            action_preset_id=action_preset_id,
            action_type=action_type,
            relationship_type=relationship_type,
            conn=conn,
            settings=settings,
        ),
    )


def register_relationship_review_workflow_tools(mcp: "FastMCP") -> None:
    """Register relationship review workflow MCP tools."""
    from .._runtime import with_db_init

    mcp.tool(name="review.relationship_action.create")(
        with_db_init(review_relationship_action_create)
    )
    mcp.tool(name="review.relationship_action.list")(with_db_init(review_relationship_action_list))
    mcp.tool(name="review.relationship_action.get")(with_db_init(review_relationship_action_get))
    mcp.tool(name="review.relationship_action.update")(
        with_db_init(review_relationship_action_update)
    )
    mcp.tool(name="review.relationship_action.delete")(
        with_db_init(review_relationship_action_delete)
    )
    mcp.tool(name="review.relationship_session.create")(
        with_db_init(review_relationship_session_create)
    )
    mcp.tool(name="review.relationship_session.list")(
        with_db_init(review_relationship_session_list)
    )
    mcp.tool(name="review.relationship_session.get")(with_db_init(review_relationship_session_get))
    mcp.tool(name="review.relationship_session.move")(
        with_db_init(review_relationship_session_move)
    )
    mcp.tool(name="review.relationship_session.update")(
        with_db_init(review_relationship_session_update)
    )
    mcp.tool(name="review.relationship_session.delete")(
        with_db_init(review_relationship_session_delete)
    )
    mcp.tool(name="review.relationship_session.apply_action")(
        with_db_init(review_relationship_session_apply_action)
    )


__all__ = [
    "review_relationship_action_create",
    "review_relationship_action_list",
    "review_relationship_action_get",
    "review_relationship_action_update",
    "review_relationship_action_delete",
    "review_relationship_session_create",
    "review_relationship_session_list",
    "review_relationship_session_get",
    "review_relationship_session_move",
    "review_relationship_session_update",
    "review_relationship_session_delete",
    "review_relationship_session_apply_action",
    "register_relationship_review_workflow_tools",
]
