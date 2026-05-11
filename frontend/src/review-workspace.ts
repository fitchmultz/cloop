/**
 * review-workspace.ts - Typed review redesign workspace for decide/plan/review flows.
 *
 * Purpose:
 *   Replace the list-heavy legacy review presentation with a focused decision
 *   workspace that explains why an item is present, what decision is required,
 *   and what happens next.
 *
 * Responsibilities:
 *   - Load planning, relationship, enrichment, and hygiene review data.
 *   - Render the queue rail, decision workspace, and impact panel.
 *   - Execute review actions, clarification answers, and planning checkpoints.
 *   - Coordinate shell handoffs into the redesigned review surface.
 *
 * Scope:
 *   - Review-main TypeScript UI only.
 *
 * Usage:
 *   - Bootstrapped from frontend/src/main.ts as part of the TypeScript-owned
 *     operator shell startup.
 *
 * Invariants/Assumptions:
 *   - Saved sessions remain the canonical queue state for planning,
 *     relationship review, and enrichment review.
 *   - The shared modal and merge runtimes are available from the TypeScript frontend.
 */

import { withReceiptOutcome } from "./action-receipts";
import { HttpRequestError, requestJson } from "./http";
import type {
  ClarificationSubmitRequest,
  EnrichmentReviewActionCreateRequest,
  EnrichmentReviewActionResponse,
  EnrichmentReviewActionUpdateRequest,
  EnrichmentReviewQueueItemResponse,
  EnrichmentReviewSessionActionResponse,
  EnrichmentReviewSessionClarificationRequest,
  EnrichmentReviewSessionClarificationResponse,
  EnrichmentReviewSessionCreateRequest,
  EnrichmentReviewSessionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  EnrichmentReviewSessionUpdateRequest,
  LoopReviewCohortItem,
  LoopReviewCohortResponse,
  LoopReviewResponse,
  PlanningExecutionFollowUpResourceResponse,
  PlanningExecutionHistoryItemResponse,
  PlanningExecutionLaunchSurfaceResponse,
  PlanningSessionCreateRequest,
  PlanningSessionResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewActionCreateRequest,
  RelationshipReviewActionResponse,
  RelationshipReviewActionUpdateRequest,
  RelationshipReviewCandidateResponse,
  RelationshipReviewSessionActionRequest,
  RelationshipReviewSessionActionResponse,
  RelationshipReviewSessionCreateRequest,
  RelationshipReviewSessionResponse,
  RelationshipReviewSessionSnapshotResponse,
  RelationshipReviewSessionUpdateRequest,
  WorkingSetResponse,
} from "./domain";
import type {
  OperatorActionCard,
  ReviewFocus,
  TrustSurfaceMetadata,
} from "./contracts-ui";
import { applyContinuityRecovery } from "./continuity-recovery";
import { resolveDurableReopenLocation } from "./continuity-follow-through";
import { continuityRecoveryForLocation } from "./continuity-surface-recovery";
import { recordRecentShellAction } from "./continuity-intelligence";
import { renderActionCardDeck } from "./operator-action-cards";
import {
  escapeHtml,
  formatRelativeTime,
  formatTimestamp,
  loopPreview,
  loopTitle,
  parseOptionalInteger,
  parseTimestampMs,
} from "./shell-core";
import { createLocation, locationToHash, parseHash } from "./shell-routing";
import { savedQueryContextSource } from "./saved-query-copy";
import { renderTrustSurface } from "./trust-surface";
import { buildFollowThroughReceipt } from "./follow-through-adapters";
import {
  buildCohortImpactCard,
  buildEnrichmentImpactCard,
  buildEnrichmentSuggestionCard,
  buildPlanningExecutionReceiptCard,
  buildPlanningExecutionSummaryCard,
  buildPlanningFollowUpResourceCard,
  buildPlanningLaunchSurfaceCard,
  describePlanningRollbackCue,
  buildRelationshipImpactCard,
} from "./review-workspace-action-cards";
import {
  executePlanningSession,
  fetchEnrichmentActions,
  fetchEnrichmentSession,
  fetchPlanningSession,
  fetchRelationshipActions,
  fetchRelationshipSession,
  runEnrichmentSessionAction,
  runRelationshipSessionAction,
} from "./review-workflow-client";
import * as modals from "./modals";
import type { AlertDialogConfig, DialogConfig } from "./modals";
import { openMergeModal, setupMergeHandlers } from "./duplicates";

interface ReviewWorkspaceElements {
  shell: HTMLElement;
  title: HTMLElement;
  description: HTMLElement;
  status: HTMLElement;
  modeTabs: HTMLButtonElement[];
  controls: HTMLElement;
  overview: HTMLElement;
  queue: HTMLElement;
  workspace: HTMLElement;
  impact: HTMLElement;
}

interface ReviewWorkspaceState {
  activeMode: ReviewFocus;
  reviewMode: "daily" | "weekly";
  selectedCohortKey: string | null;
  workingSets: WorkingSetResponse[];
  planningSessions: PlanningSessionResponse[];
  planningSnapshot: PlanningSessionSnapshotResponse | null;
  planningSessionId: number | null;
  relationshipActions: RelationshipReviewActionResponse[];
  relationshipSessions: RelationshipReviewSessionResponse[];
  relationshipSnapshot: RelationshipReviewSessionSnapshotResponse | null;
  relationshipSessionId: number | null;
  relationshipActionId: number | null;
  enrichmentActions: EnrichmentReviewActionResponse[];
  enrichmentSessions: EnrichmentReviewSessionResponse[];
  enrichmentSnapshot: EnrichmentReviewSessionSnapshotResponse | null;
  enrichmentSessionId: number | null;
  enrichmentActionId: number | null;
  reviewData: LoopReviewResponse | null;
}

interface ReviewFocusDetail {
  focus: ReviewFocus;
  sessionId: number | null;
}

type PromptDialogConfig = DialogConfig;

const COHORT_DESCRIPTORS = {
  stale: {
    label: "Stale loops",
    why: "These loops have not been updated recently enough to stay trustworthy.",
    decision: "Decide whether to revive, clarify, or close the stale work.",
  },
  no_next_action: {
    label: "Missing next action",
    why: "These loops are active but the next concrete move is still undefined.",
    decision: "Clarify the immediate next action so execution can resume.",
  },
  blocked_too_long: {
    label: "Blocked too long",
    why: "These loops have stayed blocked long enough that they may need escalation or reframing.",
    decision: "Resolve the blocker, defer intentionally, or drop the work.",
  },
  due_soon_unplanned: {
    label: "Due soon, under-planned",
    why: "These loops are approaching a due boundary without enough execution structure.",
    decision: "Plan the next move now or consciously accept the risk.",
  },
} as const;

const MODE_DESCRIPTORS = {
  planning: {
    label: "Planning",
    description: "Checkpointed planning sessions with progress, execution history, and handoff cues.",
  },
  relationship: {
    label: "Relationship review",
    description: "Duplicate and related-loop decisions with confidence, queue health, and impact previews.",
  },
  enrichment: {
    label: "Enrichment review",
    description: "Suggestion and clarification review with clear apply/reject consequences.",
  },
  cohorts: {
    label: "Hygiene review",
    description: "Daily and weekly review cohorts focused on the smallest next meaningful cleanup decision.",
  },
} as const satisfies Record<ReviewFocus, { label: string; description: string }>;

const DEFAULT_STATE: ReviewWorkspaceState = {
  activeMode: "relationship",
  reviewMode: "daily",
  selectedCohortKey: null,
  workingSets: [],
  planningSessions: [],
  planningSnapshot: null,
  planningSessionId: null,
  relationshipActions: [],
  relationshipSessions: [],
  relationshipSnapshot: null,
  relationshipSessionId: null,
  relationshipActionId: null,
  enrichmentActions: [],
  enrichmentSessions: [],
  enrichmentSnapshot: null,
  enrichmentSessionId: null,
  enrichmentActionId: null,
  reviewData: null,
};

const REVIEW_FOCUS_EVENT = "cloop:review-focus";
const REVIEW_WORKSPACE_REFRESH_EVENT = "cloop:review-workspace-refresh-requested";
const WORKSPACE_REFRESH_EVENT = "cloop:workspace-refresh-requested";

let elements: ReviewWorkspaceElements | null = null;
let state: ReviewWorkspaceState = { ...DEFAULT_STATE };
let loading = false;

function requireElement<T extends HTMLElement>(id: string, ctor: { new (): T }): T {
  const element = document.getElementById(id);
  if (!(element instanceof ctor)) {
    throw new Error(`Missing required review workspace element: ${id}`);
  }
  return element;
}

function buildElements(): ReviewWorkspaceElements {
  return {
    shell: requireElement("review-redesign-shell", HTMLElement),
    title: requireElement("review-shell-title", HTMLElement),
    description: requireElement("review-shell-description", HTMLElement),
    status: requireElement("review-shell-status", HTMLElement),
    modeTabs: Array.from(document.querySelectorAll<HTMLButtonElement>("[data-review-shell-mode]")),
    controls: requireElement("review-shell-controls", HTMLElement),
    overview: requireElement("review-shell-overview", HTMLElement),
    queue: requireElement("review-shell-queue", HTMLElement),
    workspace: requireElement("review-shell-workspace", HTMLElement),
    impact: requireElement("review-shell-impact", HTMLElement),
  };
}

function currentWorkingSetId(): number | null {
  return parseHash(window.location.hash)?.workingSetId ?? null;
}

function surfaceRecoveryForLocation(
  location: ReturnType<typeof createLocation> | null,
  workflowThreadId: string | null = null,
) {
  return continuityRecoveryForLocation({
    location,
    workflowThreadId,
  });
}

function currentPlanningRecovery(snapshot: PlanningSessionSnapshotResponse | null) {
  if (!snapshot?.session) {
    return null;
  }
  return surfaceRecoveryForLocation(
    createLocation({
      state: "plan",
      reviewFocus: "planning",
      sessionId: snapshot.session.id,
      workingSetId: currentWorkingSetId(),
    }),
    `planning:${snapshot.session.id}`,
  );
}

function currentReviewSessionRecovery(
  focus: Extract<ReviewFocus, "relationship" | "enrichment">,
  snapshot: RelationshipReviewSessionSnapshotResponse | EnrichmentReviewSessionSnapshotResponse | null,
) {
  if (!snapshot?.session) {
    return null;
  }
  return surfaceRecoveryForLocation(
    createLocation({
      state: "decide",
      reviewFocus: focus,
      sessionId: snapshot.session.id,
      workingSetId: currentWorkingSetId(),
    }),
    `review:${focus}:${snapshot.session.id}`,
  );
}

function planningImpactHandoffContext(sessionName: string): {
  breadcrumbPrefix: string[];
  fallbackWorkingSetId: number | null;
  workingSets: readonly WorkingSetResponse[];
  sessionName: string;
} {
  return {
    breadcrumbPrefix: ["Home", "Plan"],
    fallbackWorkingSetId: currentWorkingSetId(),
    workingSets: state.workingSets,
    sessionName,
  };
}

function reviewImpactHandoffContext(sessionName: string): {
  breadcrumbPrefix: string[];
  fallbackWorkingSetId: number | null;
  workingSets: readonly WorkingSetResponse[];
  sessionName: string;
} {
  return {
    breadcrumbPrefix: ["Home", "Review"],
    fallbackWorkingSetId: currentWorkingSetId(),
    workingSets: state.workingSets,
    sessionName,
  };
}

function cohortImpactHandoffContext(): {
  breadcrumbPrefix: string[];
  fallbackWorkingSetId: number | null;
  workingSets: readonly WorkingSetResponse[];
} {
  return {
    breadcrumbPrefix: ["Home", "Review"],
    fallbackWorkingSetId: currentWorkingSetId(),
    workingSets: state.workingSets,
  };
}

function toReviewHash(
  focus: ReviewFocus,
  sessionId: number | null = null,
  workingSetId: number | null = currentWorkingSetId(),
): string {
  switch (focus) {
    case "planning":
      return locationToHash(createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId,
        workingSetId,
      }));
    case "relationship":
      return locationToHash(createLocation({
        state: "decide",
        reviewFocus: "relationship",
        sessionId,
        workingSetId,
      }));
    case "enrichment":
      return locationToHash(createLocation({
        state: "decide",
        reviewFocus: "enrichment",
        sessionId,
        workingSetId,
      }));
    case "cohorts":
      return locationToHash(createLocation({
        state: "review",
        reviewFocus: "cohorts",
        workingSetId,
      }));
  }
}

function toDoHash(loopId: number, workingSetId: number | null = currentWorkingSetId()): string {
  return locationToHash(createLocation({ state: "do", loopId, workingSetId }));
}

function operatorHomeHash(): string {
  return locationToHash(createLocation({ state: "operator" }));
}

function requestedReviewLocation(
  focus: ReviewFocus,
  sessionId: number,
  workingSetId: number | null = currentWorkingSetId(),
) {
  switch (focus) {
    case "planning":
      return createLocation({ state: "plan", reviewFocus: "planning", sessionId, workingSetId });
    case "relationship":
      return createLocation({ state: "decide", reviewFocus: "relationship", sessionId, workingSetId });
    case "enrichment":
      return createLocation({ state: "decide", reviewFocus: "enrichment", sessionId, workingSetId });
    case "cohorts":
      return createLocation({ state: "review", reviewFocus: "cohorts", workingSetId });
  }
}

function redirectToResolvedFocus(focus: ReviewFocus, sessionId: number | null): boolean {
  if (sessionId == null || focus === "cohorts") {
    return false;
  }
  const resolution = resolveDurableReopenLocation({
    location: requestedReviewLocation(focus, sessionId),
    allowSessionMatch: true,
  });
  const nextHash = locationToHash(createLocation(resolution.resolvedLocation));
  if (nextHash === window.location.hash) {
    return false;
  }
  window.location.hash = nextHash;
  return true;
}

function missingSessionHomeFallback(): void {
  window.location.hash = operatorHomeHash();
}

function isMissingSessionError(error: unknown): boolean {
  return error instanceof HttpRequestError && error.status === 404;
}

const ABORT_SESSION_LOAD = Symbol("abort-session-load");

function redirectRequestedSessionOrHome<T extends { id: number }>(
  focus: Extract<ReviewFocus, "planning" | "relationship" | "enrichment">,
  requestedSessionId: number | null,
  sessions: readonly T[],
): boolean {
  if (requestedSessionId == null) {
    return false;
  }
  if (redirectToResolvedFocus(focus, requestedSessionId)) {
    return true;
  }
  if (!sessions.some((session) => session.id === requestedSessionId)) {
    missingSessionHomeFallback();
    return true;
  }
  return false;
}

async function fetchRequestedSnapshotOrAbort<T>(
  requestedSessionId: number | null,
  sessionId: number | null,
  fetcher: (sessionId: number) => Promise<T>,
): Promise<T | null | typeof ABORT_SESSION_LOAD> {
  if (sessionId == null) {
    return null;
  }
  try {
    return await fetcher(sessionId);
  } catch (error: unknown) {
    if (requestedSessionId != null && isMissingSessionError(error)) {
      missingSessionHomeFallback();
      return ABORT_SESSION_LOAD;
    }
    throw error;
  }
}

function parseHashToFocus(hash: string): ReviewFocusDetail | null {
  const location = parseHash(hash);
  if (!location) {
    return null;
  }
  if (location.state === "plan") {
    return { focus: "planning", sessionId: location.sessionId ?? null };
  }
  if (location.state === "review") {
    return { focus: "cohorts", sessionId: null };
  }
  if (location.state === "decide" && location.reviewFocus === "relationship") {
    return { focus: "relationship", sessionId: location.sessionId ?? null };
  }
  if (location.state === "decide" && location.reviewFocus === "enrichment") {
    return { focus: "enrichment", sessionId: location.sessionId ?? null };
  }
  if (location.state === "decide" && location.reviewFocus === "cohorts") {
    return { focus: "cohorts", sessionId: null };
  }
  return null;
}

function setStatus(message: string, isError = false): void {
  if (!elements) {
    return;
  }
  elements.status.textContent = message;
  elements.status.classList.toggle("is-error", isError);
}

function requestWorkspaceRefresh(): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_REFRESH_EVENT));
}

async function fetchWorkingSets(): Promise<WorkingSetResponse[]> {
  return requestJson<WorkingSetResponse[]>(
    "/loops/working-sets",
    {},
    "Failed to load working sets",
  );
}

async function fetchPlanningSessions(): Promise<PlanningSessionResponse[]> {
  return requestJson<PlanningSessionResponse[]>(
    "/loops/planning/sessions",
    {},
    "Failed to load planning sessions",
  );
}

async function createPlanningSession(payload: PlanningSessionCreateRequest): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse, PlanningSessionCreateRequest>(
    "/loops/planning/sessions",
    { method: "POST", body: payload },
    "Failed to create planning session",
  );
}

async function deletePlanningSession(sessionId: number): Promise<void> {
  await requestJson(`/loops/planning/sessions/${sessionId}`, { method: "DELETE" }, "Failed to delete planning session");
}

async function refreshPlanningSession(sessionId: number): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse>(
    `/loops/planning/sessions/${sessionId}/refresh`,
    { method: "POST" },
    "Failed to refresh planning session",
  );
}

async function movePlanningSession(sessionId: number, direction: "next" | "previous"): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse, { direction: "next" | "previous" }>(
    `/loops/planning/sessions/${sessionId}/move`,
    { method: "POST", body: { direction } },
    "Failed to move planning session",
  );
}

async function createRelationshipAction(
  payload: RelationshipReviewActionCreateRequest,
): Promise<RelationshipReviewActionResponse> {
  return requestJson<RelationshipReviewActionResponse, RelationshipReviewActionCreateRequest>(
    "/loops/review/relationship/actions",
    { method: "POST", body: payload },
    "Failed to create relationship review action",
  );
}

