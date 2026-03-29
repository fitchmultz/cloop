/**
 * shell.ts - Operator workspace and state-driven navigation bootstrap.
 *
 * Purpose:
 *   Establish the operator-first shell on top of the TypeScript-owned frontend runtime.
 *
 * Responsibilities:
 *   - Drive the top-level state-oriented navigation model.
 *   - Coordinate extracted shell modules for routing, workspace rendering,
 *     working-set state, and event wiring.
 *   - Launch capture, do, and recall through typed surface contracts.
 *   - Preserve deep-linkable context for plan/review/recall launches.
 *   - Maintain durable working-set/focus-mode context and since-last-visit summary.
 *
 * Scope:
 *   - Top-level shell routing, workspace aggregation, and shell-specific
 *     keyboard/navigation behaviors.
 *
 * Usage:
 *   - Imported and invoked from frontend/src/main.ts.
 *
 * Invariants/Assumptions:
 *   - Existing deep-work DOM surfaces remain present in frontend/index.html.
 *   - Hash routes are the canonical shareable/deep-link format for shell state.
 */

import type { ContinuityBaselineSnapshot, OperatorActionCard, RecallTool, ReviewFocus } from "./contracts-ui";
import {
  markContinuityNotificationSeen,
  markRerunActionUnavailable,
  markUndoActionUnavailable,
  readActiveContinuityNotificationRecords,
  readContinuityBaseline,
  RECENT_SHELL_ACTIONS_UPDATED_EVENT,
  recordRecentShellAction,
} from "./continuity-intelligence";
import { readMergedRankedWorkflowSummaries } from "./continuity-follow-through";
import { contractFromLocation } from "./surface-runtime";
import { updateChatPreferences } from "./surfaces/state";
import {
  displayElement,
  formatRelativeTime,
  formatTimestamp,
  HIGHLIGHT_CLASS,
  LAST_VISIT_STORAGE_KEY,
  REVIEW_FOCUS_EVENT,
} from "./shell-core";
import {
  createLocation,
  DEFAULT_LOCATION,
  locationToHash,
  locationsMatch,
  normalizeLocation,
  persistLocation,
  STATE_DESCRIPTORS,
} from "./shell-routing";
import {
  executeRerunAction as runExecutableRerunAction,
  staleRerunReason,
} from "./executable-rerun";
import {
  executeUndoAction as runExecutableUndoAction,
  staleUndoReason,
  undoConfirmationDialog,
} from "./executable-undo";
import { closeActiveModal, confirmDialog } from "./modals";
import { createShellEventController } from "./shell-events";
import { renderActionCardDeck } from "./operator-action-cards";
import { createShellOperatorCardRenderer, type ShellOperatorCardRenderer } from "./shell-operator-cards";
import { createShellWorkingSetController, type ShellWorkingSetController } from "./shell-working-set";
import { createShellWorkspaceController, type ShellWorkspaceController } from "./shell-workspace";
import type { ShellElements, ShellLocation, ShellRuntimeDependencies, WorkspaceData } from "./shell-types";

let elements: ShellElements | null = null;
let runtimeDependencies: ShellRuntimeDependencies | null = null;
let currentLocation: ShellLocation = DEFAULT_LOCATION;
let suppressHashChange = false;
let visitBaseline: Date | null = null;
let continuityBaseline: ContinuityBaselineSnapshot | null = null;
let visitStatePersisted = false;
let operatorCards: ShellOperatorCardRenderer | null = null;
let workingSetController: ShellWorkingSetController | null = null;
let workspaceController: ShellWorkspaceController | null = null;

function getLatestWorkspaceData(): WorkspaceData | null {
  return workspaceController?.getLatestWorkspaceData() ?? null;
}

function getLatestWorkingSets() {
  return workingSetController?.getLatestWorkingSets() ?? [];
}

function getWorkingSetContext() {
  return workingSetController?.getWorkingSetContext() ?? null;
}

