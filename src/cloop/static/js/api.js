/**
 * api.js - API fetch utilities
 *
 * Purpose:
 *   Provide consistent API client functions for all backend interactions.
 *
 * Responsibilities:
 *   - Loop CRUD operations
 *   - Search and filter operations
 *   - Timer API calls
 *   - Comment API calls
 *   - Template operations
 *   - Bulk operations
 *   - Error handling
 *
 * Non-scope:
 *   - State management (see state.js)
 *   - DOM manipulation (see render.js)
 *   - Event handling (see individual modules)
 */

async function extractErrorMessage(response, fallbackMessage) {
  try {
    const error = await response.json();
    const detail = error?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail.message === "string" && detail.message.trim()) {
      return detail.message;
    }
    if (typeof error?.message === "string" && error.message.trim()) {
      return error.message;
    }
    if (error?.error && typeof error.error.message === "string" && error.error.message.trim()) {
      return error.error.message;
    }
  } catch {
    // Fall back to the provided default when no structured payload is available.
  }
  return fallbackMessage;
}

// ========================================
// Memory Operations
// ========================================

export async function fetchMemoryEntries(options = {}) {
  const url = new URL("/memory", window.location.origin);
  if (options.category) {
    url.searchParams.set("category", options.category);
  }
  if (options.source) {
    url.searchParams.set("source", options.source);
  }
  if (options.minPriority !== undefined && options.minPriority !== null && options.minPriority !== "") {
    url.searchParams.set("min_priority", String(options.minPriority));
  }
  url.searchParams.set("limit", String(options.limit ?? 50));
  if (options.cursor) {
    url.searchParams.set("cursor", options.cursor);
  }

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to load memory entries"));
  }
  return response.json();
}

export async function searchMemoryEntries(query, options = {}) {
  const url = new URL("/memory/search", window.location.origin);
  url.searchParams.set("q", query);
  if (options.category) {
    url.searchParams.set("category", options.category);
  }
  if (options.source) {
    url.searchParams.set("source", options.source);
  }
  if (options.minPriority !== undefined && options.minPriority !== null && options.minPriority !== "") {
    url.searchParams.set("min_priority", String(options.minPriority));
  }
  url.searchParams.set("limit", String(options.limit ?? 50));
  if (options.cursor) {
    url.searchParams.set("cursor", options.cursor);
  }

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to search memory entries"));
  }
  return response.json();
}

export async function fetchMemoryEntry(entryId) {
  const response = await fetch(`/memory/${entryId}`);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to load memory entry"));
  }
  return response.json();
}

export async function createMemoryEntry(payload) {
  const response = await fetch("/memory", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to create memory entry"));
  }
  return response.json();
}

export async function updateMemoryEntry(entryId, payload) {
  const response = await fetch(`/memory/${entryId}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to update memory entry"));
  }
  return response.json();
}

export async function deleteMemoryEntry(entryId) {
  const response = await fetch(`/memory/${entryId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to delete memory entry"));
  }
  return true;
}

// ========================================
// Loop Operations
// ========================================

export async function fetchLoops(status, tag = null) {
  const url = new URL("/loops", window.location.origin);
  url.searchParams.set("status", status);
  if (tag) {
    url.searchParams.set("tag", tag);
  }
  const response = await fetch(url.toString());
  if (!response.ok) throw new Error("Failed to load loops");
  return response.json();
}

export async function searchLoops(query, limit = 50, offset = 0) {
  const response = await fetch("/loops/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query, limit, offset }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to search loops"));
  }
  const result = await response.json();
  return result.items;
}

export async function searchLoopsSemantic(query, options = {}) {
  const response = await fetch("/loops/search/semantic", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      query,
      status: options.status ?? "open",
      limit: options.limit ?? 50,
      offset: options.offset ?? 0,
      min_score: options.minScore ?? null,
    }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to search loops semantically"));
  }
  return response.json();
}

export async function fetchLoop(loopId) {
  const response = await fetch(`/loops/${loopId}`);
  if (!response.ok) return null;
  return response.json();
}

