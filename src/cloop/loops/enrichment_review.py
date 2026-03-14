"""Shared suggestion and clarification review workflows for enrichment.

Purpose:
    Centralize the review/follow-up lifecycle around enrichment suggestions so
    HTTP routes, CLI commands, MCP tools, and the web UI all reuse one
    canonical contract.

Responsibilities:
    - List and inspect enrichment suggestions with parsed payloads
    - Link suggestion questions to persisted clarification records
    - Apply or reject suggestions using shared loop update semantics
    - Record clarification answers against existing clarification rows
    - Mark clarification-dependent suggestions as superseded once answers land

Non-scope:
    - Triggering enrichment generation itself (see enrichment.py / enrichment_orchestration.py)
    - Duplicate merge previews and merge execution (see duplicates.py)
    - Transport-specific response modeling or error mapping
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .. import typingx
from ..settings import Settings
from . import read_service, repo
from .errors import (
    ClarificationNotFoundError,
    LoopNotFoundError,
    SuggestionNotFoundError,
    ValidationError,
)
from .serialization import enrich_loop_records_batch

SUGGESTION_APPLYABLE_FIELDS = frozenset(
    {
        "title",
        "summary",
        "definition_of_done",
        "next_action",
        "due_at",
        "snooze_until",
        "activation_energy",
        "time_minutes",
        "urgency",
        "importance",
        "project",
        "tags",
    }
)


@dataclass(frozen=True, slots=True)
class ClarificationAnswerInput:
    """One clarification answer targeting an existing clarification row."""

    clarification_id: int
    answer: str


@dataclass(frozen=True, slots=True)
class ClarificationSubmissionResult:
    """Canonical result of recording clarification answers."""

    loop_id: int
    answered_count: int
    clarifications: list[dict[str, Any]]
    superseded_suggestion_ids: list[int]
    message: str = "Clarifications recorded. Re-enrich to generate an updated suggestion."

    def to_payload(self) -> dict[str, Any]:
        """Convert the result into a transport-ready payload."""
        return {
            "loop_id": self.loop_id,
            "answered_count": self.answered_count,
            "clarifications": self.clarifications,
            "superseded_suggestion_ids": self.superseded_suggestion_ids,
            "message": self.message,
        }


def _question_map_for_clarifications(
    clarifications: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for clarification in clarifications:
        grouped[str(clarification["question"])].append(dict(clarification))
    return grouped


def _inflate_suggestion(
    *,
    suggestion: Mapping[str, Any],
    clarifications_by_question: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    parsed = json.loads(str(suggestion["suggestion_json"]))
    linked_clarifications: list[dict[str, Any]] = []
    seen_clarification_ids: set[int] = set()

    for question in parsed.get("needs_clarification") or []:
        for clarification in clarifications_by_question.get(str(question), []):
            clarification_id = int(clarification["id"])
            if clarification_id in seen_clarification_ids:
                continue
            linked_clarifications.append(dict(clarification))
            seen_clarification_ids.add(clarification_id)

    return {
        **dict(suggestion),
        "parsed": parsed,
        "clarifications": linked_clarifications,
    }


@typingx.validate_io()
def list_loop_suggestions(
    *,
    loop_id: int | None = None,
    pending_only: bool = False,
    limit: int = 50,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List suggestions with parsed payloads and linked clarification rows."""
    if pending_only:
        suggestions = repo.list_pending_suggestions(loop_id=loop_id, conn=conn, limit=limit)
    else:
        suggestions = repo.list_loop_suggestions(loop_id=loop_id, limit=limit, conn=conn)

    if not suggestions:
        return []

    loop_ids = sorted({int(suggestion["loop_id"]) for suggestion in suggestions})
    clarifications = repo.list_loop_clarifications_for_loops(loop_ids=loop_ids, conn=conn)
    clarifications_by_loop: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    grouped_by_loop: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for clarification in clarifications:
        grouped_by_loop[int(clarification["loop_id"])].append(dict(clarification))
    for current_loop_id, loop_clarifications in grouped_by_loop.items():
        clarifications_by_loop[current_loop_id] = _question_map_for_clarifications(
            loop_clarifications
        )

    return [
        _inflate_suggestion(
            suggestion=suggestion,
            clarifications_by_question=clarifications_by_loop.get(int(suggestion["loop_id"]), {}),
        )
        for suggestion in suggestions
    ]


