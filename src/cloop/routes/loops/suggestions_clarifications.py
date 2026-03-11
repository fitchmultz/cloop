"""Suggestion and clarification endpoints.

Purpose:
    HTTP endpoints for duplicate-resolution suggestions and loop
    clarification question management.

Responsibilities:
    - List, apply, reject, and aggregate suggestions
    - List and submit clarification answers for loops

Non-scope:
    - Core loop lifecycle mutations
    - Metrics, import/export, or review queries
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from ... import db
from ...loops import duplicates as loop_duplicates
from ...loops import repo as loop_repo
from ...loops.errors import LoopNotFoundError
from ...schemas.loops import (
    ApplySuggestionRequest,
    ApplySuggestionResponse,
    ClarificationListResponse,
    ClarificationResponse,
    ClarificationSubmitBatchRequest,
    ClarificationSubmitResponse,
    RejectSuggestionResponse,
    SuggestionListResponse,
    SuggestionResponse,
)
from ._common import SettingsDep

router = APIRouter()


@router.get("/{loop_id}/suggestions", response_model=SuggestionListResponse)
def get_loop_suggestions(
    loop_id: int,
    settings: SettingsDep,
    pending_only: bool = False,
) -> SuggestionListResponse:
    with db.core_connection(settings) as conn:
        suggestions = loop_duplicates.list_loop_suggestions(
            loop_id=loop_id,
            pending_only=pending_only,
            limit=50,
            conn=conn,
        )
    return SuggestionListResponse(
        suggestions=[SuggestionResponse(**s) for s in suggestions],
        count=len(suggestions),
    )


@router.post("/suggestions/{suggestion_id}/apply", response_model=ApplySuggestionResponse)
def apply_suggestion_endpoint(
    suggestion_id: int,
    request: ApplySuggestionRequest,
    settings: SettingsDep,
) -> ApplySuggestionResponse:
    with db.core_connection(settings) as conn:
        result = loop_duplicates.apply_suggestion(
            suggestion_id=suggestion_id,
            fields=request.fields,
            conn=conn,
            settings=settings,
        )
    return ApplySuggestionResponse(**result)


@router.post("/suggestions/{suggestion_id}/reject", response_model=RejectSuggestionResponse)
def reject_suggestion_endpoint(
    suggestion_id: int,
    settings: SettingsDep,
) -> RejectSuggestionResponse:
    with db.core_connection(settings) as conn:
        result = loop_duplicates.reject_suggestion(suggestion_id=suggestion_id, conn=conn)
    return RejectSuggestionResponse(**result)


@router.get("/suggestions/pending", response_model=SuggestionListResponse)
def list_pending_suggestions_endpoint(
    settings: SettingsDep,
    limit: int = 50,
) -> SuggestionListResponse:
    with db.core_connection(settings) as conn:
        suggestions = loop_duplicates.list_loop_suggestions(
            pending_only=True,
            limit=limit,
            conn=conn,
        )
    return SuggestionListResponse(
        suggestions=[SuggestionResponse(**s) for s in suggestions],
        count=len(suggestions),
    )


@router.get("/{loop_id}/clarifications", response_model=ClarificationListResponse)
def get_loop_clarifications(
    loop_id: int,
    settings: SettingsDep,
) -> ClarificationListResponse:
    with db.core_connection(settings) as conn:
        loop = loop_repo.read_loop(loop_id=loop_id, conn=conn)
        if not loop:
            raise LoopNotFoundError(loop_id)

        clarifications = loop_repo.list_loop_clarifications(loop_id=loop_id, conn=conn)
        return ClarificationListResponse(
            clarifications=[
                ClarificationResponse(
                    id=c["id"],
                    loop_id=c["loop_id"],
                    question=c["question"],
                    answer=c["answer"],
                    answered_at=c["answered_at"],
                    created_at=c["created_at"],
                )
                for c in clarifications
            ],
            count=len(clarifications),
        )


@router.post("/{loop_id}/clarify", response_model=ClarificationSubmitResponse)
def submit_clarification(
    loop_id: int,
    request: ClarificationSubmitBatchRequest,
    settings: SettingsDep,
) -> ClarificationSubmitResponse:
    with db.core_connection(settings) as conn:
        loop = loop_repo.read_loop(loop_id=loop_id, conn=conn)
        if not loop:
            raise LoopNotFoundError(loop_id)

        answered_count = 0
        created_clarifications: list[dict[str, Any]] = []

        with conn:
            for item in request.answers:
                question = item.get("question")
                answer = item.get("answer")
                if not question or not answer:
                    continue

                cursor = conn.execute(
                    """
                    INSERT INTO loop_clarifications (loop_id, question, answer, answered_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (loop_id, question, answer),
                )
                clarification_id = cursor.lastrowid
                answered_count += 1

                created_clarifications.append(
                    {
                        "id": clarification_id,
                        "loop_id": loop_id,
                        "question": question,
                        "answer": answer,
                        "answered_at": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    }
                )

        return ClarificationSubmitResponse(
            loop_id=loop_id,
            answered_count=answered_count,
            clarifications=[ClarificationResponse(**c) for c in created_clarifications],
        )
