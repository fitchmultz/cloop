/**
 * continuity-intelligence.ts - Durable continuity cache, hydration, and baseline helpers.
 *
 * Purpose:
 *   Persist deterministic continuity state so the operator shell can compare the
 *   current workspace against the last meaningful visit while treating backend
 *   continuity history as the durable source of truth.
 *
 * Responsibilities:
 *   - Read and write browser-local continuity baseline snapshots.
 *   - Hydrate durable recent outcomes and resume anchors from the backend.
 *   - Queue high-signal landed outcomes and anchors for backend persistence.
 *   - Keep local cache state deterministic for receipts, reruns, and undo state.
 *
 * Scope:
 *   - Frontend continuity persistence helpers and backend sync only.
 *
 * Usage:
 *   - Imported by shell, review-workspace, command-palette, and surface modules.
 *
 * Invariants/Assumptions:
 *   - Backend continuity is the durable authority for recent landed outcomes and anchors.
 *   - Continuity baseline snapshots remain browser-local and are not synced.
 *   - Pending unsynced writes must survive hydration and refresh attempts.
 */

import type {
  ContinuityAnchorResponse,
  ContinuityAnchorUpsertRequest,
  ContinuityAnchorsResponse,
  ContinuityLocationResponse,
  ContinuityOutcomeRecordResponse,
  ContinuityOutcomeWriteRequest,
  ContinuitySnapshotResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewCohortResponse,
  LoopReviewResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewSessionSnapshotResponse,
  WorkingSetContextResponse,
} from "./domain";
import type {
  ContinuityBaselineSnapshot,
  ContinuityPersistenceState,
  ExecutableRerunHandle,
  ExecutableUndoHandle,
  OperatorActionCard,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  ResolvedContinuityTarget,
  ResumeAnchorState,
  ResumeAnchorTarget,
  ReviewFocus,
  ShellLocationContract,
  WorkflowThreadKind,
  WorkflowThreadRef,
} from "./contracts-ui";
import { fetchContinuitySnapshot, persistContinuityOutcome, upsertContinuityAnchor } from "./continuity-api";
import { rerunHandleIdentity } from "./executable-rerun";
import { undoHandleIdentity } from "./executable-undo";
import {
  isLowSignalNavigationEntry,
  recentShellActionDedupKey,
  resolveContinuityWorkingSetId,
} from "./continuity-outcomes";

const CONTINUITY_BASELINE_STORAGE_KEY = "cloop.continuity.baseline.v2";
const RESUME_ANCHORS_CACHE_KEY = "cloop.continuity.resume-anchors.cache.v3";
const RECENT_ACTIONS_CACHE_KEY = "cloop.continuity.recent-actions.cache.v3";
const PENDING_CONTINUITY_SYNC_KEY = "cloop.continuity.pending-sync.v1";
const MAX_RECENT_ACTIONS = 24;
const DEDUPE_WINDOW_MS = 15_000;

export const RECENT_SHELL_ACTIONS_UPDATED_EVENT = "cloop:recent-shell-actions-updated";

const DEFAULT_RESUME_ANCHORS: ResumeAnchorState = {
  planning: null,
  review: null,
};

interface PendingOutcomeWrite {
  kind: "outcome";
  entry: RecentShellActionEntry;
}

interface PendingAnchorWrite {
  kind: "anchor";
  anchorKind: "planning" | "review";
  anchor: ResumeAnchorTarget;
}

type PendingContinuityWrite = PendingOutcomeWrite | PendingAnchorWrite;

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
  workflowThreadId?: string | null;
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
  workflowThreadId?: string | null;
  visitedAtUtc?: string;
}

let hydrationPromise: Promise<void> | null = null;
let syncPromise: Promise<void> | null = null;

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

function integerValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseInt(value, 10);
    return Number.isInteger(parsed) ? parsed : null;
  }
  return null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim().length ? value : null;
}

