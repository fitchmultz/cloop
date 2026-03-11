"""Loop metrics endpoints.

Purpose:
    HTTP endpoints for workflow-health and operational metrics.

Responsibilities:
    - Return loop metrics snapshots
    - Optionally include project and trend breakdowns

Non-scope:
    - Loop lifecycle mutations
    - Query/list/search or import/export behavior
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ... import db
from ...loops.metrics import compute_loop_metrics, get_operation_metrics
from ...schemas.loops import (
    LoopMetricsResponse,
    LoopOperationMetricsResponse,
    LoopStatusCountsResponse,
    ProjectMetricsResponse,
    TrendMetricsResponse,
    TrendPointResponse,
)
from ._common import SettingsDep

router = APIRouter()


@router.get("/metrics", response_model=LoopMetricsResponse)
def loop_metrics_endpoint(
    settings: SettingsDep,
    include_project: Annotated[bool, Query(description="Include project breakdown")] = False,
    include_trend: Annotated[bool, Query(description="Include trend metrics")] = False,
    trend_window_days: Annotated[int, Query(ge=1, le=90, description="Trend window in days")] = 7,
) -> LoopMetricsResponse:
    from ...loops.models import utc_now

    with db.core_connection(settings) as conn:
        metrics = compute_loop_metrics(
            conn=conn,
            now_utc=utc_now(),
            include_project_breakdown=include_project,
            include_trends=include_trend,
            trend_window_days=trend_window_days,
        )

    operation_metrics = None
    if settings.operation_metrics_enabled:
        op_metrics = get_operation_metrics().get_snapshot()
        operation_metrics = LoopOperationMetricsResponse(**op_metrics)

    response = LoopMetricsResponse(
        generated_at_utc=metrics.generated_at_utc,
        total_loops=metrics.total_loops,
        status_counts=LoopStatusCountsResponse(
            inbox=metrics.status_counts.inbox,
            actionable=metrics.status_counts.actionable,
            blocked=metrics.status_counts.blocked,
            scheduled=metrics.status_counts.scheduled,
            completed=metrics.status_counts.completed,
            dropped=metrics.status_counts.dropped,
        ),
        stale_open_count=metrics.stale_open_count,
        blocked_too_long_count=metrics.blocked_too_long_count,
        no_next_action_count=metrics.no_next_action_count,
        enrichment_pending_count=metrics.enrichment_pending_count,
        enrichment_failed_count=metrics.enrichment_failed_count,
        capture_count_24h=metrics.capture_count_24h,
        completion_count_24h=metrics.completion_count_24h,
        avg_age_open_hours=metrics.avg_age_open_hours,
        operation_metrics=operation_metrics,
    )

    if metrics.project_breakdown is not None:
        response.project_breakdown = [
            ProjectMetricsResponse(
                project_id=p.project_id,
                project_name=p.project_name,
                total_loops=p.total_loops,
                open_loops=p.open_loops,
                completed_loops=p.completed_loops,
                dropped_loops=p.dropped_loops,
                capture_count_window=p.capture_count_window,
                completion_count_window=p.completion_count_window,
                avg_age_open_hours=p.avg_age_open_hours,
            )
            for p in metrics.project_breakdown
        ]

    if metrics.trend_metrics is not None:
        response.trend_metrics = TrendMetricsResponse(
            window_days=metrics.trend_metrics.window_days,
            points=[
                TrendPointResponse(
                    date=pt.date,
                    capture_count=pt.capture_count,
                    completion_count=pt.completion_count,
                    open_count=pt.open_count,
                )
                for pt in metrics.trend_metrics.points
            ],
            total_captures=metrics.trend_metrics.total_captures,
            total_completions=metrics.trend_metrics.total_completions,
            avg_daily_captures=metrics.trend_metrics.avg_daily_captures,
            avg_daily_completions=metrics.trend_metrics.avg_daily_completions,
        )

    return response
