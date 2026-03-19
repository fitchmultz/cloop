/**
 * chat.ts - Recall grounded-chat surface.
 *
 * Purpose:
 *   Handle chat interface rendering, grounding controls, streaming responses,
 *   and local thread persistence for the recall chat surface.
 *
 * Responsibilities:
 *   - Send chat messages with configurable grounding/tool options.
 *   - Render saved chat bubbles with metadata, sources, and tool activity.
 *   - Persist chat controls and thread state through surface state.ts.
 *
 * Scope:
 *   - Recall chat UI only.
 *
 * Usage:
 *   - Imported by bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - Chat history persists locally in browser storage.
 *   - Streaming responses use SSE-style token/tool/done events.
 */

import type { ChatMessage, ChatPreferences } from "../contracts-ui";
import { parseHash } from "../shell-routing";
import { renderRecallActionCards, renderRecallResultActionCards } from "./recall-action-cards";
import * as api from "./api";
import * as state from "./state";
import type { SurfaceChatEventPayload } from "./contracts";
import { renderMarkdown } from "./markdown";
import { consumeJsonEventStream } from "./stream";
import { escapeHtml, messageFromError } from "./utils";

interface ChatModuleElements {
  chatActionCards?: HTMLElement | null;
  chatMessages: HTMLElement;
  chatInput: HTMLInputElement | HTMLTextAreaElement;
  chatForm: HTMLFormElement;
  chatResetButton?: HTMLButtonElement | null;
  chatThreadStatus?: HTMLElement | null;
  chatToolMode?: HTMLSelectElement | null;
  chatLoopContext?: HTMLInputElement | null;
  chatMemoryContext?: HTMLInputElement | null;
  chatMemoryLimit?: HTMLInputElement | null;
  chatRagContext?: HTMLInputElement | null;
  chatRagK?: HTMLInputElement | null;
  chatRagScope?: HTMLInputElement | null;
  chatControlsStatus?: HTMLElement | null;
  chatRuntimeStatus?: HTMLElement | null;
}

let chatActionCardsEl: HTMLElement | null = null;
let chatMessagesEl: HTMLElement | null = null;
let chatInput: HTMLInputElement | HTMLTextAreaElement | null = null;
let chatComposerEl: HTMLFormElement | null = null;
let chatResetButtonEl: HTMLButtonElement | null = null;
let chatThreadStatusEl: HTMLElement | null = null;
let chatToolModeEl: HTMLSelectElement | null = null;
let chatLoopContextEl: HTMLInputElement | null = null;
let chatMemoryContextEl: HTMLInputElement | null = null;
let chatMemoryLimitEl: HTMLInputElement | null = null;
let chatRagContextEl: HTMLInputElement | null = null;
let chatRagKEl: HTMLInputElement | null = null;
let chatRagScopeEl: HTMLInputElement | null = null;
let chatControlsStatusEl: HTMLElement | null = null;
let chatRuntimeStatusEl: HTMLElement | null = null;
let chatIsBusy = false;

function getEmptyThreadCopy(): { title: string; body: string; status: string } {
  return {
    title: "No saved thread in this browser yet.",
    body: "Send your first message to save this conversation across reloads. Ask about your actual work, then tune the grounding controls if you want loops, memory, or document context to shape the answer.",
    status: "No saved thread yet. Send a message to keep this conversation across reloads.",
  };
}

function scrollConversationToBottom(): void {
  requestAnimationFrame(() => {
    chatMessagesEl?.lastElementChild?.scrollIntoView({ block: "end", behavior: "auto" });
  });
}

function renderPlaceholder(): void {
  if (!chatMessagesEl) {
    return;
  }
  const emptyCopy = getEmptyThreadCopy();
  chatMessagesEl.innerHTML = `
    <div class="chat-placeholder">
      <strong class="chat-placeholder-title">${emptyCopy.title}</strong>
      <p class="chat-placeholder-body">${emptyCopy.body}</p>
    </div>
  `;
}

function getToolModeLabel(toolMode: string | null | undefined): string {
  switch (toolMode) {
    case "llm":
      return "Tools on";
    case "manual":
      return "Manual tools";
    case "none":
      return "Tools off";
    default:
      return "Backend default";
  }
}

