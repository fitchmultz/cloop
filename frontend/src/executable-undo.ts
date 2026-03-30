/**
 * executable-undo.ts - Shared executable undo contracts, builders, and transport helpers.
 *
 * Purpose:
 *   Centralize first-class undo and rollback behavior for receipt/history flows.
 *
 * Responsibilities:
 *   - Build typed undo actions from loop and planning payloads.
 *   - Execute undo actions through the canonical HTTP contracts.
 *   - Shape post-undo receipt cards and history entries consistently.
 *
 * Scope:
 *   - Frontend-only undo/rollback helpers.
 *
 * Usage:
 *   - Imported by review workspace, shell action-card events, and the command palette.
 *
 * Invariants/Assumptions:
 *   - Undo handles are always backend-aware and exact, never inferred from trust copy.
 *   - Successful undo returns a landed receipt with a deterministic resume location.
 */

import { createReceiptCard, withReceiptOutcome } from "./action-receipts";
import type {
  ExecutableUndoHandle,
  OperatorActionCard,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  ShellLocationContract,
  WorkingSetEventUndoHandle,
} from "./contracts-ui";
import type {
  ClarificationUndoResponse,
  LoopResponse,
  LoopUndoResponse,
  PlanningExecutionHistoryItemResponse,
  PlanningSessionRollbackResponse,
  RelationshipReviewSessionUndoRequest,
  RelationshipReviewSessionUndoResponse,
  WorkingSetContextResponse,
  WorkingSetDeleteResponse,
  WorkingSetResponse,
  WorkingSetUndoRequest,
  WorkingSetUndoResponse,
} from "./domain";
import { buildReviewFollowThroughReceipt, mapApiLocation } from "./follow-through-adapters";
import { HttpRequestError, requestJson } from "./http";
import { createLocation, workingSetSessionLocation } from "./shell-routing";
import { loopTitle } from "./shell-core";

export interface ExecutedUndoResult {
  card: OperatorActionCard;
  entry: Omit<RecentShellActionEntry, "occurredAt">;
  resumeLocation: ShellLocationContract | null;
}

function isHttpRequestError(error: unknown): error is HttpRequestError {
  return error instanceof HttpRequestError
    || (
      typeof error === "object"
      && error !== null
      && "name" in error
      && error.name === "HttpRequestError"
      && "status" in error
      && typeof error.status === "number"
      && "message" in error
      && typeof error.message === "string"
    );
}

function normalizeClarificationIds(clarificationIds: readonly number[]): number[] {
  return Array.from(new Set(
    clarificationIds
      .filter((clarificationId) => Number.isInteger(clarificationId) && clarificationId > 0)
      .map((clarificationId) => Number(clarificationId)),
  )).sort((left, right) => left - right);
}

export function undoHandleIdentity(handle: ExecutableUndoHandle): string {
  if (handle.kind === "loop_event") {
    return `loop:${handle.loopId}:event:${handle.expectedEventId}`;
  }
  if (handle.kind === "planning_run") {
    return `planning:${handle.sessionId}:run:${handle.runId}`;
  }
  if (handle.kind === "relationship_decision") {
    return `review:relationship:${handle.sessionId}:${handle.loopId}:${handle.candidateLoopId}`;
  }
  if (handle.kind === "clarification_answer") {
    return `clarification:${handle.loopId}:${normalizeClarificationIds(handle.clarificationIds).join(",")}`;
  }
  return `working-set:event:${handle.expectedEventId}`;
}

function loopResumeLocation(loop: Pick<LoopResponse, "id">): ShellLocationContract {
  return createLocation({ state: "do", loopId: loop.id });
}

function planResumeLocation(sessionId: number): ShellLocationContract {
  return createLocation({ state: "plan", reviewFocus: "planning", sessionId });
}

function workingSetResumeLocation(workingSetId: number): ShellLocationContract {
  return workingSetSessionLocation(workingSetId);
}

