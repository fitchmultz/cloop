"""Durable continuity storage.

Purpose:
    Persist and read backend-backed landed continuity outcomes, resume anchors,
    backend-authored workflow summaries, durable notification delivery
    state, recovery provenance, and durable recovery acknowledgements for
    cross-device operator continuity.

Responsibilities:
    - Record high-signal landed outcomes with deduplication.
    - Upsert durable planning and review resume anchors.
    - Resolve persisted resume targets against current durable resources.
    - Build backend-authored workflow summaries for frontend hydration.
    - Attach explicit successor provenance for stale or superseded resumable paths.
    - Persist durable notification delivery state and recovery acknowledgements.
    - Project canonical delivery decisions for debug inspection and push selection.

Non-scope:
    - Frontend ranking or rendering behavior.
    - Browser-local continuity baseline snapshots.

Usage:
    Imported by continuity HTTP routes.

Invariants/Assumptions:
    - Stored JSON payloads remain transport-safe and serializable.
    - Durable continuity prefers landed outcomes over launch points.
    - Missing working-set scope should degrade to the durable target before home.
    - Replacement provenance is computed on the backend and consumed as the
      canonical continuity recovery contract.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from .. import db
from ..schemas._loops.continuity import (
    ContinuityAnchorResponse,
    ContinuityAnchorsResponse,
    ContinuityAnchorUpsertRequest,
    ContinuityDeliveryDecisionResponse,
    ContinuityDeliveryInspectionChannel,
    ContinuityDeliveryInspectionResponse,
    ContinuityDeliveryReason,
    ContinuityLastSeenBatchUpsertRequest,
    ContinuityLastSeenMarkerResponse,
    ContinuityLocationResponse,
    ContinuityNotificationRecordResponse,
    ContinuityNotificationStateResponse,
    ContinuityNotificationStateUpsertRequest,
    ContinuityOutcomeRecordResponse,
    ContinuityOutcomeWriteRequest,
    ContinuityRecoveryAcknowledgementResponse,
    ContinuityRecoveryAcknowledgementUpsertRequest,
    ContinuitySchedulerPushDeliveryResponse,
    ContinuitySchedulerPushDeliveryStatus,
    ContinuitySnapshotResponse,
    ContinuitySuccessorTargetResponse,
    ContinuityTargetStatus,
    ContinuityWorkflowSummaryPriorStateResponse,
    ContinuityWorkflowSummaryResponse,
    ContinuityWorkflowSummarySignalsResponse,
    ContinuityWorkflowThreadKind,
    ResolvedContinuityTargetResponse,
    WorkflowThreadRefResponse,
)
from ..settings import Settings, get_settings

_DEDUPE_WINDOW_SECONDS = 15.0
_PUSH_UNSEEN_RESEND_COOLDOWN = timedelta(hours=6)
_PUSH_SEEN_RESEND_COOLDOWN = timedelta(hours=24)
_HOME_LOCATION = ContinuityLocationResponse(state="operator", recall_tool="chat")
_NotificationStateLifecycle = Literal[
    "active",
    "terminal",
    "expired",
    "retired",
    "orphaned",
]

_PUSH_DELIVERY_SCAN_FLOOR = 24
_PUSH_DELIVERY_SCAN_MULTIPLIER = 4


@dataclass(frozen=True, slots=True)
class _NotificationDeliveryDecision:
    record: ContinuityNotificationRecordResponse
    reason: ContinuityDeliveryReason
    resend_ready_at_utc: str | None = None
    latest_push_delivery: ContinuitySchedulerPushDeliveryResponse | None = None


@dataclass(frozen=True, slots=True)
class _ContinuityDeliveryReadWindow:
    limit: int
    scan_limit: int
    channel: ContinuityDeliveryInspectionChannel


@dataclass(frozen=True, slots=True)
class _ContinuityDeliveryContract:
    notification_records: list[ContinuityNotificationRecordResponse]
    decisions: list[_NotificationDeliveryDecision]


@dataclass(frozen=True, slots=True)
class _ContinuitySnapshotState:
    outcomes: list[ContinuityOutcomeRecordResponse]
    anchors: ContinuityAnchorsResponse
    workflow_summaries: list[ContinuityWorkflowSummaryResponse]
    last_seen_markers: list[ContinuityLastSeenMarkerResponse]
    recovery_acknowledgements: list[ContinuityRecoveryAcknowledgementResponse]
    notification_state_rows: list[Mapping[str, Any]]


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _dump_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, separators=(",", ":"), sort_keys=True)


def _load_json_map(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _location_from_value(value: Mapping[str, Any] | None) -> ContinuityLocationResponse | None:
    if value is None:
        return None
    if "state" not in value:
        return None
    return ContinuityLocationResponse.model_validate(value)


def _location_from_json(raw: str | None) -> ContinuityLocationResponse | None:
    payload = _load_json_map(raw)
    return _location_from_value(payload or None)


def _workflow_thread_from_row(row: Mapping[str, Any]) -> WorkflowThreadRefResponse:
    return WorkflowThreadRefResponse(
        id=str(row["workflow_thread_id"]),
        kind=cast(ContinuityWorkflowThreadKind, str(row["workflow_thread_kind"])),
        title=str(row["workflow_thread_title"]),
        summary=str(row["workflow_thread_summary"])
        if row["workflow_thread_summary"] is not None
        else None,
        parent_outcome_id=int(row["parent_outcome_id"])
        if row["parent_outcome_id"] is not None
        else None,
    )


def _working_set_exists(conn: sqlite3.Connection, working_set_id: int | None) -> bool:
    if working_set_id is None:
        return False
    row = conn.execute("SELECT 1 FROM working_sets WHERE id = ?", (working_set_id,)).fetchone()
    return row is not None


def _location_exists(conn: sqlite3.Connection, location: ContinuityLocationResponse) -> bool:
    if location.working_set_id is not None and location.state == "working_set":
        return _working_set_exists(conn, location.working_set_id)
    if location.state == "plan" and location.session_id is not None:
        row = conn.execute(
            "SELECT 1 FROM planning_sessions WHERE id = ?", (location.session_id,)
        ).fetchone()
        return row is not None
    if (
        location.state == "decide"
        and location.review_focus in {"relationship", "enrichment"}
        and location.session_id is not None
    ):
        row = conn.execute(
            "SELECT 1 FROM review_sessions WHERE id = ? AND review_kind = ?",
            (location.session_id, location.review_focus),
        ).fetchone()
        return row is not None
    if location.state == "do" and location.loop_id is not None:
        row = conn.execute("SELECT 1 FROM loops WHERE id = ?", (location.loop_id,)).fetchone()
        return row is not None
    if location.state == "capture" and location.view_id is not None:
        row = conn.execute("SELECT 1 FROM loop_views WHERE id = ?", (location.view_id,)).fetchone()
        return row is not None
    if (
        location.state == "recall"
        and location.recall_tool == "memory"
        and location.memory_id is not None
    ):
        row = conn.execute(
            "SELECT 1 FROM memory_entries WHERE id = ?", (location.memory_id,)
        ).fetchone()
        return row is not None
    return True


def _resolved_target(
    *,
    requested_location: ContinuityLocationResponse | None,
    resolved_location: ContinuityLocationResponse,
    status: ContinuityTargetStatus,
    message: str | None,
) -> ResolvedContinuityTargetResponse:
    return ResolvedContinuityTargetResponse(
        requested_location=requested_location,
        resolved_location=resolved_location,
        status=status,
        message=message,
        successor=None,
    )


def _resolve_location(
    conn: sqlite3.Connection,
    requested: ContinuityLocationResponse | None,
    launch: ContinuityLocationResponse | None,
) -> ResolvedContinuityTargetResponse:
    if requested is None:
        return _resolved_target(
            requested_location=None,
            resolved_location=_HOME_LOCATION,
            status="home_fallback",
            message="Original landed target is unavailable, so continuity falls back to home.",
        )

    if requested.working_set_id is not None and not _working_set_exists(
        conn, requested.working_set_id
    ):
        unscoped = requested.model_copy(update={"working_set_id": None})
        if _location_exists(conn, unscoped):
            return _resolved_target(
                requested_location=requested,
                resolved_location=unscoped,
                status="working_set_scope_removed",
                message=(
                    "Working-set scope no longer exists, so continuity falls back "
                    "to the durable target."
                ),
            )
        if launch is not None and _location_exists(conn, launch):
            return _resolved_target(
                requested_location=requested,
                resolved_location=launch,
                status="launch_fallback",
                message=(
                    "Working-set scope and landed target are gone, so continuity "
                    "falls back to the launch workflow."
                ),
            )
        return _resolved_target(
            requested_location=requested,
            resolved_location=_HOME_LOCATION,
            status="home_fallback",
            message=(
                "Working-set scope and landed target are gone, so continuity falls back to home."
            ),
        )

    if _location_exists(conn, requested):
        return _resolved_target(
            requested_location=requested,
            resolved_location=requested,
            status="ok",
            message=None,
        )

    if launch is not None and _location_exists(conn, launch):
        return _resolved_target(
            requested_location=requested,
            resolved_location=launch,
            status="launch_fallback",
            message=(
                "Original landed target is unavailable, so continuity falls back "
                "to the launch workflow."
            ),
        )

    return _resolved_target(
        requested_location=requested,
        resolved_location=_HOME_LOCATION,
        status="home_fallback",
        message="Original landed target is unavailable, so continuity falls back to home.",
    )


def _anchor_from_row(row: Mapping[str, Any]) -> ContinuityAnchorResponse:
    return ContinuityAnchorResponse(
        kind=cast(Any, str(row["anchor_kind"])),
        review_focus=cast(Any, str(row["review_focus"])),
        session_id=int(row["session_id"]),
        visited_at_utc=str(row["visited_at_utc"]),
        launch_location=_location_from_json(row["launch_location_json"]),
        resume_location=_location_from_json(row["resume_location_json"]),
        resolved_resume=None,
        outcome_title=str(row["outcome_title"]) if row["outcome_title"] is not None else None,
        outcome_summary=str(row["outcome_summary"]) if row["outcome_summary"] is not None else None,
        working_set_id=int(row["working_set_id"]) if row["working_set_id"] is not None else None,
        workflow_thread_id=str(row["workflow_thread_id"])
        if row["workflow_thread_id"] is not None
        else None,
        degraded=False,
        degraded_label=None,
        metadata=_load_json_map(row["metadata_json"]),
    )


def _last_seen_marker_from_row(row: Mapping[str, Any]) -> ContinuityLastSeenMarkerResponse:
    return ContinuityLastSeenMarkerResponse(
        entity_kind=cast(Any, str(row["entity_kind"])),
        entity_key=str(row["entity_key"]),
        observed_at_utc=str(row["observed_at_utc"]),
        observed_fingerprint=str(row["observed_fingerprint"]),
        working_set_id=int(row["working_set_id"]) if row["working_set_id"] is not None else None,
        workflow_thread_id=str(row["workflow_thread_id"])
        if row["workflow_thread_id"] is not None
        else None,
        observed_state=_load_json_map(row["observed_state_json"]),
        metadata=_load_json_map(row["metadata_json"]),
    )


def _recovery_ack_from_row(row: Mapping[str, Any]) -> ContinuityRecoveryAcknowledgementResponse:
    return ContinuityRecoveryAcknowledgementResponse(
        recovery_key=str(row["recovery_key"]),
        acknowledged_at_utc=str(row["acknowledged_at_utc"]),
        metadata=_load_json_map(row["metadata_json"]),
    )


def _notification_state_from_row(row: Mapping[str, Any]) -> ContinuityNotificationStateResponse:
    return ContinuityNotificationStateResponse(
        inboxed_at_utc=str(row["inboxed_at_utc"]) if row["inboxed_at_utc"] is not None else None,
        seen_at_utc=str(row["seen_at_utc"]) if row["seen_at_utc"] is not None else None,
        acknowledged_at_utc=str(row["acknowledged_at_utc"])
        if row["acknowledged_at_utc"] is not None
        else None,
        suppressed_until_utc=str(row["suppressed_until_utc"])
        if row["suppressed_until_utc"] is not None
        else None,
    )


def _outcome_from_row(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
) -> ContinuityOutcomeRecordResponse:
    launch_location = _location_from_json(row["launch_location_json"])
    resume_location = _location_from_json(row["resume_location_json"])
    resolved_resume = _resolve_location(conn, resume_location, launch_location)
    degraded = resolved_resume.status != "ok"
    return ContinuityOutcomeRecordResponse(
        id=int(row["id"]),
        kind=str(row["kind"]),
        label=str(row["label"]),
        description=str(row["description"]),
        occurred_at_utc=str(row["occurred_at_utc"]),
        launch_location=launch_location,
        outcome_card=_load_json_map(row["outcome_json"]),
        resume_location=resume_location,
        resolved_resume=resolved_resume,
        workflow_thread=_workflow_thread_from_row(row),
        working_set_id=int(row["working_set_id"]) if row["working_set_id"] is not None else None,
        degraded=degraded,
        degraded_label=resolved_resume.message if degraded else None,
        metadata=_load_json_map(row["metadata_json"]),
    )


def _display_title(record: ContinuityOutcomeRecordResponse) -> str:
    if isinstance(record.outcome_card, dict):
        title = record.outcome_card.get("title")
        if isinstance(title, str) and title.strip():
            return title
    return record.label


def _display_summary(record: ContinuityOutcomeRecordResponse) -> str:
    if isinstance(record.outcome_card, dict):
        summary = record.outcome_card.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary
    return record.description


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
    source: Literal["receipt", "recent", "anchor"]
    rank: int
    ranking_signals: ContinuityWorkflowSummarySignalsResponse
    representative_outcome_id: int | None
    latest_outcome_id: int | None
    occurred_at_utc: str
    requested_resume_location: ContinuityLocationResponse | None
    resolved_resume: ResolvedContinuityTargetResponse
    display_title: str
    display_summary: str
    working_set_id: int | None
    degraded: bool
    degraded_label: str | None
    workflow_thread: WorkflowThreadRefResponse


def _location_identity(location: ContinuityLocationResponse | None) -> str:
    if location is None:
        return "location:null"
    return "|".join(
        [
            location.state,
            location.recall_tool,
            location.review_focus or "-",
            str(location.session_id) if location.session_id is not None else "-",
            str(location.loop_id) if location.loop_id is not None else "-",
            str(location.view_id) if location.view_id is not None else "-",
            str(location.memory_id) if location.memory_id is not None else "-",
            str(location.working_set_id) if location.working_set_id is not None else "-",
            location.query or "-",
        ]
    )


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


def _anchor_label(anchor: ContinuityAnchorResponse) -> str:
    if anchor.kind == "planning":
        return f"Planning session #{anchor.session_id}"
    return f"{anchor.review_focus} queue #{anchor.session_id}"


def _anchor_display_title(anchor: ContinuityAnchorResponse) -> str:
    return anchor.outcome_title or _anchor_label(anchor)


def _anchor_display_summary(anchor: ContinuityAnchorResponse) -> str:
    return anchor.outcome_summary or "Resume the last saved landed workflow state."


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


def _outcome_family(
    workflow_thread: WorkflowThreadRefResponse | None,
    resolved_location: ContinuityLocationResponse,
) -> Literal["planning", "review"] | None:
    if workflow_thread and workflow_thread.kind == "planning_checkpoint":
        return "planning"
    if workflow_thread and workflow_thread.kind == "review_session":
        return "review"
    if resolved_location.state == "plan":
        return "planning"
    if resolved_location.state == "decide" and resolved_location.review_focus in {
        "relationship",
        "enrichment",
    }:
        return "review"
    return None


def _prior_anchor_for_candidate(
    candidate: _WorkflowSummaryCandidate,
    anchors: ContinuityAnchorsResponse,
) -> ContinuityAnchorResponse | None:
    family = _outcome_family(candidate.workflow_thread, candidate.resolved_resume.resolved_location)
    if family == "planning":
        return anchors.planning
    if family == "review":
        return anchors.review
    return None


def _supersedes_durable_anchor(
    candidate: _WorkflowSummaryCandidate,
    anchors: ContinuityAnchorsResponse,
) -> bool:
    anchor = _prior_anchor_for_candidate(candidate, anchors)
    if anchor is None:
        return False
    if _parse_timestamp(candidate.occurred_at_utc) < _parse_timestamp(anchor.visited_at_utc):
        return False
    if anchor.workflow_thread_id and candidate.workflow_thread.id:
        return anchor.workflow_thread_id != candidate.workflow_thread.id
    return _location_identity(
        anchor.resume_location or anchor.launch_location
    ) != _location_identity(candidate.resolved_resume.resolved_location)


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
    source: Literal["receipt", "recent", "anchor"],
) -> int:
    source_score = 18 if source == "receipt" else 10 if source == "recent" else 4
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
    anchors: ContinuityAnchorsResponse,
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
    source: Literal["receipt", "recent", "anchor"] = (
        "receipt"
        if isinstance(record.outcome_card, dict) and record.outcome_card.get("kind") == "receipt"
        else "recent"
    )
    if record.degraded:
        severity = "gone"
    elif _supersedes_durable_anchor(
        _WorkflowSummaryCandidate(
            source=source,
            rank=0,
            ranking_signals=_score_ranking_signals(
                severity="none",
                working_set_relevant=False,
                downstream_ready=True,
                degraded=False,
                age_minutes=0,
            ),
            representative_outcome_id=record.id,
            latest_outcome_id=record.id,
            occurred_at_utc=record.occurred_at_utc,
            requested_resume_location=record.resolved_resume.requested_location,
            resolved_resume=record.resolved_resume,
            display_title=_display_title(record),
            display_summary=_display_summary(record),
            working_set_id=record.working_set_id,
            degraded=record.degraded,
            degraded_label=record.degraded_label,
            workflow_thread=thread,
        ),
        anchors,
    ):
        severity = "replaced"
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
        working_set_id=record.working_set_id,
        degraded=record.degraded,
        degraded_label=record.degraded_label,
        workflow_thread=thread,
    )


def _candidate_from_anchor(
    anchor: ContinuityAnchorResponse,
    *,
    active_working_set_id: int | None,
    anchors: ContinuityAnchorsResponse,
    markers: list[ContinuityLastSeenMarkerResponse],
    now: datetime,
) -> _WorkflowSummaryCandidate:
    if anchor.resolved_resume is None:
        raise RuntimeError("Resolved continuity anchors are required before building summaries.")
    thread = _workflow_thread_or_ad_hoc(
        _anchor_thread_ref(anchor),
        anchor.resolved_resume,
        title=_anchor_display_title(anchor),
        summary=_anchor_display_summary(anchor),
    )
    marker = _workflow_marker(markers, thread.id)
    if anchor.degraded:
        severity = "gone"
    elif _supersedes_durable_anchor(
        _WorkflowSummaryCandidate(
            source="anchor",
            rank=0,
            ranking_signals=_score_ranking_signals(
                severity="none",
                working_set_relevant=False,
                downstream_ready=True,
                degraded=False,
                age_minutes=0,
            ),
            representative_outcome_id=None,
            latest_outcome_id=None,
            occurred_at_utc=anchor.visited_at_utc,
            requested_resume_location=anchor.resolved_resume.requested_location,
            resolved_resume=anchor.resolved_resume,
            display_title=_anchor_display_title(anchor),
            display_summary=_anchor_display_summary(anchor),
            working_set_id=anchor.working_set_id,
            degraded=anchor.degraded,
            degraded_label=anchor.degraded_label,
            workflow_thread=thread,
        ),
        anchors,
    ):
        severity = "replaced"
    elif marker is None:
        severity = "minor"
    else:
        severity = "none"
    age_minutes = max(0.0, (now - _parse_timestamp(anchor.visited_at_utc)).total_seconds() / 60.0)
    ranking_signals = _score_ranking_signals(
        severity=severity,
        working_set_relevant=(
            active_working_set_id is not None and anchor.working_set_id == active_working_set_id
        ),
        downstream_ready=not anchor.degraded,
        degraded=anchor.degraded,
        age_minutes=age_minutes,
    )
    return _WorkflowSummaryCandidate(
        source="anchor",
        rank=_total_ranking_score(ranking_signals, "anchor"),
        ranking_signals=ranking_signals,
        representative_outcome_id=None,
        latest_outcome_id=None,
        occurred_at_utc=anchor.visited_at_utc,
        requested_resume_location=anchor.resolved_resume.requested_location,
        resolved_resume=anchor.resolved_resume,
        display_title=_anchor_display_title(anchor),
        display_summary=_anchor_display_summary(anchor),
        working_set_id=anchor.working_set_id,
        degraded=anchor.degraded,
        degraded_label=anchor.degraded_label,
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


def _build_prior_state(
    candidate: _WorkflowSummaryCandidate,
    anchors: ContinuityAnchorsResponse,
) -> ContinuityWorkflowSummaryPriorStateResponse | None:
    anchor = _prior_anchor_for_candidate(candidate, anchors)
    if anchor is None:
        return None
    anchor_thread_id = anchor.workflow_thread_id
    same_thread = anchor_thread_id is not None and anchor_thread_id == candidate.workflow_thread.id
    same_location = _location_identity(
        anchor.resume_location or anchor.launch_location
    ) == _location_identity(candidate.resolved_resume.resolved_location)
    if same_thread or same_location:
        return None
    if anchor.resolved_resume and anchor.resolved_resume.successor is not None:
        return ContinuityWorkflowSummaryPriorStateResponse(
            kind="gone" if anchor.degraded else "replaced",
            title=anchor.outcome_title or "Prior path",
            summary=anchor.resolved_resume.successor.message
            or (
                f"{anchor.outcome_title or 'Prior path'} was superseded by "
                f"{anchor.resolved_resume.successor.title}."
            ),
        )
    if anchor.degraded:
        return ContinuityWorkflowSummaryPriorStateResponse(
            kind="gone",
            title=anchor.outcome_title or "Prior path",
            summary=anchor.degraded_label or "The prior primary path is no longer available.",
        )
    return None


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


def _build_workflow_summaries(
    *,
    conn: sqlite3.Connection,
    outcomes: list[ContinuityOutcomeRecordResponse],
    anchors: ContinuityAnchorsResponse,
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
                anchors=anchors,
                markers=markers,
                now=now,
            )
            for outcome in outcomes
        ]
    )
    recent_location_keys = {
        _location_identity(candidate.resolved_resume.resolved_location)
        for candidate in recent_candidates
    }
    anchor_candidates = [
        _candidate_from_anchor(
            anchor,
            active_working_set_id=active_working_set_id,
            anchors=anchors,
            markers=markers,
            now=now,
        )
        for anchor in (anchors.planning, anchors.review)
        if anchor is not None and anchor.resolved_resume is not None
    ]
    combined = recent_candidates + [
        candidate
        for candidate in anchor_candidates
        if _location_identity(candidate.resolved_resume.resolved_location)
        not in recent_location_keys
    ]
    buckets: dict[str, list[_WorkflowSummaryCandidate]] = defaultdict(list)
    for candidate in combined:
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
        prior_state = _build_prior_state(representative, anchors)
        outcome_count = len(items)
        summary_rank = representative.rank + min(outcome_count, 4) * 8
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
                outcome_preview_titles=[item.display_title for item in sorted_items[:3]],
                requested_resume_location=representative.requested_resume_location,
                resolved_resume=representative.resolved_resume,
                display_title=representative.display_title,
                display_summary=representative.display_summary,
                working_set_id=representative.working_set_id,
                working_set_name=working_set_names.get(representative.working_set_id)
                if representative.working_set_id is not None
                else None,
                degraded=representative.degraded,
                degraded_label=representative.degraded_label,
                why_now=_build_why_now(representative, outcome_count=outcome_count),
                changed_since_last_seen=_build_changed_since_last_seen(
                    representative,
                    outcome_count=outcome_count,
                    marker=marker,
                    latest_outcome_id=latest_by_time.latest_outcome_id,
                ),
                prior_state=prior_state,
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


def _replacement_family(
    workflow_thread: WorkflowThreadRefResponse | None,
    requested_location: ContinuityLocationResponse | None,
    resolved_location: ContinuityLocationResponse,
) -> str | None:
    location = requested_location or resolved_location
    if workflow_thread and workflow_thread.kind == "planning_checkpoint":
        return "planning"
    if workflow_thread and workflow_thread.kind == "review_session":
        return "review"
    if location.state == "plan":
        return "planning"
    if location.state == "decide" and location.review_focus in {"relationship", "enrichment"}:
        return "review"
    return None


def _replacement_identity(
    workflow_thread: WorkflowThreadRefResponse | None,
    requested_location: ContinuityLocationResponse | None,
    resolved_location: ContinuityLocationResponse,
) -> str:
    if workflow_thread is not None:
        return f"thread:{workflow_thread.id}"
    location = requested_location or resolved_location
    return _dump_json(location)


def _is_viable_successor(status: ContinuityTargetStatus) -> bool:
    return status in {"ok", "working_set_scope_removed", "launch_fallback"}


def _successor_source(
    outcomes: list[ContinuityOutcomeRecordResponse],
    *,
    workflow_thread: WorkflowThreadRefResponse | None,
    requested_location: ContinuityLocationResponse | None,
    resolved_location: ContinuityLocationResponse,
    visited_at_utc: str | None = None,
) -> ContinuityOutcomeRecordResponse | None:
    family = _replacement_family(
        workflow_thread,
        requested_location,
        resolved_location,
    )
    identity = _replacement_identity(
        workflow_thread,
        requested_location,
        resolved_location,
    )
    if family is None:
        return None
    visited_at = _parse_timestamp(visited_at_utc) if visited_at_utc is not None else None
    return next(
        (
            item
            for item in outcomes
            if _replacement_family(
                item.workflow_thread,
                item.resolved_resume.requested_location,
                item.resolved_resume.resolved_location,
            )
            == family
            and _replacement_identity(
                item.workflow_thread,
                item.resolved_resume.requested_location,
                item.resolved_resume.resolved_location,
            )
            != identity
            and _is_viable_successor(item.resolved_resume.status)
            and (visited_at is None or _parse_timestamp(item.occurred_at_utc) >= visited_at)
        ),
        None,
    )


def _build_successor(
    record: ContinuityOutcomeRecordResponse,
    prior_title: str,
) -> ContinuitySuccessorTargetResponse:
    successor_title = _display_title(record)
    return ContinuitySuccessorTargetResponse(
        kind="replacement",
        outcome_id=record.id,
        title=successor_title,
        summary=_display_summary(record),
        workflow_thread=record.workflow_thread,
        requested_location=record.resolved_resume.requested_location,
        resolved_location=record.resolved_resume.resolved_location,
        status=record.resolved_resume.status,
        message=f"{prior_title} was superseded by {successor_title}.",
    )


def _attach_successors(
    outcomes: list[ContinuityOutcomeRecordResponse],
) -> list[ContinuityOutcomeRecordResponse]:
    ordered = sorted(
        outcomes,
        key=lambda item: (_parse_timestamp(item.occurred_at_utc), item.id),
        reverse=True,
    )
    enriched: list[ContinuityOutcomeRecordResponse] = []

    for index, candidate in enumerate(ordered):
        successor_source = _successor_source(
            ordered[:index],
            workflow_thread=candidate.workflow_thread,
            requested_location=candidate.resolved_resume.requested_location,
            resolved_location=candidate.resolved_resume.resolved_location,
        )
        successor = (
            _build_successor(successor_source, _display_title(candidate))
            if successor_source is not None
            else None
        )
        enriched.append(
            candidate.model_copy(
                update={
                    "resolved_resume": candidate.resolved_resume.model_copy(
                        update={"successor": successor}
                    )
                }
            )
        )

    return enriched


def _anchor_thread_ref(anchor: ContinuityAnchorResponse) -> WorkflowThreadRefResponse | None:
    if not anchor.workflow_thread_id:
        return None
    kind: ContinuityWorkflowThreadKind = (
        "planning_checkpoint" if anchor.kind == "planning" else "review_session"
    )
    return WorkflowThreadRefResponse(
        id=anchor.workflow_thread_id,
        kind=kind,
        title=anchor.outcome_title or f"{anchor.kind.title()} #{anchor.session_id}",
        summary=anchor.outcome_summary,
        parent_outcome_id=None,
    )


def _resolve_anchor(
    conn: sqlite3.Connection,
    anchor: ContinuityAnchorResponse,
    outcomes: list[ContinuityOutcomeRecordResponse],
) -> ContinuityAnchorResponse:
    resolved_resume = _resolve_location(conn, anchor.resume_location, anchor.launch_location)
    thread_ref = _anchor_thread_ref(anchor)
    successor_source = _successor_source(
        outcomes,
        workflow_thread=thread_ref,
        requested_location=resolved_resume.requested_location,
        resolved_location=resolved_resume.resolved_location,
        visited_at_utc=anchor.visited_at_utc,
    )
    resolved_resume = resolved_resume.model_copy(
        update={
            "successor": _build_successor(
                successor_source,
                anchor.outcome_title or f"{anchor.kind.title()} #{anchor.session_id}",
            )
            if successor_source is not None
            else None
        }
    )
    degraded = resolved_resume.status != "ok"

    return anchor.model_copy(
        update={
            "resolved_resume": resolved_resume,
            "degraded": degraded,
            "degraded_label": resolved_resume.message if degraded else None,
        }
    )


def record_continuity_outcome(
    payload: ContinuityOutcomeWriteRequest,
    *,
    settings: Settings | None = None,
) -> int:
    """Persist one high-signal landed continuity outcome."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        latest = conn.execute(
            """
            SELECT id, occurred_at_utc
            FROM continuity_outcomes
            WHERE dedupe_key = ?
            ORDER BY occurred_at_utc DESC, id DESC
            LIMIT 1
            """,
            (payload.dedupe_key,),
        ).fetchone()

        launch_json = (
            _dump_json(payload.launch_location) if payload.launch_location is not None else None
        )
        outcome_json = _dump_json(payload.outcome_card)
        resume_json = (
            _dump_json(payload.resume_location) if payload.resume_location is not None else None
        )
        metadata_json = _dump_json(payload.metadata)

        if latest is not None:
            age = abs(
                (
                    _parse_timestamp(payload.occurred_at_utc)
                    - _parse_timestamp(str(latest["occurred_at_utc"]))
                ).total_seconds()
            )
            if age <= _DEDUPE_WINDOW_SECONDS:
                conn.execute(
                    """
                    UPDATE continuity_outcomes
                    SET
                        kind = ?,
                        label = ?,
                        description = ?,
                        occurred_at_utc = ?,
                        launch_location_json = ?,
                        outcome_json = ?,
                        resume_location_json = ?,
                        working_set_id = ?,
                        workflow_thread_id = ?,
                        workflow_thread_kind = ?,
                        workflow_thread_title = ?,
                        workflow_thread_summary = ?,
                        parent_outcome_id = ?,
                        source_surface = ?,
                        signal_level = ?,
                        metadata_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        payload.kind,
                        payload.label,
                        payload.description,
                        payload.occurred_at_utc,
                        launch_json,
                        outcome_json,
                        resume_json,
                        payload.working_set_id,
                        payload.workflow_thread.id,
                        payload.workflow_thread.kind,
                        payload.workflow_thread.title,
                        payload.workflow_thread.summary,
                        payload.workflow_thread.parent_outcome_id,
                        payload.source_surface,
                        payload.signal_level,
                        metadata_json,
                        int(latest["id"]),
                    ),
                )
                conn.commit()
                return int(latest["id"])

        cursor = conn.execute(
            """
            INSERT INTO continuity_outcomes (
                kind,
                label,
                description,
                occurred_at_utc,
                launch_location_json,
                outcome_json,
                resume_location_json,
                working_set_id,
                workflow_thread_id,
                workflow_thread_kind,
                workflow_thread_title,
                workflow_thread_summary,
                parent_outcome_id,
                dedupe_key,
                source_surface,
                signal_level,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.kind,
                payload.label,
                payload.description,
                payload.occurred_at_utc,
                launch_json,
                outcome_json,
                resume_json,
                payload.working_set_id,
                payload.workflow_thread.id,
                payload.workflow_thread.kind,
                payload.workflow_thread.title,
                payload.workflow_thread.summary,
                payload.workflow_thread.parent_outcome_id,
                payload.dedupe_key,
                payload.source_surface,
                payload.signal_level,
                metadata_json,
            ),
        )
        conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("continuity_outcomes insert did not return a row id")
        return int(cursor.lastrowid)


