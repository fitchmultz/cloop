/**
 * continuity-surface-recovery.ts - Shared continuity recovery lookup for non-shell surfaces.
 *
 * Purpose:
 *   Resolve the active continuity recovery plan for planning, review, and recall
 *   surfaces from the canonical backend-authored workflow summary feed.
 *
 * Responsibilities:
 *   - Read ranked workflow summaries from durable continuity hydration.
 *   - Find the recovery plan that matches a surface location or workflow thread.
 *
 * Scope:
 *   - Frontend-only recovery lookup helpers for planning, review, and recall.
 *
 * Usage:
 *   - Imported by review-workspace.ts and recall surface modules.
 *
 * Invariants/Assumptions:
 *   - Backend-authored workflow summaries are the canonical continuity feed.
 *   - Recovery provenance remains backend-authored and stable across surfaces.
 */

import type {
  ContinuityRecoveryPlan,
  ShellLocationContract,
} from "./contracts-ui";
import {
  findRecoveryPlanForLocation,
  readRankedWorkflowSummaries,
} from "./continuity-follow-through";

export function continuityRecoveryForLocation(input: {
  location: ShellLocationContract | null;
  workflowThreadId?: string | null;
}): ContinuityRecoveryPlan | null {
  const summaries = readRankedWorkflowSummaries();
  return findRecoveryPlanForLocation(summaries, {
    location: input.location,
    workflowThreadId: input.workflowThreadId ?? null,
  });
}
