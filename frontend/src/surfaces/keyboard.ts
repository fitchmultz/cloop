/**
 * keyboard.ts - Keyboard shortcuts for work surfaces.
 *
 * Purpose:
 *   Provide keyboard navigation and actions for the capture/do/recall runtime.
 *
 * Responsibilities:
 *   - Handle global navigation shortcuts and loop actions.
 *   - Support bulk selection shortcuts.
 *   - Open help and close modals from the keyboard.
 *
 * Scope:
 *   - Surface keyboard behavior only.
 *
 * Usage:
 *   - Imported by bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - Shell navigation is hash-based.
 *   - Loop cards use stable .loop-card and .loop-checkbox selectors.
 */

import * as state from "./state";
import { clearLoopSelection, selectedLoopIds, selectAllVisibleLoops, selectLoopRange } from "./state";
import { closeActiveModal, isModalOpen, showHelpModal } from "./modals";
import { closestFromEventTarget } from "./utils";

interface KeyboardModuleElements {
  rawText: HTMLTextAreaElement;
  queryFilter: HTMLInputElement;
  status: HTMLElement;
}

interface KeyboardCallbacks {
  showCompletionNote: (loopId: number | string) => void;
  enrichLoop: (loopId: number | string) => void | Promise<void>;
  refreshLoop: (loopId: number | string) => void | Promise<void>;
  toggleTimer: (loopId: number | string) => void | Promise<void>;
  toggleSnoozeDropdown: (loopId: number | string) => void;
}

const SURFACE_HASHES = {
  inbox: "#capture",
  next: "#do",
  chat: "#recall/chat",
  memory: "#recall/memory",
  rag: "#recall/rag",
} as const;

let rawText: HTMLTextAreaElement | null = null;
let queryFilter: HTMLInputElement | null = null;
let showCompletionNoteFn: KeyboardCallbacks["showCompletionNote"] | null = null;
let enrichLoopFn: KeyboardCallbacks["enrichLoop"] | null = null;
let refreshLoopFn: KeyboardCallbacks["refreshLoop"] | null = null;
let toggleTimerFn: KeyboardCallbacks["toggleTimer"] | null = null;
let toggleSnoozeDropdownFn: KeyboardCallbacks["toggleSnoozeDropdown"] | null = null;
let statusEl: HTMLElement | null = null;

let pendingGKey = false;
let gKeyTimeout: number | null = null;

export function init(elements: KeyboardModuleElements, callbacks: KeyboardCallbacks): void {
  rawText = elements.rawText;
  queryFilter = elements.queryFilter;
  statusEl = elements.status;
  showCompletionNoteFn = callbacks.showCompletionNote;
  enrichLoopFn = callbacks.enrichLoop;
  refreshLoopFn = callbacks.refreshLoop;
  toggleTimerFn = callbacks.toggleTimer;
  toggleSnoozeDropdownFn = callbacks.toggleSnoozeDropdown;

  document.addEventListener("keydown", handleKeyboardShortcuts);
}

function isInputFocused(): boolean {
  const active = document.activeElement;
  return active instanceof HTMLElement && (
    active.tagName === "INPUT"
    || active.tagName === "TEXTAREA"
    || active.tagName === "SELECT"
    || active.isContentEditable
  );
}

function getFirstVisibleLoopId(): string | null {
  const visibleMain = [
    document.getElementById("inbox-main"),
    document.getElementById("next-main"),
    document.getElementById("chat-main"),
    document.getElementById("memory-main"),
    document.getElementById("rag-main"),
    document.getElementById("review-main"),
  ].find((element) => element instanceof HTMLElement && element.style.display !== "none");

  if (!(visibleMain instanceof HTMLElement)) {
    return null;
  }
  return visibleMain.querySelector<HTMLElement>(".loop-card")?.dataset["loopId"] ?? null;
}

function navigateToSurface(
  surface: keyof typeof SURFACE_HASHES,
  options: { focusTarget?: HTMLElement | null; statusMessage?: string | null } = {},
): void {
  const hash = SURFACE_HASHES[surface];
  if (window.location.hash !== hash) {
    window.location.hash = hash;
  }

  window.setTimeout(() => {
    options.focusTarget?.focus();
    if (statusEl && options.statusMessage) {
      statusEl.textContent = options.statusMessage;
    }
  }, 0);
}

