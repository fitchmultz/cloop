"""Continuity delivery inspection, cursors, and push selection substrate.

Purpose:
    Project bounded delivery decisions for diagnostics and scheduler push
    selection without changing continuity write semantics.

Responsibilities:
    - Encode and decode opaque delivery inspection cursors
    - Walk high-signal outcomes within scan budgets for push/delivery views
    - Apply in-memory dedupe for notification delivery projections where needed

Non-scope:
    - Persisting landed continuity outcomes or notification inbox rows
    - HTTP transport shaping for continuity debug endpoints
"""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from ... import db
from ...loops.errors import ValidationError
from ...schemas._loops.continuity import (
    ContinuityDeliveryDecisionResponse,
    ContinuityDeliveryInspectionChannel,
    ContinuityDeliveryInspectionContinuationResponse,
    ContinuityDeliveryInspectionResponse,
    ContinuityDeliveryReason,
    ContinuityNotificationRecordResponse,
    ContinuityNotificationStateResponse,
    ContinuitySchedulerPushDeliveryResponse,
    ContinuitySchedulerPushDeliveryStatus,
    ContinuityWorkflowSummaryResponse,
)
from ...settings import Settings, get_settings
from ._shared import (
    _DELIVERY_CURSOR_VERSION,
    _PUSH_DELIVERY_MAX_SCAN_OUTCOMES,
    _PUSH_DELIVERY_SCAN_BATCH_SIZE,
    _cursor_fingerprint,
    _utc_now_iso,
)
from .markers import _last_seen_marker_from_row, _read_last_seen_marker_rows
from .notifications import (
    _compact_notification_states,
    _notification_record,
    _notification_state_is_suppressed,
    _push_resend_ready_at,
    _read_notification_state_rows,
)
from .outcomes import (
    _is_viable_successor,
    _location_identity,
    _outcome_from_row,
    _read_high_signal_outcome_rows,
)
from .workflow_summaries import _build_workflow_summaries


@dataclass(frozen=True, slots=True)
class _NotificationDeliveryDecision:
    record: ContinuityNotificationRecordResponse
    reason: ContinuityDeliveryReason
    resend_ready_at_utc: str | None = None
    latest_push_delivery: ContinuitySchedulerPushDeliveryResponse | None = None


@dataclass(frozen=True, slots=True)
class _ContinuityDeliveryCursor:
    snapshot_outcome_id: int
    anchor_occurred_at_utc: str
    anchor_outcome_id: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _ContinuityDeliveryCursorState:
    fingerprint: str
    snapshot_outcome_id: int
    page_anchor: tuple[str, int] | None


@dataclass(frozen=True, slots=True)
class _ContinuityDeliveryReadWindow:
    limit: int
    scan_batch_size: int
    scan_budget: int
    channel: ContinuityDeliveryInspectionChannel
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class _ContinuityDeliveryContract:
    notification_records: list[ContinuityNotificationRecordResponse]
    decisions: list[_NotificationDeliveryDecision]
    truncated: bool
    continuation_cursor: str | None = None


def _delivery_cursor_fingerprint(
    *,
    channel: ContinuityDeliveryInspectionChannel,
) -> str:
    return _cursor_fingerprint(
        {
            "resource": "continuity.delivery-decisions",
            "channel": channel,
        }
    )


