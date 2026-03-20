"""Loop review and event-history schemas.

Purpose:
    Define cohort review, event-history, undo, and shared review-cursor schemas.

Responsibilities:
    - Shape review cohort responses
    - Serialize loop event history and undo results
    - Provide shared cursor-move payloads for saved review workflows

Non-scope:
    - Relationship/enrichment review session models
    - Suggestion or clarification payloads
    - Review execution/orchestration logic
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from ._shared import BaseModel
from .core import LoopResponse


class LoopReviewCohortItem(BaseModel):
    """Single loop item within a review cohort."""

    id: int
    raw_text: str
    title: str | None = None
    status: str
    next_action: str | None = None
    due_at_utc: str | None = None
    updated_at_utc: str


class LoopReviewCohortResponse(BaseModel):
    """Response for a single review cohort."""

    cohort: str
    count: int
    items: List[LoopReviewCohortItem]


class LoopReviewResponse(BaseModel):
    """Response for GET /loops/review with daily and weekly cohorts."""

    daily: List[LoopReviewCohortResponse]
    weekly: List[LoopReviewCohortResponse]
    generated_at_utc: str


class LoopEventResponse(BaseModel):
    """Single event in loop event history."""

    id: int
    loop_id: int
    event_type: str
    payload: Dict[str, Any]
    created_at_utc: str
    is_reversible: bool


class LoopEventListResponse(BaseModel):
    """Paginated event history response."""

    loop_id: int
    events: List[LoopEventResponse]
    has_more: bool
    next_cursor: int | None = None


class LoopUndoRequest(BaseModel):
    """Request the exact reversible event to undo for one loop."""

    expected_event_id: int
    claim_token: str | None = None


class LoopUndoResponse(BaseModel):
    """Response from undo operation."""

    loop: LoopResponse
    undone_event_id: int
    undone_event_type: str
    undo_event_id: int


class ReviewSessionMoveRequest(BaseModel):
    """Move a saved review session cursor backward or forward."""

    direction: Literal["next", "previous"]
