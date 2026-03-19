/**
 * bootstrap.ts - Capture, do, and recall surface runtime bootstrap.
 *
 * Purpose:
 *   Initialize the shared work-surface runtime and wire up capture, do, and
 *   recall modules for the single-frontend cutover.
 *
 * Responsibilities:
 *   - Initialize capture/do/recall modules with DOM elements.
 *   - Attach shared event handlers for those surfaces.
 *   - Load initial data and keep surface refresh events synchronized.
 *   - Keep capture-specific notification prompts working in the unified runtime.
 *
 * Scope:
 *   - Surface runtime bootstrap and DOM wiring only.
 *
 * Usage:
 *   - Imported by frontend/src/surface-runtime.ts.
 *
 * Invariants/Assumptions:
 *   - The Vite shell renders the required capture/do/recall DOM ids.
 *   - Feature modules own their business logic once initialized.
 */

import type { LoopCaptureRequest } from "../domain";
import * as api from "./api";
import * as bulk from "./bulk";
import * as chat from "./chat";
import * as comments from "./comments";
import type { LegacySurfaceTab, SurfaceLoop } from "./contracts";
import * as duplicates from "./duplicates";
import * as keyboard from "./keyboard";
import * as loop from "./loop";
import * as memory from "./memory";
import * as modals from "./modals";
import * as next from "./next";
import * as rag from "./rag";
import * as sse from "./sse";
import * as state from "./state";
import * as suggestions from "./suggestions";
import * as timer from "./timer";
import {
  closestFromEventTarget,
  dueDateInputValueFromLoop,
  formatDateInputValue,
  messageFromError,
  parseUserDateInput,
  snoozeDurationToUtc,
} from "./utils";
import { updateBulkActionBar } from "./bulk";

interface ActivateSurfaceOptions {
  doQuery?: string;
}

type CaptureResult = SurfaceLoop & {
  queued?: boolean;
  offline?: boolean;
};

function requireElement<T extends HTMLElement>(id: string, type: { new (): T }): T {
  const element = document.getElementById(id);
  if (!(element instanceof type)) {
    throw new Error(`Missing required element #${id}`);
  }
  return element;
}

function requireQueryElement<T extends Element>(selector: string, type: { new (): T }, root: ParentNode = document): T {
  const element = root.querySelector(selector);
  if (!(element instanceof type)) {
    throw new Error(`Missing required element ${selector}`);
  }
  return element;
}

// ========================================
// DOM Element References
// ========================================

function buildElements() {
  return {
    inbox: requireElement("inbox", HTMLElement),
    status: requireElement("status", HTMLElement),
    form: requireElement("capture-form", HTMLFormElement),
    rawText: requireElement("raw-text", HTMLTextAreaElement),
    actionable: requireElement("actionable", HTMLInputElement),
    scheduled: requireElement("scheduled", HTMLInputElement),
    blocked: requireElement("blocked", HTMLInputElement),
    dueDate: requireElement("due-date", HTMLInputElement),
    nextAction: requireElement("next-action", HTMLInputElement),
    timeMinutes: requireElement("time-minutes", HTMLInputElement),
    activationEnergy: requireElement("activation-energy", HTMLSelectElement),
    project: requireElement("project", HTMLInputElement),
    tags: requireElement("tags", HTMLInputElement),
    captureDetails: requireElement("capture-details", HTMLElement),
    captureDetailsToggle: requireElement("capture-details-toggle", HTMLButtonElement),
    statusFilter: requireElement("status-filter", HTMLSelectElement),
    tagFilter: requireElement("tag-filter", HTMLSelectElement),
    queryFilter: requireElement("query-filter", HTMLInputElement),
    queryModeFilter: requireElement("query-mode-filter", HTMLSelectElement),
    viewFilter: requireElement("view-filter", HTMLSelectElement),
    saveViewBtn: requireElement("save-view-btn", HTMLButtonElement),
    importFile: requireElement("import-file", HTMLInputElement),
    templateSelect: requireElement("template-select", HTMLSelectElement),
    inboxMain: requireElement("inbox-main", HTMLElement),
    nextMain: requireElement("next-main", HTMLElement),
    chatMain: requireElement("chat-main", HTMLElement),
    memoryMain: requireElement("memory-main", HTMLElement),
    ragMain: requireElement("rag-main", HTMLElement),
    nextBuckets: requireElement("next-buckets", HTMLElement),
    nextQueryFilter: requireElement("do-query-filter", HTMLInputElement),
    refreshNextBtn: requireElement("refresh-next-btn", HTMLButtonElement),
    chatActionCards: requireElement("chat-action-cards", HTMLElement),
    chatMessages: requireElement("chat-messages", HTMLElement),
    chatInput: requireElement("chat-input", HTMLInputElement),
    chatForm: requireElement("chat-form", HTMLFormElement),
    chatThreadStatus: requireElement("chat-thread-status", HTMLElement),
    chatResetButton: requireElement("chat-reset-btn", HTMLButtonElement),
    chatToolMode: requireElement("chat-tool-mode", HTMLSelectElement),
    chatLoopContext: requireElement("chat-loop-context", HTMLInputElement),
    chatMemoryContext: requireElement("chat-memory-context", HTMLInputElement),
    chatMemoryLimit: requireElement("chat-memory-limit", HTMLInputElement),
    chatRagContext: requireElement("chat-rag-context", HTMLInputElement),
    chatRagK: requireElement("chat-rag-k", HTMLInputElement),
    chatRagScope: requireElement("chat-rag-scope", HTMLInputElement),
    chatControlsStatus: requireElement("chat-controls-status", HTMLElement),
    chatRuntimeStatus: requireElement("chat-runtime-status", HTMLElement),
    memoryActionCards: requireElement("memory-action-cards", HTMLElement),
    memoryList: requireElement("memory-list", HTMLElement),
    memoryStatus: requireElement("memory-status", HTMLElement),
    memoryFilterForm: requireElement("memory-filter-form", HTMLFormElement),
    memoryQuery: requireElement("memory-query", HTMLInputElement),
    memoryCategoryFilter: requireElement("memory-category-filter", HTMLSelectElement),
    memorySourceFilter: requireElement("memory-source-filter", HTMLSelectElement),
    memoryMinPriority: requireElement("memory-min-priority", HTMLInputElement),
    memoryClearFiltersBtn: requireElement("memory-clear-filters-btn", HTMLButtonElement),
    memoryRefreshBtn: requireElement("memory-refresh-btn", HTMLButtonElement),
    memoryLoadMoreBtn: requireElement("memory-load-more-btn", HTMLButtonElement),
    memoryCreateForm: requireElement("memory-create-form", HTMLFormElement),
    memoryKey: requireElement("memory-key", HTMLInputElement),
    memoryContent: requireElement("memory-content", HTMLTextAreaElement),
    memoryCategory: requireElement("memory-category", HTMLSelectElement),
    memoryPriority: requireElement("memory-priority", HTMLInputElement),
    memorySource: requireElement("memory-source", HTMLSelectElement),
    memoryMetadata: requireElement("memory-metadata", HTMLTextAreaElement),
    ragActionCards: requireElement("rag-action-cards", HTMLElement),
    ragInput: requireElement("rag-input", HTMLInputElement),
    ragForm: requireElement("rag-form", HTMLFormElement),
    ragAnswer: requireElement("rag-answer", HTMLElement),
    ragEmptyState: requireElement("rag-empty-state", HTMLElement),
    ragFocusIngestBtn: requireElement("rag-focus-ingest-btn", HTMLButtonElement),
    ragIngestForm: requireElement("rag-ingest-form", HTMLFormElement),
    ragIngestPath: requireElement("rag-ingest-path", HTMLInputElement),
    ragIngestMode: requireElement("rag-ingest-mode", HTMLSelectElement),
    ragIngestRecursive: requireElement("rag-ingest-recursive", HTMLInputElement),
    ragIngestStatus: requireElement("rag-ingest-status", HTMLElement),
    bulkActionBar: requireElement("bulk-action-bar", HTMLElement),
    helpModal: requireElement("help-modal", HTMLElement),
    appDialog: requireElement("app-dialog", HTMLElement),
  };
}

