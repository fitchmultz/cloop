"""Loop comment schemas.

Purpose:
    Define threaded comment request/response models for loop discussions.

Responsibilities:
    - Validate comment create/update payloads
    - Serialize nested comment trees
    - Shape comment list envelopes

Non-scope:
    - Comment persistence or webhook side effects
    - Core loop CRUD/search schemas
    - Review-session or planning workflow models
"""

from __future__ import annotations

from typing import List

from ._shared import AUTHOR_MAX, COMMENT_BODY_MAX, BaseModel, Field


class LoopCommentCreateRequest(BaseModel):
    """Request to create a comment on a loop."""

    author: str = Field(..., min_length=1, max_length=AUTHOR_MAX, description="Comment author")
    body_md: str = Field(
        ..., min_length=1, max_length=COMMENT_BODY_MAX, description="Markdown body"
    )
    parent_id: int | None = Field(default=None, description="Parent comment ID for replies")


class LoopCommentUpdateRequest(BaseModel):
    """Request to update a comment."""

    body_md: str = Field(
        ..., min_length=1, max_length=COMMENT_BODY_MAX, description="Markdown body"
    )


class LoopCommentResponse(BaseModel):
    """Response for a single comment."""

    id: int
    loop_id: int
    parent_id: int | None
    author: str
    body_md: str
    created_at_utc: str
    updated_at_utc: str
    deleted_at_utc: str | None = None
    is_deleted: bool
    is_reply: bool
    replies: List["LoopCommentResponse"] = Field(default_factory=list)


class LoopCommentListResponse(BaseModel):
    """Response for listing comments on a loop."""

    loop_id: int
    comments: List[LoopCommentResponse]
    total_count: int
