"""Review workflow queued-action execution operations.

Purpose:
    Execute saved or inline relationship/enrichment review decisions while
    keeping durable session snapshots in sync.

Responsibilities:
    - Apply or dismiss queued relationship candidates inside a saved session
    - Apply or reject queued enrichment suggestions inside a saved session
    - Record clarification answers, rerun enrichment, and refresh the same session

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Session-bound review action execution only
    - No saved action/session CRUD outside refreshing snapshots after execution

Usage:
    Imported by CLI, HTTP, MCP, and the review workflow facade.

Invariants/Assumptions:
    - Executed candidates/suggestions must already belong to the saved session snapshot
    - Refreshed snapshots preserve prior cursor ordering when possible
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from ... import typingx
from .. import enrichment_orchestration, enrichment_review, relationship_review
from ..errors import ValidationError
from .shared import (
    _enrichment_action_payload,
    _relationship_action_payload,
    _require_enrichment_action_row,
    _require_enrichment_session_row,
    _require_relationship_action_row,
    _require_relationship_session_row,
    _validate_enrichment_action,
    _validate_relationship_action,
)
from .snapshots import (
    _build_enrichment_session_snapshot,
    _build_relationship_session_snapshot,
    _candidate_loop_ids,
)


@typingx.validate_io()
def execute_relationship_review_session_action(
    *,
    session_id: int,
    loop_id: int,
    candidate_loop_id: int,
    candidate_relationship_type: str,
    action_preset_id: int | None,
    action_type: str | None,
    relationship_type: str | None,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_relationship_session_row(session_id=session_id, conn=conn)
    before = _build_relationship_session_snapshot(
        session_row=session_row, conn=conn, settings=settings
    )
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    item = next((entry for entry in before["items"] if int(entry["loop"]["id"]) == loop_id), None)
    if item is None:
        raise ValidationError(
            "loop_id", f"loop {loop_id} is not present in review session {session_id}"
        )
    candidate = next(
        (
            entry
            for entry in [
                *item.get("duplicate_candidates", []),
                *item.get("related_candidates", []),
            ]
            if int(entry["id"]) == candidate_loop_id
        ),
        None,
    )
    if candidate is None:
        raise ValidationError(
            "candidate_loop_id",
            (
                f"candidate {candidate_loop_id} is not present "
                f"for loop {loop_id} in session {session_id}"
            ),
        )

    if action_preset_id is not None:
        preset = _relationship_action_payload(
            _require_relationship_action_row(action_preset_id=action_preset_id, conn=conn)
        )
        resolved_action_type = str(preset["action_type"])
        resolved_relationship_type = str(preset["relationship_type"])
    else:
        if action_type is None or relationship_type is None:
            raise ValidationError(
                "action",
                "provide action_preset_id or both action_type and relationship_type",
            )
        resolved_action_type, resolved_relationship_type = _validate_relationship_action(
            action_type=action_type,
            relationship_type=relationship_type,
        )

    actual_relationship_type = (
        candidate_relationship_type
        if resolved_relationship_type == "suggested"
        else resolved_relationship_type
    )
    if actual_relationship_type != str(candidate["relationship_type"]):
        raise ValidationError(
            "relationship_type",
            "resolved relationship_type does not match the queued candidate",
        )

    if resolved_action_type == "confirm":
        result = relationship_review.confirm_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=actual_relationship_type,
            conn=conn,
        )
    else:
        result = relationship_review.dismiss_relationship(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            relationship_type=actual_relationship_type,
            conn=conn,
        )

    after = _build_relationship_session_snapshot(
        session_row=_require_relationship_session_row(session_id=session_id, conn=conn),
        conn=conn,
        settings=settings,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    return {"result": result, "snapshot": after}


@typingx.validate_io()
def execute_enrichment_review_session_action(
    *,
    session_id: int,
    suggestion_id: int,
    action_preset_id: int | None,
    action_type: str | None,
    fields: Sequence[str] | None,
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_enrichment_session_row(session_id=session_id, conn=conn)
    before = _build_enrichment_session_snapshot(session_row=session_row, conn=conn)
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    suggestion_in_session = next(
        (
            suggestion
            for item in before["items"]
            for suggestion in item.get("pending_suggestions", [])
            if int(suggestion["id"]) == suggestion_id
        ),
        None,
    )
    if suggestion_in_session is None:
        raise ValidationError(
            "suggestion_id",
            f"suggestion {suggestion_id} is not present in review session {session_id}",
        )

    if action_preset_id is not None:
        preset = _enrichment_action_payload(
            _require_enrichment_action_row(action_preset_id=action_preset_id, conn=conn)
        )
        resolved_action_type = str(preset["action_type"])
        resolved_fields = preset.get("fields")
    else:
        if action_type is None:
            raise ValidationError("action", "provide action_preset_id or action_type")
        resolved_action_type, resolved_fields = _validate_enrichment_action(
            action_type=action_type,
            fields=fields,
        )

    if resolved_action_type == "apply":
        result = enrichment_review.apply_suggestion(
            suggestion_id=suggestion_id,
            fields=resolved_fields,
            conn=conn,
            settings=settings,
        )
    else:
        result = enrichment_review.reject_suggestion(suggestion_id=suggestion_id, conn=conn)

    after = _build_enrichment_session_snapshot(
        session_row=_require_enrichment_session_row(session_id=session_id, conn=conn),
        conn=conn,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    return {"result": result, "snapshot": after}


@typingx.validate_io()
def answer_enrichment_review_session_clarifications(
    *,
    session_id: int,
    loop_id: int,
    answers: Sequence[enrichment_review.ClarificationAnswerInput],
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_enrichment_session_row(session_id=session_id, conn=conn)
    before = _build_enrichment_session_snapshot(session_row=session_row, conn=conn)
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    item = next((entry for entry in before["items"] if int(entry["loop"]["id"]) == loop_id), None)
    if item is None:
        raise ValidationError(
            "loop_id", f"loop {loop_id} is not present in review session {session_id}"
        )
    allowed_clarification_ids = {
        int(clarification["id"]) for clarification in item.get("pending_clarifications", [])
    }
    for answer in answers:
        if int(answer.clarification_id) not in allowed_clarification_ids:
            raise ValidationError(
                "clarification_id",
                (
                    f"clarification {answer.clarification_id} is not present "
                    f"for loop {loop_id} in session {session_id}"
                ),
            )

    result = enrichment_orchestration.orchestrate_clarification_refinement(
        loop_id=loop_id,
        answers=answers,
        conn=conn,
        settings=settings,
    ).to_payload()
    after = _build_enrichment_session_snapshot(
        session_row=_require_enrichment_session_row(session_id=session_id, conn=conn),
        conn=conn,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    return {"result": result, "snapshot": after}


__all__ = [
    "execute_relationship_review_session_action",
    "execute_enrichment_review_session_action",
    "answer_enrichment_review_session_clarifications",
]
