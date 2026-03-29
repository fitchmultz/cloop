/**
 * action-receipts.ts - Shared post-action receipt builders.
 *
 * Purpose:
 *   Build canonical receipt-flavored operator action cards for completed shell
 *   mutations and staged handoffs.
 *
 * Responsibilities:
 *   - Create receipt cards that reuse trust surfaces and workflow handoffs.
 *   - Attach receipt outcomes to recent shell actions.
 *   - Keep resume and rollback affordances consistent across shell flows.
 *
 * Scope:
 *   - Frontend-only receipt shaping helpers.
 *
 * Usage:
 *   - Imported by working-set, review, command-palette, and shell modules after
 *     deterministic work lands.
 *
 * Invariants/Assumptions:
 *   - Receipts describe completed outcomes, not proposed actions.
 *   - Resume and rollback context stays explicit on every rendered receipt.
 */

import type {
  ContinuityCardDisplay,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  OperatorActionHandoff,
  OperatorActionPreviewItem,
  RecentShellActionEntry,
  ShellLocationContract,
  TrustSurfaceMetadata,
  WorkflowThreadRef,
} from "./contracts-ui";

export interface CreateReceiptCardInput {
  id: string;
  eyebrow: string;
  title: string;
  summary: string;
  rationale: string;
  tone: OperatorActionCard["tone"];
  preview?: OperatorActionPreviewItem[];
  trust: TrustSurfaceMetadata;
  handoff: OperatorActionHandoff | null;
  resumeLocation?: ShellLocationContract | null;
  resumeLabel?: string;
  resumeDescription?: string;
  pinLabel?: string | null;
  actionContextLabel?: string | null;
  actionWarning?: string | null;
  actions?: OperatorActionCardAction[];
}

function buildResumeAction(
  location: ShellLocationContract,
  label: string,
  description: string,
): OperatorActionCardAction {
  return {
    type: "open",
    label,
    variant: "primary",
    description,
    location,
  };
}

function buildPinAction(
  location: ShellLocationContract,
  label: string,
  description: string,
  pinLabel: string,
): OperatorActionCardAction {
  return {
    type: "pin",
    label,
    variant: "secondary",
    description,
    location,
    pinLabel,
  };
}

export function createReceiptCard(input: CreateReceiptCardInput): OperatorActionCard {
  const actions: OperatorActionCardAction[] = [];

  if (input.resumeLocation) {
    actions.push(
      buildResumeAction(
        input.resumeLocation,
        input.resumeLabel ?? "Resume from here",
        input.resumeDescription ?? input.summary,
      ),
    );
  }

  if (input.resumeLocation && input.pinLabel) {
    actions.push(
      buildPinAction(
        input.resumeLocation,
        "Pin outcome",
        input.resumeDescription ?? input.summary,
        input.pinLabel,
      ),
    );
  }

  if (input.actions?.length) {
    actions.push(...input.actions);
  }

  const missingResumeWarning = input.resumeLocation
    ? null
    : "Receipt missing a landed resume target. Update this emitter so continuity can reopen the outcome safely.";

  return {
    id: input.id,
    kind: "receipt",
    tone: input.tone,
    eyebrow: input.eyebrow,
    title: input.title,
    summary: input.summary,
    rationale: input.rationale,
    preview: input.preview ?? [],
    trust: input.trust,
    handoff: input.handoff,
    actionContextLabel: missingResumeWarning
      ? "Receipt contract gap"
      : (input.actionContextLabel ?? (actions.length ? "Continue from here" : null)),
    actionWarning: missingResumeWarning ?? input.actionWarning ?? null,
    actions,
  };
}

export function createReceiptCardFromDisplayCard(input: {
  id: string;
  displayCard: ContinuityCardDisplay;
  resumeLocation: ShellLocationContract | null;
  resumeDescription?: string;
  pinLabel?: string | null;
  actions?: OperatorActionCardAction[];
}): OperatorActionCard {
  return createReceiptCard({
    id: input.id,
    eyebrow: input.displayCard.eyebrow,
    title: input.displayCard.title,
    summary: input.displayCard.summary,
    rationale: input.displayCard.rationale,
    tone: input.displayCard.tone,
    preview: input.displayCard.preview,
    trust: input.displayCard.trust,
    handoff: input.displayCard.handoff,
    resumeLocation: input.resumeLocation,
    ...(input.resumeDescription !== undefined ? { resumeDescription: input.resumeDescription } : {}),
    ...(input.pinLabel !== undefined ? { pinLabel: input.pinLabel } : {}),
    actionContextLabel: input.displayCard.actionContextLabel ?? null,
    actionWarning: input.displayCard.actionWarning ?? null,
    ...(input.actions !== undefined ? { actions: input.actions } : {}),
  });
}

export function findUndoAction(card: OperatorActionCard): OperatorActionCardUndoAction | null {
  return card.actions.find((action): action is OperatorActionCardUndoAction => action.type === "undo") ?? null;
}

export function findRerunAction(card: OperatorActionCard): OperatorActionCardRerunAction | null {
  return card.actions.find((action): action is OperatorActionCardRerunAction => action.type === "rerun") ?? null;
}

export interface ReceiptOutcomeOptions {
  workflowThread?: WorkflowThreadRef | null;
}

export function withReceiptOutcome(
  entry: Omit<RecentShellActionEntry, "occurredAt">,
  card: OperatorActionCard,
  resumeLocation: ShellLocationContract | null,
  options: ReceiptOutcomeOptions = {},
): Omit<RecentShellActionEntry, "occurredAt"> {
  return {
    ...entry,
    outcome: {
      card,
      resumeLocation,
      rollbackLabel: card.trust.rollbackLabel ?? null,
      undoAction: findUndoAction(card),
      rerunAction: findRerunAction(card),
      workflowThread: options.workflowThread ?? null,
      resolvedResume: null,
    },
  };
}
