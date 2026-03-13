/**
 * keyboard.js - Keyboard shortcuts
 *
 * Purpose:
 *   Provide keyboard navigation and actions for power users.
 *
 * Responsibilities:
 *   - Global keyboard shortcuts
 *   - G-key sequences (g i, g n, etc.)
 *   - Tab switching (1-6)
 *   - Loop actions (c, e, r, t, s)
 *   - Bulk selection shortcuts
 *   - Help modal trigger
 *
 * Non-scope:
 *   - Modal handling (see modals.js)
 *   - Tab switching logic (see init.js)
 *   - Individual actions (see respective modules)
 */

import * as state from './state.js';
import { selectedLoopIds, clearLoopSelection, selectAllVisibleLoops } from './state.js';
import { showHelpModal, isModalOpen, closeActiveModal } from './modals.js';

let rawText, queryFilter;
let switchTabFn;
let showCompletionNoteFn, enrichLoopFn, refreshLoopFn, toggleTimerFn, toggleSnoozeDropdownFn;
let statusEl;

let pendingGKey = false;
let gKeyTimeout = null;

/**
 * Initialize keyboard module
 */
export function init(elements, callbacks) {
  rawText = elements.rawText;
  queryFilter = elements.queryFilter;
  statusEl = elements.status;
  switchTabFn = callbacks.switchTab;
  showCompletionNoteFn = callbacks.showCompletionNote;
  enrichLoopFn = callbacks.enrichLoop;
  refreshLoopFn = callbacks.refreshLoop;
  toggleTimerFn = callbacks.toggleTimer;
  toggleSnoozeDropdownFn = callbacks.toggleSnoozeDropdown;

  document.addEventListener("keydown", handleKeyboardShortcuts);
}

/**
 * Check if an input element is focused
 */
function isInputFocused() {
  const active = document.activeElement;
  return active && (
    active.tagName === "INPUT" ||
    active.tagName === "TEXTAREA" ||
    active.tagName === "SELECT" ||
    active.isContentEditable
  );
}

/**
 * Get the first visible loop ID
 */
function getFirstVisibleLoopId() {
  const visibleMain = [
    document.getElementById("inbox-main"),
    document.getElementById("next-main"),
    document.getElementById("chat-main"),
    document.getElementById("rag-main"),
    document.getElementById("review-main")
  ].find(el => el && el.style.display !== "none");

  if (!visibleMain) return null;
  const firstCard = visibleMain.querySelector(".loop-card");
  return firstCard?.dataset?.loopId || null;
}

/**
 * Handle keyboard shortcuts
 */
function handleKeyboardShortcuts(event) {
  // Handle Ctrl+A for select all
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
    if (!isInputFocused()) {
      event.preventDefault();
      selectAllVisibleLoops();
      if (statusEl) {
        statusEl.textContent = `Selected ${selectedLoopIds.size} loops.`;
      }
      return;
    }
  }

  // Ignore shortcuts if modifier keys are pressed
  if (event.ctrlKey || event.metaKey || event.altKey) {
    return;
  }

  // Handle Escape key
  if (event.key === "Escape") {
    if (isModalOpen() && closeActiveModal()) {
      event.preventDefault();
      return;
    }

    // If selection is active, clear it first
    if (selectedLoopIds.size > 0) {
      clearLoopSelection();
      if (statusEl) {
        statusEl.textContent = "Selection cleared.";
      }
      event.preventDefault();
      return;
    }

    // Clear pending g-key state
    if (pendingGKey) {
      pendingGKey = false;
      if (gKeyTimeout) clearTimeout(gKeyTimeout);
      if (statusEl) statusEl.textContent = "Ready.";
    }

    return;
  }

  // Don't process other shortcuts if typing in an input
  if (isInputFocused()) {
    return;
  }

  const key = event.key.toLowerCase();

  // Handle g-key sequences
  if (pendingGKey) {
    pendingGKey = false;
    if (gKeyTimeout) clearTimeout(gKeyTimeout);

    const gMappings = {
      "i": "inbox",
      "n": "next",
      "c": "chat",
      "r": "rag",
      "v": "review",
      "m": "metrics"
    };

    if (gMappings[key]) {
      switchTabFn(gMappings[key]);
      if (statusEl) statusEl.textContent = `Switched to ${gMappings[key]}`;
      event.preventDefault();
      return;
    }
  }

  // Start g-key sequence
  if (key === "g") {
    pendingGKey = true;
    if (statusEl) statusEl.textContent = "g pressed. Press i, n, c, r, v, or m...";
    gKeyTimeout = setTimeout(() => {
      pendingGKey = false;
      if (statusEl) statusEl.textContent = "Ready.";
    }, 1500);
    event.preventDefault();
    return;
  }

  // Direct tab switching with 1-6
  const tabNumbers = { "1": "inbox", "2": "next", "3": "chat", "4": "rag", "5": "review", "6": "metrics" };
  if (tabNumbers[key]) {
    switchTabFn(tabNumbers[key]);
    if (statusEl) statusEl.textContent = `Switched to ${tabNumbers[key]}`;
    event.preventDefault();
    return;
  }

  // Show help modal
  if (key === "?") {
    showHelpModal(true);
    event.preventDefault();
    return;
  }

  // Focus capture textarea
  if (key === "n") {
    switchTabFn("inbox");
    if (rawText) {
      rawText.focus();
      if (statusEl) statusEl.textContent = "Type your loop...";
    }
    event.preventDefault();
    return;
  }

  // Focus search/query
  if (key === "/") {
    switchTabFn("inbox");
    if (queryFilter) {
      queryFilter.focus();
      if (statusEl) statusEl.textContent = "Search loops...";
    }
    event.preventDefault();
    return;
  }

  // Loop actions (require a focused/first visible loop)
  const loopId = state.state.focusedLoopId || getFirstVisibleLoopId();
  if (loopId) {
    if (key === "c" && showCompletionNoteFn) {
      showCompletionNoteFn(loopId);
      if (statusEl) statusEl.textContent = "Complete loop (add note or press Enter)";
      event.preventDefault();
      return;
    }
    if (key === "e" && enrichLoopFn) {
      enrichLoopFn(loopId);
      event.preventDefault();
      return;
    }
    if (key === "r" && refreshLoopFn) {
      refreshLoopFn(loopId);
      if (statusEl) statusEl.textContent = "Loop refreshed.";
      event.preventDefault();
      return;
    }
    if (key === "t" && toggleTimerFn) {
      toggleTimerFn(loopId);
      event.preventDefault();
      return;
    }
    if (key === "s" && toggleSnoozeDropdownFn) {
      toggleSnoozeDropdownFn(loopId);
      event.preventDefault();
      return;
    }
  }
}

/**
 * Setup shift-click range selection
 */
export function setupRangeSelection(container) {
  container.addEventListener("click", (event) => {
    // Check if clicking on checkbox itself (handled by change event)
    if (event.target.closest(".loop-checkbox")) {
      return;
    }

    // Shift+click for range selection
    if (event.shiftKey && state.state.lastClickedLoopId !== null) {
      const card = event.target.closest(".loop-card");
      if (card) {
        const currentLoopId = parseInt(card.dataset.loopId, 10);
        if (!Number.isNaN(currentLoopId) && currentLoopId !== state.state.lastClickedLoopId) {
          selectLoopRange(state.state.lastClickedLoopId, currentLoopId);
          event.preventDefault();
        }
      }
    }
  });
}