type SurfaceBootstrapElements = ReturnType<typeof buildElements>;

let elements!: SurfaceBootstrapElements;
let dataManagementStatuses: HTMLElement[] = [];
let exportButtons: HTMLElement[] = [];
let importButtons: HTMLElement[] = [];

const MOBILE_CAPTURE_MEDIA = "(max-width: 640px)";
const CAPTURE_DETAILS_STORAGE_KEY = "cloop.captureDetails.mobileExpanded";
const LEGACY_SURFACE_TABS = new Set<LegacySurfaceTab>(["inbox", "next", "chat", "memory", "rag"]);
let captureMediaQuery: MediaQueryList | null = null;

function normalizeLegacyTab(tabName: unknown): LegacySurfaceTab {
  return typeof tabName === "string" && LEGACY_SURFACE_TABS.has(tabName as LegacySurfaceTab)
    ? (tabName as LegacySurfaceTab)
    : "inbox";
}

function isMobileCaptureViewport(): boolean {
  return captureMediaQuery?.matches ?? window.matchMedia(MOBILE_CAPTURE_MEDIA).matches;
}

function readCaptureDetailsPreference(): boolean | null {
  try {
    const storedValue = window.localStorage.getItem(CAPTURE_DETAILS_STORAGE_KEY);
    if (storedValue === "true") {
      return true;
    }
    if (storedValue === "false") {
      return false;
    }
  } catch {
    // Ignore storage access issues and fall back to viewport defaults.
  }
  return null;
}

function writeCaptureDetailsPreference(expanded: boolean): void {
  try {
    window.localStorage.setItem(CAPTURE_DETAILS_STORAGE_KEY, expanded ? "true" : "false");
  } catch {
    // Ignore storage access issues and keep the current in-memory state.
  }
}

function setDataManagementStatus(message: string, { isError = false }: { isError?: boolean } = {}): void {
  dataManagementStatuses.forEach((element) => {
    element.textContent = message;
    element.classList.toggle("is-error", isError);
  });
}

// ========================================
// Surface Activation
// ========================================

async function activateSurfaceInternal(
  requestedTabName: unknown,
  options: ActivateSurfaceOptions = {},
): Promise<void> {
  const tabName = normalizeLegacyTab(requestedTabName);

  if (tabName === "inbox") {
    await Promise.all([
      loop.loadInbox(),
      populateTemplateDropdown(),
      populateTagFilter(),
      populateViewDropdown(),
    ]);
  }
  if (tabName === "next") {
    await next.loadNext({ query: options.doQuery ?? "" });
  }
  if (tabName === "memory") {
    await memory.loadMemories();
  }

  state.updateState({ activeTab: tabName });
}

function setCaptureDetailsExpanded(expanded: boolean, { persist = false }: { persist?: boolean } = {}): void {
  elements.captureDetails.hidden = !expanded;
  elements.captureDetailsToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  elements.captureDetailsToggle.textContent = expanded ? "Hide details" : "Add details";

  if (persist && isMobileCaptureViewport()) {
    writeCaptureDetailsPreference(expanded);
  }
}

