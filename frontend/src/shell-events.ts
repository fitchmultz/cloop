/**
 * shell-events.ts - Shell click handling, hotkeys, command palette, and initialization wiring.
 *
 * Purpose:
 *   Keep the operator shell's DOM event wiring and startup behavior separate
 *   from routing, working-set rendering, and workspace data loading.
 *
 * Responsibilities:
 *   - Handle delegated shell clicks and keyboard shortcuts.
 *   - Bootstrap the command palette with live shell callbacks.
 *   - Wire shell buttons, hash changes, and workspace refresh events.
 *   - Restore the initial shell location on startup.
 *
 * Scope:
 *   - Browser event handling and initialization only.
 *
 * Usage:
 *   - Created by frontend/src/shell.ts and called once during bootstrap.
 *
 * Invariants/Assumptions:
 *   - The shell coordinator remains the source of truth for location changes.
 *   - Event handlers must preserve existing operator-shell behavior exactly.
 *   - Command palette bindings remain delegated back into the shell runtime.
 */

import { bootstrapCommandPalette } from "./command-palette";
import {
  acknowledgeContinuityNotification,
  markContinuityRecoveryAcknowledged,
  suppressContinuityNotification,
} from "./continuity-intelligence";
import type { RecallTool, ReviewFocus, ShellState } from "./contracts-ui";
import type { WorkingSetContextResponse, WorkingSetResponse } from "./domain";
import { handleOperatorActionCardClick } from "./operator-action-card-events";
import {
  buildShellElements,
  parseOptionalInteger,
  WORKSPACE_REFRESH_EVENT,
} from "./shell-core";
import {
  createLocation,
  DEFAULT_LOCATION,
  defaultLocationForState,
  isWorkState,
  parseHash,
  readPersistedLocation,
  workingSetSessionLocation,
} from "./shell-routing";
import type { ShellElements, ShellLocation, WorkspaceData } from "./shell-types";

export interface ShellEventController {
  initializeShell(): void;
}

interface CreateShellEventControllerOptions {
  setElements: (elements: ShellElements) => void;
  getElements: () => ShellElements | null;
  getCurrentLocation: () => ShellLocation;
  getSuppressHashChange: () => boolean;
  readLastVisit: () => Date | null;
  setVisitBaseline: (value: Date | null) => void;
  readContinuityBaseline: () => import("./contracts-ui").ContinuityBaselineSnapshot | null;
  setContinuityBaseline: (value: import("./contracts-ui").ContinuityBaselineSnapshot | null) => void;
  setVisitStatePersisted: (value: boolean) => void;
  updateLastVisitStatus: () => void;
  applyLocation: (
    input: Partial<ShellLocation>,
    options?: { syncHash?: boolean; refreshWorkspace?: boolean },
  ) => Promise<void>;
  renderOperatorWorkspace: () => Promise<void>;
  getLatestWorkspaceData: () => WorkspaceData | null;
  getLatestWorkingSets: () => WorkingSetResponse[];
  getWorkingSetContext: () => WorkingSetContextResponse | null;
  createWorkingSetViaDialog: () => Promise<WorkingSetResponse | null>;
  promptForWorkingSetDetails: (
    defaults?: { name?: string; description?: string },
  ) => Promise<{ name: string; description: string | null } | null>;
  confirmWorkingSetDeletion: (name: string) => Promise<boolean>;
  setWorkingSetContext: (
    activeWorkingSetId: number | null,
    focusModeEnabled: boolean,
    options?: { recordHistory?: boolean },
  ) => Promise<void>;
  updateWorkingSet: (workingSetId: number, details: { name: string; description: string | null }) => Promise<void>;
  deleteWorkingSet: (workingSetId: number) => Promise<void>;
  reorderWorkingSetItems: (workingSetId: number, orderedItemIds: number[]) => Promise<void>;
  removeWorkingSetItem: (workingSetId: number, itemId: number) => Promise<void>;
  pinLocationToWorkingSet: (
    location: ShellLocation,
    label: string,
    description: string | null,
    options?: { receiptVariant?: "pin" | "stage" | "defer" },
  ) => Promise<void>;
  executeUndoAction: (
    action: import("./contracts-ui").OperatorActionCardUndoAction,
    button: HTMLButtonElement,
  ) => Promise<void>;
  executeRerunAction: (
    action: import("./contracts-ui").OperatorActionCardRerunAction,
    button: HTMLButtonElement,
  ) => Promise<void>;
  addLoopIdsToActiveWorkingSet: (loopIds: readonly number[]) => Promise<void>;
  openGroundedChatWithPrompt: (query: string) => Promise<void>;
  openMemorySearchWithQuery: (query: string) => Promise<void>;
  openDocumentAskWithQuery: (query: string) => Promise<void>;
}

