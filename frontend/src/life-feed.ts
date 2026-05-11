/**
 * life-feed.ts - Life feed web surface.
 *
 * Purpose:
 *   Provide the first-screen Life experience for messy capture, resurfacing,
 *   cleanup, preference memory, and recent automatic-cleanup undo.
 *
 * Responsibilities:
 *   - POST natural-language messages to /life/message
 *   - Render concise capture receipts and plain-language loop groups
 *   - Restore loops from backend undo handles for automatic cleanup
 *
 * Non-scope:
 *   - Legacy loop card editing, saved review workspaces, or chat runtime UI
 */

import type { LoopResponse, LoopUndoResponse } from "./domain";
import { requestJson } from "./http";
import { escapeHtml, loopPreview, loopTitle, requireElement } from "./shell-core";

interface LifeMessageRequest {
  message: string;
  external_inputs: LifeExternalInput[];
  client_tz_offset_min: number;
  captured_at?: string | null;
}

type LifeExternalInputKind = "link" | "image" | "audio" | "file" | "text";

interface LifeExternalInput {
  kind: LifeExternalInputKind;
  label: string;
  source_url?: string | null;
  media_type?: string | null;
  size_bytes?: number | null;
  text?: string | null;
}

interface LifeLoopItem {
  loop: LoopResponse;
  life_state: string;
  rationale?: string | null;
  prepared_next_action?: string | null;
  prepared_actions: LifePreparedAction[];
}

interface LifePreparedAction {
  kind: string;
  title: string;
  body: string;
  risk_level: "internal" | "external_low" | "consequential";
  requires_approval: boolean;
}

interface LifeUndoHandle {
  loop_id: number;
  expected_event_id: number;
  event_type: string;
  label: string;
}

interface LifeClarification {
  question: string;
  loop_id?: number | null;
  clarification_id?: number | null;
  assumption?: string | null;
  rationale?: string | null;
  improves: string[];
}

interface LifeClarificationAnswer {
  clarification_id: number;
  loop_id: number;
  question: string;
  answer: string;
  rationale?: string | null;
}

interface LifeLoopGroup {
  name: string;
  title: string;
  summary: string;
  items: LifeLoopItem[];
}

interface LifeCleanupPlan {
  open_count: number;
  recommendation: string;
  close_candidates: LifeLoopItem[];
  archive_candidates: LifeLoopItem[];
  keep_active: LifeLoopItem[];
  review_needed: LifeLoopItem[];
  applied_automatic_cleanup: LifeLoopItem[];
  undo: LifeUndoHandle[];
}

interface LifeMessageResponse {
  mode: "capture" | "cleanup" | "resurface" | "preference";
  reply: string;
  captured: LifeLoopItem[];
  updated: LifeLoopItem[];
  clarifications: LifeClarification[];
  answered_clarifications: LifeClarificationAnswer[];
  groups: LifeLoopGroup[];
  cleanup: LifeCleanupPlan | null;
}

interface LifeFeedElements {
  form: HTMLFormElement;
  input: HTMLTextAreaElement;
  submitButton: HTMLButtonElement;
  quickDumpButton: HTMLButtonElement;
  missingButton: HTMLButtonElement;
  mattersButton: HTMLButtonElement;
  quizButton: HTMLButtonElement;
  historyButton: HTMLButtonElement;
  cleanupButton: HTMLButtonElement;
  voiceButton: HTMLButtonElement;
  evidenceButton: HTMLButtonElement;
  evidenceInput: HTMLInputElement;
  evidenceList: HTMLElement;
  status: HTMLElement;
  response: HTMLElement;
  capturedList: HTMLElement;
  groupsList: HTMLElement;
}

interface LifeSpeechRecognitionAlternative {
  transcript: string;
}

interface LifeSpeechRecognitionResult {
  readonly length: number;
  readonly isFinal?: boolean;
  [index: number]: LifeSpeechRecognitionAlternative;
}

interface LifeSpeechRecognitionResultList {
  readonly length: number;
  [index: number]: LifeSpeechRecognitionResult;
}