export async function captureLoop(payload) {
  const response = await fetch("/loops/capture", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Capture failed");
  return response.json();
}

export async function updateLoop(loopId, fields) {
  const response = await fetch(`/loops/${loopId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!response.ok) return null;
  return response.json();
}

export async function transitionLoopStatus(loopId, status, note = null) {
  const payload = { status };
  if (note) payload.note = note;
  const response = await fetch(`/loops/${loopId}/status`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Status transition failed");
  return response.json();
}

export async function enrichLoop(loopId) {
  const response = await fetch(`/loops/${loopId}/enrich`, {
    method: "POST",
    headers: { "content-type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Enrichment request failed"));
  }
  return response.json();
}

// ========================================
// Timer Operations
// ========================================

export async function fetchTimerStatus(loopId) {
  try {
    const response = await fetch(`/loops/${loopId}/timer/status`);
    if (!response.ok) return null;
    return response.json();
  } catch (e) {
    console.warn("Failed to load timer status:", e);
    return null;
  }
}

export async function startTimer(loopId) {
  const response = await fetch(`/loops/${loopId}/timer/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
  });
  if (!response.ok) {
    if (response.status === 409) {
      return { error: "already_running" };
    }
    const error = await response.json();
    throw new Error(error.detail || "Failed to start timer");
  }
  return response.json();
}

export async function stopTimer(loopId) {
  const response = await fetch(`/loops/${loopId}/timer/stop`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.message || "Failed to stop timer");
  }
  return response.json();
}

// ========================================
// Comment Operations
// ========================================

export async function fetchComments(loopId) {
  const response = await fetch(`/loops/${loopId}/comments`);
  if (!response.ok) throw new Error("Failed to load comments");
  return response.json();
}

export async function postComment(loopId, author, body, parentId = null) {
  const response = await fetch(`/loops/${loopId}/comments`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ author, body_md: body, parent_id: parentId }),
  });
  if (!response.ok) throw new Error("Failed to post comment");
  return response.json();
}

export async function deleteComment(loopId, commentId) {
  const response = await fetch(`/loops/${loopId}/comments/${commentId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error("Failed to delete comment");
  return true;
}

// ========================================
// Template Operations
// ========================================

export async function fetchTemplates() {
  const response = await fetch("/loops/templates");
  if (!response.ok) return [];
  const data = await response.json();
  return data.templates;
}

export async function saveLoopAsTemplate(loopId, name) {
  const response = await fetch(`/loops/${loopId}/save-as-template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.message || "Failed to create template");
  }
  return response.json();
}

// ========================================
// Tag and View Operations
// ========================================

export async function fetchTags() {
  const response = await fetch("/loops/tags");
  if (!response.ok) return [];
  return response.json();
}

export async function fetchViews() {
  const response = await fetch("/loops/views");
  if (!response.ok) return [];
  return response.json();
}

export async function saveView(name, query) {
  const response = await fetch("/loops/views", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, query }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to save view");
  }
  return response.json();
}

// ========================================
// Bulk Operations
// ========================================

export async function bulkCloseLoops(items, transactional = false) {
  const response = await fetch("/loops/bulk/close", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items, transactional }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.message || "Bulk close failed");
  }
  return response.json();
}

export async function bulkSnoozeLoops(items, transactional = false) {
  const response = await fetch("/loops/bulk/snooze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items, transactional }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.message || "Bulk snooze failed");
  }
  return response.json();
}

export async function bulkUpdateLoops(updates, transactional = false) {
  const response = await fetch("/loops/bulk/update", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ updates, transactional }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.message || "Bulk update failed");
  }
  return response.json();
}

export async function bulkEnrichLoops(items) {
  const response = await fetch("/loops/bulk/enrich", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Bulk enrich failed"));
  }
  return response.json();
}

export async function bulkEnrichQuery(query, options = {}) {
  const response = await fetch("/loops/bulk/query/enrich", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      query,
      dry_run: Boolean(options.dryRun),
      limit: Number(options.limit ?? 100),
    }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Bulk enrich query failed"));
  }
  return response.json();
}

