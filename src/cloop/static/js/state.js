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

const CLIENT_STATE_STORAGE_KEY = "cloop.clientState.v2";

function canUseLocalStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function normalizeChatMessages(messages) {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages
    .filter((message) => message && typeof message.role === "string" && typeof message.content === "string")
    .map((message, index) => ({
      id: typeof message.id === "string" ? message.id : `chat-${index}-${Date.now()}`,
      role: message.role,
      content: message.content,
      createdAt: typeof message.createdAt === "string" ? message.createdAt : new Date().toISOString(),
    }));
}

export function hydrateStateFromStorage() {
  if (!canUseLocalStorage()) {
    return;
  }

  try {
    const raw = window.localStorage.getItem(CLIENT_STATE_STORAGE_KEY);
    if (!raw) {
      return;
    }

    const persisted = JSON.parse(raw);
    if (typeof persisted.activeTab === "string") {
      state.activeTab = persisted.activeTab;
    }
    state.chatMessages = normalizeChatMessages(persisted.chatMessages);
  } catch {
    // Ignore malformed persisted state and continue with in-memory defaults.
  }
}

export function persistStateToStorage() {
  if (!canUseLocalStorage()) {
    return;
  }

  try {
    window.localStorage.setItem(CLIENT_STATE_STORAGE_KEY, JSON.stringify({
      activeTab: state.activeTab,
      chatMessages: state.chatMessages,
    }));
  } catch {
    // Ignore storage failures and preserve the current in-memory session.
  }
}

// ========================================
// Bulk Selection State
// ========================================

export const selectedLoopIds = new Set();

export function updateState(updates) {
  Object.assign(state, updates);
  persistStateToStorage();
}

export function replaceChatMessages(messages) {
  state.chatMessages = normalizeChatMessages(messages);
  persistStateToStorage();
}

export function appendChatMessage(message) {
  state.chatMessages.push({
    id: typeof message.id === "string" ? message.id : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role: message.role,
    content: message.content,
    createdAt: typeof message.createdAt === "string" ? message.createdAt : new Date().toISOString(),
  });
  persistStateToStorage();
}

export function updateLastChatMessage(fields) {
  const lastMessage = state.chatMessages.at(-1);
  if (!lastMessage) {
    return;
  }
  Object.assign(lastMessage, fields);
  persistStateToStorage();
}

export function clearChatMessages() {
  state.chatMessages = [];
  persistStateToStorage();
}

export function getChatThreadState() {
  const messageCount = Array.isArray(state.chatMessages) ? state.chatMessages.length : 0;
  const lastMessage = messageCount > 0 ? state.chatMessages.at(-1) : null;

  return {
    hasSavedThread: messageCount > 0,
    messageCount,
    lastUpdatedAt: typeof lastMessage?.createdAt === "string" ? lastMessage.createdAt : null,
  };
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
