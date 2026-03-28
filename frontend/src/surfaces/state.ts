/**
 * state.ts - Surface runtime state plus shared selection-state re-exports.
 *
 * Purpose:
 *   Hold the remaining browser-local state for the capture/do/recall runtime
 *   while sharing the TypeScript-owned loop-selection state implementation.
 *
 * Responsibilities:
 *   - Persist and hydrate surface-local browser state.
 *   - Normalize chat thread payloads read from local storage.
 *   - Track active loop timers in the browser.
 *   - Re-export selection helpers used across work surfaces.
 *
 * Scope:
 *   - Surface runtime browser state only.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/* modules.
 *
 * Invariants/Assumptions:
 *   - frontend/src/selection-state.ts remains the source of truth for selected
 *     loop IDs.
 *   - Persisted chat/thread state may be malformed and must be normalized.
 */

import type {
  ChatContext,
  ChatMessage,
  ChatMetadata,
  ChatPreferences,
  ChatSource,
  ChatToolCall,
} from "../contracts-ui";
import {
  clearLoopSelection,
  getVisibleLoopIds,
  LOOP_SELECTION_CHANGED_EVENT,
  selectedLoopIds,
  selectAllVisibleLoops,
  selectLoopRange,
  toggleLoopSelection,
} from "../selection-state";
import type { ActiveTimerRecord, LegacySurfaceState, LegacySurfaceTab } from "./contracts";

const DEFAULT_CHAT_PREFERENCES: Readonly<ChatPreferences> = Object.freeze({
  toolMode: null,
  includeLoopContext: true,
  includeMemoryContext: true,
  includeRagContext: false,
  memoryLimit: 10,
  ragK: 5,
  ragScope: "",
});

export const state: LegacySurfaceState = {
  loops: [],
  activeTab: "inbox",
  templatesCache: null,
  reviewMode: "daily",
  reviewData: null,
  relationshipReviewQueue: null,
  reviewPlanningSessions: [],
  reviewPlanningSessionSnapshot: null,
  reviewPlanningSessionId: null,
  reviewRelationshipActions: [],
  reviewRelationshipSessions: [],
  reviewRelationshipSessionSnapshot: null,
  reviewRelationshipSessionId: null,
  reviewRelationshipActionId: null,
  reviewEnrichmentActions: [],
  reviewEnrichmentSessions: [],
  reviewEnrichmentSessionSnapshot: null,
  reviewEnrichmentSessionId: null,
  reviewEnrichmentActionId: null,
  reviewBulkEnrichmentPreview: null,
  reviewBulkEnrichmentResult: null,
  chatMessages: [],
  chatPreferences: { ...DEFAULT_CHAT_PREFERENCES },
  lastClickedLoopId: null,
  focusedLoopId: null,
  notificationPermissionRequested: false,
};

