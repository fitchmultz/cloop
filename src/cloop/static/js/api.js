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
  if (!response.ok) throw new Error("Failed to search loops");
  const result = await response.json();
  return result.items;
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
  if (!response.ok) throw new Error("Enrichment request failed");
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
  const response = await fetch(`/loops/${loopId}/clarify`, {
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
  const response = await fetch(`/chat?stream=${stream}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      messages,
      tool_mode: "none",
      include_loop_context: options.includeLoopContext ?? true,
      include_memory_context: options.includeMemoryContext ?? true,
      include_rag_context: options.includeRagContext ?? false,
    }),
  });
  if (!response.ok) throw new Error("Chat request failed");
  return response;
}

export async function submitRagQuestion(question, stream = true) {
  const response = await fetch(`/ask?q=${encodeURIComponent(question)}&stream=${stream}`);
  if (!response.ok) throw new Error("RAG request failed");
  return response;
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
