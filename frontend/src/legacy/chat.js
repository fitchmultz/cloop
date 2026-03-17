/**
 * chat.js - Chat tab functionality
 *
 * Purpose:
 *   Handle chat interface, grounding controls, streaming responses, and local
 *   thread persistence.
 *
 * Responsibilities:
 *   - Send chat messages with configurable grounding/tool options
 *   - Handle streaming responses and tool events
 *   - Render persisted chat bubbles with metadata, sources, and tool activity
 *   - Persist chat preferences and explicit thread reset controls
 *
 * Non-scope:
 *   - RAG tab functionality (see rag.js)
 *   - Tab switching (see init.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { renderMarkdown } from './markdown.js';
import { consumeJsonEventStream } from './stream.js';
import { escapeHtml } from './utils.js';

let chatMessagesEl;
let chatInput;
let chatComposerEl;
let chatResetButtonEl;
let chatThreadStatusEl;
let chatToolModeEl;
let chatLoopContextEl;
let chatMemoryContextEl;
let chatMemoryLimitEl;
let chatRagContextEl;
let chatRagKEl;
let chatRagScopeEl;
let chatControlsStatusEl;
let chatRuntimeStatusEl;
let chatIsBusy = false;

function getEmptyThreadCopy() {
  return {
    title: "No saved thread in this browser yet.",
    body: "Send your first message to save this conversation across reloads. Ask about your actual work, then tune the grounding controls if you want loops, memory, or document context to shape the answer.",
    status: "No saved thread yet. Send a message to keep this conversation across reloads.",
  };
}

function scrollConversationToBottom() {
  requestAnimationFrame(() => {
    chatMessagesEl?.lastElementChild?.scrollIntoView({ block: "end", behavior: "auto" });
  });
}

function renderPlaceholder() {
  const emptyCopy = getEmptyThreadCopy();
  chatMessagesEl.innerHTML = `
    <div class="chat-placeholder">
      <strong class="chat-placeholder-title">${emptyCopy.title}</strong>
      <p class="chat-placeholder-body">${emptyCopy.body}</p>
    </div>
  `;
}

function getToolModeLabel(toolMode) {
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

function describeGrounding(options) {
  if (!options) {
    return "No explicit grounding settings recorded.";
  }

  const parts = [];
  if (options.include_loop_context) {
    parts.push("loops");
  }
  if (options.include_memory_context) {
    parts.push(`memory${options.memory_limit ? ` (${options.memory_limit})` : ""}`);
  }
  if (options.include_rag_context) {
    const scope = options.rag_scope ? ` scoped to ${options.rag_scope}` : "";
    parts.push(`docs (${options.rag_k || 0})${scope}`);
  }

  return parts.length ? `Grounded in ${parts.join(" · ")}.` : "No extra grounding enabled.";
}

function renderSources(sources) {
  if (!Array.isArray(sources) || !sources.length) {
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
              Chunk ${source.chunk_index ?? "?"}${typeof source.score === "number" ? ` · Score ${(source.score).toFixed(3)}` : ""}
            </div>
          </div>
        `).join("")}
      </div>
    </details>
  `;
}

function renderToolCalls(toolCalls, toolResult) {
  if ((!Array.isArray(toolCalls) || !toolCalls.length) && !toolResult) {
    return "";
  }

  const callsMarkup = Array.isArray(toolCalls) && toolCalls.length
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

  const label = Array.isArray(toolCalls) && toolCalls.length ? `Tools (${toolCalls.length})` : "Tool result";
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

function renderMessageBadges(message) {
  if (message.role !== "assistant") {
    return "";
  }

  const badges = [];
  const model = message.metadata?.model || message.model;
  if (model) {
    badges.push(`<span class="chat-badge">${escapeHtml(model)}</span>`);
  }

  const toolMode = message.options?.tool_mode;
  if (toolMode) {
    badges.push(`<span class="chat-badge">${escapeHtml(getToolModeLabel(toolMode))}</span>`);
  }

  if (message.context?.loop_context_applied) {
    badges.push('<span class="chat-badge">Loops</span>');
  }
  if (message.context?.memory_context_applied) {
    const label = message.context.memory_entries_used
      ? `Memory ${message.context.memory_entries_used}`
      : 'Memory';
    badges.push(`<span class="chat-badge">${escapeHtml(label)}</span>`);
  }
  if (message.context?.rag_context_applied) {
    const label = message.context.rag_chunks_used
      ? `Docs ${message.context.rag_chunks_used}`
      : 'Docs';
    badges.push(`<span class="chat-badge">${escapeHtml(label)}</span>`);
  }
  if (Array.isArray(message.toolCalls) && message.toolCalls.length) {
    badges.push(`<span class="chat-badge">${message.toolCalls.length} tool${message.toolCalls.length === 1 ? '' : 's'}</span>`);
  }
  if (message.status === 'error') {
    badges.push('<span class="chat-badge chat-badge-error">Error</span>');
  }

  return badges.length ? `<div class="chat-message-badges">${badges.join("")}</div>` : "";
}

function renderMessageMeta(message) {
  if (message.role !== "assistant") {
    return "";
  }

  const metaParts = [];
  if (typeof message.metadata?.latency_ms === 'number') {
    metaParts.push(`${Math.round(message.metadata.latency_ms)} ms`);
  }
  if (message.metadata?.stop_reason) {
    metaParts.push(message.metadata.stop_reason.replaceAll('_', ' '));
  }
  if (message.error) {
    metaParts.push(message.error);
  } else if (message.options) {
    metaParts.push(describeGrounding(message.options));
  }

  const detailsMarkup = [
    renderSources(message.sources),
    renderToolCalls(message.toolCalls, message.toolResult),
  ].filter(Boolean).join('');

  if (!metaParts.length && !detailsMarkup) {
    return "";
  }

  return `
    <div class="chat-message-meta">
      ${renderMessageBadges(message)}
      ${metaParts.length ? `<p class="chat-message-meta-copy">${escapeHtml(metaParts.join(' · '))}</p>` : ''}
      ${detailsMarkup}
    </div>
  `;
}

function renderMessageContent(message) {
  if (message.role === "user") {
    return `<p>${escapeHtml(message.content).replace(/\n/g, "<br>")}</p>`;
  }

  if (!message.content) {
    if (message.status === 'tools') {
      return `<p class="chat-streaming-placeholder">Thinking and running tools…</p>`;
    }
    if (message.status === 'error') {
      return `<p class="chat-streaming-placeholder">Request failed.</p>`;
    }
    return `<p class="chat-streaming-placeholder">Thinking…</p>`;
  }

  return renderMarkdown(message.content);
}

function renderChatMessages() {
  const messages = state.state.chatMessages;
  const threadState = state.getChatThreadState();
  if (messages.length === 0) {
    renderPlaceholder();
    updateThreadStatus(getEmptyThreadCopy().status);
    syncResetButton(threadState, chatIsBusy);
    return;
  }

  chatMessagesEl.innerHTML = messages.map((message) => `
    <article class="chat-bubble ${message.role} ${message.status === 'error' ? 'is-error' : ''}" data-message-id="${escapeHtml(message.id)}">
      <div class="chat-message-body chat-rich-text">${renderMessageContent(message)}</div>
      ${renderMessageMeta(message)}
    </article>
  `).join("");

  updateThreadStatus(threadState.lastUpdatedAt
    ? `Saved locally in this browser. Last updated ${new Date(threadState.lastUpdatedAt).toLocaleString()}.`
    : "Saved locally in this browser.");
  syncResetButton(threadState, chatIsBusy);
  scrollConversationToBottom();
}

function setComposerBusy(isBusy) {
  chatIsBusy = isBusy;
  chatComposerEl?.classList.toggle("is-busy", isBusy);
  chatInput.disabled = isBusy;
  if (chatToolModeEl) chatToolModeEl.disabled = isBusy;
  if (chatLoopContextEl) chatLoopContextEl.disabled = isBusy;
  if (chatMemoryContextEl) chatMemoryContextEl.disabled = isBusy;
  if (chatMemoryLimitEl) chatMemoryLimitEl.disabled = isBusy || !chatMemoryContextEl?.checked;
  if (chatRagContextEl) chatRagContextEl.disabled = isBusy;
  if (chatRagKEl) chatRagKEl.disabled = isBusy || !chatRagContextEl?.checked;
  if (chatRagScopeEl) chatRagScopeEl.disabled = isBusy || !chatRagContextEl?.checked;
  syncResetButton(state.getChatThreadState(), isBusy);
}

function addChatBubble(message) {
  state.appendChatMessage(message);
  renderChatMessages();
}

function updateThreadStatus(text) {
  if (chatThreadStatusEl) {
    chatThreadStatusEl.textContent = text;
  }
}

function syncResetButton(threadState, isBusy) {
  if (!chatResetButtonEl) {
    return;
  }

  chatResetButtonEl.hidden = !threadState.hasSavedThread;
  chatResetButtonEl.disabled = isBusy || !threadState.hasSavedThread;
}

function getEffectiveToolModePreference(toolMode) {
  if (toolMode === 'llm' || toolMode === 'none') {
    return toolMode;
  }
  return null;
}

function readPreferencesFromControls() {
  return {
    toolMode: getEffectiveToolModePreference(chatToolModeEl?.value || null),
    includeLoopContext: Boolean(chatLoopContextEl?.checked),
    includeMemoryContext: Boolean(chatMemoryContextEl?.checked),
    includeRagContext: Boolean(chatRagContextEl?.checked),
    memoryLimit: Number.parseInt(chatMemoryLimitEl?.value || '10', 10) || 10,
    ragK: Number.parseInt(chatRagKEl?.value || '5', 10) || 5,
    ragScope: chatRagScopeEl?.value?.trim() || '',
  };
}

function syncControlsFromPreferences() {
  const preferences = state.getChatPreferences();
  if (chatToolModeEl) {
    chatToolModeEl.value = preferences.toolMode || 'none';
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

function renderChatControlsSummary() {
  const preferences = state.getChatPreferences();
  const toolMode = preferences.toolMode || 'none';
  const grounding = [];
  if (preferences.includeLoopContext) {
    grounding.push('loops');
  }
  if (preferences.includeMemoryContext) {
    grounding.push(`memory (${preferences.memoryLimit})`);
  }
  if (preferences.includeRagContext) {
    grounding.push(`docs (${preferences.ragK}${preferences.ragScope ? ` · ${preferences.ragScope}` : ''})`);
  }

  if (chatControlsStatusEl) {
    chatControlsStatusEl.textContent = `${getToolModeLabel(toolMode)} · ${grounding.length ? grounding.join(' · ') : 'No extra grounding'}`;
  }
}

function persistControls() {
  state.updateChatPreferences(readPreferencesFromControls());
  syncControlsFromPreferences();
  renderChatControlsSummary();
}

async function loadBackendDefaults() {
  if (!chatRuntimeStatusEl) {
    return;
  }

  try {
    const health = await api.fetchHealth();
    const backendDefault = health.tool_mode_default === 'llm' || health.tool_mode_default === 'none'
      ? health.tool_mode_default
      : 'none';
    const stored = state.getChatPreferences();
    if (!stored.toolMode) {
      state.updateChatPreferences({ toolMode: backendDefault });
      syncControlsFromPreferences();
      renderChatControlsSummary();
    }
    chatRuntimeStatusEl.textContent = `Backend default tool mode: ${getToolModeLabel(health.tool_mode_default)}. Active chat model: ${health.chat_model}.`;
  } catch (error) {
    chatRuntimeStatusEl.textContent = `Could not load runtime defaults: ${error.message}`;
  }
}

/**
 * Initialize chat module
 */