interface LifeSpeechRecognitionEvent {
  readonly results: LifeSpeechRecognitionResultList;
}

interface LifeSpeechRecognitionErrorEvent {
  readonly error?: string;
}

interface LifeSpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: LifeSpeechRecognitionErrorEvent) => void) | null;
  onresult: ((event: LifeSpeechRecognitionEvent) => void) | null;
  abort: () => void;
  start: () => void;
  stop: () => void;
}

interface LifeSpeechRecognitionConstructor {
  new(): LifeSpeechRecognition;
}

type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: LifeSpeechRecognitionConstructor;
  webkitSpeechRecognition?: LifeSpeechRecognitionConstructor;
};

const SAMPLE_DUMP = "Need to update my DOE CR, send availability to the recruiter, pick up medicine, research that supplement, and look into a new shaft for my 9-iron.";
const MAX_EXTERNAL_INPUTS = 10;
const URL_PATTERN = /\bhttps?:\/\/[^\s<>"']+/gi;
const GROUP_RENDER_ORDER = [
  "needs_attention_today",
  "quick_wins",
  "waiting_on_someone",
  "prepared_for_review",
  "stale_needs_decision",
  "ideas_not_tasks",
  "history",
];
const CLEANUP_BUCKETS: Array<{
  key: keyof Pick<
    LifeCleanupPlan,
    "close_candidates" | "archive_candidates" | "keep_active" | "review_needed"
  >;
  label: string;
}> = [
  { key: "close_candidates", label: "Close" },
  { key: "archive_candidates", label: "Archive" },
  { key: "keep_active", label: "Keep" },
  { key: "review_needed", label: "Review" },
];
let activeRecognition: LifeSpeechRecognition | null = null;
let attachedExternalInputs: LifeExternalInput[] = [];

function renderPreparedActions(actions: LifePreparedAction[]): string {
  if (!actions.length) {
    return "";
  }
  return `
    <div class="life-prepared-actions">
      ${actions.slice(0, 2).map((action) => `
        <section class="life-prepared-action">
          <div class="life-prepared-action-heading">
            <h5>${escapeHtml(action.title)}</h5>
            <span>${escapeHtml(action.risk_level.replaceAll("_", " "))}</span>
          </div>
          <p>${escapeHtml(action.body)}</p>
          ${action.requires_approval ? '<small>Review before action.</small>' : ""}
        </section>
      `).join("")}
    </div>
  `;
}

function renderClarifications(clarifications: LifeClarification[]): string {
  if (!clarifications.length) {
    return "";
  }
  return `
    <div class="life-clarifications" aria-label="Optional clarification questions">
      ${clarifications.slice(0, 3).map((clarification) => `
        <section class="life-clarification">
          <h4>${escapeHtml(clarification.question)}</h4>
          ${clarification.assumption ? `<p>${escapeHtml(clarification.assumption)}</p>` : ""}
          ${clarification.rationale ? `<small>${escapeHtml(clarification.rationale)}</small>` : ""}
        </section>
      `).join("")}
    </div>
  `;
}

function renderAnsweredClarifications(answers: LifeClarificationAnswer[]): string {
  if (!answers.length) {
    return "";
  }
  return `
    <div class="life-answered-clarifications" aria-label="Recorded clarification answers">
      ${answers.slice(0, 3).map((answer) => `
        <section class="life-answered-clarification">
          <h4>${escapeHtml(answer.question)}</h4>
          <p>${escapeHtml(answer.answer)}</p>
          ${answer.rationale ? `<small>${escapeHtml(answer.rationale)}</small>` : ""}
        </section>
      `).join("")}
    </div>
  `;
}

function renderCleanupBucket(label: string, items: LifeLoopItem[]): string {
  if (!items.length) {
    return "";
  }
  return `
    <section class="life-cleanup-bucket">
      <div class="life-cleanup-bucket-heading">
        <h4>${escapeHtml(label)}</h4>
        <span>${items.length}</span>
      </div>
      <div class="life-cleanup-items">
        ${items.slice(0, 2).map((item) => `
          <div class="life-cleanup-row">
            <strong>${escapeHtml(loopTitle(item.loop))}</strong>
            <span>${escapeHtml(item.prepared_next_action || item.rationale || loopPreview(item.loop))}</span>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderCleanupPlan(cleanup: LifeCleanupPlan | null): string {
  if (!cleanup) {
    return "";
  }
  const buckets = CLEANUP_BUCKETS
    .map((bucket) => renderCleanupBucket(bucket.label, cleanup[bucket.key]))
    .join("");
  if (!buckets && !cleanup.recommendation) {
    return "";
  }
  return `
    <section class="life-cleanup-plan" aria-label="Cleanup recommendation">
      <div class="life-cleanup-plan-heading">
        <h3>Cleanup</h3>
        <span>${cleanup.open_count} open</span>
      </div>
      ${cleanup.recommendation ? `<p>${escapeHtml(cleanup.recommendation)}</p>` : ""}
      ${buckets ? `<div class="life-cleanup-grid">${buckets}</div>` : ""}
    </section>
  `;
}

function buildElements(): LifeFeedElements | null {
  const form = document.getElementById("life-form");
  if (!(form instanceof HTMLFormElement)) {
    return null;
  }
  return {
    form,
    input: requireElement("life-input", HTMLTextAreaElement),
    submitButton: requireElement("life-submit-btn", HTMLButtonElement),
    quickDumpButton: requireElement("life-quick-dump-btn", HTMLButtonElement),
    missingButton: requireElement("life-missing-btn", HTMLButtonElement),
    mattersButton: requireElement("life-matters-btn", HTMLButtonElement),
    quizButton: requireElement("life-quiz-btn", HTMLButtonElement),
    historyButton: requireElement("life-history-btn", HTMLButtonElement),
    cleanupButton: requireElement("life-cleanup-btn", HTMLButtonElement),
    voiceButton: requireElement("life-voice-btn", HTMLButtonElement),
    evidenceButton: requireElement("life-evidence-btn", HTMLButtonElement),
    evidenceInput: requireElement("life-evidence-input", HTMLInputElement),
    evidenceList: requireElement("life-evidence-list", HTMLElement),
    status: requireElement("life-status", HTMLElement),
    response: requireElement("life-response", HTMLElement),
    capturedList: requireElement("life-captured-list", HTMLElement),
    groupsList: requireElement("life-groups-list", HTMLElement),
  };
}

function clientTzOffsetMin(): number {
  return -new Date().getTimezoneOffset();
}

function setBusy(elements: LifeFeedElements, busy: boolean): void {
  elements.form.setAttribute("aria-busy", String(busy));
  elements.submitButton.disabled = busy;
  elements.quickDumpButton.disabled = busy;
  elements.missingButton.disabled = busy;
  elements.mattersButton.disabled = busy;
  elements.quizButton.disabled = busy;
  elements.historyButton.disabled = busy;
  elements.cleanupButton.disabled = busy;
  elements.voiceButton.disabled = busy;
  elements.evidenceButton.disabled = busy;
  elements.evidenceInput.disabled = busy;
}

function speechRecognitionConstructor(): LifeSpeechRecognitionConstructor | null {
  const speechWindow = window as SpeechRecognitionWindow;
  return speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition || null;
}

function appendVoiceText(elements: LifeFeedElements, transcript: string): void {
  const text = transcript.trim();
  if (!text) {
    return;
  }
  const current = elements.input.value.trimEnd();
  elements.input.value = current ? `${current} ${text}` : text;
  elements.input.focus();
}

function resetVoiceButton(elements: LifeFeedElements): void {
  activeRecognition = null;
  elements.voiceButton.textContent = "Voice";
  elements.voiceButton.setAttribute("aria-pressed", "false");
}

function externalInputKey(input: LifeExternalInput): string {
  return `${input.kind}:${input.source_url || input.label}`;
}

function externalKindForFile(file: File): LifeExternalInputKind {
  if (file.type.startsWith("image/")) {
    return "image";
  }
  if (file.type.startsWith("audio/")) {
    return "audio";
  }
  return "file";
}

function renderAttachedEvidence(elements: LifeFeedElements): void {
  if (!attachedExternalInputs.length) {
    elements.evidenceList.innerHTML = "";
    return;
  }
  elements.evidenceList.innerHTML = attachedExternalInputs.map((input, index) => `
    <span class="life-evidence-chip">
      <span>${escapeHtml(input.label)}</span>
      <button type="button" aria-label="Remove ${escapeHtml(input.label)}" data-life-evidence-index="${index}">x</button>
    </span>
  `).join("");
}

function addAttachedEvidence(elements: LifeFeedElements, files: FileList): void {
  const next = [...attachedExternalInputs];
  for (const file of Array.from(files)) {
    if (next.length >= MAX_EXTERNAL_INPUTS) {
      break;
    }
    const input: LifeExternalInput = {
      kind: externalKindForFile(file),
      label: file.name,
      media_type: file.type || null,
      size_bytes: file.size,
    };
    if (!next.some((existing) => externalInputKey(existing) === externalInputKey(input))) {
      next.push(input);
    }
  }
  attachedExternalInputs = next;
  elements.evidenceInput.value = "";
  renderAttachedEvidence(elements);
  elements.status.textContent = attachedExternalInputs.length
    ? "Evidence attached."
    : "No evidence selected.";
}

function removeAttachedEvidence(elements: LifeFeedElements, index: number): void {
  attachedExternalInputs = attachedExternalInputs.filter((_, itemIndex) => itemIndex !== index);
  renderAttachedEvidence(elements);
  elements.status.textContent = attachedExternalInputs.length
    ? "Evidence updated."
    : "Evidence cleared.";
}

function linkExternalInputs(message: string): LifeExternalInput[] {
  const urls = Array.from(message.matchAll(URL_PATTERN), (match) => match[0].replace(/[).,;:]+$/, ""));
  return Array.from(new Set(urls)).slice(0, MAX_EXTERNAL_INPUTS).map((url) => ({
    kind: "link",
    label: url,
    source_url: url,
  }));
}

function lifeExternalInputs(message: string): LifeExternalInput[] {
  const merged = [...attachedExternalInputs, ...linkExternalInputs(message)];
  const seen = new Set<string>();
  const result: LifeExternalInput[] = [];
  for (const input of merged) {
    const key = externalInputKey(input);
    if (seen.has(key)) {
      continue;
    }
    result.push(input);
    seen.add(key);
    if (result.length >= MAX_EXTERNAL_INPUTS) {
      break;
    }
  }
  return result;
}

function toggleVoiceInput(elements: LifeFeedElements): void {
  if (activeRecognition) {
    activeRecognition.stop();
    elements.status.textContent = "Voice stopped.";
    return;
  }
  const Recognition = speechRecognitionConstructor();
  if (!Recognition) {
    elements.status.textContent = "Voice input is not supported in this browser.";
    return;
  }

  const recognition = new Recognition();
  activeRecognition = recognition;
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = navigator.language || "en-US";
  elements.voiceButton.textContent = "Stop voice";
  elements.voiceButton.setAttribute("aria-pressed", "true");
  elements.status.textContent = "Listening...";
  recognition.onresult = (event) => {
    const transcripts: string[] = [];
    for (let index = 0; index < event.results.length; index += 1) {
      const result = event.results[index];
      const alternative = result?.[0];
      if (alternative?.transcript) {
        transcripts.push(alternative.transcript);
      }
    }
    appendVoiceText(elements, transcripts.join(" "));
    elements.status.textContent = "Voice added.";
  };
  recognition.onerror = () => {
    elements.status.textContent = "Voice input failed.";
  };
  recognition.onend = () => {
    resetVoiceButton(elements);
  };
  try {
    recognition.start();
  } catch {
    resetVoiceButton(elements);
    elements.status.textContent = "Voice input failed.";
  }
}

function renderLoopItem(item: LifeLoopItem): string {
  const title = loopTitle(item.loop);
  const nextAction = item.prepared_next_action || item.loop.next_action || "";
  const rationale = item.rationale || loopPreview(item.loop);
  const minutes = item.loop.time_minutes ? `${item.loop.time_minutes} min` : "No estimate";
  return `
    <article class="life-loop-card">
      <div class="life-loop-card-header">
        <h4>${escapeHtml(title)}</h4>
        <span class="life-state-badge">${escapeHtml(item.life_state.replaceAll("_", " "))}</span>
      </div>
      <p>${escapeHtml(rationale)}</p>
      ${nextAction ? `<p class="life-next-action">${escapeHtml(nextAction)}</p>` : ""}
      ${renderPreparedActions(item.prepared_actions || [])}
      <div class="life-loop-meta">
        <span>${escapeHtml(minutes)}</span>
        <span>${escapeHtml(item.loop.status)}</span>
      </div>
    </article>
  `;
}

function renderCaptured(response: LifeMessageResponse): string {
  const items = [...response.captured, ...response.updated];
  if (!items.length && response.mode !== "cleanup") {
    return '<p class="operator-empty">No new loop was needed. I kept related context attached.</p>';
  }
  if (response.mode === "cleanup" && response.cleanup?.applied_automatic_cleanup.length) {
    return response.cleanup.applied_automatic_cleanup.map(renderLoopItem).join("");
  }
  if (!items.length) {
    return '<p class="operator-empty">No capture changes in this turn.</p>';
  }
  return items.map(renderLoopItem).join("");
}

function renderGroups(groups: LifeLoopGroup[]): string {
  const populated = [...groups]
    .sort((left, right) => GROUP_RENDER_ORDER.indexOf(left.name) - GROUP_RENDER_ORDER.indexOf(right.name))
    .filter((group) => group.items.length > 0)
    .slice(0, 5);
  if (!populated.length) {
    return '<p class="operator-empty">No active loop groups yet.</p>';
  }
  return populated.map((group) => `
    <section class="life-group">
      <div class="life-group-heading">
        <h4>${escapeHtml(group.title)}</h4>
        <span>${group.items.length}</span>
      </div>
      <p>${escapeHtml(group.summary)}</p>
      <div class="life-group-items">
        ${group.items.slice(0, 3).map((item) => `
          <div class="life-group-row">
            <strong>${escapeHtml(loopTitle(item.loop))}</strong>
            <span>${escapeHtml(item.prepared_next_action || item.loop.next_action || item.rationale || "")}</span>
          </div>
        `).join("")}
      </div>
    </section>
  `).join("");
}

function renderUndo(cleanup: LifeCleanupPlan | null): string {
  if (!cleanup?.undo.length) {
    return "";
  }
  return `
    <div class="life-undo-strip" aria-label="Cleanup undo actions">
      ${cleanup.undo.map((undo) => `
        <button
          class="secondary"
          type="button"
          data-life-undo-loop-id="${undo.loop_id}"
          data-life-undo-event-id="${undo.expected_event_id}"
        >
          Undo archive
        </button>
      `).join("")}
    </div>
  `;
}

function renderResponse(elements: LifeFeedElements, response: LifeMessageResponse): void {
  elements.response.hidden = false;
  elements.response.innerHTML = `
    <p class="life-response-mode">${escapeHtml(response.mode)}</p>
    <p>${escapeHtml(response.reply)}</p>
    ${renderClarifications(response.clarifications || [])}
    ${renderAnsweredClarifications(response.answered_clarifications || [])}
    ${renderCleanupPlan(response.cleanup)}
    ${renderUndo(response.cleanup)}
  `;
  elements.capturedList.innerHTML = renderCaptured(response);
  elements.groupsList.innerHTML = renderGroups(response.groups);
}

async function sendLifeMessage(
  elements: LifeFeedElements,
  message: string,
): Promise<void> {
  const trimmed = message.trim();
  if (!trimmed) {
    elements.status.textContent = "Write the messy version first.";
    elements.input.focus();
    return;
  }

  setBusy(elements, true);
  elements.status.textContent = "Defragging...";
  try {
    const payload: LifeMessageRequest = {
      message: trimmed,
      external_inputs: lifeExternalInputs(trimmed),
      client_tz_offset_min: clientTzOffsetMin(),
      captured_at: new Date().toISOString(),
    };
    const response = await requestJson<LifeMessageResponse, LifeMessageRequest>(
      "/life/message",
      { method: "POST", body: payload },
      "Failed to handle Life message",
    );
    renderResponse(elements, response);
    elements.status.textContent = "Updated.";
    elements.input.value = "";
    attachedExternalInputs = [];
    renderAttachedEvidence(elements);
  } catch (error) {
    elements.status.textContent = error instanceof Error ? error.message : "Life message failed.";
  } finally {
    setBusy(elements, false);
  }
}

async function undoLifeCleanup(elements: LifeFeedElements, button: HTMLButtonElement): Promise<void> {
  const loopId = Number.parseInt(button.dataset["lifeUndoLoopId"] || "", 10);
  const expectedEventId = Number.parseInt(button.dataset["lifeUndoEventId"] || "", 10);
  if (!Number.isInteger(loopId) || !Number.isInteger(expectedEventId)) {
    return;
  }
  button.disabled = true;
  elements.status.textContent = "Restoring loop...";
  try {
    const response = await requestJson<LoopUndoResponse, { expected_event_id: number }>(
      `/loops/${loopId}/undo`,
      { method: "POST", body: { expected_event_id: expectedEventId } },
      "Failed to undo cleanup",
    );
    elements.status.textContent = `Restored ${loopTitle(response.loop)}.`;
    await sendLifeMessage(elements, "What matters today?");
  } catch (error) {
    elements.status.textContent = error instanceof Error ? error.message : "Undo failed.";
    button.disabled = false;
  }
}

export function bootstrapLifeFeed(): void {
  const elements = buildElements();
  if (!elements) {
    return;
  }
  attachedExternalInputs = [];
  renderAttachedEvidence(elements);

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendLifeMessage(elements, elements.input.value);
  });
  elements.quickDumpButton.addEventListener("click", () => {
    elements.input.value = SAMPLE_DUMP;
    elements.input.focus();
  });
  elements.missingButton.addEventListener("click", () => {
    void sendLifeMessage(elements, "What am I missing?");
  });
  elements.mattersButton.addEventListener("click", () => {
    void sendLifeMessage(elements, "What matters today?");
  });
  elements.quizButton.addEventListener("click", () => {
    void sendLifeMessage(elements, "Quiz me on what is open.");
  });
  elements.historyButton.addEventListener("click", () => {
    void sendLifeMessage(elements, "Show my history and archive.");
  });
  elements.cleanupButton.addEventListener("click", () => {
    void sendLifeMessage(elements, "Review my open loops and clean up what your authority allows.");
  });
  elements.voiceButton.addEventListener("click", () => {
    toggleVoiceInput(elements);
  });
  elements.evidenceButton.addEventListener("click", () => {
    elements.evidenceInput.click();
  });
  elements.evidenceInput.addEventListener("change", () => {
    if (elements.evidenceInput.files) {
      addAttachedEvidence(elements, elements.evidenceInput.files);
    }
  });
  elements.evidenceList.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>("[data-life-evidence-index]")
      : null;
    if (!button) {
      return;
    }
    const index = Number.parseInt(button.dataset["lifeEvidenceIndex"] || "", 10);
    if (Number.isInteger(index)) {
      removeAttachedEvidence(elements, index);
    }
  });
  elements.response.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>("[data-life-undo-loop-id]")
      : null;
    if (button) {
      void undoLifeCleanup(elements, button);
    }
  });
}
