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
  ShellLocationContract,
} from "./contracts-ui";
import { readContinuityWorkflowSummaries } from "./continuity-intelligence";
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