// ========================================
// Next/Review Operations
// ========================================

export async function fetchNextLoops(limit = 10) {
  const response = await fetch(`/loops/next?limit=${limit}`);
  if (!response.ok) throw new Error("Failed to load next actions");
  return response.json();
}

export async function fetchReviewData() {
  const params = new URLSearchParams({ daily: "true", weekly: "true", limit: "10" });
  const response = await fetch(`/loops/review?${params}`);
  if (!response.ok) throw new Error("Failed to load review data");
  return response.json();
}

export async function fetchRelationshipReviewQueue(options = {}) {
  const params = new URLSearchParams({
    status: options.status ?? "open",
    relationship_kind: options.relationshipKind ?? "all",
    limit: String(options.limit ?? 25),
    candidate_limit: String(options.candidateLimit ?? 3),
  });
  const response = await fetch(`/loops/relationships/review?${params}`);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to load relationship review queue"));
  }
  return response.json();
}

export async function fetchLoopRelationshipReview(loopId, options = {}) {
  const params = new URLSearchParams({
    status: options.status ?? "open",
    duplicate_limit: String(options.duplicateLimit ?? 10),
    related_limit: String(options.relatedLimit ?? 10),
  });
  const response = await fetch(`/loops/${loopId}/relationships/review?${params}`);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to load relationship review"));
  }
  return response.json();
}

