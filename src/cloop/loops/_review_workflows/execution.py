"""Review workflow queued-action execution operations.

Purpose:
    Execute saved or inline relationship/enrichment review decisions while
    keeping durable session snapshots in sync.

Responsibilities:
    - Apply or dismiss queued relationship candidates inside a saved session
    - Apply or reject queued enrichment suggestions inside a saved session
    - Record clarification answers, rerun enrichment, and refresh the same session
    - Emit backend-authored follow-through payloads for landed review outcomes
    - Provide exact-handle relationship undo when the pair state has not drifted

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Session-bound review action execution and exact-handle undo only
    - No saved action/session CRUD outside refreshing snapshots after execution

Usage:
    Imported by CLI, HTTP, MCP, and the review workflow facade.

Invariants/Assumptions:
    - Executed candidates/suggestions must already belong to the saved session snapshot
    - Refreshed snapshots preserve prior cursor ordering when possible
    - Relationship undo only succeeds when the current pair state still matches
      the post-decision state captured in the exact handle
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, cast

from ... import typingx
from .. import enrichment_orchestration, enrichment_review, relationship_review, repo, working_sets
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

ReviewFocus = str
RelationshipPairState = dict[str, dict[str, Any] | None]


def _loop_label(loop: Mapping[str, Any] | None, *, fallback: str) -> str:
    if loop is None:
        return fallback
    title = str(loop.get("title") or "").strip()
    if title:
        return title
    raw_text = str(loop.get("raw_text") or "").strip()
    if raw_text:
        return raw_text
    loop_id = loop.get("id")
    return f"Loop #{loop_id}" if isinstance(loop_id, int) else fallback


def _review_resume_location(
    *,
    review_focus: ReviewFocus,
    session_id: int,
    working_set_id: int | None,
) -> dict[str, Any]:
    location: dict[str, Any] = {
        "state": "decide",
        "review_focus": review_focus,
        "session_id": session_id,
    }
    if working_set_id is not None:
        location["working_set_id"] = working_set_id
    return location


def _review_workflow_thread(
    *,
    session: Mapping[str, Any],
    review_focus: ReviewFocus,
) -> dict[str, Any]:
    return {
        "id": f"review:{review_focus}:session:{int(session['id'])}",
        "kind": "review_session",
        "title": str(session["name"]),
        "summary": str(session.get("query") or "") or None,
        "parent_outcome_id": None,
    }


def _working_set_follow_through_payload(
    context: Mapping[str, Any],
) -> tuple[int | None, dict[str, Any] | None]:
    working_set_id = context.get("active_working_set_id")
    active_working_set = context.get("active_working_set")
    if not isinstance(working_set_id, int) or not isinstance(active_working_set, Mapping):
        return None, None
    return working_set_id, {
        "working_set_id": working_set_id,
        "working_set_name": str(active_working_set.get("name") or f"Working set #{working_set_id}"),
        "item_count": int(active_working_set.get("item_count") or 0),
        "missing_item_count": int(active_working_set.get("missing_item_count") or 0),
    }


def _queue_progress(snapshot: Mapping[str, Any]) -> str:
    total = int(snapshot.get("loop_count") or 0)
    current_index = snapshot.get("current_index")
    if not isinstance(current_index, int):
        return f"0 of {total}"
    return f"{current_index + 1} of {total}"


def _queue_remaining(snapshot: Mapping[str, Any]) -> int:
    total = int(snapshot.get("loop_count") or 0)
    current_index = snapshot.get("current_index")
    if not isinstance(current_index, int):
        return total
    return max(total - (current_index + 1), 0)


def _loop_undo_action(loop: Mapping[str, Any], *, summary: str) -> dict[str, Any] | None:
    loop_id = loop.get("id")
    expected_event_id = loop.get("latest_reversible_event_id")
    if not isinstance(loop_id, int) or not isinstance(expected_event_id, int):
        return None
    return {
        "label": "Undo apply",
        "description": summary,
        "undo": {
            "kind": "loop_event",
            "loop_id": loop_id,
            "expected_event_id": expected_event_id,
            "event_type": loop.get("latest_reversible_event_type"),
            "claim_token": None,
        },
        "success_location": {"state": "do", "loop_id": loop_id},
    }


def _relationship_pair_state(
    *,
    loop_id: int,
    candidate_loop_id: int,
    conn: sqlite3.Connection,
) -> RelationshipPairState:
    rows = repo.list_loop_links_for_loop_ids(
        loop_ids=[loop_id, candidate_loop_id],
        relationship_types=["duplicate", "related"],
        link_states=None,
        conn=conn,
    )
    pair_state_map = relationship_review._build_pair_state_map(rows)
    pair_state = pair_state_map.get(relationship_review._pair_key(loop_id, candidate_loop_id), {})

    def _normalize(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not details:
            return None
        state = details.get("state")
        if state is None:
            return None
        return {
            "state": str(state),
            "confidence": (
                float(details["confidence"]) if details.get("confidence") is not None else None
            ),
            "source": str(details["source"]) if details.get("source") is not None else None,
        }

    return {
        "duplicate": _normalize(cast(Mapping[str, Any] | None, pair_state.get("duplicate"))),
        "related": _normalize(cast(Mapping[str, Any] | None, pair_state.get("related"))),
    }


def _apply_relationship_pair_state(
    *,
    loop_id: int,
    candidate_loop_id: int,
    pair_state: RelationshipPairState,
    conn: sqlite3.Connection,
) -> None:
    for relationship_type in ("duplicate", "related"):
        state = pair_state.get(relationship_type)
        if state is None:
            repo.delete_loop_link(
                loop_id=loop_id,
                related_loop_id=candidate_loop_id,
                relationship_type=relationship_type,
                conn=conn,
            )
            repo.delete_loop_link(
                loop_id=candidate_loop_id,
                related_loop_id=loop_id,
                relationship_type=relationship_type,
                conn=conn,
            )
            continue
        repo.upsert_loop_link(
            loop_id=loop_id,
            related_loop_id=candidate_loop_id,
            relationship_type=relationship_type,
            link_state=str(state["state"]),
            confidence=(
                float(state["confidence"]) if state.get("confidence") is not None else None
            ),
            source=str(state.get("source") or "user"),
            conn=conn,
        )
        repo.upsert_loop_link(
            loop_id=candidate_loop_id,
            related_loop_id=loop_id,
            relationship_type=relationship_type,
            link_state=str(state["state"]),
            confidence=(
                float(state["confidence"]) if state.get("confidence") is not None else None
            ),
            source=str(state.get("source") or "user"),
            conn=conn,
        )


def _relationship_decision_undo_action(
    *,
    session_id: int,
    loop_id: int,
    candidate_loop_id: int,
    before_state: RelationshipPairState,
    after_state: RelationshipPairState,
) -> dict[str, Any] | None:
    if before_state == after_state:
        return None
    return {
        "label": "Undo decision",
        "description": (
            "Restore this relationship pair to the state it had before the saved review decision."
        ),
        "undo": {
            "kind": "relationship_decision",
            "session_id": session_id,
            "loop_id": loop_id,
            "candidate_loop_id": candidate_loop_id,
            "expected_pair_state": after_state,
            "restore_pair_state": before_state,
        },
        "success_location": {
            "state": "decide",
            "review_focus": "relationship",
            "session_id": session_id,
        },
    }


def _relationship_follow_through(
    *,
    session: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    current_context: Mapping[str, Any],
    title: str,
    summary: str,
    rationale: str,
    tone: str,
    undo_action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    working_set_id, working_set = _working_set_follow_through_payload(current_context)
    current_item = cast(Mapping[str, Any] | None, snapshot.get("current_item"))
    current_loop = cast(
        Mapping[str, Any] | None, current_item.get("loop") if current_item else None
    )
    return {
        "display_card": {
            "kind": "receipt",
            "tone": tone,
            "eyebrow": "Relationship receipt",
            "title": title,
            "summary": summary,
            "rationale": rationale,
            "preview": [
                {"label": "Queue", "value": _queue_progress(snapshot)},
                {"label": "Remaining", "value": str(_queue_remaining(snapshot))},
                *(
                    [
                        {
                            "label": "Next up",
                            "value": _loop_label(current_loop, fallback="Review complete"),
                        }
                    ]
                    if current_loop is not None
                    else []
                ),
            ],
            "trust": {
                "generation_label": "Recorded relationship decision",
                "generation_tone": "progress",
                "context_sources": [f"Saved relationship review session {session['name']}"],
                "assumptions": [
                    "The saved relationship-review session refreshed immediately after "
                    "the decision landed.",
                ],
                "confidence_label": "Decision saved",
                "confidence_tone": "progress",
                "freshness_label": f"Queue refreshed {session['updated_at_utc']}",
                "freshness_tone": "progress",
                "rollback_label": (
                    "Undo remains available for this relationship decision."
                    if undo_action is not None
                    else "Undo is not available for this relationship decision."
                ),
                "rollback_tone": "attention" if undo_action is not None else "neutral",
                "impact_summary": summary,
                "impact_tone": tone,
            },
            "handoff": {
                "change_summary": "The relationship queue advanced after this decision.",
                "created_resources": [],
                "next_step": (
                    f"Review {_loop_label(current_loop, fallback='the next queued loop')}."
                    if current_loop is not None
                    else "This saved relationship review session is complete."
                ),
                "breadcrumbs": ["Review", str(session["name"])],
                "working_set": working_set,
            },
        },
        "undo_action": undo_action,
        "rerun_action": snapshot.get("rerun_action"),
        "resume_location": _review_resume_location(
            review_focus="relationship",
            session_id=int(session["id"]),
            working_set_id=working_set_id,
        ),
        "workflow_thread": _review_workflow_thread(session=session, review_focus="relationship"),
        "working_set_id": working_set_id,
    }


def _enrichment_follow_through(
    *,
    session: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    current_context: Mapping[str, Any],
    title: str,
    summary: str,
    rationale: str,
    tone: str,
    undo_action: Mapping[str, Any] | None,
    created_resources: list[str] | None = None,
) -> dict[str, Any]:
    working_set_id, working_set = _working_set_follow_through_payload(current_context)
    current_item = cast(Mapping[str, Any] | None, snapshot.get("current_item"))
    current_loop = cast(
        Mapping[str, Any] | None, current_item.get("loop") if current_item else None
    )
    return {
        "display_card": {
            "kind": "receipt",
            "tone": tone,
            "eyebrow": "Enrichment receipt",
            "title": title,
            "summary": summary,
            "rationale": rationale,
            "preview": [
                {"label": "Queue", "value": _queue_progress(snapshot)},
                {"label": "Remaining", "value": str(_queue_remaining(snapshot))},
                *(
                    [
                        {
                            "label": "Next up",
                            "value": _loop_label(current_loop, fallback="Review complete"),
                        }
                    ]
                    if current_loop is not None
                    else []
                ),
            ],
            "trust": {
                "generation_label": "Recorded enrichment outcome",
                "generation_tone": "progress",
                "context_sources": [f"Saved enrichment review session {session['name']}"],
                "assumptions": [
                    "The saved enrichment-review session refreshed immediately after the "
                    "mutation landed.",
                ],
                "confidence_label": "Outcome saved",
                "confidence_tone": "progress",
                "freshness_label": f"Queue refreshed {session['updated_at_utc']}",
                "freshness_tone": "progress",
                "rollback_label": (
                    "Undo remains available for this enrichment change."
                    if undo_action is not None
                    else "Undo is not available for this enrichment outcome."
                ),
                "rollback_tone": "attention" if undo_action is not None else "neutral",
                "impact_summary": summary,
                "impact_tone": tone,
            },
            "handoff": {
                "change_summary": "The enrichment queue refreshed after this outcome.",
                "created_resources": created_resources or [],
                "next_step": (
                    f"Review {_loop_label(current_loop, fallback='the next queued loop')}."
                    if current_loop is not None
                    else "This saved enrichment review session is complete."
                ),
                "breadcrumbs": ["Review", str(session["name"])],
                "working_set": working_set,
            },
        },
        "undo_action": undo_action,
        "rerun_action": snapshot.get("rerun_action"),
        "resume_location": _review_resume_location(
            review_focus="enrichment",
            session_id=int(session["id"]),
            working_set_id=working_set_id,
        ),
        "workflow_thread": _review_workflow_thread(session=session, review_focus="enrichment"),
        "working_set_id": working_set_id,
    }


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

    before_pair_state = _relationship_pair_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        conn=conn,
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
    after_pair_state = _relationship_pair_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        conn=conn,
    )

    after = _build_relationship_session_snapshot(
        session_row=_require_relationship_session_row(session_id=session_id, conn=conn),
        conn=conn,
        settings=settings,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    context = working_sets.get_working_set_context(conn=conn)
    primary_label = _loop_label(cast(Mapping[str, Any], item["loop"]), fallback=f"Loop #{loop_id}")
    candidate_label = _loop_label(
        cast(Mapping[str, Any], candidate), fallback=f"Loop #{candidate_loop_id}"
    )
    summary = (
        f"Confirmed {actual_relationship_type} for {primary_label} and {candidate_label}."
        if resolved_action_type == "confirm"
        else (
            f"Dismissed the {actual_relationship_type} suggestion for {primary_label} and "
            f"{candidate_label}."
        )
    )
    follow_through = _relationship_follow_through(
        session=after["session"],
        snapshot=after,
        current_context=context,
        title=(
            f"Confirmed {actual_relationship_type}"
            if resolved_action_type == "confirm"
            else f"Dismissed {actual_relationship_type} suggestion"
        ),
        summary=summary,
        rationale=(
            "Relationship receipts keep pair decisions resumable after the queue advances "
            "so operators can reopen the saved review session without reconstructing what "
            "landed."
        ),
        tone="attention" if resolved_action_type == "confirm" else "progress",
        undo_action=_relationship_decision_undo_action(
            session_id=session_id,
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            before_state=before_pair_state,
            after_state=after_pair_state,
        ),
    )
    return {"result": result, "snapshot": after, "follow_through": follow_through}


@typingx.validate_io()
def undo_relationship_review_session_action(
    *,
    session_id: int,
    loop_id: int,
    candidate_loop_id: int,
    expected_pair_state: Mapping[str, Any],
    restore_pair_state: Mapping[str, Any],
    conn: sqlite3.Connection,
    settings: Any,
) -> dict[str, Any]:
    session_row = _require_relationship_session_row(session_id=session_id, conn=conn)
    before = _build_relationship_session_snapshot(
        session_row=session_row,
        conn=conn,
        settings=settings,
    )
    previous_order = _candidate_loop_ids(before["items"])
    previous_index = before["current_index"]

    current_pair_state = _relationship_pair_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        conn=conn,
    )
    if current_pair_state != dict(expected_pair_state):
        raise ValidationError(
            "undo_action",
            "relationship decision is stale because the pair state changed after the "
            "saved review outcome landed",
        )

    with conn:
        _apply_relationship_pair_state(
            loop_id=loop_id,
            candidate_loop_id=candidate_loop_id,
            pair_state=dict(restore_pair_state),
            conn=conn,
        )

    after = _build_relationship_session_snapshot(
        session_row=_require_relationship_session_row(session_id=session_id, conn=conn),
        conn=conn,
        settings=settings,
        previous_order=previous_order,
        previous_index=previous_index,
    )
    context = working_sets.get_working_set_context(conn=conn)
    restored_pair_state = _relationship_pair_state(
        loop_id=loop_id,
        candidate_loop_id=candidate_loop_id,
        conn=conn,
    )
    summary = (
        "Restored the relationship pair to the state captured before the saved review decision."
    )
    follow_through = _relationship_follow_through(
        session=after["session"],
        snapshot=after,
        current_context=context,
        title="Restored relationship decision",
        summary=summary,
        rationale=(
            "Undo receipts keep saved relationship reversals explicit so the refreshed "
            "review queue stays trustworthy after an exact-handle restore."
        ),
        tone="progress",
        undo_action=None,
    )
    return {
        "result": {
            "loop_id": loop_id,
            "candidate_loop_id": candidate_loop_id,
            "restored_pair_state": restored_pair_state,
            "summary": summary,
        },
        "snapshot": after,
        "follow_through": follow_through,
    }


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
    context = working_sets.get_working_set_context(conn=conn)
    result_loop = cast(Mapping[str, Any] | None, result.get("loop"))
    suggestion_loop = cast(
        Mapping[str, Any] | None,
        next(
            (
                item.get("loop")
                for item in before["items"]
                if any(
                    int(suggestion["id"]) == suggestion_id
                    for suggestion in item.get("pending_suggestions", [])
                )
            ),
            None,
        ),
    )
    created_resources = (
        [_loop_label(result_loop, fallback="Updated loop")] if result_loop is not None else []
    )
    summary = (
        f"Applied suggestion #{suggestion_id} and refreshed the enrichment queue."
        if resolved_action_type == "apply"
        else f"Rejected suggestion #{suggestion_id} and refreshed the enrichment queue."
    )
    undo_action = (
        _loop_undo_action(
            result_loop,
            summary=(
                "Undo the applied enrichment change for "
                f"{_loop_label(result_loop, fallback='the loop')}."
            ),
        )
        if resolved_action_type == "apply" and result_loop is not None
        else None
    )
    follow_through = _enrichment_follow_through(
        session=after["session"],
        snapshot=after,
        current_context=context,
        title=(
            f"Applied suggestion #{suggestion_id}"
            if resolved_action_type == "apply"
            else f"Rejected suggestion #{suggestion_id}"
        ),
        summary=summary,
        rationale=(
            "Enrichment receipts keep saved review outcomes resumable after the queue "
            "shifts so operators can continue from the landed result instead of "
            "reconstructing it from the previous item."
        ),
        tone="attention" if resolved_action_type == "apply" else "progress",
        undo_action=undo_action,
        created_resources=(
            created_resources
            or (
                [_loop_label(suggestion_loop, fallback="Queued loop")]
                if suggestion_loop is not None
                else []
            )
        ),
    )
    return {"result": result, "snapshot": after, "follow_through": follow_through}


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
    context = working_sets.get_working_set_context(conn=conn)
    follow_through = _enrichment_follow_through(
        session=after["session"],
        snapshot=after,
        current_context=context,
        title="Recorded clarification answers",
        summary=str(result.get("message") or "Clarifications recorded and enrichment reran."),
        rationale=(
            "Clarification receipts keep the answer-and-rerun path resumable so operators "
            "can continue from the refreshed queue without reconstructing which prompts "
            "were answered."
        ),
        tone="progress",
        undo_action=None,
        created_resources=[
            _loop_label(cast(Mapping[str, Any], item["loop"]), fallback=f"Loop #{loop_id}")
        ],
    )
    return {"result": result, "snapshot": after, "follow_through": follow_through}


__all__ = [
    "execute_relationship_review_session_action",
    "undo_relationship_review_session_action",
    "execute_enrichment_review_session_action",
    "answer_enrichment_review_session_clarifications",
]
