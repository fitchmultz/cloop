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
 *   - Hydrate durable recent outcomes and notification records from the backend.
 *   - Queue high-signal landed outcomes and notification-state writes for backend persistence.
 *   - Keep local cache state deterministic for receipts, reruns, undo state,
 *     notification delivery state, and recovery acknowledgements.
 *
 * Scope:
 *   - Frontend continuity persistence helpers and backend sync only.
 *
 * Usage:
 *   - Imported by shell, review-workspace, command-palette, and surface modules.
 *
 * Invariants/Assumptions:
 *   - Backend continuity is the durable authority for recent landed outcomes.
 *   - Continuity baseline snapshots remain browser-local and are not synced.
 *   - Pending unsynced writes must survive hydration and refresh attempts.
 */

import type {
  ContinuityLastSeenBatchUpsertRequest,
  ContinuityLastSeenMarkerResponse,
  ContinuityLocationResponse,
  ContinuityNotificationRecordResponse,
  ContinuityNotificationStateResponse,
  ContinuityNotificationStateUpsertRequest,
  ContinuityOutcomeRecordResponse,
  ContinuityOutcomeWriteRequest,
  ContinuityRecoveryAcknowledgementResponse,
  ContinuityRecoveryAcknowledgementUpsertRequest,
  ContinuitySnapshotResponse,
  ContinuitySuccessorTargetResponse,
  ContinuityWorkflowSummaryPriorStateResponse,
  ContinuityWorkflowSummaryResponse,
  ContinuityWorkflowSummarySignalsResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewCohortResponse,
  LoopReviewResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewSessionSnapshotResponse,
  ResolvedContinuityTargetResponse,
  WorkingSetContextResponse,
} from "./domain";
import type {
  ContinuityBaselineSnapshot,
  ContinuityCardDisplay,
  ContinuityEntityKind,
  ContinuityLastSeenMarker,
  ContinuityNotificationRecord,
  ContinuityNotificationState,
  ContinuityPersistenceState,
  ContinuityResolvedStatus,
  ContinuitySuccessorTarget,
  ContinuityWorkflowSummary,
  ContinuityWorkflowSummaryPriorState,
  DurableRecoveryAcknowledgement,
  ExecutableRerunHandle,
  ExecutableUndoHandle,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  RerunAttemptContract,
  ResolvedContinuityTarget,
  ReviewFocus,
  ShellLocationContract,
  WorkflowThreadKind,
  WorkflowThreadRef,
} from "./contracts-ui";
import {
  fetchContinuitySnapshot,
  persistContinuityOutcome,
  upsertContinuityLastSeen,
  upsertContinuityNotificationState,
  upsertContinuityRecoveryAcknowledgement,
} from "./continuity-api";
import { findRerunAction, findUndoAction } from "./action-receipts";
import { mapApiRerunAction, rerunHandleIdentity } from "./executable-rerun";
import {
  buildFollowThroughActions,
  mapApiDisplayCard,
  mapApiLocation,
  mapApiUndoAction,
  mapApiWorkflowThread,
} from "./follow-through-adapters";
import { undoHandleIdentity } from "./executable-undo";
import {
  isLowSignalNavigationEntry,
  recentShellActionDedupKey,
  resolveContinuityWorkingSetId,
} from "./continuity-outcomes";

const CONTINUITY_BASELINE_STORAGE_KEY = "cloop.continuity.baseline.v2";
const RECENT_ACTIONS_CACHE_KEY = "cloop.continuity.recent-actions.cache.v4";
const WORKFLOW_SUMMARIES_CACHE_KEY = "cloop.continuity.workflow-summaries.cache.v2";
const NOTIFICATION_RECORDS_CACHE_KEY = "cloop.continuity.notification-records.cache.v1";
const LAST_SEEN_MARKERS_CACHE_KEY = "cloop.continuity.last-seen.cache.v1";
const PENDING_CONTINUITY_SYNC_KEY = "cloop.continuity.pending-sync.v2";
const CONTINUITY_RECOVERY_ACKS_KEY = "cloop.continuity.recovery-acks.cache.v2";
const MAX_RECENT_ACTIONS = 24;
const DEDUPE_WINDOW_MS = 15_000;

export const RECENT_SHELL_ACTIONS_UPDATED_EVENT = "cloop:recent-shell-actions-updated";

interface PendingOutcomeWrite {
  kind: "outcome";
  entry: RecentShellActionEntry;
}

interface PendingLastSeenWrite {
  kind: "last_seen";
  markers: ContinuityLastSeenMarker[];
}

interface PendingNotificationStateWrite {
  kind: "notification_state";
  notificationId: string;
  state: ContinuityNotificationState;
}

interface PendingRecoveryAckWrite {
  kind: "recovery_ack";
  acknowledgement: DurableRecoveryAcknowledgement;
}

type PendingContinuityWrite =
  | PendingOutcomeWrite
  | PendingLastSeenWrite
  | PendingNotificationStateWrite
  | PendingRecoveryAckWrite;

export interface ContinuitySnapshotInput {
  metrics: LoopMetricsResponse;
  reviewData: LoopReviewResponse;
  planningSnapshot: PlanningSessionSnapshotResponse | null;
  relationshipSnapshot: RelationshipReviewSessionSnapshotResponse | null;
  enrichmentSnapshot: EnrichmentReviewSessionSnapshotResponse | null;
  allLoops: LoopResponse[];
  workingSetContext: WorkingSetContextResponse | null;
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

function readContinuityRecoveryAcks(): DurableRecoveryAcknowledgement[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<DurableRecoveryAcknowledgement[]>(
    window.localStorage.getItem(CONTINUITY_RECOVERY_ACKS_KEY),
    [],
  );
  return Array.isArray(parsed)
    ? parsed.filter((ack): ack is DurableRecoveryAcknowledgement => {
      return typeof ack?.recoveryKey === "string" && typeof ack?.acknowledgedAtUtc === "string";
    })
    : [];
}

function writeContinuityRecoveryAcks(value: readonly DurableRecoveryAcknowledgement[]): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(CONTINUITY_RECOVERY_ACKS_KEY, JSON.stringify(value));
}

function mergePendingRecoveryAcks(
  snapshotAcks: readonly DurableRecoveryAcknowledgement[],
): DurableRecoveryAcknowledgement[] {
  const merged = new Map(snapshotAcks.map((ack) => [ack.recoveryKey, ack]));
  readPendingContinuityWrites().forEach((write) => {
    if (write.kind === "recovery_ack") {
      merged.set(write.acknowledgement.recoveryKey, write.acknowledgement);
    }
  });
  return [...merged.values()].sort(
    (left, right) => Date.parse(right.acknowledgedAtUtc) - Date.parse(left.acknowledgedAtUtc),
  );
}

export function isContinuityRecoveryAcknowledged(key: string): boolean {
  const normalizedKey = key.trim();
  return normalizedKey.length > 0 && readContinuityRecoveryAcks().some((ack) => ack.recoveryKey === normalizedKey);
}

function writePendingRecoveryAck(acknowledgement: DurableRecoveryAcknowledgement): void {
  const writes = readPendingContinuityWrites().filter((write) => {
    return write.kind !== "recovery_ack" || write.acknowledgement.recoveryKey !== acknowledgement.recoveryKey;
  });
  writes.unshift({ kind: "recovery_ack", acknowledgement });
  writePendingContinuityWrites(writes);
}

