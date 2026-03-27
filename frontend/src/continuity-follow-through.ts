/**
 * continuity-follow-through.ts - Shared continuity feed and durable reopen helpers.
 *
 * Purpose:
 *   Turn durable backend workflow summaries plus fresh local receipts into one shared
 *   frontend continuity feed so operator home, the receipt rail, and the command
 *   palette render the same ranked follow-through model.
 *
 * Responsibilities:
 *   - Read backend-authored workflow summaries from the durable continuity cache.
 *   - Merge fresh local receipt outcomes until durable summaries catch up.
 *   - Materialize continuity summaries into renderable operator cards.
 *   - Attach canonical resume, rerun, undo, pin, and recovery actions.
 *   - Resolve saved planning/review reopen targets through durable summaries only.
 *   - Expose shared recovery lookup for shell and non-shell surfaces.
 *   - Merge shell-only card chrome onto ranked summary cards without rewriting backend display.
 *
 * Scope:
 *   - Frontend rendering/model helpers for shared continuity summaries and durable reopen.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts, shell.ts, command-palette.ts, and
 *     continuity-surface-recovery.ts.
 *
 * Invariants/Assumptions:
 *   - Backend workflow summaries remain the canonical durable ranking, display,
 *     explanation, undo, and rerun source.
 *   - Fresh local receipt outcomes only bridge the feed until durable continuity sync lands.
 *   - Recovery plans continue to derive from backend-resolved targets and durable
 *     acknowledgement state.
 */

import type {
  ContinuityRecoveryPlan,
  ContinuityWorkflowSummary,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  ResolvedContinuityTarget,
  ShellLocationContract,
  WorkflowThreadRef,
} from "./contracts-ui";
import {
  readContinuityWorkflowSummaries,
  readRecentShellActions,
} from "./continuity-intelligence";
import {
  continuityLocationIdentity,
  resolveContinuityEntry,
} from "./continuity-outcomes";
import {
  scoreRankingSignals,
  totalRankingScore,
} from "./continuity-drift";
import {
  applyContinuityRecovery,
  buildContinuityRecoveryPlan,
} from "./continuity-recovery";

export interface RankedWorkflowSummary extends ContinuityWorkflowSummary {
  card: OperatorActionCard;
  recovery: ContinuityRecoveryPlan | null;
}

export interface ReadRankedWorkflowSummariesInput {
  summaries?: readonly ContinuityWorkflowSummary[];
}

export interface ReadMergedRankedWorkflowSummariesInput extends ReadRankedWorkflowSummariesInput {
  recentActions?: readonly RecentShellActionEntry[];
}

export interface DurableReopenResolution {
  resolvedLocation: ShellLocationContract;
  recovery: ContinuityRecoveryPlan | null;
  matched: boolean;
}

export type ContinuitySurfaceCardPatch = {
  id: string;
  kind?: OperatorActionCard["kind"];
  tone?: OperatorActionCard["tone"];
  eyebrow?: string;
  title?: string;
  summary?: string;
  rationale?: string;
  emphasis?: OperatorActionCard["emphasis"];
  preview?: OperatorActionCard["preview"];
  actions?: OperatorActionCardAction[];
  actionContextLabel?: string | null;
  actionWarning?: string | null;
  recovery?: ContinuityRecoveryPlan | null;
};

function stripUndefined(record: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([, v]) => v !== undefined));
}

/** Shell chrome on top of `summary.card` (backend display + recovery). */
export function continuitySurfaceCard(
  summary: RankedWorkflowSummary,
  patch: ContinuitySurfaceCardPatch,
): OperatorActionCard {
  const { id, ...optional } = patch;
  return {
    ...summary.card,
    id,
    ...stripUndefined(optional as Record<string, unknown>),
  } as OperatorActionCard;
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
): OperatorActionCardAction {
  return {
    type: "pin",
    label: "Pin outcome",
    variant: "secondary",
    description,
    location,
    pinLabel: `Outcome · ${title}`,
  };
}

