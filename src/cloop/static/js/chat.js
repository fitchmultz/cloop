/**
 * chat.js - Chat tab functionality
 *
 * Purpose:
 *   Handle chat interface, streaming responses, and local thread persistence.
 *
 * Responsibilities:
 *   - Send chat messages
 *   - Handle streaming responses
 *   - Render persisted chat bubbles
 *   - Expose explicit thread reset controls
 *
 * Non-scope:
 *   - RAG functionality (see rag.js)
 *   - Tab switching (see init.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { escapeHtml } from './utils.js';
import { renderMarkdown } from './markdown.js';

let chatMessagesEl;
let chatInput;
let chatComposerEl;
let chatResetButtonEl;
let chatThreadStatusEl;
let chatIsBusy = false;

function getEmptyThreadCopy() {
  return {
    title: "No saved thread in this browser yet.",
    body: "Send your first message to save this conversation across reloads. Ask about your real work: \"What should I focus on next?\", \"What is blocked?\", or \"What is due soon?\"",
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

function renderMessageContent(message) {
  if (message.role === "user") {
    return `<p>${escapeHtml(message.content).replace(/\n/g, "<br>")}</p>`;
  }

  if (!message.content) {
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
    <article class="chat-bubble ${message.role}" data-message-id="${escapeHtml(message.id)}">
      <div class="chat-message-body chat-rich-text">${renderMessageContent(message)}</div>
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
  syncResetButton(state.getChatThreadState(), isBusy);
}

function addChatBubble(role, content) {
  state.appendChatMessage({ role, content });
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

/**
 * Initialize chat module
 */
export function init(elements) {
  chatMessagesEl = elements.chatMessages;
  chatInput = elements.chatInput;
  chatComposerEl = elements.chatForm;
  chatResetButtonEl = elements.chatResetButton;
  chatThreadStatusEl = elements.chatThreadStatus;

  chatResetButtonEl?.addEventListener("click", () => clearChat());
  renderChatMessages();
}

/**
 * Update the last assistant bubble (for streaming)
 */
function updateLastAssistantBubble(content) {
  state.updateLastChatMessage({
    content,
    createdAt: new Date().toISOString(),
  });
  renderChatMessages();
}

/**
 * Submit a chat message and handle streaming response
 */
export async function submitChat(text) {
  const wasEmptyThread = !state.getChatThreadState().hasSavedThread;
  addChatBubble("user", text);
  addChatBubble("assistant", "");
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
    const response = await api.submitChatMessage(messages, true);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let accumulated = "";
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data:")) {
          continue;
        }

        try {
          const data = JSON.parse(line.slice(5).trim());
          if (data.token) {
            accumulated += data.token;
            updateLastAssistantBubble(accumulated);
          }
          if (data.message !== undefined && data.token === undefined) {
            accumulated = data.message;
            updateLastAssistantBubble(accumulated);
          }
        } catch (error) {
          console.warn("SSE parse error:", error);
        }
      }
    }
  } catch (error) {
    updateLastAssistantBubble("Connection error. Please try again.");
    console.error("Chat error:", error);
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
