/**
 * operator-action-card-events.ts - Shared action-card click dispatch for shell-owned surfaces.
 *
 * Purpose:
 *   Execute shared operator action-card semantics outside review-local event handlers.
 *
 * Responsibilities:
 *   - Decode open, pin, stage, edit, defer, undo, recovery, and notification button datasets.
 *   - Reuse shell navigation and working-set pinning callbacks.
 *   - Keep shared follow-through, recovery, and notification actions deterministic across shell-owned surfaces.
 *
 * Scope:
 *   - Shared shell-side action-card dispatch only.
 *
 * Usage:
 *   - Imported by frontend/src/shell-events.ts.
 *
 * Invariants/Assumptions:
 *   - Review-local event actions remain owned by review-workspace.ts.
 *   - Shared follow-through actions carry full shell-location state in data-* attributes.
 */

import type {
  ClarificationAnswerUndoHandle,
  ExecutableRerunHandle,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  PlanningRunUndoHandle,
  RecallTool,
  RelationshipDecisionUndoHandle,
  RerunAttemptContract,
  WorkingSetEventUndoHandle,
  ReviewFocus,
  ShellState,
} from "./contracts-ui";
import { parseOptionalInteger } from "./shell-core";
import { createLocation } from "./shell-routing";
import type { ShellLocation } from "./shell-types";

export interface OperatorActionCardDispatchOptions {
  applyLocation: (
    input: Partial<ShellLocation>,
    options?: { syncHash?: boolean; refreshWorkspace?: boolean },
  ) => Promise<void>;
  pinLocationToWorkingSet: (
    location: ShellLocation,
    label: string,
    description: string | null,
    options?: { receiptVariant?: "pin" | "stage" | "defer" },
  ) => Promise<void>;
  executeUndoAction: (
    action: OperatorActionCardUndoAction,
    button: HTMLButtonElement,
  ) => Promise<void>;
  executeRerunAction: (
    action: OperatorActionCardRerunAction,
    button: HTMLButtonElement,
  ) => Promise<void>;
  acknowledgeContinuityRecovery: (key: string) => void;
  acknowledgeContinuityNotification: (notificationId: string) => void;
  suppressContinuityNotification: (notificationId: string, hours: number) => void;
}

type ActionPrefix = "open" | "pin" | "stage" | "edit" | "defer" | "undoSuccess" | "recover";

const NOTIFICATION_ACKNOWLEDGEMENT_PREFIX = "notification:";

function locationFromButton(button: HTMLButtonElement, prefix: ActionPrefix): ShellLocation {
  return createLocation({
    state: button.dataset[`${prefix}State`] as ShellState | undefined,
    recallTool: button.dataset[`${prefix}RecallTool`] as RecallTool | undefined,
    reviewFocus: button.dataset[`${prefix}ReviewFocus`] as ReviewFocus | undefined,
    sessionId: parseOptionalInteger(button.dataset[`${prefix}SessionId`]),
    loopId: parseOptionalInteger(button.dataset[`${prefix}LoopId`]),
    viewId: parseOptionalInteger(button.dataset[`${prefix}ViewId`]),
    memoryId: parseOptionalInteger(button.dataset[`${prefix}MemoryId`]),
    workingSetId: parseOptionalInteger(button.dataset[`${prefix}WorkingSetId`]),
    query: button.dataset[`${prefix}Query`]?.trim() || null,
  });
}

function parseDatasetJson<T>(raw: string | undefined): T | null {
  if (!raw?.trim()) {
    return null;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function isClarificationAnswerUndoHandle(value: unknown): value is ClarificationAnswerUndoHandle {
  if (!value || typeof value !== "object") {
    return false;
  }
  const handle = value as Partial<ClarificationAnswerUndoHandle>;
  return handle.kind === "clarification_answer"
    && Number.isInteger(handle.loopId)
    && Number(handle.loopId) > 0
    && Array.isArray(handle.clarificationIds)
    && handle.clarificationIds.length > 0
    && handle.clarificationIds.every((clarificationId) => Number.isInteger(clarificationId) && clarificationId > 0);
}

function isRelationshipDecisionStateValue(value: unknown): value is "active" | "dismissed" | "resolved" {
  return value === "active" || value === "dismissed" || value === "resolved";
}

function isRelationshipDecisionStateShape(value: unknown): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  const state = value as Record<string, unknown>;
  return isRelationshipDecisionStateValue(state["state"])
    && (state["confidence"] == null || typeof state["confidence"] === "number")
    && (state["source"] == null || typeof state["source"] === "string");
}

function isRelationshipDecisionPairStateShape(value: unknown): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  const pair = value as Partial<RelationshipDecisionUndoHandle["expectedPairState"]>;
  return (pair.duplicate == null || isRelationshipDecisionStateShape(pair.duplicate))
    && (pair.related == null || isRelationshipDecisionStateShape(pair.related));
}

