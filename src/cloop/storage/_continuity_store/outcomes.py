"""Continuity outcome persistence and resume resolution."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any, cast

from ... import db
from ...schemas._loops.continuity import (
    ContinuityDisplayCardResponse,
    ContinuityLocationResponse,
    ContinuityOutcomeRecordResponse,
    ContinuityOutcomeWriteRequest,
    ContinuityRerunAction,
    ContinuitySuccessorTargetResponse,
    ContinuityTargetStatus,
    ContinuityUndoAction,
    ContinuityWorkflowThreadKind,
    ResolvedContinuityTargetResponse,
    WorkflowThreadRefResponse,
)
from ...settings import Settings, get_settings
from ._shared import (
    _CONTINUITY_FOLLOW_THROUGH_METADATA_KEY,
    _DEDUPE_WINDOW_SECONDS,
    _HOME_LOCATION,
    _dump_json,
    _load_json_map,
    _parse_timestamp,
)


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


def _sanitize_outcome_metadata(
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], ContinuityUndoAction | None, ContinuityRerunAction | None]:
    clean = dict(metadata)
    follow_through = clean.pop(_CONTINUITY_FOLLOW_THROUGH_METADATA_KEY, None)
    if not isinstance(follow_through, Mapping):
        return clean, None, None
    undo_payload = follow_through.get("undo_action")
    rerun_payload = follow_through.get("rerun_action")
    undo_action: ContinuityUndoAction | None = None
    if isinstance(undo_payload, Mapping):
        try:
            undo_action = ContinuityUndoAction.model_validate(dict(undo_payload))
        except Exception:
            undo_action = None
    rerun_action: ContinuityRerunAction | None = None
    if isinstance(rerun_payload, Mapping):
        try:
            rerun_action = ContinuityRerunAction.model_validate(dict(rerun_payload))
        except Exception:
            rerun_action = None
    return clean, undo_action, rerun_action


def _pack_outcome_metadata(
    metadata: Mapping[str, Any],
    *,
    undo_action: ContinuityUndoAction | None,
    rerun_action: ContinuityRerunAction | None,
) -> dict[str, Any]:
    packed = dict(metadata)
    if undo_action is None and rerun_action is None:
        packed.pop(_CONTINUITY_FOLLOW_THROUGH_METADATA_KEY, None)
        return packed
    packed[_CONTINUITY_FOLLOW_THROUGH_METADATA_KEY] = {
        "undo_action": undo_action.model_dump(mode="python") if undo_action is not None else None,
        "rerun_action": rerun_action.model_dump(mode="python")
        if rerun_action is not None
        else None,
    }
    return packed


def _normalize_outcome_display_card(
    display_card: ContinuityDisplayCardResponse,
    *,
    undo_action: ContinuityUndoAction | None,
    degraded_label: str | None,
) -> ContinuityDisplayCardResponse:
    trust = display_card.trust
    trust_updates: dict[str, Any] = {}
    if not trust.context_sources:
        trust_updates["context_sources"] = ["Durable continuity outcome"]
    if trust.confidence_label is None:
        trust_updates["confidence_label"] = "Persisted continuity state"
    if trust.rollback_label is None and undo_action is not None:
        trust_updates["rollback_label"] = undo_action.label
    if trust.impact_summary is None:
        trust_updates["impact_summary"] = display_card.summary
    normalized_trust = trust.model_copy(update=trust_updates) if trust_updates else trust
    action_warning = display_card.action_warning or degraded_label
    if normalized_trust is trust and action_warning == display_card.action_warning:
        return display_card
    return display_card.model_copy(
        update={
            "trust": normalized_trust,
            "action_warning": action_warning,
        }
    )


def _outcome_from_row(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
) -> ContinuityOutcomeRecordResponse:
    launch_location = _location_from_json(row["launch_location_json"])
    resume_location = _location_from_json(row["resume_location_json"])
    resolved_resume = _resolve_location(conn, resume_location, launch_location)
    degraded = resolved_resume.status != "ok"
    metadata, undo_action, rerun_action = _sanitize_outcome_metadata(
        _load_json_map(row["metadata_json"])
    )
    display_card = _normalize_outcome_display_card(
        ContinuityDisplayCardResponse.model_validate(_load_json_map(row["display_card_json"])),
        undo_action=undo_action,
        degraded_label=resolved_resume.message if degraded else None,
    )
    record = ContinuityOutcomeRecordResponse(
        id=int(row["id"]),
        kind=str(row["kind"]),
        label=str(row["label"]),
        description=str(row["description"]),
        occurred_at_utc=str(row["occurred_at_utc"]),
        launch_location=launch_location,
        display_card=display_card,
        undo_action=undo_action,
        rerun_action=rerun_action,
        resume_location=resume_location,
        resolved_resume=resolved_resume,
        workflow_thread=_workflow_thread_from_row(row),
        working_set_id=int(row["working_set_id"]) if row["working_set_id"] is not None else None,
        degraded=degraded,
        degraded_label=resolved_resume.message if degraded else None,
        metadata=metadata,
    )
    return record


def _display_title(record: ContinuityOutcomeRecordResponse) -> str:
    title = record.display_card.title.strip()
    if title:
        return title
    return record.label


def _display_summary(record: ContinuityOutcomeRecordResponse) -> str:
    summary = record.display_card.summary.strip()
    if summary:
        return summary
    return record.description


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


def _read_high_signal_outcome_rows(
    conn: sqlite3.Connection,
    *,
    snapshot_outcome_id: int | None = None,
    page_anchor: tuple[str, int] | None = None,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    sql = """
        SELECT *
        FROM continuity_outcomes
        WHERE signal_level = 'high'
    """
    params: list[Any] = []
    if snapshot_outcome_id is not None:
        sql += "\n        AND id <= ?"
        params.append(snapshot_outcome_id)
    if page_anchor is not None:
        anchor_occurred_at_utc, anchor_outcome_id = page_anchor
        sql += """
        AND (
            occurred_at_utc < ?
            OR (occurred_at_utc = ? AND id < ?)
        )
        """
        params.extend([anchor_occurred_at_utc, anchor_occurred_at_utc, anchor_outcome_id])
    sql += "\n        ORDER BY occurred_at_utc DESC, id DESC"
    if limit is not None:
        sql += "\n        LIMIT ?"
        params.append(limit)
    return conn.execute(sql, tuple(params)).fetchall()


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
        display_card_json = _dump_json(payload.display_card)
        resume_json = (
            _dump_json(payload.resume_location) if payload.resume_location is not None else None
        )
        metadata_json = _dump_json(
            _pack_outcome_metadata(
                payload.metadata,
                undo_action=payload.undo_action,
                rerun_action=payload.rerun_action,
            )
        )

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
                        display_card_json = ?,
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
                        display_card_json,
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
                display_card_json,
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
                display_card_json,
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