def upsert_continuity_anchor(
    payload: ContinuityAnchorUpsertRequest,
    *,
    settings: Settings | None = None,
) -> None:
    """Upsert one durable planning or review resume anchor."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        conn.execute(
            """
            INSERT INTO continuity_resume_anchors (
                anchor_kind,
                review_focus,
                session_id,
                visited_at_utc,
                launch_location_json,
                resume_location_json,
                outcome_title,
                outcome_summary,
                working_set_id,
                workflow_thread_id,
                metadata_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(anchor_kind) DO UPDATE SET
                review_focus = excluded.review_focus,
                session_id = excluded.session_id,
                visited_at_utc = excluded.visited_at_utc,
                launch_location_json = excluded.launch_location_json,
                resume_location_json = excluded.resume_location_json,
                outcome_title = excluded.outcome_title,
                outcome_summary = excluded.outcome_summary,
                working_set_id = excluded.working_set_id,
                workflow_thread_id = excluded.workflow_thread_id,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                payload.anchor_kind,
                payload.review_focus,
                payload.session_id,
                payload.visited_at_utc,
                _dump_json(payload.launch_location)
                if payload.launch_location is not None
                else None,
                _dump_json(payload.resume_location)
                if payload.resume_location is not None
                else None,
                payload.outcome_title,
                payload.outcome_summary,
                payload.working_set_id,
                payload.workflow_thread_id,
                _dump_json(payload.metadata),
            ),
        )
        conn.commit()