function syncCaptureDisclosureToViewport(): void {
  if (isMobileCaptureViewport()) {
    const mobilePreference = readCaptureDetailsPreference();
    setCaptureDetailsExpanded(mobilePreference ?? false);
    return;
  }

  setCaptureDetailsExpanded(true);
}

function initializeCaptureDisclosure(): void {
  captureMediaQuery = window.matchMedia(MOBILE_CAPTURE_MEDIA);
  syncCaptureDisclosureToViewport();

  const handleViewportChange = (): void => syncCaptureDisclosureToViewport();
  if (typeof captureMediaQuery.addEventListener === "function") {
    captureMediaQuery.addEventListener("change", handleViewportChange);
  } else if (typeof captureMediaQuery.addListener === "function") {
    captureMediaQuery.addListener(handleViewportChange);
  }

  elements.captureDetailsToggle.addEventListener("click", () => {
    const expanded = elements.captureDetailsToggle.getAttribute("aria-expanded") === "true";
    setCaptureDetailsExpanded(!expanded, { persist: true });
  });
}

function normalizeDueDateField(): { parsedDate: ReturnType<typeof parseUserDateInput>; isValid: boolean } {
  const rawValue = elements.dueDate.value.trim();
  if (!rawValue) {
    elements.dueDate.value = "";
    elements.dueDate.removeAttribute("aria-invalid");
    return { parsedDate: null, isValid: true };
  }

  const parsedDate = parseUserDateInput(rawValue);
  if (!parsedDate) {
    elements.dueDate.setAttribute("aria-invalid", "true");
    return { parsedDate: null, isValid: false };
  }

  elements.dueDate.value = parsedDate.displayValue;
  elements.dueDate.removeAttribute("aria-invalid");
  return { parsedDate, isValid: true };
}

// ========================================
// Capture Loop
// ========================================

async function captureLoop(event: SubmitEvent): Promise<void> {
  event.preventDefault();

  const { parsedDate, isValid: isDueDateValid } = normalizeDueDateField();
  if (!isDueDateValid) {
    elements.status.textContent = "Enter a valid due date as MM/DD/YYYY.";
    elements.dueDate.focus();
    elements.dueDate.select();
    return;
  }

  const now = new Date();
  const templateId = elements.templateSelect.value;
  const payload: LoopCaptureRequest = {
    raw_text: elements.rawText.value.trim(),
    captured_at: now.toISOString(),
    client_tz_offset_min: -now.getTimezoneOffset(),
    actionable: elements.actionable.checked,
    scheduled: elements.scheduled.checked,
    blocked: elements.blocked.checked,
  };

  if (templateId) {
    payload.template_id = Number.parseInt(templateId, 10);
  }

  if (parsedDate) {
    payload.due_date = parsedDate.isoDate;
  }
  if (elements.nextAction.value.trim()) {
    payload.next_action = elements.nextAction.value.trim();
  }
  if (elements.timeMinutes.value) {
    payload.time_minutes = Number.parseInt(elements.timeMinutes.value, 10);
  }
  if (elements.activationEnergy.value) {
    payload.activation_energy = Number.parseInt(elements.activationEnergy.value, 10);
  }
  if (elements.project.value.trim()) {
    payload.project = elements.project.value.trim();
  }
  if (elements.tags.value.trim()) {
    payload.tags = elements.tags.value.split(",")
      .map((tag) => tag.trim())
      .filter((tag) => tag.length > 0);
  }

  if (!payload.raw_text && !templateId) {
    elements.status.textContent = "Type something first.";
    return;
  }

  elements.status.textContent = navigator.onLine ? "Saving..." : "Saving offline...";

  if (!state.state.notificationPermissionRequested) {
    state.updateState({ notificationPermissionRequested: true });
    void requestNotificationPermission();
  }

  try {
    const result = await api.captureLoop(payload) as CaptureResult;

    if (result.queued && result.offline) {
      elements.status.textContent = "Saved offline - will sync when connected";
    } else {
      loop.replaceLoop(result);
      elements.status.textContent = "Saved. Enrichment queued.";
    }

    elements.rawText.value = "";
    elements.actionable.checked = false;
    elements.scheduled.checked = false;
    elements.blocked.checked = false;
    elements.templateSelect.value = "";
    elements.dueDate.value = "";
    elements.nextAction.value = "";
    elements.timeMinutes.value = "";
    elements.activationEnergy.value = "";
    elements.project.value = "";
    elements.tags.value = "";
  } catch (error: unknown) {
    elements.status.textContent = messageFromError(error, "Capture failed.");
  }
}

// ========================================
// Templates
// ========================================

async function loadTemplates() {
  if (state.state.templatesCache) {
    return state.state.templatesCache;
  }

  const templates = await api.fetchTemplates();
  state.updateState({ templatesCache: templates });
  return templates;
}

async function populateTemplateDropdown(): Promise<void> {
  const templates = await loadTemplates();

  while (elements.templateSelect.options.length > 1) {
    elements.templateSelect.remove(1);
  }

  templates.forEach((template) => {
    const option = document.createElement("option");
    option.value = String(template["id"]);
    option.textContent = String(template["name"]) + (template["is_system"] ? " (system)" : "");
    elements.templateSelect.appendChild(option);
  });
}

async function populateTagFilter() {
  const tags = await api.fetchTags();
  const currentValue = elements.tagFilter.value;

  while (elements.tagFilter.options.length > 1) {
    elements.tagFilter.remove(1);
  }

  tags.forEach((tag) => {
    const option = document.createElement("option");
    option.value = tag;
    option.textContent = tag;
    elements.tagFilter.appendChild(option);
  });

  elements.tagFilter.value = tags.includes(currentValue) ? currentValue : "";
}