function buildSummaryCard(
  summary: ContinuityWorkflowSummary,
  recovery: ContinuityRecoveryPlan | null,
): { card: OperatorActionCard; undoAction: OperatorActionCardUndoAction | null; rerunAction: OperatorActionCardRerunAction | null } {
  const undoAction = summary.undoAction ?? null;
  const rerunAction = summary.rerunAction ?? null;
  const displayCard = {
    ...summary.displayCard,
    kind: summary.displayCard.kind === "handoff" ? "context" : summary.displayCard.kind,
    eyebrow: summary.displayCard.kind === "handoff" ? "Workflow thread" : summary.displayCard.eyebrow,
  };
  const description = (summary.degraded ? summary.degradedLabel : null) ?? summary.displaySummary;
  const actions: OperatorActionCardAction[] = [
    buildResumeAction(summary.resolvedResume.resolvedLocation, description),
  ];

  if (rerunAction) {
    actions.push({ ...rerunAction, variant: "secondary" });
  }
  if (undoAction) {
    actions.push({ ...undoAction, variant: "secondary" });
  }
  actions.push(
    buildPinAction(summary.resolvedResume.resolvedLocation, displayCard.title, description),
  );

  return {
    card: applyContinuityRecovery(
      {
        id: `continuity-summary-${summary.id}`,
        kind: displayCard.kind,
        tone: displayCard.tone,
        eyebrow: displayCard.eyebrow,
        title: displayCard.title,
        summary: displayCard.summary,
        rationale: displayCard.rationale,
        preview: displayCard.preview,
        trust: displayCard.trust,
        handoff: displayCard.handoff,
        actionContextLabel: displayCard.actionContextLabel ?? (actions.length ? "Continue from here" : null),
        actionWarning: displayCard.actionWarning ?? null,
        recovery: null,
        actions,
      },
      recovery,
    ),
    undoAction,
    rerunAction,
  };
}

function rankWorkflowSummary(summary: ContinuityWorkflowSummary): RankedWorkflowSummary {
  const recovery = buildContinuityRecoveryPlan({
    displayTitle: summary.displayTitle,
    resolvedTarget: summary.resolvedResume,
    workflowThread: summary.workflowThread,
  });
  const cardState = buildSummaryCard(summary, recovery);
  return {
    ...summary,
    card: cardState.card,
    recovery,
    undoAction: cardState.undoAction,
    rerunAction: cardState.rerunAction,
  } satisfies RankedWorkflowSummary;
}

function summaryLocationIdentities(summary: ContinuityWorkflowSummary): string[] {
  return [summary.requestedResumeLocation, summary.resolvedResume.resolvedLocation]
    .filter((value): value is ShellLocationContract => value != null)
    .map((value) => continuityLocationIdentity(value));
}

function recentWorkflowThread(
  entry: RecentShellActionEntry,
  title: string,
  summary: string,
  resumeLocation: ShellLocationContract,
): WorkflowThreadRef {
  return entry.outcome?.workflowThread ?? {
    id: `recent:${entry.kind}:${continuityLocationIdentity(resumeLocation)}`,
    kind: "ad_hoc",
    title,
    summary,
    parentOutcomeId: null,
  };
}

function recentResolvedResume(entry: RecentShellActionEntry): ResolvedContinuityTarget | null {
  const resolved = resolveContinuityEntry(entry);
  if (!resolved.resumeLocation) {
    return null;
  }
  if (entry.outcome?.resolvedResume) {
    return entry.outcome.resolvedResume;
  }
  const usedLaunchFallback = entry.outcome?.resumeLocation == null;
  return {
    requestedLocation: entry.outcome?.resumeLocation ?? entry.location ?? null,
    resolvedLocation: resolved.resumeLocation,
    status: usedLaunchFallback ? "launch_fallback" : "ok",
    message: usedLaunchFallback
      ? "Receipt missing a landed resume target, so continuity falls back to the launch surface."
      : null,
    successor: null,
  };
}

