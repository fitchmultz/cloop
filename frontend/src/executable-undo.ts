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
  LoopResponse,
  LoopUndoResponse,
  PlanningExecutionHistoryItemResponse,
  PlanningSessionRollbackResponse,
  WorkingSetContextResponse,
  WorkingSetDeleteResponse,
  WorkingSetResponse,
  WorkingSetUndoRequest,
  WorkingSetUndoResponse,
} from "./domain";
import { HttpRequestError, requestJson } from "./http";
import { createLocation, workingSetSessionLocation } from "./shell-routing";
import { loopTitle } from "./shell-core";

export interface ExecutedUndoResult {
  card: OperatorActionCard;
  entry: Omit<RecentShellActionEntry, "occurredAt">;
  resumeLocation: ShellLocationContract | null;
}

function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

export function undoHandleIdentity(handle: ExecutableUndoHandle): string {
  if (handle.kind === "loop_event") {
    return `loop:${handle.loopId}:event:${handle.expectedEventId}`;
  }
  if (handle.kind === "planning_run") {
    return `planning:${handle.sessionId}:run:${handle.runId}`;
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

function planningRollbackIsBestEffort(execution: PlanningExecutionHistoryItemResponse): boolean {
  const results = execution.results ?? [];
  return results.some((result) =>
    (result.rollback_actions ?? []).some((action) => action["kind"] !== "loop.undo")
  );
}

export function buildPlanningRollbackAction(
  sessionId: number,
  execution: PlanningExecutionHistoryItemResponse,
  options: { variant?: "primary" | "secondary"; successLocation?: ShellLocationContract | null } = {},
): OperatorActionCardUndoAction | null {
  if (!execution.is_active || execution.rollback || typeof execution.run_id !== "number") {
    return null;
  }
  const actionCount = execution.rollback_cues?.rollback_action_count ?? 0;
  if (actionCount < 1) {
    return null;
  }
  const bestEffort = planningRollbackIsBestEffort(execution);
  const label = bestEffort ? "Rollback checkpoint" : "Undo checkpoint";
  const description = bestEffort
    ? `Rollback ${execution.checkpoint_title}. Some changes may fail if downstream state drifted.`
    : `Undo ${execution.checkpoint_title} and return the plan to its prior checkpoint state.`;
  return {
    type: "undo",
    label,
    variant: options.variant ?? "secondary",
    description,
    undo: {
      kind: "planning_run",
      sessionId,
      runId: execution.run_id,
      checkpointIndex: execution.checkpoint_index,
      checkpointTitle: execution.checkpoint_title,
      actionCount,
      bestEffort,
    },
    requiresConfirmation: bestEffort,
    confirmTitle: bestEffort ? "Rollback checkpoint" : null,
    confirmDescription: bestEffort
      ? `Rollback will attempt ${actionCount} action${actionCount === 1 ? "" : "s"} in reverse order. Continue only if you want a best-effort reversal.`
      : null,
    successLocation: options.successLocation ?? planResumeLocation(sessionId),
  };
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
  const failedActions = rollback.failed_actions ?? [];
  const checkpointTitle = rollback.summary?.trim()
    ? rollback.summary
    : `Rolled back checkpoint ${snapshot.session.current_checkpoint_index + 1}`;
  const title = rollback.rollback_complete ? "Rolled back planning checkpoint" : "Planning rollback incomplete";
  const summary = rollback.summary ?? "Rollback finished without a detailed summary.";
  const card = createReceiptCard({
    id: `undo-planning-${sessionId}-${rollback.rolled_back_at_utc ?? Date.now()}`,
    eyebrow: "Rollback receipt",
    title,
    summary,
    rationale:
      "Rollback receipts keep checkpoint reversals explicit so the planning session remains resumable after consequential undo work.",
    tone: rollback.rollback_complete ? "progress" : "caution",
    preview: [
      { label: "Session", value: snapshot.session.name },
      { label: "Attempted actions", value: `${rollback.attempted_action_count}` },
      { label: "Failed actions", value: `${rollback.failed_action_count}` },
      { label: "Checkpoint", value: checkpointTitle },
    ],
    trust: {
      generationLabel: rollback.rollback_complete ? "Executed planning rollback" : "Planning rollback incomplete",
      generationTone: rollback.rollback_complete ? "progress" : "caution",
      contextSources: [snapshot.session.name, "Stored planning execution history"],
      assumptions: ["Rollback only targeted the latest active checkpoint execution."],
      confidenceLabel: rollback.rollback_complete ? "Checkpoint rewound to the prior state" : "Some rollback actions still need manual follow-up",
      confidenceTone: rollback.rollback_complete ? "progress" : "caution",
      freshnessLabel: rollback.rolled_back_at_utc ? `Saved ${rollback.rolled_back_at_utc}` : "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: rollback.rollback_complete
        ? "You can inspect earlier execution history or re-run the checkpoint from the planning session."
        : "Inspect failed rollback actions before trusting the restored state.",
      rollbackTone: rollback.rollback_complete ? "neutral" : "caution",
      impactSummary: summary,
      impactTone: rollback.rollback_complete ? "progress" : "caution",
    },
    handoff: {
      changeSummary: summary,
      createdResources: failedActions.map((action) => `${action["resource_type"]} #${action["resource_id"]}`),
      nextStep: rollback.rollback_complete
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
          runId: hasOwn(rollback, "run_id") ? (rollback as { run_id?: unknown }).run_id : null,
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

export function staleUndoReason(error: unknown): string | null {
  if (error instanceof HttpRequestError) {
    return error.message;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return null;
}
