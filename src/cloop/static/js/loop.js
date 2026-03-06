/**
 * loop.js - Loop card logic and inbox management
 *
 * Purpose:
 *   Manage loop rendering, updates, and inbox interactions.
 *
 * Responsibilities:
 *   - Render and replace loop cards
 *   - Load inbox with filters
 *   - Handle inline updates (title, tags, status, etc.)
 *   - Snooze functionality
 *   - Recurrence management
 *   - Completion workflow
 *
 * Non-scope:
 *   - Timer management (see timer.js)
 *   - Bulk operations (see bulk.js)
 *   - Keyboard shortcuts (see keyboard.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import * as render from './render.js';
import * as timer from './timer.js';
import { escapeHtml, normalizeTags, isoFromLocalInput } from './utils.js';

// DOM Elements
let inbox, statusEl, queryFilter, statusFilter, tagFilter, viewFilter;

/**
 * Initialize loop module with DOM elements
 */
export function init(elements) {
  inbox = elements.inbox;
  statusEl = elements.status;
  queryFilter = elements.queryFilter;
  statusFilter = elements.statusFilter;
  tagFilter = elements.tagFilter;
  viewFilter = elements.viewFilter;
}

/**
 * Replace a loop card in the DOM
 */
export function replaceLoop(loop) {
  const rendered = render.renderLoop(loop);

  // Update in inbox view
  const existingInbox = inbox.querySelector(`[data-loop-id="${loop.id}"]`);
  if (existingInbox) {
    existingInbox.replaceWith(rendered);
  } else {
    inbox.prepend(rendered);
  }

  // Also update in nextBuckets view if present
  const nextBuckets = document.getElementById("next-buckets");
  if (nextBuckets) {
    const existingNext = nextBuckets.querySelector(`[data-loop-id="${loop.id}"]`);
    if (existingNext) {
      existingNext.replaceWith(rendered.cloneNode(true));
    }
  }

  render.queueNextActionResize(rendered);
}

export function toggleCompactCard(loopId) {
  const card = document.querySelector(`.loop-card[data-loop-id="${loopId}"]`);
  if (!card?.classList?.contains("compact-card")) {
    return;
  }

  const expanded = !card.classList.contains("compact-expanded");
  render.setCompactCardExpanded(card, expanded);
}

/**
 * Load loops into inbox based on current filters
 */
export async function loadInbox() {
  const queryValue = queryFilter.value.trim();
  let data;

  try {
    if (queryValue) {
      data = await api.searchLoops(queryValue);
    } else {
      const statusValue = statusFilter.value;
      const tagValue = tagFilter.value;
      data = await api.fetchLoops(statusValue, tagValue);
    }

    inbox.innerHTML = "";
    data.forEach((loop) => inbox.appendChild(render.renderLoop(loop)));
    render.queueNextActionResize(inbox);
  } catch (error) {
    statusEl.textContent = error.message;
    console.error("loadInbox error:", error);
  }
}

/**
 * Refresh a single loop from the server
 */
export async function refreshLoop(loopId) {
  try {
    const loop = await api.fetchLoop(loopId);
    if (!loop) {
      statusEl.textContent = "Failed to refresh loop.";
      return;
    }

    // Check timer status
    const timerStatus = await timer.loadTimerStatus(loopId);
    loop.timer_running = timerStatus?.has_active_session || false;
    loop.timer_display = '';
    if (timerStatus?.has_active_session && timerStatus.active_session) {
      const elapsed = timerStatus.active_session.elapsed_seconds ||
        Math.floor((Date.now() - new Date(timerStatus.active_session.started_at_utc).getTime()) / 1000);
      loop.timer_display = render.formatDuration(elapsed);
    }
    loop.total_tracked_minutes = timerStatus ? Math.floor(timerStatus.total_tracked_seconds / 60) : 0;

    replaceLoop(loop);

    // Restore timer UI if running
    if (timerStatus?.has_active_session) {
      timer.startTimerUI(loopId, timerStatus);
    }
  } catch (error) {
    statusEl.textContent = "Failed to refresh loop.";
    console.error("refreshLoop error:", error);
  }
}

/**
 * Handle status transition
 */
export async function transitionStatus(loopId, nextStatus) {
  try {
    const result = await api.transitionLoopStatus(loopId, nextStatus);
    replaceLoop(result);
    return result;
  } catch (error) {
    statusEl.textContent = error.message;
    return null;
  }
}

/**
 * Apply inline field updates to a loop
 */
