/**
 * state.js - Application state management
 *
 * Purpose:
 *   Centralize application state to enable module communication and UI consistency.
 *
 * Responsibilities:
 *   - Global state object with reactive updates
 *   - Selected loops tracking for bulk operations
 *   - Timer state management
 *   - Review mode state
 *   - Pending bulk actions
 *
 * Non-scope:
 *   - API calls (see api.js)
 *   - DOM rendering (see render.js)
 *   - Event handling (see individual modules)
 */

// ========================================
// Global Application State
// ========================================

export const state = {
  loops: [],
  activeTab: 'inbox',
  templatesCache: null,
  reviewMode: 'daily',
  reviewData: null,
  chatMessages: [],
  pendingBulkAction: null,
  lastClickedLoopId: null,
  focusedLoopId: null,
  notificationPermissionRequested: false,
};

// ========================================
// Bulk Selection State
// ========================================

export const selectedLoopIds = new Set();

export function updateState(updates) {
  Object.assign(state, updates);
}

export function toggleLoopSelection(loopId, isSelected) {
  if (isSelected) {
    selectedLoopIds.add(loopId);
  } else {
    selectedLoopIds.delete(loopId);
  }
}

export function clearLoopSelection() {
  selectedLoopIds.clear();
  state.lastClickedLoopId = null;
}

export function selectAllVisibleLoops() {
  document.querySelectorAll(".loop-card").forEach((card) => {
    const loopId = parseInt(card.dataset.loopId, 10);
    if (!Number.isNaN(loopId)) {
      selectedLoopIds.add(loopId);
    }
  });
}

export function getVisibleLoopIds() {
  return Array.from(document.querySelectorAll(".loop-card"))
    .map((card) => parseInt(card.dataset.loopId, 10))
    .filter((id) => !Number.isNaN(id));
}

export function selectLoopRange(fromId, toId) {
  const visibleIds = getVisibleLoopIds();
  const fromIndex = visibleIds.indexOf(fromId);
  const toIndex = visibleIds.indexOf(toId);

  if (fromIndex === -1 || toIndex === -1) return;

  const start = Math.min(fromIndex, toIndex);
  const end = Math.max(fromIndex, toIndex);

  for (let i = start; i <= end; i++) {
    selectedLoopIds.add(visibleIds[i]);
  }
}

// ========================================
// Timer State
// ========================================

export const activeTimers = new Map(); // loop_id -> { session_id, started_at, interval_id }

export function addActiveTimer(loopId, timerData) {
  activeTimers.set(loopId, timerData);
}

export function removeActiveTimer(loopId) {
  const timer = activeTimers.get(loopId);
  if (timer) {
    clearInterval(timer.interval_id);
    activeTimers.delete(loopId);
    return timer;
  }
  return null;
}

export function getActiveTimer(loopId) {
  return activeTimers.get(loopId);
}

export function clearAllTimers() {
  activeTimers.forEach((timer) => {
    clearInterval(timer.interval_id);
  });
  activeTimers.clear();
}

// ========================================
// Pending Bulk Actions
// ========================================

export function setPendingBulkAction(action) {
  state.pendingBulkAction = action;
}

export function getPendingBulkAction() {
  return state.pendingBulkAction;
}

export function clearPendingBulkAction() {
  state.pendingBulkAction = null;
}
