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
 *   - Reuse representative receipt cards while taking undo and rerun actions from the backend summary contract.
 *   - Build fallback summary cards when only anchor-style summary data exists.
 *   - Expose shared recovery lookup for shell and non-shell surfaces.
 *
 * Scope:
 *   - Frontend rendering/model helpers for backend continuity summaries only.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts, shell.ts, command-palette.ts, and
 *     continuity-surface-recovery.ts.
 *
 * Invariants/Assumptions:
 *   - Backend workflow summaries are the canonical ranking, explanation, undo, and rerun source.
 *   - Durable recent actions remain the source of representative receipt cards only.
 *   - Recovery plans continue to derive from backend-resolved targets and durable
 *     acknowledgement state.
 */

import type {
  ContinuityRecoveryPlan,
  ContinuityWorkflowSummary,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardPinAction,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  ShellLocationContract,
  WorkingSetSessionMetadata,
} from "./contracts-ui";
import {
  readContinuityWorkflowSummaries,
  readRecentShellActions,
} from "./continuity-intelligence";
import { continuityLocationIdentity } from "./continuity-outcomes";
import {
  applyContinuityRecovery,
  buildContinuityRecoveryPlan,
} from "./continuity-recovery";
import { formatRelativeTime } from "./shell-core";

export interface RankedWorkflowSummary extends ContinuityWorkflowSummary {
  card: OperatorActionCard;
  recovery: ContinuityRecoveryPlan | null;
}

export interface ReadRankedWorkflowSummariesInput {
  summaries?: readonly ContinuityWorkflowSummary[];
  recentActions?: readonly RecentShellActionEntry[];
}

function representativeEntryIndex(
  entries: readonly RecentShellActionEntry[],
): Map<number, RecentShellActionEntry> {
  return new Map(
    entries.flatMap((entry) => {
      const outcomeId = entry.persistence?.persistedOutcomeId ?? null;
      return outcomeId != null ? [[outcomeId, entry] as const] : [];
    }),
  );
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

function fallbackSummaryCard(
  summary: ContinuityWorkflowSummary,
  recovery: ContinuityRecoveryPlan | null,
  undoAction: OperatorActionCardUndoAction | null,
  rerunAction: OperatorActionCardRerunAction | null,
): OperatorActionCard {
  const resumeLocation = summary.resolvedResume.resolvedLocation;
  const degradedLabel = summary.degraded ? summary.degradedLabel : null;
  const workingSet = summary.workingSetId != null && summary.workingSetName
    ? {
        workingSetId: summary.workingSetId,
        workingSetName: summary.workingSetName,
        itemCount: 0,
        missingItemCount: 0,
      }
    : null;
  const preview = [
    ...(summary.whyNow[0] ? [{ label: "Why now", value: summary.whyNow[0] }] : []),
    ...(summary.changedSinceLastSeen[0] ? [{ label: "Changed", value: summary.changedSinceLastSeen[0] }] : []),
    ...(workingSet ? [{ label: "Working set", value: workingSet.workingSetName }] : []),
    ...(summary.outcomeCount > 1 ? [{ label: "Outcomes", value: `${summary.outcomeCount}` }] : []),
  ];

  return applyContinuityRecovery({
    id: `continuity-summary-${summary.id}`,
    kind: summary.source === "anchor" ? "handoff" : "context",
    tone: summary.degraded ? "attention" : (summary.source === "anchor" ? "attention" : "neutral"),
    eyebrow: summary.source === "anchor" ? "Resume anchor" : "Workflow summary",
    title: summary.displayTitle,
    summary: summary.displaySummary,
    rationale: "This card is rendered from the canonical backend continuity summary instead of client-side ranking heuristics.",
    preview,
    trust: {
      generationLabel: "Backend continuity summary",
      generationTone: "neutral",
      contextSources: ["Durable continuity workflow summary"],
      assumptions: [],
      confidenceLabel: "Deterministic continuity ranking",
      confidenceTone: "progress",
      freshnessLabel: `Updated ${formatRelativeTime(summary.occurredAt)}`,
      freshnessTone: "neutral",
      rollbackLabel: null,
      rollbackTone: "neutral",
      impactSummary: [...summary.whyNow, ...summary.changedSinceLastSeen].join(" · ") || summary.displaySummary,
      impactTone: "neutral",
    },
    handoff: {
      changeSummary: summary.changedSinceLastSeen.join(" · ") || summary.displaySummary,
      createdResources: summary.outcomePreviewTitles.slice(0, 3),
      nextStep: "Open the ranked workflow and continue from the durable landed state.",
      breadcrumbs: ["Home", "Since last visit", summary.workflowThread.title],
      workingSet,
    },
    actionContextLabel: "Continue from here",
    actionWarning: degradedLabel,
    recovery: null,
    actions: [
      buildResumeAction(resumeLocation, degradedLabel ?? summary.displaySummary),
      ...(rerunAction ? [{ ...rerunAction, variant: "secondary" as const }] : []),
      ...(undoAction ? [{ ...undoAction, variant: "secondary" as const }] : []),
      buildPinAction(resumeLocation, summary.displayTitle, degradedLabel ?? summary.displaySummary, `Outcome · ${summary.displayTitle}`),
    ],
  }, recovery);
}

function buildSummaryCard(
  summary: ContinuityWorkflowSummary,
  entry: RecentShellActionEntry | null,
  recovery: ContinuityRecoveryPlan | null,
): { card: OperatorActionCard; undoAction: OperatorActionCardUndoAction | null; rerunAction: OperatorActionCardRerunAction | null } {
  const baseCard = entry?.outcome?.card ?? null;
  const undoAction = summary.undoAction ?? null;
  const rerunAction = summary.rerunAction ?? null;
  const workingSet = baseCard?.handoff?.workingSet ?? null;

  if (!baseCard) {
    return {
      card: fallbackSummaryCard(summary, recovery, undoAction, rerunAction),
      undoAction,
      rerunAction,
    };
  }

  return {
    card: normalizeOutcomeCard(
      baseCard,
      summary.resolvedResume.resolvedLocation,
      summary.displaySummary,
      summary.degraded ? summary.degradedLabel : null,
      undoAction,
      rerunAction,
      workingSet,
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
  const recentActions = input.recentActions ?? readRecentShellActions();
  const entryByOutcomeId = representativeEntryIndex(recentActions);

  return summaries.map((summary) => {
    const recovery = buildContinuityRecoveryPlan({
      displayTitle: summary.displayTitle,
      resolvedTarget: summary.resolvedResume,
      workflowThread: summary.workflowThread,
    });
    const entry = summary.representativeOutcomeId != null
      ? (entryByOutcomeId.get(summary.representativeOutcomeId) ?? null)
      : null;
    const cardState = buildSummaryCard(summary, entry, recovery);
    return {
      ...summary,
      card: cardState.card,
      recovery,
      undoAction: cardState.undoAction,
      rerunAction: cardState.rerunAction,
    } satisfies RankedWorkflowSummary;
  });
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
