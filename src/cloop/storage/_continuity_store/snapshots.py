"""Durable continuity snapshot assembly for frontend hydration."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ... import db
from ...schemas._loops.continuity import (
    ContinuityLastSeenMarkerResponse,
    ContinuityOutcomeRecordResponse,
    ContinuityRecoveryAcknowledgementResponse,
    ContinuitySnapshotResponse,
    ContinuityWorkflowSummaryResponse,
)
from ...settings import Settings, get_settings
from ._shared import _utc_now_iso
from .delivery import _delivery_read_window, _evaluate_notification_delivery_contract
from .markers import _last_seen_marker_from_row, _read_last_seen_marker_rows, _recovery_ack_from_row
from .notifications import _read_notification_state_rows
from .outcomes import _attach_successors, _outcome_from_row, _read_high_signal_outcome_rows
from .workflow_summaries import _build_workflow_summaries


@dataclass(frozen=True, slots=True)
class _ContinuitySnapshotState:
    outcomes: list[ContinuityOutcomeRecordResponse]
    workflow_summaries: list[ContinuityWorkflowSummaryResponse]
    last_seen_markers: list[ContinuityLastSeenMarkerResponse]
    recovery_acknowledgements: list[ContinuityRecoveryAcknowledgementResponse]
    notification_state_rows: list[Mapping[str, Any]]
    total_outcome_count: int
    next_outcome_id: int | None = None


def _read_continuity_snapshot_state(
    conn: sqlite3.Connection,
    *,
    limit: int,
    after_outcome_id: int | None = None,
) -> _ContinuitySnapshotState:
    outcome_rows = _read_high_signal_outcome_rows(conn)
    marker_rows = _read_last_seen_marker_rows(conn)
    acknowledgement_rows = conn.execute(
        """
        SELECT *
        FROM continuity_recovery_acknowledgements
        ORDER BY acknowledged_at_utc DESC, recovery_key ASC
        """
    ).fetchall()
    notification_state_rows = _read_notification_state_rows(conn)

    all_outcomes = _attach_successors([_outcome_from_row(conn, row) for row in outcome_rows])
    start_index = 0
    if after_outcome_id is not None:
        start_index = len(all_outcomes)
        for index, outcome in enumerate(all_outcomes):
            if outcome.id == after_outcome_id:
                start_index = index + 1
                break
    end_index = start_index + limit
    outcomes = all_outcomes[start_index:end_index]
    next_outcome_id = all_outcomes[end_index - 1].id if end_index < len(all_outcomes) else None

    last_seen_markers = [_last_seen_marker_from_row(row) for row in marker_rows]
    workflow_summaries = _build_workflow_summaries(
        conn=conn,
        outcomes=outcomes,
        markers=last_seen_markers,
    )
    recovery_acknowledgements = [_recovery_ack_from_row(row) for row in acknowledgement_rows]

    return _ContinuitySnapshotState(
        outcomes=outcomes,
        workflow_summaries=workflow_summaries,
        last_seen_markers=last_seen_markers,
        recovery_acknowledgements=recovery_acknowledgements,
        notification_state_rows=notification_state_rows,
        total_outcome_count=max(0, len(all_outcomes) - start_index),
        next_outcome_id=next_outcome_id,
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
            truncated=False,
            continuation_cursor=None,
        )
        return ContinuitySnapshotResponse(
            recorded_at_utc=_utc_now_iso(),
            outcomes=snapshot_state.outcomes,
            workflow_summaries=snapshot_state.workflow_summaries,
            notification_records=delivery_contract.notification_records,
            last_seen_markers=snapshot_state.last_seen_markers,
            recovery_acknowledgements=snapshot_state.recovery_acknowledgements,
        )
