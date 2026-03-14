"""Suggestion and clarification MCP tools.

Purpose:
    Expose enrichment follow-up workflows to MCP clients through narrow,
    deterministic tools that reuse the shared review service.

Responsibilities:
    - List and inspect suggestions with linked clarification rows
    - Apply or reject suggestions idempotently
    - List clarifications for a loop
    - Submit one or many clarification answers idempotently

Non-scope:
    - Triggering enrichment generation itself (see loop.enrich)
    - Core loop lifecycle mutations (see loop_core.py / loop_read.py)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..loops import enrichment_review
from ..schemas.loops import ClarificationSubmitRequest
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def suggestion_list(
    loop_id: int | None = None,
    pending_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List enrichment suggestions with linked clarification rows.

    Args:
        loop_id: Optional loop filter.
        pending_only: If true, only include unresolved suggestions.
        limit: Maximum number of suggestions to return.

    Returns:
        Dict with `suggestions` and `count`.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        suggestions = enrichment_review.list_loop_suggestions(
            loop_id=loop_id,
            pending_only=pending_only,
            limit=limit,
            conn=conn,
        )
    return {"suggestions": suggestions, "count": len(suggestions)}


@with_mcp_error_handling
def suggestion_get(suggestion_id: int) -> dict[str, Any]:
    """Get one suggestion with linked clarification rows.

    Args:
        suggestion_id: Suggestion identifier.

    Returns:
        Suggestion payload including `parsed` and `clarifications`.

    Raises:
        ToolError: If the suggestion does not exist.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return enrichment_review.get_loop_suggestion(suggestion_id=suggestion_id, conn=conn)


@with_mcp_error_handling
def suggestion_apply(
    suggestion_id: int,
    fields: list[str] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Apply one suggestion to its loop.

    Args:
        suggestion_id: Suggestion identifier.
        fields: Optional subset of suggestion fields to apply.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with updated `loop`, `suggestion_id`, `applied_fields`, and `resolution`.

    Raises:
        ToolError: If the suggestion is missing or already resolved.
    """
    payload = {"suggestion_id": suggestion_id, "fields": fields}
    return run_idempotent_tool_mutation(
        tool_name="suggestion.apply",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: enrichment_review.apply_suggestion(
            suggestion_id=suggestion_id,
            fields=fields,
            conn=conn,
            settings=settings,
        ),
    )


@with_mcp_error_handling
def suggestion_reject(
    suggestion_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Reject one suggestion without applying fields.

    Args:
        suggestion_id: Suggestion identifier.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with `suggestion_id` and `resolution`.

    Raises:
        ToolError: If the suggestion is missing or already resolved.
    """
    payload = {"suggestion_id": suggestion_id}
    return run_idempotent_tool_mutation(
        tool_name="suggestion.reject",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: enrichment_review.reject_suggestion(
            suggestion_id=suggestion_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def clarification_list(loop_id: int) -> dict[str, Any]:
    """List clarification rows for one loop.

    Args:
        loop_id: Loop identifier.

    Returns:
        Dict with `clarifications` and `count`.

    Raises:
        ToolError: If the loop does not exist.
    """
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        clarifications = enrichment_review.list_loop_clarifications(loop_id=loop_id, conn=conn)
    return {"clarifications": clarifications, "count": len(clarifications)}


def _answer_inputs_from_payload(
    answers: Sequence[dict[str, Any]],
) -> list[enrichment_review.ClarificationAnswerInput]:
    inputs: list[enrichment_review.ClarificationAnswerInput] = []
    for answer in answers:
        parsed = ClarificationSubmitRequest.model_validate(answer)
        inputs.append(
            enrichment_review.ClarificationAnswerInput(
                clarification_id=parsed.clarification_id,
                answer=parsed.answer,
            )
        )
    return inputs


@with_mcp_error_handling
def clarification_answer(
    loop_id: int,
    clarification_id: int,
    answer: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Answer one clarification for a loop.

    Args:
        loop_id: Loop identifier.
        clarification_id: Clarification identifier.
        answer: Answer text.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with `loop_id`, `answered_count`, `clarifications`,
        `superseded_suggestion_ids`, and `message`.

    Raises:
        ToolError: If the loop or clarification is missing, or validation fails.
    """
    payload = {
        "loop_id": loop_id,
        "answers": [{"clarification_id": clarification_id, "answer": answer}],
    }
    return run_idempotent_tool_mutation(
        tool_name="clarification.answer",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: enrichment_review.submit_clarification_answers(
            loop_id=loop_id,
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=clarification_id,
                    answer=answer,
                )
            ],
            conn=conn,
        ).to_payload(),
    )


@with_mcp_error_handling
def clarification_answer_many(
    loop_id: int,
    answers: list[dict[str, Any]],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Answer multiple clarifications for one loop.

    Args:
        loop_id: Loop identifier.
        answers: List of `{"clarification_id": int, "answer": str}` objects.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with `loop_id`, `answered_count`, `clarifications`,
        `superseded_suggestion_ids`, and `message`.

    Raises:
        ToolError: If any clarification is missing or validation fails.
    """
    payload = {"loop_id": loop_id, "answers": answers}
    return run_idempotent_tool_mutation(
        tool_name="clarification.answer_many",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: enrichment_review.submit_clarification_answers(
            loop_id=loop_id,
            answers=_answer_inputs_from_payload(answers),
            conn=conn,
        ).to_payload(),
    )


def register_suggestion_tools(mcp: "FastMCP") -> None:
    """Register suggestion and clarification review tools."""
    from ._runtime import with_db_init

    mcp.tool(name="suggestion.list")(with_db_init(suggestion_list))
    mcp.tool(name="suggestion.get")(with_db_init(suggestion_get))
    mcp.tool(name="suggestion.apply")(with_db_init(suggestion_apply))
    mcp.tool(name="suggestion.reject")(with_db_init(suggestion_reject))
    mcp.tool(name="clarification.list")(with_db_init(clarification_list))
    mcp.tool(name="clarification.answer")(with_db_init(clarification_answer))
    mcp.tool(name="clarification.answer_many")(with_db_init(clarification_answer_many))