function persistenceState(status: ContinuityPersistenceState["status"]): ContinuityPersistenceState {
  return {
    status,
    persistedOutcomeId: null,
    syncedAtUtc: status === "synced" ? new Date().toISOString() : null,
  };
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

function normalizeWorkflowThread(value: unknown): WorkflowThreadRef | null {
  if (!isRecord(value) || typeof value["id"] !== "string" || typeof value["kind"] !== "string" || typeof value["title"] !== "string") {
    return null;
  }
  return {
    id: value["id"],
    kind: value["kind"] as WorkflowThreadKind,
    title: value["title"],
    summary: typeof value["summary"] === "string" ? value["summary"] : null,
    parentOutcomeId: typeof value["parentOutcomeId"] === "number" ? value["parentOutcomeId"] : null,
  };
}

function normalizeResolvedTarget(value: unknown): ResolvedContinuityTarget | null {
  if (!isRecord(value) || typeof value["status"] !== "string") {
    return null;
  }
  const resolvedLocation = normalizeLocation(value["resolvedLocation"]);
  if (!resolvedLocation) {
    return null;
  }
  return {
    requestedLocation: normalizeLocation(value["requestedLocation"]),
    resolvedLocation,
    status: value["status"] as ResolvedContinuityTarget["status"],
    message: typeof value["message"] === "string" ? value["message"] : null,
  };
}

function findUndoAction(card: OperatorActionCard): OperatorActionCardUndoAction | null {
  return card.actions.find((action): action is OperatorActionCardUndoAction => action.type === "undo") ?? null;
}

function parseRecentShellActionEntry(value: unknown): RecentShellActionEntry | null {
  if (!isRecord(value) || typeof value["kind"] !== "string" || typeof value["label"] !== "string" || typeof value["description"] !== "string" || typeof value["occurredAt"] !== "string") {
    return null;
  }

  const outcome = isRecord(value["outcome"]) ? value["outcome"] : null;
  const cardValue = outcome && isRecord(outcome["card"]) ? outcome["card"] as unknown as OperatorActionCard : null;
  const entry: RecentShellActionEntry = {
    kind: value["kind"] as RecentShellActionEntry["kind"],
    label: value["label"],
    description: value["description"],
    location: normalizeLocation(value["location"]),
    metadata: isRecord(value["metadata"]) ? value["metadata"] : null,
    occurredAt: value["occurredAt"],
    persistence: isRecord(value["persistence"])
      ? {
          status: value["persistence"]["status"] as ContinuityPersistenceState["status"],
          persistedOutcomeId: integerValue(value["persistence"]["persistedOutcomeId"]),
          syncedAtUtc: stringValue(value["persistence"]["syncedAtUtc"]),
        }
      : null,
  };

  if (!outcome || !cardValue) {
    return entry;
  }

  entry.outcome = {
    card: cardValue,
    resumeLocation: normalizeLocation(outcome["resumeLocation"]),
    rollbackLabel: typeof outcome["rollbackLabel"] === "string" ? outcome["rollbackLabel"] : null,
    undoAction: findUndoAction(cardValue),
    workflowThread: normalizeWorkflowThread(outcome["workflowThread"]),
    resolvedResume: normalizeResolvedTarget(outcome["resolvedResume"]),
  };
  return entry;
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
    workflowThreadId: typeof raw["workflowThreadId"] === "string" ? raw["workflowThreadId"] : null,
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
    workflowThreadId: input.workflowThreadId ?? `planning:${input.sessionId}`,
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
    workflowThreadId: input.workflowThreadId ?? `review:${input.reviewFocus}:${input.sessionId}`,
  };
}

function cacheKeyForOutcome(entry: RecentShellActionEntry): string {
  return `${recentShellActionDedupKey(entry)}::${entry.occurredAt}`;
}