export async function confirmLoopRelationship(loopId, candidateLoopId, relationshipType) {
  const response = await fetch(`/loops/${loopId}/relationships/${candidateLoopId}/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ relationship_type: relationshipType }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to confirm loop relationship"));
  }
  return response.json();
}

export async function dismissLoopRelationship(loopId, candidateLoopId, relationshipType) {
  const response = await fetch(`/loops/${loopId}/relationships/${candidateLoopId}/dismiss`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ relationship_type: relationshipType }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to dismiss loop relationship"));
  }
  return response.json();
}

async function requestJson(path, options = {}, fallbackMessage = "Request failed") {
  const init = { ...options };
  if (init.body !== undefined && init.body !== null && !(init.body instanceof FormData)) {
    init.headers = {
      "content-type": "application/json",
      ...(options.headers || {}),
    };
    init.body = JSON.stringify(init.body);
  }

  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, fallbackMessage));
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export async function fetchRelationshipReviewActions() {
  return requestJson("/loops/review/relationship/actions", {}, "Failed to load relationship review actions");
}

export async function createRelationshipReviewAction(payload) {
  return requestJson(
    "/loops/review/relationship/actions",
    { method: "POST", body: payload },
    "Failed to create relationship review action",
  );
}

export async function updateRelationshipReviewAction(actionId, payload) {
  return requestJson(
    `/loops/review/relationship/actions/${actionId}`,
    { method: "PATCH", body: payload },
    "Failed to update relationship review action",
  );
}

export async function deleteRelationshipReviewAction(actionId) {
  return requestJson(
    `/loops/review/relationship/actions/${actionId}`,
    { method: "DELETE" },
    "Failed to delete relationship review action",
  );
}

export async function fetchRelationshipReviewSessions() {
  return requestJson(
    "/loops/review/relationship/sessions",
    {},
    "Failed to load relationship review sessions",
  );
}

export async function createRelationshipReviewSession(payload) {
  return requestJson(
    "/loops/review/relationship/sessions",
    { method: "POST", body: payload },
    "Failed to create relationship review session",
  );
}

export async function fetchRelationshipReviewSession(sessionId) {
  return requestJson(
    `/loops/review/relationship/sessions/${sessionId}`,
    {},
    "Failed to load relationship review session",
  );
}

export async function updateRelationshipReviewSession(sessionId, payload) {
  return requestJson(
    `/loops/review/relationship/sessions/${sessionId}`,
    { method: "PATCH", body: payload },
    "Failed to update relationship review session",
  );
}

export async function deleteRelationshipReviewSession(sessionId) {
  return requestJson(
    `/loops/review/relationship/sessions/${sessionId}`,
    { method: "DELETE" },
    "Failed to delete relationship review session",
  );
}

export async function runRelationshipReviewSessionAction(sessionId, payload) {
  return requestJson(
    `/loops/review/relationship/sessions/${sessionId}/action`,
    { method: "POST", body: payload },
    "Failed to run relationship review action",
  );
}

export async function moveRelationshipReviewSession(sessionId, direction) {
  return requestJson(
    `/loops/review/relationship/sessions/${sessionId}/move`,
    { method: "POST", body: { direction } },
    "Failed to move relationship review session",
  );
}

export async function fetchEnrichmentReviewActions() {
  return requestJson("/loops/review/enrichment/actions", {}, "Failed to load enrichment review actions");
}

export async function createEnrichmentReviewAction(payload) {
  return requestJson(
    "/loops/review/enrichment/actions",
    { method: "POST", body: payload },
    "Failed to create enrichment review action",
  );
}

export async function updateEnrichmentReviewAction(actionId, payload) {
  return requestJson(
    `/loops/review/enrichment/actions/${actionId}`,
    { method: "PATCH", body: payload },
    "Failed to update enrichment review action",
  );
}

export async function deleteEnrichmentReviewAction(actionId) {
  return requestJson(
    `/loops/review/enrichment/actions/${actionId}`,
    { method: "DELETE" },
    "Failed to delete enrichment review action",
  );
}

export async function fetchEnrichmentReviewSessions() {
  return requestJson(
    "/loops/review/enrichment/sessions",
    {},
    "Failed to load enrichment review sessions",
  );
}

export async function createEnrichmentReviewSession(payload) {
  return requestJson(
    "/loops/review/enrichment/sessions",
    { method: "POST", body: payload },
    "Failed to create enrichment review session",
  );
}

export async function fetchEnrichmentReviewSession(sessionId) {
  return requestJson(
    `/loops/review/enrichment/sessions/${sessionId}`,
    {},
    "Failed to load enrichment review session",
  );
}

export async function updateEnrichmentReviewSession(sessionId, payload) {
  return requestJson(
    `/loops/review/enrichment/sessions/${sessionId}`,
    { method: "PATCH", body: payload },
    "Failed to update enrichment review session",
  );
}

export async function deleteEnrichmentReviewSession(sessionId) {
  return requestJson(
    `/loops/review/enrichment/sessions/${sessionId}`,
    { method: "DELETE" },
    "Failed to delete enrichment review session",
  );
}

export async function runEnrichmentReviewSessionAction(sessionId, payload) {
  return requestJson(
    `/loops/review/enrichment/sessions/${sessionId}/action`,
    { method: "POST", body: payload },
    "Failed to run enrichment review action",
  );
}

export async function moveEnrichmentReviewSession(sessionId, direction) {
  return requestJson(
    `/loops/review/enrichment/sessions/${sessionId}/move`,
    { method: "POST", body: { direction } },
    "Failed to move enrichment review session",
  );
}

export async function answerEnrichmentReviewSessionClarifications(sessionId, payload) {
  return requestJson(
    `/loops/review/enrichment/sessions/${sessionId}/clarifications/answer`,
    { method: "POST", body: payload },
    "Failed to answer enrichment clarifications",
  );
}

// ========================================
// Metrics
// ========================================

export async function fetchMetrics() {
  const response = await fetch("/loops/metrics");
  if (!response.ok) throw new Error("Failed to load metrics");
  return response.json();
}

// ========================================
// Import/Export
// ========================================

export async function exportLoops() {
  const response = await fetch("/loops/export");
  if (!response.ok) throw new Error("Export failed");
  return response.json();
}

export async function importLoops(loops) {
  const response = await fetch("/loops/import", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ loops }),
  });
  if (!response.ok) throw new Error("Import failed");
  return response.json();
}

// ========================================
// Duplicate Operations
// ========================================

export async function fetchDuplicateCandidates(loopId) {
  const response = await fetch(`/loops/${loopId}/duplicates`);
  if (!response.ok) return null;
  return response.json();
}

export async function fetchMergePreview(duplicateLoopId, survivingLoopId) {
  const response = await fetch(`/loops/${duplicateLoopId}/merge-preview/${survivingLoopId}`);
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail?.message || "Failed to load merge preview");
  }
  return response.json();
}

export async function mergeLoops(duplicateLoopId, survivingLoopId, fieldOverrides = {}) {
  const response = await fetch(`/loops/${duplicateLoopId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_loop_id: survivingLoopId,
      field_overrides: fieldOverrides,
    }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail?.message || "Merge failed");
  }
  return response.json();
}

