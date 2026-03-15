/**
 * init.js - Application initialization
 *
 * Purpose:
 *   Initialize the Cloop web application and wire up all modules.
 *
 * Responsibilities:
 *   - Initialize all modules with DOM elements
 *   - Setup global event handlers
 *   - Handle tab switching
 *   - Load initial data
 *   - Setup PWA and notifications
 *
 * Non-scope:
 *   - Individual feature logic (see respective modules)
 *   - API calls (see api.js)
 *   - State management (see state.js)
 */

import * as state from './state.js';
import * as api from './api.js';
import * as loop from './loop.js';
import * as timer from './timer.js';
import * as bulk from './bulk.js';
import * as review from './review.js';
import * as planning from './planning.js';
import * as next from './next.js';
import * as chat from './chat.js';
import * as memory from './memory.js';
import * as rag from './rag.js';
import * as keyboard from './keyboard.js';
import * as modals from './modals.js';
import * as comments from './comments.js';
import * as sse from './sse.js';
import * as duplicates from './duplicates.js';
import * as suggestions from './suggestions.js';
import {
  dueDateInputValueFromLoop,
  formatDateInputValue,
  parseUserDateInput,
  snoozeDurationToUtc,
} from './utils.js';
import { selectedLoopIds } from './state.js';
import { updateBulkActionBar } from './bulk.js';

// ========================================
// DOM Element References
// ========================================