async function populateViewDropdown(): Promise<void> {
  const views = await api.fetchViews();
  const currentValue = elements.viewFilter.value;

  while (elements.viewFilter.options.length > 1) {
    elements.viewFilter.remove(1);
  }

  views.forEach((view) => {
    const option = document.createElement("option");
    option.value = String(view["id"]);
    option.textContent = String(view["name"]);
    option.dataset["query"] = typeof view["query"] === "string" ? view["query"] : "";
    elements.viewFilter.appendChild(option);
  });

  elements.viewFilter.value = views.some((view) => String(view["id"]) === currentValue) ? currentValue : "";
}

async function saveAsTemplate(loopId: number | string | null | undefined): Promise<void> {
  const result = await modals.promptDialog({
    eyebrow: "Template",
    title: "Save Loop as Template",
    description: "Create a reusable template from this loop without leaving the inbox.",
    confirmLabel: "Save template",
    fields: [{
      name: "name",
      label: "Template name",
      placeholder: "Weekly review setup",
      required: true,
      maxLength: 120,
      autocomplete: "off",
    }],
    validate: (values) => {
      const name = values["name"];
      if (!name) {
        return "Enter a template name.";
      }
      return null;
    },
  });
  const templateName = result?.["name"];
  if (!loopId || !templateName) {
    return;
  }

  try {
    const template = await api.saveLoopAsTemplate(loopId, templateName);
    elements.status.textContent = `Template "${template["name"]}" created!`;
    state.updateState({ templatesCache: null });
    await populateTemplateDropdown();
  } catch (error: unknown) {
    elements.status.textContent = messageFromError(error, "Failed to save template.");
  }
}

// ========================================
// Import/Export
// ========================================

