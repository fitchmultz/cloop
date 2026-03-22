/**
 * continuity-follow-through.ts - Canonical ranked landed-outcome follow-through feed.
 *
 * Purpose:
 *   Build one shared ranked landed-outcome model for operator follow-through
 *   surfaces so home, receipt rail, and palette recents consume the same data.
 *
 * Responsibilities:
 *   - Read durable landed outcomes and outcome-aware resume anchors.
 *   - Prefer server-resolved fallback targets while keeping client-safe fallback logic.
 *   - Deduplicate anchors versus recent landed outcomes.
 *   - Normalize resume, undo, rerun, pin, and recovery affordances into one consistent card shape.
 *   - Group related outcomes into workflow threads for higher-signal continuity surfaces.
 *
 * Scope:
 *   - Frontend-only continuity ranking and card normalization.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts, shell.ts, and command-palette.ts.
 *
 * Invariants/Assumptions:
 *   - `RecentShellActionEntry.outcome` remains the canonical landed-outcome payload.
 *   - `outcome.resumeLocation` is preferred over launch location.
 *   - Anchor-only items are fallback continuity, not stronger than recent receipts.
 *   - When the backend already resolved a degraded target, the frontend preserves that explanation.
 */

import type {
  ContinuityLastSeenMarker,
  ContinuityRankingSignals,
  ContinuityRecoveryPlan,
  ContinuityResolvedStatus,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardPinAction,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  ResolvedContinuityTarget,
  ResumeAnchorState,
  ResumeAnchorTarget,
  ShellLocationContract,
  WorkingSetSessionMetadata,
  WorkflowThreadRef,
} from "./contracts-ui";
import {
  readContinuityLastSeenMarkers,
  readRecentShellActions,
  readResumeAnchors,
} from "./continuity-intelligence";
import {
  continuityLocationIdentity,
  recentShellActionDedupKey,
  resolveContinuityEntry,
} from "./continuity-outcomes";
import { scoreRankingSignals, totalRankingScore } from "./continuity-drift";
import {
  applyContinuityRecovery,
  buildContinuityRecoveryPlan,
} from "./continuity-recovery";
import { formatRelativeTime } from "./shell-core";
import { createLocation } from "./shell-routing";

export interface ContinuityAvailability {
  planningSessionIds: ReadonlySet<number>;
  relationshipSessionIds: ReadonlySet<number>;
  enrichmentSessionIds: ReadonlySet<number>;
  workingSets: ReadonlyMap<number, WorkingSetSessionMetadata>;
}

export interface RankedLandedOutcome {
  id: string;
  source: "receipt" | "recent" | "anchor";
  rank: number;
  rankingSignals: ContinuityRankingSignals;
  persistedOutcomeId: number | null;
  occurredAt: string;
  requestedResumeLocation: ShellLocationContract | null;
  resumeLocation: ShellLocationContract;
  resolvedStatus: ContinuityResolvedStatus;
  displayTitle: string;
  displaySummary: string;
  workingSetId: number | null;
  workingSetName: string | null;
  degraded: boolean;
  degradedLabel: string | null;
  recovery: ContinuityRecoveryPlan | null;
  card: OperatorActionCard;
  undoAction: OperatorActionCardUndoAction | null;
  rerunAction: OperatorActionCardRerunAction | null;
  workflowThread: WorkflowThreadRef | null;
}

export interface RankedWorkflowThread {
  id: string;
  thread: WorkflowThreadRef;
  representative: RankedLandedOutcome;
  outcomes: RankedLandedOutcome[];
  outcomeCount: number;
  rank: number;
}

export interface ReadRankedLandedOutcomesInput {
  availability: ContinuityAvailability;
  activeWorkingSetId?: number | null;
  recentActions?: readonly RecentShellActionEntry[];
  resumeAnchors?: ResumeAnchorState;
  lastSeenMarkers?: readonly ContinuityLastSeenMarker[];
  now?: number;
}

export interface BuildContinuityAvailabilityInput {
  planningSessionIds?: readonly number[];
  relationshipSessionIds?: readonly number[];
  enrichmentSessionIds?: readonly number[];
  workingSets?: readonly WorkingSetSessionMetadata[];
}

interface FollowThroughLocationResolution {
  requestedLocation: ShellLocationContract | null;
  location: ShellLocationContract;
  status: ContinuityResolvedStatus;
  degraded: boolean;
  degradedLabel: string | null;
  resolvedTarget: ResolvedContinuityTarget;
}