function describeGrounding(options: Record<string, unknown> | null): string {
  if (!options) {
    return "No explicit grounding settings recorded.";
  }

  const parts: string[] = [];
  if (options["include_loop_context"]) {
    parts.push("loops");
  }
  if (options["include_memory_context"]) {
    const memoryLimit = options["memory_limit"];
    parts.push(`memory${typeof memoryLimit === "number" ? ` (${memoryLimit})` : ""}`);
  }
  if (options["include_rag_context"]) {
    const ragK = typeof options["rag_k"] === "number" ? options["rag_k"] : 0;
    const ragScope = typeof options["rag_scope"] === "string" && options["rag_scope"]
      ? ` scoped to ${options["rag_scope"]}`
      : "";
    parts.push(`docs (${ragK})${ragScope}`);
  }

  return parts.length > 0 ? `Grounded in ${parts.join(" · ")}.` : "No extra grounding enabled.";
}

function renderSources(sources: ChatMessage["sources"]): string {
  if (!Array.isArray(sources) || sources.length === 0) {
    return "";
  }

  return `
    <details class="chat-message-details">
      <summary>Sources (${sources.length})</summary>
      <div class="chat-message-detail-list">
        ${sources.map((source) => `
          <div class="chat-inline-source">
            <div class="chat-inline-source-path">${escapeHtml(source.document_path || "Unknown source")}</div>
            <div class="chat-inline-source-meta">
              Chunk ${source.chunk_index ?? "?"}${typeof source.score === "number" ? ` · Score ${source.score.toFixed(3)}` : ""}
            </div>
          </div>
        `).join("")}
      </div>
    </details>
  `;
}

function renderToolCalls(toolCalls: ChatMessage["toolCalls"], toolResult: ChatMessage["toolResult"]): string {
  if ((!Array.isArray(toolCalls) || toolCalls.length === 0) && !toolResult) {
    return "";
  }

  const callsMarkup = Array.isArray(toolCalls) && toolCalls.length > 0
    ? toolCalls.map((toolCall) => `
        <div class="chat-tool-call-item">
          <div class="chat-tool-call-name">${escapeHtml(toolCall.name || "tool")}</div>
          <pre class="chat-tool-call-args">${escapeHtml(JSON.stringify(toolCall.arguments || {}, null, 2))}</pre>
        </div>
      `).join("")
    : "";

  const resultMarkup = toolResult
    ? `
        <div class="chat-tool-result">
          <div class="chat-tool-call-name">Result</div>
          <pre class="chat-tool-call-args">${escapeHtml(JSON.stringify(toolResult, null, 2))}</pre>
        </div>
      `
    : "";

  const label = Array.isArray(toolCalls) && toolCalls.length > 0 ? `Tools (${toolCalls.length})` : "Tool result";
  return `
    <details class="chat-message-details">
      <summary>${label}</summary>
      <div class="chat-message-detail-list">
        ${callsMarkup}
        ${resultMarkup}
      </div>
    </details>
  `;
}

function renderMessageBadges(message: ChatMessage): string {
  if (message.role !== "assistant") {
    return "";
  }

  const badges: string[] = [];
  const model = message.metadata?.model || message.model;
  if (model) {
    badges.push(`<span class="chat-badge">${escapeHtml(model)}</span>`);
  }

  const toolMode = typeof message.options?.["tool_mode"] === "string" ? message.options["tool_mode"] : null;
  if (toolMode) {
    badges.push(`<span class="chat-badge">${escapeHtml(getToolModeLabel(toolMode))}</span>`);
  }

  if (message.context?.loop_context_applied) {
    badges.push('<span class="chat-badge">Loops</span>');
  }
  if (message.context?.memory_context_applied) {
    const label = message.context.memory_entries_used ? `Memory ${message.context.memory_entries_used}` : "Memory";
    badges.push(`<span class="chat-badge">${escapeHtml(label)}</span>`);
  }
  if (message.context?.rag_context_applied) {
    const label = message.context.rag_chunks_used ? `Docs ${message.context.rag_chunks_used}` : "Docs";
    badges.push(`<span class="chat-badge">${escapeHtml(label)}</span>`);
  }
  if (message.toolCalls.length > 0) {
    badges.push(`<span class="chat-badge">${message.toolCalls.length} tool${message.toolCalls.length === 1 ? "" : "s"}</span>`);
  }
  if (message.status === "error") {
    badges.push('<span class="chat-badge chat-badge-error">Error</span>');
  }

  return badges.length > 0 ? `<div class="chat-message-badges">${badges.join("")}</div>` : "";
}