function readPendingContinuityWrites(): PendingContinuityWrite[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<unknown[]>(window.localStorage.getItem(PENDING_CONTINUITY_SYNC_KEY), []);
  if (!Array.isArray(parsed)) {
    return [];
  }
  const writes: PendingContinuityWrite[] = [];
  parsed.forEach((item) => {
    if (!isRecord(item) || typeof item["kind"] !== "string") {
      return;
    }
    if (item["kind"] === "outcome") {
      const entry = parseRecentShellActionEntry(item["entry"]);
      if (entry) {
        writes.push({ kind: "outcome", entry });
      }
      return;
    }
    if (item["kind"] === "anchor") {
      const anchorKind = item["anchorKind"];
      if (anchorKind !== "planning" && anchorKind !== "review") {
        return;
      }
      const anchor = parseResumeAnchorTarget(item["anchor"], anchorKind);
      if (anchor) {
        writes.push({ kind: "anchor", anchorKind, anchor });
      }
    }
  });
  return writes;
}

function writePendingContinuityWrites(writes: readonly PendingContinuityWrite[]): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(PENDING_CONTINUITY_SYNC_KEY, JSON.stringify(writes));
}

function readRecentActionsCache(): RecentShellActionEntry[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<unknown[]>(window.localStorage.getItem(RECENT_ACTIONS_CACHE_KEY), []);
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed
    .map((item) => parseRecentShellActionEntry(item))
    .filter((item): item is RecentShellActionEntry => item !== null);
}

function writeRecentActionsCache(entries: readonly RecentShellActionEntry[]): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(RECENT_ACTIONS_CACHE_KEY, JSON.stringify(entries));
}

function readResumeAnchorsCache(): ResumeAnchorState {
  if (!canUseLocalStorage()) {
    return { ...DEFAULT_RESUME_ANCHORS };
  }
  const parsed = safeJsonParse<unknown>(window.localStorage.getItem(RESUME_ANCHORS_CACHE_KEY), DEFAULT_RESUME_ANCHORS);
  const planning = isRecord(parsed) ? parseResumeAnchorTarget(parsed["planning"], "planning") : null;
  const review = isRecord(parsed) ? parseResumeAnchorTarget(parsed["review"], "review") : null;
  return {
    planning,
    review,
  };
}

function writeResumeAnchorsCache(value: ResumeAnchorState): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(RESUME_ANCHORS_CACHE_KEY, JSON.stringify(value));
}

function dedupeRecentActions(entries: readonly RecentShellActionEntry[]): RecentShellActionEntry[] {
  const deduped: RecentShellActionEntry[] = [];
  entries.forEach((candidate) => {
    const candidateKey = recentShellActionDedupKey(candidate);
    const existingIndex = deduped.findIndex((entry) => {
      if (recentShellActionDedupKey(entry) !== candidateKey) {
        return false;
      }
      return Math.abs(Date.parse(entry.occurredAt) - Date.parse(candidate.occurredAt)) <= DEDUPE_WINDOW_MS;
    });
    if (existingIndex >= 0) {
      const existing = deduped[existingIndex]!;
      if (Date.parse(candidate.occurredAt) >= Date.parse(existing.occurredAt)) {
        deduped.splice(existingIndex, 1, candidate);
      }
      return;
    }
    deduped.push(candidate);
  });
  return deduped
    .sort((left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt))
    .slice(0, MAX_RECENT_ACTIONS);
}

function inferWorkflowThreadKind(entry: RecentShellActionEntry): WorkflowThreadKind {
  switch (entry.kind) {
    case "planning":
      return "planning_checkpoint";
    case "review":
      return "review_session";
    case "working_set":
    case "working_set_session":
      return "working_set";
    case "recall":
      return "recall";
    case "command":
    case "bulk":
    case "snooze":
      return "command";
    default:
      return "ad_hoc";
  }
}