@typingx.validate_io()
def get_loop_suggestion(
    *,
    suggestion_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Get one suggestion with parsed payload and linked clarifications."""
    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)
    if suggestion is None:
        raise SuggestionNotFoundError(suggestion_id)

    clarifications = repo.list_loop_clarifications(loop_id=int(suggestion["loop_id"]), conn=conn)
    return _inflate_suggestion(
        suggestion=suggestion,
        clarifications_by_question=_question_map_for_clarifications(clarifications),
    )


@typingx.validate_io()
def apply_suggestion(
    *,
    suggestion_id: int,
    fields: list[str] | None = None,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    """Apply a suggestion to its loop."""
    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)
    if not suggestion:
        raise SuggestionNotFoundError(suggestion_id)

    if suggestion.get("resolution"):
        raise ValidationError(
            "suggestion", f"Suggestion already resolved: {suggestion['resolution']}"
        )

    loop_id = int(suggestion["loop_id"])
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if not loop:
        raise LoopNotFoundError(loop_id)

    parsed = json.loads(str(suggestion["suggestion_json"]))
    applied_fields: list[str] = []

    if fields:
        apply_set = set(fields)
        invalid_fields = sorted(apply_set.difference(SUGGESTION_APPLYABLE_FIELDS))
        if invalid_fields:
            raise ValidationError(
                "fields",
                f"unsupported suggestion fields: {', '.join(invalid_fields)}",
            )
    else:
        apply_set = {
            field
            for field, confidence in parsed.get("confidence", {}).items()
            if confidence >= settings.autopilot_autoapply_min_confidence
        }

    update_fields: dict[str, Any] = {}
    field_mapping = {
        "title": ("title", parsed.get("title")),
        "summary": ("summary", parsed.get("summary")),
        "definition_of_done": ("definition_of_done", parsed.get("definition_of_done")),
        "next_action": ("next_action", parsed.get("next_action")),
        "due_at": ("due_at_utc", parsed.get("due_at")),
        "snooze_until": ("snooze_until_utc", parsed.get("snooze_until")),
        "activation_energy": ("activation_energy", parsed.get("activation_energy")),
        "time_minutes": ("time_minutes", parsed.get("time_minutes")),
        "urgency": ("urgency", parsed.get("urgency")),
        "importance": ("importance", parsed.get("importance")),
    }

    for field_name, (db_field, value) in field_mapping.items():
        if field_name in apply_set and value is not None:
            update_fields[db_field] = value
            applied_fields.append(field_name)

    if "project" in apply_set and parsed.get("project"):
        project_id = repo.upsert_project(name=str(parsed["project"]), conn=conn)
        update_fields["project_id"] = project_id
        applied_fields.append("project")

    with conn:
        if "tags" in apply_set and parsed.get("tags"):
            repo.replace_loop_tags(loop_id=loop_id, tag_names=list(parsed["tags"]), conn=conn)
            applied_fields.append("tags")

        if update_fields:
            repo.update_loop_fields(loop_id=loop_id, fields=update_fields, conn=conn)

        resolution = "applied" if len(applied_fields) == len(apply_set) else "partial"
        repo.resolve_loop_suggestion(
            suggestion_id=suggestion_id,
            resolution=resolution,
            applied_fields=applied_fields,
            conn=conn,
        )

    return {
        "loop": read_service.get_loop(loop_id=loop_id, conn=conn),
        "suggestion_id": suggestion_id,
        "applied_fields": applied_fields,
        "resolution": resolution,
    }


@typingx.validate_io()
def reject_suggestion(
    *,
    suggestion_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Reject a suggestion without applying any fields."""
    suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)
    if not suggestion:
        raise SuggestionNotFoundError(suggestion_id)

    if suggestion.get("resolution"):
        raise ValidationError(
            "suggestion", f"Suggestion already resolved: {suggestion['resolution']}"
        )

    with conn:
        repo.resolve_loop_suggestion(
            suggestion_id=suggestion_id,
            resolution="rejected",
            conn=conn,
        )

    return {"suggestion_id": suggestion_id, "resolution": "rejected"}