async function updateRelationshipAction(
  actionId: number,
  payload: RelationshipReviewActionUpdateRequest,
): Promise<RelationshipReviewActionResponse> {
  return requestJson<RelationshipReviewActionResponse, RelationshipReviewActionUpdateRequest>(
    `/loops/review/relationship/actions/${actionId}`,
    { method: "PATCH", body: payload },
    "Failed to update relationship review action",
  );
}

async function deleteRelationshipAction(actionId: number): Promise<void> {
  await requestJson(
    `/loops/review/relationship/actions/${actionId}`,
    { method: "DELETE" },
    "Failed to delete relationship review action",
  );
}

async function fetchRelationshipSessions(): Promise<RelationshipReviewSessionResponse[]> {
  return requestJson<RelationshipReviewSessionResponse[]>(
    "/loops/review/relationship/sessions",
    {},
    "Failed to load relationship review sessions",
  );
}

async function createRelationshipSession(
  payload: RelationshipReviewSessionCreateRequest,
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse, RelationshipReviewSessionCreateRequest>(
    "/loops/review/relationship/sessions",
    { method: "POST", body: payload },
    "Failed to create relationship review session",
  );
}

async function updateRelationshipSession(
  sessionId: number,
  payload: RelationshipReviewSessionUpdateRequest,
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse, RelationshipReviewSessionUpdateRequest>(
    `/loops/review/relationship/sessions/${sessionId}`,
    { method: "PATCH", body: payload },
    "Failed to update relationship review session",
  );
}

async function deleteRelationshipSession(sessionId: number): Promise<void> {
  await requestJson(
    `/loops/review/relationship/sessions/${sessionId}`,
    { method: "DELETE" },
    "Failed to delete relationship review session",
  );
}

async function moveRelationshipSession(
  sessionId: number,
  direction: "next" | "previous",
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse, { direction: "next" | "previous" }>(
    `/loops/review/relationship/sessions/${sessionId}/move`,
    { method: "POST", body: { direction } },
    "Failed to move relationship review session",
  );
}

async function createEnrichmentAction(
  payload: EnrichmentReviewActionCreateRequest,
): Promise<EnrichmentReviewActionResponse> {
  return requestJson<EnrichmentReviewActionResponse, EnrichmentReviewActionCreateRequest>(
    "/loops/review/enrichment/actions",
    { method: "POST", body: payload },
    "Failed to create enrichment review action",
  );
}

async function updateEnrichmentAction(
  actionId: number,
  payload: EnrichmentReviewActionUpdateRequest,
): Promise<EnrichmentReviewActionResponse> {
  return requestJson<EnrichmentReviewActionResponse, EnrichmentReviewActionUpdateRequest>(
    `/loops/review/enrichment/actions/${actionId}`,
    { method: "PATCH", body: payload },
    "Failed to update enrichment review action",
  );
}

async function deleteEnrichmentAction(actionId: number): Promise<void> {
  await requestJson(
    `/loops/review/enrichment/actions/${actionId}`,
    { method: "DELETE" },
    "Failed to delete enrichment review action",
  );
}

async function fetchEnrichmentSessions(): Promise<EnrichmentReviewSessionResponse[]> {
  return requestJson<EnrichmentReviewSessionResponse[]>(
    "/loops/review/enrichment/sessions",
    {},
    "Failed to load enrichment review sessions",
  );
}

async function createEnrichmentSession(
  payload: EnrichmentReviewSessionCreateRequest,
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse, EnrichmentReviewSessionCreateRequest>(
    "/loops/review/enrichment/sessions",
    { method: "POST", body: payload },
    "Failed to create enrichment review session",
  );
}

async function updateEnrichmentSession(
  sessionId: number,
  payload: EnrichmentReviewSessionUpdateRequest,
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse, EnrichmentReviewSessionUpdateRequest>(
    `/loops/review/enrichment/sessions/${sessionId}`,
    { method: "PATCH", body: payload },
    "Failed to update enrichment review session",
  );
}

async function deleteEnrichmentSession(sessionId: number): Promise<void> {
  await requestJson(
    `/loops/review/enrichment/sessions/${sessionId}`,
    { method: "DELETE" },
    "Failed to delete enrichment review session",
  );
}

async function moveEnrichmentSession(
  sessionId: number,
  direction: "next" | "previous",
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse, { direction: "next" | "previous" }>(
    `/loops/review/enrichment/sessions/${sessionId}/move`,
    { method: "POST", body: { direction } },
    "Failed to move enrichment review session",
  );
}

async function answerEnrichmentClarifications(
  sessionId: number,
  payload: EnrichmentReviewSessionClarificationRequest,
): Promise<EnrichmentReviewSessionClarificationResponse> {
  return requestJson<EnrichmentReviewSessionClarificationResponse, EnrichmentReviewSessionClarificationRequest>(
    `/loops/review/enrichment/sessions/${sessionId}/clarifications/answer`,
    { method: "POST", body: payload },
    "Failed to answer enrichment clarifications",
  );
}

async function fetchReviewData(): Promise<LoopReviewResponse> {
  return requestJson<LoopReviewResponse>(
    "/loops/review?daily=true&weekly=true&limit=12",
    {},
    "Failed to load review cohorts",
  );
}

function recordBackendReviewFollowThrough(input: {
  followThrough: RelationshipReviewSessionActionResponse["follow_through"]
    | EnrichmentReviewSessionActionResponse["follow_through"]
    | EnrichmentReviewSessionClarificationResponse["follow_through"];
  metadata: Record<string, unknown>;
}): void {
  const receipt = buildFollowThroughReceipt({
    followThrough: input.followThrough,
    id: `review-follow-through-${input.followThrough.workflow_thread.id}-${Date.now()}`,
    metadata: input.metadata,
  });
  recordRecentShellAction(receipt.entry);
}

function choosePersistedId<T extends { id: number }>(items: T[], persistedId: number | null): number | null {
  const [firstItem] = items;
  if (!firstItem) {
    return null;
  }
  return items.some((item) => item.id === persistedId) ? persistedId : firstItem.id;
}

function describeQueueCount(currentIndex: number | null | undefined, total: number): string {
  if (currentIndex == null || !Number.isInteger(currentIndex) || total <= 0) {
    return `${total} item${total === 1 ? "" : "s"}`;
  }
  return `Item ${currentIndex + 1} of ${total}`;
}

function describeProgressFraction(currentIndex: number | null | undefined, total: number): string {
  if (!Number.isInteger(total) || total <= 0) {
    return `0/${Math.max(0, total)}`;
  }
  if (currentIndex == null || !Number.isInteger(currentIndex)) {
    return `0/${total}`;
  }
  return `${Math.min(total, currentIndex + 1)}/${total}`;
}

function normalizeConfidenceValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 1 ? value / 100 : value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) {
      return parsed > 1 ? parsed / 100 : parsed;
    }
  }
  return null;
}

function relationshipItemDrifted(
  snapshot: RelationshipReviewSessionSnapshotResponse | null,
  item: RelationshipReviewSessionSnapshotResponse["current_item"] | null,
): boolean {
  const candidate = relationshipPrimaryCandidate(item);
  const loopUpdated = parseTimestampMs(item?.loop.updated_at_utc);
  const candidateUpdated = parseTimestampMs(candidate?.updated_at_utc);
  const sessionUpdated = parseTimestampMs(snapshot?.session.updated_at_utc);
  return sessionUpdated != null && Math.max(loopUpdated ?? 0, candidateUpdated ?? 0) > sessionUpdated;
}

function relationshipLowConfidence(item: RelationshipReviewSessionSnapshotResponse["current_item"] | null): boolean {
  const candidate = relationshipPrimaryCandidate(item);
  return candidate != null && candidate.score < 0.75;
}

function relationshipReasonChip(item: RelationshipReviewSessionSnapshotResponse["current_item"] | null): string {
  const candidate = relationshipPrimaryCandidate(item);
  if (!candidate) {
    return "No active candidate";
  }
  return candidate.relationship_type === "duplicate" ? "Duplicate lead" : "Related lead";
}

function relationshipReasonText(item: RelationshipReviewSessionSnapshotResponse["current_item"] | null): string {
  const candidate = relationshipPrimaryCandidate(item);
  if (!candidate || !item) {
    return "This loop is still in the saved session, but no active relationship candidate remains in the current snapshot.";
  }
  const count = candidate.relationship_type === "duplicate" ? item.duplicate_count : item.related_count;
  return `${count} ${candidate.relationship_type} candidate${count === 1 ? "" : "s"} surfaced for this loop. Top match is ${loopTitle(candidate)} at ${Math.round(candidate.score * 100)}% similarity.`;
}

function relationshipDecisionLabel(item: RelationshipReviewSessionSnapshotResponse["current_item"] | null): string {
  const candidate = relationshipPrimaryCandidate(item);
  if (!candidate) {
    return "Refresh the saved queue, edit the session query, or move to the next loop.";
  }
  return candidate.relationship_type === "duplicate"
    ? "Confirm duplicate, merge the loops, or dismiss this candidate."
    : "Confirm related, escalate to duplicate, or dismiss this candidate.";
}

function relationshipConsequenceWarning(item: RelationshipReviewSessionSnapshotResponse["current_item"] | null): string | null {
  const candidate = relationshipPrimaryCandidate(item);
  if (!candidate) {
    return null;
  }
  return candidate.relationship_type === "duplicate"
    ? "Duplicate confirmation or merge is not reversible in-place. Verify both loops represent the same work before committing."
    : "Confirm as duplicate is not reversible in-place. Use that path only if both loops should collapse together.";
}

function enrichmentTopSuggestion(item: EnrichmentReviewQueueItemResponse | null) {
  return item?.pending_suggestions[0] ?? null;
}

function enrichmentSuggestedFields(item: EnrichmentReviewQueueItemResponse | null): string[] {
  const suggestion = enrichmentTopSuggestion(item);
  if (!suggestion || typeof suggestion.parsed !== "object" || !suggestion.parsed) {
    return [];
  }
  return Object.keys(suggestion.parsed).filter((key) => !["confidence", "needs_clarification"].includes(key));
}

function enrichmentSuggestionConfidence(item: EnrichmentReviewQueueItemResponse | null): number | null {
  const suggestion = enrichmentTopSuggestion(item);
  if (!suggestion || typeof suggestion.parsed !== "object" || !suggestion.parsed) {
    return null;
  }
  return normalizeConfidenceValue((suggestion.parsed as Record<string, unknown>)["confidence"]);
}

function enrichmentItemDrifted(
  snapshot: EnrichmentReviewSessionSnapshotResponse | null,
  item: EnrichmentReviewQueueItemResponse | null,
): boolean {
  const sessionUpdated = parseTimestampMs(snapshot?.session.updated_at_utc);
  const loopUpdated = parseTimestampMs(item?.loop.updated_at_utc);
  const newestPending = parseTimestampMs(item?.newest_pending_at);
  return sessionUpdated != null && Math.max(loopUpdated ?? 0, newestPending ?? 0) > sessionUpdated;
}

function enrichmentLowConfidence(item: EnrichmentReviewQueueItemResponse | null): boolean {
  const confidence = enrichmentSuggestionConfidence(item);
  return confidence != null && confidence < 0.75;
}

function enrichmentReasonChip(item: EnrichmentReviewQueueItemResponse | null): string {
  if (!item) {
    return "No pending work";
  }
  if (item.pending_clarification_count > 0) {
    return "Clarification required";
  }
  if (item.pending_suggestion_count > 0) {
    return "Suggestion ready";
  }
  return "Awaiting refresh";
}

function enrichmentReasonText(item: EnrichmentReviewQueueItemResponse | null): string {
  if (!item) {
    return "No active enrichment item remains in this saved session.";
  }
  const fields = enrichmentSuggestedFields(item);
  if (item.pending_clarification_count > 0) {
    return `${item.pending_clarification_count} unanswered clarification${item.pending_clarification_count === 1 ? "" : "s"} are blocking trustworthy apply decisions for this loop.`;
  }
  if (fields.length > 0) {
    return `The top pending suggestion proposes updates to ${fields.slice(0, 3).join(", ")}${fields.length > 3 ? ", and more" : ""}.`;
  }
  return `${item.pending_suggestion_count} pending suggestion${item.pending_suggestion_count === 1 ? "" : "s"} remain for manual review.`;
}

function enrichmentDecisionLabel(item: EnrichmentReviewQueueItemResponse | null): string {
  if (!item) {
    return "Refresh the saved queue, edit the session query, or move to the next queue.";
  }
  if (item.pending_clarification_count > 0) {
    return "Answer clarifications before trusting or applying older suggestions.";
  }
  return "Apply the top suggestion, reject it, use a saved action, or inspect the loop in Do.";
}

function enrichmentApplyWarning(item: EnrichmentReviewQueueItemResponse | null): string | null {
  return item?.pending_suggestion_count
    ? "Applying a suggestion mutates loop fields immediately and may supersede current context."
    : null;
}

function cohortDrifted(cohort: LoopReviewCohortResponse | null, generatedAtUtc: string | null): boolean {
  const generatedMs = parseTimestampMs(generatedAtUtc);
  if (generatedMs == null || !cohort) {
    return false;
  }
  return cohort.items.some((item) => {
    const updatedMs = parseTimestampMs(item.updated_at_utc);
    return updatedMs != null && updatedMs > generatedMs;
  });
}

function renderToolbarMeta(chips: string[], note: string | null = null): string {
  if (!chips.length && !note) {
    return "";
  }
  return `
    <div class="review-shell-toolbar-meta">
      <div class="review-shell-inline-chip-row">${chips.join("")}</div>
      ${note ? `<p class="review-shell-toolbar-note">${escapeHtml(note)}</p>` : ""}
    </div>
  `;
}

function selectedRelationshipAction(): RelationshipReviewActionResponse | null {
  return state.relationshipActions.find((action) => action.id === state.relationshipActionId) ?? null;
}

function selectedEnrichmentAction(): EnrichmentReviewActionResponse | null {
  return state.enrichmentActions.find((action) => action.id === state.enrichmentActionId) ?? null;
}

function planningGeneratedAt(snapshot: PlanningSessionSnapshotResponse | null): string | null {
  return (snapshot?.context_summary?.["generated_at_utc"] as string | undefined)
    ?? snapshot?.session.generated_at_utc
    ?? snapshot?.session.updated_at_utc
    ?? null;
}

function relationshipPrimaryCandidate(item: RelationshipReviewSessionSnapshotResponse["current_item"]): RelationshipReviewCandidateResponse | null {
  if (!item) {
    return null;
  }
  const duplicate = item.duplicate_candidates[0] ?? null;
  const related = item.related_candidates[0] ?? null;
  if (!duplicate) {
    return related;
  }
  if (!related) {
    return duplicate;
  }
  return duplicate.score >= related.score ? duplicate : related;
}

function relationshipRecommendation(item: RelationshipReviewSessionSnapshotResponse["current_item"]): string {
  const candidate = relationshipPrimaryCandidate(item);
  if (!candidate) {
    return "No active candidate remains for this loop.";
  }
  if (candidate.relationship_type === "duplicate" && candidate.score >= 0.9) {
    return `Recommend confirming a duplicate relationship with ${loopTitle(candidate)}.`;
  }
  if (candidate.relationship_type === "related" && candidate.score >= 0.9) {
    return `Recommend confirming a related relationship with ${loopTitle(candidate)}.`;
  }
  return `Manual review recommended before confirming ${candidate.relationship_type} for ${loopTitle(candidate)}.`;
}

function enrichmentRecommendation(item: EnrichmentReviewQueueItemResponse | null): string {
  if (!item) {
    return "No active enrichment item remains.";
  }
  if (item.pending_clarification_count > 0) {
    return "Answer clarifications first so the next suggestion is grounded in explicit context.";
  }
  if (item.pending_suggestion_count > 0) {
    return "Review the highest-signal pending suggestion and decide whether to apply or reject it.";
  }
  return "No pending enrichment work remains for this loop.";
}