function deriveWorkflowThread(entry: RecentShellActionEntry): WorkflowThreadRef | null {
  if (entry.outcome?.workflowThread) {
    return entry.outcome.workflowThread;
  }
  if (!entry.outcome?.card) {
    return null;
  }

  const metadata = isRecord(entry.metadata) ? entry.metadata : {};
  const sessionId = integerValue(metadata["sessionId"]) ?? entry.outcome.resumeLocation?.sessionId ?? entry.location?.sessionId;
  const workingSetId = integerValue(metadata["workingSetId"]) ?? resolveContinuityWorkingSetId(entry);
  const reviewFocus = stringValue(metadata["reviewFocus"]) ?? entry.outcome.resumeLocation?.reviewFocus ?? entry.location?.reviewFocus;
  const query = stringValue(metadata["query"]) ?? entry.outcome.resumeLocation?.query ?? entry.location?.query;
  const recallTool = entry.outcome.resumeLocation?.recallTool ?? entry.location?.recallTool ?? "chat";
  const checkpointIndex = integerValue(metadata["checkpointIndex"]);
  const title = entry.outcome.card.title;
  const summary = entry.outcome.card.summary;

  switch (entry.kind) {
    case "planning":
      if (sessionId != null) {
        return {
          id: checkpointIndex != null ? `planning:${sessionId}:checkpoint:${checkpointIndex}` : `planning:${sessionId}`,
          kind: "planning_checkpoint",
          title,
          summary,
          parentOutcomeId: null,
        };
      }
      break;
    case "review":
      if (sessionId != null && (reviewFocus === "relationship" || reviewFocus === "enrichment")) {
        return {
          id: `review:${reviewFocus}:${sessionId}`,
          kind: "review_session",
          title,
          summary,
          parentOutcomeId: null,
        };
      }
      break;
    case "working_set":
    case "working_set_session":
      if (workingSetId != null) {
        return {
          id: `working-set:${workingSetId}`,
          kind: "working_set",
          title,
          summary,
          parentOutcomeId: null,
        };
      }
      break;
    case "recall":
      if (query) {
        return {
          id: `recall:${recallTool}:${query.trim().toLowerCase()}`,
          kind: "recall",
          title,
          summary,
          parentOutcomeId: null,
        };
      }
      break;
    case "command":
    case "bulk":
    case "snooze":
      return {
        id: `${entry.kind}:${entry.label.trim().toLowerCase()}`,
        kind: "command",
        title,
        summary,
        parentOutcomeId: null,
      };
    default:
      break;
  }

  return {
    id: `${inferWorkflowThreadKind(entry)}:${recentShellActionDedupKey(entry)}`,
    kind: inferWorkflowThreadKind(entry),
    title,
    summary,
    parentOutcomeId: null,
  };
}

function enrichRecentActionEntry(entry: RecentShellActionEntry): RecentShellActionEntry {
  if (!entry.outcome) {
    return entry;
  }
  return {
    ...entry,
    outcome: {
      ...entry.outcome,
      workflowThread: entry.outcome.workflowThread ?? deriveWorkflowThread(entry),
      resolvedResume: entry.outcome.resolvedResume ?? null,
    },
  };
}

function shouldPersistDurably(entry: RecentShellActionEntry): boolean {
  return entry.outcome?.card.kind === "receipt" && !isLowSignalNavigationEntry(entry);
}

function mapLocationToApi(location: ShellLocationContract | null): ContinuityLocationResponse | null {
  if (!location) {
    return null;
  }
  return {
    state: location.state,
    recall_tool: location.recallTool,
    review_focus: location.reviewFocus,
    session_id: location.sessionId,
    loop_id: location.loopId,
    view_id: location.viewId ?? null,
    memory_id: location.memoryId ?? null,
    working_set_id: location.workingSetId ?? null,
    query: location.query ?? null,
  };
}

function mapLocationFromApi(location: ContinuityLocationResponse | null | undefined): ShellLocationContract | null {
  if (!location) {
    return null;
  }
  return {
    state: location.state,
    recallTool: location.recall_tool,
    reviewFocus: location.review_focus ?? null,
    sessionId: location.session_id ?? null,
    loopId: location.loop_id ?? null,
    viewId: location.view_id ?? null,
    memoryId: location.memory_id ?? null,
    workingSetId: location.working_set_id ?? null,
    query: location.query ?? null,
  };
}