function operatorResumeLocation(): ShellLocationContract {
  return createLocation({ state: "operator" });
}

function workingSetName(value: { name?: string | null } | null | undefined, fallbackId: number | null = null): string {
  const name = value?.name?.trim();
  if (name) {
    return name;
  }
  return fallbackId != null ? `Working set #${fallbackId}` : "Working set";
}

export function buildLoopUndoAction(
  loop: Pick<LoopResponse, "id" | "latest_reversible_event_id" | "latest_reversible_event_type">,
  options: {
    label?: string;
    description: string;
    variant?: "primary" | "secondary";
    claimToken?: string | null;
    successLocation?: ShellLocationContract | null;
  },
): OperatorActionCardUndoAction | null {
  if (typeof loop.latest_reversible_event_id !== "number") {
    return null;
  }
  return {
    type: "undo",
    label: options.label ?? "Undo",
    variant: options.variant ?? "secondary",
    description: options.description,
    undo: {
      kind: "loop_event",
      loopId: loop.id,
      expectedEventId: loop.latest_reversible_event_id,
      eventType: loop.latest_reversible_event_type ?? null,
      claimToken: options.claimToken ?? null,
    },
    successLocation: options.successLocation ?? loopResumeLocation(loop),
  };
}

export function buildPlanningRollbackAction(
  execution: PlanningExecutionHistoryItemResponse,
): OperatorActionCardUndoAction | null {
  const action = execution.undo_action;
  if (!action) {
    return null;
  }
  return {
    type: "undo",
    label: action.label,
    variant: "secondary",
    description: action.description,
    undo: {
      kind: "planning_run",
      sessionId: action.undo.session_id,
      runId: action.undo.run_id,
      checkpointIndex: action.undo.checkpoint_index,
      checkpointTitle: action.undo.checkpoint_title,
      actionCount: action.undo.action_count ?? 0,
      bestEffort: action.undo.best_effort === true,
    },
    requiresConfirmation: action.requires_confirmation === true,
    confirmTitle: action.confirm_title ?? null,
    confirmDescription: action.confirm_description ?? null,
    successLocation: mapApiLocation(action.success_location),
  };
}

export function undoConfirmationDialog(action: OperatorActionCardUndoAction): {
  title: string;
  description: string;
} | null {
  if (!action.requiresConfirmation) {
    return null;
  }
  const title = action.confirmTitle?.trim();
  const description = action.confirmDescription?.trim();
  if (!title || !description) {
    throw new Error(MALFORMED_UNDO_CONFIRMATION_MESSAGE);
  }
  return { title, description };
}

export function buildWorkingSetUndoAction(
  source: Pick<
    WorkingSetResponse | WorkingSetContextResponse | WorkingSetDeleteResponse,
    "latest_reversible_event_id" | "latest_reversible_event_type"
  >,
  options: {
    description: string;
    label?: string;
    variant?: "primary" | "secondary";
    successLocation?: ShellLocationContract | null | undefined;
    workingSetId?: number | null | undefined;
    workingSetName?: string | null | undefined;
  },
): OperatorActionCardUndoAction | null {
  if (typeof source.latest_reversible_event_id !== "number") {
    return null;
  }
  const undo: WorkingSetEventUndoHandle = {
    kind: "working_set_event",
    expectedEventId: source.latest_reversible_event_id,
    eventType: source.latest_reversible_event_type ?? null,
    workingSetId: options.workingSetId ?? null,
    workingSetName: options.workingSetName ?? null,
  };
  return {
    type: "undo",
    label: options.label ?? "Undo",
    variant: options.variant ?? "secondary",
    description: options.description,
    undo,
    successLocation: options.successLocation
      ?? (undo.workingSetId != null ? workingSetResumeLocation(undo.workingSetId) : operatorResumeLocation()),
  };
}

