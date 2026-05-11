"""Life feed conversation schemas.

Purpose:
    Define the lightweight product-facing contract for the Life feed.

Responsibilities:
    - Accept one natural-language user message
    - Return captured/updated loops, simple grouped loop views, cleanup plans,
      memories, and undo handles without exposing internal orchestration

Non-scope:
    - Loop persistence schemas, chat runtime schemas, or memory CRUD schemas
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..constants import CHAT_MESSAGE_MAX
from .loops import LoopResponse
from .memory import MemoryResponse

LifeMessageMode = Literal["capture", "cleanup", "resurface", "preference"]
LifeState = Literal[
    "captured",
    "active",
    "needs_clarification",
    "prepared",
    "scheduled",
    "waiting",
    "blocked",
    "stale",
    "completed",
    "archived",
    "abandoned",
    "deleted",
]
LifeGroupName = Literal[
    "needs_attention_today",
    "quick_wins",
    "waiting_on_someone",
    "prepared_for_review",
    "stale_needs_decision",
    "upcoming",
    "ideas_not_tasks",
    "history",
]
LifeCleanupBucket = Literal[
    "close_candidate",
    "archive_candidate",
    "keep_active",
    "review_needed",
]
LifePreparedActionKind = Literal[
    "email_draft",
    "text_draft",
    "call_script",
    "checklist",
    "application_checklist",
    "decision_brief",
    "decision_recommendation",
    "errand_plan",
    "appointment_prep",
    "product_shortlist",
    "route_suggestion",
    "first_10_minutes",
    "summary",
]
LifePreparedActionRisk = Literal["internal", "external_low", "consequential"]
LifeExternalInputKind = Literal["link", "image", "audio", "file", "text"]


class LifeExternalInput(BaseModel):
    """Source evidence attached to one Life-feed message."""

    kind: LifeExternalInputKind
    label: str = Field(..., min_length=1, max_length=160)
    source_url: str | None = Field(default=None, max_length=2048)
    media_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = Field(default=None, ge=0, le=50 * 1024 * 1024)
    text: str | None = Field(default=None, max_length=1000)


class LifeMessageRequest(BaseModel):
    """One user message sent to the Life feed."""

    message: str = Field(..., min_length=1, max_length=CHAT_MESSAGE_MAX)
    external_inputs: list[LifeExternalInput] = Field(
        default_factory=list,
        max_length=10,
        description="Lightweight source/evidence metadata attached to the message.",
    )
    captured_at: str | None = Field(
        default=None,
        description="Optional client ISO8601 timestamp. Defaults to server UTC time.",
    )
    client_tz_offset_min: int = Field(
        default=0,
        description="Minutes offset from UTC at capture time.",
    )


class LifePreparedAction(BaseModel):
    """Draft, script, checklist, or brief prepared for review before action."""

    kind: LifePreparedActionKind
    title: str
    body: str
    risk_level: LifePreparedActionRisk = "internal"
    requires_approval: bool = True


class LifeClarification(BaseModel):
    """Optional contextual question that would materially improve a Life loop."""

    question: str
    loop_id: int | None = None
    clarification_id: int | None = None
    assumption: str | None = None
    rationale: str | None = None
    improves: list[str] = Field(default_factory=list)


class LifeClarificationAnswer(BaseModel):
    """Answer recorded against a previously requested Life clarification."""

    clarification_id: int
    loop_id: int
    question: str
    answer: str
    rationale: str | None = None


class LifeLoopItem(BaseModel):
    """Product-facing loop projection for Life surfaces."""

    loop: LoopResponse
    life_state: LifeState
    rationale: str | None = None
    prepared_next_action: str | None = None
    prepared_actions: list[LifePreparedAction] = Field(default_factory=list)


class LifeLoopGroup(BaseModel):
    """A plain-language group in the open loops or history view."""

    name: LifeGroupName
    title: str
    summary: str
    items: list[LifeLoopItem] = Field(default_factory=list)


class LifeUndoHandle(BaseModel):
    """Undo pointer for recent automatic Life cleanup."""

    loop_id: int
    expected_event_id: int
    event_type: str
    label: str


class LifeCleanupPlan(BaseModel):
    """Guided cleanup recommendation and optional applied cleanup results."""

    open_count: int
    recommendation: str
    close_candidates: list[LifeLoopItem] = Field(default_factory=list)
    archive_candidates: list[LifeLoopItem] = Field(default_factory=list)
    keep_active: list[LifeLoopItem] = Field(default_factory=list)
    review_needed: list[LifeLoopItem] = Field(default_factory=list)
    applied_automatic_cleanup: list[LifeLoopItem] = Field(default_factory=list)
    undo: list[LifeUndoHandle] = Field(default_factory=list)


class LifeMessageResponse(BaseModel):
    """Response from the Life feed."""

    mode: LifeMessageMode
    reply: str
    notify_user: bool = False
    notification_title: str | None = None
    notification_body: str | None = None
    captured: list[LifeLoopItem] = Field(default_factory=list)
    updated: list[LifeLoopItem] = Field(default_factory=list)
    clarifications: list[LifeClarification] = Field(default_factory=list)
    answered_clarifications: list[LifeClarificationAnswer] = Field(default_factory=list)
    memories: list[MemoryResponse] = Field(default_factory=list)
    groups: list[LifeLoopGroup] = Field(default_factory=list)
    cleanup: LifeCleanupPlan | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
