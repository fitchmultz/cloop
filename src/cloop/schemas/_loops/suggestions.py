"""Suggestion and clarification schemas for loops.

Purpose:
    Define suggestion application, clarification submission, and list payloads.

Responsibilities:
    - Validate suggestion/clarification mutation requests
    - Shape suggestion and clarification list/detail responses
    - Keep enrichment follow-up payloads reusable across routes and MCP tools

Non-scope:
    - Saved enrichment-review session snapshots
    - Relationship-review or planning schemas
    - Suggestion execution/orchestration logic
"""

from __future__ import annotations

from typing import Any, List

from ._shared import BaseModel, Field


class ApplySuggestionRequest(BaseModel):
    """Request to apply a loop suggestion."""

    fields: List[str] | None = None


class ApplySuggestionResponse(BaseModel):
    """Result of applying a suggestion."""

    loop: dict[str, Any]
    suggestion_id: int
    applied_fields: List[str]
    resolution: str


class RejectSuggestionResponse(BaseModel):
    """Result of rejecting a suggestion."""

    suggestion_id: int
    resolution: str


class ClarificationSubmitRequest(BaseModel):
    """Request to submit an answer to a clarification question."""

    clarification_id: int = Field(..., description="ID of the clarification to answer")
    answer: str = Field(..., min_length=1, max_length=1000, description="User's answer")


class ClarificationSubmitBatchRequest(BaseModel):
    """Request to submit answers to multiple clarification questions at once."""

    answers: List[ClarificationSubmitRequest] = Field(
        ...,
        description="List of clarification_id + answer pairs for existing clarifications",
    )


class ClarificationResponse(BaseModel):
    """A single clarification with optional answer."""

    id: int
    loop_id: int
    question: str
    answer: str | None = None
    answered_at: str | None = None
    created_at: str


class SuggestionResponse(BaseModel):
    """A single suggestion with parsed data and linked clarifications."""

    id: int
    loop_id: int
    suggestion_json: str
    parsed: dict[str, Any]
    clarifications: List[ClarificationResponse] = Field(default_factory=list)
    model: str
    created_at: str
    resolution: str | None = None
    resolved_at: str | None = None
    resolved_fields_json: str | None = None


class SuggestionListResponse(BaseModel):
    """List of suggestions."""

    suggestions: List[SuggestionResponse]
    count: int


class ClarificationListResponse(BaseModel):
    """List of clarifications for a loop."""

    clarifications: List[ClarificationResponse]
    count: int


class ClarificationSubmitResponse(BaseModel):
    """Response after submitting clarification answers."""

    loop_id: int
    answered_count: int
    clarifications: List[ClarificationResponse]
    superseded_suggestion_ids: List[int] = Field(default_factory=list)
    message: str = "Clarifications recorded. Re-enrich to generate an updated suggestion."