export function init(elements) {
  chatMessagesEl = elements.chatMessages;
  chatInput = elements.chatInput;
  chatComposerEl = elements.chatForm;
  chatResetButtonEl = elements.chatResetButton;
  chatThreadStatusEl = elements.chatThreadStatus;
  chatToolModeEl = elements.chatToolMode;
  chatLoopContextEl = elements.chatLoopContext;
  chatMemoryContextEl = elements.chatMemoryContext;
  chatMemoryLimitEl = elements.chatMemoryLimit;
  chatRagContextEl = elements.chatRagContext;
  chatRagKEl = elements.chatRagK;
  chatRagScopeEl = elements.chatRagScope;
  chatControlsStatusEl = elements.chatControlsStatus;
  chatRuntimeStatusEl = elements.chatRuntimeStatus;

  chatResetButtonEl?.addEventListener("click", () => clearChat());
  chatToolModeEl?.addEventListener('change', persistControls);
  chatLoopContextEl?.addEventListener('change', persistControls);
  chatMemoryContextEl?.addEventListener('change', persistControls);
  chatMemoryLimitEl?.addEventListener('change', persistControls);
  chatRagContextEl?.addEventListener('change', persistControls);
  chatRagKEl?.addEventListener('change', persistControls);
  chatRagScopeEl?.addEventListener('change', persistControls);

  syncControlsFromPreferences();
  renderChatControlsSummary();
  renderChatMessages();
  void loadBackendDefaults();
}