function mapWorkflowThreadToApi(thread: WorkflowThreadRef) {
  return {
    id: thread.id,
    kind: thread.kind,
    title: thread.title,
    summary: thread.summary,
    parent_outcome_id: thread.parentOutcomeId,
  };
}

function mapWorkflowThreadFromApi(thread: ContinuityOutcomeRecordResponse["workflow_thread"]): WorkflowThreadRef {
  return {
    id: thread.id,
    kind: thread.kind,
    title: thread.title,
    summary: thread.summary ?? null,
    parentOutcomeId: thread.parent_outcome_id ?? null,
  };
}

function mapResolvedTargetFromApi(
  resolved: ContinuityOutcomeRecordResponse["resolved_resume"],
): ResolvedContinuityTarget {
  return {
    requestedLocation: mapLocationFromApi(resolved.requested_location),
    resolvedLocation: mapLocationFromApi(resolved.resolved_location)!,
    status: resolved.status,
    message: resolved.message ?? null,
  };
}

function mapPersistedOutcomeToRecentEntry(response: ContinuityOutcomeRecordResponse): RecentShellActionEntry {
  const card = response.outcome_card as unknown as OperatorActionCard;
  return enrichRecentActionEntry({
    kind: response.kind as RecentShellActionEntry["kind"],
    label: response.label,
    description: response.description,
    location: mapLocationFromApi(response.launch_location),
    metadata: response.metadata ?? null,
    occurredAt: response.occurred_at_utc,
    persistence: {
      status: "synced",
      persistedOutcomeId: response.id,
      syncedAtUtc: response.occurred_at_utc,
    },
    outcome: {
      card,
      resumeLocation: mapLocationFromApi(response.resume_location),
      rollbackLabel: card.trust.rollbackLabel ?? null,
      undoAction: findUndoAction(card),
      workflowThread: mapWorkflowThreadFromApi(response.workflow_thread),
      resolvedResume: mapResolvedTargetFromApi(response.resolved_resume),
    },
  });
}

function mapAnchorResponse(anchor: ContinuityAnchorResponse | null | undefined): ResumeAnchorTarget | null {
  if (!anchor) {
    return null;
  }
  return {
    kind: anchor.kind,
    reviewFocus: anchor.review_focus,
    sessionId: anchor.session_id,
    visitedAtUtc: anchor.visited_at_utc,
    launchLocation: mapLocationFromApi(anchor.launch_location),
    resumeLocation: mapLocationFromApi(anchor.resume_location),
    outcomeTitle: anchor.outcome_title ?? null,
    outcomeSummary: anchor.outcome_summary ?? null,
    workingSetId: anchor.working_set_id ?? null,
    workflowThreadId: anchor.workflow_thread_id ?? null,
  };
}

function mapPersistedAnchors(anchors: ContinuityAnchorsResponse): ResumeAnchorState {
  return {
    planning: mapAnchorResponse(anchors.planning),
    review: mapAnchorResponse(anchors.review),
  };
}

function mergePendingEntries(snapshotEntries: readonly RecentShellActionEntry[]): RecentShellActionEntry[] {
  const pendingEntries = readPendingContinuityWrites()
    .flatMap((write) => write.kind === "outcome" ? [write.entry] : [])
    .map((entry) => enrichRecentActionEntry(entry));
  return dedupeRecentActions([...pendingEntries, ...snapshotEntries]);
}

function mergePendingAnchors(snapshotAnchors: ResumeAnchorState): ResumeAnchorState {
  return readPendingContinuityWrites().reduce((state, write) => {
    if (write.kind !== "anchor") {
      return state;
    }
    return {
      ...state,
      [write.anchorKind]: write.anchor,
    } satisfies ResumeAnchorState;
  }, snapshotAnchors);
}