@typingx.validate_io()
def list_loop_clarifications(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List clarification records for one loop."""
    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if not loop:
        raise LoopNotFoundError(loop_id)
    return repo.list_loop_clarifications(loop_id=loop_id, conn=conn)


@typingx.validate_io()
def list_enrichment_review_queue(
    *,
    query: str,
    pending_kind: str,
    limit: int,
    suggestion_limit: int,
    clarification_limit: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """List loops with pending enrichment suggestions or clarifications."""
    if pending_kind not in {"all", "suggestions", "clarifications"}:
        raise ValidationError(
            "pending_kind",
            "must be all, suggestions, or clarifications",
        )
    if limit < 1:
        raise ValidationError("limit", "must be positive")
    if suggestion_limit < 1:
        raise ValidationError("suggestion_limit", "must be positive")
    if clarification_limit < 1:
        raise ValidationError("clarification_limit", "must be positive")

    records = repo.search_loops_by_query(query=query, limit=None, conn=conn)
    if not records:
        return {
            "query": query,
            "pending_kind": pending_kind,
            "limit": limit,
            "suggestion_limit": suggestion_limit,
            "clarification_limit": clarification_limit,
            "loop_count": 0,
            "items": [],
        }

    loop_ids = [record.id for record in records]
    payload_by_id = {
        int(payload["id"]): payload for payload in enrich_loop_records_batch(records, conn=conn)
    }
    pending_clarifications = repo.list_unanswered_clarifications_for_loops(
        loop_ids=loop_ids, conn=conn
    )
    clarifications_by_loop: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for clarification in pending_clarifications:
        clarifications_by_loop[int(clarification["loop_id"])].append(dict(clarification))

    clarifications_by_loop_question: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for loop_id, clarifications in clarifications_by_loop.items():
        clarifications_by_loop_question[loop_id] = _question_map_for_clarifications(clarifications)

    suggestions_by_loop: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for suggestion in repo.list_pending_suggestions_for_loops(loop_ids=loop_ids, conn=conn):
        inflated = _inflate_suggestion(
            suggestion=suggestion,
            clarifications_by_question=clarifications_by_loop_question.get(
                int(suggestion["loop_id"]),
                {},
            ),
        )
        suggestions_by_loop[int(suggestion["loop_id"])].append(inflated)

    items: list[dict[str, Any]] = []
    for record in records:
        loop_payload = payload_by_id.get(record.id)
        if loop_payload is None:
            continue
        loop_suggestions = suggestions_by_loop.get(record.id, [])
        loop_clarifications = clarifications_by_loop.get(record.id, [])
        if pending_kind == "suggestions":
            has_pending = bool(loop_suggestions)
        elif pending_kind == "clarifications":
            has_pending = bool(loop_clarifications)
        else:
            has_pending = bool(loop_suggestions or loop_clarifications)
        if not has_pending:
            continue

        newest_pending_at = max(
            [str(item["created_at"]) for item in loop_suggestions]
            + [str(item["created_at"]) for item in loop_clarifications]
            or [""],
        )
        items.append(
            {
                "loop": loop_payload,
                "pending_suggestion_count": len(loop_suggestions),
                "pending_clarification_count": len(loop_clarifications),
                "newest_pending_at": newest_pending_at,
                "pending_suggestions": loop_suggestions[:suggestion_limit],
                "pending_clarifications": loop_clarifications[:clarification_limit],
            }
        )

    items.sort(
        key=lambda item: (
            item["pending_clarification_count"],
            item["pending_suggestion_count"],
            str(item["newest_pending_at"]),
            str(item["loop"]["updated_at_utc"]),
            int(item["loop"]["id"]),
        ),
        reverse=True,
    )
    return {
        "query": query,
        "pending_kind": pending_kind,
        "limit": limit,
        "suggestion_limit": suggestion_limit,
        "clarification_limit": clarification_limit,
        "loop_count": len(items),
        "items": items[:limit],
    }


def _validate_clarification_answers(
    *,
    loop_id: int,
    answers: Sequence[ClarificationAnswerInput],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    if not answers:
        raise ValidationError("answers", "at least one clarification answer is required")

    loop = repo.read_loop(loop_id=loop_id, conn=conn)
    if not loop:
        raise LoopNotFoundError(loop_id)

    clarifications: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in answers:
        clarification_id = int(item.clarification_id)
        if clarification_id in seen_ids:
            raise ValidationError(
                "clarification_id", f"duplicate clarification_id in request: {clarification_id}"
            )
        seen_ids.add(clarification_id)

        answer = item.answer.strip()
        if not answer:
            raise ValidationError("answer", "answer must not be empty")

        clarification = repo.read_loop_clarification(
            clarification_id=clarification_id,
            conn=conn,
        )
        if clarification is None:
            raise ClarificationNotFoundError(clarification_id)
        if int(clarification["loop_id"]) != loop_id:
            raise ValidationError(
                "clarification_id",
                f"clarification {clarification_id} does not belong to loop {loop_id}",
            )
        if clarification.get("answer"):
            raise ValidationError(
                "clarification",
                f"Clarification already answered: {clarification_id}",
            )
        clarifications.append(clarification)
    return clarifications


def _supersede_answered_suggestions(
    *,
    loop_id: int,
    answered_questions: set[str],
    conn: sqlite3.Connection,
) -> list[int]:
    superseded_ids: list[int] = []
    pending_suggestions = repo.list_pending_suggestions(loop_id=loop_id, conn=conn, limit=1000)
    for suggestion in pending_suggestions:
        parsed = json.loads(str(suggestion["suggestion_json"]))
        needs_clarification = {
            str(question) for question in parsed.get("needs_clarification") or []
        }
        if not needs_clarification.intersection(answered_questions):
            continue
        repo.resolve_loop_suggestion(
            suggestion_id=int(suggestion["id"]),
            resolution="superseded",
            conn=conn,
        )
        superseded_ids.append(int(suggestion["id"]))
    return superseded_ids


@typingx.validate_io()
def submit_clarification_answers(
    *,
    loop_id: int,
    answers: Sequence[ClarificationAnswerInput],
    conn: sqlite3.Connection,
) -> ClarificationSubmissionResult:
    """Record answers for existing clarification rows on one loop."""
    clarifications = _validate_clarification_answers(loop_id=loop_id, answers=answers, conn=conn)

    answered_clarifications: list[dict[str, Any]] = []
    answered_questions: set[str] = set()

    with conn:
        for clarification, item in zip(clarifications, answers, strict=True):
            repo.answer_loop_clarification(
                clarification_id=int(clarification["id"]),
                answer=item.answer.strip(),
                conn=conn,
            )
            updated = repo.read_loop_clarification(
                clarification_id=int(clarification["id"]),
                conn=conn,
            )
            if updated is None:
                raise ClarificationNotFoundError(int(clarification["id"]))
            answered_clarifications.append(updated)
            answered_questions.add(str(updated["question"]))

        superseded_suggestion_ids = _supersede_answered_suggestions(
            loop_id=loop_id,
            answered_questions=answered_questions,
            conn=conn,
        )

    return ClarificationSubmissionResult(
        loop_id=loop_id,
        answered_count=len(answered_clarifications),
        clarifications=answered_clarifications,
        superseded_suggestion_ids=superseded_suggestion_ids,
    )