function renderModeTabs(): void {
  if (!elements) {
    return;
  }
  elements.modeTabs.forEach((button) => {
    const mode = button.dataset["reviewShellMode"] as ReviewFocus | undefined;
    const active = mode === state.activeMode;
    button.classList.toggle("active", active);
    if (active) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
}

function renderHeader(): void {
  if (!elements) {
    return;
  }
  const descriptor = MODE_DESCRIPTORS[state.activeMode];
  elements.title.textContent = descriptor.label;
  elements.description.textContent = descriptor.description;
  renderModeTabs();
}

function reviewChip(text: string, tone: "default" | "alert" | "success" = "default"): string {
  return `<span class="review-shell-chip review-shell-chip--${tone}">${escapeHtml(text)}</span>`;
}

function planningTrustMetadata(snapshot: PlanningSessionSnapshotResponse | null): TrustSurfaceMetadata {
  const currentCheckpoint = snapshot?.current_checkpoint ?? null;
  const freshness = snapshot?.context_freshness;
  const staleTargetLoopCount = freshness?.stale_target_loop_count ?? 0;
  const missingTargetLoopCount = freshness?.missing_target_loop_count ?? 0;
  const isStale = freshness?.is_stale ?? false;
  const sourceCount = Array.isArray(snapshot?.sources) ? snapshot.sources.length : 0;
  const assumptions = snapshot?.assumptions ?? [];
  const operationCount = currentCheckpoint?.operations?.length ?? 0;

  return {
    generationLabel: "AI-authored plan + deterministic execution",
    generationTone: "attention",
    contextSources: [
      savedQueryContextSource(snapshot?.session.query, "Saved planning session"),
      `${snapshot?.target_loops?.length ?? 0} target loop${(snapshot?.target_loops?.length ?? 0) === 1 ? "" : "s"}`,
      `${sourceCount} external source${sourceCount === 1 ? "" : "s"}`,
    ],
    assumptions,
    confidenceLabel: currentCheckpoint
      ? `${operationCount} deterministic operation${operationCount === 1 ? "" : "s"} staged`
      : "Planning session ready",
    confidenceTone: currentCheckpoint ? "progress" : "neutral",
    freshnessLabel: isStale
      ? `${staleTargetLoopCount} target loop${staleTargetLoopCount === 1 ? "" : "s"} changed${missingTargetLoopCount ? ` · ${missingTargetLoopCount} missing` : ""}`
      : `Generated ${formatRelativeTime(planningGeneratedAt(snapshot))}`,
    freshnessTone: isStale ? "attention" : "progress",
    rollbackLabel: currentCheckpoint
      ? "No mutation until you execute this checkpoint"
      : "Execution history carries rollback cues when available",
    rollbackTone: currentCheckpoint ? "progress" : "neutral",
    impactSummary: currentCheckpoint
      ? `Executing ${currentCheckpoint.title || `checkpoint ${snapshot?.session.current_checkpoint_index != null ? snapshot.session.current_checkpoint_index + 1 : ""}`.trim()} will run ${operationCount} planned operation${operationCount === 1 ? "" : "s"}.`
      : "Select or refresh a planning session to inspect the next checkpoint.",
    impactTone: currentCheckpoint ? "attention" : "neutral",
  };
}

function relationshipTrustMetadata(
  snapshot: RelationshipReviewSessionSnapshotResponse | null,
  item: RelationshipReviewSessionSnapshotResponse["current_item"] | null,
): TrustSurfaceMetadata {
  const candidate = relationshipPrimaryCandidate(item);
  const drifted = relationshipItemDrifted(snapshot, item);

  return {
    generationLabel: "Deterministic similarity queue + human decision",
    generationTone: "attention",
    contextSources: [
      savedQueryContextSource(snapshot?.session.query, "Saved relationship session"),
      snapshot?.session.relationship_kind ? `${snapshot.session.relationship_kind} review focus` : "Relationship review",
      candidate ? `Top candidate: ${loopTitle(candidate)}` : "No active candidate preview",
    ],
    assumptions: [
      candidate && candidate.score < 0.9
        ? "The score is a ranking hint; manual review is required before confirming a relationship."
        : "Human review remains required before any relationship is confirmed or dismissed.",
    ],
    confidenceLabel: candidate ? `${Math.round(candidate.score * 100)}% top-similarity signal` : "Queue-level review signal",
    confidenceTone: candidate && candidate.score >= 0.9 ? "attention" : "neutral",
    freshnessLabel: drifted
      ? "Loop or candidate changed after the saved queue snapshot"
      : `Queue refreshed ${formatRelativeTime(snapshot?.session.updated_at_utc)}`,
    freshnessTone: drifted ? "attention" : "progress",
    rollbackLabel: candidate?.relationship_type === "duplicate"
      ? "Duplicate confirmation or merge is not reversible in-place"
      : "Confirm as duplicate is not reversible in-place; inspect carefully before choosing it",
    rollbackTone: "caution",
    impactSummary: candidate
      ? relationshipRecommendation(item)
      : "Refresh or broaden the queue to surface more relationship candidates.",
    impactTone: candidate ? "attention" : "neutral",
  };
}

function enrichmentTrustMetadata(
  snapshot: EnrichmentReviewSessionSnapshotResponse | null,
  item: EnrichmentReviewQueueItemResponse | null,
): TrustSurfaceMetadata {
  const suggestion = enrichmentTopSuggestion(item);
  const suggestionFields = enrichmentSuggestedFields(item);
  const newestPendingAt = item?.newest_pending_at ?? null;
  const drifted = enrichmentItemDrifted(snapshot, item);

  return {
    generationLabel: "AI-assisted suggestion queue",
    generationTone: "attention",
    contextSources: [
      savedQueryContextSource(snapshot?.session.query, "Saved enrichment session"),
      snapshot?.session.pending_kind ? `${snapshot.session.pending_kind} pending work` : "Pending enrichment follow-up",
      suggestion ? `Model: ${suggestion.model}` : "No active suggestion preview",
    ],
    assumptions: item?.pending_clarification_count
      ? ["Answer clarifications before trusting older suggestions."]
      : ["Structured suggestions should be reviewed before mutating loop state."],
    confidenceLabel: item?.pending_clarification_count
      ? "Clarification required before high-confidence apply"
      : suggestionFields.length
        ? `Suggests ${suggestionFields.join(", ")}`
        : suggestion
          ? "Structured suggestion ready for review"
          : "Queue ready for follow-up review",
    confidenceTone: item?.pending_clarification_count ? "attention" : "progress",
    freshnessLabel: drifted
      ? "Loop or pending enrichment changed after the saved queue snapshot"
      : newestPendingAt
        ? `Newest pending ${formatRelativeTime(newestPendingAt)}`
        : `Queue refreshed ${formatRelativeTime(snapshot?.session.updated_at_utc)}`,
    freshnessTone: drifted ? "attention" : "progress",
    rollbackLabel: item?.pending_clarification_count
      ? "Clarification answers rerun enrichment and may supersede older suggestions"
      : "Applying a suggestion mutates loop fields immediately",
    rollbackTone: "caution",
    impactSummary: item ? enrichmentRecommendation(item) : "Refresh the session or widen the query to surface more pending enrichment work.",
    impactTone: item?.pending_clarification_count ? "attention" : "neutral",
  };
}

function cohortTrustMetadata(
  cohort: LoopReviewCohortResponse | null,
  reviewMode: "daily" | "weekly",
  generatedAtUtc: string | null,
): TrustSurfaceMetadata {
  const topLoop = cohort?.items[0] ?? null;
  const generatedMs = parseTimestampMs(generatedAtUtc);
  const topLoopMs = parseTimestampMs(topLoop?.updated_at_utc);
  const drifted = generatedMs != null && topLoopMs != null && topLoopMs > generatedMs;

  return {
    generationLabel: "Deterministic review cohort",
    generationTone: "progress",
    contextSources: [
      reviewMode === "daily" ? "Daily hygiene cadence" : "Weekly hygiene cadence",
      cohort ? `Cohort: ${cohortLabel(cohort)}` : "No cohort selected",
      topLoop ? `Top loop: ${loopTitle(topLoop)}` : "No loop preview available",
    ],
    assumptions: ["This cohort is a review signal, not an automatic mutation."],
    confidenceLabel: cohort ? `${cohort.count} item${cohort.count === 1 ? "" : "s"} in this cohort` : "No active cohort",
    confidenceTone: cohort?.count ? "attention" : "neutral",
    freshnessLabel: drifted
      ? "A loop in this cohort changed after the cohort snapshot was generated"
      : generatedAtUtc
        ? `Generated ${formatRelativeTime(generatedAtUtc)}`
        : "Generated time unavailable",
    freshnessTone: drifted ? "attention" : "progress",
    rollbackLabel: "Opening Review is non-mutating until you edit or close a loop",
    rollbackTone: "progress",
    impactSummary: cohort
      ? cohortDescriptor(cohort).decision
      : "Choose a cohort to see why the hygiene review is surfacing it now.",
    impactTone: cohort ? "attention" : "neutral",
  };
}

function renderCompactTrust(metadata: TrustSurfaceMetadata): string {
  return renderTrustSurface(metadata, {
    variant: "compact",
    showContextLists: false,
  });
}

function renderPanelTrust(metadata: TrustSurfaceMetadata): string {
  return renderTrustSurface(metadata, {
    variant: "panel",
    title: "Trust surface",
    showContextLists: true,
  });
}

function renderControls(): void {
  if (!elements) {
    return;
  }

  if (state.activeMode === "planning") {
    const snapshot = state.planningSnapshot;
    const session = snapshot?.session ?? null;
    const executedCurrent = session && snapshot?.execution_history?.some((item) => item.checkpoint_index === session.current_checkpoint_index);

    elements.controls.innerHTML = `
      <div class="review-shell-toolbar-group review-shell-toolbar-group--grow review-shell-toolbar-group--fields">
        <label class="review-shell-field" for="review-shell-planning-session-select">
          <span>Session</span>
          <select id="review-shell-planning-session-select">
            <option value="">No saved session</option>
            ${state.planningSessions
              .map((item) => `<option value="${item.id}" ${item.id === state.planningSessionId ? "selected" : ""}>${escapeHtml(item.name)} · ${item.executed_checkpoint_count}/${item.checkpoint_count}</option>`)
              .join("")}
          </select>
        </label>
      </div>
      <div class="review-shell-toolbar-group review-shell-toolbar-group--actions">
        <button type="button" class="secondary" data-review-action="planning-create">New plan</button>
        <button type="button" class="secondary" data-review-action="planning-delete" ${session ? "" : "disabled"}>Delete</button>
        <button type="button" class="secondary" data-review-action="planning-refresh" ${session ? "" : "disabled"}>Refresh</button>
        <button type="button" class="secondary" data-review-action="planning-move-prev" ${session && session.current_checkpoint_index > 0 ? "" : "disabled"}>Previous</button>
        <button type="button" class="secondary" data-review-action="planning-move-next" ${session && session.current_checkpoint_index < session.checkpoint_count - 1 ? "" : "disabled"}>Next</button>
        <button type="button" data-review-action="planning-execute" ${session && snapshot?.current_checkpoint && !executedCurrent ? "" : "disabled"}>Execute checkpoint</button>
      </div>
    `;
    return;
  }

  if (state.activeMode === "relationship") {
    const snapshot = state.relationshipSnapshot;
    const driftedCount = snapshot?.items.filter((item) => relationshipItemDrifted(snapshot, item)).length ?? 0;
    const lowConfidenceCount = snapshot?.items.filter((item) => relationshipLowConfidence(item)).length ?? 0;
    const toolbarMeta = snapshot?.session
      ? renderToolbarMeta(
          [
            reviewChip(`Progress ${describeProgressFraction(snapshot.current_index, snapshot.loop_count)}`),
            reviewChip(`Purpose ${snapshot.session.relationship_kind} · ${snapshot.session.query}`),
            reviewChip(`${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? "" : "s"}`),
            driftedCount
              ? reviewChip(`${driftedCount} drifted`, "alert")
              : reviewChip(`Refreshed ${formatRelativeTime(snapshot.session.updated_at_utc)}`),
            lowConfidenceCount ? reviewChip(`${lowConfidenceCount} low-confidence`, "alert") : "",
          ].filter((chip): chip is string => Boolean(chip)),
          driftedCount
            ? "Some loops or candidates changed after this saved snapshot. Refresh before committing risky duplicate decisions."
            : null,
        )
      : "";

    elements.controls.innerHTML = `
      <div class="review-shell-toolbar-group review-shell-toolbar-group--grow review-shell-toolbar-group--fields">
        <label class="review-shell-field" for="review-shell-relationship-session-select">
          <span>Session</span>
          <select id="review-shell-relationship-session-select">
            <option value="">No saved session</option>
            ${state.relationshipSessions
              .map((item) => `<option value="${item.id}" ${item.id === state.relationshipSessionId ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.query)}</option>`)
              .join("")}
          </select>
        </label>
        <label class="review-shell-field" for="review-shell-relationship-action-select">
          <span>Saved action</span>
          <select id="review-shell-relationship-action-select">
            <option value="">No saved action</option>
            ${state.relationshipActions
              .map((item) => `<option value="${item.id}" ${item.id === state.relationshipActionId ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.action_type)} ${escapeHtml(item.relationship_type)}</option>`)
              .join("")}
          </select>
        </label>
      </div>
      <div class="review-shell-toolbar-group review-shell-toolbar-group--actions">
        <button type="button" class="secondary" data-review-action="relationship-session-create">New session</button>
        <button type="button" class="secondary" data-review-action="relationship-session-edit" ${state.relationshipSnapshot?.session ? "" : "disabled"}>Edit session</button>
        <button type="button" class="secondary" data-review-action="relationship-session-delete" ${state.relationshipSnapshot?.session ? "" : "disabled"}>Delete session</button>
        <button type="button" class="secondary" data-review-action="relationship-action-create">New action</button>
        <button type="button" class="secondary" data-review-action="relationship-action-edit" ${selectedRelationshipAction() ? "" : "disabled"}>Edit action</button>
        <button type="button" class="secondary" data-review-action="relationship-action-delete" ${selectedRelationshipAction() ? "" : "disabled"}>Delete action</button>
      </div>
      ${toolbarMeta}
    `;
    return;
  }

  if (state.activeMode === "enrichment") {
    const snapshot = state.enrichmentSnapshot;
    const driftedCount = snapshot?.items.filter((item) => enrichmentItemDrifted(snapshot, item)).length ?? 0;
    const lowConfidenceCount = snapshot?.items.filter((item) => enrichmentLowConfidence(item)).length ?? 0;
    const toolbarMeta = snapshot?.session
      ? renderToolbarMeta(
          [
            reviewChip(`Progress ${describeProgressFraction(snapshot.current_index, snapshot.loop_count)}`),
            reviewChip(`Purpose ${snapshot.session.pending_kind} · ${snapshot.session.query}`),
            reviewChip(`${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? "" : "s"}`),
            driftedCount
              ? reviewChip(`${driftedCount} drifted`, "alert")
              : reviewChip(`Refreshed ${formatRelativeTime(snapshot.session.updated_at_utc)}`),
            lowConfidenceCount ? reviewChip(`${lowConfidenceCount} low-confidence`, "alert") : "",
          ].filter((chip): chip is string => Boolean(chip)),
          driftedCount
            ? "Some loops or pending enrichment changed after this saved snapshot. Refresh before applying stale suggestions."
            : null,
        )
      : "";

    elements.controls.innerHTML = `
      <div class="review-shell-toolbar-group review-shell-toolbar-group--grow review-shell-toolbar-group--fields">
        <label class="review-shell-field" for="review-shell-enrichment-session-select">
          <span>Session</span>
          <select id="review-shell-enrichment-session-select">
            <option value="">No saved session</option>
            ${state.enrichmentSessions
              .map((item) => `<option value="${item.id}" ${item.id === state.enrichmentSessionId ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.query)}</option>`)
              .join("")}
          </select>
        </label>
        <label class="review-shell-field" for="review-shell-enrichment-action-select">
          <span>Saved action</span>
          <select id="review-shell-enrichment-action-select">
            <option value="">No saved action</option>
            ${state.enrichmentActions
              .map((item) => `<option value="${item.id}" ${item.id === state.enrichmentActionId ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.action_type)}</option>`)
              .join("")}
          </select>
        </label>
      </div>
      <div class="review-shell-toolbar-group review-shell-toolbar-group--actions">
        <button type="button" class="secondary" data-review-action="enrichment-session-create">New session</button>
        <button type="button" class="secondary" data-review-action="enrichment-session-edit" ${state.enrichmentSnapshot?.session ? "" : "disabled"}>Edit session</button>
        <button type="button" class="secondary" data-review-action="enrichment-session-delete" ${state.enrichmentSnapshot?.session ? "" : "disabled"}>Delete session</button>
        <button type="button" class="secondary" data-review-action="enrichment-action-create">New action</button>
        <button type="button" class="secondary" data-review-action="enrichment-action-edit" ${selectedEnrichmentAction() ? "" : "disabled"}>Edit action</button>
        <button type="button" class="secondary" data-review-action="enrichment-action-delete" ${selectedEnrichmentAction() ? "" : "disabled"}>Delete action</button>
      </div>
      ${toolbarMeta}
    `;
    return;
  }

  const cohorts = state.reviewData?.[state.reviewMode] ?? [];
  const activeCohorts = cohorts.filter((item) => item.count > 0);
  const selected = selectedCohort();
  const driftedCount = activeCohorts.filter((cohort) => cohortDrifted(cohort, state.reviewData?.generated_at_utc ?? null)).length;
  const toolbarMeta = renderToolbarMeta(
    [
      reviewChip(`Progress ${activeCohorts.length}/${cohorts.length || 0} active cohorts`),
      reviewChip(state.reviewMode === "daily" ? "Daily cadence" : "Weekly cadence"),
      selected ? reviewChip(`Selected ${selected.count} loop${selected.count === 1 ? "" : "s"}`) : "",
      driftedCount
        ? reviewChip(`${driftedCount} drifted`, "alert")
        : reviewChip(`Generated ${formatRelativeTime(state.reviewData?.generated_at_utc ?? null)}`),
    ].filter((chip): chip is string => Boolean(chip)),
    driftedCount ? "Some cohort members changed after the review snapshot. Refresh to repopulate the hygiene queue with current data." : null,
  );
  elements.controls.innerHTML = `
    <div class="review-shell-toolbar-group review-shell-toolbar-group--grow review-shell-toolbar-group--fields">
      <div class="review-shell-segmented" role="group" aria-label="Review cadence">
        <button type="button" class="${state.reviewMode === "daily" ? "active" : ""}" data-review-action="cohort-mode-daily">Daily</button>
        <button type="button" class="${state.reviewMode === "weekly" ? "active" : ""}" data-review-action="cohort-mode-weekly">Weekly</button>
      </div>
    </div>
    <div class="review-shell-toolbar-group review-shell-toolbar-group--actions">
      <button type="button" class="secondary" data-review-action="cohort-refresh">Refresh cohorts</button>
      <button type="button" data-review-action="cohort-open-top" ${activeCohorts.length ? "" : "disabled"}>Open top item</button>
    </div>
    ${toolbarMeta}
  `;
}