function buildFreshOutcomeSummary(
  entry: RecentShellActionEntry,
  maxDurableRank: number,
  index: number,
): ContinuityWorkflowSummary | null {
  if (entry.outcome?.card.kind !== "receipt" || entry.persistence?.status === "synced") {
    return null;
  }

  const resolved = resolveContinuityEntry(entry);
  const resolvedResume = recentResolvedResume(entry);
  const card = resolved.card;
  if (!card || !resolvedResume) {
    return null;
  }

  const degraded = resolvedResume.status !== "ok" || resolved.degradedReason !== "none";
  const ageMinutes = Math.max(0, (Date.now() - Date.parse(entry.occurredAt)) / 60000);
  const rankingSignals = scoreRankingSignals({
    severity: "moderate",
    workingSetRelevant: resolved.workingSetId != null,
    downstreamReady: resolvedResume.resolvedLocation.state !== "operator",
    degraded,
    ageMinutes,
  });
  const title = resolved.displayTitle.trim();
  const summary = resolved.displaySummary.trim();
  const workflowThread = recentWorkflowThread(entry, title, summary, resolvedResume.resolvedLocation);
  const statusNote = entry.persistence?.status === "failed"
    ? "Durable continuity sync failed, so this local receipt remains the latest continuity record until retry."
    : "Fresh landed outcome was recorded locally and is waiting for durable continuity sync.";

  return {
    id: workflowThread.id,
    source: "recent",
    rank: maxDurableRank + totalRankingScore(rankingSignals, "recent") + Math.max(0, 12 - index),
    rankingSignals,
    workflowThread,
    representativeOutcomeId: entry.persistence?.persistedOutcomeId ?? null,
    latestOutcomeId: entry.persistence?.persistedOutcomeId ?? null,
    occurredAt: entry.occurredAt,
    outcomeCount: 1,
    outcomePreviewTitles: title ? [title] : [],
    requestedResumeLocation: entry.outcome?.resumeLocation ?? entry.location ?? null,
    resolvedResume,
    displayTitle: title,
    displaySummary: summary,
    displayCard: {
      kind: card.kind,
      tone: card.tone,
      eyebrow: card.eyebrow,
      title: card.title,
      summary: card.summary,
      rationale: card.rationale,
      preview: card.preview,
      trust: card.trust,
      handoff: card.handoff,
      actionContextLabel: card.actionContextLabel ?? null,
      actionWarning: card.actionWarning ?? null,
    },
    undoAction: entry.outcome?.undoAction ?? null,
    rerunAction: entry.outcome?.rerunAction ?? null,
    workingSetId: resolved.workingSetId,
    workingSetName: resolved.workingSet?.workingSetName ?? null,
    degraded,
    degradedLabel: card.actionWarning ?? resolvedResume.message ?? null,
    whyNow: [statusNote],
    changedSinceLastSeen: summary ? [summary] : [],
    priorState: null,
  } satisfies ContinuityWorkflowSummary;
}

function freshOutcomeSummaries(
  recentActions: readonly RecentShellActionEntry[],
  durableSummaries: readonly ContinuityWorkflowSummary[],
): ContinuityWorkflowSummary[] {
  const durableThreadIds = new Set(durableSummaries.map((summary) => summary.workflowThread.id));
  const durableLocationIdentities = new Set(durableSummaries.flatMap((summary) => summaryLocationIdentities(summary)));
  const maxDurableRank = durableSummaries.reduce((max, summary) => Math.max(max, summary.rank), 0);

  return recentActions
    .filter((entry) => entry.outcome?.card.kind === "receipt" && entry.persistence?.status !== "synced")
    .sort((left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt))
    .map((entry, index) => buildFreshOutcomeSummary(entry, maxDurableRank, index))
    .filter((summary): summary is ContinuityWorkflowSummary => summary != null)
    .filter((summary) => {
      if (durableThreadIds.has(summary.workflowThread.id)) {
        return false;
      }
      return !summaryLocationIdentities(summary).some((identity) => durableLocationIdentities.has(identity));
    });
}