export function buildClarificationUndoAction(
  loopId: number,
  clarificationIds: readonly number[],
): OperatorActionCardUndoAction | null {
  const normalizedClarificationIds = normalizeClarificationIds(clarificationIds);
  if (!Number.isInteger(loopId) || loopId <= 0 || normalizedClarificationIds.length === 0) {
    return null;
  }
  const clarificationCount = normalizedClarificationIds.length;
  return {
    type: "undo",
    label: clarificationCount === 1 ? "Undo answer" : "Undo answers",
    variant: "secondary",
    description: clarificationCount === 1
      ? "Restore this clarification to its unanswered state."
      : `Restore these ${clarificationCount} clarifications to their unanswered state.`,
    undo: {
      kind: "clarification_answer",
      loopId,
      clarificationIds: normalizedClarificationIds,
    },
    successLocation: loopResumeLocation({ id: loopId }),
  };
}

function maybeChainLoopUndo(loop: LoopResponse, summary: string): OperatorActionCardUndoAction | null {
  return buildLoopUndoAction(loop, {
    description: summary,
    successLocation: loopResumeLocation(loop),
  });
}

function maybeChainWorkingSetUndo(
  source: WorkingSetResponse | WorkingSetContextResponse | WorkingSetDeleteResponse,
  description: string,
  options: {
    workingSetId?: number | null;
    workingSetName?: string | null;
    successLocation?: ShellLocationContract | null;
  } = {},
): OperatorActionCardUndoAction | null {
  return buildWorkingSetUndoAction(source, {
    description,
    successLocation: options.successLocation,
    workingSetId: options.workingSetId,
    workingSetName: options.workingSetName,
  });
}

function buildLoopUndoReceipt(response: LoopUndoResponse): ExecutedUndoResult {
  const loop = response.loop;
  const resumeLocation = loopResumeLocation(loop);
  const loopLabel = loopTitle(loop);
  const summary = `Restored ${loopLabel} after undoing the latest ${response.undone_event_type.replaceAll("_", " ")} event.`;
  const card = createReceiptCard({
    id: `undo-loop-${loop.id}-${response.undo_event_id}`,
    eyebrow: "Undo receipt",
    title: `Restored ${loopLabel}`,
    summary,
    rationale:
      "Undo receipts keep reversals visible, resumable, and outcome-linked so recent history stays trustworthy.",
    tone: "progress",
    preview: [
      { label: "Loop", value: loopLabel },
      { label: "Undid", value: response.undone_event_type.replaceAll("_", " ") },
      { label: "Undo event", value: `#${response.undo_event_id}` },
    ],
    trust: {
      generationLabel: "Executed loop undo",
      generationTone: "progress",
      contextSources: ["Exact loop event handle", `Loop #${loop.id}`],
      assumptions: ["The loop remains available in the Do surface after undo completes."],
      confidenceLabel: "Reverted the intended loop mutation",
      confidenceTone: "progress",
      freshnessLabel: "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: loop.latest_reversible_event_id != null
        ? "Earlier reversible loop history is still available from this restored state."
        : "No earlier reversible loop event is currently available.",
      rollbackTone: loop.latest_reversible_event_id != null ? "caution" : "neutral",
      impactSummary: summary,
      impactTone: "progress",
    },
    handoff: {
      changeSummary: summary,
      createdResources: [loopLabel],
      nextStep: "Open the restored loop and decide whether to continue, edit, or leave it as-is.",
      breadcrumbs: ["Home", "Undo", loopLabel],
    },
    resumeLocation,
    resumeLabel: "Open restored loop",
    resumeDescription: summary,
    pinLabel: `Loop · ${loopLabel}`,
    actions: [maybeChainLoopUndo(loop, `Undo the next earlier reversible change for ${loopLabel}.`)].filter(
      (action): action is OperatorActionCardUndoAction => action != null,
    ),
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: "command",
        label: card.title,
        description: card.summary,
        location: resumeLocation,
        metadata: {
          source: "undo",
          loopId: loop.id,
          undoEventId: response.undo_event_id,
          undoneEventId: response.undone_event_id,
        },
      },
      card,
      resumeLocation,
      {
        workflowThread: {
          id: `command:loop:${loop.id}`,
          kind: "command",
          title: card.title,
          summary: card.summary,
          parentOutcomeId: null,
        },
      },
    ),
  };
}