function isRelationshipDecisionUndoHandle(value: unknown): value is RelationshipDecisionUndoHandle {
  if (!value || typeof value !== "object") {
    return false;
  }
  const handle = value as Partial<RelationshipDecisionUndoHandle>;
  return handle.kind === "relationship_decision"
    && Number.isInteger(handle.sessionId)
    && Number(handle.sessionId) > 0
    && Number.isInteger(handle.loopId)
    && Number(handle.loopId) > 0
    && Number.isInteger(handle.candidateLoopId)
    && Number(handle.candidateLoopId) > 0
    && isRelationshipDecisionPairStateShape(handle.expectedPairState)
    && isRelationshipDecisionPairStateShape(handle.restorePairState);
}

function undoActionFromButton(button: HTMLButtonElement): OperatorActionCardUndoAction | null {
  const kind = button.dataset["undoKind"]?.trim();
  const description = button.dataset["undoDescription"]?.trim();
  if (!description) {
    return null;
  }
  if (kind === "loop_event") {
    const loopId = parseOptionalInteger(button.dataset["undoLoopId"]);
    const expectedEventId = parseOptionalInteger(button.dataset["undoExpectedEventId"]);
    if (loopId == null || expectedEventId == null) {
      return null;
    }
    return {
      type: "undo",
      label: button.textContent?.trim() || "Undo",
      variant: button.classList.contains("secondary") ? "secondary" : "primary",
      description,
      undo: {
        kind: "loop_event",
        loopId,
        expectedEventId,
        eventType: button.dataset["undoEventType"]?.trim() || null,
        claimToken: button.dataset["undoClaimToken"]?.trim() || null,
      },
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: button.dataset["undoRequiresConfirmation"] === "true",
      successLocation: button.hasAttribute("data-undo-success-state")
        ? locationFromButton(button, "undoSuccess")
        : null,
      disabledReason: button.disabled ? button.title || "Undo is unavailable." : null,
    };
  }
  if (kind === "planning_run") {
    const sessionId = parseOptionalInteger(button.dataset["undoSessionId"]);
    const runId = parseOptionalInteger(button.dataset["undoRunId"]);
    const checkpointIndex = parseOptionalInteger(button.dataset["undoCheckpointIndex"]);
    const actionCount = parseOptionalInteger(button.dataset["undoActionCount"]);
    if (sessionId == null || runId == null || checkpointIndex == null || actionCount == null) {
      return null;
    }
    const undo: PlanningRunUndoHandle = {
      kind: "planning_run",
      sessionId,
      runId,
      checkpointIndex,
      checkpointTitle: button.dataset["undoCheckpointTitle"]?.trim() || "",
      actionCount,
      bestEffort: button.dataset["undoBestEffort"] === "true",
    };
    return {
      type: "undo",
      label: button.textContent?.trim() || (undo.bestEffort ? "Rollback checkpoint" : "Undo checkpoint"),
      variant: button.classList.contains("secondary") ? "secondary" : "primary",
      description,
      undo,
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: button.dataset["undoRequiresConfirmation"] === "true",
      successLocation: button.hasAttribute("data-undo-success-state")
        ? locationFromButton(button, "undoSuccess")
        : null,
      disabledReason: button.disabled ? button.title || "Undo is unavailable." : null,
    };
  }
  if (kind === "working_set_event") {
    const expectedEventId = parseOptionalInteger(button.dataset["undoExpectedEventId"]);
    if (expectedEventId == null) {
      return null;
    }
    const undo: WorkingSetEventUndoHandle = {
      kind: "working_set_event",
      expectedEventId,
      eventType: button.dataset["undoEventType"]?.trim() || null,
      workingSetId: parseOptionalInteger(button.dataset["undoWorkingSetId"]),
      workingSetName: button.dataset["undoWorkingSetName"]?.trim() || null,
    };
    return {
      type: "undo",
      label: button.textContent?.trim() || "Undo",
      variant: button.classList.contains("secondary") ? "secondary" : "primary",
      description,
      undo,
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: button.dataset["undoRequiresConfirmation"] === "true",
      successLocation: button.hasAttribute("data-undo-success-state")
        ? locationFromButton(button, "undoSuccess")
        : null,
      disabledReason: button.disabled ? button.title || "Undo is unavailable." : null,
    };
  }
  if (kind === "relationship_decision") {
    const undo = parseDatasetJson<RelationshipDecisionUndoHandle>(button.dataset["undoHandle"]);
    if (!isRelationshipDecisionUndoHandle(undo)) {
      return null;
    }
    return {
      type: "undo",
      label: button.textContent?.trim() || "Undo decision",
      variant: button.classList.contains("secondary") ? "secondary" : "primary",
      description,
      undo,
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: button.dataset["undoRequiresConfirmation"] === "true",
      successLocation: button.hasAttribute("data-undo-success-state")
        ? locationFromButton(button, "undoSuccess")
        : null,
      disabledReason: button.disabled ? button.title || "Undo is unavailable." : null,
    };
  }
  if (kind === "clarification_answer") {
    const undo = parseDatasetJson<ClarificationAnswerUndoHandle>(button.dataset["undoHandle"]);
    if (!isClarificationAnswerUndoHandle(undo)) {
      return null;
    }
    return {
      type: "undo",
      label: button.textContent?.trim() || "Undo answers",
      variant: button.classList.contains("secondary") ? "secondary" : "primary",
      description,
      undo,
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: button.dataset["undoRequiresConfirmation"] === "true",
      successLocation: button.hasAttribute("data-undo-success-state")
        ? locationFromButton(button, "undoSuccess")
        : null,
      disabledReason: button.disabled ? button.title || "Undo is unavailable." : null,
    };
  }
  return null;
}