def _encode_delivery_cursor(cursor: _ContinuityDeliveryCursor) -> str:
    packed = json.dumps(
        {
            "v": _DELIVERY_CURSOR_VERSION,
            "snapshot_outcome_id": cursor.snapshot_outcome_id,
            "anchor_occurred_at_utc": cursor.anchor_occurred_at_utc,
            "anchor_outcome_id": cursor.anchor_outcome_id,
            "fingerprint": cursor.fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def _decode_delivery_cursor(
    token: str,
    *,
    expected_fingerprint: str,
) -> _ContinuityDeliveryCursor:
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValidationError("cursor", "invalid cursor") from exc

    if payload.get("v") != _DELIVERY_CURSOR_VERSION:
        raise ValidationError("cursor", "unsupported cursor version")
    if payload.get("fingerprint") != expected_fingerprint:
        raise ValidationError("cursor", "cursor does not match this query")

    try:
        return _ContinuityDeliveryCursor(
            snapshot_outcome_id=int(payload["snapshot_outcome_id"]),
            anchor_occurred_at_utc=str(payload["anchor_occurred_at_utc"]),
            anchor_outcome_id=int(payload["anchor_outcome_id"]),
            fingerprint=str(payload["fingerprint"]),
        )
    except Exception as exc:
        raise ValidationError("cursor", "cursor missing required fields") from exc


def _notification_delivery_dedupe_key(
    summary: ContinuityWorkflowSummaryResponse,
) -> str:
    return _location_identity(summary.resolved_resume.resolved_location)


def _delivery_read_window(
    *,
    limit: int,
    channel: ContinuityDeliveryInspectionChannel,
    cursor: str | None = None,
) -> _ContinuityDeliveryReadWindow:
    scan_batch_size = limit
    scan_budget = limit
    if channel == "push":
        scan_batch_size = max(limit, _PUSH_DELIVERY_SCAN_BATCH_SIZE)
        scan_budget = max(limit, _PUSH_DELIVERY_MAX_SCAN_OUTCOMES)
    return _ContinuityDeliveryReadWindow(
        limit=limit,
        scan_batch_size=scan_batch_size,
        scan_budget=scan_budget,
        channel=channel,
        cursor=cursor,
    )


def _max_high_signal_outcome_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS max_id FROM continuity_outcomes WHERE signal_level = 'high'"
    ).fetchone()
    return int(row["max_id"]) if row is not None else 0


def _prepare_continuity_delivery_cursor_state(
    conn: sqlite3.Connection,
    *,
    channel: ContinuityDeliveryInspectionChannel,
    cursor: str | None,
) -> _ContinuityDeliveryCursorState:
    fingerprint = _delivery_cursor_fingerprint(channel=channel)
    if cursor is None:
        return _ContinuityDeliveryCursorState(
            fingerprint=fingerprint,
            snapshot_outcome_id=_max_high_signal_outcome_id(conn),
            page_anchor=None,
        )
    decoded = _decode_delivery_cursor(cursor, expected_fingerprint=fingerprint)
    return _ContinuityDeliveryCursorState(
        fingerprint=fingerprint,
        snapshot_outcome_id=decoded.snapshot_outcome_id,
        page_anchor=(decoded.anchor_occurred_at_utc, decoded.anchor_outcome_id),
    )


def _continuation_cursor_for_outcome_row(
    row: Mapping[str, Any],
    *,
    cursor_state: _ContinuityDeliveryCursorState,
) -> str:
    return _encode_delivery_cursor(
        _ContinuityDeliveryCursor(
            snapshot_outcome_id=cursor_state.snapshot_outcome_id,
            anchor_occurred_at_utc=str(row["occurred_at_utc"]),
            anchor_outcome_id=int(row["id"]),
            fingerprint=cursor_state.fingerprint,
        )
    )


def _read_continuity_delivery_outcome_batch_rows(
    conn: sqlite3.Connection,
    *,
    cursor_state: _ContinuityDeliveryCursorState,
    page_anchor: tuple[str, int] | None,
    limit: int,
) -> tuple[list[Mapping[str, Any]], bool, str | None]:
    outcome_rows = _read_high_signal_outcome_rows(
        conn,
        snapshot_outcome_id=cursor_state.snapshot_outcome_id,
        page_anchor=page_anchor,
        limit=limit + 1,
    )
    has_more = len(outcome_rows) > limit
    page_rows = outcome_rows[:limit]
    continuation_cursor = None
    if has_more and page_rows:
        continuation_cursor = _continuation_cursor_for_outcome_row(
            page_rows[-1],
            cursor_state=cursor_state,
        )
    return page_rows, has_more, continuation_cursor


def _scheduler_push_delivery_from_row(
    row: Mapping[str, Any],
) -> ContinuitySchedulerPushDeliveryResponse:
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
        delivery_reason=str(row["delivery_reason"]) if row["delivery_reason"] is not None else None,
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
        SELECT task_name, slot_key, push_kind, notification_id, workflow_thread_id,
               claimed_at, send_started_at, send_completed_at, delivery_status, delivery_reason,
               push_count
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


def _build_continuity_delivery_inputs(
    conn: sqlite3.Connection,
    *,
    outcome_rows: list[Mapping[str, Any]],
) -> tuple[
    list[ContinuityWorkflowSummaryResponse],
    list[Mapping[str, Any]],
]:
    outcomes = [_outcome_from_row(conn, row) for row in outcome_rows]
    workflow_thread_ids = {
        outcome.workflow_thread.id for outcome in outcomes if outcome.workflow_thread is not None
    }
    workflow_summaries = _build_workflow_summaries(
        conn=conn,
        outcomes=outcomes,
        markers=[
            _last_seen_marker_from_row(row)
            for row in _read_last_seen_marker_rows(
                conn,
                workflow_thread_ids=workflow_thread_ids,
            )
        ],
    )
    notification_state_rows = _read_notification_state_rows(
        conn,
        notification_ids={summary.id for summary in workflow_summaries},
    )
    return workflow_summaries, notification_state_rows


def _evaluate_notification_delivery_contract(
    conn: sqlite3.Connection,
    workflow_summaries: list[ContinuityWorkflowSummaryResponse],
    notification_state_rows: list[Mapping[str, Any]],
    *,
    read_window: _ContinuityDeliveryReadWindow,
    truncated: bool,
    continuation_cursor: str | None,
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
        truncated=truncated,
        continuation_cursor=continuation_cursor,
    )


def _read_continuity_delivery_contract(
    *,
    limit: int,
    settings: Settings | None = None,
    channel: ContinuityDeliveryInspectionChannel = "all",
    cursor: str | None = None,
) -> _ContinuityDeliveryContract:
    settings = settings or get_settings()
    read_window = _delivery_read_window(limit=limit, channel=channel, cursor=cursor)
    empty_contract = _ContinuityDeliveryContract(
        notification_records=[],
        decisions=[],
        truncated=False,
        continuation_cursor=None,
    )
    with db.core_connection(settings) as conn:
        cursor_state = _prepare_continuity_delivery_cursor_state(
            conn,
            channel=read_window.channel,
            cursor=read_window.cursor,
        )
        scanned_rows: list[Mapping[str, Any]] = []
        page_anchor = cursor_state.page_anchor
        remaining_budget = read_window.scan_budget
        latest_contract = empty_contract

        while remaining_budget > 0:
            batch_limit = min(read_window.scan_batch_size, remaining_budget)
            batch_rows, truncated, continuation_cursor = (
                _read_continuity_delivery_outcome_batch_rows(
                    conn,
                    cursor_state=cursor_state,
                    page_anchor=page_anchor,
                    limit=batch_limit,
                )
            )
            if not batch_rows:
                return latest_contract

            scanned_rows.extend(batch_rows)
            workflow_summaries, notification_state_rows = _build_continuity_delivery_inputs(
                conn,
                outcome_rows=scanned_rows,
            )
            latest_contract = _evaluate_notification_delivery_contract(
                conn,
                workflow_summaries,
                notification_state_rows,
                read_window=read_window,
                truncated=truncated,
                continuation_cursor=continuation_cursor,
            )
            if read_window.channel != "push":
                return latest_contract

            if (
                sum(1 for decision in latest_contract.decisions if decision.reason == "sent")
                >= limit
            ):
                return latest_contract
            if not truncated:
                return latest_contract

            remaining_budget -= len(batch_rows)
            if remaining_budget <= 0:
                return latest_contract
            page_anchor = (str(batch_rows[-1]["occurred_at_utc"]), int(batch_rows[-1]["id"]))

        return latest_contract


def read_continuity_delivery_inspection(
    *,
    limit: int = 3,
    settings: Settings | None = None,
    channel: ContinuityDeliveryInspectionChannel = "all",
    cursor: str | None = None,
) -> ContinuityDeliveryInspectionResponse:
    """Inspect canonical continuity delivery decisions without changing selection behavior."""
    delivery_contract = _read_continuity_delivery_contract(
        limit=limit,
        settings=settings,
        channel=channel,
        cursor=cursor,
    )
    decisions = [
        ContinuityDeliveryDecisionResponse(
            record=decision.record,
            reason=decision.reason,
            resend_ready_at_utc=decision.resend_ready_at_utc,
            latest_push_delivery=decision.latest_push_delivery,
        )
        for decision in delivery_contract.decisions
    ]
    continuation = (
        ContinuityDeliveryInspectionContinuationResponse(
            cursor=delivery_contract.continuation_cursor
        )
        if delivery_contract.truncated and delivery_contract.continuation_cursor is not None
        else None
    )
    return ContinuityDeliveryInspectionResponse(
        inspected_at_utc=_utc_now_iso(),
        channel=channel,
        limit=limit,
        truncated=delivery_contract.truncated,
        continuation=continuation,
        decisions=decisions,
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