function buildPlanningRollbackReceipt(response: PlanningSessionRollbackResponse): ExecutedUndoResult {
  const rollback = response.rollback;
  const snapshot = response.snapshot;
  const sessionId = snapshot.session.id;
  const resumeLocation = planResumeLocation(sessionId);
  const failedActions = rollback.failed_actions;
  const attemptedActionCount = rollback.attempted_action_count;
  const failedActionCount = rollback.failed_action_count;
  const rollbackComplete = rollback.rollback_complete;
  const checkpointTitle = rollback.checkpoint_title.trim() || `Checkpoint #${rollback.checkpoint_index + 1}`;
  const title = rollbackComplete ? "Rolled back planning checkpoint" : "Planning rollback incomplete";
  const summary = rollback.summary.trim() || "Rollback finished without a detailed summary.";
  const card = createReceiptCard({
    id: `undo-planning-${sessionId}-${rollback.rolled_back_at_utc || rollback.run_id}`,
    eyebrow: "Rollback receipt",
    title,
    summary,
    rationale:
      "Rollback receipts keep checkpoint reversals explicit so the planning session remains resumable after consequential undo work.",
    tone: rollbackComplete ? "progress" : "caution",
    preview: [
      { label: "Session", value: snapshot.session.name },
      { label: "Attempted actions", value: `${attemptedActionCount}` },
      { label: "Failed actions", value: `${failedActionCount}` },
      { label: "Rolled back checkpoint", value: checkpointTitle },
    ],
    trust: {
      generationLabel: rollbackComplete ? "Executed planning rollback" : "Planning rollback incomplete",
      generationTone: rollbackComplete ? "progress" : "caution",
      contextSources: [snapshot.session.name, "Stored planning execution history"],
      assumptions: ["Rollback only targeted the latest active checkpoint execution."],
      confidenceLabel: rollbackComplete ? "Checkpoint rewound to the prior state" : "Some rollback actions still need manual follow-up",
      confidenceTone: rollbackComplete ? "progress" : "caution",
      freshnessLabel: rollback.rolled_back_at_utc ? `Saved ${rollback.rolled_back_at_utc}` : "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: rollbackComplete
        ? "You can inspect earlier execution history or re-run the checkpoint from the planning session."
        : "Inspect failed rollback actions before trusting the restored state.",
      rollbackTone: rollbackComplete ? "neutral" : "caution",
      impactSummary: summary,
      impactTone: rollbackComplete ? "progress" : "caution",
    },
    handoff: {
      changeSummary: summary,
      createdResources: failedActions.map((action) => `${action["resource_type"]} #${action["resource_id"]}`),
      nextStep: rollbackComplete
        ? "Resume the planning session and decide whether to re-execute or revise the checkpoint."
        : "Resume the planning session and inspect the failed rollback actions before continuing.",
      breadcrumbs: ["Home", "Plan", snapshot.session.name],
    },
    resumeLocation,
    resumeLabel: "Resume plan",
    resumeDescription: summary,
    pinLabel: `Plan · ${snapshot.session.name}`,
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: "planning",
        label: card.title,
        description: card.summary,
        location: resumeLocation,
        metadata: {
          source: "undo",
          sessionId,
        },
      },
      card,
      resumeLocation,
      {
        workflowThread: {
          id: `planning:${sessionId}`,
          kind: "planning_checkpoint",
          title: snapshot.session.name,
          summary: card.summary,
          parentOutcomeId: null,
        },
      },
    ),
  };
}