function rerunActionFromButton(button: HTMLButtonElement): OperatorActionCardRerunAction | null {
  const rerun = parseDatasetJson<ExecutableRerunHandle>(button.dataset["rerunHandle"]);
  const contract = parseDatasetJson<RerunAttemptContract>(button.dataset["rerunContract"]);
  if (!rerun || !contract) {
    return null;
  }
  return {
    type: "rerun",
    label: button.textContent?.trim() || (contract.mode === "refresh" ? "Refresh" : "Rerun"),
    variant: button.classList.contains("secondary") ? "secondary" : "primary",
    description: contract.postRun.summary,
    rerun,
    contract,
    disabledReason: button.disabled ? button.title || "Rerun is unavailable." : null,
  };
}

export async function handleOperatorActionCardClick(
  event: Event,
  options: OperatorActionCardDispatchOptions,
): Promise<boolean> {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const openButton = target.closest<HTMLButtonElement>("[data-open-state]");
  if (openButton) {
    await options.applyLocation(locationFromButton(openButton, "open"));
    return true;
  }

  const pinButton = target.closest<HTMLButtonElement>("[data-pin-label]");
  if (pinButton) {
    const label = pinButton.dataset["pinLabel"]?.trim();
    if (!label) {
      return true;
    }
    await options.pinLocationToWorkingSet(
      locationFromButton(pinButton, "pin"),
      label,
      pinButton.dataset["pinDescription"]?.trim() || null,
      { receiptVariant: "pin" },
    );
    return true;
  }

  const actionButton = target.closest<HTMLButtonElement>("[data-card-action]");
  if (!actionButton || actionButton.disabled) {
    return false;
  }

  switch (actionButton.dataset["cardAction"]) {
    case "stage": {
      const label = actionButton.dataset["stageLabel"]?.trim();
      if (!label) {
        return true;
      }
      const location = locationFromButton(actionButton, "stage");
      await options.pinLocationToWorkingSet(
        location,
        label,
        actionButton.dataset["stageDescription"]?.trim() || null,
        { receiptVariant: "stage" },
      );
      if (actionButton.dataset["stageOpenAfter"] !== "false") {
        await options.applyLocation(location);
      }
      return true;
    }
    case "edit": {
      const location = locationFromButton(actionButton, "edit");
      const query = actionButton.dataset["editQuery"]?.trim() || location.query;
      await options.applyLocation({ ...location, query: query || null });
      return true;
    }
    case "defer": {
      const label = actionButton.dataset["deferLabel"]?.trim();
      if (!label) {
        return true;
      }
      await options.pinLocationToWorkingSet(
        locationFromButton(actionButton, "defer"),
        label,
        actionButton.dataset["deferDescription"]?.trim() || null,
        { receiptVariant: "defer" },
      );
      return true;
    }
    case "undo": {
      const action = undoActionFromButton(actionButton);
      if (!action) {
        return true;
      }
      await options.executeUndoAction(action, actionButton);
      return true;
    }
    case "rerun": {
      const action = rerunActionFromButton(actionButton);
      if (!action) {
        return true;
      }
      await options.executeRerunAction(action, actionButton);
      return true;
    }
    case "recover": {
      const key = actionButton.dataset["recoveryKey"]?.trim();
      if (key) {
        options.acknowledgeContinuityRecovery(key);
      }
      await options.applyLocation(locationFromButton(actionButton, "recover"));
      return true;
    }
    case "acknowledge": {
      const key = actionButton.dataset["acknowledgementKey"]?.trim();
      if (!key) {
        return true;
      }
      if (key.startsWith(NOTIFICATION_ACKNOWLEDGEMENT_PREFIX)) {
        options.acknowledgeContinuityNotification(key.slice(NOTIFICATION_ACKNOWLEDGEMENT_PREFIX.length));
        return true;
      }
      options.acknowledgeContinuityRecovery(key);
      return true;
    }
    case "event": {
      const notificationId = actionButton.dataset["notificationSuppressId"]?.trim();
      if (!notificationId) {
        return false;
      }
      options.suppressContinuityNotification(
        notificationId,
        parseOptionalInteger(actionButton.dataset["notificationSuppressHours"]) ?? 24,
      );
      return true;
    }
    default:
      return false;
  }
}
