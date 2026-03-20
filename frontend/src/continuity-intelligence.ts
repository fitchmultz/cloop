/**
 * continuity-intelligence.ts - Browser-local continuity baseline and resume helpers.
 *
 * Purpose:
 *   Persist deterministic continuity state so the operator shell can compare the
 *   current workspace against the last meaningful visit and surface explicit
 *   resume anchors.
 *
 * Responsibilities:
 *   - Read and write continuity baseline snapshots in localStorage.
 *   - Track last planning/review resume anchors.
 *   - Record recent shell actions for deterministic resume suggestions.
 *
 * Scope:
 *   - Frontend-only continuity persistence helpers.
 *
 * Usage:
 *   - Imported by shell, review-workspace, command-palette, and surface modules.
 *
 * Invariants/Assumptions:
 *   - Continuity state is browser-local and may be absent or malformed.
 *   - Backend-owned queue and plan state remain the source of truth; this file
 *     only stores deterministic browser-side snapshots and history.
 */

import type {
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewCohortResponse,
  LoopReviewResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewSessionSnapshotResponse,
  EnrichmentReviewSessionSnapshotResponse,
  WorkingSetContextResponse,
} from "./domain";
import type {
  ContinuityBaselineSnapshot,
  RecentShellActionEntry,
  ResumeAnchorState,
  ReviewFocus,
  ShellLocationContract,
} from "./contracts-ui";

const CONTINUITY_BASELINE_STORAGE_KEY = "cloop.continuity.baseline.v2";
const RESUME_ANCHORS_STORAGE_KEY = "cloop.continuity.resume-anchors.v1";
const RECENT_ACTIONS_STORAGE_KEY = "cloop.continuity.recent-actions.v1";
const MAX_RECENT_ACTIONS = 12;

export const RECENT_SHELL_ACTIONS_UPDATED_EVENT = "cloop:recent-shell-actions-updated";

const DEFAULT_RESUME_ANCHORS: ResumeAnchorState = {
  lastPlanningSessionId: null,
  lastPlanningVisitedAtUtc: null,
  lastPlanningWorkingSetId: null,
  lastReviewFocus: null,
  lastReviewSessionId: null,
  lastReviewVisitedAtUtc: null,
  lastReviewWorkingSetId: null,
};

export interface ContinuitySnapshotInput {
  metrics: LoopMetricsResponse;
  reviewData: LoopReviewResponse;
  planningSnapshot: PlanningSessionSnapshotResponse | null;
  relationshipSnapshot: RelationshipReviewSessionSnapshotResponse | null;
  enrichmentSnapshot: EnrichmentReviewSessionSnapshotResponse | null;
  allLoops: LoopResponse[];
  workingSetContext: WorkingSetContextResponse | null;
}

function safeJsonParse<T>(raw: string | null, fallback: T): T {
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function canUseLocalStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function emitRecentShellActionsUpdated(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(RECENT_SHELL_ACTIONS_UPDATED_EVENT));
}

function sameLocation(
  left: ShellLocationContract | null | undefined,
  right: ShellLocationContract | null | undefined,
): boolean {
  if (!left || !right) {
    return left === right;
  }
  return left.state === right.state
    && left.recallTool === right.recallTool
    && left.reviewFocus === right.reviewFocus
    && left.sessionId === right.sessionId
    && left.loopId === right.loopId
    && (left.viewId ?? null) === (right.viewId ?? null)
    && (left.memoryId ?? null) === (right.memoryId ?? null)
    && (left.workingSetId ?? null) === (right.workingSetId ?? null)
    && (left.query ?? null) === (right.query ?? null);
}

function cohortByName(
  reviewData: LoopReviewResponse,
  cohortName: LoopReviewCohortResponse["cohort"],
): LoopReviewCohortResponse | null {
  return [...reviewData.daily, ...reviewData.weekly].find((item) => item.cohort === cohortName) ?? null;
}

function cohortBaseline(
  reviewData: LoopReviewResponse,
  cohortName: LoopReviewCohortResponse["cohort"],
): { count: number; itemIds: number[] } {
  const cohort = cohortByName(reviewData, cohortName);
  return {
    count: cohort?.count ?? 0,
    itemIds: (cohort?.items ?? []).map((item) => item.id),
  };
}

function sessionBaseline(
  snapshot: RelationshipReviewSessionSnapshotResponse | EnrichmentReviewSessionSnapshotResponse | null,
): ContinuityBaselineSnapshot["relationshipSession"] | ContinuityBaselineSnapshot["enrichmentSession"] {
  if (!snapshot?.session) {
    return null;
  }
  return {
    sessionId: snapshot.session.id,
    loopCount: snapshot.loop_count,
    currentLoopId: snapshot.current_item?.loop.id ?? snapshot.session.current_loop_id ?? null,
    updatedAtUtc: snapshot.session.updated_at_utc,
  };
}

function planningBaseline(
  snapshot: PlanningSessionSnapshotResponse | null,
): ContinuityBaselineSnapshot["planningSession"] {
  if (!snapshot?.session) {
    return null;
  }

  const freshness = snapshot.context_freshness;
  const resourceChanges = snapshot.resource_change_summary;

  return {
    sessionId: snapshot.session.id,
    sessionName: snapshot.session.name,
    status: snapshot.session.status,
    loopCount: snapshot.target_loops?.length ?? 0,
    currentLoopId: snapshot.target_loops?.[0]?.id ?? null,
    updatedAtUtc: snapshot.session.updated_at_utc,
    generatedAtUtc: snapshot.session.generated_at_utc ?? null,
    contextIsStale: freshness?.is_stale ?? false,
    staleTargetLoopCount: freshness?.stale_target_loop_count ?? 0,
    missingTargetLoopCount: freshness?.missing_target_loop_count ?? 0,
    targetLoopIds: (snapshot.target_loops ?? []).map((loop) => loop.id),
    lastExecutedAtUtc: snapshot.session.last_executed_at_utc ?? null,
    resourceChangeCount: resourceChanges?.total_change_count ?? 0,
    downstreamResourceChangeCount: resourceChanges?.downstream_change_count ?? 0,
  };
}