const elements = {
  inbox: document.getElementById("inbox"),
  status: document.getElementById("status"),
  form: document.getElementById("capture-form"),
  rawText: document.getElementById("raw-text"),
  actionable: document.getElementById("actionable"),
  scheduled: document.getElementById("scheduled"),
  blocked: document.getElementById("blocked"),
  dueDate: document.getElementById("due-date"),
  nextAction: document.getElementById("next-action"),
  timeMinutes: document.getElementById("time-minutes"),
  activationEnergy: document.getElementById("activation-energy"),
  project: document.getElementById("project"),
  tags: document.getElementById("tags"),
  captureDetails: document.getElementById("capture-details"),
  captureDetailsToggle: document.getElementById("capture-details-toggle"),
  statusFilter: document.getElementById("status-filter"),
  tagFilter: document.getElementById("tag-filter"),
  queryFilter: document.getElementById("query-filter"),
  queryModeFilter: document.getElementById("query-mode-filter"),
  viewFilter: document.getElementById("view-filter"),
  saveViewBtn: document.getElementById("save-view-btn"),
  importFile: document.getElementById("import-file"),
  templateSelect: document.getElementById("template-select"),
  inboxMain: document.getElementById("inbox-main"),
  nextMain: document.getElementById("next-main"),
  chatMain: document.getElementById("chat-main"),
  memoryMain: document.getElementById("memory-main"),
  ragMain: document.getElementById("rag-main"),
  reviewMain: document.getElementById("review-main"),
  metricsMain: document.getElementById("metrics-main"),
  nextBuckets: document.getElementById("next-buckets"),
  refreshNextBtn: document.getElementById("refresh-next-btn"),
  refreshMetricsBtn: document.getElementById("refresh-metrics-btn"),
  chatMessages: document.getElementById("chat-messages"),
  chatInput: document.getElementById("chat-input"),
  chatForm: document.getElementById("chat-form"),
  chatThreadStatus: document.getElementById("chat-thread-status"),
  chatResetButton: document.getElementById("chat-reset-btn"),
  chatToolMode: document.getElementById("chat-tool-mode"),
  chatLoopContext: document.getElementById("chat-loop-context"),
  chatMemoryContext: document.getElementById("chat-memory-context"),
  chatMemoryLimit: document.getElementById("chat-memory-limit"),
  chatRagContext: document.getElementById("chat-rag-context"),
  chatRagK: document.getElementById("chat-rag-k"),
  chatRagScope: document.getElementById("chat-rag-scope"),
  chatControlsStatus: document.getElementById("chat-controls-status"),
  chatRuntimeStatus: document.getElementById("chat-runtime-status"),
  memoryList: document.getElementById("memory-list"),
  memoryStatus: document.getElementById("memory-status"),
  memoryFilterForm: document.getElementById("memory-filter-form"),
  memoryQuery: document.getElementById("memory-query"),
  memoryCategoryFilter: document.getElementById("memory-category-filter"),
  memorySourceFilter: document.getElementById("memory-source-filter"),
  memoryMinPriority: document.getElementById("memory-min-priority"),
  memoryClearFiltersBtn: document.getElementById("memory-clear-filters-btn"),
  memoryRefreshBtn: document.getElementById("memory-refresh-btn"),
  memoryLoadMoreBtn: document.getElementById("memory-load-more-btn"),
  memoryCreateForm: document.getElementById("memory-create-form"),
  memoryKey: document.getElementById("memory-key"),
  memoryContent: document.getElementById("memory-content"),
  memoryCategory: document.getElementById("memory-category"),
  memoryPriority: document.getElementById("memory-priority"),
  memorySource: document.getElementById("memory-source"),
  memoryMetadata: document.getElementById("memory-metadata"),
  ragInput: document.getElementById("rag-input"),
  ragForm: document.getElementById("rag-form"),
  ragAnswer: document.getElementById("rag-answer"),
  ragEmptyState: document.getElementById("rag-empty-state"),
  ragFocusIngestBtn: document.getElementById("rag-focus-ingest-btn"),
  ragIngestForm: document.getElementById("rag-ingest-form"),
  ragIngestPath: document.getElementById("rag-ingest-path"),
  ragIngestMode: document.getElementById("rag-ingest-mode"),
  ragIngestRecursive: document.getElementById("rag-ingest-recursive"),
  ragIngestStatus: document.getElementById("rag-ingest-status"),
  reviewCohorts: document.getElementById("review-cohorts"),
  reviewPlanningSessionSelect: document.getElementById("review-planning-session-select"),
  reviewPlanningSessionNew: document.getElementById("review-planning-session-new"),
  reviewPlanningSessionDelete: document.getElementById("review-planning-session-delete"),
  reviewPlanningSessionRefresh: document.getElementById("review-planning-session-refresh"),
  reviewPlanningSessionExecute: document.getElementById("review-planning-session-execute"),
  reviewPlanningSessionStatus: document.getElementById("review-planning-session-status"),
  reviewPlanningSessionSummary: document.getElementById("review-planning-session-summary"),
  reviewPlanningSessionList: document.getElementById("review-planning-session-list"),
  reviewPlanningSessionDetail: document.getElementById("review-planning-session-detail"),
  reviewRelationshipSessionSelect: document.getElementById("review-relationship-session-select"),
  reviewRelationshipSessionNew: document.getElementById("review-relationship-session-new"),
  reviewRelationshipSessionEdit: document.getElementById("review-relationship-session-edit"),
  reviewRelationshipSessionDelete: document.getElementById("review-relationship-session-delete"),
  reviewRelationshipSessionRefresh: document.getElementById("review-relationship-session-refresh"),
  reviewRelationshipActionSelect: document.getElementById("review-relationship-action-select"),
  reviewRelationshipActionNew: document.getElementById("review-relationship-action-new"),
  reviewRelationshipActionEdit: document.getElementById("review-relationship-action-edit"),
  reviewRelationshipActionDelete: document.getElementById("review-relationship-action-delete"),
  reviewRelationshipSessionStatus: document.getElementById("review-relationship-session-status"),
  reviewRelationshipSessionSummary: document.getElementById("review-relationship-session-summary"),
  reviewRelationshipSessionList: document.getElementById("review-relationship-session-list"),
  reviewRelationshipSessionDetail: document.getElementById("review-relationship-session-detail"),
  reviewEnrichmentSessionSelect: document.getElementById("review-enrichment-session-select"),
  reviewEnrichmentSessionNew: document.getElementById("review-enrichment-session-new"),
  reviewEnrichmentSessionEdit: document.getElementById("review-enrichment-session-edit"),
  reviewEnrichmentSessionDelete: document.getElementById("review-enrichment-session-delete"),
  reviewEnrichmentSessionRefresh: document.getElementById("review-enrichment-session-refresh"),
  reviewEnrichmentActionSelect: document.getElementById("review-enrichment-action-select"),
  reviewEnrichmentActionNew: document.getElementById("review-enrichment-action-new"),
  reviewEnrichmentActionEdit: document.getElementById("review-enrichment-action-edit"),
  reviewEnrichmentActionDelete: document.getElementById("review-enrichment-action-delete"),
  reviewEnrichmentSessionStatus: document.getElementById("review-enrichment-session-status"),
  reviewEnrichmentSessionSummary: document.getElementById("review-enrichment-session-summary"),
  reviewEnrichmentSessionList: document.getElementById("review-enrichment-session-list"),
  reviewEnrichmentSessionDetail: document.getElementById("review-enrichment-session-detail"),
  reviewBulkEnrichQuery: document.getElementById("review-bulk-enrich-query"),
  reviewBulkEnrichLimit: document.getElementById("review-bulk-enrich-limit"),
  reviewBulkEnrichPreview: document.getElementById("review-bulk-enrich-preview"),
  reviewBulkEnrichRun: document.getElementById("review-bulk-enrich-run"),
  reviewBulkEnrichStatus: document.getElementById("review-bulk-enrich-status"),
  reviewBulkEnrichPreviewResults: document.getElementById("review-bulk-enrich-preview-results"),
  reviewBulkEnrichRunResults: document.getElementById("review-bulk-enrich-run-results"),
  metricsContent: document.getElementById("metrics-content"),
  bulkActionBar: document.getElementById("bulk-action-bar"),
  helpModal: document.getElementById("help-modal"),
  appDialog: document.getElementById("app-dialog"),
  offlineBanner: document.getElementById("offline-banner"),
};

const dataManagementStatuses = Array.from(
  document.querySelectorAll("[data-data-management-status]"),
);
const exportButtons = Array.from(document.querySelectorAll("[data-export-loops]"));
const importButtons = Array.from(document.querySelectorAll("[data-import-loops]"));

const MOBILE_CAPTURE_MEDIA = "(max-width: 640px)";
const CAPTURE_DETAILS_STORAGE_KEY = "cloop.captureDetails.mobileExpanded";
let captureMediaQuery = null;

function isMobileCaptureViewport() {
  return captureMediaQuery?.matches ?? window.matchMedia(MOBILE_CAPTURE_MEDIA).matches;
}

