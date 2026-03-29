"""Relationship-review schemas for loops.

Purpose:
    Define duplicate/related review payloads, actions, sessions, and decisions.

Responsibilities:
    - Shape relationship candidate and queue responses
    - Validate saved relationship-review action/session payloads
    - Serialize relationship review decisions and session snapshots

Non-scope:
    - Relationship-link persistence or similarity logic
    - Suggestion/clarification enrichment schemas
    - Planning workflow contracts
"""

from __future__ import annotations

from typing import List, Literal

from ._shared import SEARCH_QUERY_MAX, VIEW_DESCRIPTION_MAX, VIEW_NAME_MAX, BaseModel, Field
from .continuity import (
    ContinuityRelationshipDecisionPairState,
    ContinuityRelationshipDecisionUndoHandle,
    ContinuityRerunAction,
    ReviewFollowThroughResponse,
)
from .core import LoopResponse


class RelationshipReviewCandidateResponse(LoopResponse):
    """A related or duplicate candidate surfaced for relationship review."""

    relationship_type: Literal["related", "duplicate"]
    score: float
    raw_text_preview: str
    existing_state: str | None = None
    existing_source: str | None = None


class LoopRelationshipReviewResponse(BaseModel):
    """Relationship-review payload for one loop."""

    loop: LoopResponse
    indexed_count: int
    candidate_count: int
    duplicate_count: int
    related_count: int
    duplicate_candidates: List[RelationshipReviewCandidateResponse]
    related_candidates: List[RelationshipReviewCandidateResponse]
    existing_duplicates: List[RelationshipReviewCandidateResponse] = Field(default_factory=list)
    existing_related: List[RelationshipReviewCandidateResponse] = Field(default_factory=list)


class LoopRelationshipReviewQueueItemResponse(BaseModel):
    """One loop with pending relationship-review candidates."""

    loop: LoopResponse
    duplicate_count: int
    related_count: int
    top_score: float
    duplicate_candidates: List[RelationshipReviewCandidateResponse]
    related_candidates: List[RelationshipReviewCandidateResponse]


class LoopRelationshipReviewQueueResponse(BaseModel):
    """Relationship-review queue across multiple loops."""

    status: str
    relationship_kind: Literal["all", "duplicate", "related"]
    limit: int
    candidate_limit: int
    indexed_count: int
    loop_count: int
    items: List[LoopRelationshipReviewQueueItemResponse]


class RelationshipReviewActionCreateRequest(BaseModel):
    """Create a saved relationship-review action."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["confirm", "dismiss"]
    relationship_type: Literal["suggested", "related", "duplicate"] = "suggested"
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class RelationshipReviewActionUpdateRequest(BaseModel):
    """Update a saved relationship-review action."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    action_type: Literal["confirm", "dismiss"] | None = None
    relationship_type: Literal["suggested", "related", "duplicate"] | None = None
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class RelationshipReviewActionResponse(BaseModel):
    """Saved relationship-review action response."""

    id: int
    name: str
    review_kind: Literal["relationship"] = "relationship"
    action_type: Literal["confirm", "dismiss"]
    relationship_type: Literal["suggested", "related", "duplicate"]
    description: str | None = None
    created_at_utc: str
    updated_at_utc: str


class RelationshipReviewSessionCreateRequest(BaseModel):
    """Create a saved relationship-review session."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    query: str = Field(..., min_length=1, max_length=SEARCH_QUERY_MAX)
    relationship_kind: Literal["all", "duplicate", "related"] = "all"
    candidate_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)
    current_loop_id: int | None = None


class RelationshipReviewSessionUpdateRequest(BaseModel):
    """Update a saved relationship-review session."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    relationship_kind: Literal["all", "duplicate", "related"] | None = None
    candidate_limit: int | None = Field(default=None, ge=1, le=20)
    item_limit: int | None = Field(default=None, ge=1, le=100)
    current_loop_id: int | None = None


class RelationshipReviewSessionResponse(BaseModel):
    """Saved relationship-review session metadata."""

    id: int
    name: str
    review_kind: Literal["relationship"] = "relationship"
    query: str
    relationship_kind: Literal["all", "duplicate", "related"]
    candidate_limit: int
    item_limit: int
    current_loop_id: int | None = None
    created_at_utc: str
    updated_at_utc: str


class RelationshipReviewSessionSnapshotResponse(BaseModel):
    """Session snapshot for relationship review."""

    session: RelationshipReviewSessionResponse
    loop_count: int
    current_index: int | None = None
    current_item: LoopRelationshipReviewQueueItemResponse | None = None
    items: List[LoopRelationshipReviewQueueItemResponse]
    rerun_action: ContinuityRerunAction | None = None


class RelationshipReviewSessionActionRequest(BaseModel):
    """Run a relationship-review action inside a saved session."""

    loop_id: int
    candidate_loop_id: int
    candidate_relationship_type: Literal["related", "duplicate"]
    action_preset_id: int | None = None
    action_type: Literal["confirm", "dismiss"] | None = None
    relationship_type: Literal["suggested", "related", "duplicate"] | None = None


class RelationshipReviewSessionActionResponse(BaseModel):
    """Result of a relationship-review session action."""

    result: "RelationshipDecisionResponse"
    snapshot: RelationshipReviewSessionSnapshotResponse
    follow_through: ReviewFollowThroughResponse


class RelationshipReviewSessionUndoRequest(BaseModel):
    """Undo one exact saved relationship decision."""

    undo: ContinuityRelationshipDecisionUndoHandle


class RelationshipDecisionUndoResultResponse(BaseModel):
    """Result of restoring one relationship pair to its prior state."""

    loop_id: int
    candidate_loop_id: int
    restored_pair_state: ContinuityRelationshipDecisionPairState
    summary: str


class RelationshipReviewSessionUndoResponse(BaseModel):
    """Result of undoing one saved relationship-review session decision."""

    result: RelationshipDecisionUndoResultResponse
    snapshot: RelationshipReviewSessionSnapshotResponse
    follow_through: ReviewFollowThroughResponse


class RelationshipDecisionRequest(BaseModel):
    """Confirm or dismiss one relationship candidate."""

    relationship_type: Literal["related", "duplicate"]


class RelationshipDecisionResponse(BaseModel):
    """Result of confirming or dismissing one relationship candidate."""

    loop_id: int
    candidate_loop_id: int
    relationship_type: Literal["related", "duplicate"]
    link_state: Literal["active", "dismissed"]