function renderOverview(): void {
  if (!elements) {
    return;
  }

  if (state.activeMode === "planning") {
    const snapshot = state.planningSnapshot;
    const session = snapshot?.session;
    const currentCheckpoint = snapshot?.current_checkpoint;
    const latestExecution = snapshot?.execution_history?.at(-1) ?? null;
    elements.overview.innerHTML = session
      ? `
        <div class="review-shell-overview-grid">
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Session purpose</span>
            <strong>${escapeHtml(snapshot.plan_title || session.name)}</strong>
            <p>${escapeHtml(snapshot.plan_summary)}</p>
          </article>
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Progress</span>
            <strong>${session.executed_checkpoint_count}/${session.checkpoint_count} checkpoints executed</strong>
            <p>${currentCheckpoint ? `Current checkpoint: ${escapeHtml(currentCheckpoint.title)}` : "No current checkpoint available."}</p>
          </article>
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Queue health</span>
            <strong>${Math.max(0, session.checkpoint_count - session.executed_checkpoint_count)} remaining</strong>
            <p>${latestExecution ? `Last execution ${formatRelativeTime(latestExecution.executed_at_utc)}` : "No checkpoint executed yet."}</p>
          </article>
        </div>
      `
      : '<p class="review-shell-empty">Create or select a planning session to generate a checkpointed workflow.</p>';
    return;
  }

  if (state.activeMode === "relationship") {
    const snapshot = state.relationshipSnapshot;
    const current = snapshot?.current_item ?? null;
    const highConfidence = snapshot?.items.filter((item) => item.top_score >= 0.9).length ?? 0;
    const duplicatePocket = snapshot?.items.reduce((sum, item) => sum + item.duplicate_count, 0) ?? 0;
    const relatedPocket = snapshot?.items.reduce((sum, item) => sum + item.related_count, 0) ?? 0;
    const driftedCount = snapshot?.items.filter((item) => relationshipItemDrifted(snapshot, item)).length ?? 0;
    const lowConfidenceCount = snapshot?.items.filter((item) => relationshipLowConfidence(item)).length ?? 0;
    elements.overview.innerHTML = snapshot?.session
      ? `
        <div class="review-shell-overview-grid">
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Why this queue exists</span>
            <strong>${escapeHtml(snapshot.session.query)}</strong>
            <p>${escapeHtml(snapshot.session.relationship_kind)} relationship review with cursor preservation.</p>
          </article>
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Progress</span>
            <strong>${describeProgressFraction(snapshot.current_index, snapshot.loop_count)} reviewed</strong>
            <p>${current ? `Current loop: ${escapeHtml(loopTitle(current.loop))}` : "No current loop selected."}</p>
          </article>
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Queue health</span>
            <strong>${highConfidence}/${snapshot.loop_count} high-confidence item${highConfidence === 1 ? "" : "s"}</strong>
            <p>${driftedCount} drifted · ${lowConfidenceCount} low-confidence · ${duplicatePocket} duplicate candidates · ${relatedPocket} related candidates.</p>
          </article>
        </div>
      `
      : '<p class="review-shell-empty">Create or select a relationship session to review duplicate and related-loop decisions.</p>';
    return;
  }

  if (state.activeMode === "enrichment") {
    const snapshot = state.enrichmentSnapshot;
    const current = snapshot?.current_item ?? null;
    const clarificationHeavy = snapshot?.items.filter((item) => item.pending_clarification_count > 0).length ?? 0;
    const suggestionHeavy = snapshot?.items.filter((item) => item.pending_suggestion_count > 0).length ?? 0;
    const newestPending = snapshot?.items
      .map((item) => item.newest_pending_at)
      .sort((left, right) => right.localeCompare(left))[0] ?? null;
    const driftedCount = snapshot?.items.filter((item) => enrichmentItemDrifted(snapshot, item)).length ?? 0;
    const lowConfidenceCount = snapshot?.items.filter((item) => enrichmentLowConfidence(item)).length ?? 0;

    elements.overview.innerHTML = snapshot?.session
      ? `
        <div class="review-shell-overview-grid">
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Why this queue exists</span>
            <strong>${escapeHtml(snapshot.session.query)}</strong>
            <p>${escapeHtml(snapshot.session.pending_kind)} pending enrichment follow-up with a preserved cursor.</p>
          </article>
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Progress</span>
            <strong>${describeProgressFraction(snapshot.current_index, snapshot.loop_count)} reviewed</strong>
            <p>${current ? `Current loop: ${escapeHtml(loopTitle(current.loop))}` : "No current loop selected."}</p>
          </article>
          <article class="review-shell-overview-card">
            <span class="review-shell-overview-label">Queue health</span>
            <strong>${clarificationHeavy} clarification-heavy item${clarificationHeavy === 1 ? "" : "s"}</strong>
            <p>${suggestionHeavy} suggestion-heavy · ${driftedCount} drifted · ${lowConfidenceCount} low-confidence · newest pending ${formatRelativeTime(newestPending)}</p>
          </article>
        </div>
      `
      : '<p class="review-shell-empty">Create or select an enrichment session to review pending suggestions and clarifications.</p>';
    return;
  }

  const cohorts = state.reviewData?.[state.reviewMode] ?? [];
  const totalItems = cohorts.reduce((sum, cohort) => sum + cohort.count, 0);
  const activeCohort = selectedCohort();
  const activeCohortCount = cohorts.filter((item) => item.count > 0).length;
  const driftedCount = cohorts.filter((cohort) => cohortDrifted(cohort, state.reviewData?.generated_at_utc ?? null)).length;
  elements.overview.innerHTML = `
    <div class="review-shell-overview-grid">
      <article class="review-shell-overview-card">
        <span class="review-shell-overview-label">Cadence</span>
        <strong>${escapeHtml(state.reviewMode)}</strong>
        <p>${state.reviewMode === "daily" ? "Daily review keeps current work honest." : "Weekly review catches structural drift and backlog decay."}</p>
      </article>
      <article class="review-shell-overview-card">
        <span class="review-shell-overview-label">Queue health</span>
        <strong>${totalItems} item${totalItems === 1 ? "" : "s"} in view</strong>
        <p>${activeCohortCount} active cohort${activeCohortCount === 1 ? "" : "s"} · ${driftedCount} drifted.</p>
      </article>
      <article class="review-shell-overview-card">
        <span class="review-shell-overview-label">Current cohort</span>
        <strong>${escapeHtml(activeCohort ? cohortLabel(activeCohort) : "No active cohort")}</strong>
        <p>${escapeHtml(activeCohort ? cohortDescriptor(activeCohort).decision : "Refresh or switch cadence to inspect review cohorts.")}</p>
      </article>
    </div>
  `;
}

function queueItemButtonAttributes(hash: string): string {
  return `data-review-open-hash="${escapeHtml(hash)}"`;
}

function relationshipEmptyStateHtml(snapshot: RelationshipReviewSessionSnapshotResponse | null): string {
  const session = snapshot?.session;
  if (!session) {
    return '<p class="review-shell-empty">Create or select a relationship session to preserve queue purpose, progress, and cursor state.</p>';
  }
  return `
    <div class="review-shell-empty">
      <strong>No queued relationship decisions</strong>
      <p>No duplicate or related candidates currently match “${escapeHtml(session.query)}”.</p>
      <p>To repopulate this queue, capture or update loops so similarity review finds candidates, or edit the saved session query and refresh.</p>
    </div>
  `;
}

function enrichmentEmptyStateHtml(snapshot: EnrichmentReviewSessionSnapshotResponse | null): string {
  const session = snapshot?.session;
  if (!session) {
    return '<p class="review-shell-empty">Create or select an enrichment session to preserve suggestion-review progress and cursor state.</p>';
  }
  return `
    <div class="review-shell-empty">
      <strong>No queued enrichment decisions</strong>
      <p>No pending suggestions or clarifications currently match “${escapeHtml(session.query)}”.</p>
      <p>To repopulate this queue, run enrichment on matching loops so new suggestions or clarifications are generated, or edit the saved session query and refresh.</p>
    </div>
  `;
}

function cohortEmptyStateHtml(reviewMode: "daily" | "weekly"): string {
  return `
    <div class="review-shell-empty">
      <strong>No active ${escapeHtml(reviewMode)} cohorts</strong>
      <p>This cadence currently has no loops surfacing as stale, blocked too long, missing a next action, or due soon without enough planning.</p>
      <p>Refresh after upstream loop changes, or switch cadence to inspect the other review horizon.</p>
    </div>
  `;
}

function renderRelationshipQueueCard(
  snapshot: RelationshipReviewSessionSnapshotResponse,
  item: RelationshipReviewSessionSnapshotResponse["items"][number],
): string {
  const active = snapshot.session.current_loop_id === item.loop.id;
  const candidate = relationshipPrimaryCandidate(item);
  const drifted = relationshipItemDrifted(snapshot, item);
  const lowConfidence = relationshipLowConfidence(item);

  return `
    <button type="button" class="review-shell-rail-card review-shell-rail-card--button ${active ? "is-active" : ""}" data-review-action="relationship-select-loop" data-loop-id="${item.loop.id}">
      <div class="review-shell-rail-card-header">
        <strong>${escapeHtml(loopTitle(item.loop))}</strong>
        ${candidate ? reviewChip(`${Math.round(candidate.score * 100)}%`, candidate.score >= 0.9 ? "alert" : "default") : reviewChip("No candidate")}
      </div>
      <div class="review-shell-inline-chip-row">
        ${reviewChip(relationshipReasonChip(item), candidate?.relationship_type === "duplicate" ? "alert" : "default")}
        ${drifted ? reviewChip("Snapshot drift", "alert") : ""}
        ${lowConfidence ? reviewChip("Low confidence", "alert") : candidate && candidate.score < 0.9 ? reviewChip("Manual review") : ""}
      </div>
      <p>${escapeHtml(relationshipReasonText(item))}</p>
      <div class="review-shell-inline-chip-row">
        ${reviewChip(`Duplicates ${item.duplicate_count}`, item.duplicate_count ? "alert" : "default")}
        ${reviewChip(`Related ${item.related_count}`)}
      </div>
      ${renderCompactTrust(relationshipTrustMetadata(snapshot, item))}
    </button>
  `;
}

function renderEnrichmentQueueCard(
  snapshot: EnrichmentReviewSessionSnapshotResponse,
  item: EnrichmentReviewQueueItemResponse,
): string {
  const active = snapshot.session.current_loop_id === item.loop.id;
  const drifted = enrichmentItemDrifted(snapshot, item);
  const lowConfidence = enrichmentLowConfidence(item);
  const confidence = enrichmentSuggestionConfidence(item);

  return `
    <button type="button" class="review-shell-rail-card review-shell-rail-card--button ${active ? "is-active" : ""}" data-review-action="enrichment-select-loop" data-loop-id="${item.loop.id}">
      <div class="review-shell-rail-card-header">
        <strong>${escapeHtml(loopTitle(item.loop))}</strong>
        ${reviewChip(formatRelativeTime(item.newest_pending_at), "default")}
      </div>
      <div class="review-shell-inline-chip-row">
        ${reviewChip(enrichmentReasonChip(item), item.pending_clarification_count > 0 ? "alert" : "default")}
        ${drifted ? reviewChip("Snapshot drift", "alert") : ""}
        ${lowConfidence ? reviewChip("Low confidence", "alert") : confidence != null ? reviewChip(`${Math.round(confidence * 100)}% confidence`) : ""}
      </div>
      <p>${escapeHtml(enrichmentReasonText(item))}</p>
      <div class="review-shell-inline-chip-row">
        ${reviewChip(`Suggestions ${item.pending_suggestion_count}`, item.pending_suggestion_count ? "alert" : "default")}
        ${reviewChip(`Clarifications ${item.pending_clarification_count}`, item.pending_clarification_count ? "alert" : "default")}
      </div>
      ${renderCompactTrust(enrichmentTrustMetadata(snapshot, item))}
    </button>
  `;
}

function renderQueue(): void {
  if (!elements) {
    return;
  }

  if (state.activeMode === "planning") {
    const snapshot = state.planningSnapshot;
    elements.queue.innerHTML = snapshot?.checkpoints?.length
      ? `
        <div class="review-shell-rail-header">
          <h3>Checkpoint rail</h3>
          <p>${snapshot.checkpoints.length} checkpoint${snapshot.checkpoints.length === 1 ? "" : "s"}</p>
        </div>
        <div class="review-shell-rail-list">
          ${snapshot.checkpoints
            .map((checkpoint, index) => {
              const session = snapshot.session;
              const executed = snapshot.execution_history?.some((item) => item.checkpoint_index === index) ?? false;
              const isCurrent = session.current_checkpoint_index === index;
              const status = executed ? "executed" : isCurrent ? "current" : index < session.current_checkpoint_index ? "passed" : "pending";
              return `
                <article class="review-shell-rail-card review-shell-rail-card--${escapeHtml(status)}">
                  <div class="review-shell-rail-card-header">
                    <strong>${escapeHtml(checkpoint.title || `Checkpoint ${index + 1}`)}</strong>
                    ${reviewChip(status, executed ? "success" : isCurrent ? "alert" : "default")}
                  </div>
                  <p>${escapeHtml(checkpoint.summary || "No summary provided.")}</p>
                  <div class="review-shell-inline-chip-row">
                    ${reviewChip(`${checkpoint.operations?.length ?? 0} operation${(checkpoint.operations?.length ?? 0) === 1 ? "" : "s"}`)}
                    ${reviewChip(`${checkpoint.focus_loop_ids?.length ?? 0} focus loop${(checkpoint.focus_loop_ids?.length ?? 0) === 1 ? "" : "s"}`)}
                  </div>
                  ${renderCompactTrust({
                    generationLabel: "AI-authored checkpoint",
                    generationTone: "attention",
                    contextSources: [
                      `${checkpoint.operations?.length ?? 0} deterministic operation${(checkpoint.operations?.length ?? 0) === 1 ? "" : "s"}`,
                      `${checkpoint.focus_loop_ids?.length ?? 0} focus loop${(checkpoint.focus_loop_ids?.length ?? 0) === 1 ? "" : "s"}`,
                    ],
                    assumptions: [],
                    confidenceLabel: executed ? "Already executed" : isCurrent ? "Current checkpoint" : "Queued checkpoint",
                    confidenceTone: executed ? "progress" : isCurrent ? "attention" : "neutral",
                    freshnessLabel: snapshot.session.updated_at_utc ? `Session updated ${formatRelativeTime(snapshot.session.updated_at_utc)}` : null,
                    freshnessTone: executed ? "progress" : "neutral",
                    rollbackLabel: executed ? "Check execution history for rollback cues" : "No mutation until execution",
                    rollbackTone: executed ? "caution" : "progress",
                    impactSummary: isCurrent
                      ? `Review ${checkpoint.operations?.length ?? 0} staged operation${(checkpoint.operations?.length ?? 0) === 1 ? "" : "s"} before execution.`
                      : `Checkpoint ${index + 1} remains in the saved plan queue.`,
                    impactTone: isCurrent ? "attention" : "neutral",
                  })}
                </article>
              `;
            })
            .join("")}
        </div>
      `
      : '<p class="review-shell-empty">No checkpoints are available yet.</p>';
    return;
  }

  if (state.activeMode === "relationship") {
    const snapshot = state.relationshipSnapshot;
    elements.queue.innerHTML = snapshot?.items?.length
      ? `
        <div class="review-shell-rail-header">
          <h3>Queue rail</h3>
          <p>${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? "" : "s"} · ${escapeHtml(snapshot.session.query)}</p>
        </div>
        <div class="review-shell-rail-list">
          ${snapshot.items.map((item) => renderRelationshipQueueCard(snapshot, item)).join("")}
        </div>
      `
      : relationshipEmptyStateHtml(snapshot);
    return;
  }

  if (state.activeMode === "enrichment") {
    const snapshot = state.enrichmentSnapshot;
    elements.queue.innerHTML = snapshot?.items?.length
      ? `
        <div class="review-shell-rail-header">
          <h3>Queue rail</h3>
          <p>${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? "" : "s"} · ${escapeHtml(snapshot.session.query)}</p>
        </div>
        <div class="review-shell-rail-list">
          ${snapshot.items.map((item) => renderEnrichmentQueueCard(snapshot, item)).join("")}
        </div>
      `
      : enrichmentEmptyStateHtml(snapshot);
    return;
  }

  const cohorts = (state.reviewData?.[state.reviewMode] ?? []).filter((item) => item.count > 0);
  elements.queue.innerHTML = cohorts.length
    ? `
      <div class="review-shell-rail-header">
        <h3>Cohort rail</h3>
        <p>${cohorts.length} active cohort${cohorts.length === 1 ? "" : "s"} · ${state.reviewMode === "daily" ? "daily" : "weekly"} hygiene review</p>
      </div>
      <div class="review-shell-rail-list">
        ${cohorts
          .map((cohort) => {
            const active = state.selectedCohortKey === cohort.cohort;
            const drifted = cohortDrifted(cohort, state.reviewData?.generated_at_utc ?? null);
            return `
              <button type="button" class="review-shell-rail-card review-shell-rail-card--button ${active ? "is-active" : ""}" data-review-action="cohort-select" data-cohort-key="${escapeHtml(cohort.cohort)}">
                <div class="review-shell-rail-card-header">
                  <strong>${escapeHtml(cohortLabel(cohort))}</strong>
                  ${reviewChip(`${cohort.count} item${cohort.count === 1 ? "" : "s"}`, cohort.count > 0 ? "alert" : "default")}
                </div>
                <div class="review-shell-inline-chip-row">
                  ${reviewChip(cohortDescriptor(cohort).label, "default")}
                  ${drifted ? reviewChip("Snapshot drift", "alert") : reviewChip(state.reviewMode === "daily" ? "Daily cadence" : "Weekly cadence")}
                </div>
                <p>${escapeHtml(cohortDescriptor(cohort).why)}</p>
                ${renderCompactTrust(cohortTrustMetadata(cohort, state.reviewMode, state.reviewData?.generated_at_utc ?? null))}
              </button>
            `;
          })
          .join("")}
      </div>
    `
    : cohortEmptyStateHtml(state.reviewMode);
}

function renderLoopSummary(loop: { id: number; raw_text: string; title?: string | null; status?: string | null; summary?: string | null; next_action?: string | null; project?: string | null; due_date?: string | null; due_at_utc?: string | null; tags?: string[] | undefined }): string {
  return `
    <article class="review-shell-loop-summary">
      <div class="review-shell-loop-summary-header">
        <div>
          <p class="support-eyebrow">Loop #${loop.id}</p>
          <h4>${escapeHtml(loopTitle(loop))}</h4>
        </div>
        ${loop.status ? reviewChip(loop.status) : ""}
      </div>
      <p>${escapeHtml(loopPreview(loop))}</p>
      <div class="review-shell-inline-chip-row">
        ${loop.next_action ? reviewChip(`Next: ${loop.next_action}`) : reviewChip("Next action not set", "alert")}
        ${loop.project ? reviewChip(`Project: ${loop.project}`) : ""}
        ${loop.due_date ? reviewChip(`Due: ${loop.due_date}`) : ""}
        ${loop.due_at_utc ? reviewChip(`Due at: ${formatTimestamp(loop.due_at_utc)}`) : ""}
        ${(loop.tags ?? []).length ? reviewChip(`Tags: ${(loop.tags ?? []).join(", ")}`) : ""}
      </div>
    </article>
  `;
}

