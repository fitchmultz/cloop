/**
 * rag.ts - Recall RAG surface functionality.
 *
 * Purpose:
 *   Handle document-grounded RAG questions, streaming answers, and knowledge
 *   ingestion inside the unified recall runtime.
 *
 * Responsibilities:
 *   - Submit streaming RAG questions.
 *   - Render answers and supporting sources.
 *   - Trigger document ingestion from local paths.
 *
 * Scope:
 *   - Recall RAG UI only.
 *
 * Usage:
 *   - Imported by bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - The recall RAG surface exposes the current DOM ids for answer/source UI.
 *   - Streaming responses use the shared SSE-like event stream parser.
 */

import { parseHash } from "../shell-routing";
import { renderRecallActionCards } from "./recall-action-cards";
import * as api from "./api";
import type { RagChunk, RagSource, SurfaceChatEventPayload } from "./contracts";
import { consumeJsonEventStream } from "./stream";
import { escapeHtml, messageFromError } from "./utils";

const NO_KNOWLEDGE_MESSAGE = "No knowledge available. Ingest documents first.";

interface RagModuleElements {
  ragActionCards?: HTMLElement | null;
  ragAnswer: HTMLElement;
  ragAnswerText: HTMLElement;
  ragSources: HTMLElement;
  ragSourcesList: HTMLElement;
  ragInput: HTMLInputElement | HTMLTextAreaElement;
  ragEmptyState: HTMLElement;
  ragIngestForm: HTMLFormElement;
  ragIngestPath: HTMLInputElement;
  ragIngestMode: HTMLSelectElement;
  ragIngestRecursive: HTMLInputElement;
  ragIngestStatus: HTMLElement;
}

let ragActionCardsEl: HTMLElement | null = null;
let ragAnswer: HTMLElement | null = null;
let ragAnswerText: HTMLElement | null = null;
let ragSources: HTMLElement | null = null;
let ragSourcesList: HTMLElement | null = null;
let ragInput: HTMLInputElement | HTMLTextAreaElement | null = null;
let ragEmptyState: HTMLElement | null = null;
let ragIngestPath: HTMLInputElement | null = null;
let ragIngestMode: HTMLSelectElement | null = null;
let ragIngestRecursive: HTMLInputElement | null = null;
let ragIngestStatus: HTMLElement | null = null;

export function init(elements: RagModuleElements): void {
  ragActionCardsEl = elements.ragActionCards ?? null;
  ragAnswer = elements.ragAnswer;
  ragAnswerText = elements.ragAnswerText;
  ragSources = elements.ragSources;
  ragSourcesList = elements.ragSourcesList;
  ragInput = elements.ragInput;
  ragEmptyState = elements.ragEmptyState;
  ragIngestPath = elements.ragIngestPath;
  ragIngestMode = elements.ragIngestMode;
  ragIngestRecursive = elements.ragIngestRecursive;
  ragIngestStatus = elements.ragIngestStatus;
  renderActionCards({ hasKnowledge: false });
}

function currentWorkingSetId(): number | null {
  return parseHash(window.location.hash)?.workingSetId ?? null;
}

function renderActionCards(options: { hasKnowledge?: boolean } = {}): void {
  renderRecallActionCards(ragActionCardsEl, {
    tool: "rag",
    workingSetId: currentWorkingSetId(),
    ragQuestion: ragInput?.value.trim() || undefined,
    hasKnowledge: options.hasKnowledge,
  });
}

function setIngestStatus(message: string, options: { isError?: boolean } = {}): void {
  if (!ragIngestStatus) {
    return;
  }
  ragIngestStatus.textContent = message;
  ragIngestStatus.classList.toggle("is-error", options.isError ?? false);
}

function setNoKnowledgeState(visible: boolean): void {
  ragAnswer?.classList.toggle("rag-answer-empty", visible);
  ragEmptyState?.classList.toggle("hidden", !visible);
  ragSources?.classList.toggle("hidden", visible);
}