function downloadExport(payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  anchor.download = `cloop-loops-${stamp}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function exportLoops(): Promise<void> {
  elements.status.textContent = "Exporting...";
  setDataManagementStatus("Exporting data...");
  try {
    const payload = await api.exportLoops();
    downloadExport(payload);
    elements.status.textContent = "Exported.";
    setDataManagementStatus("Exported loop snapshot.");
  } catch (error: unknown) {
    const message = messageFromError(error, "Export failed.");
    elements.status.textContent = message;
    setDataManagementStatus(message, { isError: true });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function importLoops(file: File): Promise<void> {
  elements.status.textContent = "Importing...";
  setDataManagementStatus("Importing data...");
  try {
    const text = await file.text();
    let payload: unknown;
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      elements.status.textContent = "Invalid JSON file.";
      setDataManagementStatus("Invalid JSON file.", { isError: true });
      return;
    }
    const loops = Array.isArray(payload)
      ? payload
      : isRecord(payload) && Array.isArray(payload["loops"])
        ? payload["loops"]
        : [];
    const result = await api.importLoops(loops);
    const importedCount = typeof result["imported"] === "number" ? result["imported"] : 0;
    elements.status.textContent = `Imported ${importedCount} loops.`;
    setDataManagementStatus(`Imported ${importedCount} loops.`);
    await loop.loadInbox();
  } catch (error: unknown) {
    const message = messageFromError(error, "Import failed.");
    elements.status.textContent = message;
    setDataManagementStatus(message, { isError: true });
  }
}

// ========================================
// PWA and Notifications
// ========================================

async function requestNotificationPermission() {
  if (!("Notification" in window)) return false;
  if (Notification.permission === "granted") {
    // Also subscribe to push notifications
    await subscribeToPush();
    return true;
  }
  if (Notification.permission !== "denied") {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      await subscribeToPush();
      return true;
    }
  }
  return false;
}

async function subscribeToPush(): Promise<void> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return;
  }

  try {
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
      });
    }

    const response = await fetch("/loops/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        keys: {
          p256dh: arrayBufferToBase64(subscription.getKey("p256dh")),
          auth: arrayBufferToBase64(subscription.getKey("auth")),
        },
      }),
    });

    if (!response.ok) {
      console.error("Failed to register push subscription:", await response.text());
    }
  } catch (error: unknown) {
    console.error("Push subscription failed:", error);
  }
}

function arrayBufferToBase64(buffer: ArrayBuffer | null): string {
  if (!buffer) {
    return "";
  }
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < bytes.byteLength; index += 1) {
    const byte = bytes[index];
    if (byte === undefined) {
      continue;
    }
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

// ========================================
// Event Handlers Setup
// ========================================

function syncLoopQueryModeUi(): void {
  const isSemantic = elements.queryModeFilter.value === "semantic";
  elements.queryFilter.placeholder = isSemantic
    ? "e.g., buy groceries before the weekend"
    : "e.g., status:inbox due:today";
  elements.saveViewBtn.disabled = isSemantic;
  elements.saveViewBtn.title = isSemantic
    ? "Saved views currently support DSL queries only"
    : "Save current DSL query as a view";
}

function setupEventHandlers(): void {
  elements.form.addEventListener("submit", (event) => {
    void captureLoop(event);
  });
  elements.dueDate.addEventListener("input", () => {
    const formattedValue = formatDateInputValue(elements.dueDate.value);
    if (elements.dueDate.value !== formattedValue) {
      elements.dueDate.value = formattedValue;
    }
    elements.dueDate.removeAttribute("aria-invalid");
  });
  elements.dueDate.addEventListener("blur", () => {
    normalizeDueDateField();
  });
  elements.chatForm.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    const text = elements.chatInput.value.trim();
    if (!text) {
      return;
    }
    elements.chatInput.value = "";
    void chat.submitChat(text);
  });
  elements.ragForm.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    const question = elements.ragInput.value.trim();
    if (!question) {
      return;
    }
    elements.ragInput.value = "";
    void rag.submitRagQuestion(question);
  });
  elements.ragIngestForm.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    void rag.submitIngestPath();
  });
  elements.ragFocusIngestBtn.addEventListener("click", () => {
    rag.handleEmptyStateAction();
  });

  elements.statusFilter.addEventListener("change", () => {
    elements.queryFilter.value = "";
    elements.viewFilter.value = "";
    void loop.loadInbox();
  });
  elements.tagFilter.addEventListener("change", () => {
    elements.queryFilter.value = "";
    elements.viewFilter.value = "";
    void loop.loadInbox();
  });
  elements.queryModeFilter.addEventListener("change", () => {
    elements.viewFilter.value = "";
    syncLoopQueryModeUi();
    if (elements.queryFilter.value.trim()) {
      void loop.loadInbox();
    }
  });
  elements.queryFilter.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      elements.viewFilter.value = "";
      elements.statusFilter.value = "all";
      elements.tagFilter.value = "";
      void loop.loadInbox();
    }
  });
  elements.viewFilter.addEventListener("change", () => {
    const selected = elements.viewFilter.selectedOptions[0];
    const savedQuery = selected?.dataset["query"];
    if (savedQuery) {
      elements.queryFilter.value = savedQuery;
      elements.queryModeFilter.value = "dsl";
      syncLoopQueryModeUi();
      elements.statusFilter.value = "all";
      elements.tagFilter.value = "";
      void loop.loadInbox();
    }
  });

  elements.saveViewBtn.addEventListener("click", () => {
    void (async () => {
      const query = elements.queryFilter.value.trim();
      if (elements.queryModeFilter.value === "semantic") {
        elements.status.textContent = "Saved views currently support DSL queries only.";
        return;
      }
      if (!query) {
        elements.status.textContent = "Enter a query first.";
        return;
      }
      const result = await modals.promptDialog({
        eyebrow: "Saved view",
        title: "Save Current View",
        description: `Store this query for quick reuse:\n${query}`,
        confirmLabel: "Save view",
        fields: [{
          name: "name",
          label: "View name",
          placeholder: "Due today",
          required: true,
          maxLength: 120,
          autocomplete: "off",
        }],
        validate: (values) => {
          const name = values["name"];
          if (!name) {
            return "Enter a view name.";
          }
          return null;
        },
      });
      const viewName = result?.["name"];
      if (!viewName) {
        return;
      }
      try {
        await api.saveView(viewName, query);
        elements.status.textContent = "View saved.";
        await populateViewDropdown();
      } catch (error: unknown) {
        elements.status.textContent = messageFromError(error, "Failed to save view.");
      }
    })();
  });
  exportButtons.forEach((button) => button.addEventListener("click", () => {
    void exportLoops();
  }));
  importButtons.forEach((button) => {
    button.addEventListener("click", () => elements.importFile.click());
  });
  elements.importFile.addEventListener("change", (event: Event) => {
    const fileInput = event.currentTarget instanceof HTMLInputElement ? event.currentTarget : elements.importFile;
    const file = fileInput.files?.[0];
    if (file) {
      void importLoops(file);
    }
    fileInput.value = "";
  });
  elements.refreshNextBtn.addEventListener("click", () => {
    void next.loadNext({ query: elements.nextQueryFilter.value.trim() });
  });
  elements.nextQueryFilter.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void next.loadNext({ query: elements.nextQueryFilter.value.trim() });
    }
  });

  document.addEventListener("click", (event: MouseEvent) => {
    const bulkButton = closestFromEventTarget<HTMLElement>(event.target, "[data-bulk-action]");
    if (bulkButton) {
      void bulk.handleBulkAction(bulkButton.dataset["bulkAction"] ?? "");
      updateBulkActionBar();
      return;
    }

    if (!closestFromEventTarget(event.target, ".snooze-wrapper")) {
      document.querySelectorAll<HTMLElement>(".snooze-dropdown.visible").forEach((dropdown) => {
        dropdown.classList.remove("visible");
      });
    }
  });
}

// ========================================
// Loop Card Event Handlers
// ========================================

function setupLoopCardHandlers(container: HTMLElement): void {
  const applyDueUpdateAndMaybeClose = (
    target: HTMLElement,
    { blurTarget = false }: { blurTarget?: boolean } = {},
  ): void => {
    void Promise.resolve(loop.applyInlineUpdate(target)).then((shouldClose) => {
      if (shouldClose === false) {
        return;
      }
      void import("./render").then((module) => {
        const card = target.closest(".loop-card");
        if (card instanceof HTMLElement) {
          module.setDueEditorExpanded(card, false);
        }
      });
      if (blurTarget) {
        target.blur();
      }
    });
  };

  container.addEventListener("change", (event: Event) => {
    const checkbox = closestFromEventTarget<HTMLInputElement>(event.target, ".loop-checkbox");
    if (checkbox) {
      const loopId = Number.parseInt(checkbox.dataset["loopId"] ?? "", 10);
      if (!Number.isInteger(loopId)) {
        return;
      }
      if ((event as MouseEvent).shiftKey && state.state.lastClickedLoopId !== null && state.state.lastClickedLoopId !== loopId) {
        state.selectLoopRange(state.state.lastClickedLoopId, loopId);
        checkbox.checked = true;
      } else {
        state.toggleLoopSelection(loopId, checkbox.checked);
      }
      state.updateState({ lastClickedLoopId: loopId });
      event.stopPropagation();
      updateBulkActionBar();
      return;
    }

    const recurrenceToggle = closestFromEventTarget<HTMLInputElement>(event.target, "[data-recurrence-toggle]");
    if (recurrenceToggle?.type === "checkbox") {
      const loopId = recurrenceToggle.dataset["recurrenceToggle"];
      if (!loopId) {
        return;
      }
      const card = recurrenceToggle.closest(".loop-card");
      const scheduleInput = card?.querySelector<HTMLInputElement>(`[data-recurrence-schedule="${loopId}"]`) ?? null;
      const rrule = scheduleInput?.value.trim() || "";

      loop.toggleRecurrenceSection(loopId, recurrenceToggle.checked);

      if (recurrenceToggle.checked && rrule) {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        void loop.updateRecurrence(loopId, rrule, timezone, true);
      } else if (!recurrenceToggle.checked) {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        void loop.updateRecurrence(loopId, "", timezone, false);
      }
      return;
    }

    const scheduleInput = closestFromEventTarget<HTMLInputElement>(event.target, ".recurrence-schedule-input");
    if (scheduleInput) {
      const loopId = scheduleInput.dataset["recurrenceSchedule"];
      if (!loopId) {
        return;
      }
      const card = scheduleInput.closest(".loop-card");
      const toggle = card?.querySelector<HTMLInputElement>(`[data-recurrence-toggle="${loopId}"]`) ?? null;

      if (toggle?.checked && scheduleInput.value.trim()) {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        void loop.updateRecurrence(loopId, scheduleInput.value.trim(), timezone, true);
      }
      return;
    }

    const snoozeDatetime = closestFromEventTarget<HTMLInputElement>(event.target, ".snooze-datetime");
    if (snoozeDatetime) {
      const loopId = snoozeDatetime.dataset["snoozeCustom"];
      const localTime = snoozeDatetime.value;
      if (loopId && localTime) {
        void loop.snoozeLoop(loopId, new Date(localTime).toISOString());
        const dropdown = snoozeDatetime.closest(".snooze-dropdown");
        if (dropdown instanceof HTMLElement) {
          dropdown.classList.remove("visible");
        }
      }
    }

    const fieldTarget = event.target instanceof HTMLElement ? event.target : null;
    const fieldName = fieldTarget?.dataset["field"];
    if (fieldTarget && fieldName && !["due_date", "due_time"].includes(fieldName)) {
      void loop.applyInlineUpdate(fieldTarget);
    }
  });

  container.addEventListener("click", (event: MouseEvent) => {
    const button = closestFromEventTarget<HTMLButtonElement>(event.target, "button");
    if (button) {
      const action = button.dataset["action"];
      const loopId = button.dataset["id"];
      if (action === "complete" && loopId) {
        loop.showCompletionNote(loopId);
      } else if (action === "toggle-compact") {
        loop.toggleCompactCard(button.closest(".loop-card")?.getAttribute("data-loop-id"));
      } else if (action === "edit-due") {
        void import("./render").then((module) => {
          const card = button.closest(".loop-card");
          if (card instanceof HTMLElement) {
            module.setDueEditorExpanded(card, true);
          }
        });
        event.preventDefault();
      } else if (action === "toggle-card-body") {
        loop.toggleMobileCardText(button.closest(".loop-card")?.getAttribute("data-loop-id"));
      } else if (action === "confirm-complete" && loopId) {
        const card = button.closest(".loop-card");
        const input = card?.querySelector<HTMLInputElement | HTMLTextAreaElement>(".completion-note-input") ?? null;
        if (input) {
          input.dataset["skipComplete"] = "true";
        }
        void loop.confirmComplete(loopId, input?.value || "");
      } else if (action === "cancel-complete" && loopId) {
        loop.hideCompletionNote(loopId);
      } else if (action === "enrich" && loopId) {
        void loop.enrichLoop(loopId);
      } else if (action === "refresh" && loopId) {
        void loop.refreshLoop(loopId);
      } else if (action === "timer-toggle" && loopId) {
        void timer.toggleTimer(loopId);
      } else if (action === "snooze" && loopId) {
        event.stopPropagation();
        loop.toggleSnoozeDropdown(loopId);
      } else if (action === "edit-tags") {
        const tagsWrap = button.closest(".tags-edit");
        if (tagsWrap instanceof HTMLElement) {
          tagsWrap.classList.add("editing");
          const input = tagsWrap.querySelector<HTMLInputElement>(".tag-input");
          if (input) {
            input.value = "";
            input.focus();
          }
        }
      } else if (action === "remove-tag") {
        const card = button.closest(".loop-card");
        const tag = button.dataset["tag"];
        const cardLoopId = card?.getAttribute("data-loop-id");
        if (card instanceof HTMLElement && cardLoopId && tag) {
          void loop.removeTag(cardLoopId, tag, card);
        }
      } else if (action === "save-template") {
        void saveAsTemplate(loopId);
      } else if (action === "clear-due") {
        const card = button.closest(".loop-card");
        const dueDateInput = card?.querySelector<HTMLInputElement>('[data-field="due_date"]') ?? null;
        const dueTimeInput = card?.querySelector<HTMLInputElement>('[data-field="due_time"]') ?? null;
        if (dueDateInput) {
          dueDateInput.value = "";
        }
        if (dueTimeInput) {
          dueTimeInput.value = "";
        }
        if (dueDateInput) {
          applyDueUpdateAndMaybeClose(dueDateInput);
        }
      }
    }

    const snoozeOption = closestFromEventTarget<HTMLElement>(event.target, ".snooze-option");
    if (snoozeOption) {
      const dropdown = snoozeOption.closest(".snooze-dropdown");
      const loopId = dropdown instanceof HTMLElement ? dropdown.dataset["snoozeDropdown"] : null;
      const duration = snoozeOption.dataset["snoozeDuration"];
      if (loopId && duration) {
        const utcTime = snoozeDurationToUtc(duration);
        if (utcTime) {
          void loop.snoozeLoop(loopId, utcTime);
          if (dropdown instanceof HTMLElement) {
            dropdown.classList.remove("visible");
          }
        }
      }
    }
  });

  container.addEventListener("pointerdown", (event: PointerEvent) => {
    const button = closestFromEventTarget<HTMLButtonElement>(event.target, "button");
    if (button?.dataset["action"] === "cancel-complete") {
      const card = button.closest(".loop-card");
      const input = card?.querySelector<HTMLInputElement | HTMLTextAreaElement>(".completion-note-input") ?? null;
      if (input) {
        input.dataset["skipComplete"] = "true";
      }
    }
  }, true);

  container.addEventListener("focusout", (event: FocusEvent) => {
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      if (target.classList.contains("completion-note-input")) {
        if (target.dataset["skipComplete"]) {
          delete target.dataset["skipComplete"];
          return;
        }
        const card = target.closest(".loop-card");
        const loopId = card?.getAttribute("data-loop-id");
        if (!loopId) {
          return;
        }
        const mode = target.dataset["mode"] || "complete";
        if (mode === "complete") {
          void loop.confirmComplete(loopId, target.value);
        } else if (mode === "edit" && target instanceof HTMLInputElement) {
          void loop.saveCompletionNote(loopId, target);
        }
        return;
      }

      if (target.classList.contains("tag-input") && target instanceof HTMLInputElement) {
        void loop.appendTagsFromInput(target);
        return;
      }

      const field = target.dataset["field"];
      if (field && ["due_date", "due_time"].includes(field)) {
        const dueField = target.closest("[data-due-field]");
        if (dueField instanceof HTMLElement && dueField.contains(event.relatedTarget as Node | null)) {
          return;
        }
        applyDueUpdateAndMaybeClose(target);
      }
    }
  });

  container.addEventListener("input", (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
      return;
    }
    if (target instanceof HTMLTextAreaElement && target.dataset["field"] === "next_action") {
      void import("./render").then((module) => module.autoResizeTextarea(target));
    } else if (target.dataset["field"] === "due_date") {
      const formattedValue = formatDateInputValue(target.value);
      if (target.value !== formattedValue) {
        target.value = formattedValue;
      }
      target.removeAttribute("aria-invalid");
    }
  });

  container.addEventListener("focus", (event: FocusEvent) => {
    const target = event.target;
    if (target instanceof HTMLTextAreaElement && target.dataset["field"] === "next_action") {
      void import("./render").then((module) => module.autoResizeTextarea(target));
    }
  }, true);

  container.addEventListener("keydown", (event: KeyboardEvent) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
      return;
    }

    if (target.dataset["action"] === "completion-note") {
      const card = target.closest(".loop-card");
      const loopId = card?.getAttribute("data-loop-id");
      const mode = target.dataset["mode"] || "complete";
      if (event.key === "Enter" && loopId) {
        event.preventDefault();
        target.dataset["skipComplete"] = "true";
        if (mode === "complete") {
          void loop.confirmComplete(loopId, target.value);
        } else if (mode === "edit" && target instanceof HTMLInputElement) {
          void loop.saveCompletionNote(loopId, target);
          target.blur();
        }
      } else if (event.key === "Escape" && loopId) {
        event.preventDefault();
        target.dataset["skipComplete"] = "true";
        if (mode === "complete") {
          loop.hideCompletionNote(loopId);
        } else if (mode === "edit") {
          target.value = target.dataset["initial"] || "";
          target.blur();
        }
      }
      return;
    }

    const field = target.dataset["field"];
    if (!field) {
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      if (field === "tags_add" && target instanceof HTMLInputElement) {
        void loop.appendTagsFromInput(target);
      } else if (["due_date", "due_time"].includes(field)) {
        applyDueUpdateAndMaybeClose(target, { blurTarget: true });
      } else {
        target.blur();
      }
    } else if (event.key === "Escape") {
      if (field === "tags_add") {
        const tagsWrap = target.closest(".tags-edit");
        target.value = "";
        if (tagsWrap instanceof HTMLElement) {
          tagsWrap.classList.remove("editing");
        }
      } else if (["due_date", "due_time"].includes(field)) {
        const card = target.closest(".loop-card");
        const dueDateInput = card?.querySelector<HTMLInputElement>('[data-field="due_date"]') ?? null;
        const dueTimeInput = card?.querySelector<HTMLInputElement>('[data-field="due_time"]') ?? null;
        const loopStub = {
          due_date: dueDateInput?.dataset["initialDate"] || "",
          due_at_utc: dueDateInput?.dataset["initialTimestamp"] || "",
        };
        if (dueDateInput) {
          dueDateInput.value = dueDateInput.dataset["initialDate"]
            ? formatDateInputValue(dueDateInputValueFromLoop(loopStub))
            : dueDateInputValueFromLoop(loopStub);
          dueDateInput.removeAttribute("aria-invalid");
        }
        if (dueTimeInput) {
          dueTimeInput.value = dueTimeInput.dataset["initialTime"] || "";
        }
        void import("./render").then((module) => {
          if (card instanceof HTMLElement) {
            module.setDueEditorExpanded(card, false);
          }
        });
        target.blur();
      }
    }
  }, true);
}

// ========================================
// Initialize Application
// ========================================

let bootstrapped = false;

function initializeSurfaceRuntime(): void {
  if (bootstrapped) {
    return;
  }
  elements = buildElements();
  dataManagementStatuses = Array.from(document.querySelectorAll<HTMLElement>("[data-data-management-status]"));
  exportButtons = Array.from(document.querySelectorAll<HTMLElement>("[data-export-loops]"));
  importButtons = Array.from(document.querySelectorAll<HTMLElement>("[data-import-loops]"));
  bootstrapped = true;

  state.hydrateStateFromStorage();
  initializeCaptureDisclosure();

  loop.init({
    inbox: elements.inbox,
    status: elements.status,
    queryFilter: elements.queryFilter,
    queryModeFilter: elements.queryModeFilter,
    statusFilter: elements.statusFilter,
    tagFilter: elements.tagFilter,
    viewFilter: elements.viewFilter,
  });
  timer.init({ status: elements.status });
  bulk.init({ status: elements.status, bulkActionBar: elements.bulkActionBar });
  next.init({ nextBuckets: elements.nextBuckets, nextQueryFilter: elements.nextQueryFilter });
  chat.init({
    chatActionCards: elements.chatActionCards,
    chatMessages: elements.chatMessages,
    chatInput: elements.chatInput,
    chatForm: elements.chatForm,
    chatThreadStatus: elements.chatThreadStatus,
    chatResetButton: elements.chatResetButton,
    chatToolMode: elements.chatToolMode,
    chatLoopContext: elements.chatLoopContext,
    chatMemoryContext: elements.chatMemoryContext,
    chatMemoryLimit: elements.chatMemoryLimit,
    chatRagContext: elements.chatRagContext,
    chatRagK: elements.chatRagK,
    chatRagScope: elements.chatRagScope,
    chatControlsStatus: elements.chatControlsStatus,
    chatRuntimeStatus: elements.chatRuntimeStatus,
  });
  memory.init({
    memoryActionCards: elements.memoryActionCards,
    memoryList: elements.memoryList,
    memoryStatus: elements.memoryStatus,
    memoryFilterForm: elements.memoryFilterForm,
    memoryQuery: elements.memoryQuery,
    memoryCategoryFilter: elements.memoryCategoryFilter,
    memorySourceFilter: elements.memorySourceFilter,
    memoryMinPriority: elements.memoryMinPriority,
    memoryClearFiltersBtn: elements.memoryClearFiltersBtn,
    memoryRefreshBtn: elements.memoryRefreshBtn,
    memoryLoadMoreBtn: elements.memoryLoadMoreBtn,
    memoryCreateForm: elements.memoryCreateForm,
    memoryKey: elements.memoryKey,
    memoryContent: elements.memoryContent,
    memoryCategory: elements.memoryCategory,
    memoryPriority: elements.memoryPriority,
    memorySource: elements.memorySource,
    memoryMetadata: elements.memoryMetadata,
  });
  rag.init({
    ragActionCards: elements.ragActionCards,
    ragAnswer: elements.ragAnswer,
    ragAnswerText: requireQueryElement(".rag-answer-text", HTMLElement, elements.ragAnswer),
    ragSources: requireQueryElement(".rag-sources", HTMLElement, elements.ragAnswer),
    ragSourcesList: requireQueryElement(".rag-sources-list", HTMLElement, elements.ragAnswer),
    ragInput: elements.ragInput,
    ragEmptyState: elements.ragEmptyState,
    ragIngestForm: elements.ragIngestForm,
    ragIngestPath: elements.ragIngestPath,
    ragIngestMode: elements.ragIngestMode,
    ragIngestRecursive: elements.ragIngestRecursive,
    ragIngestStatus: elements.ragIngestStatus,
  });
  modals.init({ helpModal: elements.helpModal, appDialog: elements.appDialog });
  keyboard.init(
    { rawText: elements.rawText, queryFilter: elements.queryFilter, status: elements.status },
    {
      showCompletionNote: loop.showCompletionNote,
      enrichLoop: loop.enrichLoop,
      refreshLoop: loop.refreshLoop,
      toggleTimer: timer.toggleTimer,
      toggleSnoozeDropdown: loop.toggleSnoozeDropdown,
    },
  );

  syncLoopQueryModeUi();
  setupEventHandlers();
  setupLoopCardHandlers(elements.inbox);
  setupLoopCardHandlers(elements.nextBuckets);
  comments.setupCommentHandlers();
  suggestions.setupSuggestionHandlers();
  duplicates.setupMergeHandlers();

  void loop.loadInbox();
  void populateTemplateDropdown();
  void populateTagFilter();
  void populateViewDropdown();

  sse.connectSSE();
  sse.setupVisibilityHandler();
  window.addEventListener("beforeunload", () => sse.disconnectSSE());

  window.addEventListener(
    duplicates.SURFACE_RUNTIME_REFRESH_EVENT,
    ((event: CustomEvent<Record<string, unknown>>) => {
      const detail = isRecord(event.detail) ? event.detail : {};
      if (detail["inbox"]) {
        void loop.loadInbox();
      }
      if (detail["next"]) {
        void next.loadNext({ query: elements.nextQueryFilter.value.trim() });
      }
    }) as EventListener,
  );

  window.addEventListener("load", () => {
    window.setTimeout(duplicates.checkAndShowDuplicateBadges, 2000);
  });
}

export function bootstrapSurfaceRuntime(): void {
  initializeSurfaceRuntime();
}

export async function activateSurface(
  requestedTabName: unknown,
  options: ActivateSurfaceOptions = {},
): Promise<void> {
  initializeSurfaceRuntime();
  await activateSurfaceInternal(requestedTabName, options);
}

export async function refreshSurface(requestedTabName: unknown): Promise<void> {
  initializeSurfaceRuntime();
  await activateSurfaceInternal(requestedTabName, {
    doQuery: elements.nextQueryFilter.value.trim(),
  });
  if (requestedTabName === "inbox") {
    await loop.loadInbox();
    return;
  }
  if (requestedTabName === "next") {
    await next.loadNext({ query: elements.nextQueryFilter.value.trim() });
    return;
  }
  if (requestedTabName === "memory") {
    await memory.loadMemories();
  }
}