function renderRelationshipCandidateActions(loopId: number, candidate: RelationshipReviewCandidateResponse): string {
  const selectedAction = selectedRelationshipAction();
  const canUseSelectedPreset = selectedAction != null
    && (selectedAction.relationship_type === "suggested" || selectedAction.relationship_type === candidate.relationship_type);

  return `
    <div class="review-shell-inline-actions review-shell-inline-actions--decision">
      ${selectedAction
        ? `<button type="button" class="secondary" data-review-action="relationship-use-preset" data-loop-id="${loopId}" data-candidate-id="${candidate.id}" data-candidate-type="${escapeHtml(candidate.relationship_type)}" ${canUseSelectedPreset ? "" : "disabled"}>Use “${escapeHtml(selectedAction.name)}”</button>`
        : ""}
      <button type="button" data-review-action="relationship-confirm" data-loop-id="${loopId}" data-candidate-id="${candidate.id}" data-candidate-type="${escapeHtml(candidate.relationship_type)}" data-relationship-type="${escapeHtml(candidate.relationship_type)}">Confirm ${escapeHtml(candidate.relationship_type)}</button>
      ${candidate.relationship_type === "related"
        ? `<button type="button" class="secondary" data-review-action="relationship-confirm" data-loop-id="${loopId}" data-candidate-id="${candidate.id}" data-candidate-type="related" data-relationship-type="duplicate">Confirm as duplicate</button>`
        : `<button type="button" class="secondary" data-review-action="relationship-merge" data-loop-id="${loopId}" data-candidate-id="${candidate.id}">Merge</button>`}
      <button type="button" class="secondary" data-review-action="relationship-dismiss" data-loop-id="${loopId}" data-candidate-id="${candidate.id}" data-candidate-type="${escapeHtml(candidate.relationship_type)}">Dismiss</button>
    </div>
  `;
}

function renderRelationshipCandidateCard(loopId: number, candidate: RelationshipReviewCandidateResponse): string {
  const decisionText = candidate.relationship_type === "duplicate"
    ? "Confirm duplicate, merge the loops, or dismiss this candidate."
    : "Confirm related, confirm as duplicate, or dismiss this candidate.";
  const warningText = candidate.relationship_type === "duplicate"
    ? "Duplicate confirmation or merge is not reversible in-place."
    : "Confirm as duplicate is not reversible in-place. Use that path only if both loops should collapse together.";

  return `
    <article class="review-shell-candidate-card review-shell-candidate-card--${escapeHtml(candidate.relationship_type)}">
      <div class="review-shell-candidate-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(candidate.relationship_type)} candidate</p>
          <h4>${escapeHtml(loopTitle(candidate))}</h4>
        </div>
        ${reviewChip(`${Math.round(candidate.score * 100)}%`, candidate.score >= 0.9 ? "alert" : "default")}
      </div>
      <p>${escapeHtml(candidate.raw_text_preview || candidate.raw_text)}</p>
      <div class="review-shell-inline-chip-row">
        ${candidate.existing_state ? reviewChip(`Existing state: ${candidate.existing_state}`) : ""}
        ${candidate.existing_source ? reviewChip(`Existing source: ${candidate.existing_source}`) : ""}
        ${candidate.project ? reviewChip(`Project: ${candidate.project}`) : ""}
      </div>
      <section class="review-shell-decision-block">
        <p class="support-eyebrow">Decision required</p>
        <p class="review-shell-decision-copy">${escapeHtml(decisionText)}</p>
        <p class="review-shell-warning-copy">${escapeHtml(warningText)}</p>
        ${renderRelationshipCandidateActions(loopId, candidate)}
      </section>
    </article>
  `;
}

function renderSuggestionCard(suggestion: EnrichmentReviewQueueItemResponse["pending_suggestions"][number]): string {
  const snapshot = state.enrichmentSnapshot;
  const sessionName = snapshot?.session?.name ?? "Enrichment review";
  return renderActionCardDeck(
    [buildEnrichmentSuggestionCard({
      suggestion,
      selectedAction: selectedEnrichmentAction(),
      context: reviewImpactHandoffContext(sessionName),
    })],
    "",
  );
}

function renderClarificationForm(item: EnrichmentReviewQueueItemResponse): string {
  if (!item.pending_clarifications.length) {
    return '<p class="review-shell-empty-inline">No pending clarifications remain for this loop.</p>';
  }

  return `
    <form class="review-shell-clarification-form" data-review-action="enrichment-clarifications-submit" data-loop-id="${item.loop.id}">
      <div class="review-shell-clarification-list">
        ${item.pending_clarifications
          .map((clarification) => `
            <label class="review-shell-clarification-card" for="review-shell-clarification-${clarification.id}">
              <span>${escapeHtml(clarification.question)}</span>
              <input id="review-shell-clarification-${clarification.id}" type="text" data-clarification-id="${clarification.id}" placeholder="Type an answer" autocomplete="off">
            </label>
          `)
          .join("")}
      </div>
      <section class="review-shell-decision-block">
        <p class="support-eyebrow">Decision required</p>
        <p class="review-shell-decision-copy">Answer at least one clarification, then rerun enrichment so the queue reflects the new context.</p>
      </section>
      <div class="review-shell-inline-actions review-shell-inline-actions--stack-mobile">
        <button type="submit">Answer clarifications & rerun</button>
      </div>
    </form>
  `;
}

function renderWorkspace(): void {
  if (!elements) {
    return;
  }

  if (state.activeMode === "planning") {
    const snapshot = state.planningSnapshot;
    const currentCheckpoint = snapshot?.current_checkpoint ?? null;
    const targetLoops = snapshot?.target_loops ?? [];
    elements.workspace.innerHTML = snapshot?.session
      ? `
        <section class="review-shell-section">
          <div class="review-shell-section-header">
            <h3>Decision detail</h3>
            <p>Review one checkpoint at a time, then execute only when the proposed changes look right.</p>
          </div>
          <div class="review-shell-focus-card">
            <div class="review-shell-focus-card-header">
              <div>
                <p class="support-eyebrow">Current checkpoint</p>
                <h3>${escapeHtml(currentCheckpoint?.title || `Checkpoint ${snapshot.session.current_checkpoint_index + 1}`)}</h3>
              </div>
              ${reviewChip(snapshot.session.status.replaceAll("_", " "), snapshot.session.status === "completed" ? "success" : "default")}
            </div>
            <p>${escapeHtml(currentCheckpoint?.summary || snapshot.plan_summary)}</p>
            <div class="review-shell-inline-chip-row">
              ${reviewChip(`Success criteria: ${currentCheckpoint?.success_criteria || "Not provided"}`)}
              ${reviewChip(`Generated ${formatRelativeTime(planningGeneratedAt(snapshot))}`)}
            </div>
            ${renderPanelTrust(planningTrustMetadata(snapshot))}
          </div>
          <section class="review-shell-subsection">
            <div class="review-shell-section-header">
              <h4>Focus loops</h4>
              <p>${currentCheckpoint?.focus_loop_ids?.length ?? 0} loop${(currentCheckpoint?.focus_loop_ids?.length ?? 0) === 1 ? "" : "s"} targeted</p>
            </div>
            <div class="review-shell-loop-grid">
              ${currentCheckpoint?.focus_loop_ids?.length
                ? currentCheckpoint.focus_loop_ids
                  .map((id) => targetLoops.find((loop) => loop.id === id) ?? null)
                  .filter((loop): loop is NonNullable<typeof loop> => loop != null)
                  .map((loop) => renderLoopSummary(loop))
                  .join("") || '<p class="review-shell-empty-inline">Focus-loop IDs exist, but none were present in the grounded snapshot.</p>'
                : '<p class="review-shell-empty-inline">This checkpoint does not directly target existing loops.</p>'}
            </div>
          </section>
          <section class="review-shell-subsection">
            <div class="review-shell-section-header">
              <h4>Deterministic operations</h4>
              <p>${currentCheckpoint?.operations?.length ?? 0} operation${(currentCheckpoint?.operations?.length ?? 0) === 1 ? "" : "s"}</p>
            </div>
            <div class="review-shell-operation-list">
              ${(currentCheckpoint?.operations ?? [])
                .map((operation) => `
                  <article class="review-shell-operation-card">
                    <div class="review-shell-candidate-header">
                      <div>
                        <p class="support-eyebrow">${escapeHtml(String(operation["kind"] || "operation"))}</p>
                        <h4>${escapeHtml(String(operation["summary"] || "No summary provided."))}</h4>
                      </div>
                    </div>
                    <details>
                      <summary>Inspect payload</summary>
                      <pre>${escapeHtml(JSON.stringify(operation, null, 2))}</pre>
                    </details>
                  </article>
                `)
                .join("") || '<p class="review-shell-empty-inline">No operations were recorded for this checkpoint.</p>'}
            </div>
          </section>
        </section>
      `
      : '<p class="review-shell-empty">No planning session selected.</p>';
    return;
  }

  if (state.activeMode === "relationship") {
    const snapshot = state.relationshipSnapshot;
    const item = snapshot?.current_item ?? null;
    elements.workspace.innerHTML = snapshot?.session
      ? item
        ? `
          <section class="review-shell-section">
            <div class="review-shell-section-header">
              <h3>Decision detail</h3>
              <p>Make one relationship decision at a time with queue context preserved.</p>
            </div>
            <div class="review-shell-comparison-grid">
              ${renderLoopSummary(item.loop)}
              <article class="review-shell-focus-card">
                <div class="review-shell-focus-card-header">
                  <div>
                    <p class="support-eyebrow">Why this item is here</p>
                    <h3>${escapeHtml(relationshipReasonText(item))}</h3>
                  </div>
                  ${reviewChip(`Progress ${describeProgressFraction(snapshot.current_index, snapshot.loop_count)}`, "default")}
                </div>
                <div class="review-shell-inline-chip-row">
                  ${reviewChip(`Session ${snapshot.session.relationship_kind} · ${snapshot.session.query}`)}
                  ${reviewChip(relationshipReasonChip(item), relationshipPrimaryCandidate(item)?.relationship_type === "duplicate" ? "alert" : "default")}
                  ${relationshipItemDrifted(snapshot, item) ? reviewChip("Snapshot drift — refresh recommended", "alert") : reviewChip(`Queue refreshed ${formatRelativeTime(snapshot.session.updated_at_utc)}`)}
                </div>
                <p>${escapeHtml(relationshipRecommendation(item))}</p>
                <section class="review-shell-decision-block">
                  <p class="support-eyebrow">Decision required</p>
                  <p class="review-shell-decision-copy">${escapeHtml(relationshipDecisionLabel(item))}</p>
                  ${relationshipConsequenceWarning(item) ? `<p class="review-shell-warning-copy">${escapeHtml(relationshipConsequenceWarning(item) ?? "")}</p>` : ""}
                  <div class="review-shell-inline-actions review-shell-inline-actions--nav">
                    <button type="button" class="secondary" data-review-action="relationship-move-prev" ${snapshot.current_index != null && snapshot.current_index > 0 ? "" : "disabled"}>Previous</button>
                    <button type="button" class="secondary" data-review-action="relationship-move-next" ${snapshot.current_index != null && snapshot.current_index < snapshot.items.length - 1 ? "" : "disabled"}>Next</button>
                    <button type="button" class="secondary" ${queueItemButtonAttributes(toDoHash(item.loop.id))}>Open loop in Do</button>
                  </div>
                </section>
                ${renderPanelTrust(relationshipTrustMetadata(snapshot, item))}
              </article>
            </div>
            <section class="review-shell-subsection">
              <div class="review-shell-section-header">
                <h4>Primary candidates</h4>
                <p>Highest-signal options in the current queue item.</p>
              </div>
              <div class="review-shell-candidate-grid">
                ${item.duplicate_candidates.map((candidate) => renderRelationshipCandidateCard(item.loop.id, candidate)).join("") || '<p class="review-shell-empty-inline">No duplicate candidates remain.</p>'}
                ${item.related_candidates.map((candidate) => renderRelationshipCandidateCard(item.loop.id, candidate)).join("") || '<p class="review-shell-empty-inline">No related candidates remain.</p>'}
              </div>
            </section>
          </section>
        `
        : relationshipEmptyStateHtml(snapshot)
      : relationshipEmptyStateHtml(snapshot);
    return;
  }

  if (state.activeMode === "enrichment") {
    const snapshot = state.enrichmentSnapshot;
    const item = snapshot?.current_item ?? null;
    elements.workspace.innerHTML = snapshot?.session
      ? item
        ? `
          <section class="review-shell-section">
            <div class="review-shell-section-header">
              <h3>Decision detail</h3>
              <p>Resolve one loop's pending suggestions or clarifications without losing your place.</p>
            </div>
            <div class="review-shell-comparison-grid">
              ${renderLoopSummary(item.loop)}
              <article class="review-shell-focus-card">
                <div class="review-shell-focus-card-header">
                  <div>
                    <p class="support-eyebrow">Why this item is here</p>
                    <h3>${escapeHtml(enrichmentReasonText(item))}</h3>
                  </div>
                  ${reviewChip(`Progress ${describeProgressFraction(snapshot.current_index, snapshot.loop_count)}`, "default")}
                </div>
                <div class="review-shell-inline-chip-row">
                  ${reviewChip(`Session ${snapshot.session.pending_kind} · ${snapshot.session.query}`)}
                  ${reviewChip(enrichmentReasonChip(item), item.pending_clarification_count > 0 ? "alert" : "default")}
                  ${enrichmentItemDrifted(snapshot, item) ? reviewChip("Snapshot drift — refresh recommended", "alert") : reviewChip(`Newest pending ${formatRelativeTime(item.newest_pending_at)}`)}
                  ${enrichmentLowConfidence(item) ? reviewChip("Low confidence suggestion", "alert") : ""}
                </div>
                <p>${escapeHtml(enrichmentRecommendation(item))}</p>
                <section class="review-shell-decision-block">
                  <p class="support-eyebrow">Decision required</p>
                  <p class="review-shell-decision-copy">${escapeHtml(enrichmentDecisionLabel(item))}</p>
                  ${enrichmentApplyWarning(item) ? `<p class="review-shell-warning-copy">${escapeHtml(enrichmentApplyWarning(item) ?? "")}</p>` : ""}
                  <div class="review-shell-inline-actions review-shell-inline-actions--nav">
                    <button type="button" class="secondary" data-review-action="enrichment-move-prev" ${snapshot.current_index != null && snapshot.current_index > 0 ? "" : "disabled"}>Previous</button>
                    <button type="button" class="secondary" data-review-action="enrichment-move-next" ${snapshot.current_index != null && snapshot.current_index < snapshot.items.length - 1 ? "" : "disabled"}>Next</button>
                    <button type="button" class="secondary" ${queueItemButtonAttributes(toDoHash(item.loop.id))}>Open loop in Do</button>
                  </div>
                </section>
                ${renderPanelTrust(enrichmentTrustMetadata(snapshot, item))}
              </article>
            </div>
            <section class="review-shell-subsection">
              <div class="review-shell-section-header">
                <h4>Pending suggestions</h4>
                <p>${item.pending_suggestion_count} suggestion${item.pending_suggestion_count === 1 ? "" : "s"} ready for review.</p>
              </div>
              <div class="review-shell-suggestion-grid">
                ${item.pending_suggestions.length
                  ? item.pending_suggestions.map((suggestion) => renderSuggestionCard(suggestion)).join("")
                  : '<p class="review-shell-empty-inline">No pending suggestions remain.</p>'}
              </div>
            </section>
            <section class="review-shell-subsection">
              <div class="review-shell-section-header">
                <h4>Pending clarifications</h4>
                <p>${item.pending_clarification_count} clarification${item.pending_clarification_count === 1 ? "" : "s"} need answers.</p>
              </div>
              ${renderClarificationForm(item)}
            </section>
          </section>
        `
        : enrichmentEmptyStateHtml(snapshot)
      : enrichmentEmptyStateHtml(snapshot);
    return;
  }

  const cohort = selectedCohort();
  elements.workspace.innerHTML = cohort
    ? `
      <section class="review-shell-section">
        <div class="review-shell-section-header">
          <h3>Decision detail</h3>
          <p>${escapeHtml(cohortDescriptor(cohort).decision)}</p>
        </div>
        <div class="review-shell-focus-card">
          <div class="review-shell-focus-card-header">
            <div>
              <p class="support-eyebrow">Why this cohort is here</p>
              <h3>${escapeHtml(cohortLabel(cohort))}</h3>
            </div>
            ${reviewChip(`${cohort.count} item${cohort.count === 1 ? "" : "s"}`, cohort.count > 0 ? "alert" : "default")}
          </div>
          <div class="review-shell-inline-chip-row">
            ${reviewChip(state.reviewMode === "daily" ? "Daily hygiene review" : "Weekly hygiene review")}
            ${reviewChip(cohortDescriptor(cohort).label)}
            ${cohortDrifted(cohort, state.reviewData?.generated_at_utc ?? null) ? reviewChip("Snapshot drift — refresh recommended", "alert") : reviewChip(`Generated ${formatRelativeTime(state.reviewData?.generated_at_utc ?? null)}`)}
          </div>
          <p>${escapeHtml(cohortDescriptor(cohort).why)}</p>
          <section class="review-shell-decision-block">
            <p class="support-eyebrow">Decision required</p>
            <p class="review-shell-decision-copy">${escapeHtml(cohortDescriptor(cohort).decision)}</p>
          </section>
          ${renderPanelTrust(cohortTrustMetadata(cohort, state.reviewMode, state.reviewData?.generated_at_utc ?? null))}
        </div>
        <div class="review-shell-loop-grid">
          ${cohort.items.map((item) => renderCohortLoopCard(item)).join("") || '<p class="review-shell-empty-inline">No loop previews available for this cohort.</p>'}
        </div>
      </section>
    `
    : cohortEmptyStateHtml(state.reviewMode);
}