function renderMessageMeta(message: ChatMessage): string {
  if (message.role !== "assistant") {
    return "";
  }

  const metaParts: string[] = [];
  if (typeof message.metadata?.latency_ms === "number") {
    metaParts.push(`${Math.round(message.metadata.latency_ms)} ms`);
  }
  if (message.metadata?.stop_reason) {
    metaParts.push(message.metadata.stop_reason.replaceAll("_", " "));
  }
  if (message.error) {
    metaParts.push(message.error);
  } else if (message.options) {
    metaParts.push(describeGrounding(message.options));
  }

  const detailsMarkup = [
    renderSources(message.sources),
    renderToolCalls(message.toolCalls, message.toolResult),
  ].filter(Boolean).join("");

  if (metaParts.length === 0 && !detailsMarkup) {
    return "";
  }

  return `
    <div class="chat-message-meta">
      ${renderMessageBadges(message)}
      ${metaParts.length > 0 ? `<p class="chat-message-meta-copy">${escapeHtml(metaParts.join(" · "))}</p>` : ""}
      ${detailsMarkup}
    </div>
  `;
}

function renderMessageActionCards(message: ChatMessage, prompt: string | null): string {
  if (message.role !== "assistant" || message.status !== "done") {
    return "";
  }

  const sourceLabels = Array.from(new Set((message.sources ?? [])
    .map((source) => source.document_path?.trim() || null)
    .filter((path): path is string => Boolean(path))));
  const hasGrounding = Boolean(
    message.context?.loop_context_applied
    || message.context?.memory_context_applied
    || message.context?.rag_context_applied
    || sourceLabels.length > 0,
  );
  if (!hasGrounding) {
    return "";
  }

  const answerSummary = message.content.trim();
  if (!answerSummary) {
    return "";
  }

  return renderRecallResultActionCards({
    tool: "chat",
    workingSetId: currentWorkingSetId(),
    chatGroundingSummary: message.options ? describeGrounding(message.options) : undefined,
    memoryQuery: message.context?.memory_context_applied ? prompt ?? "recent commitments" : undefined,
    ragQuestion: prompt ?? (typeof message.options?.["rag_scope"] === "string" && message.options["rag_scope"]
      ? String(message.options["rag_scope"])
      : undefined),
    hasKnowledge: message.context?.rag_context_applied || sourceLabels.length > 0,
    answerSummary,
    sourceCount: sourceLabels.length,
    sourceLabels,
    loopContextApplied: message.context?.loop_context_applied,
    memoryContextApplied: message.context?.memory_context_applied,
    memoryEntriesUsed: message.context?.memory_entries_used,
    ragContextApplied: message.context?.rag_context_applied,
    ragChunksUsed: message.context?.rag_chunks_used,
  });
}

function renderMessageContent(message: ChatMessage): string {
  if (message.role === "user") {
    return `<p>${escapeHtml(message.content).replace(/\n/g, "<br>")}</p>`;
  }

  if (!message.content) {
    if (message.status === "tools") {
      return '<p class="chat-streaming-placeholder">Thinking and running tools…</p>';
    }
    if (message.status === "error") {
      return '<p class="chat-streaming-placeholder">Request failed.</p>';
    }
    return '<p class="chat-streaming-placeholder">Thinking…</p>';
  }

  return renderMarkdown(message.content);
}

function updateThreadStatus(text: string): void {
  if (chatThreadStatusEl) {
    chatThreadStatusEl.textContent = text;
  }
}

