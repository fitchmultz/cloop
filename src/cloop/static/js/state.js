/**
 * state.js - Application state management
 *
 * Purpose:
 *   Centralize application state to enable module communication and UI consistency.
 *
 * Responsibilities:
 *   - Global state object with reactive updates
 *   - Persisted chat thread and chat preferences
 *   - Selected loops tracking for bulk operations
 *   - Timer state management
 *   - Review mode state
 *
 * Non-scope:
 *   - API calls (see api.js)
 *   - DOM rendering (see render.js)
 *   - Event handling (see individual modules)
 */

const DEFAULT_CHAT_PREFERENCES = Object.freeze({
  toolMode: null,
  includeLoopContext: true,
  includeMemoryContext: true,
  includeRagContext: false,
  memoryLimit: 10,
  ragK: 5,
  ragScope: "",
});

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
  chatPreferences: { ...DEFAULT_CHAT_PREFERENCES },
  lastClickedLoopId: null,
  focusedLoopId: null,
  notificationPermissionRequested: false,
};

const CLIENT_STATE_STORAGE_KEY = "cloop.clientState.v3";

function canUseLocalStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function normalizeToolCalls(toolCalls) {
  if (!Array.isArray(toolCalls)) {
    return [];
  }

  return toolCalls
    .filter((toolCall) => toolCall && typeof toolCall.name === "string")
    .map((toolCall) => ({
      name: toolCall.name,
      arguments: toolCall.arguments && typeof toolCall.arguments === "object" ? toolCall.arguments : {},
    }));
}

function normalizeSources(sources) {
  if (!Array.isArray(sources)) {
    return [];
  }

  return sources
    .filter((source) => source && typeof source === "object")
    .map((source) => ({
      id: source.id ?? null,
      document_path: typeof source.document_path === "string" ? source.document_path : null,
      chunk_index: Number.isInteger(source.chunk_index) ? source.chunk_index : null,
      score: typeof source.score === "number" ? source.score : null,
    }));
}

function normalizeMetadata(metadata) {
  if (!metadata || typeof metadata !== "object") {
    return null;
  }

  return {
    model: typeof metadata.model === "string" ? metadata.model : null,
    provider: typeof metadata.provider === "string" ? metadata.provider : null,
    api: typeof metadata.api === "string" ? metadata.api : null,
    latency_ms: typeof metadata.latency_ms === "number" ? metadata.latency_ms : null,
    stop_reason: typeof metadata.stop_reason === "string" ? metadata.stop_reason : null,
    usage: metadata.usage && typeof metadata.usage === "object" ? metadata.usage : {},
  };
}

function normalizeOptions(options) {
  if (!options || typeof options !== "object") {
    return null;
  }

  return {
    tool_mode: typeof options.tool_mode === "string" ? options.tool_mode : null,
    include_loop_context: Boolean(options.include_loop_context),
    include_memory_context: Boolean(options.include_memory_context),
    include_rag_context: Boolean(options.include_rag_context),
    memory_limit: Number.isInteger(options.memory_limit) ? options.memory_limit : null,
    rag_k: Number.isInteger(options.rag_k) ? options.rag_k : null,
    rag_scope: typeof options.rag_scope === "string" ? options.rag_scope : null,
  };
}

function normalizeContext(context) {
  if (!context || typeof context !== "object") {
    return null;
  }

  return {
    loop_context_applied: Boolean(context.loop_context_applied),
    memory_context_applied: Boolean(context.memory_context_applied),
    memory_entries_used: Number.isInteger(context.memory_entries_used) ? context.memory_entries_used : 0,
    rag_context_applied: Boolean(context.rag_context_applied),
    rag_chunks_used: Number.isInteger(context.rag_chunks_used) ? context.rag_chunks_used : 0,
  };
}

function normalizeChatMessage(message, index = 0) {
  if (!message || typeof message.role !== "string" || typeof message.content !== "string") {
    return null;
  }

  return {
    id: typeof message.id === "string" ? message.id : `chat-${index}-${Date.now()}`,
    role: message.role,
    content: message.content,
    createdAt: typeof message.createdAt === "string" ? message.createdAt : new Date().toISOString(),
    status: typeof message.status === "string" ? message.status : "done",
    model: typeof message.model === "string" ? message.model : null,
    metadata: normalizeMetadata(message.metadata),
    options: normalizeOptions(message.options),
    context: normalizeContext(message.context),
    toolCalls: normalizeToolCalls(message.toolCalls || message.tool_calls),
    toolResult: message.toolResult && typeof message.toolResult === "object"
      ? message.toolResult
      : message.tool_result && typeof message.tool_result === "object"
        ? message.tool_result
        : null,
    sources: normalizeSources(message.sources),
    error: typeof message.error === "string" ? message.error : null,
  };
}

function normalizeChatMessages(messages) {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages
    .map((message, index) => normalizeChatMessage(message, index))
    .filter(Boolean);
}

function normalizeChatPreferences(preferences) {
  if (!preferences || typeof preferences !== "object") {
    return { ...DEFAULT_CHAT_PREFERENCES };
  }

  const toolMode = typeof preferences.toolMode === "string" && preferences.toolMode.trim()
    ? preferences.toolMode
    : null;
  const ragScope = typeof preferences.ragScope === "string" ? preferences.ragScope : "";

  return {
    toolMode,
    includeLoopContext: preferences.includeLoopContext ?? DEFAULT_CHAT_PREFERENCES.includeLoopContext,
    includeMemoryContext: preferences.includeMemoryContext ?? DEFAULT_CHAT_PREFERENCES.includeMemoryContext,
    includeRagContext: preferences.includeRagContext ?? DEFAULT_CHAT_PREFERENCES.includeRagContext,
    memoryLimit: Number.isInteger(preferences.memoryLimit) ? preferences.memoryLimit : DEFAULT_CHAT_PREFERENCES.memoryLimit,
    ragK: Number.isInteger(preferences.ragK) ? preferences.ragK : DEFAULT_CHAT_PREFERENCES.ragK,
    ragScope,
  };
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
    state.chatPreferences = normalizeChatPreferences(persisted.chatPreferences);
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
      chatPreferences: state.chatPreferences,
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
  const normalized = normalizeChatMessage(message, state.chatMessages.length);
  if (!normalized) {
    return;
  }
  state.chatMessages.push(normalized);
  persistStateToStorage();
}

export function updateLastChatMessage(fields) {
  const lastMessage = state.chatMessages.at(-1);
  if (!lastMessage) {
    return;
  }
  Object.assign(lastMessage, normalizeChatMessage({ ...lastMessage, ...fields }, state.chatMessages.length - 1));
  persistStateToStorage();
}

export function clearChatMessages() {
  state.chatMessages = [];
  persistStateToStorage();
}

export function updateChatPreferences(updates) {
  state.chatPreferences = normalizeChatPreferences({ ...state.chatPreferences, ...updates });
  persistStateToStorage();
}

export function getChatPreferences() {
  return { ...state.chatPreferences };
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