function buildWorkingSetUndoReceipt(response: WorkingSetUndoResponse): ExecutedUndoResult {
  const restoredWorkingSet = response.working_set;
  const activeWorkingSet = response.context.active_working_set ?? null;
  const primaryWorkingSet = restoredWorkingSet ?? activeWorkingSet;
  const primaryWorkingSetId = primaryWorkingSet?.id ?? response.affected_working_set_id ?? null;
  const primaryWorkingSetName = primaryWorkingSet?.name ?? response.affected_working_set_name ?? null;
  const resumeLocation = primaryWorkingSetId != null
    ? workingSetResumeLocation(primaryWorkingSetId)
    : operatorResumeLocation();
  const title = response.undone_event_type === "context_update"
    ? "Restored working-set context"
    : `Restored ${workingSetName(primaryWorkingSet, primaryWorkingSetId)}`;
  const summary = response.summary?.trim() || "Working-set undo completed.";
  const chainAction = restoredWorkingSet != null
    ? maybeChainWorkingSetUndo(
        restoredWorkingSet,
        `Undo the next earlier reversible change for ${workingSetName(restoredWorkingSet, restoredWorkingSet.id)}.`,
        {
          workingSetId: restoredWorkingSet.id,
          workingSetName: restoredWorkingSet.name,
          successLocation: workingSetResumeLocation(restoredWorkingSet.id),
        },
      )
    : maybeChainWorkingSetUndo(
        response.context,
        "Undo the next earlier working-set context change.",
        {
          workingSetId: activeWorkingSet?.id ?? null,
          workingSetName: activeWorkingSet?.name ?? null,
          successLocation: activeWorkingSet != null
            ? workingSetResumeLocation(activeWorkingSet.id)
            : operatorResumeLocation(),
        },
      );
  const card = createReceiptCard({
    id: `undo-working-set-${response.undo_event_id}`,
    eyebrow: "Undo receipt",
    title,
    summary,
    rationale:
      "Working-set undo receipts keep bounded-context reversals explicit so resumed sessions stay trustworthy after saved-state changes.",
    tone: "progress",
    preview: [
      { label: "Undid", value: response.undone_event_type.replaceAll("_", " ") },
      { label: "Undo event", value: `#${response.undo_event_id}` },
      ...(primaryWorkingSetName ? [{ label: "Working set", value: primaryWorkingSetName }] : []),
      { label: "Focus mode", value: response.context.focus_mode_enabled ? "Enabled" : "Off" },
    ],
    trust: {
      generationLabel: "Executed working-set undo",
      generationTone: "progress",
      contextSources: ["Exact working-set event handle"].concat(
        primaryWorkingSetName ? [primaryWorkingSetName] : ["Working-set context"]
      ),
      assumptions: ["Undo only succeeds when the supplied working-set event is still the latest reversible change."],
      confidenceLabel: "Reverted the intended working-set mutation",
      confidenceTone: "progress",
      freshnessLabel: "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: chainAction != null
        ? "Earlier reversible working-set history is still available from this restored state."
        : "No earlier reversible working-set event is currently available.",
      rollbackTone: chainAction != null ? "caution" : "neutral",
      impactSummary: summary,
      impactTone: "progress",
    },
    handoff: {
      changeSummary: summary,
      createdResources: primaryWorkingSetName ? [primaryWorkingSetName] : [],
      nextStep: primaryWorkingSetId != null
        ? "Open the restored working set and continue from the recovered bounded context."
        : "Continue from the unscoped operator workspace or reopen another working set.",
      breadcrumbs: ["Home", "Working set undo", primaryWorkingSetName ?? "Operator"],
      workingSet: primaryWorkingSet != null
        ? {
            workingSetId: primaryWorkingSet.id,
            workingSetName: primaryWorkingSet.name,
            itemCount: primaryWorkingSet.item_count,
            missingItemCount: primaryWorkingSet.missing_item_count,
          }
        : null,
    },
    resumeLocation,
    resumeLabel: primaryWorkingSetId != null ? "Open restored working set" : "Return to operator",
    resumeDescription: summary,
    pinLabel: primaryWorkingSetName ? `Working set · ${primaryWorkingSetName}` : null,
    actions: chainAction != null ? [chainAction] : [],
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: primaryWorkingSetId != null ? "working_set" : "working_set_session",
        label: card.title,
        description: card.summary,
        location: resumeLocation,
        metadata: {
          source: "undo",
          workingSetId: primaryWorkingSetId,
          undoneEventId: response.undone_event_id,
          undoEventId: response.undo_event_id,
        },
      },
      card,
      resumeLocation,
      {
        workflowThread: primaryWorkingSetId != null
          ? {
              id: `working-set:${primaryWorkingSetId}`,
              kind: "working_set",
              title: primaryWorkingSetName ?? card.title,
              summary: card.summary,
              parentOutcomeId: null,
            }
          : null,
      },
    ),
  };
}