function applyContinuitySnapshot(snapshot: ContinuitySnapshotResponse): void {
  const snapshotEntries = (snapshot.outcomes ?? []).map((item) => mapPersistedOutcomeToRecentEntry(item));
  const anchors = snapshot.anchors ?? { planning: null, review: null };
  writeRecentActionsCache(mergePendingEntries(snapshotEntries));
  writeResumeAnchorsCache(mergePendingAnchors(mapPersistedAnchors(anchors)));
  emitRecentShellActionsUpdated();
}

function buildOutcomeWriteRequest(entry: RecentShellActionEntry): ContinuityOutcomeWriteRequest {
  const workflowThread = deriveWorkflowThread(entry);
  if (!entry.outcome || !workflowThread) {
    throw new Error("High-signal continuity writes require a landed outcome and workflow thread.");
  }
  return {
    kind: entry.kind,
    label: entry.label,
    description: entry.description,
    occurred_at_utc: entry.occurredAt,
    launch_location: mapLocationToApi(entry.location),
    outcome_card: entry.outcome.card as unknown as Record<string, unknown>,
    resume_location: mapLocationToApi(entry.outcome.resumeLocation),
    working_set_id: resolveContinuityWorkingSetId(entry),
    workflow_thread: mapWorkflowThreadToApi(workflowThread),
    dedupe_key: recentShellActionDedupKey(entry),
    source_surface: stringValue(isRecord(entry.metadata) ? entry.metadata["source"] : null) ?? entry.kind,
    signal_level: "high",
    metadata: isRecord(entry.metadata) ? entry.metadata : {},
  };
}

function buildAnchorWriteRequest(
  anchorKind: "planning" | "review",
  anchor: ResumeAnchorTarget,
): ContinuityAnchorUpsertRequest {
  return {
    anchor_kind: anchorKind,
    review_focus: anchor.reviewFocus,
    session_id: anchor.sessionId,
    visited_at_utc: anchor.visitedAtUtc,
    launch_location: mapLocationToApi(anchor.launchLocation),
    resume_location: mapLocationToApi(anchor.resumeLocation),
    outcome_title: anchor.outcomeTitle,
    outcome_summary: anchor.outcomeSummary,
    working_set_id: anchor.workingSetId,
    workflow_thread_id: anchor.workflowThreadId ?? null,
    metadata: {},
  };
}

function writePendingOutcome(entry: RecentShellActionEntry): void {
  const candidate = enrichRecentActionEntry(entry);
  const candidateKey = cacheKeyForOutcome(candidate);
  const writes = readPendingContinuityWrites().filter((write) => {
    if (write.kind !== "outcome") {
      return true;
    }
    return cacheKeyForOutcome(write.entry) !== candidateKey;
  });
  writes.unshift({ kind: "outcome", entry: candidate });
  writePendingContinuityWrites(writes);
}

function writePendingAnchor(anchorKind: "planning" | "review", anchor: ResumeAnchorTarget): void {
  const writes = readPendingContinuityWrites().filter((write) => {
    return write.kind !== "anchor" || write.anchorKind !== anchorKind;
  });
  writes.unshift({ kind: "anchor", anchorKind, anchor });
  writePendingContinuityWrites(writes);
}

function markOutcomePersistenceStatus(
  entry: RecentShellActionEntry,
  status: ContinuityPersistenceState["status"],
): void {
  const targetKey = cacheKeyForOutcome(entry);
  const updated = readRecentActionsCache().map((candidate) => {
    if (cacheKeyForOutcome(candidate) !== targetKey) {
      return candidate;
    }
    return {
      ...candidate,
      persistence: persistenceState(status),
    } satisfies RecentShellActionEntry;
  });
  writeRecentActionsCache(updated);
  emitRecentShellActionsUpdated();
}

async function persistOneWrite(write: PendingContinuityWrite): Promise<ContinuitySnapshotResponse> {
  if (write.kind === "outcome") {
    return persistContinuityOutcome(buildOutcomeWriteRequest(write.entry));
  }
  return upsertContinuityAnchor(write.anchorKind, buildAnchorWriteRequest(write.anchorKind, write.anchor));
}