function readCaptureDetailsPreference() {
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

function writeCaptureDetailsPreference(expanded) {
  try {
    window.localStorage.setItem(CAPTURE_DETAILS_STORAGE_KEY, expanded ? "true" : "false");
  } catch {
    // Ignore storage access issues and keep the current in-memory state.
  }
}

function setDataManagementStatus(message, { isError = false } = {}) {
  dataManagementStatuses.forEach((element) => {
    element.textContent = message;
    element.classList.toggle("is-error", isError);
  });
}

// ========================================
// Tab Switching
// ========================================

function switchTab(tabName) {
  const tabs = document.querySelectorAll(".tab");
  let activeTab = null;
  tabs.forEach(t => {
    const isActive = t.dataset.tab === tabName;
    t.classList.toggle("active", isActive);
    t.setAttribute("aria-selected", isActive);
    if (isActive) {
      activeTab = t;
    }
  });

  const scrollBehavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  activeTab?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: scrollBehavior });

  elements.inboxMain.style.display = tabName === "inbox" ? "grid" : "none";
  elements.nextMain.style.display = tabName === "next" ? "grid" : "none";
  elements.chatMain.style.display = tabName === "chat" ? "grid" : "none";
  if (elements.memoryMain) {
    elements.memoryMain.style.display = tabName === "memory" ? "grid" : "none";
  }
  elements.ragMain.style.display = tabName === "rag" ? "grid" : "none";
  if (elements.reviewMain) {
    elements.reviewMain.style.display = tabName === "review" ? "grid" : "none";
  }
  if (elements.metricsMain) {
    elements.metricsMain.style.display = tabName === "metrics" ? "grid" : "none";
  }

  // Load data when switching to tabs
  if (tabName === "next") {
    next.loadNext();
  }
  if (tabName === "memory") {
    memory.loadMemories();
  }
  if (tabName === "review") {
    review.loadReviewData();
    planning.loadPlanningWorkspace();
  }
  if (tabName === "metrics") {
    fetchAndRenderMetrics();
  }

  state.updateState({ activeTab: tabName });
}

function setCaptureDetailsExpanded(expanded, { persist = false } = {}) {
  if (!elements.captureDetails || !elements.captureDetailsToggle) {
    return;
  }

  elements.captureDetails.hidden = !expanded;
  elements.captureDetailsToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  elements.captureDetailsToggle.textContent = expanded ? "Hide details" : "Add details";

  if (persist && isMobileCaptureViewport()) {
    writeCaptureDetailsPreference(expanded);
  }
}

function syncCaptureDisclosureToViewport() {
  if (!elements.captureDetails || !elements.captureDetailsToggle) {
    return;
  }

  if (isMobileCaptureViewport()) {
    const mobilePreference = readCaptureDetailsPreference();
    setCaptureDetailsExpanded(mobilePreference ?? false);
    return;
  }

  setCaptureDetailsExpanded(true);
}

function initializeCaptureDisclosure() {
  if (!elements.captureDetails || !elements.captureDetailsToggle) {
    return;
  }

  captureMediaQuery = window.matchMedia(MOBILE_CAPTURE_MEDIA);
  syncCaptureDisclosureToViewport();

  const handleViewportChange = () => syncCaptureDisclosureToViewport();
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

function normalizeDueDateField() {
  if (!elements.dueDate) {
    return { parsedDate: null, isValid: true };
  }

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

async function captureLoop(event) {
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
  const payload = {
    raw_text: elements.rawText.value.trim(),
    captured_at: now.toISOString(),
    client_tz_offset_min: -now.getTimezoneOffset(),
    actionable: elements.actionable.checked,
    scheduled: elements.scheduled.checked,
    blocked: elements.blocked.checked,
  };

  if (templateId) {
    payload.template_id = parseInt(templateId, 10);
  }

  // Add optional metadata fields (only if non-empty)
  if (parsedDate) {
    payload.due_date = parsedDate.isoDate;
  }
  if (elements.nextAction.value.trim()) {
    payload.next_action = elements.nextAction.value.trim();
  }
  if (elements.timeMinutes.value) {
    payload.time_minutes = parseInt(elements.timeMinutes.value, 10);
  }
  if (elements.activationEnergy.value) {
    payload.activation_energy = parseInt(elements.activationEnergy.value, 10);
  }
  if (elements.project.value.trim()) {
    payload.project = elements.project.value.trim();
  }
  if (elements.tags.value.trim()) {
    // Split on comma, trim each tag, filter empty
    payload.tags = elements.tags.value.split(",")
      .map(t => t.trim())
      .filter(t => t.length > 0);
  }

  if (!payload.raw_text && !templateId) {
    elements.status.textContent = "Type something first.";
    return;
  }

  // Show offline indicator immediately if offline
  if (!navigator.onLine) {
    elements.offlineBanner.classList.add("visible");
    elements.status.textContent = "Saving offline...";
  } else {
    elements.status.textContent = "Saving...";
  }

  // Request notification permission on first capture
  if (!state.state.notificationPermissionRequested) {
    state.updateState({ notificationPermissionRequested: true });
    requestNotificationPermission();
  }

  try {
    const result = await api.captureLoop(payload);

    // Handle service worker's offline queued response
    if (result.queued && result.offline) {
      elements.status.textContent = "Saved offline - will sync when connected";
    } else {
      loop.replaceLoop(result);
      elements.status.textContent = "Saved. Enrichment queued.";
    }

    // Clear form
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
  } catch (error) {
    elements.status.textContent = error.message;
  }
}

// ========================================
// Templates
// ========================================

async function loadTemplates() {
  if (state.state.templatesCache) return state.state.templatesCache;

  const templates = await api.fetchTemplates();
  state.updateState({ templatesCache: templates });
  return templates;
}

async function populateTemplateDropdown() {
  const templates = await loadTemplates();

  // Clear existing options except first ("None")
  while (elements.templateSelect.options.length > 1) {
    elements.templateSelect.remove(1);
  }

  // Add options
  templates.forEach(t => {
    const option = document.createElement("option");
    option.value = t.id;
    option.textContent = t.name + (t.is_system ? " (system)" : "");
    elements.templateSelect.appendChild(option);
  });
}

async function saveAsTemplate(loopId) {
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
    validate: ({ name }) => {
      if (!name) {
        return "Enter a template name.";
      }
      return null;
    },
  });
  if (!result?.name) return;

  try {
    const template = await api.saveLoopAsTemplate(loopId, result.name);
    elements.status.textContent = `Template "${template.name}" created!`;
    state.updateState({ templatesCache: null });
    populateTemplateDropdown();
  } catch (error) {
    elements.status.textContent = error.message;
  }
}