function buildRelationshipDecisionUndoReceipt(
  response: RelationshipReviewSessionUndoResponse,
): ExecutedUndoResult {
  const summary = response.result.summary?.trim() || "Relationship decision undo completed.";
  return buildReviewFollowThroughReceipt({
    followThrough: response.follow_through,
    id: `undo-review-relationship-${response.result.loop_id}-${response.result.candidate_loop_id}`,
    label: response.follow_through.display_card.title,
    description: summary,
  });
}

function buildClarificationUndoReceipt(response: ClarificationUndoResponse): ExecutedUndoResult {
  const resumeLocation = loopResumeLocation({ id: response.loop_id });
  const restoredCount = response.restored_count;
  const reopenedCount = response.reopened_suggestion_ids?.length ?? 0;
  const summary = response.message?.trim()
    || (restoredCount === 1
      ? "Restored the clarification to its unanswered state."
      : `Restored ${restoredCount} clarifications to their unanswered state.`);
  const title = restoredCount === 1
    ? `Restored clarification on Loop #${response.loop_id}`
    : `Restored clarifications on Loop #${response.loop_id}`;
  const card = createReceiptCard({
    id: `undo-clarification-${response.loop_id}-${(response.restored_clarification_ids ?? []).join("-") || Date.now()}`,
    eyebrow: "Undo receipt",
    title,
    summary,
    rationale:
      "Clarification undo receipts keep answer-only review work reversible without hiding which questions and suggestions were restored.",
    tone: "progress",
    preview: [
      { label: "Loop", value: `Loop #${response.loop_id}` },
      { label: "Restored clarifications", value: String(restoredCount) },
      { label: "Reopened suggestions", value: String(reopenedCount) },
    ],
    trust: {
      generationLabel: "Executed clarification undo",
      generationTone: "progress",
      contextSources: [`Loop #${response.loop_id}`, "Exact clarification-answer handle"],
      assumptions: ["The loop remains available so you can review the restored unanswered clarification state."],
      confidenceLabel: restoredCount === 1 ? "Clarification restored" : "Clarifications restored",
      confidenceTone: "progress",
      freshnessLabel: "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: "Undo is no longer available for this restored answer-only clarification state.",
      rollbackTone: "neutral",
      impactSummary: reopenedCount > 0
        ? `Reopened ${reopenedCount} superseded suggestion${reopenedCount === 1 ? "" : "s"} for review.`
        : "The restored clarifications can be answered again before rerunning enrichment.",
      impactTone: reopenedCount > 0 ? "attention" : "progress",
    },
    handoff: {
      changeSummary: summary,
      createdResources: [
        restoredCount === 1 ? "1 restored clarification" : `${restoredCount} restored clarifications`,
        ...(reopenedCount > 0
          ? [reopenedCount === 1 ? "1 reopened suggestion" : `${reopenedCount} reopened suggestions`]
          : []),
      ],
      nextStep: reopenedCount > 0
        ? "Open the loop to review the reopened suggestions and restored questions together."
        : "Open the loop and answer the restored clarification again when you are ready.",
      breadcrumbs: ["Home", "Undo", `Loop #${response.loop_id}`],
    },
    resumeLocation,
    resumeLabel: "Open loop",
    resumeDescription: summary,
    pinLabel: `Loop · #${response.loop_id}`,
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: "review",
        label: title,
        description: summary,
        location: resumeLocation,
        metadata: {
          source: "undo",
          loopId: response.loop_id,
          restoredClarificationIds: response.restored_clarification_ids ?? [],
          reopenedSuggestionIds: response.reopened_suggestion_ids ?? [],
        },
      },
      card,
      resumeLocation,
      {
        workflowThread: {
          id: `clarification-answer:loop:${response.loop_id}`,
          kind: "ad_hoc",
          title,
          summary,
          parentOutcomeId: null,
        },
      },
    ),
  };
}

