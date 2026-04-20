"""Backend-authored continuity workflow summaries."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from ...schemas._loops.continuity import (
    ContinuityDisplayCardResponse,
    ContinuityDisplayWorkingSetResponse,
    ContinuityLastSeenMarkerResponse,
    ContinuityLocationResponse,
    ContinuityOutcomeRecordResponse,
    ContinuityRerunAction,
    ContinuityUndoAction,
    ContinuityWorkflowSummaryResponse,
    ContinuityWorkflowSummarySignalsResponse,
    ResolvedContinuityTargetResponse,
    WorkflowThreadRefResponse,
)
from ._shared import _parse_timestamp
from .outcomes import _display_summary, _display_title, _location_identity

_DRIFT_SCORE: dict[str, int] = {
    "none": 0,
    "minor": 24,
    "moderate": 52,
    "major": 78,
    "replaced": 92,
    "gone": 100,
}


@dataclass(frozen=True, slots=True)
class _WorkflowSummaryCandidate:
    source: Literal["receipt", "recent"]
    rank: int
    ranking_signals: ContinuityWorkflowSummarySignalsResponse
    representative_outcome_id: int | None
    latest_outcome_id: int | None
    occurred_at_utc: str
    requested_resume_location: ContinuityLocationResponse | None
    resolved_resume: ResolvedContinuityTargetResponse
    display_title: str
    display_summary: str
    display_card: ContinuityDisplayCardResponse
    undo_action: ContinuityUndoAction | None
    rerun_action: ContinuityRerunAction | None
    working_set_id: int | None
    degraded: bool
    degraded_label: str | None
    workflow_thread: WorkflowThreadRefResponse


def _workflow_thread_or_ad_hoc(
    workflow_thread: WorkflowThreadRefResponse | None,
    resolved_resume: ResolvedContinuityTargetResponse,
    *,
    title: str,
    summary: str | None,
) -> WorkflowThreadRefResponse:
    if workflow_thread is not None:
        return workflow_thread
    return WorkflowThreadRefResponse(
        id=_location_identity(resolved_resume.resolved_location),
        kind="ad_hoc",
        title=title,
        summary=summary,
        parent_outcome_id=None,
    )


def _active_working_set_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT active_working_set_id FROM working_set_context WHERE singleton_id = 1"
    ).fetchone()
    if row is None or row["active_working_set_id"] is None:
        return None
    return int(row["active_working_set_id"])


def _working_set_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row["id"]): str(row["name"])
        for row in conn.execute("SELECT id, name FROM working_sets").fetchall()
    }


def _workflow_marker(
    markers: list[ContinuityLastSeenMarkerResponse],
    workflow_thread_id: str,
) -> ContinuityLastSeenMarkerResponse | None:
    return next(
        (
            marker
            for marker in markers
            if marker.entity_kind == "workflow_thread" and marker.entity_key == workflow_thread_id
        ),
        None,
    )


def _score_ranking_signals(
    *,
    severity: str,
    working_set_relevant: bool,
    downstream_ready: bool,
    degraded: bool,
    age_minutes: float,
) -> ContinuityWorkflowSummarySignalsResponse:
    recency_tie_breaker = max(0, 18 - int(age_minutes // 90))
    return ContinuityWorkflowSummarySignalsResponse(
        drift_severity=cast(Any, severity),
        drift_score=_DRIFT_SCORE[severity],
        working_set_relevant=working_set_relevant,
        downstream_ready=downstream_ready and not degraded,
        degraded=degraded,
        recency_tie_breaker=recency_tie_breaker,
    )


def _total_ranking_score(
    signals: ContinuityWorkflowSummarySignalsResponse,
    source: Literal["receipt", "recent"],
) -> int:
    source_score = 18 if source == "receipt" else 10
    return (
        signals.drift_score * 100
        + (240 if signals.working_set_relevant else 0)
        + (180 if signals.downstream_ready else -220)
        - (120 if signals.degraded else 0)
        + source_score
        + signals.recency_tie_breaker
    )


def _candidate_from_outcome(
    record: ContinuityOutcomeRecordResponse,
    *,
    active_working_set_id: int | None,
    markers: list[ContinuityLastSeenMarkerResponse],
    now: datetime,
) -> _WorkflowSummaryCandidate:
    thread = _workflow_thread_or_ad_hoc(
        record.workflow_thread,
        record.resolved_resume,
        title=_display_title(record),
        summary=_display_summary(record),
    )
    marker = _workflow_marker(markers, thread.id)
    last_seen_outcome_id = int(marker.observed_state.get("latestOutcomeId", 0)) if marker else 0
    source: Literal["receipt", "recent"] = (
        "receipt" if record.display_card.kind == "receipt" else "recent"
    )
    if record.degraded:
        severity = "gone"
    elif marker is None:
        severity = "moderate"
    elif record.id > last_seen_outcome_id:
        severity = "major" if record.id - last_seen_outcome_id >= 3 else "moderate"
    else:
        severity = "none"
    age_minutes = max(0.0, (now - _parse_timestamp(record.occurred_at_utc)).total_seconds() / 60.0)
    ranking_signals = _score_ranking_signals(
        severity=severity,
        working_set_relevant=(
            active_working_set_id is not None and record.working_set_id == active_working_set_id
        ),
        downstream_ready=not record.degraded,
        degraded=record.degraded,
        age_minutes=age_minutes,
    )
    return _WorkflowSummaryCandidate(
        source=source,
        rank=_total_ranking_score(ranking_signals, source),
        ranking_signals=ranking_signals,
        representative_outcome_id=record.id,
        latest_outcome_id=record.id,
        occurred_at_utc=record.occurred_at_utc,
        requested_resume_location=record.resolved_resume.requested_location,
        resolved_resume=record.resolved_resume,
        display_title=_display_title(record),
        display_summary=_display_summary(record),
        display_card=record.display_card,
        undo_action=record.undo_action,
        rerun_action=record.rerun_action,
        working_set_id=record.working_set_id,
        degraded=record.degraded,
        degraded_label=record.degraded_label,
        workflow_thread=thread,
    )


def _dedupe_candidates(
    candidates: list[_WorkflowSummaryCandidate],
) -> list[_WorkflowSummaryCandidate]:
    deduped: dict[str, _WorkflowSummaryCandidate] = {}
    for candidate in candidates:
        key = "::".join(
            [
                _location_identity(candidate.resolved_resume.resolved_location),
                candidate.display_title.strip().lower(),
                candidate.display_summary.strip().lower(),
            ]
        )
        existing = deduped.get(key)
        if (
            existing is None
            or candidate.rank > existing.rank
            or _parse_timestamp(candidate.occurred_at_utc)
            > _parse_timestamp(existing.occurred_at_utc)
        ):
            deduped[key] = candidate
    return list(deduped.values())


def _build_why_now(
    candidate: _WorkflowSummaryCandidate,
    *,
    outcome_count: int,
) -> list[str]:
    lines: list[str] = []
    severity = candidate.ranking_signals.drift_severity
    if severity == "replaced":
        lines.append("A newer workflow superseded the prior path you last saved.")
    elif severity == "gone":
        lines.append("The prior landing target disappeared, so this is the safest surviving path.")
    elif severity == "major":
        lines.append("This workflow changed materially since you last saw it.")
    elif severity == "moderate":
        lines.append("This workflow has fresh unseen movement.")
    elif severity == "minor":
        lines.append("This workflow drifted slightly and is still ready to resume.")
    else:
        lines.append("This is the highest deterministic ready-to-resume workflow.")
    if candidate.ranking_signals.working_set_relevant:
        lines.append("It stays inside the active working set.")
    if candidate.ranking_signals.downstream_ready:
        lines.append("A downstream surface is ready to open immediately.")
    if outcome_count > 1:
        lines.append(f"{outcome_count} related landed outcomes were grouped into one thread.")
    return lines


def _build_changed_since_last_seen(
    candidate: _WorkflowSummaryCandidate,
    *,
    outcome_count: int,
    marker: ContinuityLastSeenMarkerResponse | None,
    latest_outcome_id: int | None,
) -> list[str]:
    lines: list[str] = []
    if marker is None:
        lines.append("This workflow has never been seen from durable continuity.")
    previous_outcome_id = int(marker.observed_state.get("latestOutcomeId", 0)) if marker else 0
    if latest_outcome_id is not None and latest_outcome_id > previous_outcome_id:
        delta = latest_outcome_id - previous_outcome_id
        suffix = "s" if delta != 1 else ""
        lines.append(f"{delta} newer landed outcome{suffix} appeared since you last saw it.")
    if outcome_count > 1:
        lines.append(f"{outcome_count} outcomes are grouped under this workflow thread.")
    if candidate.degraded_label:
        lines.append(candidate.degraded_label)
    if not lines:
        lines.append(
            "No opaque heuristic changed this ranking; it still wins on deterministic readiness."
        )
    return lines


def _summary_working_set(
    candidate: _WorkflowSummaryCandidate,
    *,
    working_set_name: str | None,
) -> ContinuityDisplayWorkingSetResponse | None:
    existing = (
        candidate.display_card.handoff.working_set if candidate.display_card.handoff else None
    )
    if existing is not None:
        return existing
    if candidate.working_set_id is None or working_set_name is None:
        return None
    return ContinuityDisplayWorkingSetResponse(
        working_set_id=candidate.working_set_id,
        working_set_name=working_set_name,
        item_count=0,
        missing_item_count=0,
    )


def _summary_display_card(
    candidate: _WorkflowSummaryCandidate,
    *,
    working_set_name: str | None,
    outcome_preview_titles: list[str],
    why_now: list[str],
    changed_since_last_seen: list[str],
) -> ContinuityDisplayCardResponse:
    working_set = _summary_working_set(candidate, working_set_name=working_set_name)
    base = candidate.display_card
    handoff = None
    if base.handoff is not None:
        handoff = base.handoff.model_copy(
            update={
                "working_set": base.handoff.working_set or working_set,
            }
        )
    return base.model_copy(
        update={
            "title": candidate.display_title,
            "summary": candidate.display_summary,
            "handoff": handoff,
            "action_context_label": base.action_context_label or "Continue from here",
            "action_warning": candidate.degraded_label or base.action_warning,
        }
    )


def _build_workflow_summaries(
    *,
    conn: sqlite3.Connection,
    outcomes: list[ContinuityOutcomeRecordResponse],
    markers: list[ContinuityLastSeenMarkerResponse],
) -> list[ContinuityWorkflowSummaryResponse]:
    now = datetime.now(UTC)
    active_working_set_id = _active_working_set_id(conn)
    working_set_names = _working_set_names(conn)
    recent_candidates = _dedupe_candidates(
        [
            _candidate_from_outcome(
                outcome,
                active_working_set_id=active_working_set_id,
                markers=markers,
                now=now,
            )
            for outcome in outcomes
        ]
    )
    buckets: dict[str, list[_WorkflowSummaryCandidate]] = defaultdict(list)
    for candidate in recent_candidates:
        buckets[candidate.workflow_thread.id].append(candidate)
    summaries: list[ContinuityWorkflowSummaryResponse] = []
    for items in buckets.values():
        sorted_items = sorted(
            items,
            key=lambda item: (item.rank, _parse_timestamp(item.occurred_at_utc)),
            reverse=True,
        )
        representative = sorted_items[0]
        latest_by_time = max(
            items,
            key=lambda item: (_parse_timestamp(item.occurred_at_utc), item.latest_outcome_id or 0),
        )
        marker = _workflow_marker(markers, representative.workflow_thread.id)
        outcome_count = len(items)
        summary_rank = representative.rank + min(outcome_count, 4) * 8
        outcome_preview_titles = [item.display_title for item in sorted_items[:3]]
        working_set_name = (
            working_set_names.get(representative.working_set_id)
            if representative.working_set_id is not None
            else None
        )
        why_now = _build_why_now(representative, outcome_count=outcome_count)
        changed_since_last_seen = _build_changed_since_last_seen(
            representative,
            outcome_count=outcome_count,
            marker=marker,
            latest_outcome_id=latest_by_time.latest_outcome_id,
        )
        summaries.append(
            ContinuityWorkflowSummaryResponse(
                id=representative.workflow_thread.id,
                source=cast(Any, representative.source),
                rank=summary_rank,
                ranking_signals=representative.ranking_signals,
                workflow_thread=representative.workflow_thread,
                representative_outcome_id=representative.representative_outcome_id,
                latest_outcome_id=latest_by_time.latest_outcome_id,
                occurred_at_utc=representative.occurred_at_utc,
                outcome_count=outcome_count,
                outcome_preview_titles=outcome_preview_titles,
                requested_resume_location=representative.requested_resume_location,
                resolved_resume=representative.resolved_resume,
                display_title=representative.display_title,
                display_summary=representative.display_summary,
                display_card=_summary_display_card(
                    representative,
                    working_set_name=working_set_name,
                    outcome_preview_titles=outcome_preview_titles,
                    why_now=why_now,
                    changed_since_last_seen=changed_since_last_seen,
                ),
                undo_action=representative.undo_action,
                rerun_action=representative.rerun_action,
                working_set_id=representative.working_set_id,
                working_set_name=working_set_name,
                degraded=representative.degraded,
                degraded_label=representative.degraded_label,
                why_now=why_now,
                changed_since_last_seen=changed_since_last_seen,
                prior_state=None,
            )
        )
    return sorted(
        summaries,
        key=lambda item: (
            item.degraded,
            -item.rank,
            -_parse_timestamp(item.occurred_at_utc).timestamp(),
        ),
    )