export function readRankedWorkflowSummaries(
  input: ReadRankedWorkflowSummariesInput = {},
): RankedWorkflowSummary[] {
  const summaries = input.summaries ?? readContinuityWorkflowSummaries();
  return summaries.map((summary) => rankWorkflowSummary(summary));
}

export function readMergedRankedWorkflowSummaries(
  input: ReadMergedRankedWorkflowSummariesInput = {},
): RankedWorkflowSummary[] {
  const durableSummaries = input.summaries ?? readContinuityWorkflowSummaries();
  const recentActions = input.recentActions ?? readRecentShellActions();
  const summaries = [
    ...freshOutcomeSummaries(recentActions, durableSummaries),
    ...durableSummaries,
  ];
  return summaries
    .map((summary) => rankWorkflowSummary(summary))
    .sort((left, right) => right.rank - left.rank || Date.parse(right.occurredAt) - Date.parse(left.occurredAt));
}

function isPlanningOrReviewSessionLocation(location: ShellLocationContract | null | undefined): boolean {
  if (!location || location.sessionId == null) {
    return false;
  }
  if (location.state === "plan") {
    return true;
  }
  return location.state === "decide"
    && (location.reviewFocus === "relationship" || location.reviewFocus === "enrichment");
}

function sameResumableSession(
  left: ShellLocationContract | null | undefined,
  right: ShellLocationContract,
): boolean {
  if (!left || !isPlanningOrReviewSessionLocation(left) || !isPlanningOrReviewSessionLocation(right)) {
    return false;
  }
  return left.state === right.state
    && left.reviewFocus === right.reviewFocus
    && left.sessionId === right.sessionId;
}

function findSummaryForLocation(
  summaries: readonly RankedWorkflowSummary[],
  requestedLocation: ShellLocationContract,
  allowSessionMatch: boolean,
): RankedWorkflowSummary | null {
  const requestedIdentity = continuityLocationIdentity(requestedLocation);
  const exact = summaries.find((item) => {
    return continuityLocationIdentity(item.requestedResumeLocation) === requestedIdentity
      || continuityLocationIdentity(item.resolvedResume.resolvedLocation) === requestedIdentity;
  });
  if (exact) {
    return exact;
  }

  if (!allowSessionMatch || !isPlanningOrReviewSessionLocation(requestedLocation)) {
    return null;
  }

  return summaries.find((item) => {
    return sameResumableSession(item.requestedResumeLocation, requestedLocation)
      || sameResumableSession(item.resolvedResume.resolvedLocation, requestedLocation);
  }) ?? null;
}

export function resolveDurableReopenLocation(input: {
  location: ShellLocationContract;
  summaries?: readonly RankedWorkflowSummary[];
  allowSessionMatch?: boolean;
}): DurableReopenResolution {
  const summaries = input.summaries ?? readRankedWorkflowSummaries();
  const allowSessionMatch = input.allowSessionMatch ?? false;

  const summaryMatch = findSummaryForLocation(summaries, input.location, allowSessionMatch);
  if (summaryMatch) {
    return {
      resolvedLocation: summaryMatch.resolvedResume.resolvedLocation,
      recovery: summaryMatch.recovery,
      matched: true,
    };
  }

  return {
    resolvedLocation: input.location,
    recovery: null,
    matched: false,
  };
}

export function findRecoveryPlanForLocation(
  summaries: readonly RankedWorkflowSummary[],
  input: {
    location: ShellLocationContract | null;
    workflowThreadId?: string | null;
  },
): ContinuityRecoveryPlan | null {
  const targetIdentity = continuityLocationIdentity(input.location);

  return summaries.find((item) => {
    if (!item.recovery) {
      return false;
    }
    return (
      (input.workflowThreadId != null && item.workflowThread.id === input.workflowThreadId)
      || continuityLocationIdentity(item.requestedResumeLocation) === targetIdentity
      || continuityLocationIdentity(item.resolvedResume.resolvedLocation) === targetIdentity
    );
  })?.recovery ?? null;
}
