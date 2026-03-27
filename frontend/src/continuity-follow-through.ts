/**
 * continuity-follow-through.ts - Backend-authored continuity summary hydration helpers.
 *
 * Purpose:
 *   Turn durable backend workflow summaries into one canonical frontend follow-through
 *   feed so operator home, the receipt rail, the command palette, and downstream
 *   recovery consumers render the same ranked continuity model.
 *
 * Responsibilities:
 *   - Read backend-authored workflow summaries from the durable continuity cache.
 *   - Materialize backend-authored display payloads into renderable operator cards.
 *   - Attach canonical resume, rerun, undo, pin, and recovery actions.
 *   - Resolve saved planning/review reopen targets through shared summaries and anchors.
 *   - Expose shared recovery lookup for shell and non-shell surfaces.
 *   - Merge shell-only card chrome onto ranked summary cards without rewriting backend display.
 *
 * Scope:
 *   - Frontend rendering/model helpers for backend continuity summaries only.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts, shell.ts, command-palette.ts, and
 *     continuity-surface-recovery.ts.
 *
 * Invariants/Assumptions:
 *   - Backend workflow summaries are the canonical ranking, display, explanation,
 *     undo, and rerun source.
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
  ResumeAnchorState,
  ResumeAnchorTarget,
  ShellLocationContract,
} from "./contracts-ui";
import { readContinuityWorkflowSummaries, readResumeAnchors } from "./continuity-intelligence";
import { continuityLocationIdentity } from "./continuity-outcomes";
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
    buildPinAction(summary.resolvedResume.resolvedLocation, summary.displayCard.title, description),
  );

  return {
    card: applyContinuityRecovery(
      {
        id: `continuity-summary-${summary.id}`,
        kind: summary.displayCard.kind,
        tone: summary.displayCard.tone,
        eyebrow: summary.displayCard.eyebrow,
        title: summary.displayCard.title,
        summary: summary.displayCard.summary,
        rationale: summary.displayCard.rationale,
        preview: summary.displayCard.preview,
        trust: summary.displayCard.trust,
        handoff: summary.displayCard.handoff,
        actionContextLabel: summary.displayCard.actionContextLabel ?? (actions.length ? "Continue from here" : null),
        actionWarning: summary.displayCard.actionWarning ?? null,
        recovery: null,
        actions,
      },
      recovery,
    ),
    undoAction,
    rerunAction,
  };
}

export function readRankedWorkflowSummaries(
  input: ReadRankedWorkflowSummariesInput = {},
): RankedWorkflowSummary[] {
  const summaries = input.summaries ?? readContinuityWorkflowSummaries();

  return summaries.map((summary) => {
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
  });
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

function anchorCandidates(anchors: ResumeAnchorState): ResumeAnchorTarget[] {
  return [anchors.planning, anchors.review].filter((value): value is ResumeAnchorTarget => value != null);
}

function anchorLocations(anchor: ResumeAnchorTarget): ShellLocationContract[] {
  return [
    anchor.resumeLocation,
    anchor.resolvedResume?.requestedLocation,
    anchor.resolvedResume?.resolvedLocation,
    anchor.launchLocation,
  ].filter((value): value is ShellLocationContract => value != null);
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

function findAnchorForLocation(
  anchors: ResumeAnchorState,
  requestedLocation: ShellLocationContract,
  allowSessionMatch: boolean,
): ResumeAnchorTarget | null {
  const requestedIdentity = continuityLocationIdentity(requestedLocation);
  const exact = anchorCandidates(anchors).find((anchor) => {
    return anchorLocations(anchor).some((location) => continuityLocationIdentity(location) === requestedIdentity);
  });
  if (exact) {
    return exact;
  }

  if (!allowSessionMatch || !isPlanningOrReviewSessionLocation(requestedLocation)) {
    return null;
  }

  return anchorCandidates(anchors).find((anchor) => {
    return anchor.sessionId === requestedLocation.sessionId
      && ((anchor.kind === "planning" && requestedLocation.state === "plan")
        || (anchor.kind === "review"
          && requestedLocation.state === "decide"
          && anchor.reviewFocus === requestedLocation.reviewFocus));
  }) ?? null;
}

export function resolveDurableReopenLocation(input: {
  location: ShellLocationContract;
  summaries?: readonly RankedWorkflowSummary[];
  anchors?: ResumeAnchorState;
  allowSessionMatch?: boolean;
}): DurableReopenResolution {
  const summaries = input.summaries ?? readRankedWorkflowSummaries();
  const anchors = input.anchors ?? readResumeAnchors();
  const allowSessionMatch = input.allowSessionMatch ?? false;

  const summaryMatch = findSummaryForLocation(summaries, input.location, allowSessionMatch);
  if (summaryMatch) {
    return {
      resolvedLocation: summaryMatch.resolvedResume.resolvedLocation,
      recovery: summaryMatch.recovery,
      matched: true,
    };
  }

  const anchorMatch = findAnchorForLocation(anchors, input.location, allowSessionMatch);
  if (anchorMatch) {
    return {
      resolvedLocation: anchorMatch.resolvedResume?.resolvedLocation
        ?? anchorMatch.resumeLocation
        ?? anchorMatch.launchLocation
        ?? input.location,
      recovery: anchorMatch.resolvedResume
        ? buildContinuityRecoveryPlan({
            displayTitle: anchorMatch.outcomeTitle ?? `Resume ${anchorMatch.reviewFocus}`,
            resolvedTarget: anchorMatch.resolvedResume,
            workflowThread: null,
          })
        : null,
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