export async function executeUndoAction(action: OperatorActionCardUndoAction): Promise<ExecutedUndoResult> {
  if (action.undo.kind === "loop_event") {
    const response = await requestJson<LoopUndoResponse, { expected_event_id: number; claim_token?: string | null }>(
      `/loops/${action.undo.loopId}/undo`,
      {
        method: "POST",
        body: {
          expected_event_id: action.undo.expectedEventId,
          claim_token: action.undo.claimToken ?? null,
        },
      },
      "Failed to undo loop change",
    );
    return buildLoopUndoReceipt(response);
  }

  if (action.undo.kind === "working_set_event") {
    const response = await requestJson<WorkingSetUndoResponse, WorkingSetUndoRequest>(
      "/loops/working-sets/undo",
      {
        method: "POST",
        body: { expected_event_id: action.undo.expectedEventId },
      },
      "Failed to undo working-set change",
    );
    return buildWorkingSetUndoReceipt(response);
  }

  if (action.undo.kind === "relationship_decision") {
    const response = await requestJson<
      RelationshipReviewSessionUndoResponse,
      RelationshipReviewSessionUndoRequest
    >(
      `/loops/review/relationship/sessions/${action.undo.sessionId}/undo`,
      {
        method: "POST",
        body: { undo: {
          kind: "relationship_decision",
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
        } },
      },
      "Failed to undo relationship decision",
    );
    return buildRelationshipDecisionUndoReceipt(response);
  }

  if (action.undo.kind === "clarification_answer") {
    const response = await requestJson<ClarificationUndoResponse, { clarification_ids: number[] }>(
      `/loops/${action.undo.loopId}/clarifications/undo`,
      {
        method: "POST",
        body: { clarification_ids: action.undo.clarificationIds },
      },
      "Failed to undo clarification answers",
    );
    return buildClarificationUndoReceipt(response);
  }

  const response = await requestJson<PlanningSessionRollbackResponse, { run_id: number }>(
    `/loops/planning/sessions/${action.undo.sessionId}/rollback`,
    {
      method: "POST",
      body: { run_id: action.undo.runId },
    },
    action.undo.bestEffort ? "Failed to roll back checkpoint" : "Failed to undo checkpoint",
  );
  return buildPlanningRollbackReceipt(response);
}

const MALFORMED_UNDO_CONFIRMATION_MESSAGE = "Undo action requires backend confirmation title and description.";

export function undoUnavailableReason(error: unknown): string | null {
  if (isHttpRequestError(error)) {
    if (error.status === 400 || error.status === 404 || error.status === 409 || error.status === 422) {
      return error.message;
    }
    return null;
  }
  if (error instanceof Error && error.message.trim() === MALFORMED_UNDO_CONFIRMATION_MESSAGE) {
    return error.message;
  }
  return null;
}