export async function applyInlineUpdate(target) {
  const card = target.closest(".loop-card");
  if (!card) return;
  const loopId = card.dataset.loopId;
  const field = target.dataset.field;
  if (!field) return;
  if (field === "tags_add") return;

  if (field === "title" && target.dataset.initial === target.value.trim()) {
    return;
  }

  if (field === "status") {
    const nextStatus = target.value;
    const initialStatus = target.dataset.initial || "";
    if (nextStatus === initialStatus) return;

    if (nextStatus === "completed") {
      if (card) {
        card.dataset.pendingStatus = "completed";
        card.dataset.previousStatus = initialStatus;
        card.dataset.status = "completed";
      }
      showCompletionNote(loopId);
      return;
    }

    await transitionStatus(loopId, nextStatus);
    return;
  }

  const payload = {};
  const nextInput = card.querySelector('[data-field="next_action"]');
  const dueInput = card.querySelector('[data-field="due_at_utc"]');
  const blockedInput = card.querySelector('[data-field="blocked_reason"]');
  const titleInput = card.querySelector('[data-field="title"]');

  if (nextInput) {
    const nextValue = nextInput.value.trim();
    const initialNext = nextInput.dataset.initial || "";
    if (nextValue !== initialNext) {
      payload.next_action = nextValue || null;
    }
  }

  if (titleInput) {
    const titleValue = titleInput.value.trim();
    const initialTitle = titleInput.dataset.initial || "";
    if (titleValue !== initialTitle) {
      payload.title = titleValue || null;
    }
  }

  if (dueInput) {
    const dueIso = isoFromLocalInput(dueInput.value);
    const initialDue = dueInput.dataset.initial || "";
    if (!dueInput.value && initialDue) {
      payload.due_at_utc = null;
    } else if (dueIso && dueIso !== initialDue) {
      payload.due_at_utc = dueIso;
    }
  }

  if (blockedInput) {
    const blockedValue = blockedInput.value.trim();
    const initialBlocked = blockedInput.dataset.initial || "";
    if (blockedValue !== initialBlocked) {
      payload.blocked_reason = blockedValue || null;
    }
  }

  if (Object.keys(payload).length) {
    try {
      const updated = await api.updateLoop(loopId, payload);
      if (updated) {
        replaceLoop(updated);
      }
    } catch (error) {
      statusEl.textContent = error.message;
    }
  }
}

/**
 * Show completion note input
 */
export function showCompletionNote(loopId) {
  const card = document.querySelector(`.loop-card[data-loop-id="${loopId}"]`);
  if (!card) return;

  const noteRow = card.querySelector(".completion-note-row");
  if (noteRow) {
    noteRow.classList.add("visible");
    noteRow.classList.add("completing");
    const input = noteRow.querySelector(".completion-note-input");
    if (input) {
      input.dataset.mode = "complete";
      input.value = input.dataset.initial || "";
      input.focus();
    }
  }
}

/**
 * Hide completion note input
 */
export function hideCompletionNote(loopId) {
  const card = document.querySelector(`.loop-card[data-loop-id="${loopId}"]`);
  if (!card) return;

  const noteRow = card.querySelector(".completion-note-row");
  if (!noteRow) return;

  const input = noteRow.querySelector(".completion-note-input");
  noteRow.classList.remove("completing");

  if (input) {
    input.dataset.mode = "edit";
    input.value = input.dataset.initial || "";

    const statusSelect = card.querySelector('[data-field="status"]');
    const currentStatus = statusSelect ? statusSelect.value : card.dataset.status;
    const pinned = currentStatus === "completed" || Boolean(input.dataset.initial?.trim());

    if (card.dataset.pendingStatus === "completed") {
      const previous = card.dataset.previousStatus || "";
      if (statusSelect && previous) {
        statusSelect.value = previous;
        statusSelect.dataset.initial = previous;
      }
      if (previous) {
        card.dataset.status = previous;
      }
      delete card.dataset.pendingStatus;
      delete card.dataset.previousStatus;
    }

    if (!pinned) {
      noteRow.classList.remove("visible");
    }
  } else {
    noteRow.classList.remove("visible");
  }
}

/**
 * Save completion note
 */