// ========================================
// Import/Export
// ========================================

function downloadExport(payload) {
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

async function exportLoops() {
  elements.status.textContent = "Exporting...";
  setDataManagementStatus("Exporting data...");
  try {
    const payload = await api.exportLoops();
    downloadExport(payload);
    elements.status.textContent = "Exported.";
    setDataManagementStatus("Exported loop snapshot.");
  } catch (error) {
    elements.status.textContent = error.message;
    setDataManagementStatus(error.message, { isError: true });
  }
}

async function importLoops(file) {
  elements.status.textContent = "Importing...";
  setDataManagementStatus("Importing data...");
  try {
    const text = await file.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      elements.status.textContent = "Invalid JSON file.";
      setDataManagementStatus("Invalid JSON file.", { isError: true });
      return;
    }
    const loops = Array.isArray(payload) ? payload : payload.loops || [];
    const result = await api.importLoops(loops);
    elements.status.textContent = `Imported ${result.imported} loops.`;
    setDataManagementStatus(`Imported ${result.imported} loops.`);
    await loop.loadInbox();
  } catch (error) {
    elements.status.textContent = error.message;
    setDataManagementStatus(error.message, { isError: true });
  }
}

// ========================================
// Metrics
// ========================================

async function fetchAndRenderMetrics() {
  if (!elements.metricsContent) return;

  elements.metricsContent.innerHTML = '<div class="cohort-loading">Loading metrics...</div>';

  try {
    const data = await api.fetchMetrics();
    renderMetrics(data);
  } catch (err) {
    console.error("metrics error:", err);
    elements.metricsContent.innerHTML = '<div class="cohort-empty">Error loading metrics.</div>';
  }
}

function renderMetrics(data) {
  const statusHtml = `
    <div class="metrics-section-title">Status Distribution</div>
    <div class="metrics-status-row">
      <span class="status-badge inbox">Inbox: ${data.status_counts.inbox}</span>
      <span class="status-badge actionable">Actionable: ${data.status_counts.actionable}</span>
      <span class="status-badge blocked">Blocked: ${data.status_counts.blocked}</span>
      <span class="status-badge scheduled">Scheduled: ${data.status_counts.scheduled}</span>
      <span class="status-badge completed">Completed: ${data.status_counts.completed}</span>
      <span class="status-badge dropped">Dropped: ${data.status_counts.dropped}</span>
    </div>
  `;

  const staleClass = data.stale_open_count > 5 ? 'alert' : data.stale_open_count > 0 ? 'warning' : '';
  const blockedClass = data.blocked_too_long_count > 3 ? 'alert' : data.blocked_too_long_count > 0 ? 'warning' : '';
  const enrichClass = data.enrichment_failed_count > 0 ? 'alert' : '';

  const healthHtml = `
    <div class="metrics-section-title">Health Indicators</div>
    <div class="metrics-grid">
      <div class="metric-card ${staleClass}">
        <div class="metric-value">${data.stale_open_count}</div>
        <div class="metric-label">Stale Open (72h+)</div>
      </div>
      <div class="metric-card ${blockedClass}">
        <div class="metric-value">${data.blocked_too_long_count}</div>
        <div class="metric-label">Blocked 48h+</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${data.no_next_action_count}</div>
        <div class="metric-label">No Next Action</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${data.enrichment_pending_count}</div>
        <div class="metric-label">Enrichment Pending</div>
      </div>
      <div class="metric-card ${enrichClass}">
        <div class="metric-value">${data.enrichment_failed_count}</div>
        <div class="metric-label">Enrichment Failed</div>
      </div>
    </div>
  `;

  const throughputClass = data.completion_count_24h >= data.capture_count_24h ? 'success' : '';
  const throughputHtml = `
    <div class="metrics-section-title">Throughput (24h)</div>
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-value">${data.capture_count_24h}</div>
        <div class="metric-label">Captured</div>
      </div>
      <div class="metric-card ${throughputClass}">
        <div class="metric-value">${data.completion_count_24h}</div>
        <div class="metric-label">Completed</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${data.avg_age_open_hours !== null ? data.avg_age_open_hours.toFixed(1) + 'h' : 'N/A'}</div>
        <div class="metric-label">Avg Age Open</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${data.total_loops}</div>
        <div class="metric-label">Total Loops</div>
      </div>
    </div>
  `;

  elements.metricsContent.innerHTML = statusHtml + healthHtml + throughputHtml;
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

async function subscribeToPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return;
  }

  try {
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
      // Create new subscription (requires VAPID key in production)
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        // applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
      });
    }

    // Send subscription to server
    const response = await fetch("/loops/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        keys: {
          p256dh: arrayBufferToBase64(subscription.getKey("p256dh")),
          auth: arrayBufferToBase64(subscription.getKey("auth"))
        }
      })
    });

    if (!response.ok) {
      console.error("Failed to register push subscription:", await response.text());
    }
  } catch (err) {
    console.error("Push subscription failed:", err);
  }
}

