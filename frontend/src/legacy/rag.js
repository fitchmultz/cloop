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
import { consumeJsonEventStream } from './stream.js';
import { escapeHtml } from './utils.js';

const NO_KNOWLEDGE_MESSAGE = "No knowledge available. Ingest documents first.";

let ragAnswer;
let ragAnswerText;
let ragSources;
let ragSourcesList;
let ragInput;
let ragEmptyState;
let ragIngestForm;
let ragIngestPath;
let ragIngestMode;
let ragIngestRecursive;
let ragIngestStatus;

/**
 * Initialize RAG module
 */
export function init(elements) {
  ragAnswer = elements.ragAnswer;
  ragAnswerText = elements.ragAnswerText;
  ragSources = elements.ragSources;
  ragSourcesList = elements.ragSourcesList;
  ragInput = elements.ragInput;
  ragEmptyState = elements.ragEmptyState;
  ragIngestForm = elements.ragIngestForm;
  ragIngestPath = elements.ragIngestPath;
  ragIngestMode = elements.ragIngestMode;
  ragIngestRecursive = elements.ragIngestRecursive;
  ragIngestStatus = elements.ragIngestStatus;
}

function setIngestStatus(message, { isError = false } = {}) {
  if (!ragIngestStatus) {
    return;
  }
  ragIngestStatus.textContent = message;
  ragIngestStatus.classList.toggle("is-error", isError);
}

function setNoKnowledgeState(visible) {
  ragAnswer?.classList.toggle("rag-answer-empty", visible);
  ragEmptyState?.classList.toggle("hidden", !visible);
  ragSources?.classList.toggle("hidden", visible);
}

function focusIngestPath() {
  if (!ragIngestPath) {
    return;
  }
  ragIngestPath.focus();
  ragIngestPath.select();
  ragIngestPath.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderAnswer(answer, sources, chunks) {
  const isNoKnowledgeState = answer.trim() === NO_KNOWLEDGE_MESSAGE && !sources.length && !chunks.length;
  ragAnswerText.textContent = isNoKnowledgeState ? "No knowledge indexed yet." : answer;
  setNoKnowledgeState(isNoKnowledgeState);
  renderRagSources(sources, chunks);
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
  ragAnswer.classList.remove("hidden");
  ragAnswer.style.display = "block";
  ragAnswer.classList.remove("rag-answer-error");
  setNoKnowledgeState(false);
  ragAnswerText.textContent = "Thinking...";
  ragSourcesList.innerHTML = "";

  try {
    const response = await api.submitRagQuestion(question, true);
    let accumulated = "";
    let finalAnswer = "";
    let sources = [];
    let chunks = [];

    await consumeJsonEventStream(response, (eventName, payload) => {
      if (eventName === "token" && payload.token) {
        accumulated += payload.token;
        ragAnswerText.textContent = accumulated;
        return;
      }

      if (eventName === "done") {
        if (Array.isArray(payload.sources)) {
          sources = payload.sources;
        }
        if (Array.isArray(payload.chunks)) {
          chunks = payload.chunks;
        }
        if (typeof payload.answer === "string") {
          finalAnswer = payload.answer;
        }
      }
    });

    renderAnswer(finalAnswer || accumulated || ragAnswerText.textContent, sources, chunks);
    ragAnswer.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    ragAnswer.classList.remove("hidden");
    ragAnswer.classList.add("rag-answer-error");
    setNoKnowledgeState(false);
    ragAnswerText.textContent = err.message || "Connection error. Please try again.";
    console.error("RAG error:", err);
  }
}

export async function submitIngestPath() {
  if (!ragIngestPath || !ragIngestMode || !ragIngestRecursive) {
    return;
  }

  const path = ragIngestPath.value.trim();
  if (!path) {
    setIngestStatus("Enter a file or folder path first.", { isError: true });
    focusIngestPath();
    return;
  }

  setIngestStatus("Indexing knowledge...");
  try {
    const result = await api.ingestKnowledge(
      [path],
      ragIngestMode.value,
      ragIngestRecursive.checked,
    );
    const failedCount = Array.isArray(result.failed_files) ? result.failed_files.length : 0;
    const summary = failedCount > 0
      ? `Indexed ${result.files} files into ${result.chunks} chunks with ${failedCount} failures.`
      : `Indexed ${result.files} files into ${result.chunks} chunks.`;
    setIngestStatus(summary);
    ragAnswer.classList.remove("hidden");
    ragAnswer.classList.remove("rag-answer-error");
    ragAnswerText.textContent = "Knowledge indexed. Ask a question when you're ready.";
    setNoKnowledgeState(false);
    ragSourcesList.innerHTML = "";
    ragInput?.focus();
  } catch (error) {
    setIngestStatus(error.message, { isError: true });
  }
}

export function handleEmptyStateAction() {
  focusIngestPath();
}
