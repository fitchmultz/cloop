/**
 * continuity-recovery.ts - Shared continuity recovery modeling and action shaping.
 *
 * Purpose:
 *   Turn backend-resolved degraded or superseded continuity targets into
 *   explicit recovery plans that every consumer surface can render and execute
 *   consistently.
 *
 * Responsibilities:
 *   - Build recovery plans from resolved fallback states and backend-authored
 *     replacement successors.
 *   - Build explicit recover and acknowledge card actions.
 *   - Apply recovery state to operator cards without per-surface duplication.
 *
 * Scope:
 *   - Frontend-only continuity recovery modeling and card shaping.
 *
 * Usage:
 *   - Imported by continuity-follow-through.ts, continuity-recommendations.ts,
 *     and downstream action-card surfaces.
 *
 * Invariants/Assumptions:
 *   - Recovery is a first-class UI state, not just warning copy.
 *   - Acknowledgement is backend-synced durable state with a browser-local cache.
 *   - Replacement recovery only appears when the backend emits explicit
 *     successor provenance.
 */

import type {
  ContinuityRecoveryKind,
  ContinuityRecoveryPlan,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardAcknowledgeAction,
  OperatorActionCardRecoverAction,
  ResolvedContinuityTarget,
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

function buildSuccessorRecoveryPlan(input: {
  displayTitle: string;
  resolvedTarget: ResolvedContinuityTarget;
  workflowThread: WorkflowThreadRef | null;
}): ContinuityRecoveryPlan | null {
  const successor = input.resolvedTarget.successor;
  if (!successor) {
    return null;
  }

  const key = buildRecoveryKey(
    "replacement",
    successor.workflowThread ?? input.workflowThread,
    input.resolvedTarget.requestedLocation,
    successor.resolvedLocation,
  );

  return {
    key,
    kind: "replacement",
    title: `${input.displayTitle} was replaced`,
    summary: successor.message?.trim()
      || `${input.displayTitle} was superseded by ${successor.title}.`,
    nextStep: "Open the surviving workflow and continue from the newer durable state.",
    ctaLabel: "Open replacement workflow",
    ctaDescription: `Continue from ${successor.title}.`,
    location: successor.resolvedLocation,
    acknowledged: isContinuityRecoveryAcknowledged(key),
  };
}

function buildFallbackRecoveryPlan(input: {
  displayTitle: string;
  resolvedTarget: ResolvedContinuityTarget;
  workflowThread: WorkflowThreadRef | null;
}): ContinuityRecoveryPlan | null {
  if (input.resolvedTarget.status === "ok") {
    return null;
  }

  const key = buildRecoveryKey(
    input.resolvedTarget.status,
    input.workflowThread,
    input.resolvedTarget.requestedLocation,
    input.resolvedTarget.resolvedLocation,
  );

  if (input.resolvedTarget.status === "working_set_scope_removed") {
    return {
      key,
      kind: input.resolvedTarget.status,
      title: `${input.displayTitle} lost its working-set scope`,
      summary: input.resolvedTarget.message
        ?? "The original working-set scope is gone, but the durable target still survives outside that scope.",
      nextStep: "Open the durable target, then repin or restage it if it still belongs in a working set.",
      ctaLabel: "Open durable target",
      ctaDescription: "Continue from the surviving unscoped target.",
      location: input.resolvedTarget.resolvedLocation,
      acknowledged: isContinuityRecoveryAcknowledged(key),
    };
  }

  if (input.resolvedTarget.status === "launch_fallback") {
    return {
      key,
      kind: input.resolvedTarget.status,
      title: `${input.displayTitle} fell back to its launch workflow`,
      summary: input.resolvedTarget.message
        ?? "The landed outcome is no longer available, so recovery returns you to the workflow that created it.",
      nextStep: "Open the launch workflow, inspect what changed, and recreate or replace the missing outcome.",
      ctaLabel: "Open launch workflow",
      ctaDescription: "Return to the originating workflow and recover from there.",
      location: input.resolvedTarget.resolvedLocation,
      acknowledged: isContinuityRecoveryAcknowledged(key),
    };
  }

  return {
    key,
    kind: input.resolvedTarget.status,
    title: `${input.displayTitle} no longer has a surviving target`,
    summary: input.resolvedTarget.message
      ?? "Neither the landed outcome nor its launch workflow still exists, so recovery falls back to home.",
    nextStep: "Return home, then choose a surviving queue, plan, or replacement path from the operator workspace.",
    ctaLabel: "Return home",
    ctaDescription: "Go back to the operator workspace and recover from a surviving path.",
    location: input.resolvedTarget.resolvedLocation,
    acknowledged: isContinuityRecoveryAcknowledged(key),
  };
}

export function buildContinuityRecoveryPlan(input: {
  displayTitle: string;
  resolvedTarget: ResolvedContinuityTarget | null;
  workflowThread: WorkflowThreadRef | null;
}): ContinuityRecoveryPlan | null {
  const { resolvedTarget } = input;
  if (!resolvedTarget) {
    return null;
  }
  return buildSuccessorRecoveryPlan({ ...input, resolvedTarget })
    ?? buildFallbackRecoveryPlan({ ...input, resolvedTarget });
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