function renderLaunchSurface(
  surface: PlanningExecutionLaunchSurfaceResponse,
  sessionName: string,
  latestExecution: PlanningExecutionHistoryItemResponse,
): string {
  const card = buildPlanningLaunchSurfaceCard(surface, latestExecution, planningImpactHandoffContext(sessionName));
  return card ? renderActionCardDeck([card], "") : "";
}

function renderFollowUpResource(
  resource: PlanningExecutionFollowUpResourceResponse,
  sessionName: string,
): string {
  return renderActionCardDeck(
    [buildPlanningFollowUpResourceCard(resource, planningImpactHandoffContext(sessionName))],
    "",
  );
}

function renderPlanningImpact(snapshot: PlanningSessionSnapshotResponse | null): string {
  const latestExecution = snapshot?.execution_history?.at(-1) ?? null;
  const recovery = currentPlanningRecovery(snapshot);
  if (!snapshot?.session) {
    return '<p class="review-shell-empty">Planning impact previews appear after a session loads.</p>';
  }

  if (!latestExecution) {
    const card: OperatorActionCard = applyContinuityRecovery({
      id: `review-plan-empty-${snapshot.session.id}`,
      kind: "refresh",
      tone: "neutral",
      eyebrow: "Impact preview",
      title: "Nothing executed yet",
      summary: "Review the current checkpoint and its planned operations before executing the first step.",
      rationale: "Planning impact stays action-first by surfacing the next checkpoint even before any execution history exists.",
      preview: [
        { label: "Status", value: snapshot.session.status.replaceAll("_", " ") },
        { label: "Assumptions", value: `${snapshot.assumptions?.length ?? 0}` },
        { label: "Target loops", value: `${snapshot.target_loops?.length ?? 0}` },
      ],
      trust: planningTrustMetadata(snapshot),
      handoff: {
        changeSummary: "No execution history exists yet for this plan.",
        createdResources: [],
        nextStep: "Inspect the checkpoint payload, then execute when the planned operations look right.",
        breadcrumbs: ["Home", "Plan", snapshot.session.name],
      },
      actions: [
        {
          type: "open",
          label: "Resume plan",
          variant: "primary",
          location: createLocation({ state: "plan", reviewFocus: "planning", sessionId: snapshot.session.id, workingSetId: currentWorkingSetId() }),
          description: `Resume ${snapshot.session.name}`,
        },
      ],
    }, recovery);
    return renderActionCardDeck([card], '');
  }

  return `
    ${renderActionCardDeck([
      buildPlanningExecutionSummaryCard(
        snapshot,
        latestExecution,
        {
          generationLabel: "Deterministic execution result",
          generationTone: "progress",
          contextSources: [
            `${latestExecution.operation_count} execution result${latestExecution.operation_count === 1 ? "" : "s"}`,
            `${latestExecution.follow_up_resources?.length ?? 0} follow-up resource${(latestExecution.follow_up_resources?.length ?? 0) === 1 ? "" : "s"}`,
            `${latestExecution.launch_surfaces?.length ?? 0} launch surface${(latestExecution.launch_surfaces?.length ?? 0) === 1 ? "" : "s"}`,
          ],
          assumptions: ["Execution reflects the latest stored checkpoint payload."],
          confidenceLabel: latestExecution.launch_surfaces?.length ? "A downstream queue is ready" : "Execution completed without a dedicated next queue",
          confidenceTone: latestExecution.launch_surfaces?.length ? "attention" : "progress",
          freshnessLabel: `Executed ${formatRelativeTime(latestExecution.executed_at_utc)}`,
          freshnessTone: "progress",
          rollbackLabel: describePlanningRollbackCue(latestExecution.rollback_cues),
          rollbackTone: latestExecution.rollback_cues?.rollback_supported_operation_count ? "caution" : "neutral",
          impactSummary: latestExecution.summary && typeof latestExecution.summary === "object" && typeof latestExecution.summary["summary"] === "string"
            ? String(latestExecution.summary["summary"])
            : `Checkpoint execution produced ${latestExecution.operation_count} result${latestExecution.operation_count === 1 ? "" : "s"}.`,
          impactTone: latestExecution.launch_surfaces?.length ? "attention" : "progress",
        },
        planningImpactHandoffContext(snapshot.session.name),
        { recovery },
      ),
    ], '')}
    ${(latestExecution.launch_surfaces ?? []).map((surface) => renderLaunchSurface(surface, snapshot.session.name, latestExecution)).join("")}
    ${(latestExecution.follow_up_resources ?? []).map((resource) => renderFollowUpResource(resource, snapshot.session.name)).join("")}
  `;
}

function renderRelationshipImpact(snapshot: RelationshipReviewSessionSnapshotResponse | null): string {
  const item = snapshot?.current_item ?? null;
  const candidate = relationshipPrimaryCandidate(item);
  if (!snapshot?.session) {
    return '<p class="review-shell-empty">Impact previews appear after a relationship session loads.</p>';
  }
  if (!item || !candidate) {
    return '<p class="review-shell-empty">Refresh the session after more similarity candidates appear, or edit the query to broaden the queue.</p>';
  }
  const recommendedDecision = candidate.relationship_type === "duplicate"
    ? `Confirming duplicate would consolidate ${loopTitle(item.loop)} with ${loopTitle(candidate)}.`
    : "Confirming related would preserve both loops but record an explicit relationship between them.";

  return renderActionCardDeck([
    buildRelationshipImpactCard({
      snapshot,
      candidate,
      recommendedDecision,
      recommendationTitle: relationshipRecommendation(item),
      trust: {
        ...relationshipTrustMetadata(snapshot, item),
        impactSummary: recommendedDecision,
        impactTone: candidate.relationship_type === "duplicate" ? "attention" : "neutral",
      },
      selectedAction: selectedRelationshipAction(),
      context: {
        ...reviewImpactHandoffContext(snapshot.session.name),
        loopId: item.loop.id,
      },
      recovery: currentReviewSessionRecovery("relationship", snapshot),
    }),
  ], '');
}

function renderEnrichmentImpact(snapshot: EnrichmentReviewSessionSnapshotResponse | null): string {
  const item = snapshot?.current_item ?? null;
  if (!snapshot?.session) {
    return '<p class="review-shell-empty">Impact previews appear after an enrichment session loads.</p>';
  }
  if (!item) {
    return '<p class="review-shell-empty">Refresh the saved session after new suggestions or clarifications appear, or edit the query if the queue needs a broader scope.</p>';
  }
  const firstSuggestion = item.pending_suggestions[0] ?? null;
  const suggestionFields = firstSuggestion && typeof firstSuggestion.parsed === "object" && firstSuggestion.parsed
    ? Object.keys(firstSuggestion.parsed).filter((key) => !["confidence", "needs_clarification"].includes(key))
    : [];
  const recommendedDecision = item.pending_clarification_count > 0
    ? "Answering clarifications reruns enrichment and can supersede stale suggestions."
    : suggestionFields.length
      ? `Applying the top suggestion may update ${suggestionFields.join(", ")}.`
      : "Applying the top suggestion may update the loop's structured fields.";

  return renderActionCardDeck([
    buildEnrichmentImpactCard({
      snapshot,
      item,
      recommendationTitle: enrichmentRecommendation(item),
      recommendedDecision,
      trust: {
        ...enrichmentTrustMetadata(snapshot, item),
        impactSummary: recommendedDecision,
        impactTone: item.pending_clarification_count > 0 ? "attention" : "neutral",
      },
      selectedAction: selectedEnrichmentAction(),
      context: reviewImpactHandoffContext(snapshot.session.name),
      recovery: currentReviewSessionRecovery("enrichment", snapshot),
    }),
  ], '');
}

function cohortDescriptor(cohort: LoopReviewCohortResponse): { label: string; why: string; decision: string } {
  return COHORT_DESCRIPTORS[cohort.cohort as keyof typeof COHORT_DESCRIPTORS] ?? {
    label: cohort.cohort.replaceAll("_", " "),
    why: "This cohort groups loops that need review attention.",
    decision: "Choose the smallest next meaningful cleanup action.",
  };
}

function cohortLabel(cohort: LoopReviewCohortResponse): string {
  return cohortDescriptor(cohort).label;
}

function selectedCohort(): LoopReviewCohortResponse | null {
  const cohorts = state.reviewData?.[state.reviewMode] ?? [];
  if (!cohorts.length) {
    return null;
  }
  const selected = cohorts.find((cohort) => cohort.cohort === state.selectedCohortKey) ?? null;
  return selected ?? cohorts.find((cohort) => cohort.count > 0) ?? cohorts[0] ?? null;
}

function renderCohortLoopCard(item: LoopReviewCohortItem): string {
  return `
    <article class="review-shell-loop-summary">
      <div class="review-shell-loop-summary-header">
        <div>
          <p class="support-eyebrow">Loop #${item.id}</p>
          <h4>${escapeHtml(loopTitle(item))}</h4>
        </div>
        ${reviewChip(item.status)}
      </div>
      <p>${escapeHtml(item.next_action?.trim() || item.raw_text)}</p>
      <div class="review-shell-inline-actions">
        <button type="button" ${queueItemButtonAttributes(toDoHash(item.id))}>Open in Do</button>
      </div>
    </article>
  `;
}

function renderCohortImpact(cohort: LoopReviewCohortResponse | null): string {
  if (!cohort) {
    return '<p class="review-shell-empty">Impact previews appear after a cohort is selected.</p>';
  }
  const descriptor = cohortDescriptor(cohort);
  return renderActionCardDeck([
    buildCohortImpactCard({
      cohort,
      decisionLabel: descriptor.decision,
      why: descriptor.why,
      trust: cohortTrustMetadata(cohort, state.reviewMode, state.reviewData?.generated_at_utc ?? null),
      reviewMode: state.reviewMode,
      context: cohortImpactHandoffContext(),
      recovery: surfaceRecoveryForLocation(createLocation({ state: "review", workingSetId: currentWorkingSetId() })),
    }),
  ], '');
}

function renderImpact(): void {
  if (!elements) {
    return;
  }

  if (state.activeMode === "planning") {
    elements.impact.innerHTML = renderPlanningImpact(state.planningSnapshot);
    return;
  }
  if (state.activeMode === "relationship") {
    elements.impact.innerHTML = renderRelationshipImpact(state.relationshipSnapshot);
    return;
  }
  if (state.activeMode === "enrichment") {
    elements.impact.innerHTML = renderEnrichmentImpact(state.enrichmentSnapshot);
    return;
  }
  elements.impact.innerHTML = renderCohortImpact(selectedCohort());
}

function renderAll(): void {
  renderHeader();
  renderControls();
  renderOverview();
  renderQueue();
  renderWorkspace();
  renderImpact();
}

async function loadPlanningMode(requestedSessionId: number | null): Promise<void> {
  const sessions = await fetchPlanningSessions();
  if (redirectRequestedSessionOrHome("planning", requestedSessionId, sessions)) {
    return;
  }
  const sessionId = requestedSessionId ?? choosePersistedId(sessions, state.planningSessionId);
  const snapshot = await fetchRequestedSnapshotOrAbort(requestedSessionId, sessionId, fetchPlanningSession);
  if (snapshot === ABORT_SESSION_LOAD) {
    return;
  }
  state = {
    ...state,
    activeMode: "planning",
    planningSessions: sessions,
    planningSessionId: sessionId,
    planningSnapshot: snapshot,
  };
  setStatus(
    snapshot?.session
      ? `Loaded ${snapshot.session.name}. ${snapshot.session.executed_checkpoint_count}/${snapshot.session.checkpoint_count} checkpoints executed.`
      : "Create a planning session to start a checkpointed plan.",
  );
}

async function loadRelationshipMode(requestedSessionId: number | null): Promise<void> {
  const [actions, sessions] = await Promise.all([fetchRelationshipActions(), fetchRelationshipSessions()]);
  if (redirectRequestedSessionOrHome("relationship", requestedSessionId, sessions)) {
    return;
  }
  const sessionId = requestedSessionId ?? choosePersistedId(sessions, state.relationshipSessionId);
  const actionId = choosePersistedId(actions, state.relationshipActionId);
  const snapshot = await fetchRequestedSnapshotOrAbort(requestedSessionId, sessionId, fetchRelationshipSession);
  if (snapshot === ABORT_SESSION_LOAD) {
    return;
  }
  state = {
    ...state,
    activeMode: "relationship",
    relationshipActions: actions,
    relationshipSessions: sessions,
    relationshipActionId: actionId,
    relationshipSessionId: sessionId,
    relationshipSnapshot: snapshot,
  };
  setStatus(
    snapshot?.session
      ? `Loaded ${snapshot.session.name}. ${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? "" : "s"}.`
      : "Create a relationship-review session to review duplicate and related candidates.",
  );
}

async function loadEnrichmentMode(requestedSessionId: number | null): Promise<void> {
  const [actions, sessions] = await Promise.all([fetchEnrichmentActions(), fetchEnrichmentSessions()]);
  if (redirectRequestedSessionOrHome("enrichment", requestedSessionId, sessions)) {
    return;
  }
  const sessionId = requestedSessionId ?? choosePersistedId(sessions, state.enrichmentSessionId);
  const actionId = choosePersistedId(actions, state.enrichmentActionId);
  const snapshot = await fetchRequestedSnapshotOrAbort(requestedSessionId, sessionId, fetchEnrichmentSession);
  if (snapshot === ABORT_SESSION_LOAD) {
    return;
  }
  state = {
    ...state,
    activeMode: "enrichment",
    enrichmentActions: actions,
    enrichmentSessions: sessions,
    enrichmentActionId: actionId,
    enrichmentSessionId: sessionId,
    enrichmentSnapshot: snapshot,
  };
  setStatus(
    snapshot?.session
      ? `Loaded ${snapshot.session.name}. ${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? "" : "s"}.`
      : "Create an enrichment-review session to review suggestions and clarifications.",
  );
}

async function loadCohortsMode(): Promise<void> {
  const reviewData = await fetchReviewData();
  const cohort = selectedCohortFromData(reviewData, state.reviewMode, state.selectedCohortKey);
  state = {
    ...state,
    activeMode: "cohorts",
    reviewData,
    selectedCohortKey: cohort?.cohort ?? null,
  };
  setStatus(`Loaded ${state.reviewMode} review cohorts.`);
}

function selectedCohortFromData(
  reviewData: LoopReviewResponse,
  reviewMode: "daily" | "weekly",
  cohortKey: string | null,
): LoopReviewCohortResponse | null {
  const cohorts = reviewData[reviewMode] ?? [];
  return cohorts.find((cohort) => cohort.cohort === cohortKey)
    ?? cohorts.find((cohort) => cohort.count > 0)
    ?? cohorts[0]
    ?? null;
}

async function loadMode(focus: ReviewFocus, sessionId: number | null = null): Promise<void> {
  if (!elements || loading) {
    return;
  }
  loading = true;
  try {
    state = {
      ...state,
      workingSets: await fetchWorkingSets().catch(() => state.workingSets),
    };
    if (focus === "planning") {
      await loadPlanningMode(sessionId);
    } else if (focus === "relationship") {
      await loadRelationshipMode(sessionId);
    } else if (focus === "enrichment") {
      await loadEnrichmentMode(sessionId);
    } else {
      await loadCohortsMode();
    }
    renderAll();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to load review workspace";
    setStatus(message, true);
  } finally {
    loading = false;
  }
}

async function navigateToFocus(detail: ReviewFocusDetail): Promise<void> {
  await loadMode(detail.focus, detail.sessionId);
}

function currentFocusDetail(): ReviewFocusDetail {
  if (state.activeMode === "planning") {
    return { focus: "planning", sessionId: state.planningSessionId };
  }
  if (state.activeMode === "relationship") {
    return { focus: "relationship", sessionId: state.relationshipSessionId };
  }
  if (state.activeMode === "enrichment") {
    return { focus: "enrichment", sessionId: state.enrichmentSessionId };
  }
  return { focus: "cohorts", sessionId: null };
}

function dialogApi(): {
  promptDialog: (config: PromptDialogConfig) => Promise<Record<string, string> | null>;
  confirmDialog: (config: DialogConfig) => Promise<boolean>;
  alertDialog: (config: AlertDialogConfig) => Promise<void>;
} {
  const { promptDialog, confirmDialog, alertDialog } = modals;
  return { promptDialog, confirmDialog, alertDialog };
}

function dialogValue(values: Record<string, string>, key: string): string {
  return values[key] ?? "";
}

function dialogOptionalValue(values: Record<string, string>, key: string): string | null {
  const value = dialogValue(values, key).trim();
  return value ? value : null;
}

function dialogPositiveInteger(values: Record<string, string>, key: string): number {
  return Number.parseInt(dialogValue(values, key), 10);
}

function validatePositiveInteger(value: string, label: string): string | null {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return `${label} must be a positive integer.`;
  }
  return null;
}

