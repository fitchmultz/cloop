"""Loop metrics, duplicate, and merge schemas.

Purpose:
    Define operational metrics plus duplicate-detection and merge payloads.

Responsibilities:
    - Shape loop metrics responses and trend breakdowns
    - Serialize duplicate candidate and merge preview/result payloads
    - Keep workflow analytics separate from CRUD and review schemas

Non-scope:
    - Metrics collection or duplicate-resolution logic
    - Relationship-review session contracts
    - Core loop CRUD/search request models
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._shared import BaseModel


class LoopStatusCountsResponse(BaseModel):
    """Loop counts by status."""

    inbox: int
    actionable: int
    blocked: int
    scheduled: int
    completed: int
    dropped: int


class LoopOperationMetricsResponse(BaseModel):
    """Operation-level metrics for loop lifecycle events."""

    capture_count: int
    update_count: int
    transition_counts: Dict[str, int]
    reset_count: int


class ProjectMetricsResponse(BaseModel):
    """Per-project metrics breakdown."""

    project_id: int | None
    project_name: str | None
    total_loops: int
    open_loops: int
    completed_loops: int
    dropped_loops: int
    capture_count_window: int
    completion_count_window: int
    avg_age_open_hours: float | None


class TrendPointResponse(BaseModel):
    """Single data point in a trend series."""

    date: str
    capture_count: int
    completion_count: int
    open_count: int


class TrendMetricsResponse(BaseModel):
    """Time-series trend metrics."""

    window_days: int
    points: List[TrendPointResponse]
    total_captures: int
    total_completions: int
    avg_daily_captures: float
    avg_daily_completions: float


class LoopMetricsResponse(BaseModel):
    """Operational metrics for loop workflow health."""

    generated_at_utc: str
    total_loops: int
    status_counts: LoopStatusCountsResponse
    stale_open_count: int
    blocked_too_long_count: int
    no_next_action_count: int
    enrichment_pending_count: int
    enrichment_failed_count: int
    capture_count_24h: int
    completion_count_24h: int
    avg_age_open_hours: float | None
    operation_metrics: LoopOperationMetricsResponse | None = None

    # New optional fields
    project_breakdown: List[ProjectMetricsResponse] | None = None
    trend_metrics: TrendMetricsResponse | None = None


class DuplicateCandidateResponse(BaseModel):
    """A potential duplicate loop with similarity score."""

    loop_id: int
    score: float
    title: str | None
    raw_text_preview: str
    status: str
    captured_at_utc: str


class DuplicatesListResponse(BaseModel):
    """Response for listing duplicate candidates."""

    loop_id: int
    candidates: List[DuplicateCandidateResponse]


class MergePreviewResponse(BaseModel):
    """Preview of what a merge would produce."""

    surviving_loop_id: int
    duplicate_loop_id: int
    merged_title: str | None
    merged_summary: str | None
    merged_tags: List[str]
    merged_next_action: str | None
    field_conflicts: Dict[str, Dict[str, Any]]


class MergeRequest(BaseModel):
    """Request to merge a duplicate loop into another."""

    target_loop_id: int
    field_overrides: Dict[str, str | None] | None = None


class MergeResultResponse(BaseModel):
    """Result of a completed merge operation."""

    surviving_loop_id: int
    closed_loop_id: int
    merged_tags: List[str]
    fields_updated: List[str]
