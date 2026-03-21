/**
 * continuity-recovery.ts - Shared continuity recovery modeling and action shaping.
 *
 * Purpose:
 *   Turn degraded or superseded continuity outcomes into explicit recovery plans
 *   that every consumer surface can render and execute consistently.
 *
 * Responsibilities:
 *   - Build recovery plans from degraded fallback states and replaced workflows.
 *   - Build explicit recover and acknowledge card actions.
 *   - Apply recovery state to operator cards without per-surface duplication.
 *
 * Scope:
 *   - Frontend-only continuity recovery modeling and card shaping.
 *
 * Usage:
 *   - Imported by continuity-follow-through.ts and continuity-recommendations.ts.
 *
 * Invariants/Assumptions:
 *   - Recovery is a first-class UI state, not just warning copy.
 *   - Acknowledgement is browser-local presentation state, not durable backend truth.
 *   - Recovery plans always point at a deterministic surviving destination.
 */

import type {
  ContinuityRecoveryKind,
  ContinuityRecoveryPlan,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardAcknowledgeAction,
  OperatorActionCardRecoverAction,
  ShellLocationContract,
  WorkflowThreadRef,
} from "./contracts-ui";
import { isContinuityRecoveryAcknowledged } from "./continuity-intelligence";
import { continuityLocationIdentity } from "./continuity-outcomes";

function buildRecoveryKey(
  kind: ContinuityRecoveryKind,
  workflowThread: WorkflowThreadRef | null,
  requestedLocation: ShellLocationContract | null,
  resolvedLocation: ShellLocationContract,
): string {
  return [
    kind,
    workflowThread?.id ?? "ad_hoc",
    continuityLocationIdentity(requestedLocation),
    continuityLocationIdentity(resolvedLocation),
  ].join("::");
}

export function buildResolvedTargetRecoveryPlan(input: {
  kind: Exclude<ContinuityRecoveryKind, "replacement">;
  displayTitle: string;
  message: string | null;
  requestedLocation: ShellLocationContract | null;
  location: ShellLocationContract;
  workflowThread: WorkflowThreadRef | null;
}): ContinuityRecoveryPlan {
  const displayTitle = input.displayTitle.trim() || "This workflow";
  const key = buildRecoveryKey(input.kind, input.workflowThread, input.requestedLocation, input.location);

  if (input.kind === "working_set_scope_removed") {
    return {
      key,
      kind: input.kind,
      title: `${displayTitle} lost its working-set scope`,
      summary: input.message
        ?? "The original working-set scope is gone, but the durable target still survives outside that scope.",
      nextStep: "Open the durable target, then repin or restage it if it still belongs in a working set.",
      ctaLabel: "Open durable target",
      ctaDescription: "Continue from the surviving unscoped target.",
      location: input.location,
      acknowledged: isContinuityRecoveryAcknowledged(key),
    };
  }

  if (input.kind === "launch_fallback") {
    return {
      key,
      kind: input.kind,
      title: `${displayTitle} fell back to its launch workflow`,
      summary: input.message
        ?? "The landed outcome is no longer available, so recovery returns you to the workflow that created it.",
      nextStep: "Open the launch workflow, inspect what changed, and recreate or replace the missing outcome.",
      ctaLabel: "Open launch workflow",
      ctaDescription: "Return to the originating workflow and recover from there.",
      location: input.location,
      acknowledged: isContinuityRecoveryAcknowledged(key),
    };
  }

  return {
    key,
    kind: input.kind,
    title: `${displayTitle} no longer has a surviving target`,
    summary: input.message
      ?? "Neither the landed outcome nor its launch workflow still exists, so recovery falls back to home.",
    nextStep: "Return home, then choose a surviving queue, plan, or replacement path from the operator workspace.",
    ctaLabel: "Return home",
    ctaDescription: "Go back to the operator workspace and recover from a surviving path.",
    location: input.location,
    acknowledged: isContinuityRecoveryAcknowledged(key),
  };
}

export function buildReplacementRecoveryPlan(input: {
  priorTitle: string;
  representativeTitle: string;
  location: ShellLocationContract;
  workflowThread: WorkflowThreadRef | null;
  gone?: boolean;
  summaryOverride?: string | null;
}): ContinuityRecoveryPlan {
  const key = buildRecoveryKey("replacement", input.workflowThread, null, input.location);
  const priorTitle = input.priorTitle.trim() || "Your prior path";

  return {
    key,
    kind: "replacement",
    title: input.gone ? `${priorTitle} is gone` : `${priorTitle} was replaced`,
    summary: input.summaryOverride?.trim()
      || (input.gone
        ? `${priorTitle} is no longer available. Continue from ${input.representativeTitle}.`
        : `${priorTitle} was superseded by ${input.representativeTitle}.`),
    nextStep: input.gone
      ? "Open the surviving workflow and continue from the newest durable state."
      : "Open the replacement workflow and continue from the newer path instead of the superseded one.",
    ctaLabel: input.gone ? "Open surviving workflow" : "Open replacement workflow",
    ctaDescription: "Continue from the workflow that replaced the prior path.",
    location: input.location,
    acknowledged: isContinuityRecoveryAcknowledged(key),
  };
}

function buildRecoverAction(recovery: ContinuityRecoveryPlan): OperatorActionCardRecoverAction {
  return {
    type: "recover",
    label: recovery.ctaLabel,
    variant: "primary",
    description: recovery.ctaDescription,
    location: recovery.location,
    recoveryKey: recovery.key,
    recoveryKind: recovery.kind,
  };
}

function buildAcknowledgeAction(recovery: ContinuityRecoveryPlan): OperatorActionCardAcknowledgeAction | null {
  if (recovery.acknowledged) {
    return null;
  }
  return {
    type: "acknowledge",
    label: "Acknowledge change",
    variant: "secondary",
    description: recovery.summary,
    acknowledgementKey: recovery.key,
  };
}

function filteredCarryForwardActions(actions: readonly OperatorActionCardAction[]): OperatorActionCardAction[] {
  return actions.filter((action) => action.type !== "open" && action.type !== "recover" && action.type !== "acknowledge");
}

export function applyContinuityRecovery(
  card: OperatorActionCard,
  recovery: ContinuityRecoveryPlan | null,
): OperatorActionCard {
  if (!recovery) {
    return {
      ...card,
      recovery: null,
    };
  }

  const actions: OperatorActionCardAction[] = [buildRecoverAction(recovery)];
  const acknowledge = buildAcknowledgeAction(recovery);
  if (acknowledge) {
    actions.push(acknowledge);
  }
  actions.push(...filteredCarryForwardActions(card.actions));

  return {
    ...card,
    tone: card.tone === "progress" ? "attention" : card.tone,
    recovery,
    actionContextLabel: "Recovery path",
    actionWarning: recovery.acknowledged ? null : recovery.summary,
    actions,
  };
}
