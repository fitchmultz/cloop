/**
 * review-workflow-client.ts - Shared HTTP client helpers for planning and saved review workflows.
 *
 * Purpose:
 *   Centralize the frontend request helpers for planning checkpoint execution and
 *   saved review session/action reads so command-palette and review-workspace
 *   reuse the same transport contracts.
 *
 * Responsibilities:
 *   - Fetch planning, relationship-review, and enrichment-review session snapshots.
 *   - Execute planning checkpoints through the canonical HTTP endpoint.
 *   - Refresh saved review session snapshots through the canonical refresh endpoints.
 *   - List saved review actions and execute saved review-session actions.
 *
 * Scope:
 *   - Frontend HTTP request wrappers only.
 *
 * Usage:
 *   - Imported by `frontend/src/review-workspace.ts` and
 *     `frontend/src/command-palette.ts`.
 *
 * Invariants/Assumptions:
 *   - Shared FastAPI routes under `/loops/planning/*` and `/loops/review/*`
 *     remain the canonical execution surface.
 *   - Callers own any confirmation UX, state updates, and continuity receipts.
 */

import { requestJson } from "./http";
import type {
  EnrichmentReviewActionResponse,
  EnrichmentReviewSessionActionRequest,
  EnrichmentReviewSessionActionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  PlanningSessionExecuteResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewActionResponse,
  RelationshipReviewSessionActionRequest,
  RelationshipReviewSessionActionResponse,
  RelationshipReviewSessionSnapshotResponse,
} from "./domain";

export async function fetchPlanningSession(
  sessionId: number,
): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse>(
    `/loops/planning/sessions/${sessionId}`,
    {},
    "Failed to load planning session",
  );
}

export async function executePlanningSession(
  sessionId: number,
): Promise<PlanningSessionExecuteResponse> {
  return requestJson<PlanningSessionExecuteResponse>(
    `/loops/planning/sessions/${sessionId}/execute`,
    { method: "POST" },
    "Failed to execute planning checkpoint",
  );
}

export async function fetchRelationshipActions(): Promise<RelationshipReviewActionResponse[]> {
  return requestJson<RelationshipReviewActionResponse[]>(
    "/loops/review/relationship/actions",
    {},
    "Failed to load relationship review actions",
  );
}

export async function fetchRelationshipSession(
  sessionId: number,
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse>(
    `/loops/review/relationship/sessions/${sessionId}`,
    {},
    "Failed to load relationship review session",
  );
}

export async function refreshRelationshipSession(
  sessionId: number,
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse>(
    `/loops/review/relationship/sessions/${sessionId}/refresh`,
    { method: "POST" },
    "Failed to refresh relationship review session",
  );
}

export async function runRelationshipSessionAction(
  sessionId: number,
  payload: RelationshipReviewSessionActionRequest,
): Promise<RelationshipReviewSessionActionResponse> {
  return requestJson<RelationshipReviewSessionActionResponse, RelationshipReviewSessionActionRequest>(
    `/loops/review/relationship/sessions/${sessionId}/action`,
    { method: "POST", body: payload },
    "Failed to run relationship review action",
  );
}

export async function fetchEnrichmentActions(): Promise<EnrichmentReviewActionResponse[]> {
  return requestJson<EnrichmentReviewActionResponse[]>(
    "/loops/review/enrichment/actions",
    {},
    "Failed to load enrichment review actions",
  );
}

export async function fetchEnrichmentSession(
  sessionId: number,
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse>(
    `/loops/review/enrichment/sessions/${sessionId}`,
    {},
    "Failed to load enrichment review session",
  );
}

export async function refreshEnrichmentSession(
  sessionId: number,
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse>(
    `/loops/review/enrichment/sessions/${sessionId}/refresh`,
    { method: "POST" },
    "Failed to refresh enrichment review session",
  );
}

export async function runEnrichmentSessionAction(
  sessionId: number,
  payload: EnrichmentReviewSessionActionRequest,
): Promise<EnrichmentReviewSessionActionResponse> {
  return requestJson<EnrichmentReviewSessionActionResponse, EnrichmentReviewSessionActionRequest>(
    `/loops/review/enrichment/sessions/${sessionId}/action`,
    { method: "POST", body: payload },
    "Failed to run enrichment review action",
  );
}