function syncResetButton(
  threadState: ReturnType<typeof state.getChatThreadState>,
  isBusy: boolean,
): void {
  if (!chatResetButtonEl) {
    return;
  }
  chatResetButtonEl.hidden = !threadState.hasSavedThread;
  chatResetButtonEl.disabled = isBusy || !threadState.hasSavedThread;
}

function renderChatMessages(): void {
  if (!chatMessagesEl) {
    return;
  }

  const messages = state.state.chatMessages;
  const threadState = state.getChatThreadState();
  if (messages.length === 0) {
    renderPlaceholder();
    updateThreadStatus(getEmptyThreadCopy().status);
    syncResetButton(threadState, chatIsBusy);
    return;
  }

  chatMessagesEl.innerHTML = messages.map((message, index) => {
    const priorUserMessage = index > 0
      ? messages.slice(0, index).reverse().find((candidate) => candidate.role === "user") ?? null
      : null;
    return `
      <article class="chat-bubble ${message.role} ${message.status === "error" ? "is-error" : ""}" data-message-id="${escapeHtml(message.id)}">
        <div class="chat-message-body chat-rich-text">${renderMessageContent(message)}</div>
        ${renderMessageActionCards(message, priorUserMessage?.content?.trim() || null)}
        ${renderMessageMeta(message)}
      </article>
    `;
  }).join("");

  updateThreadStatus(
    threadState.lastUpdatedAt
      ? `Saved locally in this browser. Last updated ${new Date(threadState.lastUpdatedAt).toLocaleString()}.`
      : "Saved locally in this browser.",
  );
  syncResetButton(threadState, chatIsBusy);
  scrollConversationToBottom();
}

function setComposerBusy(isBusy: boolean): void {
  chatIsBusy = isBusy;
  chatComposerEl?.classList.toggle("is-busy", isBusy);
  if (chatInput) {
    chatInput.disabled = isBusy;
  }
  if (chatToolModeEl) {
    chatToolModeEl.disabled = isBusy;
  }
  if (chatLoopContextEl) {
    chatLoopContextEl.disabled = isBusy;
  }
  if (chatMemoryContextEl) {
    chatMemoryContextEl.disabled = isBusy;
  }
  if (chatMemoryLimitEl) {
    chatMemoryLimitEl.disabled = isBusy || !(chatMemoryContextEl?.checked);
  }
  if (chatRagContextEl) {
    chatRagContextEl.disabled = isBusy;
  }
  if (chatRagKEl) {
    chatRagKEl.disabled = isBusy || !(chatRagContextEl?.checked);
  }
  if (chatRagScopeEl) {
    chatRagScopeEl.disabled = isBusy || !(chatRagContextEl?.checked);
  }
  syncResetButton(state.getChatThreadState(), isBusy);
}

function addChatBubble(message: Partial<ChatMessage> & { role: string; content: string }): void {
  state.appendChatMessage(message);
  renderChatMessages();
}

function getEffectiveToolModePreference(toolMode: string | null): ChatPreferences["toolMode"] {
  return toolMode === "llm" || toolMode === "none" ? toolMode : null;
}

function readPreferencesFromControls(): ChatPreferences {
  return {
    toolMode: getEffectiveToolModePreference(chatToolModeEl?.value || null),
    includeLoopContext: Boolean(chatLoopContextEl?.checked),
    includeMemoryContext: Boolean(chatMemoryContextEl?.checked),
    includeRagContext: Boolean(chatRagContextEl?.checked),
    memoryLimit: Number.parseInt(chatMemoryLimitEl?.value || "10", 10) || 10,
    ragK: Number.parseInt(chatRagKEl?.value || "5", 10) || 5,
    ragScope: chatRagScopeEl?.value.trim() || "",
  };
}

