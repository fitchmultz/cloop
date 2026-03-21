"""Durable continuity storage.

Purpose:
    Persist and read backend-backed landed continuity outcomes, grouped workflow
    threads, and resume anchors for cross-device operator continuity.

Responsibilities:
    - Record high-signal landed outcomes with deduplication.
    - Upsert durable planning and review resume anchors.
    - Resolve persisted resume targets against current durable resources.
    - Build grouped workflow-thread summaries for frontend hydration.

Non-scope:
    - Frontend ranking or rendering behavior.
    - Browser-local continuity baseline snapshots.

Usage:
    Imported by continuity HTTP routes.

Invariants/Assumptions:
    - Stored JSON payloads remain transport-safe and serializable.
    - Durable continuity prefers landed outcomes over launch points.
    - Missing working-set scope should degrade to the durable target before home.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from .. import db
from ..schemas._loops.continuity import (
    ContinuityAnchorResponse,
    ContinuityAnchorsResponse,
    ContinuityAnchorUpsertRequest,
    ContinuityLastSeenBatchUpsertRequest,
    ContinuityLastSeenMarkerResponse,
    ContinuityLocationResponse,
    ContinuityOutcomeRecordResponse,
    ContinuityOutcomeWriteRequest,
    ContinuitySnapshotResponse,
    ContinuityThreadSummaryResponse,
    ContinuityWorkflowThreadKind,
    ResolvedContinuityTargetResponse,
    WorkflowThreadRefResponse,
)
from ..settings import Settings, get_settings

_DEDUPE_WINDOW_SECONDS = 15.0
_HOME_LOCATION = ContinuityLocationResponse(state="operator", recall_tool="chat")


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


def _resolve_location(
    conn: sqlite3.Connection,
    requested: ContinuityLocationResponse | None,
    launch: ContinuityLocationResponse | None,
) -> ResolvedContinuityTargetResponse:
    if requested is None:
        return ResolvedContinuityTargetResponse(
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
            return ResolvedContinuityTargetResponse(
                requested_location=requested,
                resolved_location=unscoped,
                status="working_set_scope_removed",
                message=(
                    "Working-set scope no longer exists, so continuity falls back "
                    "to the durable target."
                ),
            )
        if launch is not None and _location_exists(conn, launch):
            return ResolvedContinuityTargetResponse(
                requested_location=requested,
                resolved_location=launch,
                status="launch_fallback",
                message=(
                    "Working-set scope and landed target are gone, so continuity "
                    "falls back to the launch workflow."
                ),
            )
        return ResolvedContinuityTargetResponse(
            requested_location=requested,
            resolved_location=_HOME_LOCATION,
            status="home_fallback",
            message=(
                "Working-set scope and landed target are gone, so continuity falls back to home."
            ),
        )

    if _location_exists(conn, requested):
        return ResolvedContinuityTargetResponse(
            requested_location=requested,
            resolved_location=requested,
            status="ok",
            message=None,
        )

    if launch is not None and _location_exists(conn, launch):
        return ResolvedContinuityTargetResponse(
            requested_location=requested,
            resolved_location=launch,
            status="launch_fallback",
            message=(
                "Original landed target is unavailable, so continuity falls back "
                "to the launch workflow."
            ),
        )

    return ResolvedContinuityTargetResponse(
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
        outcome_title=str(row["outcome_title"]) if row["outcome_title"] is not None else None,
        outcome_summary=str(row["outcome_summary"]) if row["outcome_summary"] is not None else None,
        working_set_id=int(row["working_set_id"]) if row["working_set_id"] is not None else None,
        workflow_thread_id=str(row["workflow_thread_id"])
        if row["workflow_thread_id"] is not None
        else None,
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


def read_continuity_snapshot(
    *,
    limit: int = 48,
    settings: Settings | None = None,
) -> ContinuitySnapshotResponse:
    """Read the durable continuity snapshot for frontend hydration."""
    settings = settings or get_settings()
    with db.core_connection(settings) as conn:
        outcome_rows = conn.execute(
            """
            SELECT *
            FROM continuity_outcomes
            WHERE signal_level = 'high'
            ORDER BY occurred_at_utc DESC, id DESC
            LIMIT ?
            """,
            (limit,),
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

        outcomes = [_outcome_from_row(conn, row) for row in outcome_rows]

        thread_buckets: dict[str, list[ContinuityOutcomeRecordResponse]] = defaultdict(list)
        for outcome in outcomes:
            thread_buckets[outcome.workflow_thread.id].append(outcome)

        threads = [
            ContinuityThreadSummaryResponse(
                workflow_thread=items[0].workflow_thread,
                outcome_count=len(items),
                latest_outcome_id=items[0].id,
                latest_occurred_at_utc=items[0].occurred_at_utc,
                representative_title=items[0].outcome_card.get("title", items[0].label)
                if isinstance(items[0].outcome_card, dict)
                else items[0].label,
                representative_summary=items[0].outcome_card.get("summary", items[0].description)
                if isinstance(items[0].outcome_card, dict)
                else items[0].description,
            )
            for items in sorted(
                (
                    sorted(
                        bucket,
                        key=lambda item: (_parse_timestamp(item.occurred_at_utc), item.id),
                        reverse=True,
                    )
                    for bucket in thread_buckets.values()
                ),
                key=lambda bucket: (_parse_timestamp(bucket[0].occurred_at_utc), bucket[0].id),
                reverse=True,
            )
        ]

        anchors = ContinuityAnchorsResponse()
        for row in anchor_rows:
            anchor = _anchor_from_row(row)
            if anchor.kind == "planning":
                anchors.planning = anchor
            elif anchor.kind == "review":
                anchors.review = anchor

        last_seen_markers = [_last_seen_marker_from_row(row) for row in marker_rows]

        return ContinuitySnapshotResponse(
            recorded_at_utc=_utc_now_iso(),
            outcomes=outcomes,
            anchors=anchors,
            threads=threads,
            last_seen_markers=last_seen_markers,
        )


__all__ = [
    "read_continuity_snapshot",
    "record_continuity_outcome",
    "upsert_continuity_anchor",
    "upsert_continuity_last_seen_markers",
]
