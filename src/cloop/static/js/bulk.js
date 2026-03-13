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
import * as modals from './modals.js';
import { selectedLoopIds, clearLoopSelection } from './state.js';

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
export async function handleBulkAction(action) {
  const count = selectedLoopIds.size;
  if (count === 0) return;

  switch (action) {
    case "complete": {
      const confirmed = await modals.confirmDialog({
        eyebrow: "Bulk action",
        title: "Complete Loops",
        description: `Mark ${count} loop${count !== 1 ? "s" : ""} as completed?`,
        confirmLabel: "Complete loops",
      });
      if (confirmed) {
        executeBulkClose("completed");
      }
      break;
    }

    case "drop": {
      const confirmed = await modals.confirmDialog({
        eyebrow: "Bulk action",
        title: "Drop Loops",
        description: `Mark ${count} loop${count !== 1 ? "s" : ""} as dropped? This cannot be undone.`,
        confirmLabel: "Drop loops",
        confirmVariant: "danger",
      });
      if (confirmed) {
        executeBulkClose("dropped");
      }
      break;
    }

    case "status": {
      const result = await modals.promptDialog({
        eyebrow: "Bulk action",
        title: "Change Status",
        description: `Update ${count} selected loop${count !== 1 ? "s" : ""} to the same status.`,
        confirmLabel: "Apply status",
        fields: [{
          name: "status",
          label: "New status",
          type: "select",
          value: "actionable",
          options: [
            { value: "inbox", label: "Inbox" },
            { value: "actionable", label: "Actionable" },
            { value: "blocked", label: "Blocked" },
            { value: "scheduled", label: "Scheduled" },
          ],
        }],
      });
      if (result?.status) {
        executeBulkStatus(result.status);
      }
      break;
    }

    case "snooze": {
      const result = await modals.promptDialog({
        eyebrow: "Bulk action",
        title: "Snooze Loops",
        description: `Hide ${count} selected loop${count !== 1 ? "s" : ""} until a specific date and time.`,
        confirmLabel: "Snooze loops",
        fields: [{
          name: "snoozeUntil",
          label: "Snooze until",
          type: "datetime-local",
          required: true,
          helpText: "Uses your local time zone.",
        }],
        validate: ({ snoozeUntil }) => {
          if (!snoozeUntil) {
            return "Choose a snooze date and time.";
          }
          if (Number.isNaN(new Date(snoozeUntil).getTime())) {
            return "Enter a valid snooze date and time.";
          }
          return null;
        },
      });
      if (result?.snoozeUntil) {
        executeBulkSnooze(new Date(result.snoozeUntil).toISOString());
      }
      break;
    }

    case "tags": {
      const result = await modals.promptDialog({
        eyebrow: "Bulk action",
        title: "Add Tags",
        description: `Add one or more tags to ${count} selected loop${count !== 1 ? "s" : ""}.`,
        confirmLabel: "Add tags",
        fields: [{
          name: "tags",
          label: "Tags",
          placeholder: "ops, errands, deep-work",
          helpText: "Separate tags with commas.",
          required: true,
        }],
        validate: ({ tags }) => {
          if (!tags) {
            return "Enter at least one tag.";
          }
          return null;
        },
      });
      if (result?.tags) {
        const tagList = result.tags.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
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