function focusIngestPath(): void {
  if (!ragIngestPath) {
    return;
  }
  ragIngestPath.focus();
  ragIngestPath.select();
  ragIngestPath.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderAnswer(answer: string, sources: RagSource[], chunks: RagChunk[]): void {
  if (!ragAnswerText) {
    return;
  }

  const normalizedAnswer = answer.trim();
  const isNoKnowledgeState = normalizedAnswer === NO_KNOWLEDGE_MESSAGE && sources.length === 0 && chunks.length === 0;
  ragAnswerText.textContent = isNoKnowledgeState ? "No knowledge indexed yet." : answer;
  setNoKnowledgeState(isNoKnowledgeState);
  renderRagSources(sources, chunks);
  renderActionCards({ hasKnowledge: !isNoKnowledgeState });
}

function renderRagSources(sources: RagSource[], chunks: RagChunk[]): void {
  if (!ragSourcesList) {
    return;
  }

  if (sources.length === 0) {
    ragSourcesList.innerHTML = '<div class="rag-source">No sources found</div>';
    return;
  }

  ragSourcesList.innerHTML = sources.map((source, index) => {
    const chunk = chunks[index] ?? null;
    const contentPreview = chunk?.content ? escapeHtml(chunk.content.slice(0, 200)) : "";
    const isTruncated = Boolean(chunk?.content && chunk.content.length > 200);
    return `
      <div class="rag-source">
        <div class="rag-source-path">${escapeHtml(source.document_path || "Unknown")}</div>
        <div class="rag-source-meta">
          Chunk ${source.chunk_index ?? "?"} · Score: ${(source.score ?? 0).toFixed(3)}
        </div>
        ${contentPreview ? `<div class="rag-source-content">${contentPreview}${isTruncated ? "..." : ""}</div>` : ""}
      </div>
    `;
  }).join("");
}

export async function submitRagQuestion(question: string): Promise<void> {
  if (!ragAnswer || !ragAnswerText || !ragSourcesList) {
    return;
  }

  ragAnswer.classList.remove("hidden", "rag-answer-error");
  ragAnswer.style.display = "block";
  setNoKnowledgeState(false);
  ragAnswerText.textContent = "Thinking...";
  ragSourcesList.innerHTML = "";

  try {
    const response = await api.submitRagQuestion(question, true);
    let accumulated = "";
    let finalAnswer = "";
    let sources: RagSource[] = [];
    let chunks: RagChunk[] = [];

    await consumeJsonEventStream<SurfaceChatEventPayload>(response, (eventName, payload) => {
      if (eventName === "token" && typeof payload.token === "string") {
        accumulated += payload.token;
        if (ragAnswerText) {
          ragAnswerText.textContent = accumulated;
        }
        return;
      }

      if (eventName === "done") {
        sources = Array.isArray(payload.sources) ? payload.sources : [];
        chunks = Array.isArray(payload.chunks) ? payload.chunks : [];
        finalAnswer = typeof payload.answer === "string" ? payload.answer : "";
      }
    });

    renderAnswer(finalAnswer || accumulated || ragAnswerText.textContent || "", sources, chunks);
    ragAnswer.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error: unknown) {
    ragAnswer.classList.remove("hidden");
    ragAnswer.classList.add("rag-answer-error");
    setNoKnowledgeState(false);
    ragAnswerText.textContent = messageFromError(error, "Connection error. Please try again.");
  }
}

export async function submitIngestPath(): Promise<void> {
  if (!ragIngestPath || !ragIngestMode || !ragIngestRecursive || !ragAnswer || !ragAnswerText || !ragSourcesList) {
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
    const result = await api.ingestKnowledge([path], ragIngestMode.value, ragIngestRecursive.checked);
    const failedCount = Array.isArray(result.failed_files) ? result.failed_files.length : 0;
    const summary = failedCount > 0
      ? `Indexed ${result.files} files into ${result.chunks} chunks with ${failedCount} failures.`
      : `Indexed ${result.files} files into ${result.chunks} chunks.`;
    setIngestStatus(summary);
    ragAnswer.classList.remove("hidden", "rag-answer-error");
    ragAnswerText.textContent = "Knowledge indexed. Ask a question when you're ready.";
    setNoKnowledgeState(false);
    ragSourcesList.innerHTML = "";
    renderActionCards({ hasKnowledge: true });
    ragInput?.focus();
  } catch (error: unknown) {
    setIngestStatus(messageFromError(error, "Knowledge ingestion failed."), { isError: true });
  }
}

export function handleEmptyStateAction(): void {
  focusIngestPath();
}