export function buildContinuityBaseline(
  input: ContinuitySnapshotInput,
): ContinuityBaselineSnapshot {
  return {
    recordedAtUtc: new Date().toISOString(),
    metrics: {
      staleOpenCount: input.metrics.stale_open_count,
      blockedTooLongCount: input.metrics.blocked_too_long_count,
      noNextActionCount: input.metrics.no_next_action_count,
    },
    cohorts: {
      stale: cohortBaseline(input.reviewData, "stale"),
      blocked_too_long: cohortBaseline(input.reviewData, "blocked_too_long"),
      due_soon_unplanned: cohortBaseline(input.reviewData, "due_soon_unplanned"),
      no_next_action: cohortBaseline(input.reviewData, "no_next_action"),
    },
    planningSession: planningBaseline(input.planningSnapshot),
    relationshipSession: sessionBaseline(input.relationshipSnapshot),
    enrichmentSession: sessionBaseline(input.enrichmentSnapshot),
    activeWorkingSetId: input.workingSetContext?.active_working_set_id ?? null,
    snoozedLoops: input.allLoops
      .filter((loop) => typeof loop.snooze_until_utc === "string" && loop.snooze_until_utc.trim().length > 0)
      .map((loop) => ({
        id: loop.id,
        snoozeUntilUtc: loop.snooze_until_utc as string,
      })),
  };
}

export function readContinuityBaseline(): ContinuityBaselineSnapshot | null {
  if (!canUseLocalStorage()) {
    return null;
  }
  const parsed = safeJsonParse<ContinuityBaselineSnapshot | null>(
    window.localStorage.getItem(CONTINUITY_BASELINE_STORAGE_KEY),
    null,
  );
  return parsed?.recordedAtUtc ? parsed : null;
}

export function writeContinuityBaseline(snapshot: ContinuityBaselineSnapshot): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(CONTINUITY_BASELINE_STORAGE_KEY, JSON.stringify(snapshot));
}

export function readResumeAnchors(): ResumeAnchorState {
  if (!canUseLocalStorage()) {
    return { ...DEFAULT_RESUME_ANCHORS };
  }
  const parsed = safeJsonParse<ResumeAnchorState>(
    window.localStorage.getItem(RESUME_ANCHORS_STORAGE_KEY),
    DEFAULT_RESUME_ANCHORS,
  );
  return {
    ...DEFAULT_RESUME_ANCHORS,
    ...parsed,
  };
}

function writeResumeAnchors(value: ResumeAnchorState): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(RESUME_ANCHORS_STORAGE_KEY, JSON.stringify(value));
}

export function rememberPlanningAnchor(
  sessionId: number,
  workingSetId: number | null = null,
): void {
  const current = readResumeAnchors();
  writeResumeAnchors({
    ...current,
    lastPlanningSessionId: sessionId,
    lastPlanningVisitedAtUtc: new Date().toISOString(),
    lastPlanningWorkingSetId: workingSetId,
  });
}

export function rememberReviewAnchor(
  reviewFocus: Extract<ReviewFocus, "relationship" | "enrichment">,
  sessionId: number,
  workingSetId: number | null = null,
): void {
  const current = readResumeAnchors();
  writeResumeAnchors({
    ...current,
    lastReviewFocus: reviewFocus,
    lastReviewSessionId: sessionId,
    lastReviewVisitedAtUtc: new Date().toISOString(),
    lastReviewWorkingSetId: workingSetId,
  });
}

export function readRecentShellActions(): RecentShellActionEntry[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<RecentShellActionEntry[]>(
    window.localStorage.getItem(RECENT_ACTIONS_STORAGE_KEY),
    [],
  );
  return Array.isArray(parsed) ? parsed : [];
}

export function readRecentShellReceiptEntries(
  limit = MAX_RECENT_ACTIONS,
): Array<RecentShellActionEntry & { outcome: NonNullable<RecentShellActionEntry["outcome"]> }> {
  return readRecentShellActions()
    .filter(
      (
        entry,
      ): entry is RecentShellActionEntry & { outcome: NonNullable<RecentShellActionEntry["outcome"]> } =>
        entry.outcome?.card.kind === "receipt",
    )
    .slice(0, limit);
}

export function recordRecentShellAction(
  entry: Omit<RecentShellActionEntry, "occurredAt"> & { occurredAt?: string },
): void {
  if (!canUseLocalStorage()) {
    return;
  }
  const next: RecentShellActionEntry = {
    ...entry,
    occurredAt: entry.occurredAt ?? new Date().toISOString(),
  };
  const existing = readRecentShellActions().filter((candidate) => {
    if (candidate.label !== next.label || !sameLocation(candidate.location, next.location)) {
      return true;
    }
    if ((candidate.outcome?.card.summary ?? null) !== (next.outcome?.card.summary ?? null)) {
      return true;
    }
    return Math.abs(Date.parse(candidate.occurredAt) - Date.parse(next.occurredAt)) > 15_000;
  });
  window.localStorage.setItem(
    RECENT_ACTIONS_STORAGE_KEY,
    JSON.stringify([next, ...existing].slice(0, MAX_RECENT_ACTIONS)),
  );
  emitRecentShellActionsUpdated();
}