export async function saveCompletionNote(loopId, input) {
  const noteValue = input.value.trim();
  const initialValue = input.dataset.initial || "";
  if (noteValue === initialValue) return;

  try {
    const updated = await api.updateLoop(loopId, {
      completion_note: noteValue || null,
    });
    if (updated) {
      replaceLoop(updated);
    }
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

/**
 * Confirm completion with optional note
 */
export async function confirmComplete(loopId, note) {
  try {
    const updated = await api.transitionLoopStatus(loopId, "completed", note);
    const filterValue = statusFilter.value;
    const shouldHide =
      filterValue === "open" ||
      (filterValue && filterValue !== "all" && filterValue !== "completed");

    if (shouldHide) {
      const card = inbox.querySelector(`[data-loop-id="${loopId}"]`);
      card?.remove();
      return;
    }
    replaceLoop(updated);
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

/**
 * Request enrichment for a loop
 */
export async function enrichLoop(loopId) {
  statusEl.textContent = "Enrichment requested...";
  try {
    const loop = await api.enrichLoop(loopId);
    replaceLoop(loop);
    statusEl.textContent = "Enrichment running...";
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

/**
 * Toggle snooze dropdown visibility
 */
export function toggleSnoozeDropdown(loopId) {
  const dropdown = document.querySelector(`[data-snooze-dropdown="${loopId}"]`);
  if (!dropdown) return;

  // Close other dropdowns
  document.querySelectorAll('.snooze-dropdown.visible').forEach(d => {
    if (d !== dropdown) d.classList.remove('visible');
  });

  dropdown.classList.toggle('visible');
}

/**
 * Snooze a loop
 */
export async function snoozeLoop(loopId, snoozeUntilUtc) {
  try {
    const updated = await api.snoozeLoop(loopId, snoozeUntilUtc);
    replaceLoop(updated);
    statusEl.textContent = snoozeUntilUtc ? 'Loop snoozed successfully.' : 'Snooze cleared.';
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

/**
 * Toggle recurrence section visibility
 */
export function toggleRecurrenceSection(loopId, show) {
  const section = document.querySelector(`[data-recurrence-section="${loopId}"]`);
  if (!section) return;

  const config = section.querySelector('.recurrence-config');
  if (config) {
    config.classList.toggle('visible', show);
  }
  section.classList.toggle('expanded', show);
}

/**
 * Update loop recurrence
 */
export async function updateRecurrence(loopId, rrule, tz, enabled) {
  try {
    const updated = await api.updateRecurrence(loopId, rrule, tz, enabled);
    replaceLoop(updated);

    // Update preview
    const preview = document.querySelector(`[data-recurrence-preview="${loopId}"]`);
    if (preview) {
      if (updated.next_due_at_utc) {
        preview.textContent = `Next: ${formatTime(updated.next_due_at_utc)}`;
        preview.style.display = 'flex';
      } else if (enabled) {
        preview.textContent = 'Enter a schedule to see next occurrence';
        preview.style.display = 'flex';
      } else {
        preview.style.display = 'none';
      }
    }

    // Clear error
    const errorEl = document.querySelector(`[data-recurrence-error="${loopId}"]`);
    if (errorEl) {
      errorEl.classList.remove('visible');
    }

    statusEl.textContent = enabled ? 'Recurrence enabled.' : 'Recurrence disabled.';
  } catch (error) {
    statusEl.textContent = error.message;

    // Show error in UI
    const errorEl = document.querySelector(`[data-recurrence-error="${loopId}"]`);
    if (errorEl) {
      errorEl.textContent = error.message;
      errorEl.classList.add('visible');
    }
  }
}

/**
 * Get tags from a loop card
 */
export function getTagsFromCard(card) {
  return Array.from(card.querySelectorAll(".tag-chip"))
    .map((chip) => chip.dataset.tag || "")
    .filter(Boolean);
}

/**
 * Append tags from input to a loop
 */
export async function appendTagsFromInput(input) {
  const card = input.closest(".loop-card");
  const tagsWrap = input.closest(".tags-edit");
  if (!card || !tagsWrap) return;

  const newTags = normalizeTags(input.value);
  input.value = "";
  tagsWrap.classList.remove("editing");

  if (!newTags.length) return;

  const existing = getTagsFromCard(card);
  const combined = [...existing];
  newTags.forEach((tag) => {
    if (!combined.includes(tag)) {
      combined.push(tag);
    }
  });

  if (
    combined.length === existing.length &&
    combined.every((tag, index) => tag === existing[index])
  ) {
    return;
  }

  try {
    const updated = await api.updateLoop(card.dataset.loopId, { tags: combined });
    if (updated) {
      replaceLoop(updated);
    }
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

/**
 * Remove a tag from a loop
 */
export async function removeTag(loopId, tag, card) {
  const existing = getTagsFromCard(card);
  const updatedTags = existing.filter((value) => value !== tag);

  if (updatedTags.length === existing.length) return;

  try {
    const updated = await api.updateLoop(loopId, { tags: updatedTags });
    if (updated) {
      replaceLoop(updated);
    }
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

/**
 * Handle loop closed event
 */
export function handleLoopClosed(loopId, payload) {
  const filterValue = statusFilter.value;
  const shouldHide = filterValue === 'open' ||
    (filterValue && filterValue !== 'all' && filterValue !== payload?.to);

  if (shouldHide) {
    const card = inbox.querySelector(`[data-loop-id="${loopId}"]`);
    card?.remove();
  } else {
    refreshLoop(loopId);
  }
}
