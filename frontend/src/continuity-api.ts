/**
 * continuity-api.ts - Durable backend continuity transport.
 *
 * Purpose:
 *   Centralize HTTP reads and writes for backend-backed continuity outcomes and
 *   resume anchors.
 *
 * Responsibilities:
 *   - Fetch the durable continuity snapshot used for hydration.
 *   - Persist high-signal landed outcomes.
 *   - Upsert durable planning and review resume anchors.
 *
 * Scope:
 *   - Frontend HTTP helpers for continuity routes only.
 *
 * Usage:
 *   - Imported by continuity-intelligence.ts.
 *
 * Invariants/Assumptions:
 *   - The backend snapshot is the durable continuity authority.
 *   - Request and response payloads follow generated OpenAPI contracts.
 */

import type {
  ContinuityAnchorUpsertRequest,
  ContinuityLastSeenBatchUpsertRequest,
  ContinuityRecoveryAcknowledgementUpsertRequest,
  ContinuitySnapshotResponse,
  ContinuityOutcomeWriteRequest,
} from "./domain";
import { requestJson } from "./http";

export function fetchContinuitySnapshot(limit = 48): Promise<ContinuitySnapshotResponse> {
  return requestJson<ContinuitySnapshotResponse>(
    `/loops/continuity?limit=${limit}`,
    {},
    "Failed to load durable continuity state",
  );
}

export function persistContinuityOutcome(
  payload: ContinuityOutcomeWriteRequest,
): Promise<ContinuitySnapshotResponse> {
  return requestJson<ContinuitySnapshotResponse, ContinuityOutcomeWriteRequest>(
    "/loops/continuity/outcomes",
    {
      method: "POST",
      body: payload,
    },
    "Failed to persist durable continuity outcome",
  );
}

export function upsertContinuityAnchor(
  anchorKind: "planning" | "review",
  payload: ContinuityAnchorUpsertRequest,
): Promise<ContinuitySnapshotResponse> {
  return requestJson<ContinuitySnapshotResponse, ContinuityAnchorUpsertRequest>(
    `/loops/continuity/anchors/${anchorKind}`,
    {
      method: "PUT",
      body: payload,
    },
    "Failed to persist durable continuity anchor",
  );
}

export function upsertContinuityLastSeen(
  payload: ContinuityLastSeenBatchUpsertRequest,
): Promise<ContinuitySnapshotResponse> {
  return requestJson<ContinuitySnapshotResponse, ContinuityLastSeenBatchUpsertRequest>(
    "/loops/continuity/last-seen",
    {
      method: "PUT",
      body: payload,
    },
    "Failed to persist durable last-seen continuity markers",
  );
}

export function upsertContinuityRecoveryAcknowledgement(
  payload: ContinuityRecoveryAcknowledgementUpsertRequest,
): Promise<ContinuitySnapshotResponse> {
  return requestJson<ContinuitySnapshotResponse, ContinuityRecoveryAcknowledgementUpsertRequest>(
    "/loops/continuity/recovery-acks",
    {
      method: "PUT",
      body: payload,
    },
    "Failed to persist durable continuity recovery acknowledgement",
  );
}