export function markContinuityRecoveryAcknowledged(key: string): void {
  const recoveryKey = key.trim();
  if (!recoveryKey || !canUseLocalStorage()) {
    return;
  }
  const acknowledgement: DurableRecoveryAcknowledgement = {
    recoveryKey,
    acknowledgedAtUtc: new Date().toISOString(),
    metadata: {},
  };
  writeContinuityRecoveryAcks(mergePendingRecoveryAcks([
    acknowledgement,
    ...readContinuityRecoveryAcks(),
  ]));
  writePendingRecoveryAck(acknowledgement);
  emitRecentShellActionsUpdated();
  void flushPendingContinuityWrites();
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

function stableSerialize(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableSerialize(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function buildFingerprint(state: Record<string, unknown>): string {
  return stableSerialize(state);
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

function normalizeSuccessorTarget(value: unknown): ContinuitySuccessorTarget | null {
  if (!isRecord(value) || typeof value["outcomeId"] !== "number") {
    return null;
  }
  const resolvedLocation = normalizeLocation(value["resolvedLocation"]);
  if (!resolvedLocation) {
    return null;
  }
  return {
    kind: "replacement",
    outcomeId: value["outcomeId"],
    title: typeof value["title"] === "string" ? value["title"] : "Replacement workflow",
    summary: typeof value["summary"] === "string" ? value["summary"] : null,
    workflowThread: normalizeWorkflowThread(value["workflowThread"]),
    requestedLocation: normalizeLocation(value["requestedLocation"]),
    resolvedLocation,
    status: value["status"] as ContinuityResolvedStatus,
    message: typeof value["message"] === "string" ? value["message"] : null,
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
    successor: normalizeSuccessorTarget(value["successor"]),
  };
}

function normalizeContinuityCardDisplay(value: unknown): ContinuityCardDisplay | null {
  if (!isRecord(value) || typeof value["kind"] !== "string" || typeof value["tone"] !== "string" || typeof value["eyebrow"] !== "string" || typeof value["title"] !== "string" || typeof value["summary"] !== "string" || typeof value["rationale"] !== "string") {
    return null;
  }
  const trustValue = value["trust"];
  if (!isRecord(trustValue)) {
    return null;
  }
  const preview = Array.isArray(value["preview"])
    ? value["preview"].flatMap((item) => {
      if (!isRecord(item) || typeof item["label"] !== "string" || typeof item["value"] !== "string") {
        return [];
      }
      return [{ label: item["label"], value: item["value"] }];
    })
    : [];
  const handoffValue = value["handoff"];
  const workingSetValue = isRecord(handoffValue) && isRecord(handoffValue["workingSet"]) ? handoffValue["workingSet"] : null;
  return {
    kind: value["kind"] as ContinuityCardDisplay["kind"],
    tone: value["tone"] as ContinuityCardDisplay["tone"],
    eyebrow: value["eyebrow"],
    title: value["title"],
    summary: value["summary"],
    rationale: value["rationale"],
    preview,
    trust: {
      generationLabel: stringValue(trustValue["generationLabel"]),
      generationTone: (stringValue(trustValue["generationTone"]) as ContinuityCardDisplay["trust"]["generationTone"]) ?? null,
      contextSources: Array.isArray(trustValue["contextSources"])
        ? trustValue["contextSources"].filter((item): item is string => typeof item === "string")
        : [],
      assumptions: Array.isArray(trustValue["assumptions"])
        ? trustValue["assumptions"].filter((item): item is string => typeof item === "string")
        : [],
      confidenceLabel: stringValue(trustValue["confidenceLabel"]),
      confidenceTone: (stringValue(trustValue["confidenceTone"]) as ContinuityCardDisplay["trust"]["confidenceTone"]) ?? null,
      freshnessLabel: stringValue(trustValue["freshnessLabel"]),
      freshnessTone: (stringValue(trustValue["freshnessTone"]) as ContinuityCardDisplay["trust"]["freshnessTone"]) ?? null,
      rollbackLabel: stringValue(trustValue["rollbackLabel"]),
      rollbackTone: (stringValue(trustValue["rollbackTone"]) as ContinuityCardDisplay["trust"]["rollbackTone"]) ?? null,
      impactSummary: stringValue(trustValue["impactSummary"]),
      impactTone: (stringValue(trustValue["impactTone"]) as ContinuityCardDisplay["trust"]["impactTone"]) ?? null,
    },
    handoff: isRecord(handoffValue)
      ? {
        changeSummary: stringValue(handoffValue["changeSummary"]) ?? "Continue from the landed workflow state.",
        createdResources: Array.isArray(handoffValue["createdResources"])
          ? handoffValue["createdResources"].filter((item): item is string => typeof item === "string")
          : [],
        nextStep: stringValue(handoffValue["nextStep"]),
        breadcrumbs: Array.isArray(handoffValue["breadcrumbs"])
          ? handoffValue["breadcrumbs"].filter((item): item is string => typeof item === "string")
          : [],
        workingSet: workingSetValue && typeof workingSetValue["workingSetId"] === "number" && typeof workingSetValue["workingSetName"] === "string"
          ? {
            workingSetId: workingSetValue["workingSetId"],
            workingSetName: workingSetValue["workingSetName"],
            itemCount: typeof workingSetValue["itemCount"] === "number" ? workingSetValue["itemCount"] : 0,
            missingItemCount: typeof workingSetValue["missingItemCount"] === "number" ? workingSetValue["missingItemCount"] : 0,
          }
          : null,
      }
      : null,
    actionContextLabel: stringValue(value["actionContextLabel"]),
    actionWarning: stringValue(value["actionWarning"]),
  };
}

function parseUndoHandle(value: unknown): ExecutableUndoHandle | null {
  if (!isRecord(value) || typeof value["kind"] !== "string") {
    return null;
  }
  if (value["kind"] === "loop_event") {
    const loopId = integerValue(value["loopId"]);
    const expectedEventId = integerValue(value["expectedEventId"]);
    if (loopId == null || expectedEventId == null) {
      return null;
    }
    return {
      kind: "loop_event",
      loopId,
      expectedEventId,
      eventType: stringValue(value["eventType"]),
      claimToken: stringValue(value["claimToken"]),
    };
  }
  if (value["kind"] === "planning_run") {
    const sessionId = integerValue(value["sessionId"]);
    const runId = integerValue(value["runId"]);
    const checkpointIndex = integerValue(value["checkpointIndex"]);
    const checkpointTitle = stringValue(value["checkpointTitle"]);
    const actionCount = integerValue(value["actionCount"]);
    if (sessionId == null || runId == null || checkpointIndex == null || checkpointTitle == null || actionCount == null) {
      return null;
    }
    return {
      kind: "planning_run",
      sessionId,
      runId,
      checkpointIndex,
      checkpointTitle,
      actionCount,
      bestEffort: value["bestEffort"] === true,
    };
  }
  if (value["kind"] === "working_set_event") {
    const expectedEventId = integerValue(value["expectedEventId"]);
    if (expectedEventId == null) {
      return null;
    }
    return {
      kind: "working_set_event",
      expectedEventId,
      eventType: stringValue(value["eventType"]),
      workingSetId: integerValue(value["workingSetId"]),
      workingSetName: stringValue(value["workingSetName"]),
    };
  }
  if (value["kind"] === "relationship_decision") {
    const sessionId = integerValue(value["sessionId"]);
    const loopId = integerValue(value["loopId"]);
    const candidateLoopId = integerValue(value["candidateLoopId"]);
    const expectedPairState = isRecord(value["expectedPairState"]) ? value["expectedPairState"] : null;
    const restorePairState = isRecord(value["restorePairState"]) ? value["restorePairState"] : null;
    if (sessionId == null || loopId == null || candidateLoopId == null || !expectedPairState || !restorePairState) {
      return null;
    }
    const parseState = (raw: unknown) => isRecord(raw) && typeof raw["state"] === "string"
      ? {
          state: raw["state"] as "active" | "dismissed" | "resolved",
          confidence: typeof raw["confidence"] === "number" ? raw["confidence"] : null,
          source: stringValue(raw["source"]),
        }
      : null;
    return {
      kind: "relationship_decision",
      sessionId,
      loopId,
      candidateLoopId,
      expectedPairState: {
        duplicate: parseState(expectedPairState["duplicate"]),
        related: parseState(expectedPairState["related"]),
      },
      restorePairState: {
        duplicate: parseState(restorePairState["duplicate"]),
        related: parseState(restorePairState["related"]),
      },
    };
  }
  return null;
}

function parseUndoAction(value: unknown): OperatorActionCardUndoAction | null {
  if (!isRecord(value) || typeof value["label"] !== "string" || typeof value["description"] !== "string") {
    return null;
  }
  const undo = parseUndoHandle(value["undo"]);
  if (!undo) {
    return null;
  }
  return {
    type: "undo",
    label: value["label"],
    variant: value["variant"] === "primary" ? "primary" : "secondary",
    description: value["description"],
    disabledReason: stringValue(value["disabledReason"]),
    undo,
    requiresConfirmation: value["requiresConfirmation"] === true,
    confirmTitle: stringValue(value["confirmTitle"]),
    confirmDescription: stringValue(value["confirmDescription"]),
    successLocation: normalizeLocation(value["successLocation"]),
  };
}

function parseRerunHandle(value: unknown): ExecutableRerunHandle | null {
  if (!isRecord(value) || typeof value["kind"] !== "string") {
    return null;
  }
  if (value["kind"] === "planning_session") {
    const sessionId = integerValue(value["sessionId"]);
    const sessionName = stringValue(value["sessionName"]);
    if (sessionId == null || sessionName == null) {
      return null;
    }
    return {
      kind: "planning_session",
      sessionId,
      sessionName,
    };
  }
  if (value["kind"] === "review_session") {
    const sessionId = integerValue(value["sessionId"]);
    const sessionName = stringValue(value["sessionName"]);
    const reviewFocus = value["reviewFocus"];
    if (sessionId == null || sessionName == null || (reviewFocus !== "relationship" && reviewFocus !== "enrichment")) {
      return null;
    }
    return {
      kind: "review_session",
      reviewFocus,
      sessionId,
      sessionName,
    };
  }
  if (value["kind"] === "recall_query") {
    const query = stringValue(value["query"]);
    const recallTool = value["recallTool"];
    if (query == null || (recallTool !== "chat" && recallTool !== "rag")) {
      return null;
    }
    return {
      kind: "recall_query",
      recallTool,
      query,
      workingSetId: integerValue(value["workingSetId"]),
      includeLoopContext: value["includeLoopContext"] === true ? true : undefined,
      includeMemoryContext: value["includeMemoryContext"] === true ? true : undefined,
      includeRagContext: value["includeRagContext"] === true ? true : undefined,
    };
  }
  return null;
}

function parseRerunAttemptContract(value: unknown): RerunAttemptContract | null {
  if (!isRecord(value) || typeof value["mode"] !== "string" || typeof value["provenanceLabel"] !== "string" || typeof value["strategySummary"] !== "string") {
    return null;
  }
  if (value["mode"] !== "refresh" && value["mode"] !== "rerun") {
    return null;
  }
  const postRunValue = value["postRun"];
  if (!isRecord(postRunValue) || typeof postRunValue["summary"] !== "string") {
    return null;
  }
  return {
    mode: value["mode"],
    provenanceLabel: value["provenanceLabel"],
    freshnessLabel: stringValue(value["freshnessLabel"]),
    strategySummary: value["strategySummary"],
    strictInvariants: Array.isArray(value["strictInvariants"])
      ? value["strictInvariants"].filter((item): item is string => typeof item === "string")
      : [],
    mayVary: Array.isArray(value["mayVary"])
      ? value["mayVary"].filter((item): item is string => typeof item === "string")
      : [],
    postRun: {
      summary: postRunValue["summary"],
      location: normalizeLocation(postRunValue["location"]),
    },
  };
}

function parseRerunAction(value: unknown): OperatorActionCardRerunAction | null {
  if (!isRecord(value) || typeof value["label"] !== "string" || typeof value["description"] !== "string") {
    return null;
  }
  const rerun = parseRerunHandle(value["rerun"]);
  const contract = parseRerunAttemptContract(value["contract"]);
  if (!rerun || !contract) {
    return null;
  }
  return {
    type: "rerun",
    label: value["label"],
    variant: value["variant"] === "primary" ? "primary" : "secondary",
    description: value["description"],
    disabledReason: stringValue(value["disabledReason"]),
    rerun,
    contract,
  };
}

function parseContinuityRankingSignals(value: unknown) {
  if (!isRecord(value) || typeof value["driftSeverity"] !== "string") {
    return null;
  }
  return {
    driftSeverity: value["driftSeverity"] as ContinuityWorkflowSummary["rankingSignals"]["driftSeverity"],
    driftScore: integerValue(value["driftScore"]) ?? 0,
    workingSetRelevant: value["workingSetRelevant"] === true,
    downstreamReady: value["downstreamReady"] === true,
    degraded: value["degraded"] === true,
    recencyTieBreaker: integerValue(value["recencyTieBreaker"]) ?? 0,
  } satisfies ContinuityWorkflowSummary["rankingSignals"];
}

function parseContinuityWorkflowSummaryPriorState(
  value: unknown,
): ContinuityWorkflowSummaryPriorState | null {
  if (!isRecord(value) || typeof value["kind"] !== "string" || typeof value["title"] !== "string" || typeof value["summary"] !== "string") {
    return null;
  }
  if (value["kind"] !== "replaced" && value["kind"] !== "gone") {
    return null;
  }
  return {
    kind: value["kind"],
    title: value["title"],
    summary: value["summary"],
  };
}

function parseContinuityWorkflowSummary(value: unknown): ContinuityWorkflowSummary | null {
  if (!isRecord(value) || typeof value["id"] !== "string" || typeof value["source"] !== "string" || typeof value["rank"] !== "number" || typeof value["occurredAt"] !== "string") {
    return null;
  }
  const workflowThread = normalizeWorkflowThread(value["workflowThread"]);
  const resolvedResume = normalizeResolvedTarget(value["resolvedResume"]);
  const rankingSignals = parseContinuityRankingSignals(value["rankingSignals"]);
  const displayCard = normalizeContinuityCardDisplay(value["displayCard"]);
  if (!workflowThread || !resolvedResume || !rankingSignals || !displayCard) {
    return null;
  }
  return {
    id: value["id"],
    source: value["source"] as ContinuityWorkflowSummary["source"],
    rank: value["rank"],
    rankingSignals,
    workflowThread,
    representativeOutcomeId: integerValue(value["representativeOutcomeId"]),
    latestOutcomeId: integerValue(value["latestOutcomeId"]),
    occurredAt: value["occurredAt"],
    outcomeCount: integerValue(value["outcomeCount"]) ?? 0,
    outcomePreviewTitles: Array.isArray(value["outcomePreviewTitles"])
      ? value["outcomePreviewTitles"].filter((item): item is string => typeof item === "string")
      : [],
    requestedResumeLocation: normalizeLocation(value["requestedResumeLocation"]),
    resolvedResume,
    displayTitle: typeof value["displayTitle"] === "string" ? value["displayTitle"] : workflowThread.title,
    displaySummary: typeof value["displaySummary"] === "string" ? value["displaySummary"] : workflowThread.summary ?? "",
    displayCard,
    undoAction: parseUndoAction(value["undoAction"]),
    rerunAction: parseRerunAction(value["rerunAction"]),
    workingSetId: integerValue(value["workingSetId"]),
    workingSetName: stringValue(value["workingSetName"]),
    degraded: value["degraded"] === true,
    degradedLabel: stringValue(value["degradedLabel"]),
    whyNow: Array.isArray(value["whyNow"])
      ? value["whyNow"].filter((item): item is string => typeof item === "string")
      : [],
    changedSinceLastSeen: Array.isArray(value["changedSinceLastSeen"])
      ? value["changedSinceLastSeen"].filter((item): item is string => typeof item === "string")
      : [],
    priorState: parseContinuityWorkflowSummaryPriorState(value["priorState"]),
  };
}

function emptyNotificationState(): ContinuityNotificationState {
  return {
    inboxedAtUtc: null,
    seenAtUtc: null,
    acknowledgedAtUtc: null,
    suppressedUntilUtc: null,
  };
}

function parseContinuityNotificationState(value: unknown): ContinuityNotificationState {
  if (!isRecord(value)) {
    return emptyNotificationState();
  }
  return {
    inboxedAtUtc: stringValue(value["inboxedAtUtc"]),
    seenAtUtc: stringValue(value["seenAtUtc"]),
    acknowledgedAtUtc: stringValue(value["acknowledgedAtUtc"]),
    suppressedUntilUtc: stringValue(value["suppressedUntilUtc"]),
  };
}

function parseContinuityNotificationRecord(value: unknown): ContinuityNotificationRecord | null {
  if (!isRecord(value) || typeof value["id"] !== "string" || typeof value["title"] !== "string" || typeof value["body"] !== "string" || typeof value["severity"] !== "string") {
    return null;
  }
  const workflowThread = normalizeWorkflowThread(value["workflowThread"]);
  const resolvedLocation = normalizeLocation(value["resolvedLocation"]);
  if (!workflowThread || !resolvedLocation) {
    return null;
  }
  if (value["severity"] !== "info" && value["severity"] !== "warning" && value["severity"] !== "alert") {
    return null;
  }
  return {
    id: value["id"],
    title: value["title"],
    body: value["body"],
    severity: value["severity"],
    workflowThread,
    resolvedLocation,
    state: parseContinuityNotificationState(value["state"]),
  };
}

function parseRecentShellActionEntry(value: unknown): RecentShellActionEntry | null {
  if (!isRecord(value) || typeof value["kind"] !== "string" || typeof value["label"] !== "string" || typeof value["description"] !== "string" || typeof value["occurredAt"] !== "string") {
    return null;
  }

  const outcome = isRecord(value["outcome"]) ? value["outcome"] : null;
  const displayCard = outcome ? normalizeContinuityCardDisplay(outcome["card"]) : null;
  const undoAction = outcome ? parseUndoAction(outcome["undoAction"]) : null;
  const rerunAction = outcome ? parseRerunAction(outcome["rerunAction"]) : null;
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

  if (!outcome || !displayCard) {
    return entry;
  }

  const rawCardId = stringValue(isRecord(outcome["card"]) ? outcome["card"]["id"] : null);
  entry.outcome = {
    card: buildOutcomeCardFromDisplayCard(displayCard, null, {
      ...(rawCardId ? { id: rawCardId } : {}),
      actions: outcomeCardFollowThroughActions({ undoAction, rerunAction }),
    }),
    resumeLocation: normalizeLocation(outcome["resumeLocation"]),
    rollbackLabel: typeof outcome["rollbackLabel"] === "string" ? outcome["rollbackLabel"] : null,
    undoAction,
    rerunAction,
    workflowThread: normalizeWorkflowThread(outcome["workflowThread"]),
    resolvedResume: normalizeResolvedTarget(outcome["resolvedResume"]),
  };
  return entry;
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
    if (item["kind"] === "last_seen" && Array.isArray(item["markers"])) {
      writes.push({
        kind: "last_seen",
        markers: item["markers"].flatMap((marker) => {
          if (!isRecord(marker) || typeof marker["entityKind"] !== "string" || typeof marker["entityKey"] !== "string") {
            return [];
          }
          return [{
            entityKind: marker["entityKind"] as ContinuityEntityKind,
            entityKey: marker["entityKey"],
            observedAtUtc: stringValue(marker["observedAtUtc"]) ?? new Date().toISOString(),
            observedFingerprint: stringValue(marker["observedFingerprint"]) ?? "{}",
            workingSetId: integerValue(marker["workingSetId"]),
            workflowThreadId: stringValue(marker["workflowThreadId"]),
            observedState: isRecord(marker["observedState"]) ? marker["observedState"] : {},
            metadata: isRecord(marker["metadata"]) ? marker["metadata"] : {},
          } satisfies ContinuityLastSeenMarker];
        }),
      });
      return;
    }
    if (item["kind"] === "notification_state" && typeof item["notificationId"] === "string") {
      writes.push({
        kind: "notification_state",
        notificationId: item["notificationId"],
        state: parseContinuityNotificationState(item["state"]),
      });
      return;
    }
    if (item["kind"] === "recovery_ack" && isRecord(item["acknowledgement"])) {
      const acknowledgement = item["acknowledgement"];
      const recoveryKey = stringValue(acknowledgement["recoveryKey"]);
      const acknowledgedAtUtc = stringValue(acknowledgement["acknowledgedAtUtc"]);
      if (recoveryKey && acknowledgedAtUtc) {
        writes.push({
          kind: "recovery_ack",
          acknowledgement: {
            recoveryKey,
            acknowledgedAtUtc,
            metadata: isRecord(acknowledgement["metadata"]) ? acknowledgement["metadata"] : {},
          },
        });
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

export function readContinuityWorkflowSummaries(): ContinuityWorkflowSummary[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<unknown[]>(window.localStorage.getItem(WORKFLOW_SUMMARIES_CACHE_KEY), []);
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed
    .map((item) => parseContinuityWorkflowSummary(item))
    .filter((item): item is ContinuityWorkflowSummary => item !== null);
}

function writeContinuityWorkflowSummaries(summaries: readonly ContinuityWorkflowSummary[]): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(WORKFLOW_SUMMARIES_CACHE_KEY, JSON.stringify(summaries));
}

export function readContinuityNotificationRecords(): ContinuityNotificationRecord[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<unknown[]>(window.localStorage.getItem(NOTIFICATION_RECORDS_CACHE_KEY), []);
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed
    .map((item) => parseContinuityNotificationRecord(item))
    .filter((item): item is ContinuityNotificationRecord => item !== null);
}

function writeContinuityNotificationRecords(records: readonly ContinuityNotificationRecord[]): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(NOTIFICATION_RECORDS_CACHE_KEY, JSON.stringify(records));
}

export function readContinuityLastSeenMarkers(): ContinuityLastSeenMarker[] {
  if (!canUseLocalStorage()) {
    return [];
  }
  const parsed = safeJsonParse<unknown[]>(window.localStorage.getItem(LAST_SEEN_MARKERS_CACHE_KEY), []);
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed.flatMap((marker) => {
    if (!isRecord(marker) || typeof marker["entityKind"] !== "string" || typeof marker["entityKey"] !== "string") {
      return [];
    }
    return [{
      entityKind: marker["entityKind"] as ContinuityEntityKind,
      entityKey: marker["entityKey"],
      observedAtUtc: stringValue(marker["observedAtUtc"]) ?? new Date().toISOString(),
      observedFingerprint: stringValue(marker["observedFingerprint"]) ?? "{}",
      workingSetId: integerValue(marker["workingSetId"]),
      workflowThreadId: stringValue(marker["workflowThreadId"]),
      observedState: isRecord(marker["observedState"]) ? marker["observedState"] : {},
      metadata: isRecord(marker["metadata"]) ? marker["metadata"] : {},
    } satisfies ContinuityLastSeenMarker];
  });
}

function writeContinuityLastSeenMarkers(markers: readonly ContinuityLastSeenMarker[]): void {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.setItem(LAST_SEEN_MARKERS_CACHE_KEY, JSON.stringify(markers));
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
  const undoAction = entry.outcome.undoAction ?? findUndoAction(entry.outcome.card);
  const rerunAction = entry.outcome.rerunAction ?? findRerunAction(entry.outcome.card);
  return {
    ...entry,
    outcome: {
      ...entry.outcome,
      card: {
        ...entry.outcome.card,
        actions: outcomeCardFollowThroughActions({ undoAction, rerunAction }),
      },
      undoAction,
      rerunAction,
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

export function mapLocationFromApi(location: ContinuityLocationResponse | null | undefined): ShellLocationContract | null {
  return mapApiLocation(location);
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

function mapUndoActionToApi(action: OperatorActionCardUndoAction | null | undefined) {
  if (!action) {
    return null;
  }
  if (action.undo.kind === "loop_event") {
    return {
      label: action.label,
      description: action.description,
      undo: {
        kind: "loop_event" as const,
        loop_id: action.undo.loopId,
        expected_event_id: action.undo.expectedEventId,
        event_type: action.undo.eventType ?? null,
        claim_token: action.undo.claimToken ?? null,
      },
      requires_confirmation: action.requiresConfirmation ?? false,
      confirm_title: action.confirmTitle ?? null,
      confirm_description: action.confirmDescription ?? null,
      success_location: mapLocationToApi(action.successLocation ?? null),
    };
  }
  if (action.undo.kind === "planning_run") {
    return {
      label: action.label,
      description: action.description,
      undo: {
        kind: "planning_run" as const,
        session_id: action.undo.sessionId,
        run_id: action.undo.runId,
        checkpoint_index: action.undo.checkpointIndex,
        checkpoint_title: action.undo.checkpointTitle,
        action_count: action.undo.actionCount,
        best_effort: action.undo.bestEffort,
      },
      requires_confirmation: action.requiresConfirmation ?? false,
      confirm_title: action.confirmTitle ?? null,
      confirm_description: action.confirmDescription ?? null,
      success_location: mapLocationToApi(action.successLocation ?? null),
    };
  }
  if (action.undo.kind === "relationship_decision") {
    return {
      label: action.label,
      description: action.description,
      undo: {
        kind: "relationship_decision" as const,
        session_id: action.undo.sessionId,
        loop_id: action.undo.loopId,
        candidate_loop_id: action.undo.candidateLoopId,
        expected_pair_state: {
          duplicate: action.undo.expectedPairState.duplicate
            ? {
                state: action.undo.expectedPairState.duplicate.state,
                confidence: action.undo.expectedPairState.duplicate.confidence,
                source: action.undo.expectedPairState.duplicate.source,
              }
            : null,
          related: action.undo.expectedPairState.related
            ? {
                state: action.undo.expectedPairState.related.state,
                confidence: action.undo.expectedPairState.related.confidence,
                source: action.undo.expectedPairState.related.source,
              }
            : null,
        },
        restore_pair_state: {
          duplicate: action.undo.restorePairState.duplicate
            ? {
                state: action.undo.restorePairState.duplicate.state,
                confidence: action.undo.restorePairState.duplicate.confidence,
                source: action.undo.restorePairState.duplicate.source,
              }
            : null,
          related: action.undo.restorePairState.related
            ? {
                state: action.undo.restorePairState.related.state,
                confidence: action.undo.restorePairState.related.confidence,
                source: action.undo.restorePairState.related.source,
              }
            : null,
        },
      },
      requires_confirmation: action.requiresConfirmation ?? false,
      confirm_title: action.confirmTitle ?? null,
      confirm_description: action.confirmDescription ?? null,
      success_location: mapLocationToApi(action.successLocation ?? null),
    };
  }
  return {
    label: action.label,
    description: action.description,
    undo: {
      kind: "working_set_event" as const,
      expected_event_id: action.undo.expectedEventId,
      event_type: action.undo.eventType ?? null,
      working_set_id: action.undo.workingSetId ?? null,
      working_set_name: action.undo.workingSetName ?? null,
    },
    requires_confirmation: action.requiresConfirmation ?? false,
    confirm_title: action.confirmTitle ?? null,
    confirm_description: action.confirmDescription ?? null,
    success_location: mapLocationToApi(action.successLocation ?? null),
  };
}

function mapRerunActionToApi(action: OperatorActionCardRerunAction | null | undefined) {
  if (!action) {
    return null;
  }
  if (action.rerun.kind === "planning_session") {
    return {
      label: action.label,
      description: action.description,
      rerun: {
        kind: "planning_session" as const,
        session_id: action.rerun.sessionId,
        session_name: action.rerun.sessionName,
      },
      contract: {
        mode: action.contract.mode,
        provenance_label: action.contract.provenanceLabel,
        freshness_label: action.contract.freshnessLabel ?? null,
        strategy_summary: action.contract.strategySummary,
        strict_invariants: action.contract.strictInvariants,
        may_vary: action.contract.mayVary,
        post_run: {
          summary: action.contract.postRun.summary,
          location: mapLocationToApi(action.contract.postRun.location),
        },
      },
    };
  }
  if (action.rerun.kind === "review_session") {
    return {
      label: action.label,
      description: action.description,
      rerun: {
        kind: "review_session" as const,
        review_focus: action.rerun.reviewFocus,
        session_id: action.rerun.sessionId,
        session_name: action.rerun.sessionName,
      },
      contract: {
        mode: action.contract.mode,
        provenance_label: action.contract.provenanceLabel,
        freshness_label: action.contract.freshnessLabel ?? null,
        strategy_summary: action.contract.strategySummary,
        strict_invariants: action.contract.strictInvariants,
        may_vary: action.contract.mayVary,
        post_run: {
          summary: action.contract.postRun.summary,
          location: mapLocationToApi(action.contract.postRun.location),
        },
      },
    };
  }
  return {
    label: action.label,
    description: action.description,
    rerun: {
      kind: "recall_query" as const,
      recall_tool: action.rerun.recallTool,
      query: action.rerun.query,
      working_set_id: action.rerun.workingSetId ?? null,
      include_loop_context: action.rerun.includeLoopContext ?? null,
      include_memory_context: action.rerun.includeMemoryContext ?? null,
      include_rag_context: action.rerun.includeRagContext ?? null,
    },
    contract: {
      mode: action.contract.mode,
      provenance_label: action.contract.provenanceLabel,
      freshness_label: action.contract.freshnessLabel ?? null,
      strategy_summary: action.contract.strategySummary,
      strict_invariants: action.contract.strictInvariants,
      may_vary: action.contract.mayVary,
      post_run: {
        summary: action.contract.postRun.summary,
        location: mapLocationToApi(action.contract.postRun.location),
      },
    },
  };
}

export function mapWorkflowThreadFromApi(thread: ContinuityOutcomeRecordResponse["workflow_thread"]): WorkflowThreadRef {
  return mapApiWorkflowThread(thread);
}

export function mapContinuityCardDisplayFromApi(
  response: ContinuityOutcomeRecordResponse["display_card"] | ContinuityWorkflowSummaryResponse["display_card"],
): ContinuityCardDisplay {
  return mapApiDisplayCard(response);
}

function outcomeCardFollowThroughActions(input: {
  undoAction: OperatorActionCardUndoAction | null | undefined;
  rerunAction: OperatorActionCardRerunAction | null | undefined;
}): OperatorActionCardAction[] {
  return buildFollowThroughActions(input);
}

export function buildOutcomeCardFromDisplayCard(
  displayCard: ContinuityCardDisplay,
  outcomeId: number | null,
  options: { id?: string; actions?: readonly OperatorActionCardAction[] } = {},
): OperatorActionCard {
  return {
    id: options.id ?? (outcomeId != null ? `continuity-outcome-${outcomeId}` : "continuity-outcome"),
    kind: displayCard.kind,
    tone: displayCard.tone,
    eyebrow: displayCard.eyebrow,
    title: displayCard.title,
    summary: displayCard.summary,
    rationale: displayCard.rationale,
    preview: displayCard.preview,
    trust: displayCard.trust,
    handoff: displayCard.handoff,
    actionContextLabel: displayCard.actionContextLabel ?? null,
    actionWarning: displayCard.actionWarning ?? null,
    recovery: null,
    actions: [...(options.actions ?? [])],
  };
}

function mapDisplayCardToApi(
  card: OperatorActionCard,
): ContinuityOutcomeWriteRequest["display_card"] {
  return {
    kind: card.kind,
    tone: card.tone,
    eyebrow: card.eyebrow,
    title: card.title,
    summary: card.summary,
    rationale: card.rationale,
    preview: card.preview.map((item) => ({
      label: item.label,
      value: item.value,
    })),
    trust: {
      generation_label: card.trust.generationLabel ?? null,
      generation_tone: card.trust.generationTone ?? null,
      context_sources: card.trust.contextSources ?? [],
      assumptions: card.trust.assumptions ?? [],
      confidence_label: card.trust.confidenceLabel ?? null,
      confidence_tone: card.trust.confidenceTone ?? null,
      freshness_label: card.trust.freshnessLabel ?? null,
      freshness_tone: card.trust.freshnessTone ?? null,
      rollback_label: card.trust.rollbackLabel ?? null,
      rollback_tone: card.trust.rollbackTone ?? null,
      impact_summary: card.trust.impactSummary ?? null,
      impact_tone: card.trust.impactTone ?? null,
    },
    handoff: card.handoff
      ? {
        change_summary: card.handoff.changeSummary,
        created_resources: card.handoff.createdResources ?? [],
        next_step: card.handoff.nextStep ?? null,
        breadcrumbs: card.handoff.breadcrumbs ?? [],
        working_set: card.handoff.workingSet
          ? {
            working_set_id: card.handoff.workingSet.workingSetId,
            working_set_name: card.handoff.workingSet.workingSetName,
            item_count: card.handoff.workingSet.itemCount ?? 0,
            missing_item_count: card.handoff.workingSet.missingItemCount ?? 0,
          }
          : null,
      }
      : null,
    action_context_label: card.actionContextLabel ?? null,
    action_warning: card.actionWarning ?? null,
  };
}

function mapSuccessorFromApi(
  successor: ContinuitySuccessorTargetResponse | null | undefined,
): ContinuitySuccessorTarget | null {
  if (!successor) {
    return null;
  }
  return {
    kind: "replacement",
    outcomeId: successor.outcome_id,
    title: successor.title,
    summary: successor.summary ?? null,
    workflowThread: successor.workflow_thread
      ? {
        id: successor.workflow_thread.id,
        kind: successor.workflow_thread.kind,
        title: successor.workflow_thread.title,
        summary: successor.workflow_thread.summary ?? null,
        parentOutcomeId: successor.workflow_thread.parent_outcome_id ?? null,
      }
      : null,
    requestedLocation: mapLocationFromApi(successor.requested_location),
    resolvedLocation: mapLocationFromApi(successor.resolved_location)!,
    status: successor.status,
    message: successor.message ?? null,
  };
}

function mapResolvedTargetFromApi(
  resolved: ResolvedContinuityTargetResponse,
): ResolvedContinuityTarget {
  return {
    requestedLocation: mapLocationFromApi(resolved.requested_location),
    resolvedLocation: mapLocationFromApi(resolved.resolved_location)!,
    status: resolved.status,
    message: resolved.message ?? null,
    successor: mapSuccessorFromApi(resolved.successor),
  };
}

export function mapUndoActionFromApi(
  action: ContinuityOutcomeRecordResponse["undo_action"] | ContinuityWorkflowSummaryResponse["undo_action"] | null | undefined,
): OperatorActionCardUndoAction | null {
  return mapApiUndoAction(action);
}

function mapRerunActionFromApi(
  action: ContinuityOutcomeRecordResponse["rerun_action"] | ContinuityWorkflowSummaryResponse["rerun_action"] | null | undefined,
): OperatorActionCardRerunAction | null {
  return mapApiRerunAction(action);
}

function mapPersistedOutcomeToRecentEntry(response: ContinuityOutcomeRecordResponse): RecentShellActionEntry {
  const displayCard = mapContinuityCardDisplayFromApi(response.display_card);
  const card = buildOutcomeCardFromDisplayCard(displayCard, response.id);
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
      undoAction: mapUndoActionFromApi(response.undo_action),
      rerunAction: mapRerunActionFromApi(response.rerun_action),
      workflowThread: mapWorkflowThreadFromApi(response.workflow_thread),
      resolvedResume: mapResolvedTargetFromApi(response.resolved_resume),
    },
  });
}

function mapLastSeenMarkerResponse(marker: ContinuityLastSeenMarkerResponse): ContinuityLastSeenMarker {
  return {
    entityKind: marker.entity_kind,
    entityKey: marker.entity_key,
    observedAtUtc: marker.observed_at_utc,
    observedFingerprint: marker.observed_fingerprint,
    workingSetId: marker.working_set_id ?? null,
    workflowThreadId: marker.workflow_thread_id ?? null,
    observedState: marker.observed_state ?? {},
    metadata: marker.metadata ?? {},
  };
}

function mapRecoveryAcknowledgementResponse(
  response: ContinuityRecoveryAcknowledgementResponse,
): DurableRecoveryAcknowledgement {
  return {
    recoveryKey: response.recovery_key,
    acknowledgedAtUtc: response.acknowledged_at_utc,
    metadata: response.metadata ?? {},
  };
}

function mapNotificationStateResponse(
  response: ContinuityNotificationStateResponse | null | undefined,
): ContinuityNotificationState {
  return {
    inboxedAtUtc: response?.inboxed_at_utc ?? null,
    seenAtUtc: response?.seen_at_utc ?? null,
    acknowledgedAtUtc: response?.acknowledged_at_utc ?? null,
    suppressedUntilUtc: response?.suppressed_until_utc ?? null,
  };
}

function mapWorkflowSummarySignalsResponse(
  response: ContinuityWorkflowSummarySignalsResponse,
): ContinuityWorkflowSummary["rankingSignals"] {
  return {
    driftSeverity: response.drift_severity,
    driftScore: response.drift_score,
    workingSetRelevant: response.working_set_relevant,
    downstreamReady: response.downstream_ready,
    degraded: response.degraded,
    recencyTieBreaker: response.recency_tie_breaker,
  };
}

function mapWorkflowSummaryPriorStateResponse(
  response: ContinuityWorkflowSummaryPriorStateResponse | null | undefined,
): ContinuityWorkflowSummaryPriorState | null {
  if (!response) {
    return null;
  }
  return {
    kind: response.kind,
    title: response.title,
    summary: response.summary,
  };
}

function mapWorkflowSummaryResponse(
  response: ContinuityWorkflowSummaryResponse,
): ContinuityWorkflowSummary {
  return {
    id: response.id,
    source: response.source,
    rank: response.rank,
    rankingSignals: mapWorkflowSummarySignalsResponse(response.ranking_signals),
    workflowThread: {
      id: response.workflow_thread.id,
      kind: response.workflow_thread.kind,
      title: response.workflow_thread.title,
      summary: response.workflow_thread.summary ?? null,
      parentOutcomeId: response.workflow_thread.parent_outcome_id ?? null,
    },
    representativeOutcomeId: response.representative_outcome_id ?? null,
    latestOutcomeId: response.latest_outcome_id ?? null,
    occurredAt: response.occurred_at_utc,
    outcomeCount: response.outcome_count,
    outcomePreviewTitles: response.outcome_preview_titles ?? [],
    requestedResumeLocation: mapLocationFromApi(response.requested_resume_location),
    resolvedResume: mapResolvedTargetFromApi(response.resolved_resume),
    displayTitle: response.display_title,
    displaySummary: response.display_summary,
    displayCard: mapContinuityCardDisplayFromApi(response.display_card),
    undoAction: mapUndoActionFromApi(response.undo_action),
    rerunAction: mapRerunActionFromApi(response.rerun_action),
    workingSetId: response.working_set_id ?? null,
    workingSetName: response.working_set_name ?? null,
    degraded: Boolean(response.degraded),
    degradedLabel: response.degraded_label ?? null,
    whyNow: response.why_now ?? [],
    changedSinceLastSeen: response.changed_since_last_seen ?? [],
    priorState: mapWorkflowSummaryPriorStateResponse(response.prior_state),
  };
}

function mapNotificationRecordResponse(
  response: ContinuityNotificationRecordResponse,
): ContinuityNotificationRecord {
  return {
    id: response.id,
    title: response.title,
    body: response.body,
    severity: response.severity,
    workflowThread: {
      id: response.workflow_thread.id,
      kind: response.workflow_thread.kind,
      title: response.workflow_thread.title,
      summary: response.workflow_thread.summary ?? null,
      parentOutcomeId: response.workflow_thread.parent_outcome_id ?? null,
    },
    resolvedLocation: mapLocationFromApi(response.resolved_location)!,
    state: mapNotificationStateResponse(response.state),
  };
}

function mergePendingEntries(snapshotEntries: readonly RecentShellActionEntry[]): RecentShellActionEntry[] {
  const pendingEntries = readPendingContinuityWrites()
    .flatMap((write) => write.kind === "outcome" ? [write.entry] : [])
    .map((entry) => enrichRecentActionEntry(entry));
  return dedupeRecentActions([...pendingEntries, ...snapshotEntries]);
}

function mergePendingLastSeenMarkers(
  snapshotMarkers: readonly ContinuityLastSeenMarker[],
): ContinuityLastSeenMarker[] {
  const merged = new Map(snapshotMarkers.map((marker) => [`${marker.entityKind}:${marker.entityKey}`, marker]));
  readPendingContinuityWrites().forEach((write) => {
    if (write.kind !== "last_seen") {
      return;
    }
    write.markers.forEach((marker) => {
      merged.set(`${marker.entityKind}:${marker.entityKey}`, marker);
    });
  });
  return [...merged.values()].sort((left, right) => Date.parse(right.observedAtUtc) - Date.parse(left.observedAtUtc));
}

function mergePendingNotificationRecords(
  snapshotRecords: readonly ContinuityNotificationRecord[],
): ContinuityNotificationRecord[] {
  const merged = new Map(snapshotRecords.map((record) => [record.id, record]));
  readPendingContinuityWrites().forEach((write) => {
    if (write.kind !== "notification_state") {
      return;
    }
    const existing = merged.get(write.notificationId);
    if (!existing) {
      return;
    }
    merged.set(write.notificationId, {
      ...existing,
      state: write.state,
    });
  });
  return [...merged.values()];
}

function applyContinuitySnapshot(snapshot: ContinuitySnapshotResponse): void {
  const snapshotEntries = (snapshot.outcomes ?? []).map((item) => mapPersistedOutcomeToRecentEntry(item));
  const workflowSummaries = (snapshot.workflow_summaries ?? []).map((item) =>
    mapWorkflowSummaryResponse(item),
  );
  const notificationRecords = (snapshot.notification_records ?? []).map((item) =>
    mapNotificationRecordResponse(item),
  );
  const lastSeenMarkers = (snapshot.last_seen_markers ?? []).map((item) => mapLastSeenMarkerResponse(item));
  const recoveryAcks = (snapshot.recovery_acknowledgements ?? []).map((item) =>
    mapRecoveryAcknowledgementResponse(item),
  );
  writeRecentActionsCache(mergePendingEntries(snapshotEntries));
  writeContinuityWorkflowSummaries(workflowSummaries);
  writeContinuityNotificationRecords(mergePendingNotificationRecords(notificationRecords));
  writeContinuityLastSeenMarkers(mergePendingLastSeenMarkers(lastSeenMarkers));
  writeContinuityRecoveryAcks(mergePendingRecoveryAcks(recoveryAcks));
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
    display_card: mapDisplayCardToApi(entry.outcome.card),
    undo_action: mapUndoActionToApi(entry.outcome.undoAction),
    rerun_action: mapRerunActionToApi(entry.outcome.rerunAction),
    resume_location: mapLocationToApi(entry.outcome.resumeLocation),
    working_set_id: resolveContinuityWorkingSetId(entry),
    workflow_thread: mapWorkflowThreadToApi(workflowThread),
    dedupe_key: recentShellActionDedupKey(entry),
    source_surface: stringValue(isRecord(entry.metadata) ? entry.metadata["source"] : null) ?? entry.kind,
    signal_level: "high",
    metadata: isRecord(entry.metadata) ? entry.metadata : {},
  };
}

function buildLastSeenBatchWriteRequest(
  markers: readonly ContinuityLastSeenMarker[],
): ContinuityLastSeenBatchUpsertRequest {
  return {
    markers: markers.map((marker) => ({
      entity_kind: marker.entityKind,
      entity_key: marker.entityKey,
      observed_at_utc: marker.observedAtUtc,
      observed_fingerprint: marker.observedFingerprint,
      working_set_id: marker.workingSetId,
      workflow_thread_id: marker.workflowThreadId,
      observed_state: marker.observedState,
      metadata: marker.metadata,
    })),
  };
}

function buildRecoveryAckWriteRequest(
  acknowledgement: DurableRecoveryAcknowledgement,
): ContinuityRecoveryAcknowledgementUpsertRequest {
  return {
    recovery_key: acknowledgement.recoveryKey,
    acknowledged_at_utc: acknowledgement.acknowledgedAtUtc,
    metadata: acknowledgement.metadata,
  };
}

function buildNotificationStateWriteRequest(
  state: ContinuityNotificationState,
): ContinuityNotificationStateUpsertRequest {
  return {
    inboxed_at_utc: state.inboxedAtUtc,
    seen_at_utc: state.seenAtUtc,
    acknowledged_at_utc: state.acknowledgedAtUtc,
    suppressed_until_utc: state.suppressedUntilUtc,
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

function writePendingLastSeen(markers: readonly ContinuityLastSeenMarker[]): void {
  const writes = readPendingContinuityWrites().filter(
    (write): write is PendingOutcomeWrite | PendingNotificationStateWrite | PendingRecoveryAckWrite => write.kind !== "last_seen",
  );
  writePendingContinuityWrites([{ kind: "last_seen", markers: [...markers] }, ...writes]);
}

function writePendingNotificationState(notificationId: string, state: ContinuityNotificationState): void {
  const writes = readPendingContinuityWrites().filter((write) => {
    return write.kind !== "notification_state" || write.notificationId !== notificationId;
  });
  writes.unshift({ kind: "notification_state", notificationId, state });
  writePendingContinuityWrites(writes);
}

function writeOneNotificationRecord(record: ContinuityNotificationRecord): void {
  const records = readContinuityNotificationRecords();
  const next = records.map((item) => item.id === record.id ? record : item);
  writeContinuityNotificationRecords(next);
}

function updateContinuityNotificationState(
  notificationId: string,
  mutate: (current: ContinuityNotificationState) => ContinuityNotificationState,
): void {
  const record = readContinuityNotificationRecords().find((item) => item.id === notificationId);
  if (!record) {
    return;
  }
  const state = mutate(record.state);
  writeOneNotificationRecord({
    ...record,
    state,
  });
  writePendingNotificationState(notificationId, state);
  void flushPendingContinuityWrites();
}

export function isContinuityNotificationSuppressed(state: ContinuityNotificationState): boolean {
  return Boolean(state.suppressedUntilUtc) && Date.parse(state.suppressedUntilUtc!) > Date.now();
}

export function isActiveContinuityNotification(record: ContinuityNotificationRecord): boolean {
  return record.state.acknowledgedAtUtc == null && !isContinuityNotificationSuppressed(record.state);
}

export function isBannerEligibleContinuityNotification(record: ContinuityNotificationRecord): boolean {
  return isActiveContinuityNotification(record) && record.state.seenAtUtc == null;
}

export function readActiveContinuityNotificationRecords(): ContinuityNotificationRecord[] {
  return readContinuityNotificationRecords().filter((record) => isActiveContinuityNotification(record));
}

export function readBannerContinuityNotificationRecords(): ContinuityNotificationRecord[] {
  return readContinuityNotificationRecords().filter((record) => isBannerEligibleContinuityNotification(record));
}

export function markContinuityNotificationSeen(notificationId: string): void {
  const now = new Date().toISOString();
  updateContinuityNotificationState(notificationId, (current) => ({
    ...current,
    inboxedAtUtc: current.inboxedAtUtc ?? now,
    seenAtUtc: current.seenAtUtc ?? now,
  }));
}

export function acknowledgeContinuityNotification(notificationId: string): void {
  const now = new Date().toISOString();
  updateContinuityNotificationState(notificationId, (current) => ({
    ...current,
    inboxedAtUtc: current.inboxedAtUtc ?? now,
    seenAtUtc: current.seenAtUtc ?? now,
    acknowledgedAtUtc: current.acknowledgedAtUtc ?? now,
  }));
}

export function suppressContinuityNotification(notificationId: string, hours = 24): void {
  const now = new Date();
  updateContinuityNotificationState(notificationId, (current) => {
    const currentSuppression = current.suppressedUntilUtc ? Date.parse(current.suppressedUntilUtc) : 0;
    const nextSuppression = Math.max(now.getTime() + Math.max(hours, 1) * 60 * 60 * 1000, currentSuppression);
    const nowIso = now.toISOString();
    return {
      ...current,
      inboxedAtUtc: current.inboxedAtUtc ?? nowIso,
      seenAtUtc: current.seenAtUtc ?? nowIso,
      suppressedUntilUtc: new Date(nextSuppression).toISOString(),
    };
  });
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
  if (write.kind === "last_seen") {
    return upsertContinuityLastSeen(buildLastSeenBatchWriteRequest(write.markers));
  }
  if (write.kind === "notification_state") {
    return upsertContinuityNotificationState(
      write.notificationId,
      buildNotificationStateWriteRequest(write.state),
    );
  }
  return upsertContinuityRecoveryAcknowledgement(buildRecoveryAckWriteRequest(write.acknowledgement));
}

function upsertLocalLastSeenMarkers(markers: readonly ContinuityLastSeenMarker[]): void {
  const merged = new Map(
    readContinuityLastSeenMarkers().map((marker) => [`${marker.entityKind}:${marker.entityKey}`, marker]),
  );
  markers.forEach((marker) => {
    merged.set(`${marker.entityKind}:${marker.entityKey}`, marker);
  });
  writeContinuityLastSeenMarkers(
    [...merged.values()].sort((left, right) => Date.parse(right.observedAtUtc) - Date.parse(left.observedAtUtc)),
  );
}

export function rememberContinuityObservation(markers: readonly ContinuityLastSeenMarker[]): void {
  if (!markers.length || !canUseLocalStorage()) {
    return;
  }
  upsertLocalLastSeenMarkers(markers);
  writePendingLastSeen(markers);
  void flushPendingContinuityWrites();
}

export function buildPlanningLastSeenMarker(
  snapshot: PlanningSessionSnapshotResponse | null,
  workingSetId: number | null,
): ContinuityLastSeenMarker | null {
  if (!snapshot?.session) {
    return null;
  }
  const observedState = {
    sessionId: snapshot.session.id,
    status: snapshot.session.status,
    checkpointIndex: snapshot.session.current_checkpoint_index,
    targetLoopIds: (snapshot.target_loops ?? []).map((loop) => loop.id).sort((left, right) => left - right),
    contextIsStale: snapshot.context_freshness?.is_stale ?? false,
    staleTargetLoopCount: snapshot.context_freshness?.stale_target_loop_count ?? 0,
    missingTargetLoopCount: snapshot.context_freshness?.missing_target_loop_count ?? 0,
    downstreamResourceChangeCount: snapshot.resource_change_summary?.downstream_change_count ?? 0,
    updatedAtUtc: snapshot.session.updated_at_utc,
  } satisfies Record<string, unknown>;

  return {
    entityKind: "planning_session",
    entityKey: `planning:${snapshot.session.id}`,
    observedAtUtc: new Date().toISOString(),
    observedFingerprint: buildFingerprint(observedState),
    workingSetId,
    workflowThreadId: `planning:${snapshot.session.id}`,
    observedState,
    metadata: {},
  };
}

export function buildReviewLastSeenMarker(input: {
  reviewFocus: Extract<ReviewFocus, "relationship" | "enrichment">;
  snapshot: RelationshipReviewSessionSnapshotResponse | EnrichmentReviewSessionSnapshotResponse | null;
  workingSetId: number | null;
}): ContinuityLastSeenMarker | null {
  const snapshot = input.snapshot;
  if (!snapshot?.session) {
    return null;
  }
  const observedState = {
    sessionId: snapshot.session.id,
    reviewFocus: input.reviewFocus,
    loopCount: snapshot.loop_count,
    currentLoopId: snapshot.current_item?.loop.id ?? snapshot.session.current_loop_id ?? null,
    updatedAtUtc: snapshot.session.updated_at_utc,
  } satisfies Record<string, unknown>;
  return {
    entityKind: "review_session",
    entityKey: `review:${input.reviewFocus}:${snapshot.session.id}`,
    observedAtUtc: new Date().toISOString(),
    observedFingerprint: buildFingerprint(observedState),
    workingSetId: input.workingSetId,
    workflowThreadId: `review:${input.reviewFocus}:${snapshot.session.id}`,
    observedState,
    metadata: {},
  };
}

export function buildCohortLastSeenMarker(input: {
  cohort: LoopReviewCohortResponse["cohort"];
  reviewData: LoopReviewResponse;
  workingSetId: number | null;
}): ContinuityLastSeenMarker {
  const cohort = [...input.reviewData.daily, ...input.reviewData.weekly].find((item) => item.cohort === input.cohort) ?? null;
  const observedState = {
    cohort: input.cohort,
    count: cohort?.count ?? 0,
    itemIds: (cohort?.items ?? []).map((item) => item.id).sort((left, right) => left - right),
    generatedAtUtc: input.reviewData.generated_at_utc,
  } satisfies Record<string, unknown>;
  return {
    entityKind: "cohort_snapshot",
    entityKey: `cohort:${input.cohort}`,
    observedAtUtc: new Date().toISOString(),
    observedFingerprint: buildFingerprint(observedState),
    workingSetId: input.workingSetId,
    workflowThreadId: null,
    observedState,
    metadata: {},
  };
}

export function buildWorkflowSummaryLastSeenMarker(input: {
  summaryId: string;
  workflowThreadId: string | null;
  workingSetId: number | null;
  latestOutcomeId: number | null;
  title: string;
  summary: string | null;
}): ContinuityLastSeenMarker {
  const observedState = {
    latestOutcomeId: input.latestOutcomeId,
    title: input.title,
    summary: input.summary,
  } satisfies Record<string, unknown>;
  return {
    entityKind: "workflow_thread",
    entityKey: input.summaryId,
    observedAtUtc: new Date().toISOString(),
    observedFingerprint: buildFingerprint(observedState),
    workingSetId: input.workingSetId,
    workflowThreadId: input.workflowThreadId,
    observedState,
    metadata: {},
  };
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

export function readRecentShellActions(): RecentShellActionEntry[] {
  return readRecentActionsCache();
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
  const updatedSummaries = readContinuityWorkflowSummaries().map((summary) => ({
    ...summary,
    undoAction: summary.undoAction && undoHandleIdentity(summary.undoAction.undo) === targetIdentity
      ? { ...summary.undoAction, disabledReason: reason }
      : summary.undoAction ?? null,
  }));
  writeRecentActionsCache(updated);
  writeContinuityWorkflowSummaries(updatedSummaries);
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
        rerunAction: outcome.rerunAction && rerunHandleIdentity(outcome.rerunAction.rerun) === targetIdentity
          ? { ...outcome.rerunAction, disabledReason: reason }
          : outcome.rerunAction ?? null,
      },
    });
  });
  const updatedSummaries = readContinuityWorkflowSummaries().map((summary) => ({
    ...summary,
    rerunAction: summary.rerunAction && rerunHandleIdentity(summary.rerunAction.rerun) === targetIdentity
      ? { ...summary.rerunAction, disabledReason: reason }
      : summary.rerunAction ?? null,
  }));
  writeRecentActionsCache(updated);
  writeContinuityWorkflowSummaries(updatedSummaries);
  emitRecentShellActionsUpdated();
}
