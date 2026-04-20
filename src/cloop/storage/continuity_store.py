"""Durable continuity storage.

Purpose:
    Persist and read backend-backed landed continuity outcomes,
    backend-authored workflow summaries, durable notification delivery
    state, recovery provenance, and durable recovery acknowledgements for
    cross-device operator continuity.

Responsibilities:
    - Record high-signal landed outcomes with deduplication.
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

Implementation:
    Focused modules live under `cloop.storage._continuity_store`; this module
    remains the stable public import surface.
"""

from __future__ import annotations

from ._continuity_store.delivery import (
    read_continuity_delivery_inspection,
    read_continuity_notification_records,
)
from ._continuity_store.markers import (
    upsert_continuity_last_seen_markers,
    upsert_continuity_recovery_acknowledgement,
)
from ._continuity_store.notifications import upsert_continuity_notification_state
from ._continuity_store.outcomes import record_continuity_outcome
from ._continuity_store.snapshots import read_continuity_snapshot

__all__ = [
    "read_continuity_delivery_inspection",
    "read_continuity_notification_records",
    "read_continuity_snapshot",
    "record_continuity_outcome",
    "upsert_continuity_last_seen_markers",
    "upsert_continuity_notification_state",
    "upsert_continuity_recovery_acknowledgement",
]