function handleKeyboardShortcuts(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a" && !isInputFocused()) {
    event.preventDefault();
    selectAllVisibleLoops();
    if (statusEl) {
      statusEl.textContent = `Selected ${selectedLoopIds.size} loops.`;
    }
    return;
  }

  if (event.ctrlKey || event.metaKey || event.altKey) {
    return;
  }

  if (event.key === "Escape") {
    if (isModalOpen() && closeActiveModal()) {
      event.preventDefault();
      return;
    }

    if (selectedLoopIds.size > 0) {
      clearLoopSelection();
      if (statusEl) {
        statusEl.textContent = "Selection cleared.";
      }
      event.preventDefault();
      return;
    }

    if (pendingGKey) {
      pendingGKey = false;
      if (gKeyTimeout) {
        window.clearTimeout(gKeyTimeout);
      }
      if (statusEl) {
        statusEl.textContent = "Ready.";
      }
    }
    return;
  }

  if (isInputFocused()) {
    return;
  }

  const key = event.key.toLowerCase();
  if (pendingGKey) {
    pendingGKey = false;
    if (gKeyTimeout) {
      window.clearTimeout(gKeyTimeout);
    }

    const gMappings: Record<string, { surface: keyof typeof SURFACE_HASHES; message: string }> = {
      i: { surface: "inbox", message: "Opened Capture" },
      n: { surface: "next", message: "Opened Do" },
      c: { surface: "chat", message: "Opened grounded chat" },
      e: { surface: "memory", message: "Opened memory" },
      r: { surface: "rag", message: "Opened documents" },
    };

    const mapping = gMappings[key];
    if (mapping) {
      navigateToSurface(mapping.surface, { statusMessage: mapping.message });
      event.preventDefault();
      return;
    }
  }

  if (key === "g") {
    pendingGKey = true;
    if (statusEl) {
      statusEl.textContent = "g pressed. Press i, n, c, e, or r...";
    }
    gKeyTimeout = window.setTimeout(() => {
      pendingGKey = false;
      if (statusEl) {
        statusEl.textContent = "Ready.";
      }
    }, 1500);
    event.preventDefault();
    return;
  }

  if (key === "?") {
    showHelpModal(true);
    event.preventDefault();
    return;
  }

  if (key === "n") {
    navigateToSurface("inbox", { focusTarget: rawText, statusMessage: "Type your loop..." });
    event.preventDefault();
    return;
  }

  if (key === "/") {
    navigateToSurface("inbox", { focusTarget: queryFilter, statusMessage: "Search loops..." });
    event.preventDefault();
    return;
  }

  const loopId = state.state.focusedLoopId ?? getFirstVisibleLoopId();
  if (!loopId) {
    return;
  }

  if (key === "c" && showCompletionNoteFn) {
    showCompletionNoteFn(loopId);
    if (statusEl) {
      statusEl.textContent = "Complete loop (add note or press Enter)";
    }
    event.preventDefault();
    return;
  }
  if (key === "e" && enrichLoopFn) {
    void enrichLoopFn(loopId);
    event.preventDefault();
    return;
  }
  if (key === "r" && refreshLoopFn) {
    void refreshLoopFn(loopId);
    if (statusEl) {
      statusEl.textContent = "Loop refreshed.";
    }
    event.preventDefault();
    return;
  }
  if (key === "t" && toggleTimerFn) {
    void toggleTimerFn(loopId);
    event.preventDefault();
    return;
  }
  if (key === "s" && toggleSnoozeDropdownFn) {
    toggleSnoozeDropdownFn(loopId);
    event.preventDefault();
  }
}

export function setupRangeSelection(container: HTMLElement): void {
  container.addEventListener("click", (event: MouseEvent) => {
    if (closestFromEventTarget(event.target, ".loop-checkbox")) {
      return;
    }

    if (event.shiftKey && state.state.lastClickedLoopId !== null) {
      const card = closestFromEventTarget<HTMLElement>(event.target, ".loop-card");
      const currentLoopId = Number.parseInt(card?.dataset["loopId"] ?? "", 10);
      if (Number.isInteger(currentLoopId) && currentLoopId !== state.state.lastClickedLoopId) {
        selectLoopRange(state.state.lastClickedLoopId, currentLoopId);
        event.preventDefault();
      }
    }
  });
}
