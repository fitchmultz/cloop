"""Operator Now-feed response models.

Purpose:
    Define the canonical backend-ranked Now-feed schema shared by the web
    operator workspace and command palette.

Responsibilities:
    - Model one deterministic Now-feed item with launch and freshness metadata.
    - Keep the backend-authored ranking contract transport-safe and explicit.
    - Reuse the shared continuity shell-location contract for launches.

Non-scope:
    - Building or ranking Now-feed items.
    - Frontend card rendering behavior.
    - Persistence or workflow orchestration.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .continuity import ContinuityLocationResponse

NowFeedItemSource = Literal[
    "continuity",
    "planning_session",
    "relationship_review_session",
    "enrichment_review_session",
    "loop",
]
NowFeedDisplayKind = Literal["handoff", "decision", "mutation", "context"]
NowFeedDisplayTone = Literal["neutral", "progress", "attention", "caution"]


class NowFeedItemResponse(BaseModel):
    """One backend-ranked Now-feed item."""

    id: str
    rank: int
    source: NowFeedItemSource
    display_kind: NowFeedDisplayKind = "context"
    display_tone: NowFeedDisplayTone = "neutral"
    eyebrow: str
    title: str
    summary: str
    rationale: str
    reason_labels: list[str] = Field(default_factory=list)
    freshness_at_utc: str | None = None
    freshness_prefix: str | None = None
    action_label: str
    launch_location: ContinuityLocationResponse
    working_set_id: int | None = None


class NowFeedResponse(BaseModel):
    """Canonical backend-ranked operator Now feed."""

    generated_at_utc: str
    items: list[NowFeedItemResponse] = Field(default_factory=list)
