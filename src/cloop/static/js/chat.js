/**
 * chat.js - Chat tab functionality
 *
 * Purpose:
 *   Handle chat interface with streaming responses.
 *
 * Responsibilities:
 *   - Send chat messages
 *   - Handle streaming responses
 *   - Render chat bubbles
 *   - Manage chat history
 *
 * Non-scope:
 *   - RAG functionality (see rag.js)
 *   - Tab switching (see init.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { escapeHtml } from './utils.js';

let chatMessagesEl, chatInput;

/**
 * Initialize chat module
 */
export function init(elements) {
  chatMessagesEl = elements.chatMessages;
  chatInput = elements.chatInput;
}

/**
 * Render all chat messages
 */
function renderChatMessages() {
  if (state.state.chatMessages.length === 0) {
    chatMessagesEl.innerHTML = `
      <div class="chat-placeholder">
        Ask about your real work: "What should I focus on next?", "What is blocked?", or "What is due soon?"
      </div>
    `;
    return;
  }

  chatMessagesEl.innerHTML = state.state.chatMessages.map(msg =>
    `<div class="chat-bubble ${msg.role}">${renderMessageContent(msg.content, msg.role)}</div>`
  ).join("");

  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

/**
 * Add a new chat bubble
 */
function addChatBubble(role, content) {
  state.state.chatMessages.push({ role, content });
  renderChatMessages();
}

function renderMessageContent(content, role) {
  const escaped = escapeHtml(content);
  if (role === "user") {
    return escaped;
  }

  const formatted = escaped
    .replace(/^### (.+)$/gm, "<strong>$1</strong>")
    .replace(/^\* (.+)$/gm, "• $1")
    .replace(/\n/g, "<br>");

  return `<p>${formatted.replace(/(?:<br>){2,}/g, "</p><p>")}</p>`;
}

/**
 * Update the last assistant bubble (for streaming)
 */
function updateLastAssistantBubble(content) {
  const messages = state.state.chatMessages;
  if (messages.length && messages[messages.length - 1].role === "assistant") {
    messages[messages.length - 1].content = content;
    renderChatMessages();
  }
}

/**
 * Submit a chat message and handle streaming response
 */
export async function submitChat(text) {
  addChatBubble("user", text);
  addChatBubble("assistant", "");

  const messages = state.state.chatMessages.slice(0, -1).map(m => ({
    role: m.role,
    content: m.content
  }));

  try {
    const response = await api.submitChatMessage(messages, true);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let accumulated = "";
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data:")) {
          try {
            const data = JSON.parse(line.slice(5).trim());
            if (data.token) {
              accumulated += data.token;
              updateLastAssistantBubble(accumulated);
            }
            if (data.message !== undefined && data.token === undefined) {
              updateLastAssistantBubble(data.message);
            }
          } catch (e) {
            console.warn("SSE parse error:", e);
          }
        }
      }
    }
  } catch (err) {
    updateLastAssistantBubble("Connection error. Please try again.");
    console.error("Chat error:", err);
  }
}

/**
 * Clear chat history
 */
export function clearChat() {
  state.state.chatMessages = [];
  renderChatMessages();
}
