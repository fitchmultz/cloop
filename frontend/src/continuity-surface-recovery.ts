/**
 * continuity-surface-recovery.ts - Shared continuity recovery lookup for non-shell surfaces.
 *
 * Purpose:
 *   Resolve the active continuity recovery plan for planning, review, and recall
 *   surfaces without duplicating ranked-outcome lookup logic.
 *
 * Responsibilities:
 *   - Build continuity availability snapshots for downstream surfaces.
 *   - Read ranked landed outcomes from durable continuity state.
 *   - Find the recovery plan that matches a surface location or workflow thread.
 *
 * Scope:
 *   - Frontend-only recovery lookup helpers for planning, review, and recall.
 *
 * Usage:
 *   - Imported by review-workspace.ts and recall surface modules.
 *
 * Invariants/Assumptions:
 *   - Backend-authored successor provenance is the canonical replacement source.
 *   - Surfaces may omit availability details; persisted resolved targets still win.
 *   - Working-set metadata stays shallow and transport-safe.
 */

import type {
  ContinuityRecoveryPlan,
  ShellLocationContract,
  WorkingSetSessionMetadata,
} from "./contracts-ui";
import {
  buildContinuityAvailability,
  findRecoveryPlanForLocation,
  readRankedLandedOutcomes,
} from "./continuity-follow-through";

export interface SurfaceRecoveryAvailabilityInput {
  planningSessionIds?: readonly number[];
  relationshipSessionIds?: readonly number[];
  enrichmentSessionIds?: readonly number[];
  workingSets?: readonly WorkingSetSessionMetadata[];
}

export function continuityRecoveryForLocation(input: {
  location: ShellLocationContract | null;
  workflowThreadId?: string | null;
  availability?: SurfaceRecoveryAvailabilityInput;
}): ContinuityRecoveryPlan | null {
  const availability = buildContinuityAvailability({
    planningSessionIds: input.availability?.planningSessionIds ?? [],
    relationshipSessionIds: input.availability?.relationshipSessionIds ?? [],
    enrichmentSessionIds: input.availability?.enrichmentSessionIds ?? [],
    workingSets: input.availability?.workingSets ?? [],
  });
  const outcomes = readRankedLandedOutcomes({ availability });
  return findRecoveryPlanForLocation(outcomes, {
    location: input.location,
    workflowThreadId: input.workflowThreadId ?? null,
  });
}
