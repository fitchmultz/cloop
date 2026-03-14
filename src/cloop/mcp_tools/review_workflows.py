"""MCP tools for saved review actions and review sessions.

Purpose:
    Expose saved relationship/enrichment review actions and session-preserving
    review workflows to MCP clients through thin tool wrappers.

Responsibilities:
    - Register MCP tools for saved review action CRUD
    - Register MCP tools for saved review session CRUD and session actions
    - Reuse shared MCP idempotency and error-handling helpers around
      `loops/review_workflows.py`

Non-scope:
    - Review workflow business logic
    - MCP server assembly
    - Domain validation beyond translating MCP inputs into shared contracts
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..loops import enrichment_review, review_workflows
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_relationship_review_actions(conn=conn)


@with_mcp_error_handling
def review_relationship_action_get(action_preset_id: int) -> dict[str, Any]:
    """Get one saved relationship-review action."""
    from .. import db
    from ..settings import get_settings

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
    """Create a relationship-review session snapshot."""
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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_relationship_review_sessions(conn=conn)


@with_mcp_error_handling
def review_relationship_session_get(session_id: int) -> dict[str, Any]:
    """Get a relationship-review session snapshot."""
    from .. import db
    from ..settings import get_settings

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
    """Move a relationship-review session cursor."""
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
    """Run a relationship-review action inside a session."""
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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_enrichment_review_actions(conn=conn)


@with_mcp_error_handling
def review_enrichment_action_get(action_preset_id: int) -> dict[str, Any]:
    """Get one saved enrichment-review action."""
    from .. import db
    from ..settings import get_settings

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
    """Create an enrichment-review session snapshot."""
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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.list_enrichment_review_sessions(conn=conn)


@with_mcp_error_handling
def review_enrichment_session_get(session_id: int) -> dict[str, Any]:
    """Get an enrichment-review session snapshot."""
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return review_workflows.get_enrichment_review_session(session_id=session_id, conn=conn)


@with_mcp_error_handling
def review_enrichment_session_move(
    session_id: int,
    direction: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Move an enrichment-review session cursor."""
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
    """Run an enrichment-review action inside a session."""
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
    """Answer clarifications for one loop in an enrichment session."""
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


def register_review_workflow_tools(mcp: "FastMCP") -> None:
    """Register review workflow MCP tools."""
    from ._runtime import with_db_init

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