export function createShellEventController(
  options: CreateShellEventControllerOptions,
): ShellEventController {
  let commandPaletteController: ReturnType<typeof bootstrapCommandPalette> | null = null;

  function workingSetIdFromButton(button: HTMLButtonElement, key: string): number | null {
    return parseOptionalInteger(button.dataset[key]);
  }

  async function handleShellClick(event: Event): Promise<void> {
    if (await handleOperatorActionCardClick(event, {
      applyLocation: options.applyLocation,
      pinLocationToWorkingSet: options.pinLocationToWorkingSet,
      executeUndoAction: options.executeUndoAction,
      executeRerunAction: options.executeRerunAction,
      acknowledgeContinuityRecovery: markContinuityRecoveryAcknowledged,
      acknowledgeContinuityNotification,
      suppressContinuityNotification,
    })) {
      return;
    }

    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const stateButton = target.closest<HTMLButtonElement>("[data-shell-state]");
    if (stateButton) {
      handleStateButtonClick(stateButton);
      return;
    }

    const recallButton = target.closest<HTMLButtonElement>("[data-recall-tool]");
    if (recallButton) {
      const currentLocation = options.getCurrentLocation();
      const recallTool = (recallButton.dataset["recallTool"] as RecallTool | undefined) ?? currentLocation.recallTool;
      await options.applyLocation(defaultLocationForState("recall", { ...currentLocation, recallTool }));
      return;
    }

    const workButton = target.closest<HTMLButtonElement>("[data-work-state]");
    if (workButton) {
      const workState = workButton.dataset["workState"] as ShellState | undefined;
      if (workState) {
        await options.applyLocation(defaultLocationForState(workState, options.getCurrentLocation()));
      }
      return;
    }

    const primaryActionButton = target.closest<HTMLButtonElement>("#shell-primary-action");
    if (primaryActionButton) {
      handlePrimaryActionClick();
      return;
    }

    if (target.closest<HTMLButtonElement>("#shell-refresh-workspace-btn")) {
      await options.renderOperatorWorkspace();
      return;
    }

    if (target.closest<HTMLButtonElement>("#shell-command-palette-btn")) {
      commandPaletteController?.open();
      return;
    }

    if (target.closest<HTMLButtonElement>("#operator-create-working-set-btn")) {
      const created = await options.createWorkingSetViaDialog();
      if (created) {
        await options.applyLocation(workingSetSessionLocation(created.id));
      }
      return;
    }

    const createButton = target.closest<HTMLButtonElement>("[data-working-set-create]");
    if (createButton) {
      const created = await options.createWorkingSetViaDialog();
      if (created) {
        await options.applyLocation(workingSetSessionLocation(created.id));
      }
      return;
    }

    const activateButton = target.closest<HTMLButtonElement>("[data-working-set-activate]");
    const activateId = activateButton ? workingSetIdFromButton(activateButton, "workingSetActivate") : null;
    if (activateButton && activateId != null) {
      await options.applyLocation(workingSetSessionLocation(activateId));
      return;
    }

    const focusButton = target.closest<HTMLButtonElement>("[data-working-set-focus]");
    const focusId = focusButton ? workingSetIdFromButton(focusButton, "workingSetFocus") : null;
    if (focusButton && focusId != null) {
      const workingSetContext = options.getWorkingSetContext();
      const shouldEnable = !(workingSetContext?.focus_mode_enabled && workingSetContext?.active_working_set_id === focusId);
      await options.setWorkingSetContext(focusId, shouldEnable, { recordHistory: false });
      await options.applyLocation(workingSetSessionLocation(focusId));
      return;
    }

    const editButton = target.closest<HTMLButtonElement>("[data-working-set-edit]");
    const editId = editButton ? workingSetIdFromButton(editButton, "workingSetEdit") : null;
    if (editButton && editId != null) {
      const existing = options.getLatestWorkingSets().find((set) => set.id === editId) ?? null;
      if (!existing) {
        return;
      }
      const details = await options.promptForWorkingSetDetails({
        name: existing.name,
        description: existing.description ?? "",
      });
      if (!details) {
        return;
      }
      await options.updateWorkingSet(editId, details);
      return;
    }

    const deleteButton = target.closest<HTMLButtonElement>("[data-working-set-delete]");
    const deleteId = deleteButton ? workingSetIdFromButton(deleteButton, "workingSetDelete") : null;
    if (deleteButton && deleteId != null) {
      const existing = options.getLatestWorkingSets().find((set) => set.id === deleteId) ?? null;
      if (!existing || !(await options.confirmWorkingSetDeletion(existing.name))) {
        return;
      }
      await options.deleteWorkingSet(deleteId);
      return;
    }

    const moveItemButton = target.closest<HTMLButtonElement>("[data-working-set-move]");
    const moveToken = moveItemButton?.dataset["workingSetMove"] ?? "";
    if (moveToken) {
      const [workingSetIdRaw = "", itemIdRaw = "", direction = ""] = moveToken.split(":");
      const workingSetId = Number.parseInt(workingSetIdRaw, 10);
      const itemId = Number.parseInt(itemIdRaw, 10);
      const workingSet = options.getLatestWorkingSets().find((set) => set.id === workingSetId) ?? null;
      if (!workingSet || !Number.isInteger(itemId)) {
        return;
      }
      const orderedIds = (workingSet.items ?? []).map((item) => item.id);
      const index = orderedIds.indexOf(itemId);
      if (index < 0) {
        return;
      }
      const swapIndex = direction === "up" ? index - 1 : index + 1;
      if (swapIndex < 0 || swapIndex >= orderedIds.length) {
        return;
      }
      const nextOrderedIds = [...orderedIds];
      const currentValue = nextOrderedIds[index];
      const swapValue = nextOrderedIds[swapIndex];
      if (currentValue == null || swapValue == null) {
        return;
      }
      nextOrderedIds[index] = swapValue;
      nextOrderedIds[swapIndex] = currentValue;
      await options.reorderWorkingSetItems(workingSetId, nextOrderedIds);
      return;
    }

    const removeItemButton = target.closest<HTMLButtonElement>("[data-remove-working-set-item]");
    const removeToken = removeItemButton?.dataset["removeWorkingSetItem"] ?? "";
    if (removeToken) {
      const [workingSetIdRaw = "", itemIdRaw = ""] = removeToken.split(":");
      const workingSetId = Number.parseInt(workingSetIdRaw, 10);
      const itemId = Number.parseInt(itemIdRaw, 10);
      if (!Number.isInteger(workingSetId) || !Number.isInteger(itemId)) {
        return;
      }
      await options.removeWorkingSetItem(workingSetId, itemId);
    }
  }

  function handleStateButtonClick(button: HTMLButtonElement): void {
    const state = button.dataset["shellState"] as ShellState | undefined;
    if (!state) {
      return;
    }
    const currentLocation = options.getCurrentLocation();
    const nextState = button.dataset["shellMobileWork"]
      ? (isWorkState(currentLocation.state) ? currentLocation.state : "do")
      : state;
    void options.applyLocation(defaultLocationForState(nextState, currentLocation));
  }

  function handlePrimaryActionClick(): void {
    const elements = options.getElements();
    if (!elements) {
      return;
    }
    const location = createLocation({
      state: elements.shellPrimaryAction.dataset["primaryState"] as ShellState | undefined,
      recallTool: elements.shellPrimaryAction.dataset["primaryRecallTool"] as RecallTool | undefined,
      reviewFocus: elements.shellPrimaryAction.dataset["primaryReviewFocus"] as ReviewFocus | undefined,
      sessionId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primarySessionId"]),
      loopId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryLoopId"]),
      viewId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryViewId"]),
      memoryId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryMemoryId"]),
      workingSetId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryWorkingSetId"]),
      query: elements.shellPrimaryAction.dataset["primaryQuery"]?.trim() || null,
    });
    void options.applyLocation(location);
  }

  function handleHashChange(): void {
    if (options.getSuppressHashChange()) {
      return;
    }
    const hashLocation = parseHash(window.location.hash) ?? readPersistedLocation();
    void options.applyLocation(hashLocation, { syncHash: false });
  }

  function shouldIgnoreHotkeys(target: EventTarget | null): boolean {
    return target instanceof HTMLElement
      && (target.tagName === "INPUT"
        || target.tagName === "TEXTAREA"
        || target.tagName === "SELECT"
        || target.isContentEditable);
  }

  function handleShellHotkeys(event: KeyboardEvent): void {
    if (event.defaultPrevented) {
      return;
    }
    if (commandPaletteController?.handleGlobalHotkey(event)) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }
    if (commandPaletteController?.isOpen()) {
      return;
    }
    if (shouldIgnoreHotkeys(event.target)) {
      return;
    }

    const currentLocation = options.getCurrentLocation();
    const mapping: Record<string, ShellLocation> = {
      "1": defaultLocationForState("operator", currentLocation),
      "2": defaultLocationForState("capture", currentLocation),
      "3": defaultLocationForState("do", currentLocation),
      "4": defaultLocationForState("decide", currentLocation),
      "5": defaultLocationForState("plan", currentLocation),
      "6": defaultLocationForState("review", currentLocation),
      "7": defaultLocationForState("recall", currentLocation),
    };

    const location = mapping[event.key];
    if (!location) {
      return;
    }

    event.preventDefault();
    event.stopImmediatePropagation();
    void options.applyLocation(location);
  }

  function initializeShell(): void {
    const elements = buildShellElements();
    options.setElements(elements);
    options.setVisitBaseline(options.readLastVisit());
    options.setContinuityBaseline(options.readContinuityBaseline());
    options.setVisitStatePersisted(false);
    options.updateLastVisitStatus();
    commandPaletteController = bootstrapCommandPalette({
      getContext: () => ({
        currentLocation: options.getCurrentLocation(),
        loops: options.getLatestWorkspaceData()?.allLoops ?? [],
        workingSets: options.getLatestWorkingSets(),
        workingSetContext: options.getWorkingSetContext(),
        nowFeed: options.getLatestWorkspaceData()?.nowFeed.items ?? [],
        planningSessions: options.getLatestWorkspaceData()?.planningSessions ?? [],
        relationshipSessions: options.getLatestWorkspaceData()?.relationshipSessions ?? [],
        enrichmentSessions: options.getLatestWorkspaceData()?.enrichmentSessions ?? [],
      }),
      openLocation: async (location) => options.applyLocation(location),
      refreshWorkspace: async () => options.renderOperatorWorkspace(),
      createWorkingSet: async () => options.createWorkingSetViaDialog(),
      setWorkingSetContext: async (workingSetId, focusModeEnabled) =>
        options.setWorkingSetContext(workingSetId, focusModeEnabled),
      pinLocation: async (location, label, description) =>
        options.pinLocationToWorkingSet(createLocation(location), label, description),
      addLoopIdsToActiveWorkingSet: async (loopIds) => options.addLoopIdsToActiveWorkingSet(loopIds),
      askGroundedChat: async (query) => options.openGroundedChatWithPrompt(query),
      runMemorySearch: async (query) => options.openMemorySearchWithQuery(query),
      runDocumentAsk: async (query) => options.openDocumentAskWithQuery(query),
    });

    document.addEventListener("click", (event) => {
      void handleShellClick(event);
    });
    elements.workingSetFocusToggleButton.addEventListener("click", () => {
      const activeId = options.getWorkingSetContext()?.active_working_set_id ?? null;
      if (activeId == null) {
        return;
      }
      void options.setWorkingSetContext(activeId, !Boolean(options.getWorkingSetContext()?.focus_mode_enabled));
    });
    elements.workingSetExitFocusButton.addEventListener("click", () => {
      void options.setWorkingSetContext(null, false);
    });
    window.addEventListener("hashchange", handleHashChange);
    window.addEventListener("keydown", handleShellHotkeys, { capture: true });
    window.addEventListener(WORKSPACE_REFRESH_EVENT, () => {
      void options.renderOperatorWorkspace();
    });

    const initialLocation = parseHash(window.location.hash) ?? readPersistedLocation() ?? DEFAULT_LOCATION;

    window.setTimeout(() => {
      void options.applyLocation(initialLocation, {
        syncHash: !window.location.hash,
        refreshWorkspace: true,
      });
    }, 0);
  }

  return {
    initializeShell,
  };
}
