/**
 * operator-action-card-events.ts - Shared action-card click dispatch for shell-owned surfaces.
 *
 * Purpose:
 *   Execute shared operator action-card semantics outside review-local event handlers.
 *
 * Responsibilities:
 *   - Decode open, pin, stage, edit, and defer button datasets.
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

import type { RecallTool, ReviewFocus, ShellState } from "./contracts-ui";
import { parseOptionalInteger } from "./shell-core";
import { createLocation } from "./shell-routing";
import type { ShellLocation } from "./shell-types";

export interface OperatorActionCardDispatchOptions {
  applyLocation: (
    input: Partial<ShellLocation>,
    options?: { syncHash?: boolean; refreshWorkspace?: boolean; recordHistory?: boolean },
  ) => Promise<void>;
  pinLocationToWorkingSet: (location: ShellLocation, label: string, description: string | null) => Promise<void>;
}

type ActionPrefix = "open" | "pin" | "stage" | "edit" | "defer";

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
    );
    return true;
  }

  const actionButton = target.closest<HTMLButtonElement>("[data-card-action]");
  if (!actionButton) {
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
      );
      return true;
    }
    default:
      return false;
  }
}
