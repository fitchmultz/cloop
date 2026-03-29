"""Enrichment-review workflow schemas.

Purpose:
    Define queue, action, session, and clarification-rerun payloads for enrichment review.

Responsibilities:
    - Shape enrichment-review queue and session snapshots
    - Validate enrichment-review action payloads
    - Serialize clarification-answer + rerun response envelopes

Non-scope:
    - Suggestion base schemas defined elsewhere
    - Planning-session checkpoint models
    - Enrichment execution/orchestration logic
"""

from __future__ import annotations

from typing import List, Literal

from ._shared import SEARCH_QUERY_MAX, VIEW_DESCRIPTION_MAX, VIEW_NAME_MAX, BaseModel, Field
from .continuity import ContinuityRerunAction, ReviewFollowThroughResponse
from .core import LoopEnrichmentResponse, LoopResponse
from .suggestions import (
    ClarificationResponse,
    ClarificationSubmitRequest,
    ClarificationSubmitResponse,
    SuggestionResponse,
)


class EnrichmentReviewQueueItemResponse(BaseModel):
    """One loop with pending enrichment follow-up work."""

    loop: LoopResponse
    pending_suggestion_count: int
    pending_clarification_count: int
    newest_pending_at: str
    pending_suggestions: List["SuggestionResponse"]
    pending_clarifications: List["ClarificationResponse"]


class EnrichmentReviewActionCreateRequest(BaseModel):
    """Create a saved enrichment-review action."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["apply", "reject"]
    fields: List[str] | None = None
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class EnrichmentReviewActionUpdateRequest(BaseModel):
    """Update a saved enrichment-review action."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["apply", "reject"] | None = None
    fields: List[str] | None = None
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class EnrichmentReviewActionResponse(BaseModel):
    """Saved enrichment-review action response."""

    id: int
    name: str
    review_kind: Literal["enrichment"] = "enrichment"
    action_type: Literal["apply", "reject"]
    fields: List[str] | None = None
    description: str | None = None
    created_at_utc: str
    updated_at_utc: str


class EnrichmentReviewSessionCreateRequest(BaseModel):
    """Create a saved enrichment-review session."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    query: str = Field(..., min_length=1, max_length=SEARCH_QUERY_MAX)
    pending_kind: Literal["all", "suggestions", "clarifications"] = "all"
    suggestion_limit: int = Field(default=3, ge=1, le=20)
    clarification_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)
    current_loop_id: int | None = None


class EnrichmentReviewSessionUpdateRequest(BaseModel):
    """Update a saved enrichment-review session."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    pending_kind: Literal["all", "suggestions", "clarifications"] | None = None
    suggestion_limit: int | None = Field(default=None, ge=1, le=20)
    clarification_limit: int | None = Field(default=None, ge=1, le=20)
    item_limit: int | None = Field(default=None, ge=1, le=100)
    current_loop_id: int | None = None


class EnrichmentReviewSessionResponse(BaseModel):
    """Saved enrichment-review session metadata."""

    id: int
    name: str
    review_kind: Literal["enrichment"] = "enrichment"
    query: str
    pending_kind: Literal["all", "suggestions", "clarifications"]
    suggestion_limit: int
    clarification_limit: int
    item_limit: int
    current_loop_id: int | None = None
    created_at_utc: str
    updated_at_utc: str


class EnrichmentReviewSessionSnapshotResponse(BaseModel):
    """Session snapshot for enrichment review."""

    session: EnrichmentReviewSessionResponse
    loop_count: int
    current_index: int | None = None
    current_item: EnrichmentReviewQueueItemResponse | None = None
    items: List[EnrichmentReviewQueueItemResponse]
    rerun_action: ContinuityRerunAction | None = None


class EnrichmentReviewSessionActionRequest(BaseModel):
    """Run an enrichment-review action inside a saved session."""

    suggestion_id: int
    action_preset_id: int | None = None
    action_type: Literal["apply", "reject"] | None = None
    fields: List[str] | None = None


class EnrichmentReviewActionResultResponse(BaseModel):
    """Normalized result of applying or rejecting a suggestion."""

    suggestion_id: int
    resolution: str
    loop: LoopResponse | None = None
    applied_fields: List[str] = Field(default_factory=list)


class EnrichmentReviewSessionActionResponse(BaseModel):
    """Result of an enrichment-review session action."""

    result: EnrichmentReviewActionResultResponse
    snapshot: EnrichmentReviewSessionSnapshotResponse
    follow_through: ReviewFollowThroughResponse


class EnrichmentReviewSessionClarificationRequest(BaseModel):
    """Answer clarifications inside a saved enrichment session."""

    loop_id: int
    answers: List["ClarificationSubmitRequest"]


class ClarificationRefinementResponse(BaseModel):
    """Result of answering clarifications and rerunning enrichment."""

    loop_id: int
    clarification_result: "ClarificationSubmitResponse"
    enrichment_result: LoopEnrichmentResponse
    message: str = "Clarifications recorded and enrichment reran."


class EnrichmentReviewSessionClarificationResponse(BaseModel):
    """Result of answering clarifications inside a saved enrichment session."""

    result: ClarificationRefinementResponse
    snapshot: EnrichmentReviewSessionSnapshotResponse
    follow_through: ReviewFollowThroughResponse
