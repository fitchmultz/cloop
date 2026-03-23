"""Durable continuity HTTP routes.

Purpose:
    Expose backend-backed continuity outcomes and resume anchors for the
    operator shell's cross-device hydration and write-through persistence.

Responsibilities:
    - Return the current durable continuity snapshot.
    - Expose debug-first continuity delivery-decision inspection.
    - Persist high-signal landed outcomes.
    - Upsert durable planning and review resume anchors.
    - Upsert durable notification delivery state and recovery acknowledgements.

Non-scope:
    - Frontend-only ranking or card rendering logic.
    - Browser-local baseline snapshots.

Usage:
    Mounted under `/loops` via `cloop.routes.loops`.

Invariants/Assumptions:
    - Backend continuity stores only high-signal landed outcomes.
    - Snapshot responses remain the canonical frontend hydration payload.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...schemas._loops.continuity import (
    ContinuityAnchorUpsertRequest,
    ContinuityDeliveryInspectionChannel,
    ContinuityDeliveryInspectionResponse,
    ContinuityLastSeenBatchUpsertRequest,
    ContinuityNotificationStateUpsertRequest,
    ContinuityOutcomeWriteRequest,
    ContinuityRecoveryAcknowledgementUpsertRequest,
    ContinuitySnapshotResponse,
)
from ...storage import (
    read_continuity_delivery_inspection,
    read_continuity_snapshot,
    record_continuity_outcome,
    upsert_continuity_anchor,
    upsert_continuity_last_seen_markers,
    upsert_continuity_notification_state,
    upsert_continuity_recovery_acknowledgement,
)
from ._common import SettingsDep

router = APIRouter()


@router.get("/continuity", response_model=ContinuitySnapshotResponse)
def get_continuity_snapshot_endpoint(
    settings: SettingsDep,
    limit: int = Query(default=48, ge=1, le=200),
) -> ContinuitySnapshotResponse:
    """Return the current durable continuity snapshot."""
    return read_continuity_snapshot(limit=limit, settings=settings)


@router.get(
    "/continuity/debug/delivery-decisions", response_model=ContinuityDeliveryInspectionResponse
)
def get_continuity_delivery_decisions_endpoint(
    settings: SettingsDep,
    limit: int = Query(default=3, ge=1, le=50),
    channel: Annotated[ContinuityDeliveryInspectionChannel, Query()] = "all",
) -> ContinuityDeliveryInspectionResponse:
    """Inspect canonical continuity delivery decisions for debugging."""
    return read_continuity_delivery_inspection(limit=limit, settings=settings, channel=channel)


@router.post("/continuity/outcomes", response_model=ContinuitySnapshotResponse)
def create_continuity_outcome_endpoint(
    request: ContinuityOutcomeWriteRequest,
    settings: SettingsDep,
) -> ContinuitySnapshotResponse:
    """Persist one high-signal landed continuity outcome and return the refreshed snapshot."""
    if request.signal_level == "high":
        record_continuity_outcome(request, settings=settings)
    return read_continuity_snapshot(settings=settings)


@router.put("/continuity/anchors/{anchor_kind}", response_model=ContinuitySnapshotResponse)
def upsert_continuity_anchor_endpoint(
    anchor_kind: str,
    request: ContinuityAnchorUpsertRequest,
    settings: SettingsDep,
) -> ContinuitySnapshotResponse:
    """Upsert one durable continuity anchor and return the refreshed snapshot."""
    payload = (
        request
        if request.anchor_kind == anchor_kind
        else request.model_copy(update={"anchor_kind": anchor_kind})
    )
    upsert_continuity_anchor(payload, settings=settings)
    return read_continuity_snapshot(settings=settings)


@router.put("/continuity/last-seen", response_model=ContinuitySnapshotResponse)
def upsert_continuity_last_seen_endpoint(
    request: ContinuityLastSeenBatchUpsertRequest,
    settings: SettingsDep,
) -> ContinuitySnapshotResponse:
    """Upsert durable last-seen markers and return the refreshed continuity snapshot."""
    if request.markers:
        upsert_continuity_last_seen_markers(request, settings=settings)
    return read_continuity_snapshot(settings=settings)


@router.put(
    "/continuity/notifications/{notification_id}/state", response_model=ContinuitySnapshotResponse
)
def upsert_continuity_notification_state_endpoint(
    notification_id: str,
    request: ContinuityNotificationStateUpsertRequest,
    settings: SettingsDep,
) -> ContinuitySnapshotResponse:
    """Upsert durable notification delivery state and return the refreshed snapshot."""
    upsert_continuity_notification_state(notification_id, request, settings=settings)
    return read_continuity_snapshot(settings=settings)


@router.put("/continuity/recovery-acks", response_model=ContinuitySnapshotResponse)
def upsert_continuity_recovery_acknowledgement_endpoint(
    request: ContinuityRecoveryAcknowledgementUpsertRequest,
    settings: SettingsDep,
) -> ContinuitySnapshotResponse:
    """Upsert one durable recovery acknowledgement and return the refreshed snapshot."""
    upsert_continuity_recovery_acknowledgement(request, settings=settings)
    return read_continuity_snapshot(settings=settings)


__all__ = ["router"]
