/**
 * operator-action-card-events.ts - Shared action-card click dispatch for shell-owned surfaces.
 *
 * Purpose:
 *   Execute shared operator action-card semantics outside review-local event handlers.
 *
 * Responsibilities:
 *   - Decode open, pin, stage, edit, defer, and undo button datasets.
 *   - Reuse shell navigation and working-set pinning callbacks.
 *   - Keep shared follow-through actions deterministic across shell-owned surfaces.
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
  ExecutableRerunHandle,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  PlanningRunUndoHandle,
  RecallTool,
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
    options?: { syncHash?: boolean; refreshWorkspace?: boolean; recordHistory?: boolean },
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
}

type ActionPrefix = "open" | "pin" | "stage" | "edit" | "defer" | "undoSuccess";

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

function undoActionFromButton(button: HTMLButtonElement): OperatorActionCardUndoAction | null {
  const kind = button.dataset["undoKind"]?.trim();
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
      description: button.dataset["undoEventType"]?.trim() || "Undo the latest loop event.",
      undo: {
        kind: "loop_event",
        loopId,
        expectedEventId,
        eventType: button.dataset["undoEventType"]?.trim() || null,
        claimToken: button.dataset["undoClaimToken"]?.trim() || null,
      },
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: Boolean(button.dataset["undoConfirmDescription"]?.trim()),
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
      description: button.dataset["undoCheckpointTitle"]?.trim() || "Undo the latest planning checkpoint.",
      undo,
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: Boolean(button.dataset["undoConfirmDescription"]?.trim()),
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
      description: button.dataset["undoEventType"]?.trim() || "Undo the latest working-set change.",
      undo,
      confirmTitle: button.dataset["undoConfirmTitle"]?.trim() || null,
      confirmDescription: button.dataset["undoConfirmDescription"]?.trim() || null,
      requiresConfirmation: Boolean(button.dataset["undoConfirmDescription"]?.trim()),
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
    default:
      return false;
  }
}