async function planningSessionDialog(): Promise<PlanningSessionCreateRequest | null> {
  const dialogs = dialogApi();
  const result = await dialogs.promptDialog({
    eyebrow: "Planning workflows",
    title: "Create planning session",
    description: "Generate a checkpointed workflow grounded in current loops, memory, and optional retrieval context.",
    confirmLabel: "Create session",
    fields: [
      { name: "name", label: "Session name", required: true },
      { name: "prompt", label: "Planning prompt", type: "textarea", rows: 5, required: true, placeholder: "Create a checkpointed plan for ..." },
      { name: "query", label: "DSL query (optional)", value: "status:open", placeholder: "status:open project:launch" },
      { name: "loop_limit", label: "Loop limit", type: "number", value: "10", inputMode: "numeric" },
      { name: "include_memory_context", label: "Include memory context", type: "select", value: "true", options: [{ value: "true", label: "Yes" }, { value: "false", label: "No" }] },
      { name: "include_rag_context", label: "Include RAG context", type: "select", value: "false", options: [{ value: "false", label: "No" }, { value: "true", label: "Yes" }] },
      { name: "rag_k", label: "RAG chunk count", type: "number", value: "5", inputMode: "numeric" },
      { name: "rag_scope", label: "RAG scope (optional)", value: "", placeholder: "launch-notes" },
    ],
    validate: (values) => {
      if (!dialogValue(values, "name")) {
        return "Enter a planning session name.";
      }
      if (!dialogValue(values, "prompt")) {
        return "Enter a planning prompt.";
      }
      return validatePositiveInteger(dialogValue(values, "loop_limit"), "Loop limit")
        || validatePositiveInteger(dialogValue(values, "rag_k"), "RAG chunk count");
    },
  });

  if (!result) {
    return null;
  }

  return {
    name: dialogValue(result, "name"),
    prompt: dialogValue(result, "prompt"),
    query: dialogOptionalValue(result, "query"),
    loop_limit: dialogPositiveInteger(result, "loop_limit"),
    include_memory_context: dialogValue(result, "include_memory_context") === "true",
    include_rag_context: dialogValue(result, "include_rag_context") === "true",
    rag_k: dialogPositiveInteger(result, "rag_k"),
    rag_scope: dialogOptionalValue(result, "rag_scope"),
  };
}

async function relationshipSessionDialog(
  existingSession: RelationshipReviewSessionResponse | null,
): Promise<RelationshipReviewSessionCreateRequest | RelationshipReviewSessionUpdateRequest | null> {
  const dialogs = dialogApi();
  const result = await dialogs.promptDialog({
    eyebrow: "Relationship review",
    title: existingSession ? "Edit review session" : "Create review session",
    description: "Persist a filtered relationship-review worklist so you can leave and return without losing your place.",
    confirmLabel: existingSession ? "Save session" : "Create session",
    fields: [
      { name: "name", label: "Session name", value: existingSession?.name || "", required: true, maxLength: 120, autocomplete: "off" },
      { name: "query", label: "DSL query", value: existingSession?.query || "status:open", required: true, maxLength: 500, autocomplete: "off" },
      { name: "relationship_kind", label: "Relationship kind", type: "select", value: existingSession?.relationship_kind || "all", options: [{ value: "all", label: "All" }, { value: "duplicate", label: "Duplicates" }, { value: "related", label: "Related" }] },
      { name: "candidate_limit", label: "Candidates per loop", type: "number", value: String(existingSession?.candidate_limit || 3), inputMode: "numeric" },
      { name: "item_limit", label: "Loop limit", type: "number", value: String(existingSession?.item_limit || 25), inputMode: "numeric" },
    ],
    validate: (values) => {
      if (!dialogValue(values, "name")) {
        return "Enter a session name.";
      }
      if (!dialogValue(values, "query")) {
        return "Enter a DSL query.";
      }
      return validatePositiveInteger(dialogValue(values, "candidate_limit"), "Candidates per loop")
        || validatePositiveInteger(dialogValue(values, "item_limit"), "Loop limit");
    },
  });

  if (!result) {
    return null;
  }

  return {
    name: dialogValue(result, "name"),
    query: dialogValue(result, "query"),
    relationship_kind: (dialogValue(result, "relationship_kind") || "all") as NonNullable<RelationshipReviewSessionCreateRequest["relationship_kind"]>,
    candidate_limit: dialogPositiveInteger(result, "candidate_limit"),
    item_limit: dialogPositiveInteger(result, "item_limit"),
  };
}

async function relationshipActionDialog(
  existingAction: RelationshipReviewActionResponse | null,
): Promise<RelationshipReviewActionCreateRequest | RelationshipReviewActionUpdateRequest | null> {
  const dialogs = dialogApi();
  const result = await dialogs.promptDialog({
    eyebrow: "Relationship review",
    title: existingAction ? "Edit saved action" : "Create saved action",
    description: "Save a reusable duplicate or related-loop decision so repeated review work stays consistent.",
    confirmLabel: existingAction ? "Save action" : "Create action",
    fields: [
      { name: "name", label: "Action name", value: existingAction?.name || "", required: true, maxLength: 120, autocomplete: "off" },
      { name: "action_type", label: "Action", type: "select", value: existingAction?.action_type || "confirm", options: [{ value: "confirm", label: "Confirm" }, { value: "dismiss", label: "Dismiss" }] },
      { name: "relationship_type", label: "Relationship target", type: "select", value: existingAction?.relationship_type || "suggested", options: [{ value: "suggested", label: "Use queued candidate type" }, { value: "duplicate", label: "Duplicate only" }, { value: "related", label: "Related only" }] },
      { name: "description", label: "Description", type: "textarea", rows: 3, value: existingAction?.description || "" },
    ],
    validate: (values) => (!dialogValue(values, "name") ? "Enter an action name." : null),
  });

  if (!result) {
    return null;
  }

  return {
    name: dialogValue(result, "name"),
    action_type: dialogValue(result, "action_type") as RelationshipReviewActionCreateRequest["action_type"],
    relationship_type: (dialogValue(result, "relationship_type") || "suggested") as NonNullable<RelationshipReviewActionCreateRequest["relationship_type"]>,
    description: dialogOptionalValue(result, "description"),
  };
}

async function enrichmentSessionDialog(
  existingSession: EnrichmentReviewSessionResponse | null,
): Promise<EnrichmentReviewSessionCreateRequest | EnrichmentReviewSessionUpdateRequest | null> {
  const dialogs = dialogApi();
  const result = await dialogs.promptDialog({
    eyebrow: "Enrichment review",
    title: existingSession ? "Edit review session" : "Create review session",
    description: "Persist a filtered suggestion and clarification queue so you can work through follow-ups without losing your place.",
    confirmLabel: existingSession ? "Save session" : "Create session",
    fields: [
      { name: "name", label: "Session name", value: existingSession?.name || "", required: true, maxLength: 120, autocomplete: "off" },
      { name: "query", label: "DSL query", value: existingSession?.query || "status:open", required: true, maxLength: 500, autocomplete: "off" },
      { name: "pending_kind", label: "Pending work kind", type: "select", value: existingSession?.pending_kind || "all", options: [{ value: "all", label: "Suggestions and clarifications" }, { value: "suggestions", label: "Suggestions only" }, { value: "clarifications", label: "Clarifications only" }] },
      { name: "suggestion_limit", label: "Suggestions per loop", type: "number", value: String(existingSession?.suggestion_limit || 3), inputMode: "numeric" },
      { name: "clarification_limit", label: "Clarifications per loop", type: "number", value: String(existingSession?.clarification_limit || 3), inputMode: "numeric" },
      { name: "item_limit", label: "Loop limit", type: "number", value: String(existingSession?.item_limit || 25), inputMode: "numeric" },
    ],
    validate: (values) => {
      if (!dialogValue(values, "name")) {
        return "Enter a session name.";
      }
      if (!dialogValue(values, "query")) {
        return "Enter a DSL query.";
      }
      return validatePositiveInteger(dialogValue(values, "suggestion_limit"), "Suggestions per loop")
        || validatePositiveInteger(dialogValue(values, "clarification_limit"), "Clarifications per loop")
        || validatePositiveInteger(dialogValue(values, "item_limit"), "Loop limit");
    },
  });

  if (!result) {
    return null;
  }

  return {
    name: dialogValue(result, "name"),
    query: dialogValue(result, "query"),
    pending_kind: (dialogValue(result, "pending_kind") || "all") as NonNullable<EnrichmentReviewSessionCreateRequest["pending_kind"]>,
    suggestion_limit: dialogPositiveInteger(result, "suggestion_limit"),
    clarification_limit: dialogPositiveInteger(result, "clarification_limit"),
    item_limit: dialogPositiveInteger(result, "item_limit"),
  };
}

async function enrichmentActionDialog(
  existingAction: EnrichmentReviewActionResponse | null,
): Promise<EnrichmentReviewActionCreateRequest | EnrichmentReviewActionUpdateRequest | null> {
  const dialogs = dialogApi();
  const result = await dialogs.promptDialog({
    eyebrow: "Enrichment review",
    title: existingAction ? "Edit saved action" : "Create saved action",
    description: "Save a reusable suggestion follow-up action so repeated review work stays consistent.",
    confirmLabel: existingAction ? "Save action" : "Create action",
    fields: [
      { name: "name", label: "Action name", value: existingAction?.name || "", required: true, maxLength: 120, autocomplete: "off" },
      { name: "action_type", label: "Action", type: "select", value: existingAction?.action_type || "apply", options: [{ value: "apply", label: "Apply suggestion" }, { value: "reject", label: "Reject suggestion" }] },
      { name: "fields", label: "Apply fields (comma separated)", value: Array.isArray(existingAction?.fields) ? existingAction.fields.join(", ") : "", helpText: "Leave blank to use the default apply field set. Reject actions must leave this empty." },
      { name: "description", label: "Description", type: "textarea", rows: 3, value: existingAction?.description || "" },
    ],
    validate: (values) => {
      if (!dialogValue(values, "name")) {
        return "Enter an action name.";
      }
      if (dialogValue(values, "action_type") === "reject" && dialogValue(values, "fields")) {
        return "Reject actions cannot define fields.";
      }
      return null;
    },
  });

  if (!result) {
    return null;
  }

  const fieldsText = dialogValue(result, "fields");
  const fields = fieldsText
    ? fieldsText.split(",").map((value) => value.trim()).filter(Boolean)
    : null;

  return {
    name: dialogValue(result, "name"),
    action_type: dialogValue(result, "action_type") as EnrichmentReviewActionCreateRequest["action_type"],
    fields,
    description: dialogOptionalValue(result, "description"),
  };
}

async function handlePlanningCreate(): Promise<void> {
  const payload = await planningSessionDialog();
  if (!payload) {
    return;
  }
  const snapshot = await createPlanningSession(payload);
  state.planningSessionId = snapshot.session.id;
  requestWorkspaceRefresh();
  window.location.hash = toReviewHash("planning", snapshot.session.id);
}

async function handlePlanningDelete(): Promise<void> {
  const session = state.planningSnapshot?.session;
  if (!session) {
    return;
  }
  const confirmed = await dialogApi().confirmDialog({
    eyebrow: "Planning workflows",
    title: "Delete planning session",
    description: `Delete “${session.name}”? The saved plan and execution history will be removed.`,
    confirmLabel: "Delete session",
    confirmVariant: "danger",
  });
  if (!confirmed) {
    return;
  }
  await deletePlanningSession(session.id);
  requestWorkspaceRefresh();
  window.location.hash = toReviewHash("planning");
}

async function handlePlanningRefresh(): Promise<void> {
  const sessionId = state.planningSessionId;
  if (sessionId == null) {
    return;
  }
  state.planningSnapshot = await refreshPlanningSession(sessionId);
  requestWorkspaceRefresh();
  renderAll();
  setStatus(`Refreshed ${state.planningSnapshot.session.name}.`);
}

async function handlePlanningExecute(): Promise<void> {
  const sessionId = state.planningSessionId;
  if (sessionId == null) {
    return;
  }
  const payload = await executePlanningSession(sessionId);
  state.planningSnapshot = payload.snapshot;
  requestWorkspaceRefresh();
  renderAll();

  const planLocation = createLocation({
    state: "plan",
    reviewFocus: "planning",
    sessionId,
    workingSetId: currentWorkingSetId(),
  });
  const receiptCard = buildPlanningExecutionReceiptCard({
    snapshot: payload.snapshot,
    latestExecution: payload.execution,
    context: planningImpactHandoffContext(payload.snapshot.session.name),
    recovery: surfaceRecoveryForLocation(planLocation, `planning:${sessionId}`),
  });
  recordRecentShellAction(
    withReceiptOutcome(
      {
        kind: "planning",
        label: receiptCard.title,
        description: receiptCard.summary,
        location: planLocation,
        metadata: {
          source: "review-workspace",
          sessionId,
          checkpointIndex: payload.execution.checkpoint_index,
        },
      },
      receiptCard,
      planLocation,
    ),
  );

  const launchSurface = payload.execution.launch_surfaces?.[0] ?? null;
  setStatus(
    launchSurface
      ? `Executed ${payload.execution.checkpoint_title}. Next queue ready: ${launchSurface.label}.`
      : `Executed ${payload.execution.checkpoint_title}.`,
  );
}

async function handlePlanningMove(direction: "next" | "previous"): Promise<void> {
  const sessionId = state.planningSessionId;
  if (sessionId == null) {
    return;
  }
  state.planningSnapshot = await movePlanningSession(sessionId, direction);
  renderAll();
  setStatus(`Moved to checkpoint ${state.planningSnapshot.session.current_checkpoint_index + 1}.`);
}

async function handleRelationshipSessionCreate(): Promise<void> {
  const payload = await relationshipSessionDialog(null);
  if (!payload) {
    return;
  }
  const snapshot = await createRelationshipSession(payload as RelationshipReviewSessionCreateRequest);
  state.relationshipSessionId = snapshot.session.id;
  requestWorkspaceRefresh();
  window.location.hash = toReviewHash("relationship", snapshot.session.id);
}

async function handleRelationshipSessionEdit(): Promise<void> {
  const session = state.relationshipSnapshot?.session ?? null;
  if (!session) {
    return;
  }
  const payload = await relationshipSessionDialog(session);
  if (!payload) {
    return;
  }
  state.relationshipSnapshot = await updateRelationshipSession(session.id, payload as RelationshipReviewSessionUpdateRequest);
  requestWorkspaceRefresh();
  renderAll();
  setStatus(`Saved ${state.relationshipSnapshot.session.name}.`);
}

async function handleRelationshipSessionDelete(): Promise<void> {
  const session = state.relationshipSnapshot?.session;
  if (!session) {
    return;
  }
  const confirmed = await dialogApi().confirmDialog({
    eyebrow: "Relationship review",
    title: "Delete review session",
    description: `Delete “${session.name}”? The saved session and cursor will be removed.`,
    confirmLabel: "Delete session",
    confirmVariant: "danger",
  });
  if (!confirmed) {
    return;
  }
  await deleteRelationshipSession(session.id);
  requestWorkspaceRefresh();
  window.location.hash = toReviewHash("relationship");
}

async function handleRelationshipActionCreate(): Promise<void> {
  const payload = await relationshipActionDialog(null);
  if (!payload) {
    return;
  }
  const action = await createRelationshipAction(payload as RelationshipReviewActionCreateRequest);
  state.relationshipActionId = action.id;
  await loadMode("relationship", state.relationshipSessionId);
}

async function handleRelationshipActionEdit(): Promise<void> {
  const action = selectedRelationshipAction();
  if (!action) {
    return;
  }
  const payload = await relationshipActionDialog(action);
  if (!payload) {
    return;
  }
  const updated = await updateRelationshipAction(action.id, payload as RelationshipReviewActionUpdateRequest);
  state.relationshipActionId = updated.id;
  await loadMode("relationship", state.relationshipSessionId);
}

async function handleRelationshipActionDelete(): Promise<void> {
  const action = selectedRelationshipAction();
  if (!action) {
    return;
  }
  const confirmed = await dialogApi().confirmDialog({
    eyebrow: "Relationship review",
    title: "Delete saved action",
    description: `Delete “${action.name}”?`,
    confirmLabel: "Delete action",
    confirmVariant: "danger",
  });
  if (!confirmed) {
    return;
  }
  await deleteRelationshipAction(action.id);
  state.relationshipActionId = null;
  await loadMode("relationship", state.relationshipSessionId);
}

async function handleRelationshipMove(direction: "next" | "previous"): Promise<void> {
  const sessionId = state.relationshipSessionId;
  if (sessionId == null) {
    return;
  }
  state.relationshipSnapshot = await moveRelationshipSession(sessionId, direction);
  requestWorkspaceRefresh();
  renderAll();
  setStatus(`Moved to ${describeQueueCount(state.relationshipSnapshot.current_index, state.relationshipSnapshot.loop_count)}.`);
}

async function handleRelationshipSelectLoop(loopId: number): Promise<void> {
  const session = state.relationshipSnapshot?.session;
  if (!session) {
    return;
  }
  state.relationshipSnapshot = await updateRelationshipSession(session.id, { current_loop_id: loopId });
  renderAll();
  setStatus(`Focused ${loopTitle(state.relationshipSnapshot.current_item?.loop ?? { id: loopId, raw_text: "", title: null })}.`);
}

function findRelationshipCandidate(candidateId: number): RelationshipReviewCandidateResponse | null {
  const item = state.relationshipSnapshot?.current_item;
  if (!item) {
    return null;
  }
  return [...item.duplicate_candidates, ...item.related_candidates].find((candidate) => candidate.id === candidateId) ?? null;
}

function findEnrichmentSuggestion(
  suggestionId: number,
): EnrichmentReviewQueueItemResponse["pending_suggestions"][number] | null {
  return state.enrichmentSnapshot?.current_item?.pending_suggestions.find((suggestion) => suggestion.id === suggestionId) ?? null;
}

async function confirmRelationshipDuplicateIfNeeded(
  candidateId: number,
  relationshipType: RelationshipReviewSessionActionRequest["relationship_type"],
): Promise<boolean> {
  if (relationshipType !== "duplicate") {
    return true;
  }
  const candidate = findRelationshipCandidate(candidateId);
  return dialogApi().confirmDialog({
    eyebrow: "Relationship review",
    title: "Confirm duplicate relationship",
    description: `This records ${candidate ? `“${loopTitle(candidate)}”` : `loop #${candidateId}`} as a duplicate and is not reversible in-place. Continue only if both loops truly represent the same work.`,
    confirmLabel: "Confirm duplicate",
    confirmVariant: "danger",
  });
}