function syncControlsFromPreferences(): void {
  const preferences = state.getChatPreferences();
  if (chatToolModeEl) {
    chatToolModeEl.value = preferences.toolMode || "none";
  }
  if (chatLoopContextEl) {
    chatLoopContextEl.checked = preferences.includeLoopContext;
  }
  if (chatMemoryContextEl) {
    chatMemoryContextEl.checked = preferences.includeMemoryContext;
  }
  if (chatMemoryLimitEl) {
    chatMemoryLimitEl.value = String(preferences.memoryLimit);
    chatMemoryLimitEl.disabled = !preferences.includeMemoryContext || chatIsBusy;
  }
  if (chatRagContextEl) {
    chatRagContextEl.checked = preferences.includeRagContext;
  }
  if (chatRagKEl) {
    chatRagKEl.value = String(preferences.ragK);
    chatRagKEl.disabled = !preferences.includeRagContext || chatIsBusy;
  }
  if (chatRagScopeEl) {
    chatRagScopeEl.value = preferences.ragScope;
    chatRagScopeEl.disabled = !preferences.includeRagContext || chatIsBusy;
  }
}

function currentWorkingSetId(): number | null {
  return parseHash(window.location.hash)?.workingSetId ?? null;
}

function renderActionCards(): void {
  renderRecallActionCards(chatActionCardsEl, {
    tool: "chat",
    workingSetId: currentWorkingSetId(),
    chatGroundingSummary: chatControlsStatusEl?.textContent || undefined,
    hasKnowledge: state.getChatPreferences().includeRagContext,
    ragQuestion: state.getChatPreferences().ragScope || undefined,
  });
}

function renderChatControlsSummary(): void {
  if (!chatControlsStatusEl) {
    return;
  }

  const preferences = state.getChatPreferences();
  const toolMode = preferences.toolMode || "none";
  const grounding: string[] = [];
  if (preferences.includeLoopContext) {
    grounding.push("loops");
  }
  if (preferences.includeMemoryContext) {
    grounding.push(`memory (${preferences.memoryLimit})`);
  }
  if (preferences.includeRagContext) {
    grounding.push(`docs (${preferences.ragK}${preferences.ragScope ? ` · ${preferences.ragScope}` : ""})`);
  }

  chatControlsStatusEl.textContent = `${getToolModeLabel(toolMode)} · ${grounding.length > 0 ? grounding.join(" · ") : "No extra grounding"}`;
  renderActionCards();
}

function persistControls(): void {
  state.updateChatPreferences(readPreferencesFromControls());
  syncControlsFromPreferences();
  renderChatControlsSummary();
}

async function loadBackendDefaults(): Promise<void> {
  if (!chatRuntimeStatusEl) {
    return;
  }

  try {
    const health = await api.fetchHealth();
    const backendDefault = health.tool_mode_default === "llm" || health.tool_mode_default === "none"
      ? health.tool_mode_default
      : "none";
    const stored = state.getChatPreferences();
    if (!stored.toolMode) {
      state.updateChatPreferences({ toolMode: backendDefault });
      syncControlsFromPreferences();
      renderChatControlsSummary();
    }
    chatRuntimeStatusEl.textContent = `Backend default tool mode: ${getToolModeLabel(health.tool_mode_default)}. Active chat model: ${health.chat_model}.`;
  } catch (error: unknown) {
    chatRuntimeStatusEl.textContent = `Could not load runtime defaults: ${messageFromError(error, "Could not load runtime defaults.")}`;
  }
}

export function init(elements: ChatModuleElements): void {
  chatActionCardsEl = elements.chatActionCards ?? null;
  chatMessagesEl = elements.chatMessages;
  chatInput = elements.chatInput;
  chatComposerEl = elements.chatForm;
  chatResetButtonEl = elements.chatResetButton ?? null;
  chatThreadStatusEl = elements.chatThreadStatus ?? null;
  chatToolModeEl = elements.chatToolMode ?? null;
  chatLoopContextEl = elements.chatLoopContext ?? null;
  chatMemoryContextEl = elements.chatMemoryContext ?? null;
  chatMemoryLimitEl = elements.chatMemoryLimit ?? null;
  chatRagContextEl = elements.chatRagContext ?? null;
  chatRagKEl = elements.chatRagK ?? null;
  chatRagScopeEl = elements.chatRagScope ?? null;
  chatControlsStatusEl = elements.chatControlsStatus ?? null;
  chatRuntimeStatusEl = elements.chatRuntimeStatus ?? null;

  chatResetButtonEl?.addEventListener("click", () => clearChat());
  chatToolModeEl?.addEventListener("change", persistControls);
  chatLoopContextEl?.addEventListener("change", persistControls);
  chatMemoryContextEl?.addEventListener("change", persistControls);
  chatMemoryLimitEl?.addEventListener("change", persistControls);
  chatRagContextEl?.addEventListener("change", persistControls);
  chatRagKEl?.addEventListener("change", persistControls);
  chatRagScopeEl?.addEventListener("change", persistControls);

  syncControlsFromPreferences();
  renderChatControlsSummary();
  renderChatMessages();
  renderActionCards();
  void loadBackendDefaults();
}

