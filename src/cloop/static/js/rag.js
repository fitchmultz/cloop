/**
 * rag.js - RAG tab functionality
 *
 * Purpose:
 *   Handle RAG (Retrieval Augmented Generation) queries with sources.
 *
 * Responsibilities:
 *   - Submit RAG questions
 *   - Handle streaming responses
 *   - Render answer and sources
 *   - Display source metadata
 *
 * Non-scope:
 *   - Chat functionality (see chat.js)
 *   - Tab switching (see init.js)
 */

import * as api from './api.js';
import { escapeHtml } from './utils.js';

let ragAnswer, ragAnswerText, ragSourcesList, ragInput;

/**
 * Initialize RAG module
 */
export function init(elements) {
  ragAnswer = elements.ragAnswer;
  ragAnswerText = elements.ragAnswerText;
  ragSourcesList = elements.ragSourcesList;
  ragInput = elements.ragInput;
}

/**
 * Render RAG sources list
 */
function renderRagSources(sources, chunks) {
  if (!sources || !sources.length) {
    ragSourcesList.innerHTML = '<div class="rag-source">No sources found</div>';
    return;
  }

  ragSourcesList.innerHTML = sources.map((src, idx) => {
    const chunk = chunks && chunks[idx] ? chunks[idx] : null;
    const contentPreview = chunk && chunk.content ? escapeHtml(chunk.content.substring(0, 200)) : "";
    return `
      <div class="rag-source">
        <div class="rag-source-path">${escapeHtml(src.document_path || "Unknown")}</div>
        <div class="rag-source-meta">
          Chunk ${src.chunk_index ?? "?"} · Score: ${(src.score ?? 0).toFixed(3)}
        </div>
        ${contentPreview ? `<div class="rag-source-content">${contentPreview}${chunk.content.length > 200 ? '...' : ''}</div>` : ''}
      </div>
    `;
  }).join("");
}

/**
 * Submit a RAG question
 */
export async function submitRagQuestion(question) {
  ragAnswer.style.display = "block";
  ragAnswerText.textContent = "Thinking...";
  ragSourcesList.innerHTML = "";

  try {
    const response = await api.submitRagQuestion(question, true);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let accumulated = "";
    let sources = [];
    let chunks = [];
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
              ragAnswerText.textContent = accumulated;
            }
            if (data.sources) {
              sources = data.sources;
            }
            if (data.chunks) {
              chunks = data.chunks;
            }
            if (data.answer !== undefined && data.token === undefined) {
              ragAnswerText.textContent = data.answer;
            }
          } catch (e) {
            console.warn("SSE parse error:", e);
          }
        }
      }
    }

    renderRagSources(sources, chunks);
  } catch (err) {
    ragAnswerText.textContent = "Connection error. Please try again.";
    console.error("RAG error:", err);
  }
}
