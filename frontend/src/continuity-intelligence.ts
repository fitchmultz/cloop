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
 *   - Track landed-outcome planning/review resume anchors.
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
  ExecutableRerunHandle,
  ExecutableUndoHandle,
  RecentShellActionEntry,
  ResumeAnchorState,
  ResumeAnchorTarget,
  ReviewFocus,
  ShellLocationContract,
} from "./contracts-ui";
import { rerunHandleIdentity } from "./executable-rerun";
import { undoHandleIdentity } from "./executable-undo";
import { recentShellActionDedupKey } from "./continuity-outcomes";

const CONTINUITY_BASELINE_STORAGE_KEY = "cloop.continuity.baseline.v2";
const RESUME_ANCHORS_STORAGE_KEY = "cloop.continuity.resume-anchors.v2";
const RECENT_ACTIONS_STORAGE_KEY = "cloop.continuity.recent-actions.v1";
const MAX_RECENT_ACTIONS = 12;

export const RECENT_SHELL_ACTIONS_UPDATED_EVENT = "cloop:recent-shell-actions-updated";

const DEFAULT_RESUME_ANCHORS: ResumeAnchorState = {
  planning: null,
  review: null,
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

export interface RememberPlanningAnchorInput {
  sessionId: number;
  launchLocation?: ShellLocationContract | null;
  resumeLocation?: ShellLocationContract | null;
  outcomeTitle?: string | null;
  outcomeSummary?: string | null;
  workingSetId?: number | null;
  visitedAtUtc?: string;
}

export interface RememberReviewAnchorInput {
  reviewFocus: Extract<ReviewFocus, "relationship" | "enrichment">;
  sessionId: number;
  launchLocation?: ShellLocationContract | null;
  resumeLocation?: ShellLocationContract | null;
  outcomeTitle?: string | null;
  outcomeSummary?: string | null;
  workingSetId?: number | null;
  visitedAtUtc?: string;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeLocation(value: unknown): ShellLocationContract | null {
  if (!isRecord(value) || typeof value["state"] !== "string" || typeof value["recallTool"] !== "string") {
    return null;
  }
  return {
    state: value["state"] as ShellLocationContract["state"],
    recallTool: value["recallTool"] as ShellLocationContract["recallTool"],
    reviewFocus: typeof value["reviewFocus"] === "string" ? value["reviewFocus"] as ReviewFocus : null,
    sessionId: typeof value["sessionId"] === "number" ? value["sessionId"] : null,
    loopId: typeof value["loopId"] === "number" ? value["loopId"] : null,
    viewId: typeof value["viewId"] === "number" ? value["viewId"] : null,
    memoryId: typeof value["memoryId"] === "number" ? value["memoryId"] : null,
    workingSetId: typeof value["workingSetId"] === "number" ? value["workingSetId"] : null,
    query: typeof value["query"] === "string" ? value["query"] : null,
  };
}

function parseResumeAnchorTarget(
  raw: unknown,
  expectedKind: ResumeAnchorTarget["kind"],
): ResumeAnchorTarget | null {
  if (!isRecord(raw) || typeof raw["sessionId"] !== "number" || typeof raw["visitedAtUtc"] !== "string") {
    return null;
  }

  const reviewFocus = raw["reviewFocus"];
  if (expectedKind === "planning") {
    if (reviewFocus !== "planning") {
      return null;
    }
  } else if (reviewFocus !== "relationship" && reviewFocus !== "enrichment") {
    return null;
  }

  return {
    kind: expectedKind,
    reviewFocus,
    sessionId: raw["sessionId"],
    visitedAtUtc: raw["visitedAtUtc"],
    launchLocation: normalizeLocation(raw["launchLocation"]),
    resumeLocation: normalizeLocation(raw["resumeLocation"]),
    outcomeTitle: typeof raw["outcomeTitle"] === "string" ? raw["outcomeTitle"] : null,
    outcomeSummary: typeof raw["outcomeSummary"] === "string" ? raw["outcomeSummary"] : null,
    workingSetId: typeof raw["workingSetId"] === "number" ? raw["workingSetId"] : null,
  };
}

function buildPlanningAnchor(input: RememberPlanningAnchorInput): ResumeAnchorTarget {
  return {
    kind: "planning",
    reviewFocus: "planning",
    sessionId: input.sessionId,
    visitedAtUtc: input.visitedAtUtc ?? new Date().toISOString(),
    launchLocation: input.launchLocation ?? null,
    resumeLocation: input.resumeLocation ?? null,
    outcomeTitle: input.outcomeTitle ?? null,
    outcomeSummary: input.outcomeSummary ?? null,
    workingSetId: input.workingSetId ?? null,
  };
}

function buildReviewAnchor(input: RememberReviewAnchorInput): ResumeAnchorTarget {
  return {
    kind: "review",
    reviewFocus: input.reviewFocus,
    sessionId: input.sessionId,
    visitedAtUtc: input.visitedAtUtc ?? new Date().toISOString(),
    launchLocation: input.launchLocation ?? null,
    resumeLocation: input.resumeLocation ?? null,
    outcomeTitle: input.outcomeTitle ?? null,
    outcomeSummary: input.outcomeSummary ?? null,
    workingSetId: input.workingSetId ?? null,
  };
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
  const parsed = safeJsonParse<unknown>(
    window.localStorage.getItem(RESUME_ANCHORS_STORAGE_KEY),
    DEFAULT_RESUME_ANCHORS,
  );
  const planning = isRecord(parsed) ? parseResumeAnchorTarget(parsed["planning"], "planning") : null;
  const review = isRecord(parsed) ? parseResumeAnchorTarget(parsed["review"], "review") : null;
  return {
    planning,
    review,
  };
}

function writeResumeAnchors(value: ResumeAnchorState): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(RESUME_ANCHORS_STORAGE_KEY, JSON.stringify(value));
}

export function rememberPlanningAnchor(input: RememberPlanningAnchorInput): void {
  const current = readResumeAnchors();
  writeResumeAnchors({
    ...current,
    planning: buildPlanningAnchor(input),
  });
}

export function rememberReviewAnchor(input: RememberReviewAnchorInput): void {
  const current = readResumeAnchors();
  writeResumeAnchors({
    ...current,
    review: buildReviewAnchor(input),
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
  const nextKey = recentShellActionDedupKey(next);
  const existing = readRecentShellActions().filter((candidate) => {
    if (recentShellActionDedupKey(candidate) !== nextKey) {
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

export function markUndoActionUnavailable(handle: ExecutableUndoHandle, reason: string): void {
  if (!canUseLocalStorage()) {
    return;
  }
  const targetIdentity = undoHandleIdentity(handle);
  const updated = readRecentShellActions().map((entry) => {
    const outcome = entry.outcome;
    if (!outcome?.card?.actions?.length) {
      return entry;
    }
    let mutated = false;
    const nextActions = outcome.card.actions.map((action) => {
      if (action.type !== "undo" || undoHandleIdentity(action.undo) !== targetIdentity) {
        return action;
      }
      mutated = true;
      return {
        ...action,
        disabledReason: reason,
      };
    });
    if (!mutated) {
      return entry;
    }
    return {
      ...entry,
      outcome: {
        ...outcome,
        card: {
          ...outcome.card,
          actions: nextActions,
        },
        undoAction: outcome.undoAction && undoHandleIdentity(outcome.undoAction.undo) === targetIdentity
          ? { ...outcome.undoAction, disabledReason: reason }
          : outcome.undoAction,
      },
    } satisfies RecentShellActionEntry;
  });
  window.localStorage.setItem(RECENT_ACTIONS_STORAGE_KEY, JSON.stringify(updated));
  emitRecentShellActionsUpdated();
}

export function markRerunActionUnavailable(handle: ExecutableRerunHandle, reason: string): void {
  if (!canUseLocalStorage()) {
    return;
  }
  const targetIdentity = rerunHandleIdentity(handle);
  const updated = readRecentShellActions().map((entry) => {
    const outcome = entry.outcome;
    if (!outcome?.card?.actions?.length) {
      return entry;
    }
    let mutated = false;
    const nextActions = outcome.card.actions.map((action) => {
      if (action.type !== "rerun" || rerunHandleIdentity(action.rerun) !== targetIdentity) {
        return action;
      }
      mutated = true;
      return {
        ...action,
        disabledReason: reason,
      };
    });
    if (!mutated) {
      return entry;
    }
    return {
      ...entry,
      outcome: {
        ...outcome,
        card: {
          ...outcome.card,
          actions: nextActions,
        },
      },
    } satisfies RecentShellActionEntry;
  });
  window.localStorage.setItem(RECENT_ACTIONS_STORAGE_KEY, JSON.stringify(updated));
  emitRecentShellActionsUpdated();
}
