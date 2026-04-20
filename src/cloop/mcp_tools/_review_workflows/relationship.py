"""Relationship review MCP tools.

Purpose:
    Expose saved relationship-review action and session workflows to MCP
    clients through thin tool wrappers.

Responsibilities:
    - Register relationship-review action CRUD MCP tools
    - Register relationship-review session CRUD, movement, apply-action, and
      exact-handle undo MCP tools
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
from ...schemas._loops.continuity import ContinuityRelationshipDecisionUndoHandle
from .._mutation import run_idempotent_tool_mutation
from .._runtime import with_mcp_error_handling
from ._mcp_common import (
    read_review_workflow,
    register_review_workflow_mcp_tools,
    require_clear_current_loop_xor,
)

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
    return read_review_workflow(
        lambda conn, _settings: review_workflows.list_relationship_review_actions(conn=conn),
    )


@with_mcp_error_handling
def review_relationship_action_get(action_preset_id: int) -> dict[str, Any]:
    """Get one saved relationship-review action."""
    return read_review_workflow(
        lambda conn, _settings: review_workflows.get_relationship_review_action(
            action_preset_id=action_preset_id,
            conn=conn,
        ),
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
    return read_review_workflow(
        lambda conn, _settings: review_workflows.list_relationship_review_sessions(conn=conn),
    )


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
    return read_review_workflow(
        lambda conn, settings: review_workflows.get_relationship_review_session(
            session_id=session_id,
            conn=conn,
            settings=settings,
        ),
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
def review_relationship_session_refresh(
    session_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Refresh one relationship-review session from live queue state.

    Args:
        session_id: Saved relationship-review session ID.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Refreshed relationship-review session snapshot with the same durable session
        identity and the best preserved cursor available after queue regeneration.

    Raises:
        ToolError: If the session is missing.
    """
    payload = {"session_id": session_id}
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_session.refresh",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.refresh_relationship_review_session(
            session_id=session_id,
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
    require_clear_current_loop_xor(
        clear_current_loop=clear_current_loop,
        current_loop_id=current_loop_id,
    )
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
        - `follow_through`: backend-authored receipt, rerun, and undo metadata

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


@with_mcp_error_handling
def review_relationship_session_undo(
    undo: dict[str, Any],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Undo one exact saved relationship decision.

    Args:
        undo: Exact relationship undo handle returned in
            `follow_through.undo_action.undo`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with:
        - `result`: normalized relationship undo payload
        - `snapshot`: refreshed relationship-review session after the undo
        - `follow_through`: backend-authored receipt after restoration

    Raises:
        ToolError: If the undo handle is invalid, stale, or targets missing
            saved review state.
    """
    validated = ContinuityRelationshipDecisionUndoHandle.model_validate(undo)
    payload = {"undo": validated.model_dump(mode="python")}
    return run_idempotent_tool_mutation(
        tool_name="review.relationship_session.undo",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: review_workflows.undo_relationship_review_session_action(
            session_id=validated.session_id,
            loop_id=validated.loop_id,
            candidate_loop_id=validated.candidate_loop_id,
            expected_pair_state=validated.expected_pair_state.model_dump(mode="python"),
            restore_pair_state=validated.restore_pair_state.model_dump(mode="python"),
            conn=conn,
            settings=settings,
        ),
    )


def register_relationship_review_workflow_tools(mcp: "FastMCP") -> None:
    """Register relationship review workflow MCP tools."""
    register_review_workflow_mcp_tools(
        mcp,
        (
            ("review.relationship_action.create", review_relationship_action_create),
            ("review.relationship_action.list", review_relationship_action_list),
            ("review.relationship_action.get", review_relationship_action_get),
            ("review.relationship_action.update", review_relationship_action_update),
            ("review.relationship_action.delete", review_relationship_action_delete),
            ("review.relationship_session.create", review_relationship_session_create),
            ("review.relationship_session.list", review_relationship_session_list),
            ("review.relationship_session.get", review_relationship_session_get),
            ("review.relationship_session.move", review_relationship_session_move),
            ("review.relationship_session.refresh", review_relationship_session_refresh),
            ("review.relationship_session.update", review_relationship_session_update),
            ("review.relationship_session.delete", review_relationship_session_delete),
            ("review.relationship_session.apply_action", review_relationship_session_apply_action),
            ("review.relationship_session.undo", review_relationship_session_undo),
        ),
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
    "review_relationship_session_refresh",
    "review_relationship_session_update",
    "review_relationship_session_delete",
    "review_relationship_session_apply_action",
    "review_relationship_session_undo",
    "register_relationship_review_workflow_tools",
]