/**
 * Update the last assistant bubble (for streaming)
 */
function updateLastAssistantBubble(fields) {
  state.updateLastChatMessage({
    ...fields,
    createdAt: new Date().toISOString(),
  });
  renderChatMessages();
}

/**
 * Submit a chat message and handle streaming response
 */
export async function submitChat(text) {
  const preferences = state.getChatPreferences();
  const wasEmptyThread = !state.getChatThreadState().hasSavedThread;
  addChatBubble({ role: 'user', content: text });
  addChatBubble({ role: 'assistant', content: '', status: 'streaming' });
  setComposerBusy(true);
  updateThreadStatus(
    wasEmptyThread
      ? 'First message saved locally. Waiting for the first reply…'
      : 'Saved locally. Streaming response…',
  );

  const messages = state.state.chatMessages.slice(0, -1).map((message) => ({
    role: message.role,
    content: message.content,
  }));

  try {
    const response = await api.submitChatMessage(messages, true, preferences);
    let accumulated = '';
    let finalPayload = null;
    let pendingToolCalls = [];
    let pendingToolResult = null;

    await consumeJsonEventStream(response, (eventName, payload) => {
      if (eventName === 'token' && payload.token) {
        accumulated += payload.token;
        updateLastAssistantBubble({ content: accumulated, status: pendingToolCalls.length ? 'tools' : 'streaming' });
        return;
      }

      if (eventName === 'tool_call') {
        pendingToolCalls = [
          ...pendingToolCalls,
          {
            name: payload.name,
            arguments: payload.arguments || {},
          },
        ];
        updateLastAssistantBubble({
          status: 'tools',
          toolCalls: pendingToolCalls,
          toolResult: pendingToolResult,
        });
        return;
      }

      if (eventName === 'tool_result') {
        if (payload.output && typeof payload.output === 'object') {
          pendingToolResult = payload.output;
          updateLastAssistantBubble({
            status: 'tools',
            toolCalls: pendingToolCalls,
            toolResult: pendingToolResult,
          });
        }
        return;
      }

      if (eventName === 'done') {
        finalPayload = payload;
      }
    });

    updateLastAssistantBubble({
      content: finalPayload?.message ?? accumulated,
      status: 'done',
      model: finalPayload?.model || null,
      metadata: finalPayload?.metadata || null,
      options: finalPayload?.options || null,
      context: finalPayload?.context || null,
      toolCalls: finalPayload?.tool_calls || pendingToolCalls,
      toolResult: finalPayload?.tool_result || pendingToolResult,
      sources: finalPayload?.sources || [],
      error: null,
    });
  } catch (error) {
    updateLastAssistantBubble({
      content: `Request failed: ${error.message}`,
      status: 'error',
      error: error.message,
    });
    console.error('Chat error:', error);
  } finally {
    setComposerBusy(false);
    renderChatMessages();
  }
}

/**
 * Clear chat history
 */
export function clearChat() {
  state.clearChatMessages();
  renderChatMessages();
  chatInput?.focus();
}