function safeTimestamp(value: string): number {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function workingSetMetadata(
  availability: ContinuityAvailability,
  workingSetId: number | null | undefined,
): WorkingSetSessionMetadata | null {
  if (workingSetId == null) {
    return null;
  }
  return availability.workingSets.get(workingSetId) ?? null;
}

function workingSetName(
  availability: ContinuityAvailability,
  workingSetId: number | null | undefined,
): string | null {
  const metadata = workingSetMetadata(availability, workingSetId);
  if (metadata) {
    return metadata.workingSetName;
  }
  return workingSetId != null ? `Working set #${workingSetId}` : null;
}

function cloneLocation(location: ShellLocationContract): ShellLocationContract {
  return { ...location };
}

export function buildContinuityAvailability(input: BuildContinuityAvailabilityInput): ContinuityAvailability {
  return {
    planningSessionIds: new Set(input.planningSessionIds ?? []),
    relationshipSessionIds: new Set(input.relationshipSessionIds ?? []),
    enrichmentSessionIds: new Set(input.enrichmentSessionIds ?? []),
    workingSets: new Map((input.workingSets ?? []).map((metadata) => [metadata.workingSetId, metadata])),
  };
}

function locationExists(location: ShellLocationContract, availability: ContinuityAvailability): boolean {
  if (location.state === "working_set") {
    return location.workingSetId != null && availability.workingSets.has(location.workingSetId);
  }
  if (location.state === "plan" && location.sessionId != null) {
    return availability.planningSessionIds.size === 0 || availability.planningSessionIds.has(location.sessionId);
  }
  if (location.state === "decide" && location.reviewFocus === "relationship" && location.sessionId != null) {
    return availability.relationshipSessionIds.size === 0 || availability.relationshipSessionIds.has(location.sessionId);
  }
  if (location.state === "decide" && location.reviewFocus === "enrichment" && location.sessionId != null) {
    return availability.enrichmentSessionIds.size === 0 || availability.enrichmentSessionIds.has(location.sessionId);
  }
  return true;
}

export function fallbackFollowThroughLocation(
  location: ShellLocationContract | null,
  availability: ContinuityAvailability,
): FollowThroughLocationResolution {
  if (!location) {
    const resolvedTarget: ResolvedContinuityTarget = {
      requestedLocation: null,
      resolvedLocation: createLocation({ state: "operator" }),
      status: "home_fallback",
      message: "Original outcome is no longer available, so this follow-through falls back to home.",
      successor: null,
    };
    return {
      requestedLocation: resolvedTarget.requestedLocation,
      location: resolvedTarget.resolvedLocation,
      status: resolvedTarget.status,
      degraded: true,
      degradedLabel: resolvedTarget.message,
      resolvedTarget,
    };
  }

  if (location.workingSetId != null && !availability.workingSets.has(location.workingSetId)) {
    if (location.state === "working_set") {
      const resolvedTarget: ResolvedContinuityTarget = {
        requestedLocation: location,
        resolvedLocation: createLocation({ state: "operator" }),
        status: "home_fallback",
        message: "Working-set session is no longer available, so this follow-through falls back to home.",
        successor: null,
      };
      return {
        requestedLocation: resolvedTarget.requestedLocation,
        location: resolvedTarget.resolvedLocation,
        status: resolvedTarget.status,
        degraded: true,
        degradedLabel: resolvedTarget.message,
        resolvedTarget,
      };
    }
    const unscopedLocation = createLocation({ ...location, workingSetId: null });
    if (locationExists(unscopedLocation, availability)) {
      const resolvedTarget: ResolvedContinuityTarget = {
        requestedLocation: location,
        resolvedLocation: unscopedLocation,
        status: "working_set_scope_removed",
        message: "Working-set scope was removed, so this follow-through falls back to the durable session or object.",
        successor: null,
      };
      return {
        requestedLocation: resolvedTarget.requestedLocation,
        location: resolvedTarget.resolvedLocation,
        status: resolvedTarget.status,
        degraded: true,
        degradedLabel: resolvedTarget.message,
        resolvedTarget,
      };
    }
  }

  if (locationExists(location, availability)) {
    const resolvedTarget: ResolvedContinuityTarget = {
      requestedLocation: location,
      resolvedLocation: cloneLocation(location),
      status: "ok",
      message: null,
      successor: null,
    };
    return {
      requestedLocation: resolvedTarget.requestedLocation,
      location: resolvedTarget.resolvedLocation,
      status: resolvedTarget.status,
      degraded: false,
      degradedLabel: null,
      resolvedTarget,
    };
  }

  const resolvedTarget: ResolvedContinuityTarget = {
    requestedLocation: location,
    resolvedLocation: createLocation({ state: "operator" }),
    status: "home_fallback",
    message: "Original outcome is no longer available, so this follow-through falls back to home.",
    successor: null,
  };
  return {
    requestedLocation: resolvedTarget.requestedLocation,
    location: resolvedTarget.resolvedLocation,
    status: resolvedTarget.status,
    degraded: true,
    degradedLabel: resolvedTarget.message,
    resolvedTarget,
  };
}

function resolvedFollowThroughLocation(
  entry: RecentShellActionEntry,
  availability: ContinuityAvailability,
): FollowThroughLocationResolution {
  const resolved = entry.outcome?.resolvedResume ?? null;
  if (resolved) {
    return {
      requestedLocation: resolved.requestedLocation ?? resolveContinuityEntry(entry).resumeLocation,
      location: resolved.resolvedLocation,
      status: resolved.status,
      degraded: resolved.status !== "ok",
      degradedLabel: resolved.status !== "ok" ? resolved.message : null,
      resolvedTarget: resolved,
    };
  }
  return fallbackFollowThroughLocation(resolveContinuityEntry(entry).resumeLocation, availability);
}

function resolvedAnchorLocation(
  anchor: ResumeAnchorTarget,
  availability: ContinuityAvailability,
): FollowThroughLocationResolution {
  if (anchor.resolvedResume) {
    return {
      requestedLocation: anchor.resolvedResume.requestedLocation ?? anchor.resumeLocation ?? anchor.launchLocation,
      location: anchor.resolvedResume.resolvedLocation,
      status: anchor.resolvedResume.status,
      degraded: anchor.resolvedResume.status !== "ok",
      degradedLabel: anchor.resolvedResume.status !== "ok" ? anchor.resolvedResume.message : null,
      resolvedTarget: anchor.resolvedResume,
    };
  }
  return fallbackFollowThroughLocation(anchor.resumeLocation ?? anchor.launchLocation, availability);
}

function buildResumeAction(location: ShellLocationContract, description: string): OperatorActionCardAction {
  return {
    type: "open",
    label: "Resume outcome",
    variant: "primary",
    description,
    location,
  };
}

function buildPinAction(
  location: ShellLocationContract,
  title: string,
  description: string,
  pinLabel: string,
): OperatorActionCardAction {
  return {
    type: "pin",
    label: "Pin outcome",
    variant: "secondary",
    description,
    location,
    pinLabel,
  };
}

function preferredPinLabel(card: OperatorActionCard): string {
  const pinAction = card.actions.find((action): action is OperatorActionCardPinAction => action.type === "pin") ?? null;
  return pinAction?.pinLabel ?? `Outcome · ${card.title}`;
}

function normalizeOutcomeCard(
  base: OperatorActionCard,
  resumeLocation: ShellLocationContract,
  summary: string,
  degradedLabel: string | null,
  undoAction: OperatorActionCardUndoAction | null,
  rerunAction: OperatorActionCardRerunAction | null,
  workingSet: WorkingSetSessionMetadata | null,
  recovery: ContinuityRecoveryPlan | null,
): OperatorActionCard {
  const carryForward = base.actions.filter((action) => {
    return action.type !== "open" && action.type !== "pin" && action.type !== "undo" && action.type !== "rerun";
  });
  const actions: OperatorActionCardAction[] = [buildResumeAction(resumeLocation, degradedLabel ?? summary)];

  if (rerunAction) {
    actions.push({
      ...rerunAction,
      variant: "secondary",
    });
  }

  if (undoAction) {
    actions.push({
      ...undoAction,
      variant: "secondary",
    });
  }

  actions.push(buildPinAction(resumeLocation, base.title, degradedLabel ?? summary, preferredPinLabel(base)));
  actions.push(...carryForward);

  const normalizedCard: OperatorActionCard = {
    ...base,
    handoff: base.handoff
      ? {
          ...base.handoff,
          workingSet: base.handoff.workingSet ?? workingSet,
        }
      : base.handoff,
    actionContextLabel: actions.length ? "Continue from here" : (base.actionContextLabel ?? null),
    actionWarning: degradedLabel ?? base.actionWarning ?? null,
    recovery: null,
    actions,
  };

  return applyContinuityRecovery(normalizedCard, recovery);
}

function anchorLabel(anchor: ResumeAnchorTarget): string {
  if (anchor.kind === "planning") {
    return `Planning session #${anchor.sessionId}`;
  }
  return `${anchor.reviewFocus} queue #${anchor.sessionId}`;
}

function anchorEyebrow(anchor: ResumeAnchorTarget): string {
  if (anchor.kind === "planning") {
    return "Resume plan";
  }
  return `Resume ${anchor.reviewFocus}`;
}

function anchorBreadcrumb(anchor: ResumeAnchorTarget): string {
  if (anchor.kind === "planning") {
    return "Plan";
  }
  return "Decide";
}

function anchorWorkflowThread(anchor: ResumeAnchorTarget): WorkflowThreadRef | null {
  if (!anchor.workflowThreadId) {
    return null;
  }
  return {
    id: anchor.workflowThreadId,
    kind: anchor.kind === "planning" ? "planning_checkpoint" : "review_session",
    title: anchor.outcomeTitle ?? anchorLabel(anchor),
    summary: anchor.outcomeSummary ?? null,
    parentOutcomeId: null,
  };
}

function buildAnchorCard(
  anchor: ResumeAnchorTarget,
  resumeLocation: ShellLocationContract,
  degradedLabel: string | null,
  workingSet: WorkingSetSessionMetadata | null,
): OperatorActionCard {
  const title = anchor.outcomeTitle ?? anchorLabel(anchor);
  const summary = anchor.outcomeSummary ?? "Resume the most recent landed workflow state from durable continuity.";
  const preview = [
    { label: "Last visited", value: formatRelativeTime(anchor.visitedAtUtc) },
    ...(workingSet ? [{ label: "Working set", value: workingSet.workingSetName }] : []),
  ];

  return {
    id: `follow-through-anchor-${anchor.kind}-${anchor.reviewFocus}-${anchor.sessionId}`,
    kind: "handoff",
    tone: "attention",
    eyebrow: anchorEyebrow(anchor),
    title,
    summary,
    rationale:
      "Outcome-aware resume anchors preserve the best durable handoff when there is no newer landed receipt to supersede it.",
    preview,
    trust: {
      generationLabel: "Durable continuity anchor",
      generationTone: "attention",
      contextSources: ["Backend-backed outcome continuity anchors"],
      assumptions: ["Resume anchors stay durable across browser sessions and devices."],
      confidenceLabel: "Deterministic resume shortcut",
      confidenceTone: "progress",
      freshnessLabel: `Visited ${formatRelativeTime(anchor.visitedAtUtc)}`,
      freshnessTone: "neutral",
      rollbackLabel: "Opening an anchor restores context only; later mutations remain explicit.",
      rollbackTone: "neutral",
      impactSummary: summary,
      impactTone: "neutral",
    },
    handoff: {
      changeSummary: degradedLabel ?? "Resume the landed workflow state directly.",
      createdResources: [title],
      nextStep: "Reopen the saved workflow context and continue from the landed state.",
      breadcrumbs: ["Home", "Since last visit", anchorBreadcrumb(anchor)],
      workingSet,
    },
    actionContextLabel: "Continue from here",
    actionWarning: degradedLabel,
    actions: [
      buildResumeAction(resumeLocation, degradedLabel ?? summary),
      buildPinAction(resumeLocation, title, degradedLabel ?? summary, `Outcome · ${title}`),
    ],
  };
}

function workflowThreadMarker(
  markers: readonly ContinuityLastSeenMarker[],
  workflowThreadId: string | null,
): ContinuityLastSeenMarker | null {
  if (!workflowThreadId) {
    return null;
  }
  return markers.find((marker) => marker.entityKind === "workflow_thread" && marker.entityKey === workflowThreadId) ?? null;
}

function outcomeFamily(
  workflowThread: WorkflowThreadRef | null,
  resumeLocation: ShellLocationContract,
): "planning" | "review" | null {
  if (workflowThread?.kind === "planning_checkpoint" || resumeLocation.state === "plan") {
    return "planning";
  }
  if (
    workflowThread?.kind === "review_session"
    || (resumeLocation.state === "decide"
      && (resumeLocation.reviewFocus === "relationship" || resumeLocation.reviewFocus === "enrichment"))
  ) {
    return "review";
  }
  return null;
}

function supersedesDurableAnchor(input: {
  source: RankedLandedOutcome["source"];
  workflowThread: WorkflowThreadRef | null;
  resumeLocation: ShellLocationContract;
  occurredAt: string;
  resumeAnchors: ResumeAnchorState;
}): boolean {
  if (input.source === "anchor") {
    return false;
  }

  const family = outcomeFamily(input.workflowThread, input.resumeLocation);
  const anchor = family === "planning"
    ? input.resumeAnchors.planning
    : family === "review"
      ? input.resumeAnchors.review
      : null;
  if (!anchor) {
    return false;
  }

  if (safeTimestamp(input.occurredAt) < safeTimestamp(anchor.visitedAtUtc)) {
    return false;
  }

  if (anchor.workflowThreadId && input.workflowThread?.id) {
    return anchor.workflowThreadId !== input.workflowThread.id;
  }

  return continuityLocationIdentity(anchor.resumeLocation ?? anchor.launchLocation)
    !== continuityLocationIdentity(input.resumeLocation);
}

function scoreOutcome(input: {
  source: RankedLandedOutcome["source"];
  occurredAt: string;
  activeWorkingSetId: number | null;
  workingSetId: number | null;
  degraded: boolean;
  undoAction: OperatorActionCardUndoAction | null;
  rerunAction: OperatorActionCardRerunAction | null;
  workflowThread: WorkflowThreadRef | null;
  resumeLocation: ShellLocationContract;
  resumeAnchors: ResumeAnchorState;
  lastSeenMarkers: readonly ContinuityLastSeenMarker[];
  persistedOutcomeId: number | null;
  now: number;
}): ContinuityRankingSignals {
  const ageMinutes = Math.max(0, input.now - safeTimestamp(input.occurredAt)) / 60_000;
  const threadMarker = workflowThreadMarker(input.lastSeenMarkers, input.workflowThread?.id ?? null);
  const lastSeenOutcomeId = Number(
    (threadMarker?.observedState as { latestOutcomeId?: number } | undefined)?.latestOutcomeId ?? 0,
  );

  let severity: ContinuityRankingSignals["driftSeverity"] = "none";
  if (input.degraded) {
    severity = "gone";
  } else if (supersedesDurableAnchor(input)) {
    severity = "replaced";
  } else if (!threadMarker) {
    severity = input.source === "anchor" ? "minor" : "moderate";
  } else if (input.persistedOutcomeId != null && input.persistedOutcomeId > lastSeenOutcomeId) {
    severity = input.persistedOutcomeId - lastSeenOutcomeId >= 3 ? "major" : "moderate";
  }

  return scoreRankingSignals({
    severity,
    workingSetRelevant: input.activeWorkingSetId != null && input.workingSetId === input.activeWorkingSetId,
    downstreamReady: !input.degraded,
    degraded: input.degraded,
    ageMinutes,
  });
}

export function findRecoveryPlanForLocation(
  outcomes: readonly RankedLandedOutcome[],
  input: {
    location: ShellLocationContract | null;
    workflowThreadId?: string | null;
  },
): ContinuityRecoveryPlan | null {
  const targetIdentity = continuityLocationIdentity(input.location);

  return outcomes.find((item) => {
    if (!item.recovery) {
      return false;
    }
    return (
      (input.workflowThreadId != null && item.workflowThread?.id === input.workflowThreadId)
      || continuityLocationIdentity(item.requestedResumeLocation) === targetIdentity
      || continuityLocationIdentity(item.resumeLocation) === targetIdentity
    );
  })?.recovery ?? null;
}

function buildRecentOutcome(
  entry: RecentShellActionEntry,
  availability: ContinuityAvailability,
  activeWorkingSetId: number | null,
  resumeAnchors: ResumeAnchorState,
  lastSeenMarkers: readonly ContinuityLastSeenMarker[],
  now: number,
): RankedLandedOutcome | null {
  if (!entry.outcome?.card) {
    return null;
  }

  const resolved = resolveContinuityEntry(entry);
  const resolvedTarget = resolvedFollowThroughLocation(entry, availability);
  const workingSet = resolved.workingSet ?? workingSetMetadata(availability, resolved.workingSetId);
  const undoAction = entry.outcome.undoAction ?? null;
  const rerunAction = entry.outcome.card.actions.find(
    (action): action is OperatorActionCardRerunAction => action.type === "rerun",
  ) ?? null;
  const source: RankedLandedOutcome["source"] = entry.outcome.card.kind === "receipt" ? "receipt" : "recent";
  const workflowThread = entry.outcome.workflowThread ?? null;
  const rankingSignals = scoreOutcome({
    source,
    occurredAt: entry.occurredAt,
    activeWorkingSetId,
    workingSetId: resolved.workingSetId,
    degraded: resolvedTarget.degraded,
    undoAction,
    rerunAction,
    workflowThread,
    resumeLocation: resolvedTarget.location,
    resumeAnchors,
    lastSeenMarkers,
    persistedOutcomeId: entry.persistence?.persistedOutcomeId ?? null,
    now,
  });
  const recovery = buildContinuityRecoveryPlan({
    displayTitle: resolved.displayTitle,
    resolvedTarget: resolvedTarget.resolvedTarget,
    workflowThread,
  });
  const card = normalizeOutcomeCard(
    entry.outcome.card,
    resolvedTarget.location,
    resolved.displaySummary,
    resolvedTarget.degraded ? resolvedTarget.degradedLabel : null,
    undoAction,
    rerunAction,
    workingSet,
    recovery,
  );

  return {
    id: `${source}-${recentShellActionDedupKey(entry)}`,
    source,
    rank: totalRankingScore(rankingSignals, source),
    rankingSignals,
    persistedOutcomeId: entry.persistence?.persistedOutcomeId ?? null,
    occurredAt: entry.occurredAt,
    requestedResumeLocation: resolvedTarget.requestedLocation,
    resumeLocation: resolvedTarget.location,
    resolvedStatus: resolvedTarget.status,
    displayTitle: resolved.displayTitle,
    displaySummary: resolved.displaySummary,
    workingSetId: resolved.workingSetId,
    workingSetName: workingSet?.workingSetName ?? workingSetName(availability, resolved.workingSetId),
    degraded: resolvedTarget.degraded,
    degradedLabel: resolvedTarget.degraded ? resolvedTarget.degradedLabel : null,
    recovery,
    card,
    undoAction,
    rerunAction,
    workflowThread,
  };
}

function buildAnchorOutcome(
  anchor: ResumeAnchorTarget,
  availability: ContinuityAvailability,
  activeWorkingSetId: number | null,
  resumeAnchors: ResumeAnchorState,
  lastSeenMarkers: readonly ContinuityLastSeenMarker[],
  now: number,
): RankedLandedOutcome {
  const resolvedTarget = resolvedAnchorLocation(anchor, availability);
  const workingSet = workingSetMetadata(availability, anchor.workingSetId);
  const workflowThread = anchorWorkflowThread(anchor);
  const displayTitle = anchor.outcomeTitle ?? anchorLabel(anchor);
  const displaySummary = anchor.outcomeSummary ?? "Resume the last saved landed workflow state.";
  const recovery = buildContinuityRecoveryPlan({
    displayTitle,
    resolvedTarget: resolvedTarget.resolvedTarget,
    workflowThread,
  });
  const card = applyContinuityRecovery(
    buildAnchorCard(
      anchor,
      resolvedTarget.location,
      resolvedTarget.degraded ? resolvedTarget.degradedLabel : null,
      workingSet,
    ),
    recovery,
  );
  const rankingSignals = scoreOutcome({
    source: "anchor",
    occurredAt: anchor.visitedAtUtc,
    activeWorkingSetId,
    workingSetId: anchor.workingSetId,
    degraded: resolvedTarget.degraded,
    undoAction: null,
    rerunAction: null,
    workflowThread,
    resumeLocation: resolvedTarget.location,
    resumeAnchors,
    lastSeenMarkers,
    persistedOutcomeId: null,
    now,
  });

  return {
    id: `anchor-${anchor.kind}-${anchor.reviewFocus}-${anchor.sessionId}`,
    source: "anchor",
    rank: totalRankingScore(rankingSignals, "anchor"),
    rankingSignals,
    persistedOutcomeId: null,
    occurredAt: anchor.visitedAtUtc,
    requestedResumeLocation: resolvedTarget.requestedLocation,
    resumeLocation: resolvedTarget.location,
    resolvedStatus: resolvedTarget.status,
    displayTitle,
    displaySummary,
    workingSetId: anchor.workingSetId,
    workingSetName: workingSet?.workingSetName ?? workingSetName(availability, anchor.workingSetId),
    degraded: resolvedTarget.degraded,
    degradedLabel: resolvedTarget.degraded ? resolvedTarget.degradedLabel : null,
    recovery,
    card,
    undoAction: null,
    rerunAction: null,
    workflowThread,
  };
}

function dedupeRecentOutcomes(items: readonly RankedLandedOutcome[]): RankedLandedOutcome[] {
  const deduped = new Map<string, RankedLandedOutcome>();

  items.forEach((item) => {
    const key = [
      continuityLocationIdentity(item.resumeLocation),
      item.displayTitle.trim().toLowerCase(),
      item.displaySummary.trim().toLowerCase(),
    ].join("::");
    const existing = deduped.get(key) ?? null;
    if (!existing) {
      deduped.set(key, item);
      return;
    }
    if (item.rank > existing.rank || safeTimestamp(item.occurredAt) > safeTimestamp(existing.occurredAt)) {
      deduped.set(key, item);
    }
  });

  return [...deduped.values()];
}

export function readRankedLandedOutcomes(input: ReadRankedLandedOutcomesInput): RankedLandedOutcome[] {
  const recentActions = input.recentActions ?? readRecentShellActions();
  const resumeAnchors = input.resumeAnchors ?? readResumeAnchors();
  const activeWorkingSetId = input.activeWorkingSetId ?? null;
  const lastSeenMarkers = input.lastSeenMarkers ?? readContinuityLastSeenMarkers();
  const now = input.now ?? Date.now();

  const recent = dedupeRecentOutcomes(
    recentActions
      .map((entry) => buildRecentOutcome(entry, input.availability, activeWorkingSetId, resumeAnchors, lastSeenMarkers, now))
      .filter((item): item is RankedLandedOutcome => item !== null),
  );

  const recentLocationKeys = new Set(recent.map((item) => continuityLocationIdentity(item.resumeLocation)));
  const anchors = [resumeAnchors.planning, resumeAnchors.review]
    .filter((anchor): anchor is ResumeAnchorTarget => anchor != null)
    .map((anchor) => buildAnchorOutcome(anchor, input.availability, activeWorkingSetId, resumeAnchors, lastSeenMarkers, now))
    .filter((item) => !recentLocationKeys.has(continuityLocationIdentity(item.resumeLocation)));

  return [...recent, ...anchors].sort((left, right) => {
    if (right.rank !== left.rank) {
      return right.rank - left.rank;
    }
    return safeTimestamp(right.occurredAt) - safeTimestamp(left.occurredAt);
  });
}

export function groupRankedWorkflowThreads(
  outcomes: readonly RankedLandedOutcome[],
): RankedWorkflowThread[] {
  const buckets = new Map<string, RankedLandedOutcome[]>();

  outcomes.forEach((outcome) => {
    const key = outcome.workflowThread?.id ?? continuityLocationIdentity(outcome.resumeLocation);
    const existing = buckets.get(key) ?? [];
    existing.push(outcome);
    buckets.set(key, existing);
  });

  return [...buckets.entries()].map(([id, items]) => {
    const sortedItems = [...items].sort((left, right) => {
      if (right.rank !== left.rank) {
        return right.rank - left.rank;
      }
      return safeTimestamp(right.occurredAt) - safeTimestamp(left.occurredAt);
    });
    const representative = sortedItems[0]!;
    return {
      id,
      thread: representative.workflowThread ?? {
        id,
        kind: "ad_hoc",
        title: representative.displayTitle,
        summary: representative.displaySummary,
        parentOutcomeId: null,
      },
      representative,
      outcomes: sortedItems,
      outcomeCount: sortedItems.length,
      rank: representative.rank + Math.min(sortedItems.length, 4) * 8,
    } satisfies RankedWorkflowThread;
  }).sort((left, right) => {
    if (right.rank !== left.rank) {
      return right.rank - left.rank;
    }
    return safeTimestamp(right.representative.occurredAt) - safeTimestamp(left.representative.occurredAt);
  });
}
