"""Durable continuity notification delivery state."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from ... import db
from ...schemas._loops.continuity import (
    ContinuityNotificationRecordResponse,
    ContinuityNotificationStateResponse,
    ContinuityNotificationStateUpsertRequest,
    ContinuityWorkflowSummaryResponse,
)
from ...settings import Settings, get_settings
from ._shared import (
    _PUSH_SEEN_RESEND_COOLDOWN,
    _PUSH_UNSEEN_RESEND_COOLDOWN,
    _parse_timestamp,
)

_NotificationStateLifecycle = Literal[
    "active",
    "terminal",
    "expired",
    "retired",
    "orphaned",
]


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


def _read_notification_state_rows(
    conn: sqlite3.Connection,
    *,
    notification_ids: set[str] | None = None,
) -> list[Mapping[str, Any]]:
    if notification_ids is None:
        return conn.execute(
            """
            SELECT *
            FROM continuity_notification_states
            ORDER BY updated_at DESC, notification_id ASC
            """
        ).fetchall()
    if not notification_ids:
        return []
    placeholders = ", ".join("?" for _ in notification_ids)
    return conn.execute(
        f"""
        SELECT *
        FROM continuity_notification_states
        WHERE notification_id IN ({placeholders})
        ORDER BY updated_at DESC, notification_id ASC
        """,
        tuple(sorted(notification_ids)),
    ).fetchall()


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