function arrayBufferToBase64(buffer) {
  if (!buffer) return "";
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("/sw.js");
    } catch (error) {
      console.error("Service worker registration failed:", error);
    }
  }
}

function updateOnlineStatus() {
  if (navigator.onLine) {
    elements.offlineBanner.classList.remove("visible");
    if ("serviceWorker" in navigator && "SyncManager" in window) {
      navigator.serviceWorker.ready.then((registration) => {
        registration.sync.register("sync-captures");
      });
    }
  } else {
    elements.offlineBanner.classList.add("visible");
  }
}

// ========================================
// Event Handlers Setup
// ========================================

function syncLoopQueryModeUi() {
  const isSemantic = elements.queryModeFilter?.value === "semantic";
  if (elements.queryFilter) {
    elements.queryFilter.placeholder = isSemantic
      ? "e.g., buy groceries before the weekend"
      : "e.g., status:inbox due:today";
  }
  if (elements.saveViewBtn) {
    elements.saveViewBtn.disabled = Boolean(isSemantic);
    elements.saveViewBtn.title = isSemantic
      ? "Saved views currently support DSL queries only"
      : "Save current DSL query as a view";
  }
}


function setupEventHandlers() {
  // Tab switching
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  // Form submissions
  elements.form.addEventListener("submit", captureLoop);
  elements.dueDate?.addEventListener("input", () => {
    const formattedValue = formatDateInputValue(elements.dueDate.value);
    if (elements.dueDate.value !== formattedValue) {
      elements.dueDate.value = formattedValue;
    }
    elements.dueDate.removeAttribute("aria-invalid");
  });
  elements.dueDate?.addEventListener("blur", normalizeDueDateField);
  elements.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = elements.chatInput.value.trim();
    if (!text) return;
    elements.chatInput.value = "";
    chat.submitChat(text);
  });
  elements.ragForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = elements.ragInput.value.trim();
    if (!question) return;
    elements.ragInput.value = "";
    rag.submitRagQuestion(question);
  });
  elements.ragIngestForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await rag.submitIngestPath();
  });
  elements.ragFocusIngestBtn?.addEventListener("click", () => {
    rag.handleEmptyStateAction();
  });

  // Filter handlers
  elements.statusFilter.addEventListener("change", () => {
    elements.queryFilter.value = "";
    elements.viewFilter.value = "";
    loop.loadInbox();
  });
  elements.tagFilter.addEventListener("change", () => {
    elements.queryFilter.value = "";
    elements.viewFilter.value = "";
    loop.loadInbox();
  });
  elements.queryModeFilter?.addEventListener("change", () => {
    elements.viewFilter.value = "";
    syncLoopQueryModeUi();
    if (elements.queryFilter.value.trim()) {
      loop.loadInbox();
    }
  });
  elements.queryFilter.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      elements.viewFilter.value = "";
      elements.statusFilter.value = "all";
      elements.tagFilter.value = "";
      loop.loadInbox();
    }
  });
  elements.viewFilter.addEventListener("change", () => {
    const selected = elements.viewFilter.selectedOptions[0];
    if (selected?.dataset.query) {
      elements.queryFilter.value = selected.dataset.query;
      if (elements.queryModeFilter) {
        elements.queryModeFilter.value = "dsl";
        syncLoopQueryModeUi();
      }
      elements.statusFilter.value = "all";
      elements.tagFilter.value = "";
      loop.loadInbox();
    }
  });

  // Button handlers
  elements.saveViewBtn.addEventListener("click", async () => {
    const query = elements.queryFilter.value.trim();
    if (elements.queryModeFilter?.value === "semantic") {
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
      validate: ({ name }) => {
        if (!name) {
          return "Enter a view name.";
        }
        return null;
      },
    });
    if (!result?.name) return;
    try {
      await api.saveView(result.name, query);
      elements.status.textContent = "View saved.";
      await api.fetchViews();
    } catch (error) {
      elements.status.textContent = error.message;
    }
  });
  exportButtons.forEach((button) => button.addEventListener("click", exportLoops));
  importButtons.forEach((button) => {
    button.addEventListener("click", () => elements.importFile.click());
  });
  elements.importFile.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) importLoops(file);
    elements.importFile.value = "";
  });
  elements.refreshNextBtn?.addEventListener("click", next.loadNext);
  elements.refreshMetricsBtn?.addEventListener("click", fetchAndRenderMetrics);

  // Review mode toggle
  document.querySelectorAll("[data-review-mode]").forEach(btn => {
    btn.addEventListener("click", () => {
      review.setReviewMode(btn.dataset.reviewMode);
      document.querySelectorAll("[data-review-mode]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  // Bulk action handlers
  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-bulk-action]");
    if (btn) {
      bulk.handleBulkAction(btn.dataset.bulkAction);
      updateBulkActionBar();
    }
  });

  // Close snooze dropdowns when clicking outside
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.snooze-wrapper')) {
      document.querySelectorAll('.snooze-dropdown.visible').forEach(d => {
        d.classList.remove('visible');
      });
    }
  });

  // Online/offline detection
  window.addEventListener("online", updateOnlineStatus);
  window.addEventListener("offline", updateOnlineStatus);
}

