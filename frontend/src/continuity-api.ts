/**
 * continuity-api.ts - Durable backend continuity transport.
 *
 * Purpose:
 *   Centralize HTTP reads and writes for backend-backed continuity outcomes,
 *   notification state, and durable observations.
 *
 * Responsibilities:
 *   - Fetch the durable continuity snapshot used for hydration.
 *   - Persist high-signal landed outcomes.
 *   - Upsert durable notification delivery state, recovery acknowledgements,
 *     and last-seen markers.
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
  ContinuityLastSeenBatchUpsertRequest,
  ContinuityNotificationStateUpsertRequest,
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

export function upsertContinuityNotificationState(
  notificationId: string,
  payload: ContinuityNotificationStateUpsertRequest,
): Promise<ContinuitySnapshotResponse> {
  return requestJson<ContinuitySnapshotResponse, ContinuityNotificationStateUpsertRequest>(
    `/loops/continuity/notifications/${encodeURIComponent(notificationId)}/state`,
    {
      method: "PUT",
      body: payload,
    },
    "Failed to persist durable continuity notification state",
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
