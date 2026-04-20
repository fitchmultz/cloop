"""Durable continuity last-seen markers and recovery acknowledgements."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any, cast

from ... import db
from ...schemas._loops.continuity import (
    ContinuityLastSeenBatchUpsertRequest,
    ContinuityLastSeenMarkerResponse,
    ContinuityRecoveryAcknowledgementResponse,
    ContinuityRecoveryAcknowledgementUpsertRequest,
)
from ...settings import Settings, get_settings
from ._shared import _dump_json, _load_json_map


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


def _read_last_seen_marker_rows(
    conn: sqlite3.Connection,
    *,
    workflow_thread_ids: set[str] | None = None,
) -> list[Mapping[str, Any]]:
    if workflow_thread_ids is None:
        return conn.execute(
            """
            SELECT *
            FROM continuity_last_seen_markers
            ORDER BY observed_at_utc DESC, entity_kind ASC, entity_key ASC
            """
        ).fetchall()
    if not workflow_thread_ids:
        return []
    placeholders = ", ".join("?" for _ in workflow_thread_ids)
    return conn.execute(
        f"""
        SELECT *
        FROM continuity_last_seen_markers
        WHERE entity_kind = 'workflow_thread' AND entity_key IN ({placeholders})
        ORDER BY observed_at_utc DESC, entity_kind ASC, entity_key ASC
        """,
        tuple(sorted(workflow_thread_ids)),
    ).fetchall()


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