function updateLastAssistantBubble(fields: Record<string, unknown>): void {
  state.updateLastChatMessage({
    ...fields,
    createdAt: new Date().toISOString(),
  });
  renderChatMessages();
}

export async function submitChat(text: string): Promise<void> {
  const preferences = state.getChatPreferences();
  const wasEmptyThread = !state.getChatThreadState().hasSavedThread;
  addChatBubble({ role: "user", content: text });
  addChatBubble({ role: "assistant", content: "", status: "streaming" });
  setComposerBusy(true);
  updateThreadStatus(
    wasEmptyThread
      ? "First message saved locally. Waiting for the first reply…"
      : "Saved locally. Streaming response…",
  );

  const messages = state.state.chatMessages.slice(0, -1).map((message) => ({
    role: message.role,
    content: message.content,
  }));

  try {
    const response = await api.submitChatMessage(messages, true, preferences);
    let accumulated = "";
    let finalPayload: SurfaceChatEventPayload | undefined;
    let pendingToolCalls: ChatMessage["toolCalls"] = [];
    let pendingToolResult: ChatMessage["toolResult"] = null;

    await consumeJsonEventStream<SurfaceChatEventPayload>(response, (eventName, payload) => {
      if (eventName === "token" && typeof payload.token === "string") {
        accumulated += payload.token;
        updateLastAssistantBubble({
          content: accumulated,
          status: pendingToolCalls.length > 0 ? "tools" : "streaming",
        });
        return;
      }

      if (eventName === "tool_call") {
        pendingToolCalls = [
          ...pendingToolCalls,
          {
            name: typeof payload.name === "string" ? payload.name : "tool",
            arguments: payload.arguments && typeof payload.arguments === "object" ? payload.arguments : {},
          },
        ];
        updateLastAssistantBubble({ status: "tools", toolCalls: pendingToolCalls, toolResult: pendingToolResult });
        return;
      }

      if (eventName === "tool_result") {
        if (payload.output && typeof payload.output === "object") {
          pendingToolResult = payload.output;
          updateLastAssistantBubble({ status: "tools", toolCalls: pendingToolCalls, toolResult: pendingToolResult });
        }
        return;
      }

      if (eventName === "done") {
        finalPayload = payload;
      }
    });

    const resolvedPayload = finalPayload;
    updateLastAssistantBubble({
      content: typeof resolvedPayload?.message === "string" ? resolvedPayload.message : accumulated,
      status: "done",
      model: typeof resolvedPayload?.model === "string" ? resolvedPayload.model : null,
      metadata: resolvedPayload?.metadata ?? null,
      options: resolvedPayload?.options ?? null,
      context: resolvedPayload?.context ?? null,
      toolCalls: resolvedPayload?.tool_calls ?? pendingToolCalls,
      toolResult: resolvedPayload?.tool_result ?? pendingToolResult,
      sources: resolvedPayload?.sources ?? [],
      error: null,
    });
  } catch (error: unknown) {
    const errorMessage = messageFromError(error, "Chat request failed.");
    updateLastAssistantBubble({
      content: `Request failed: ${errorMessage}`,
      status: "error",
      error: errorMessage,
    });
  } finally {
    setComposerBusy(false);
    renderChatMessages();
  }
}

export function clearChat(): void {
  state.clearChatMessages();
  renderChatMessages();
  chatInput?.focus();
}