// ========================================
// Loop Card Event Handlers
// ========================================

function setupLoopCardHandlers(container) {
  const applyDueUpdateAndMaybeClose = (target, { blurTarget = false } = {}) => {
    Promise.resolve(loop.applyInlineUpdate(target)).then((shouldClose) => {
      if (shouldClose === false) {
        return;
      }
      import('./render.js').then((m) => {
        const card = target.closest(".loop-card");
        if (card) {
          m.setDueEditorExpanded(card, false);
        }
      });
      if (blurTarget) {
        target.blur();
      }
    });
  };

  // Checkbox change handler for bulk selection
  container.addEventListener("change", (event) => {
    const checkbox = event.target.closest(".loop-checkbox");
    if (checkbox) {
      const loopId = parseInt(checkbox.dataset.loopId, 10);
      if (event.shiftKey && state.state.lastClickedLoopId !== null && state.state.lastClickedLoopId !== loopId) {
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

    // Handle recurrence toggle
    const recurrenceToggle = event.target.closest('[data-recurrence-toggle]');
    if (recurrenceToggle && event.target.type === 'checkbox') {
      const loopId = recurrenceToggle.dataset.recurrenceToggle;
      const card = recurrenceToggle.closest('.loop-card');
      const scheduleInput = card?.querySelector(`[data-recurrence-schedule="${loopId}"]`);
      const rrule = scheduleInput?.value?.trim() || '';

      loop.toggleRecurrenceSection(loopId, event.target.checked);

      if (event.target.checked && rrule) {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        loop.updateRecurrence(loopId, rrule, tz, true);
      } else if (!event.target.checked) {
        loop.updateRecurrence(loopId, null, null, false);
      }
      return;
    }

    // Handle recurrence schedule input change
    const scheduleInput = event.target.closest('.recurrence-schedule-input');
    if (scheduleInput) {
      const loopId = scheduleInput.dataset.recurrenceSchedule;
      const card = scheduleInput.closest('.loop-card');
      const toggle = card?.querySelector(`[data-recurrence-toggle="${loopId}"]`);

      if (toggle?.checked && scheduleInput.value.trim()) {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        loop.updateRecurrence(loopId, scheduleInput.value.trim(), tz, true);
      }
      return;
    }
  });

  // Click handlers
  container.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (button) {
      if (button.dataset.action === "complete") {
        loop.showCompletionNote(button.dataset.id);
      } else if (button.dataset.action === "toggle-compact") {
        loop.toggleCompactCard(button.closest(".loop-card")?.dataset.loopId);
      } else if (button.dataset.action === "edit-due") {
        import('./render.js').then((m) => {
          const card = button.closest(".loop-card");
          if (card) {
            m.setDueEditorExpanded(card, true);
          }
        });
        event.preventDefault();
      } else if (button.dataset.action === "toggle-card-body") {
        loop.toggleMobileCardText(button.closest(".loop-card")?.dataset.loopId);
      } else if (button.dataset.action === "confirm-complete") {
        const card = button.closest(".loop-card");
        const input = card?.querySelector(".completion-note-input");
        if (input) {
          input.dataset.skipComplete = "true";
        }
        loop.confirmComplete(button.dataset.id, input?.value || "");
      } else if (button.dataset.action === "cancel-complete") {
        loop.hideCompletionNote(button.dataset.id);
      } else if (button.dataset.action === "enrich") {
        loop.enrichLoop(button.dataset.id);
      } else if (button.dataset.action === "refresh") {
        loop.refreshLoop(button.dataset.id);
      } else if (button.dataset.action === "timer-toggle") {
        timer.toggleTimer(button.dataset.id);
      } else if (button.dataset.action === "snooze") {
        event.stopPropagation();
        loop.toggleSnoozeDropdown(button.dataset.id);
      } else if (button.dataset.action === "edit-tags") {
        const tagsWrap = button.closest(".tags-edit");
        if (tagsWrap) {
          tagsWrap.classList.add("editing");
          const input = tagsWrap.querySelector(".tag-input");
          if (input) {
            input.value = "";
            input.focus();
          }
        }
      } else if (button.dataset.action === "remove-tag") {
        const card = button.closest(".loop-card");
        if (card) {
          loop.removeTag(card.dataset.loopId, button.dataset.tag, card);
        }
      } else if (button.dataset.action === "save-template") {
        saveAsTemplate(button.dataset.id);
      } else if (button.dataset.action === "clear-due") {
        const card = button.closest(".loop-card");
        const dueDateInput = card?.querySelector('[data-field="due_date"]');
        const dueTimeInput = card?.querySelector('[data-field="due_time"]');
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

      // Handle snooze option clicks
      const snoozeOption = event.target.closest('.snooze-option');
      if (snoozeOption) {
        const dropdown = snoozeOption.closest('.snooze-dropdown');
        const loopId = dropdown?.dataset?.snoozeDropdown;
        const duration = snoozeOption.dataset?.snoozeDuration;

        if (loopId && duration) {
          const utcTime = snoozeDurationToUtc(duration);
          if (utcTime) {
            loop.snoozeLoop(loopId, utcTime);
            dropdown.classList.remove('visible');
          }
        }
      }
    }
  });

  // Custom snooze datetime change
  container.addEventListener("change", (event) => {
    const snoozeDatetime = event.target.closest('.snooze-datetime');
    if (snoozeDatetime) {
      const loopId = snoozeDatetime.dataset?.snoozeCustom;
      const localTime = snoozeDatetime.value;

      if (loopId && localTime) {
        const utcTime = new Date(localTime).toISOString();
        loop.snoozeLoop(loopId, utcTime);
        const dropdown = snoozeDatetime.closest('.snooze-dropdown');
        if (dropdown) dropdown.classList.remove('visible');
      }
    }

    // Handle status and other field changes
    if (event.target?.dataset?.field && !["due_date", "due_time"].includes(event.target.dataset.field)) {
      loop.applyInlineUpdate(event.target);
    }
  });

  // Pointer down for cancel-complete
  container.addEventListener("pointerdown", (event) => {
    const button = event.target.closest("button");
    if (button?.dataset.action === "cancel-complete") {
      const card = button.closest(".loop-card");
      const input = card?.querySelector(".completion-note-input");
      if (input) {
        input.dataset.skipComplete = "true";
      }
    }
  }, true);

  // Focus out handlers
  container.addEventListener("focusout", (event) => {
    const target = event.target;

    if (target?.classList?.contains("completion-note-input")) {
      if (target.dataset.skipComplete) {
        delete target.dataset.skipComplete;
        return;
      }
      const card = target.closest(".loop-card");
      const loopId = card?.dataset?.loopId;
      if (!loopId) return;
      const mode = target.dataset.mode || "complete";
      if (mode === "complete") {
        loop.confirmComplete(loopId, target.value);
      } else if (mode === "edit") {
        loop.saveCompletionNote(loopId, target);
      }
      return;
    }

    if (target?.classList?.contains("tag-input")) {
      loop.appendTagsFromInput(target);
      return;
    }

    if (["due_date", "due_time"].includes(target?.dataset?.field)) {
      const dueField = target.closest("[data-due-field]");
      if (dueField?.contains(event.relatedTarget)) {
        return;
      }
      applyDueUpdateAndMaybeClose(target);
    }
  });

  // Input handlers for auto-resize
  container.addEventListener("input", (event) => {
    const target = event.target;
    if (target?.dataset?.field === "next_action") {
      import('./render.js').then(m => m.autoResizeTextarea(target));
    } else if (target?.dataset?.field === "due_date") {
      const formattedValue = formatDateInputValue(target.value);
      if (target.value !== formattedValue) {
        target.value = formattedValue;
      }
      target.removeAttribute("aria-invalid");
    }
  });

  container.addEventListener("focus", (event) => {
    const target = event.target;
    if (target?.dataset?.field === "next_action") {
      import('./render.js').then(m => m.autoResizeTextarea(target));
    }
  }, true);

  // Keydown handlers
  container.addEventListener("keydown", (event) => {
    const target = event.target;

    if (target?.dataset?.action === "completion-note") {
      const card = target.closest(".loop-card");
      const loopId = card?.dataset?.loopId;
      const mode = target.dataset.mode || "complete";

      if (event.key === "Enter" && loopId) {
        event.preventDefault();
        target.dataset.skipComplete = "true";
        if (mode === "complete") {
          loop.confirmComplete(loopId, target.value);
        } else if (mode === "edit") {
          loop.saveCompletionNote(loopId, target);
          target.blur();
        }
      } else if (event.key === "Escape" && loopId) {
        event.preventDefault();
        target.dataset.skipComplete = "true";
        if (mode === "complete") {
          loop.hideCompletionNote(loopId);
        } else if (mode === "edit") {
          target.value = target.dataset.initial || "";
          target.blur();
        }
      }
      return;
    }

    if (!target?.dataset?.field) return;

    if (event.key === "Enter") {
      event.preventDefault();
      if (target.dataset.field === "tags_add") {
        loop.appendTagsFromInput(target);
      } else if (["due_date", "due_time"].includes(target.dataset.field)) {
        applyDueUpdateAndMaybeClose(target, { blurTarget: true });
      } else {
        target.blur();
      }
    } else if (event.key === "Escape") {
      if (target.dataset.field === "tags_add") {
        const tagsWrap = target.closest(".tags-edit");
        target.value = "";
        if (tagsWrap) {
          tagsWrap.classList.remove("editing");
        }
      } else if (["due_date", "due_time"].includes(target.dataset.field)) {
        const card = target.closest(".loop-card");
        const dueDateInput = card?.querySelector('[data-field="due_date"]');
        const dueTimeInput = card?.querySelector('[data-field="due_time"]');
        const loopStub = {
          due_date: dueDateInput?.dataset.initialDate || "",
          due_at_utc: dueDateInput?.dataset.initialTimestamp || "",
        };
        if (dueDateInput) {
          dueDateInput.value = dueDateInput.dataset.initialDate
            ? formatDateInputValue(dueDateInputValueFromLoop(loopStub))
            : dueDateInputValueFromLoop(loopStub);
          dueDateInput.removeAttribute("aria-invalid");
        }
        if (dueTimeInput) {
          dueTimeInput.value = dueTimeInput.dataset.initialTime || "";
        }
        import('./render.js').then((m) => {
          if (card) {
            m.setDueEditorExpanded(card, false);
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

function init() {
  state.hydrateStateFromStorage();
  initializeCaptureDisclosure();

  // Initialize modules
  loop.init({
    inbox: elements.inbox,
    status: elements.status,
    queryFilter: elements.queryFilter,
    statusFilter: elements.statusFilter,
    tagFilter: elements.tagFilter,
    viewFilter: elements.viewFilter,
  });
  timer.init({ status: elements.status });
  bulk.init({ status: elements.status, bulkActionBar: elements.bulkActionBar });
  review.init({
    reviewCohorts: elements.reviewCohorts,
    reviewRelationshipSessionSelect: elements.reviewRelationshipSessionSelect,
    reviewRelationshipSessionNew: elements.reviewRelationshipSessionNew,
    reviewRelationshipSessionEdit: elements.reviewRelationshipSessionEdit,
    reviewRelationshipSessionDelete: elements.reviewRelationshipSessionDelete,
    reviewRelationshipSessionRefresh: elements.reviewRelationshipSessionRefresh,
    reviewRelationshipActionSelect: elements.reviewRelationshipActionSelect,
    reviewRelationshipActionNew: elements.reviewRelationshipActionNew,
    reviewRelationshipActionEdit: elements.reviewRelationshipActionEdit,
    reviewRelationshipActionDelete: elements.reviewRelationshipActionDelete,
    reviewRelationshipSessionStatus: elements.reviewRelationshipSessionStatus,
    reviewRelationshipSessionSummary: elements.reviewRelationshipSessionSummary,
    reviewRelationshipSessionList: elements.reviewRelationshipSessionList,
    reviewRelationshipSessionDetail: elements.reviewRelationshipSessionDetail,
    reviewEnrichmentSessionSelect: elements.reviewEnrichmentSessionSelect,
    reviewEnrichmentSessionNew: elements.reviewEnrichmentSessionNew,
    reviewEnrichmentSessionEdit: elements.reviewEnrichmentSessionEdit,
    reviewEnrichmentSessionDelete: elements.reviewEnrichmentSessionDelete,
    reviewEnrichmentSessionRefresh: elements.reviewEnrichmentSessionRefresh,
    reviewEnrichmentActionSelect: elements.reviewEnrichmentActionSelect,
    reviewEnrichmentActionNew: elements.reviewEnrichmentActionNew,
    reviewEnrichmentActionEdit: elements.reviewEnrichmentActionEdit,
    reviewEnrichmentActionDelete: elements.reviewEnrichmentActionDelete,
    reviewEnrichmentSessionStatus: elements.reviewEnrichmentSessionStatus,
    reviewEnrichmentSessionSummary: elements.reviewEnrichmentSessionSummary,
    reviewEnrichmentSessionList: elements.reviewEnrichmentSessionList,
    reviewEnrichmentSessionDetail: elements.reviewEnrichmentSessionDetail,
    reviewBulkEnrichQuery: elements.reviewBulkEnrichQuery,
    reviewBulkEnrichLimit: elements.reviewBulkEnrichLimit,
    reviewBulkEnrichPreview: elements.reviewBulkEnrichPreview,
    reviewBulkEnrichRun: elements.reviewBulkEnrichRun,
    reviewBulkEnrichStatus: elements.reviewBulkEnrichStatus,
    reviewBulkEnrichPreviewResults: elements.reviewBulkEnrichPreviewResults,
    reviewBulkEnrichRunResults: elements.reviewBulkEnrichRunResults,
  });
  planning.init({
    reviewPlanningSessionSelect: elements.reviewPlanningSessionSelect,
    reviewPlanningSessionNew: elements.reviewPlanningSessionNew,
    reviewPlanningSessionDelete: elements.reviewPlanningSessionDelete,
    reviewPlanningSessionRefresh: elements.reviewPlanningSessionRefresh,
    reviewPlanningSessionExecute: elements.reviewPlanningSessionExecute,
    reviewPlanningSessionStatus: elements.reviewPlanningSessionStatus,
    reviewPlanningSessionSummary: elements.reviewPlanningSessionSummary,
    reviewPlanningSessionList: elements.reviewPlanningSessionList,
    reviewPlanningSessionDetail: elements.reviewPlanningSessionDetail,
  });
  next.init({ nextBuckets: elements.nextBuckets });
  chat.init({
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
    ragAnswer: elements.ragAnswer,
    ragAnswerText: elements.ragAnswer.querySelector(".rag-answer-text"),
    ragSources: elements.ragAnswer.querySelector(".rag-sources"),
    ragSourcesList: elements.ragAnswer.querySelector(".rag-sources-list"),
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
      switchTab,
      showCompletionNote: loop.showCompletionNote,
      enrichLoop: loop.enrichLoop,
      refreshLoop: loop.refreshLoop,
      toggleTimer: timer.toggleTimer,
      toggleSnoozeDropdown: loop.toggleSnoozeDropdown,
    }
  );

  syncLoopQueryModeUi();

  // Setup handlers
  setupEventHandlers();
  setupLoopCardHandlers(elements.inbox);
  setupLoopCardHandlers(elements.nextBuckets);
  comments.setupCommentHandlers();
  suggestions.setupSuggestionHandlers();
  duplicates.setupMergeHandlers();

  // Initial load
  switchTab(state.state.activeTab || "inbox");
  loop.loadInbox();
  populateTemplateDropdown();

  // Initialize SSE
  sse.connectSSE();
  sse.setupVisibilityHandler();
  window.addEventListener('beforeunload', () => sse.disconnectSSE());

  // Check for duplicates after initial load
  window.addEventListener('load', () => {
    setTimeout(duplicates.checkAndShowDuplicateBadges, 2000);
  });

  // PWA
  updateOnlineStatus();
  registerServiceWorker();
}

// Start when DOM is ready
document.addEventListener("DOMContentLoaded", init);