const CLIENT_STATE_STORAGE_KEY = "cloop.clientState.v3";
const LEGACY_SURFACE_TABS = new Set<LegacySurfaceTab>(["inbox", "next", "chat", "memory", "rag"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function canUseLocalStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function normalizeLegacyTab(tab: unknown): LegacySurfaceTab {
  return typeof tab === "string" && LEGACY_SURFACE_TABS.has(tab as LegacySurfaceTab)
    ? (tab as LegacySurfaceTab)
    : "inbox";
}

function normalizeToolCalls(toolCalls: unknown): ChatToolCall[] {
  if (!Array.isArray(toolCalls)) {
    return [];
  }

  return toolCalls.flatMap((toolCall) => {
    if (!isRecord(toolCall) || typeof toolCall["name"] !== "string") {
      return [];
    }
    return [{
      name: toolCall["name"],
      arguments: isRecord(toolCall["arguments"]) ? toolCall["arguments"] : {},
    }];
  });
}

function normalizeToolResults(toolResults: unknown): Record<string, unknown>[] {
  if (!Array.isArray(toolResults)) {
    return [];
  }
  return toolResults.flatMap((toolResult) => (isRecord(toolResult) ? [toolResult] : []));
}

function normalizeSources(sources: unknown): ChatSource[] {
  if (!Array.isArray(sources)) {
    return [];
  }

  return sources.flatMap((source) => {
    if (!isRecord(source)) {
      return [];
    }
    return [{
      id: typeof source["id"] === "string" || typeof source["id"] === "number" ? source["id"] : null,
      document_path: typeof source["document_path"] === "string" ? source["document_path"] : null,
      chunk_index: Number.isInteger(source["chunk_index"]) ? (source["chunk_index"] as number) : null,
      score: typeof source["score"] === "number" ? source["score"] : null,
    }];
  });
}

function normalizeMetadata(metadata: unknown): ChatMetadata | null {
  if (!isRecord(metadata)) {
    return null;
  }

  return {
    model: typeof metadata["model"] === "string" ? metadata["model"] : null,
    provider: typeof metadata["provider"] === "string" ? metadata["provider"] : null,
    api: typeof metadata["api"] === "string" ? metadata["api"] : null,
    latency_ms: typeof metadata["latency_ms"] === "number" ? metadata["latency_ms"] : null,
    stop_reason: typeof metadata["stop_reason"] === "string" ? metadata["stop_reason"] : null,
    usage: isRecord(metadata["usage"]) ? metadata["usage"] : {},
  };
}

function normalizeOptions(options: unknown): Record<string, unknown> | null {
  if (!isRecord(options)) {
    return null;
  }

  return {
    tool_mode: typeof options["tool_mode"] === "string" ? options["tool_mode"] : null,
    include_loop_context: Boolean(options["include_loop_context"]),
    include_memory_context: Boolean(options["include_memory_context"]),
    include_rag_context: Boolean(options["include_rag_context"]),
    memory_limit: Number.isInteger(options["memory_limit"]) ? options["memory_limit"] : null,
    rag_k: Number.isInteger(options["rag_k"]) ? options["rag_k"] : null,
    rag_scope: typeof options["rag_scope"] === "string" ? options["rag_scope"] : null,
  };
}

function normalizeContext(context: unknown): ChatContext | null {
  if (!isRecord(context)) {
    return null;
  }

  return {
    loop_context_applied: Boolean(context["loop_context_applied"]),
    memory_context_applied: Boolean(context["memory_context_applied"]),
    memory_entries_used: Number.isInteger(context["memory_entries_used"]) ? context["memory_entries_used"] as number : 0,
    rag_context_applied: Boolean(context["rag_context_applied"]),
    rag_chunks_used: Number.isInteger(context["rag_chunks_used"]) ? context["rag_chunks_used"] as number : 0,
  };
}

function normalizeRerunAction(message: unknown): ChatMessage["rerunAction"] {
  if (!isRecord(message) || typeof message["label"] !== "string" || typeof message["description"] !== "string") {
    return null;
  }
  return message as unknown as ChatMessage["rerunAction"];
}

function normalizeChatMessage(message: unknown, index = 0): ChatMessage | null {
  if (!isRecord(message) || typeof message["role"] !== "string" || typeof message["content"] !== "string") {
    return null;
  }

  return {
    id: typeof message["id"] === "string" ? message["id"] : `chat-${index}-${Date.now()}`,
    role: message["role"],
    content: message["content"],
    createdAt: typeof message["createdAt"] === "string" ? message["createdAt"] : new Date().toISOString(),
    status: typeof message["status"] === "string" ? message["status"] : "done",
    model: typeof message["model"] === "string" ? message["model"] : null,
    metadata: normalizeMetadata(message["metadata"]),
    options: normalizeOptions(message["options"]),
    context: normalizeContext(message["context"]),
    toolCalls: normalizeToolCalls(message["toolCalls"] ?? message["tool_calls"]),
    toolResults: normalizeToolResults(message["toolResults"] ?? message["tool_results"]),
    sources: normalizeSources(message["sources"]),
    rerunAction: normalizeRerunAction(message["rerunAction"]),
    error: typeof message["error"] === "string" ? message["error"] : null,
  };
}

function normalizeChatMessages(messages: unknown): ChatMessage[] {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages.flatMap((message, index) => {
    const normalized = normalizeChatMessage(message, index);
    return normalized ? [normalized] : [];
  });
}

function normalizeChatPreferences(preferences: unknown): ChatPreferences {
  if (!isRecord(preferences)) {
    return { ...DEFAULT_CHAT_PREFERENCES };
  }

  const rawToolMode = typeof preferences["toolMode"] === "string" && preferences["toolMode"].trim()
    ? preferences["toolMode"]
    : null;
  const toolMode = rawToolMode === "llm" || rawToolMode === "none" ? rawToolMode : null;
  const ragScope = typeof preferences["ragScope"] === "string" ? preferences["ragScope"] : "";

  return {
    toolMode,
    includeLoopContext: typeof preferences["includeLoopContext"] === "boolean"
      ? preferences["includeLoopContext"]
      : DEFAULT_CHAT_PREFERENCES.includeLoopContext,
    includeMemoryContext: typeof preferences["includeMemoryContext"] === "boolean"
      ? preferences["includeMemoryContext"]
      : DEFAULT_CHAT_PREFERENCES.includeMemoryContext,
    includeRagContext: typeof preferences["includeRagContext"] === "boolean"
      ? preferences["includeRagContext"]
      : DEFAULT_CHAT_PREFERENCES.includeRagContext,
    memoryLimit: Number.isInteger(preferences["memoryLimit"])
      ? preferences["memoryLimit"] as number
      : DEFAULT_CHAT_PREFERENCES.memoryLimit,
    ragK: Number.isInteger(preferences["ragK"])
      ? preferences["ragK"] as number
      : DEFAULT_CHAT_PREFERENCES.ragK,
    ragScope,
  };
}

export function hydrateStateFromStorage(): void {
  if (!canUseLocalStorage()) {
    return;
  }

  try {
    const raw = window.localStorage.getItem(CLIENT_STATE_STORAGE_KEY);
    if (!raw) {
      return;
    }

    const persisted: unknown = JSON.parse(raw);
    if (!isRecord(persisted)) {
      return;
    }

    state.activeTab = normalizeLegacyTab(persisted["activeTab"]);
    if (typeof persisted["reviewMode"] === "string") {
      state.reviewMode = persisted["reviewMode"] as LegacySurfaceState["reviewMode"];
    }
    state.chatMessages = normalizeChatMessages(persisted["chatMessages"]);
    state.chatPreferences = normalizeChatPreferences(persisted["chatPreferences"]);
    state.reviewPlanningSessionId = Number.isInteger(persisted["reviewPlanningSessionId"])
      ? persisted["reviewPlanningSessionId"] as number
      : null;
    state.reviewRelationshipSessionId = Number.isInteger(persisted["reviewRelationshipSessionId"])
      ? persisted["reviewRelationshipSessionId"] as number
      : null;
    state.reviewRelationshipActionId = Number.isInteger(persisted["reviewRelationshipActionId"])
      ? persisted["reviewRelationshipActionId"] as number
      : null;
    state.reviewEnrichmentSessionId = Number.isInteger(persisted["reviewEnrichmentSessionId"])
      ? persisted["reviewEnrichmentSessionId"] as number
      : null;
    state.reviewEnrichmentActionId = Number.isInteger(persisted["reviewEnrichmentActionId"])
      ? persisted["reviewEnrichmentActionId"] as number
      : null;
  } catch {
    // Ignore malformed persisted state and continue with in-memory defaults.
  }
}

export function persistStateToStorage(): void {
  if (!canUseLocalStorage()) {
    return;
  }

  try {
    window.localStorage.setItem(CLIENT_STATE_STORAGE_KEY, JSON.stringify({
      activeTab: state.activeTab,
      reviewMode: state.reviewMode,
      reviewPlanningSessionId: state.reviewPlanningSessionId,
      reviewRelationshipSessionId: state.reviewRelationshipSessionId,
      reviewRelationshipActionId: state.reviewRelationshipActionId,
      reviewEnrichmentSessionId: state.reviewEnrichmentSessionId,
      reviewEnrichmentActionId: state.reviewEnrichmentActionId,
      chatMessages: state.chatMessages,
      chatPreferences: state.chatPreferences,
    }));
  } catch {
    // Ignore storage failures and preserve the current in-memory session.
  }
}

export function updateState(updates: Partial<LegacySurfaceState>): void {
  const normalizedUpdates: Partial<LegacySurfaceState> = { ...updates };
  if (Object.hasOwn(normalizedUpdates, "activeTab")) {
    normalizedUpdates.activeTab = normalizeLegacyTab(normalizedUpdates.activeTab);
  }
  Object.assign(state, normalizedUpdates);
  persistStateToStorage();
}

export function replaceChatMessages(messages: unknown): void {
  state.chatMessages = normalizeChatMessages(messages);
  persistStateToStorage();
}

export function appendChatMessage(message: unknown): void {
  const normalized = normalizeChatMessage(message, state.chatMessages.length);
  if (!normalized) {
    return;
  }
  state.chatMessages.push(normalized);
  persistStateToStorage();
}

export function updateLastChatMessage(fields: Record<string, unknown>): void {
  const lastMessage = state.chatMessages.at(-1);
  if (!lastMessage) {
    return;
  }
  const merged = normalizeChatMessage({ ...lastMessage, ...fields }, state.chatMessages.length - 1);
  if (!merged) {
    return;
  }
  Object.assign(lastMessage, merged);
  persistStateToStorage();
}

export function clearChatMessages(): void {
  state.chatMessages = [];
  persistStateToStorage();
}

export function updateChatPreferences(updates: Partial<ChatPreferences>): void {
  state.chatPreferences = normalizeChatPreferences({ ...state.chatPreferences, ...updates });
  persistStateToStorage();
}

export function getChatPreferences(): ChatPreferences {
  return { ...state.chatPreferences };
}

export function getChatThreadState(): {
  hasSavedThread: boolean;
  messageCount: number;
  lastUpdatedAt: string | null;
} {
  const messageCount = Array.isArray(state.chatMessages) ? state.chatMessages.length : 0;
  const lastMessage = messageCount > 0 ? state.chatMessages.at(-1) ?? null : null;

  return {
    hasSavedThread: messageCount > 0,
    messageCount,
    lastUpdatedAt: typeof lastMessage?.createdAt === "string" ? lastMessage.createdAt : null,
  };
}

export const activeTimers = new Map<number, ActiveTimerRecord>();

export function addActiveTimer(loopId: number, timerData: ActiveTimerRecord): void {
  activeTimers.set(loopId, timerData);
}

export function removeActiveTimer(loopId: number): ActiveTimerRecord | null {
  const timer = activeTimers.get(loopId);
  if (timer) {
    clearInterval(timer.interval_id);
    activeTimers.delete(loopId);
    return timer;
  }
  return null;
}

export function getActiveTimer(loopId: number): ActiveTimerRecord | undefined {
  return activeTimers.get(loopId);
}

export function clearAllTimers(): void {
  activeTimers.forEach((timer) => {
    clearInterval(timer.interval_id);
  });
  activeTimers.clear();
}

export {
  clearLoopSelection,
  getVisibleLoopIds,
  LOOP_SELECTION_CHANGED_EVENT,
  selectedLoopIds,
  selectAllVisibleLoops,
  selectLoopRange,
  toggleLoopSelection,
};
