"""Working-set and focus-mode schemas for loops.

Purpose:
    Define durable working-set and active-focus request/response models for the
    operator shell.

Responsibilities:
    - Validate working-set CRUD payloads
    - Validate working-set membership and ordering payloads
    - Shape active working-set/focus-mode responses for the frontend shell

Scope:
    - Pydantic request/response models for working sets only

Usage:
    - Imported by loop routes and frontend OpenAPI generation via
      `cloop.schemas.loops`

Invariants/Assumptions:
    - Working-set item responses stay launch-ready for the shell
    - These models do not persist rows or execute workflow logic

Non-scope:
    - Persisting working-set rows or items
    - Shell-only rendering concerns
    - Planning/review/chat execution logic
"""

from __future__ import annotations

from typing import Any, Literal

from ._shared import SEARCH_QUERY_MAX, VIEW_DESCRIPTION_MAX, VIEW_NAME_MAX, BaseModel, Field

WorkingSetItemType = Literal[
    "loop",
    "planning_session",
    "relationship_review_session",
    "enrichment_review_session",
    "view",
    "memory",
    "query_anchor",
    "state_anchor",
]

WorkingSetShellState = Literal[
    "operator",
    "capture",
    "do",
    "decide",
    "plan",
    "review",
    "recall",
    "working_set",
]
WorkingSetRecallTool = Literal["chat", "memory", "rag"]
WorkingSetReviewFocus = Literal["planning", "relationship", "enrichment", "cohorts"]


class WorkingSetLaunchLocationResponse(BaseModel):
    """Frontend launch target for one working-set item or the set itself."""

    state: WorkingSetShellState
    recall_tool: WorkingSetRecallTool = "chat"
    review_focus: WorkingSetReviewFocus | None = None
    session_id: int | None = Field(default=None, ge=1)
    loop_id: int | None = Field(default=None, ge=1)
    view_id: int | None = Field(default=None, ge=1)
    memory_id: int | None = Field(default=None, ge=1)
    working_set_id: int | None = Field(default=None, ge=1)
    query: str | None = None


class WorkingSetItemCreateRequest(BaseModel):
    """Request to add one item to a working set."""

    item_type: WorkingSetItemType
    item_id: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkingSetItemResponse(BaseModel):
    """Resolved working-set item payload for shell rendering."""

    id: int
    item_type: WorkingSetItemType
    item_id: int | None = None
    kind_label: str
    label: str
    description: str
    status_label: str | None = None
    missing: bool = False
    position: int
    created_at_utc: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    launch: WorkingSetLaunchLocationResponse


class WorkingSetCreateRequest(BaseModel):
    """Request to create a working set."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class WorkingSetUpdateRequest(BaseModel):
    """Request to update working-set metadata."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class WorkingSetReorderRequest(BaseModel):
    """Request to reorder all items inside a working set."""

    ordered_item_ids: list[int] = Field(..., min_length=1)


class WorkingSetResponse(BaseModel):
    """Resolved working-set payload with ordered items and a session launch target."""

    id: int
    name: str
    description: str | None = None
    item_count: int
    missing_item_count: int
    last_activated_at_utc: str | None = None
    created_at_utc: str
    updated_at_utc: str
    items: list[WorkingSetItemResponse] = Field(default_factory=list)
    launch: WorkingSetLaunchLocationResponse


class WorkingSetContextUpdateRequest(BaseModel):
    """Request to change the active working set or focus mode."""

    active_working_set_id: int | None = Field(default=None, ge=1)
    focus_mode_enabled: bool


class WorkingSetContextResponse(BaseModel):
    """Current active working-set/focus-mode context."""

    active_working_set_id: int | None = None
    focus_mode_enabled: bool
    updated_at_utc: str
    active_working_set: WorkingSetResponse | None = None


class WorkingSetQueryAnchorRequest(BaseModel):
    """Request model for creating a query-anchor working-set item."""

    label: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX)
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)
    query: str = Field(..., min_length=1, max_length=SEARCH_QUERY_MAX)
    state: Literal["capture", "do", "review"] = "capture"