function readLastVisit(): Date | null {
  const raw = window.localStorage.getItem(LAST_VISIT_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function writeLastVisitNow(): void {
  window.localStorage.setItem(LAST_VISIT_STORAGE_KEY, new Date().toISOString());
}

function updateShellHeader(location: ShellLocation): void {
  if (!elements) {
    return;
  }
  const descriptor = STATE_DESCRIPTORS[location.state];
  elements.shellTitle.textContent = descriptor.title;
  elements.shellDescription.textContent = descriptor.description;
  elements.shellContext.textContent = descriptor.context;
  elements.shellRoutePill.textContent = descriptor.pill;
  elements.shellPrimaryAction.textContent = descriptor.primaryActionLabel;
  elements.shellPrimaryAction.dataset["primaryState"] = descriptor.primaryActionLocation.state;
  elements.shellPrimaryAction.dataset["primaryRecallTool"] = descriptor.primaryActionLocation.recallTool;
  elements.shellPrimaryAction.dataset["primaryReviewFocus"] = descriptor.primaryActionLocation.reviewFocus ?? "";
  elements.shellPrimaryAction.dataset["primarySessionId"] =
    descriptor.primaryActionLocation.sessionId != null
      ? String(descriptor.primaryActionLocation.sessionId)
      : "";
  elements.shellPrimaryAction.dataset["primaryLoopId"] =
    descriptor.primaryActionLocation.loopId != null ? String(descriptor.primaryActionLocation.loopId) : "";
  elements.shellPrimaryAction.dataset["primaryViewId"] =
    descriptor.primaryActionLocation.viewId != null ? String(descriptor.primaryActionLocation.viewId) : "";
  elements.shellPrimaryAction.dataset["primaryMemoryId"] =
    descriptor.primaryActionLocation.memoryId != null ? String(descriptor.primaryActionLocation.memoryId) : "";
  elements.shellPrimaryAction.dataset["primaryWorkingSetId"] =
    descriptor.primaryActionLocation.workingSetId != null ? String(descriptor.primaryActionLocation.workingSetId) : "";
  elements.shellPrimaryAction.dataset["primaryQuery"] = descriptor.primaryActionLocation.query ?? "";
}

function syncNavState(location: ShellLocation): void {
  if (!elements) {
    return;
  }
  elements.stateButtons.forEach((button) => {
    const isActive = button.dataset["shellState"] === location.state;
    button.classList.toggle("active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });

  const showRecallSubnav = location.state === "recall";
  elements.recallSubnav.hidden = !showRecallSubnav;
  elements.recallButtons.forEach((button) => {
    const isActive = button.dataset["recallTool"] === location.recallTool;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function syncVisiblePanels(location: ShellLocation): void {
  if (!elements) {
    return;
  }

  displayElement(elements.operatorMain, location.state === "operator", "grid");
  displayElement(elements.inboxMain, location.state === "capture", "grid");
  displayElement(elements.nextMain, location.state === "do", "grid");
  displayElement(
    elements.reviewMain,
    location.state === "decide" || location.state === "plan" || location.state === "review",
    "grid",
  );
  displayElement(elements.chatMain, location.state === "recall" && location.recallTool === "chat", "grid");
  displayElement(
    elements.memoryMain,
    location.state === "recall" && location.recallTool === "memory",
    "grid",
  );
  displayElement(elements.ragMain, location.state === "recall" && location.recallTool === "rag", "grid");
  displayElement(elements.workingSetMain, location.state === "working_set", "grid");
}

async function activateOwnedSurface(location: ShellLocation): Promise<void> {
  if (!runtimeDependencies) {
    return;
  }

  const contract = contractFromLocation(location);
  if (!contract) {
    return;
  }

  await runtimeDependencies.surfaces.activate(contract);
}

function clearReviewFocusClasses(): void {
  const panels = document.querySelectorAll<HTMLElement>(
    ".planning-review-panel, .relationship-review-panel, .enrichment-review-panel, .bulk-enrichment-panel, #review-cohorts",
  );
  panels.forEach((panel) => panel.classList.remove("is-shell-focus"));
}

function getReviewFocusElement(focus: ReviewFocus | null): HTMLElement | null {
  const redesignedShell = document.getElementById("review-redesign-shell");
  if (redesignedShell) {
    return redesignedShell;
  }

  switch (focus) {
    case "planning":
      return document.querySelector<HTMLElement>(".planning-review-panel");
    case "relationship":
      return document.querySelector<HTMLElement>(".relationship-review-panel");
    case "enrichment":
      return document.querySelector<HTMLElement>(".enrichment-review-panel");
    case "cohorts":
      return document.getElementById("review-cohorts");
    default:
      return null;
  }
}

function emphasizeElement(element: HTMLElement | null): void {
  if (!element) {
    return;
  }
  element.classList.remove(HIGHLIGHT_CLASS);
  void element.offsetWidth;
  element.classList.add(HIGHLIGHT_CLASS);
  window.setTimeout(() => element.classList.remove(HIGHLIGHT_CLASS), 2200);
}

function focusReviewPanel(location: ShellLocation): void {
  clearReviewFocusClasses();
  const panel = getReviewFocusElement(location.reviewFocus);
  if (!panel) {
    return;
  }
  panel.classList.add("is-shell-focus");
  panel.scrollIntoView({ block: "start", behavior: "smooth" });
  emphasizeElement(panel);
}

function waitForCondition(predicate: () => boolean, attempts = 24, delayMs = 120): Promise<boolean> {
  return new Promise((resolve) => {
    let remaining = attempts;
    const tick = () => {
      if (predicate()) {
        resolve(true);
        return;
      }
      remaining -= 1;
      if (remaining <= 0) {
        resolve(false);
        return;
      }
      window.setTimeout(tick, delayMs);
    };
    tick();
  });
}

async function focusLoopCard(loopId: number): Promise<void> {
  const found = await waitForCondition(() => {
    return document.querySelector(`[data-loop-id="${loopId}"]`) instanceof HTMLElement;
  });
  if (!found) {
    return;
  }

  const cards = Array.from(document.querySelectorAll<HTMLElement>("[data-loop-id]"));
  const card = document.querySelector<HTMLElement>(`[data-loop-id="${loopId}"]`);
  cards.forEach((candidate) => {
    candidate.classList.toggle(
      "shell-focus-hidden",
      candidate !== card && Boolean(getWorkingSetContext()?.focus_mode_enabled),
    );
  });
  if (!card) {
    return;
  }
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  emphasizeElement(card);
}

async function selectViewFilter(viewId: number | null): Promise<void> {
  if (viewId == null) {
    return;
  }
  const available = await waitForCondition(() => {
    const select = document.getElementById("view-filter");
    return select instanceof HTMLSelectElement && select.options.length >= 1;
  });
  if (!available) {
    return;
  }
  const select = document.getElementById("view-filter");
  if (!(select instanceof HTMLSelectElement)) {
    return;
  }
  select.value = String(viewId);
  select.dispatchEvent(new Event("change", { bubbles: true }));
  emphasizeElement(select);
}

async function applyQueryAnchor(state: ShellLocation["state"], query: string | null): Promise<void> {
  if (!query) {
    return;
  }
  const inputId =
    state === "review"
      ? "review-bulk-enrich-query"
      : state === "do"
        ? "do-query-filter"
        : "query-filter";
  const available = await waitForCondition(() => {
    const input = document.getElementById(inputId);
    return input instanceof HTMLInputElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById(inputId);
  if (!(input instanceof HTMLInputElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  if (state !== "review") {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
  emphasizeElement(input);
}

async function focusMemoryEntry(memoryId: number | null): Promise<void> {
  if (memoryId == null) {
    return;
  }
  const found = await waitForCondition(() => {
    return document.querySelector(`[data-memory-id="${memoryId}"]`) instanceof HTMLElement;
  });
  if (!found) {
    return;
  }
  const card = document.querySelector<HTMLElement>(`[data-memory-id="${memoryId}"]`);
  if (!card) {
    return;
  }
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  emphasizeElement(card);
}

async function runMemorySearchSurface(query: string | null): Promise<void> {
  if (!query) {
    return;
  }
  const available = await waitForCondition(() => {
    return document.getElementById("memory-query") instanceof HTMLInputElement
      && document.getElementById("memory-filter-form") instanceof HTMLFormElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById("memory-query");
  const form = document.getElementById("memory-filter-form");
  if (!(input instanceof HTMLInputElement) || !(form instanceof HTMLFormElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  form.requestSubmit();
  emphasizeElement(input);
}

async function runDocumentAskSurface(query: string | null): Promise<void> {
  if (!query) {
    return;
  }
  const available = await waitForCondition(() => {
    return document.getElementById("rag-input") instanceof HTMLInputElement
      && document.getElementById("rag-form") instanceof HTMLFormElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById("rag-input");
  const form = document.getElementById("rag-form");
  if (!(input instanceof HTMLInputElement) || !(form instanceof HTMLFormElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  form.requestSubmit();
  emphasizeElement(input);
}

async function askGroundedChatSurface(query: string): Promise<void> {
  const available = await waitForCondition(() => {
    return document.getElementById("chat-input") instanceof HTMLInputElement
      && document.getElementById("chat-form") instanceof HTMLFormElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  if (!(input instanceof HTMLInputElement) || !(form instanceof HTMLFormElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  form.requestSubmit();
  emphasizeElement(input);
}

async function selectReviewSession(focus: ReviewFocus | null, sessionId: number | null): Promise<void> {
  if (focus) {
    window.dispatchEvent(
      new CustomEvent(REVIEW_FOCUS_EVENT, {
        detail: { focus, sessionId },
      }),
    );
  }

  if (sessionId == null) {
    return;
  }

  const selectId =
    focus === "planning"
      ? "review-shell-planning-session-select"
      : focus === "relationship"
        ? "review-shell-relationship-session-select"
        : focus === "enrichment"
          ? "review-shell-enrichment-session-select"
          : null;

  if (!selectId) {
    return;
  }

  const available = await waitForCondition(() => {
    const select = document.getElementById(selectId);
    return select instanceof HTMLSelectElement && select.options.length > 1;
  });
  if (!available) {
    return;
  }

  const select = document.getElementById(selectId);
  if (!(select instanceof HTMLSelectElement)) {
    return;
  }
  select.value = String(sessionId);
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function updateLastVisitStatus(): void {
  if (!elements) {
    return;
  }
  if (!visitBaseline) {
    elements.shellLastVisit.textContent = "First visit in this browser. The workspace is showing a calm current-state overview.";
    return;
  }
  elements.shellLastVisit.textContent = `Last visit ${formatRelativeTime(visitBaseline)} · ${formatTimestamp(
    visitBaseline.toISOString(),
  )}`;
}

function renderShellReceiptRail(): void {
  if (!elements) {
    return;
  }
  const workspaceData = getLatestWorkspaceData();
  if (!workspaceData) {
    elements.shellReceiptRail.hidden = true;
    elements.shellReceiptRail.innerHTML = "";
    return;
  }

  const cards: OperatorActionCard[] = readMergedRankedWorkflowSummaries()
    .slice(0, 1)
    .map((item) => item.card);

  elements.shellReceiptRail.hidden = cards.length === 0;
  elements.shellReceiptRail.innerHTML = cards.length
    ? renderActionCardDeck(cards, "")
    : "";
}

function markCurrentNotificationSeen(location: ShellLocation): void {
  const notification = readActiveContinuityNotificationRecords().find((candidate) => {
    return locationsMatch(candidate.resolvedLocation, location);
  });
  if (notification) {
    markContinuityNotificationSeen(notification.id);
  }
}

async function applyLocation(
  input: Partial<ShellLocation>,
  options: { syncHash?: boolean; refreshWorkspace?: boolean } = {},
): Promise<void> {
  const previousLocation = currentLocation;
  currentLocation = normalizeLocation(input);
  if (!locationsMatch(previousLocation, currentLocation)) {
    closeActiveModal();
  }
  markCurrentNotificationSeen(currentLocation);

  if (currentLocation.state === "working_set" && currentLocation.workingSetId != null && workingSetController) {
    const activeId = getWorkingSetContext()?.active_working_set_id ?? null;
    const desiredFocus =
      activeId === currentLocation.workingSetId
        ? Boolean(getWorkingSetContext()?.focus_mode_enabled)
        : false;

    if (activeId !== currentLocation.workingSetId || !getLatestWorkingSets().length) {
      await workingSetController.setWorkingSetContext(currentLocation.workingSetId, desiredFocus, {
        recordHistory: false,
      });
    }
  }

  updateShellHeader(currentLocation);
  syncNavState(currentLocation);
  syncVisiblePanels(currentLocation);
  await activateOwnedSurface(currentLocation);
  persistLocation(currentLocation);

  if (options.syncHash ?? true) {
    suppressHashChange = true;
    window.location.hash = locationToHash(currentLocation);
    window.setTimeout(() => {
      suppressHashChange = false;
    }, 0);
  }

  if (currentLocation.state === "working_set") {
    workingSetController?.renderWorkingSetSessionSurface();
  }

  if (currentLocation.state === "operator" || options.refreshWorkspace) {
    void workspaceController?.renderOperatorWorkspace();
  }

  if (currentLocation.state === "plan") {
    window.setTimeout(() => {
      focusReviewPanel(currentLocation);
      void selectReviewSession("planning", currentLocation.sessionId);
    }, 140);
  }

  if (currentLocation.state === "decide") {
    window.setTimeout(() => {
      focusReviewPanel(currentLocation);
      void selectReviewSession(currentLocation.reviewFocus, currentLocation.sessionId);
    }, 140);
  }

  if (currentLocation.state === "review") {
    window.setTimeout(() => {
      focusReviewPanel(createLocation({ state: "review", reviewFocus: "cohorts" }));
      void selectReviewSession("cohorts", null);
      void applyQueryAnchor("review", currentLocation.query ?? null);
    }, 140);
  }

  if (currentLocation.state === "capture") {
    window.setTimeout(() => {
      void selectViewFilter(currentLocation.viewId ?? null);
      void applyQueryAnchor("capture", currentLocation.query ?? null);
    }, 140);
  }

  if (currentLocation.state === "do") {
    if (currentLocation.loopId != null) {
      void focusLoopCard(currentLocation.loopId);
    }
    if (currentLocation.query) {
      window.setTimeout(() => {
        void applyQueryAnchor("do", currentLocation.query ?? null);
      }, 140);
    }
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "memory" && currentLocation.memoryId != null) {
    window.setTimeout(() => {
      void focusMemoryEntry(currentLocation.memoryId ?? null);
    }, 140);
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "chat" && currentLocation.query) {
    window.setTimeout(() => {
      void askGroundedChatSurface(currentLocation.query ?? "");
    }, 140);
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "memory" && currentLocation.query) {
    window.setTimeout(() => {
      void runMemorySearchSurface(currentLocation.query ?? null);
    }, 140);
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "rag" && currentLocation.query) {
    window.setTimeout(() => {
      void runDocumentAskSurface(currentLocation.query ?? null);
    }, 140);
  }
}

async function openGroundedChatWithPrompt(query: string): Promise<void> {
  await applyLocation(createLocation({ state: "recall", recallTool: "chat", query }));
}

async function openMemorySearchWithQuery(query: string): Promise<void> {
  await applyLocation(createLocation({ state: "recall", recallTool: "memory", query }));
}

async function openDocumentAskWithQuery(query: string): Promise<void> {
  await applyLocation(createLocation({ state: "recall", recallTool: "rag", query }));
}

async function rerunRecallQuery(handle: import("./contracts-ui").RecallQueryRerunHandle): Promise<void> {
  if (handle.recallTool === "chat") {
    const chatPreferenceOverrides = {
      ...(handle.includeLoopContext != null ? { includeLoopContext: handle.includeLoopContext } : {}),
      ...(handle.includeMemoryContext != null ? { includeMemoryContext: handle.includeMemoryContext } : {}),
      ...(handle.includeRagContext != null ? { includeRagContext: handle.includeRagContext } : {}),
    };
    if (Object.keys(chatPreferenceOverrides).length > 0) {
      updateChatPreferences(chatPreferenceOverrides);
    }
  }
  await applyLocation(
    createLocation({
      state: "recall",
      recallTool: handle.recallTool,
      workingSetId: handle.workingSetId,
      query: handle.query,
    }),
  );
}

function ensureControllers(): void {
  if (workingSetController && workspaceController && operatorCards) {
    return;
  }

  const renderOperatorZones = (data: WorkspaceData): void => {
    operatorCards?.renderOperatorZones(data);
  };

  workingSetController = createShellWorkingSetController({
    getElements: () => elements,
    getCurrentLocation: () => currentLocation,
    getLatestWorkspaceData,
    renderOperatorZones,
  });

  operatorCards = createShellOperatorCardRenderer({
    getElements: () => elements,
    getVisitBaseline: () => visitBaseline,
    getContinuityBaseline: () => continuityBaseline,
    getLatestWorkingSets,
    getWorkingSetContext,
    workingSetItemLocation: (item) => workingSetController!.workingSetItemLocation(item),
    focusModeActiveSet: () => workingSetController!.focusModeActiveSet(),
  });

  workspaceController = createShellWorkspaceController({
    getElements: () => elements,
    getCurrentLocation: () => currentLocation,
    getVisitStatePersisted: () => visitStatePersisted,
    setVisitStatePersisted: (value) => {
      visitStatePersisted = value;
    },
    setContinuityBaseline: (value) => {
      continuityBaseline = value;
    },
    writeLastVisitNow,
    getWorkingSetContext,
    loadWorkingSetState: () => workingSetController!.loadWorkingSetState(),
    renderOperatorZones,
    renderWorkingSet: (data) => workingSetController!.renderWorkingSet(data),
    renderWorkingSetFocusBanner: () => workingSetController!.renderWorkingSetFocusBanner(),
    syncFocusModeClass: () => workingSetController!.syncFocusModeClass(),
    renderWorkingSetSessionSurface: () => workingSetController!.renderWorkingSetSessionSurface(),
    onWorkspaceSettled: () => {
      renderShellReceiptRail();
    },
  });
}

export function bootstrapShell(dependencies: ShellRuntimeDependencies): void {
  runtimeDependencies = dependencies;
  ensureControllers();

  if (typeof window === "undefined") {
    return;
  }

  window.addEventListener(RECENT_SHELL_ACTIONS_UPDATED_EVENT, () => {
    renderShellReceiptRail();
    if (currentLocation.state === "operator") {
      void workspaceController?.renderOperatorWorkspace();
    }
  });

  const eventController = createShellEventController({
    setElements: (nextElements) => {
      elements = nextElements;
      renderShellReceiptRail();
    },
    getElements: () => elements,
    getCurrentLocation: () => currentLocation,
    getSuppressHashChange: () => suppressHashChange,
    readLastVisit,
    setVisitBaseline: (value) => {
      visitBaseline = value;
    },
    readContinuityBaseline,
    setContinuityBaseline: (value) => {
      continuityBaseline = value;
    },
    setVisitStatePersisted: (value) => {
      visitStatePersisted = value;
    },
    updateLastVisitStatus,
    applyLocation,
    renderOperatorWorkspace: async () => workspaceController!.renderOperatorWorkspace(),
    getLatestWorkspaceData,
    getLatestWorkingSets,
    getWorkingSetContext,
    createWorkingSetViaDialog: async () => workingSetController!.createWorkingSetViaDialog(),
    promptForWorkingSetDetails: async (defaults) => workingSetController!.promptForWorkingSetDetails(defaults),
    confirmWorkingSetDeletion: async (name) => workingSetController!.confirmWorkingSetDeletion(name),
    setWorkingSetContext: async (activeWorkingSetId, focusModeEnabled, options) =>
      workingSetController!.setWorkingSetContext(activeWorkingSetId, focusModeEnabled, options),
    updateWorkingSet: async (workingSetId, details) => workingSetController!.updateWorkingSet(workingSetId, details),
    deleteWorkingSet: async (workingSetId) => workingSetController!.deleteWorkingSet(workingSetId),
    reorderWorkingSetItems: async (workingSetId, orderedItemIds) =>
      workingSetController!.reorderWorkingSetItems(workingSetId, orderedItemIds),
    removeWorkingSetItem: async (workingSetId, itemId) => workingSetController!.removeWorkingSetItem(workingSetId, itemId),
    pinLocationToWorkingSet: async (location, label, description, options) =>
      workingSetController!.pinLocationToWorkingSet(location, label, description, options),
    executeUndoAction: async (action, button) => {
      const confirmation = undoConfirmationDialog(action);
      if (confirmation) {
        const confirmed = await confirmDialog({
          eyebrow: action.undo.kind === "planning_run" ? "Planning rollback" : "Undo",
          title: confirmation.title,
          description: confirmation.description,
          confirmLabel: action.label,
          confirmVariant: "danger",
        });
        if (!confirmed) {
          return;
        }
      }

      try {
        const result = await runExecutableUndoAction(action);
        recordRecentShellAction(result.entry);
      } catch (error: unknown) {
        const reason = staleUndoReason(error) ?? "Undo is no longer available.";
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
        button.title = reason;
        markUndoActionUnavailable(action.undo, reason);
      }
    },
    executeRerunAction: async (action, button) => {
      try {
        const result = await runExecutableRerunAction(action, {
          rerunRecallQuery,
        });
        recordRecentShellAction(result.entry);
        if (result.resumeLocation && action.rerun.kind !== "recall_query") {
          await applyLocation(result.resumeLocation);
        }
      } catch (error: unknown) {
        const reason = staleRerunReason(error) ?? "Rerun is no longer available.";
        if (staleRerunReason(error)) {
          button.disabled = true;
          button.setAttribute("aria-disabled", "true");
          button.title = reason;
          markRerunActionUnavailable(action.rerun, reason);
          return;
        }
        throw error;
      }
    },
    addLoopIdsToActiveWorkingSet: async (loopIds) => workingSetController!.addLoopIdsToActiveWorkingSet(loopIds),
    openGroundedChatWithPrompt,
    openMemorySearchWithQuery,
    openDocumentAskWithQuery,
  });

  const initializeShell = (): void => {
    eventController.initializeShell();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeShell, { once: true });
    return;
  }
  initializeShell();
}