def upsert_continuity_last_seen_markers(
    payload: ContinuityLastSeenBatchUpsertRequest,
    *,
    settings: Settings | None = None,
) -> None:
    """Upsert durable last-seen markers for continuity-relevant entities."""
    settings = settings or get_settings()
    if not payload.markers:
        return
    with db.core_connection(settings) as conn:
        conn.executemany(
            """
            INSERT INTO continuity_last_seen_markers (
                entity_kind,
                entity_key,
                observed_at_utc,
                working_set_id,
                workflow_thread_id,
                observed_fingerprint,
                observed_state_json,
                metadata_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(entity_kind, entity_key) DO UPDATE SET
                observed_at_utc = excluded.observed_at_utc,
                working_set_id = excluded.working_set_id,
                workflow_thread_id = excluded.workflow_thread_id,
                observed_fingerprint = excluded.observed_fingerprint,
                observed_state_json = excluded.observed_state_json,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    marker.entity_kind,
                    marker.entity_key,
                    marker.observed_at_utc,
                    marker.working_set_id,
                    marker.workflow_thread_id,
                    marker.observed_fingerprint,
                    _dump_json(marker.observed_state),
                    _dump_json(marker.metadata),
                )
                for marker in payload.markers
            ],
        )
        conn.commit()


def upsert_continuity_recovery_acknowledgement(
    payload: ContinuityRecoveryAcknowledgementUpsertRequest,
    *,
    settings: Settings | None = None,
) -> None:
    """Upsert one durable continuity recovery acknowledgement."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        conn.execute(
            """
            INSERT INTO continuity_recovery_acknowledgements (
                recovery_key,
                acknowledged_at_utc,
                metadata_json,
                updated_at
            ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(recovery_key) DO UPDATE SET
                acknowledged_at_utc = excluded.acknowledged_at_utc,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                payload.recovery_key,
                payload.acknowledged_at_utc,
                _dump_json(payload.metadata),
            ),
        )
        conn.commit()


def upsert_continuity_notification_state(
    notification_id: str,
    payload: ContinuityNotificationStateUpsertRequest,
    *,
    settings: Settings | None = None,
) -> None:
    """Upsert durable delivery state for one canonical notification record."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        existing_row = conn.execute(
            "SELECT * FROM continuity_notification_states WHERE notification_id = ?",
            (notification_id,),
        ).fetchone()
        existing = (
            _notification_state_from_row(existing_row)
            if existing_row is not None
            else ContinuityNotificationStateResponse()
        )
        fields = payload.model_fields_set
        merged = ContinuityNotificationStateResponse(
            inboxed_at_utc=(
                payload.inboxed_at_utc if "inboxed_at_utc" in fields else existing.inboxed_at_utc
            ),
            seen_at_utc=payload.seen_at_utc if "seen_at_utc" in fields else existing.seen_at_utc,
            acknowledged_at_utc=(
                payload.acknowledged_at_utc
                if "acknowledged_at_utc" in fields
                else existing.acknowledged_at_utc
            ),
            suppressed_until_utc=(
                payload.suppressed_until_utc
                if "suppressed_until_utc" in fields
                else existing.suppressed_until_utc
            ),
        )
        conn.execute(
            """
            INSERT INTO continuity_notification_states (
                notification_id,
                inboxed_at_utc,
                seen_at_utc,
                acknowledged_at_utc,
                suppressed_until_utc,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(notification_id) DO UPDATE SET
                inboxed_at_utc = excluded.inboxed_at_utc,
                seen_at_utc = excluded.seen_at_utc,
                acknowledged_at_utc = excluded.acknowledged_at_utc,
                suppressed_until_utc = excluded.suppressed_until_utc,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                notification_id,
                merged.inboxed_at_utc,
                merged.seen_at_utc,
                merged.acknowledged_at_utc,
                merged.suppressed_until_utc,
            ),
        )
        conn.commit()


def _notification_state_latest_lifecycle_at(
    state: ContinuityNotificationStateResponse,
) -> datetime | None:
    timestamps = [
        _parse_timestamp(value)
        for value in (
            state.inboxed_at_utc,
            state.seen_at_utc,
            state.acknowledged_at_utc,
        )
        if value is not None
    ]
    if not timestamps:
        return None
    return max(timestamps)


def _classify_notification_state(
    notification_id: str,
    state: ContinuityNotificationStateResponse,
    workflow_summary_times: Mapping[str, datetime],
    *,
    now: datetime,
) -> _NotificationStateLifecycle:
    summary_time = workflow_summary_times.get(notification_id)
    if summary_time is None:
        return "orphaned"

    lifecycle_at = _notification_state_latest_lifecycle_at(state)
    if lifecycle_at is not None and lifecycle_at < summary_time:
        return "retired"
    if state.acknowledged_at_utc is not None:
        return "terminal"
    if (
        state.suppressed_until_utc is not None
        and _parse_timestamp(state.suppressed_until_utc) <= now
    ):
        return "expired"
    return "active"


def _compact_notification_states(
    conn: sqlite3.Connection,
    rows: list[Mapping[str, Any]],
    workflow_summaries: list[ContinuityWorkflowSummaryResponse],
    *,
    now: datetime | None = None,
) -> dict[str, ContinuityNotificationStateResponse]:
    now = now or datetime.now(UTC)
    workflow_summary_times = {
        summary.id: _parse_timestamp(summary.occurred_at_utc) for summary in workflow_summaries
    }
    retained: dict[str, ContinuityNotificationStateResponse] = {}
    expired_ids: list[str] = []
    deleted_ids: list[str] = []

    for row in rows:
        notification_id = str(row["notification_id"])
        state = _notification_state_from_row(row)
        lifecycle = _classify_notification_state(
            notification_id,
            state,
            workflow_summary_times,
            now=now,
        )
        if lifecycle in {"orphaned", "retired"}:
            deleted_ids.append(notification_id)
            continue
        if lifecycle == "expired":
            expired_ids.append(notification_id)
            state = state.model_copy(update={"suppressed_until_utc": None})
        retained[notification_id] = state

    if deleted_ids:
        placeholders = ", ".join("?" for _ in deleted_ids)
        conn.execute(
            f"DELETE FROM continuity_notification_states WHERE notification_id IN ({placeholders})",
            deleted_ids,
        )
    if expired_ids:
        conn.executemany(
            """
            UPDATE continuity_notification_states
            SET suppressed_until_utc = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = ?
            """,
            [(notification_id,) for notification_id in expired_ids],
        )
    if deleted_ids or expired_ids:
        conn.commit()

    return retained


def _read_continuity_snapshot_state(
    conn: sqlite3.Connection,
    *,
    limit: int,
) -> _ContinuitySnapshotState:
    outcome_rows = conn.execute(
        """
        SELECT *
        FROM continuity_outcomes
        WHERE signal_level = 'high'
        ORDER BY occurred_at_utc DESC, id DESC
        """
    ).fetchall()
    anchor_rows = conn.execute(
        """
        SELECT *
        FROM continuity_resume_anchors
        ORDER BY updated_at DESC, anchor_kind ASC
        """
    ).fetchall()
    marker_rows = conn.execute(
        """
        SELECT *
        FROM continuity_last_seen_markers
        ORDER BY observed_at_utc DESC, entity_kind ASC, entity_key ASC
        """
    ).fetchall()
    acknowledgement_rows = conn.execute(
        """
        SELECT *
        FROM continuity_recovery_acknowledgements
        ORDER BY acknowledged_at_utc DESC, recovery_key ASC
        """
    ).fetchall()
    notification_state_rows = conn.execute(
        """
        SELECT *
        FROM continuity_notification_states
        ORDER BY updated_at DESC, notification_id ASC
        """
    ).fetchall()

    all_outcomes = _attach_successors([_outcome_from_row(conn, row) for row in outcome_rows])
    outcomes = all_outcomes[:limit]

    anchors = ContinuityAnchorsResponse()
    for row in anchor_rows:
        unresolved = _anchor_from_row(row)
        resolved = _resolve_anchor(conn, unresolved, all_outcomes)
        if resolved.kind == "planning":
            anchors.planning = resolved
        elif resolved.kind == "review":
            anchors.review = resolved

    last_seen_markers = [_last_seen_marker_from_row(row) for row in marker_rows]
    workflow_summaries = _build_workflow_summaries(
        conn=conn,
        outcomes=outcomes,
        anchors=anchors,
        markers=last_seen_markers,
    )
    recovery_acknowledgements = [_recovery_ack_from_row(row) for row in acknowledgement_rows]

    return _ContinuitySnapshotState(
        outcomes=outcomes,
        anchors=anchors,
        workflow_summaries=workflow_summaries,
        last_seen_markers=last_seen_markers,
        recovery_acknowledgements=recovery_acknowledgements,
        notification_state_rows=notification_state_rows,
    )


def _notification_severity(
    summary: ContinuityWorkflowSummaryResponse,
) -> Literal["info", "warning", "alert"]:
    severity = summary.ranking_signals.drift_severity
    if severity == "gone":
        return "alert"
    if summary.degraded or severity in {"replaced", "major"}:
        return "warning"
    return "info"


def _notification_title(summary: ContinuityWorkflowSummaryResponse) -> str:
    severity = summary.ranking_signals.drift_severity
    if severity == "gone":
        return f"{summary.display_title} needs a recovery decision"
    if severity == "replaced":
        return f"{summary.display_title} has a newer path"
    if summary.ranking_signals.working_set_relevant:
        return f"{summary.display_title} is ready in your working set"
    if summary.ranking_signals.downstream_ready:
        return f"{summary.display_title} is ready to resume"
    return summary.display_title


def _notification_body(summary: ContinuityWorkflowSummaryResponse) -> str:
    unique_lines = list(
        dict.fromkeys(
            line.strip()
            for line in [
                *summary.why_now[:2],
                *summary.changed_since_last_seen[:2],
                summary.display_summary,
                summary.prior_state.summary if summary.prior_state is not None else None,
            ]
            if isinstance(line, str) and line.strip()
        )
    )
    return " · ".join(unique_lines[:2]) or summary.display_summary


def _notification_record(
    summary: ContinuityWorkflowSummaryResponse,
    state: ContinuityNotificationStateResponse | None,
) -> ContinuityNotificationRecordResponse:
    return ContinuityNotificationRecordResponse(
        id=summary.id,
        title=_notification_title(summary),
        body=_notification_body(summary),
        severity=_notification_severity(summary),
        workflow_thread=summary.workflow_thread,
        resolved_location=summary.resolved_resume.resolved_location,
        state=state or ContinuityNotificationStateResponse(),
    )


def _notification_state_is_suppressed(
    state: ContinuityNotificationStateResponse,
    *,
    now: datetime | None = None,
) -> bool:
    if not state.suppressed_until_utc:
        return False
    now = now or datetime.now(UTC)
    return _parse_timestamp(state.suppressed_until_utc) > now


def _push_resend_ready_at(
    state: ContinuityNotificationStateResponse,
) -> datetime | None:
    if state.seen_at_utc is not None:
        return _parse_timestamp(state.seen_at_utc) + _PUSH_SEEN_RESEND_COOLDOWN
    if state.inboxed_at_utc is not None:
        return _parse_timestamp(state.inboxed_at_utc) + _PUSH_UNSEEN_RESEND_COOLDOWN
    return None


def _notification_delivery_dedupe_key(
    summary: ContinuityWorkflowSummaryResponse,
) -> str:
    return _location_identity(summary.resolved_resume.resolved_location)


def _delivery_read_window(
    *,
    limit: int,
    channel: ContinuityDeliveryInspectionChannel,
) -> _ContinuityDeliveryReadWindow:
    scan_limit = limit
    if channel == "push":
        scan_limit = max(_PUSH_DELIVERY_SCAN_FLOOR, limit * _PUSH_DELIVERY_SCAN_MULTIPLIER)
    return _ContinuityDeliveryReadWindow(limit=limit, scan_limit=scan_limit, channel=channel)


def _scheduler_push_delivery_from_row(
    row: Mapping[str, Any],
) -> ContinuitySchedulerPushDeliveryResponse:
    payload = _load_json_map(str(row["payload_json"]) if row["payload_json"] is not None else None)
    raw_delivery_reason = payload.get("delivery_reason")
    delivery_reason = raw_delivery_reason if isinstance(raw_delivery_reason, str) else None
    return ContinuitySchedulerPushDeliveryResponse(
        task_name=str(row["task_name"]),
        slot_key=str(row["slot_key"]),
        push_kind=str(row["push_kind"]),
        notification_id=str(row["notification_id"]) if row["notification_id"] is not None else None,
        workflow_thread_id=str(row["workflow_thread_id"])
        if row["workflow_thread_id"] is not None
        else None,
        claimed_at_utc=str(row["claimed_at"]),
        send_started_at_utc=str(row["send_started_at"])
        if row["send_started_at"] is not None
        else None,
        send_completed_at_utc=str(row["send_completed_at"])
        if row["send_completed_at"] is not None
        else None,
        delivery_status=cast(ContinuitySchedulerPushDeliveryStatus, str(row["delivery_status"])),
        delivery_reason=delivery_reason,
        push_count=int(row["push_count"] or 0),
    )


def _read_latest_scheduler_push_deliveries(
    conn: sqlite3.Connection,
    notification_records: list[ContinuityNotificationRecordResponse],
) -> dict[str, ContinuitySchedulerPushDeliveryResponse]:
    if not notification_records:
        return {}

    notification_ids = sorted({record.id for record in notification_records})
    workflow_thread_ids = sorted({record.workflow_thread.id for record in notification_records})
    predicates: list[str] = []
    params: list[str] = []

    if notification_ids:
        placeholders = ", ".join("?" for _ in notification_ids)
        predicates.append(f"notification_id IN ({placeholders})")
        params.extend(notification_ids)
    if workflow_thread_ids:
        placeholders = ", ".join("?" for _ in workflow_thread_ids)
        predicates.append(f"workflow_thread_id IN ({placeholders})")
        params.extend(workflow_thread_ids)

    rows = conn.execute(
        f"""
        SELECT task_name, slot_key, push_kind, payload_json, notification_id, workflow_thread_id,
               claimed_at, send_started_at, send_completed_at, delivery_status, push_count
        FROM scheduler_push_deliveries
        WHERE {" OR ".join(predicates)}
        ORDER BY COALESCE(send_completed_at, send_started_at, claimed_at) DESC,
                 task_name ASC,
                 slot_key ASC,
                 push_kind ASC
        """,
        tuple(params),
    ).fetchall()

    latest_by_key: dict[str, ContinuitySchedulerPushDeliveryResponse] = {}
    for row in rows:
        delivery = _scheduler_push_delivery_from_row(row)
        if delivery.notification_id is not None:
            latest_by_key.setdefault(f"notification:{delivery.notification_id}", delivery)
        if delivery.workflow_thread_id is not None:
            latest_by_key.setdefault(f"thread:{delivery.workflow_thread_id}", delivery)

    deliveries: dict[str, ContinuitySchedulerPushDeliveryResponse] = {}
    for record in notification_records:
        delivery = latest_by_key.get(f"notification:{record.id}") or latest_by_key.get(
            f"thread:{record.workflow_thread.id}"
        )
        if delivery is not None:
            deliveries[record.id] = delivery
    return deliveries


def _notification_resend_ready_at(
    state: ContinuityNotificationStateResponse,
    *,
    channel: ContinuityDeliveryInspectionChannel,
    now: datetime,
) -> str | None:
    if channel != "push":
        return None
    if _notification_state_is_suppressed(state, now=now):
        return state.suppressed_until_utc
    resend_ready_at = _push_resend_ready_at(state)
    if resend_ready_at is None or resend_ready_at <= now:
        return None
    return resend_ready_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _notification_delivery_reason(
    summary: ContinuityWorkflowSummaryResponse,
    record: ContinuityNotificationRecordResponse,
    *,
    channel: ContinuityDeliveryInspectionChannel,
    now: datetime,
) -> ContinuityDeliveryReason:
    if channel != "push":
        return "sent"
    state = record.state
    if state.acknowledged_at_utc is not None:
        return "acknowledged"
    if _notification_state_is_suppressed(state, now=now):
        return "suppressed"
    if not _is_viable_successor(summary.resolved_resume.status):
        return "missing_target"
    resend_ready_at = _push_resend_ready_at(state)
    if resend_ready_at is not None and resend_ready_at > now:
        return "cooled_down"
    return "sent"


def _evaluate_notification_delivery_contract(
    conn: sqlite3.Connection,
    workflow_summaries: list[ContinuityWorkflowSummaryResponse],
    notification_state_rows: list[Mapping[str, Any]],
    *,
    read_window: _ContinuityDeliveryReadWindow,
    now: datetime | None = None,
) -> _ContinuityDeliveryContract:
    now = now or datetime.now(UTC)
    limit = read_window.limit
    channel = read_window.channel
    notification_states = _compact_notification_states(
        conn,
        notification_state_rows,
        workflow_summaries,
        now=now,
    )
    notification_records = [
        _notification_record(summary, notification_states.get(summary.id))
        for summary in workflow_summaries
    ]

    summary_by_id = {summary.id: summary for summary in workflow_summaries}
    latest_push_deliveries = _read_latest_scheduler_push_deliveries(conn, notification_records)
    sent_count = 0
    sent_dedupe_keys: set[str] = set()
    decisions: list[_NotificationDeliveryDecision] = []

    for record in notification_records:
        summary = summary_by_id.get(record.id)
        resend_ready_at_utc = _notification_resend_ready_at(record.state, channel=channel, now=now)
        latest_push_delivery = latest_push_deliveries.get(record.id)
        if summary is None:
            decisions.append(
                _NotificationDeliveryDecision(
                    record=record,
                    reason="missing_target",
                    resend_ready_at_utc=resend_ready_at_utc,
                    latest_push_delivery=latest_push_delivery,
                )
            )
            continue

        reason = _notification_delivery_reason(summary, record, channel=channel, now=now)
        if reason != "sent":
            decisions.append(
                _NotificationDeliveryDecision(
                    record=record,
                    reason=reason,
                    resend_ready_at_utc=resend_ready_at_utc,
                    latest_push_delivery=latest_push_delivery,
                )
            )
            continue

        dedupe_key: str | None = None
        if channel == "push":
            dedupe_key = _notification_delivery_dedupe_key(summary)
            if dedupe_key in sent_dedupe_keys:
                decisions.append(
                    _NotificationDeliveryDecision(
                        record=record,
                        reason="deduped",
                        resend_ready_at_utc=resend_ready_at_utc,
                        latest_push_delivery=latest_push_delivery,
                    )
                )
                continue

        if sent_count >= limit:
            decisions.append(
                _NotificationDeliveryDecision(
                    record=record,
                    reason="skipped",
                    resend_ready_at_utc=resend_ready_at_utc,
                    latest_push_delivery=latest_push_delivery,
                )
            )
            continue

        if dedupe_key is not None:
            sent_dedupe_keys.add(dedupe_key)
        sent_count += 1
        decisions.append(
            _NotificationDeliveryDecision(
                record=record,
                reason="sent",
                resend_ready_at_utc=resend_ready_at_utc,
                latest_push_delivery=latest_push_delivery,
            )
        )

    return _ContinuityDeliveryContract(
        notification_records=notification_records,
        decisions=decisions,
    )


def _read_continuity_delivery_contract(
    *,
    limit: int,
    settings: Settings | None = None,
    channel: ContinuityDeliveryInspectionChannel = "all",
) -> _ContinuityDeliveryContract:
    settings = settings or get_settings()
    read_window = _delivery_read_window(limit=limit, channel=channel)
    with db.core_connection(settings) as conn:
        snapshot_state = _read_continuity_snapshot_state(conn, limit=read_window.scan_limit)
        return _evaluate_notification_delivery_contract(
            conn,
            snapshot_state.workflow_summaries,
            snapshot_state.notification_state_rows,
            read_window=read_window,
        )


def read_continuity_snapshot(
    *,
    limit: int = 48,
    settings: Settings | None = None,
) -> ContinuitySnapshotResponse:
    """Read the durable continuity snapshot for frontend hydration."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        snapshot_state = _read_continuity_snapshot_state(conn, limit=limit)
        delivery_contract = _evaluate_notification_delivery_contract(
            conn,
            snapshot_state.workflow_summaries,
            snapshot_state.notification_state_rows,
            read_window=_delivery_read_window(
                limit=len(snapshot_state.workflow_summaries),
                channel="all",
            ),
        )
        return ContinuitySnapshotResponse(
            recorded_at_utc=_utc_now_iso(),
            outcomes=snapshot_state.outcomes,
            anchors=snapshot_state.anchors,
            workflow_summaries=snapshot_state.workflow_summaries,
            notification_records=delivery_contract.notification_records,
            last_seen_markers=snapshot_state.last_seen_markers,
            recovery_acknowledgements=snapshot_state.recovery_acknowledgements,
        )


def read_continuity_delivery_inspection(
    *,
    limit: int = 3,
    settings: Settings | None = None,
    channel: ContinuityDeliveryInspectionChannel = "all",
) -> ContinuityDeliveryInspectionResponse:
    """Inspect canonical continuity delivery decisions without changing selection behavior."""
    delivery_contract = _read_continuity_delivery_contract(
        limit=limit,
        settings=settings,
        channel=channel,
    )
    return ContinuityDeliveryInspectionResponse(
        inspected_at_utc=_utc_now_iso(),
        channel=channel,
        limit=limit,
        decisions=[
            ContinuityDeliveryDecisionResponse(
                record=decision.record,
                reason=decision.reason,
                resend_ready_at_utc=decision.resend_ready_at_utc,
                latest_push_delivery=decision.latest_push_delivery,
            )
            for decision in delivery_contract.decisions
        ],
    )


def read_continuity_notification_records(
    *,
    limit: int = 3,
    settings: Settings | None = None,
    channel: ContinuityDeliveryInspectionChannel = "all",
) -> list[ContinuityNotificationRecordResponse]:
    """Read calm notification records derived from ranked workflow summaries."""
    delivery_contract = _read_continuity_delivery_contract(
        limit=limit,
        settings=settings,
        channel=channel,
    )
    return [
        decision.record for decision in delivery_contract.decisions if decision.reason == "sent"
    ]


__all__ = [
    "ContinuityNotificationRecordResponse",
    "read_continuity_delivery_inspection",
    "read_continuity_notification_records",
    "read_continuity_snapshot",
    "record_continuity_outcome",
    "upsert_continuity_anchor",
    "upsert_continuity_last_seen_markers",
    "upsert_continuity_notification_state",
    "upsert_continuity_recovery_acknowledgement",
]
