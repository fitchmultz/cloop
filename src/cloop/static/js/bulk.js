/**
 * bulk.js - Bulk selection and actions
 *
 * Purpose:
 *   Manage bulk selection of loops and execute bulk operations.
 *
 * Responsibilities:
 *   - Selection state management
 *   - Bulk action bar UI
 *   - Bulk operations (complete, drop, snooze, status, tags)
 *   - Confirmation modals for bulk actions
 *
 * Non-scope:
 *   - Individual loop operations (see loop.js)
 *   - Timer management (see timer.js)
 *   - Keyboard shortcuts (see keyboard.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { selectedLoopIds, clearLoopSelection } from './state.js';
import { snoozeDurationToUtc } from './utils.js';

let statusEl, bulkActionBar;

/**
 * Initialize bulk module
 */
export function init(elements) {
  statusEl = elements.status;
  bulkActionBar = elements.bulkActionBar;
}

/**
 * Update bulk action bar visibility and count
 */
export function updateBulkActionBar() {
  const count = selectedLoopIds.size;

  if (count > 0) {
    bulkActionBar.classList.add("visible");
    bulkActionBar.querySelector(".bulk-count").textContent =
      `${count} loop${count !== 1 ? "s" : ""} selected`;
  } else {
    bulkActionBar.classList.remove("visible");
  }

  // Update selected state on cards
  document.querySelectorAll(".loop-card").forEach((card) => {
    const loopId = parseInt(card.dataset.loopId, 10);
    const checkbox = card.querySelector(".loop-checkbox");
    if (selectedLoopIds.has(loopId)) {
      card.classList.add("selected");
      if (checkbox) checkbox.checked = true;
    } else {
      card.classList.remove("selected");
      if (checkbox) checkbox.checked = false;
    }
  });
}

/**
 * Show bulk confirmation modal
 */
export function showBulkConfirm(title, message, action) {
  state.setPendingBulkAction(action);
  document.getElementById("bulk-confirm-title").textContent = title;
  document.getElementById("bulk-confirm-message").textContent = message;
  document.getElementById("bulk-confirm-modal").classList.add("visible");
}

/**
 * Hide bulk confirmation modal
 */
export function hideBulkConfirm() {
  state.clearPendingBulkAction();
  document.getElementById("bulk-confirm-modal").classList.remove("visible");
}

/**
 * Execute bulk close (complete or drop)
 */
export async function executeBulkClose(status) {
  const loopIds = Array.from(selectedLoopIds);
  const items = loopIds.map((id) => ({ loop_id: id, status }));

  statusEl.textContent = `Closing ${items.length} loops...`;

  try {
    const result = await api.bulkCloseLoops(items, false);
    statusEl.textContent = `Closed ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`;
    clearLoopSelection();
    updateBulkActionBar();
    // SSE will auto-refresh the affected loops
  } catch (error) {
    console.error("Bulk close error:", error);
    statusEl.textContent = error.message;
  }
}

/**
 * Execute bulk snooze
 */
export async function executeBulkSnooze(snoozeUntilUtc) {
  const loopIds = Array.from(selectedLoopIds);
  const items = loopIds.map((id) => ({ loop_id: id, snooze_until_utc: snoozeUntilUtc }));

  statusEl.textContent = `Snoozing ${items.length} loops...`;

  try {
    const result = await api.bulkSnoozeLoops(items, false);
    statusEl.textContent = `Snoozed ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`;
    clearLoopSelection();
    updateBulkActionBar();
  } catch (error) {
    console.error("Bulk snooze error:", error);
    statusEl.textContent = error.message;
  }
}

/**
 * Execute bulk status change
 */
export async function executeBulkStatus(newStatus) {
  const loopIds = Array.from(selectedLoopIds);
  const updates = loopIds.map((id) => ({
    loop_id: id,
    fields: { status: newStatus },
  }));

  statusEl.textContent = `Updating ${updates.length} loops...`;

  try {
    const result = await api.bulkUpdateLoops(updates, false);
    statusEl.textContent = `Updated ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`;
    clearLoopSelection();
    updateBulkActionBar();
  } catch (error) {
    console.error("Bulk update error:", error);
    statusEl.textContent = error.message;
  }
}

/**
 * Execute bulk add tags
 */
export async function executeBulkAddTags(newTags) {
  const loopIds = Array.from(selectedLoopIds);

  // Merge new tags with existing tags for each loop
  const updates = loopIds.map((id) => {
    const card = document.querySelector(`.loop-card[data-loop-id="${id}"]`);
    const existingTags = card ? JSON.parse(card.dataset.tags || "[]") : [];
    const mergedTags = [...new Set([...existingTags, ...newTags])];
    return {
      loop_id: id,
      fields: { tags: mergedTags },
    };
  });

  statusEl.textContent = `Adding tags to ${updates.length} loops...`;

  try {
    const result = await api.bulkUpdateLoops(updates, false);
    statusEl.textContent = `Tagged ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`;
    clearLoopSelection();
    updateBulkActionBar();
  } catch (error) {
    console.error("Bulk tag error:", error);
    statusEl.textContent = error.message;
  }
}

/**
 * Handle bulk action button clicks
 */
export function handleBulkAction(action) {
  const count = selectedLoopIds.size;
  if (count === 0) return;

  switch (action) {
    case "complete":
      showBulkConfirm(
        "Complete Loops",
        `Mark ${count} loop${count !== 1 ? "s" : ""} as completed?`,
        () => executeBulkClose("completed")
      );
      break;

    case "drop":
      showBulkConfirm(
        "Drop Loops",
        `Mark ${count} loop${count !== 1 ? "s" : ""} as dropped? This cannot be undone.`,
        () => executeBulkClose("dropped")
      );
      break;

    case "status": {
      const newStatus = prompt("Enter new status (inbox, actionable, blocked, scheduled):");
      if (newStatus && ["inbox", "actionable", "blocked", "scheduled"].includes(newStatus.toLowerCase())) {
        executeBulkStatus(newStatus.toLowerCase());
      } else if (newStatus) {
        statusEl.textContent = "Invalid status. Must be one of: inbox, actionable, blocked, scheduled.";
      }
      break;
    }

    case "snooze": {
      const snoozeDate = prompt("Enter snooze date (YYYY-MM-DD HH:MM):");
      if (snoozeDate) {
        const date = new Date(snoozeDate);
        if (!Number.isNaN(date.getTime())) {
          executeBulkSnooze(date.toISOString());
        } else {
          statusEl.textContent = "Invalid date format.";
        }
      }
      break;
    }

    case "tags": {
      const tags = prompt("Enter tags to add (comma-separated):");
      if (tags) {
        const tagList = tags.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
        if (tagList.length > 0) {
          executeBulkAddTags(tagList);
        }
      }
      break;
    }

    case "clear":
      clearLoopSelection();
      updateBulkActionBar();
      break;
  }
}