// ========================================
// Suggestion Operations
// ========================================

export async function fetchSuggestions(loopId, pendingOnly = true) {
  const url = `/loops/${loopId}/suggestions?pending_only=${pendingOnly}`;
  const response = await fetch(url);
  if (!response.ok) return [];
  const data = await response.json();
  return data.suggestions || [];
}

export async function applySuggestion(suggestionId, fields = null) {
  const response = await fetch(`/loops/suggestions/${suggestionId}/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || "Failed to apply suggestion");
  }
  return response.json();
}

export async function rejectSuggestion(suggestionId) {
  const response = await fetch(`/loops/suggestions/${suggestionId}/reject`, {
    method: "POST",
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || "Failed to reject suggestion");
  }
  return true;
}

export async function submitClarification(loopId, answers) {
  const response = await fetch(`/loops/${loopId}/clarifications/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || "Failed to submit clarification");
  }
  return response.json();
}

export async function refineClarification(loopId, answers) {
  const response = await fetch(`/loops/${loopId}/clarifications/refine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || "Failed to refine clarification");
  }
  return response.json();
}

export async function fetchClarifications(loopId) {
  const response = await fetch(`/loops/${loopId}/clarifications`);
  if (!response.ok) return [];
  const data = await response.json();
  return data.clarifications || [];
}

// ========================================
// Chat and RAG
// ========================================

export async function submitChatMessage(messages, stream = true, options = {}) {
  const payload = {
    messages,
    tool_mode: options.toolMode ?? undefined,
    include_loop_context: options.includeLoopContext ?? true,
    include_memory_context: options.includeMemoryContext ?? true,
    memory_limit: options.memoryLimit ?? 10,
    include_rag_context: options.includeRagContext ?? false,
    rag_k: options.ragK ?? 5,
    rag_scope: options.ragScope?.trim() ? options.ragScope.trim() : undefined,
  };

  const response = await fetch(`/chat?stream=${stream}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Chat request failed"));
  }
  return response;
}

export async function submitRagQuestion(question, stream = true) {
  const response = await fetch(`/ask?q=${encodeURIComponent(question)}&stream=${stream}`);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "RAG request failed"));
  }
  return response;
}

export async function fetchHealth() {
  const response = await fetch("/health");
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, "Failed to load health"));
  }
  return response.json();
}

export async function ingestKnowledge(paths, mode = "add", recursive = true) {
  const response = await fetch("/ingest", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ paths, mode, recursive }),
  });
  if (!response.ok) {
    let message = "Knowledge ingestion failed";
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch {
      // Fall back to the generic message when the error payload is absent.
    }
    throw new Error(message);
  }
  return response.json();
}

// ========================================
// Recurrence
// ========================================

export async function updateRecurrence(loopId, rrule, timezone, enabled) {
  const payload = {
    recurrence_rrule: enabled ? rrule : null,
    recurrence_tz: enabled ? timezone : null,
    recurrence_enabled: enabled,
  };

  const response = await fetch(`/loops/${loopId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Recurrence update failed");
  }
  return response.json();
}

// ========================================
// Snooze
// ========================================

export async function snoozeLoop(loopId, snoozeUntilUtc) {
  const response = await fetch(`/loops/${loopId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ snooze_until_utc: snoozeUntilUtc }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Snooze failed");
  }
  return response.json();
}