async function confirmEnrichmentApplyIfNeeded(suggestionId: number): Promise<boolean> {
  const suggestion = findEnrichmentSuggestion(suggestionId);
  const fields = enrichmentSuggestedFields(state.enrichmentSnapshot?.current_item ?? null).slice(0, 3);
  return dialogApi().confirmDialog({
    eyebrow: "Enrichment review",
    title: "Apply suggestion",
    description: fields.length
      ? `Applying ${suggestion ? `suggestion #${suggestion.id}` : `suggestion #${suggestionId}`} will mutate ${fields.join(", ")} immediately and may supersede current loop context. Continue?`
      : `Applying ${suggestion ? `suggestion #${suggestion.id}` : `suggestion #${suggestionId}`} mutates loop fields immediately and may supersede current loop context. Continue?`,
    confirmLabel: "Apply suggestion",
    confirmVariant: "danger",
  });
}

async function handleRelationshipDecision(button: HTMLButtonElement, actionType: "confirm" | "dismiss"): Promise<void> {
  const sessionId = state.relationshipSessionId;
  if (sessionId == null) {
    return;
  }
  const loopId = parseOptionalInteger(button.dataset["loopId"]);
  const candidateId = parseOptionalInteger(button.dataset["candidateId"]);
  const candidateType = button.dataset["candidateType"] as RelationshipReviewSessionActionRequest["candidate_relationship_type"] | undefined;
  if (loopId == null || candidateId == null || !candidateType) {
    return;
  }
  const requestedRelationshipType = (button.dataset["relationshipType"] as RelationshipReviewSessionActionRequest["relationship_type"] | undefined) ?? candidateType;
  const relationshipType: "duplicate" | "related" = requestedRelationshipType === "suggested"
    ? candidateType
    : requestedRelationshipType;
  if (actionType === "confirm" && !(await confirmRelationshipDuplicateIfNeeded(candidateId, relationshipType))) {
    return;
  }
  const response = await runRelationshipSessionAction(sessionId, {
    loop_id: loopId,
    candidate_loop_id: candidateId,
    candidate_relationship_type: candidateType,
    action_type: actionType,
    relationship_type: relationshipType,
  });
  state.relationshipSnapshot = response.snapshot;
  requestWorkspaceRefresh();
  renderAll();

  recordBackendReviewFollowThrough({
    followThrough: response.follow_through,
    metadata: {
      source: "review-workspace",
      sessionId,
      loopId,
      candidateId,
      actionType,
      relationshipType,
    },
  });
  setStatus(`Recorded ${actionType} for loop #${loopId}.`);
}

async function handleRelationshipPreset(button: HTMLButtonElement): Promise<void> {
  const sessionId = state.relationshipSessionId;
  const actionId = state.relationshipActionId;
  const selectedAction = selectedRelationshipAction();
  if (sessionId == null || actionId == null || !selectedAction) {
    return;
  }
  const loopId = parseOptionalInteger(button.dataset["loopId"]);
  const candidateId = parseOptionalInteger(button.dataset["candidateId"]);
  const candidateType = button.dataset["candidateType"] as RelationshipReviewSessionActionRequest["candidate_relationship_type"] | undefined;
  if (loopId == null || candidateId == null || !candidateType) {
    return;
  }
  const resolvedRelationshipType: "duplicate" | "related" = selectedAction.relationship_type === "suggested"
    ? candidateType
    : selectedAction.relationship_type;
  if (selectedAction.action_type === "confirm" && !(await confirmRelationshipDuplicateIfNeeded(candidateId, resolvedRelationshipType))) {
    return;
  }
  const response = await runRelationshipSessionAction(sessionId, {
    loop_id: loopId,
    candidate_loop_id: candidateId,
    candidate_relationship_type: candidateType,
    action_preset_id: actionId,
  });
  state.relationshipSnapshot = response.snapshot;
  requestWorkspaceRefresh();
  renderAll();

  recordBackendReviewFollowThrough({
    followThrough: response.follow_through,
    metadata: {
      source: "review-workspace",
      sessionId,
      loopId,
      candidateId,
      actionPresetId: actionId,
      actionType: selectedAction.action_type,
      relationshipType: resolvedRelationshipType,
    },
  });
  setStatus(`Applied saved relationship action.`);
}

async function handleEnrichmentSessionCreate(): Promise<void> {
  const payload = await enrichmentSessionDialog(null);
  if (!payload) {
    return;
  }
  const snapshot = await createEnrichmentSession(payload as EnrichmentReviewSessionCreateRequest);
  state.enrichmentSessionId = snapshot.session.id;
  requestWorkspaceRefresh();
  window.location.hash = toReviewHash("enrichment", snapshot.session.id);
}

async function handleEnrichmentSessionEdit(): Promise<void> {
  const session = state.enrichmentSnapshot?.session ?? null;
  if (!session) {
    return;
  }
  const payload = await enrichmentSessionDialog(session);
  if (!payload) {
    return;
  }
  state.enrichmentSnapshot = await updateEnrichmentSession(session.id, payload as EnrichmentReviewSessionUpdateRequest);
  requestWorkspaceRefresh();
  renderAll();
  setStatus(`Saved ${state.enrichmentSnapshot.session.name}.`);
}

async function handleEnrichmentSessionDelete(): Promise<void> {
  const session = state.enrichmentSnapshot?.session;
  if (!session) {
    return;
  }
  const confirmed = await dialogApi().confirmDialog({
    eyebrow: "Enrichment review",
    title: "Delete review session",
    description: `Delete “${session.name}”? The saved session and cursor will be removed.`,
    confirmLabel: "Delete session",
    confirmVariant: "danger",
  });
  if (!confirmed) {
    return;
  }
  await deleteEnrichmentSession(session.id);
  requestWorkspaceRefresh();
  window.location.hash = toReviewHash("enrichment");
}

async function handleEnrichmentActionCreate(): Promise<void> {
  const payload = await enrichmentActionDialog(null);
  if (!payload) {
    return;
  }
  const action = await createEnrichmentAction(payload as EnrichmentReviewActionCreateRequest);
  state.enrichmentActionId = action.id;
  await loadMode("enrichment", state.enrichmentSessionId);
}

async function handleEnrichmentActionEdit(): Promise<void> {
  const action = selectedEnrichmentAction();
  if (!action) {
    return;
  }
  const payload = await enrichmentActionDialog(action);
  if (!payload) {
    return;
  }
  const updated = await updateEnrichmentAction(action.id, payload as EnrichmentReviewActionUpdateRequest);
  state.enrichmentActionId = updated.id;
  await loadMode("enrichment", state.enrichmentSessionId);
}

async function handleEnrichmentActionDelete(): Promise<void> {
  const action = selectedEnrichmentAction();
  if (!action) {
    return;
  }
  const confirmed = await dialogApi().confirmDialog({
    eyebrow: "Enrichment review",
    title: "Delete saved action",
    description: `Delete “${action.name}”?`,
    confirmLabel: "Delete action",
    confirmVariant: "danger",
  });
  if (!confirmed) {
    return;
  }
  await deleteEnrichmentAction(action.id);
  state.enrichmentActionId = null;
  await loadMode("enrichment", state.enrichmentSessionId);
}

async function handleEnrichmentMove(direction: "next" | "previous"): Promise<void> {
  const sessionId = state.enrichmentSessionId;
  if (sessionId == null) {
    return;
  }
  state.enrichmentSnapshot = await moveEnrichmentSession(sessionId, direction);
  requestWorkspaceRefresh();
  renderAll();
  setStatus(`Moved to ${describeQueueCount(state.enrichmentSnapshot.current_index, state.enrichmentSnapshot.loop_count)}.`);
}

async function handleEnrichmentSelectLoop(loopId: number): Promise<void> {
  const session = state.enrichmentSnapshot?.session;
  if (!session) {
    return;
  }
  state.enrichmentSnapshot = await updateEnrichmentSession(session.id, { current_loop_id: loopId });
  renderAll();
  setStatus(`Focused ${loopTitle(state.enrichmentSnapshot.current_item?.loop ?? { id: loopId, raw_text: "", title: null })}.`);
}

async function handleEnrichmentDecision(suggestionId: number, actionType: "apply" | "reject"): Promise<void> {
  const sessionId = state.enrichmentSessionId;
  if (sessionId == null) {
    return;
  }
  if (actionType === "apply" && !(await confirmEnrichmentApplyIfNeeded(suggestionId))) {
    return;
  }
  const response = await runEnrichmentSessionAction(sessionId, {
    suggestion_id: suggestionId,
    action_type: actionType,
  });
  state.enrichmentSnapshot = response.snapshot;
  requestWorkspaceRefresh();
  renderAll();

  recordBackendReviewFollowThrough({
    followThrough: response.follow_through,
    metadata: {
      source: "review-workspace",
      sessionId,
      suggestionId,
      actionType,
    },
  });
  setStatus(`${actionType === "apply" ? "Applied" : "Rejected"} suggestion #${suggestionId}.`);
}

async function handleEnrichmentPreset(suggestionId: number): Promise<void> {
  const sessionId = state.enrichmentSessionId;
  const actionId = state.enrichmentActionId;
  const action = selectedEnrichmentAction();
  if (sessionId == null || actionId == null || !action) {
    return;
  }
  if (action.action_type === "apply" && !(await confirmEnrichmentApplyIfNeeded(suggestionId))) {
    return;
  }
  const response = await runEnrichmentSessionAction(sessionId, {
    suggestion_id: suggestionId,
    action_preset_id: actionId,
  });
  state.enrichmentSnapshot = response.snapshot;
  requestWorkspaceRefresh();
  renderAll();

  recordBackendReviewFollowThrough({
    followThrough: response.follow_through,
    metadata: {
      source: "review-workspace",
      sessionId,
      suggestionId,
      actionPresetId: actionId,
      actionType: action.action_type,
    },
  });
  setStatus(`Applied saved enrichment action.`);
}

async function handleEnrichmentClarifications(form: HTMLFormElement): Promise<void> {
  const sessionId = state.enrichmentSessionId;
  const loopId = parseOptionalInteger(form.dataset["loopId"]);
  if (sessionId == null || loopId == null) {
    return;
  }
  const answers = Array.from(form.querySelectorAll<HTMLInputElement>("[data-clarification-id]"))
    .map((input) => {
      const clarificationId = parseOptionalInteger(input.dataset["clarificationId"]);
      const answer = input.value.trim();
      if (clarificationId == null || !answer) {
        return null;
      }
      return {
        clarification_id: clarificationId,
        answer,
      } satisfies ClarificationSubmitRequest;
    })
    .filter((item): item is ClarificationSubmitRequest => item != null);

  if (!answers.length) {
    setStatus("Enter at least one clarification answer.", true);
    return;
  }

  const response = await answerEnrichmentClarifications(sessionId, {
    loop_id: loopId,
    answers,
  });
  state.enrichmentSnapshot = response.snapshot;
  requestWorkspaceRefresh();
  renderAll();

  recordBackendReviewFollowThrough({
    followThrough: response.follow_through,
    metadata: {
      source: "review-workspace",
      sessionId,
      loopId,
      answerCount: answers.length,
      actionType: "clarify",
    },
  });
  setStatus(response.result.message ?? "Clarification answered.");
}

async function handleControlChange(event: Event): Promise<void> {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }

  if (target.id === "review-shell-planning-session-select") {
    const sessionId = parseOptionalInteger(target.value);
    window.location.hash = toReviewHash("planning", sessionId);
    return;
  }
  if (target.id === "review-shell-relationship-session-select") {
    const sessionId = parseOptionalInteger(target.value);
    window.location.hash = toReviewHash("relationship", sessionId);
    return;
  }
  if (target.id === "review-shell-relationship-action-select") {
    state.relationshipActionId = parseOptionalInteger(target.value);
    renderAll();
    return;
  }
  if (target.id === "review-shell-enrichment-session-select") {
    const sessionId = parseOptionalInteger(target.value);
    window.location.hash = toReviewHash("enrichment", sessionId);
    return;
  }
  if (target.id === "review-shell-enrichment-action-select") {
    state.enrichmentActionId = parseOptionalInteger(target.value);
    renderAll();
  }
}

async function handleControlClick(event: Event): Promise<void> {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const hashButton = target.closest<HTMLButtonElement>("[data-review-open-hash]");
  if (hashButton?.dataset["reviewOpenHash"]) {
    window.location.hash = hashButton.dataset["reviewOpenHash"];
    return;
  }

  const actionButton = target.closest<HTMLButtonElement>("[data-review-action]");
  if (!actionButton) {
    return;
  }

  const action = actionButton.dataset["reviewAction"];
  try {
    switch (action) {
      case "planning-create":
        await handlePlanningCreate();
        break;
      case "planning-delete":
        await handlePlanningDelete();
        break;
      case "planning-refresh":
        await handlePlanningRefresh();
        break;
      case "planning-execute":
        await handlePlanningExecute();
        break;
      case "planning-move-prev":
        await handlePlanningMove("previous");
        break;
      case "planning-move-next":
        await handlePlanningMove("next");
        break;
      case "relationship-session-create":
        await handleRelationshipSessionCreate();
        break;
      case "relationship-session-edit":
        await handleRelationshipSessionEdit();
        break;
      case "relationship-session-delete":
        await handleRelationshipSessionDelete();
        break;
      case "relationship-action-create":
        await handleRelationshipActionCreate();
        break;
      case "relationship-action-edit":
        await handleRelationshipActionEdit();
        break;
      case "relationship-action-delete":
        await handleRelationshipActionDelete();
        break;
      case "relationship-move-prev":
        await handleRelationshipMove("previous");
        break;
      case "relationship-move-next":
        await handleRelationshipMove("next");
        break;
      case "relationship-select-loop": {
        const loopId = parseOptionalInteger(actionButton.dataset["loopId"]);
        if (loopId != null) {
          await handleRelationshipSelectLoop(loopId);
        }
        break;
      }
      case "relationship-confirm":
      case "relationship-dismiss":
        await handleRelationshipDecision(actionButton, action === "relationship-confirm" ? "confirm" : "dismiss");
        break;
      case "relationship-use-preset":
        await handleRelationshipPreset(actionButton);
        break;
      case "relationship-merge": {
        const loopId = parseOptionalInteger(actionButton.dataset["loopId"]);
        const candidateId = parseOptionalInteger(actionButton.dataset["candidateId"]);
        if (loopId != null && candidateId != null) {
          await openMergeModal(loopId, candidateId);
        }
        break;
      }
      case "enrichment-session-create":
        await handleEnrichmentSessionCreate();
        break;
      case "enrichment-session-edit":
        await handleEnrichmentSessionEdit();
        break;
      case "enrichment-session-delete":
        await handleEnrichmentSessionDelete();
        break;
      case "enrichment-action-create":
        await handleEnrichmentActionCreate();
        break;
      case "enrichment-action-edit":
        await handleEnrichmentActionEdit();
        break;
      case "enrichment-action-delete":
        await handleEnrichmentActionDelete();
        break;
      case "enrichment-move-prev":
        await handleEnrichmentMove("previous");
        break;
      case "enrichment-move-next":
        await handleEnrichmentMove("next");
        break;
      case "enrichment-select-loop": {
        const loopId = parseOptionalInteger(actionButton.dataset["loopId"]);
        if (loopId != null) {
          await handleEnrichmentSelectLoop(loopId);
        }
        break;
      }
      case "enrichment-apply": {
        const suggestionId = parseOptionalInteger(actionButton.dataset["suggestionId"]);
        if (suggestionId != null) {
          await handleEnrichmentDecision(suggestionId, "apply");
        }
        break;
      }
      case "enrichment-reject": {
        const suggestionId = parseOptionalInteger(actionButton.dataset["suggestionId"]);
        if (suggestionId != null) {
          await handleEnrichmentDecision(suggestionId, "reject");
        }
        break;
      }
      case "enrichment-use-preset": {
        const suggestionId = parseOptionalInteger(actionButton.dataset["suggestionId"]);
        if (suggestionId != null) {
          await handleEnrichmentPreset(suggestionId);
        }
        break;
      }
      case "cohort-mode-daily":
        state.reviewMode = "daily";
        await loadMode("cohorts");
        break;
      case "cohort-mode-weekly":
        state.reviewMode = "weekly";
        await loadMode("cohorts");
        break;
      case "cohort-select": {
        const cohortKey = actionButton.dataset["cohortKey"] ?? null;
        state.selectedCohortKey = cohortKey;
        renderAll();
        break;
      }
      case "cohort-refresh":
        await loadMode("cohorts");
        break;
      case "cohort-open-top": {
        const topLoop = selectedCohort()?.items[0] ?? null;
        if (topLoop) {
          window.location.hash = toDoHash(topLoop.id);
        }
        break;
      }
      default: {
        const mode = actionButton.dataset["reviewShellMode"] as ReviewFocus | undefined;
        if (mode) {
          window.location.hash = toReviewHash(mode);
        }
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Review action failed";
    setStatus(message, true);
  }
}

function handleWorkspaceSubmit(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLFormElement)) {
    return;
  }
  const action = target.dataset["reviewAction"];
  if (action !== "enrichment-clarifications-submit") {
    return;
  }
  event.preventDefault();
  void handleEnrichmentClarifications(target);
}

function handleReviewFocusEvent(event: Event): void {
  if (!(event instanceof CustomEvent)) {
    return;
  }
  const detail = event.detail as ReviewFocusDetail | undefined;
  if (!detail?.focus) {
    return;
  }
  void navigateToFocus(detail);
}

function handleReviewWorkspaceRefresh(): void {
  void navigateToFocus(currentFocusDetail());
}

function initialize(): void {
  elements = buildElements();
  setupMergeHandlers();
  renderHeader();
  elements.shell.addEventListener("click", (event) => {
    void handleControlClick(event);
  });
  elements.shell.addEventListener("change", (event) => {
    void handleControlChange(event);
  });
  elements.shell.addEventListener("submit", handleWorkspaceSubmit);
  window.addEventListener(REVIEW_FOCUS_EVENT, handleReviewFocusEvent as EventListener);
  window.addEventListener(REVIEW_WORKSPACE_REFRESH_EVENT, handleReviewWorkspaceRefresh);

  const initial = parseHashToFocus(window.location.hash) ?? { focus: "relationship" as ReviewFocus, sessionId: null };
  void navigateToFocus(initial);
}

export function bootstrapReviewWorkspace(): void {
  if (typeof window === "undefined") {
    return;
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
    return;
  }
  initialize();
}