export async function hydrateDurableContinuityState(): Promise<void> {
  if (!canUseLocalStorage()) {
    return;
  }
  if (hydrationPromise) {
    return hydrationPromise;
  }
  hydrationPromise = (async () => {
    const snapshot = await fetchContinuitySnapshot();
    applyContinuitySnapshot(snapshot);
    if (readPendingContinuityWrites().length) {
      void flushPendingContinuityWrites();
    }
  })().finally(() => {
    hydrationPromise = null;
  });
  return hydrationPromise;
}

async function flushPendingContinuityWrites(): Promise<void> {
  if (!canUseLocalStorage()) {
    return;
  }
  if (syncPromise) {
    return syncPromise;
  }

  let completed = false;
  syncPromise = (async () => {
    let writes = readPendingContinuityWrites();
    while (writes.length) {
      const current = writes[0]!;
      try {
        const snapshot = await persistOneWrite(current);
        writes = writes.slice(1);
        writePendingContinuityWrites(writes);
        applyContinuitySnapshot(snapshot);
      } catch {
        if (current.kind === "outcome") {
          markOutcomePersistenceStatus(current.entry, "failed");
        }
        throw current;
      }
    }
    completed = true;
  })()
    .catch(() => {
      // Keep queued writes for the next retry. The local cache already reflects failure.
    })
    .finally(() => {
      syncPromise = null;
      if (completed && readPendingContinuityWrites().length) {
        void flushPendingContinuityWrites();
      }
    });

  return syncPromise;
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
  return readResumeAnchorsCache();
}

export function rememberPlanningAnchor(input: RememberPlanningAnchorInput): void {
  const current = readResumeAnchorsCache();
  const planning = buildPlanningAnchor(input);
  writeResumeAnchorsCache({
    ...current,
    planning,
  });
  writePendingAnchor("planning", planning);
  void flushPendingContinuityWrites();
}

export function rememberReviewAnchor(input: RememberReviewAnchorInput): void {
  const current = readResumeAnchorsCache();
  const review = buildReviewAnchor(input);
  writeResumeAnchorsCache({
    ...current,
    review,
  });
  writePendingAnchor("review", review);
  void flushPendingContinuityWrites();
}

export function readRecentShellActions(): RecentShellActionEntry[] {
  return readRecentActionsCache();
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
  const persisted = enrichRecentActionEntry({
    ...entry,
    occurredAt: entry.occurredAt ?? new Date().toISOString(),
    persistence: entry.outcome?.card.kind === "receipt" ? persistenceState("pending") : (entry.persistence ?? null),
  });
  writeRecentActionsCache(dedupeRecentActions([persisted, ...readRecentActionsCache()]));
  emitRecentShellActionsUpdated();

  if (!shouldPersistDurably(persisted)) {
    return;
  }

  writePendingOutcome(persisted);
  void flushPendingContinuityWrites();
}

export function markUndoActionUnavailable(handle: ExecutableUndoHandle, reason: string): void {
  if (!canUseLocalStorage()) {
    return;
  }
  const targetIdentity = undoHandleIdentity(handle);
  const updated = readRecentActionsCache().map((entry) => {
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
    return enrichRecentActionEntry({
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
    });
  });
  writeRecentActionsCache(updated);
  emitRecentShellActionsUpdated();
}

export function markRerunActionUnavailable(handle: ExecutableRerunHandle, reason: string): void {
  if (!canUseLocalStorage()) {
    return;
  }
  const targetIdentity = rerunHandleIdentity(handle);
  const updated = readRecentActionsCache().map((entry) => {
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
    return enrichRecentActionEntry({
      ...entry,
      outcome: {
        ...outcome,
        card: {
          ...outcome.card,
          actions: nextActions,
        },
      },
    });
  });
  writeRecentActionsCache(updated);
  emitRecentShellActionsUpdated();
}
