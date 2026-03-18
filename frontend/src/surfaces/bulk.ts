/**
 * bulk.ts - Surface bulk-action flows backed by the shared selection runtime.
 *
 * Purpose:
 *   Execute capture/do bulk mutations while sharing the canonical TypeScript
 *   bulk action-bar sync implementation.
 *
 * Responsibilities:
 *   - Execute bulk close, snooze, update, tag, and enrich mutations.
 *   - Re-export the shared bulk-action-bar updater.
 *   - Keep bulk status messaging and selection cleanup consistent.
 *
 * Scope:
 *   - Capture/do bulk-action execution only.
 *
 * Usage:
 *   - Imported by bootstrap.ts and sibling surface modules.
 *
 * Invariants/Assumptions:
 *   - frontend/src/bulk-actions.ts is the source of truth for bulk-bar sync.
 *   - Selection state comes from frontend/src/selection-state.ts via state.ts.
 */

import { updateBulkActionBar as syncBulkActionBar } from "../bulk-actions";
import { recordRecentShellAction } from "../continuity-intelligence";
import * as api from "./api";
import * as modals from "./modals";
import { loadInbox } from "./loop";
import { clearLoopSelection, selectedLoopIds } from "./state";
import { messageFromError } from "./utils";

interface BulkModuleElements {
  status: HTMLElement;
  bulkActionBar?: HTMLElement | null;
}

let statusEl: HTMLElement | null = null;

export function init(elements: BulkModuleElements): void {
  statusEl = elements.status;
  if (elements.bulkActionBar) {
    syncBulkActionBar();
  }
}

export function updateBulkActionBar(): void {
  syncBulkActionBar();
}

function statusMessage(text: string): void {
  if (statusEl) {
    statusEl.textContent = text;
  }
}

export async function executeBulkClose(status: "completed" | "dropped"): Promise<void> {
  const loopIds = Array.from(selectedLoopIds);
  const items = loopIds.map((id) => ({ loop_id: id, status }));
  statusMessage(`Closing ${items.length} loops...`);

  try {
    const result = await api.bulkCloseLoops(items, false);
    statusMessage(`Closed ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`);
    clearLoopSelection();
    syncBulkActionBar();
    await loadInbox();
  } catch (error: unknown) {
    statusMessage(messageFromError(error, "Bulk close failed."));
  }
}

export async function executeBulkSnooze(snoozeUntilUtc: string): Promise<void> {
  const loopIds = Array.from(selectedLoopIds);
  const items = loopIds.map((id) => ({ loop_id: id, snooze_until_utc: snoozeUntilUtc }));
  statusMessage(`Snoozing ${items.length} loops...`);

  try {
    const result = await api.bulkSnoozeLoops(items, false);
    recordRecentShellAction({
      kind: "snooze",
      label: `Snoozed ${result.succeeded} selected loop${result.succeeded === 1 ? "" : "s"}`,
      description: `Bulk snoozed ${result.succeeded} loop${result.succeeded === 1 ? "" : "s"}.`,
      location: {
        state: "do",
        recallTool: "chat",
        reviewFocus: null,
        sessionId: null,
        loopId: loopIds[0] ?? null,
        viewId: null,
        memoryId: null,
        query: null,
      },
      metadata: {
        snoozeUntilUtc,
        loopIds,
        succeeded: result.succeeded,
      },
    });
    statusMessage(`Snoozed ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`);
    clearLoopSelection();
    syncBulkActionBar();
  } catch (error: unknown) {
    statusMessage(messageFromError(error, "Bulk snooze failed."));
  }
}

export async function executeBulkStatus(newStatus: "inbox" | "actionable" | "blocked" | "scheduled"): Promise<void> {
  const loopIds = Array.from(selectedLoopIds);
  statusMessage(`Updating ${loopIds.length} loops...`);

  try {
    await Promise.all(loopIds.map((loopId) => api.transitionLoopStatus(loopId, newStatus)));
    statusMessage(`Updated ${loopIds.length} loop${loopIds.length !== 1 ? "s" : ""}.`);
    clearLoopSelection();
    syncBulkActionBar();
    await loadInbox();
  } catch (error: unknown) {
    statusMessage(messageFromError(error, "Bulk update failed."));
  }
}

export async function executeBulkAddTags(newTags: string[]): Promise<void> {
  const loopIds = Array.from(selectedLoopIds);
  const updates = loopIds.map((id) => {
    const card = document.querySelector<HTMLElement>(`.loop-card[data-loop-id="${id}"]`);
    const rawTags = card?.dataset["tags"];
    const existingTags = rawTags ? JSON.parse(rawTags) as string[] : [];
    const mergedTags = [...new Set([...existingTags, ...newTags])];
    return {
      loop_id: id,
      fields: { tags: mergedTags },
    };
  });

  statusMessage(`Adding tags to ${updates.length} loops...`);

  try {
    const result = await api.bulkUpdateLoops(updates, false);
    statusMessage(`Tagged ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`);
    clearLoopSelection();
    syncBulkActionBar();
  } catch (error: unknown) {
    statusMessage(messageFromError(error, "Bulk tag update failed."));
  }
}

export async function executeBulkEnrich(): Promise<void> {
  const loopIds = Array.from(selectedLoopIds);
  const items = loopIds.map((id) => ({ loop_id: id }));
  statusMessage(`Enriching ${items.length} loops...`);

  try {
    const result = await api.bulkEnrichLoops(items);
    const clarificationCount = result.results.filter((item: { ok: boolean; needs_clarification?: unknown[] | null }) => item.ok && item.needs_clarification?.length).length;
    statusMessage(
      clarificationCount > 0
        ? `Enriched ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}; ${clarificationCount} need clarification.`
        : `Enriched ${result.succeeded} loop${result.succeeded !== 1 ? "s" : ""}.`,
    );
    clearLoopSelection();
    syncBulkActionBar();
    await loadInbox();
  } catch (error: unknown) {
    statusMessage(messageFromError(error, "Bulk enrich failed."));
  }
}

export async function handleBulkAction(action: string): Promise<void> {
  const count = selectedLoopIds.size;
  if (count === 0) {
    return;
  }

  switch (action) {
    case "complete": {
      const confirmed = await modals.confirmDialog({
        eyebrow: "Bulk action",
        title: "Complete Loops",
        description: `Mark ${count} loop${count !== 1 ? "s" : ""} as completed?`,
        confirmLabel: "Complete loops",
      });
      if (confirmed) {
        await executeBulkClose("completed");
      }
      return;
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
        await executeBulkClose("dropped");
      }
      return;
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
      const selectedStatus = result?.["status"];
      if (
        selectedStatus === "inbox"
        || selectedStatus === "actionable"
        || selectedStatus === "blocked"
        || selectedStatus === "scheduled"
      ) {
        await executeBulkStatus(selectedStatus);
      }
      return;
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
        validate: (values) => {
          const snoozeUntil = values["snoozeUntil"];
          if (!snoozeUntil) {
            return "Choose a snooze date and time.";
          }
          if (Number.isNaN(new Date(snoozeUntil).getTime())) {
            return "Enter a valid snooze date and time.";
          }
          return null;
        },
      });
      if (result?.["snoozeUntil"]) {
        await executeBulkSnooze(new Date(result["snoozeUntil"]).toISOString());
      }
      return;
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
        validate: (values) => {
          if (!values["tags"]) {
            return "Enter at least one tag.";
          }
          return null;
        },
      });
      if (result?.["tags"]) {
        const tagList = result["tags"].split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean);
        if (tagList.length > 0) {
          await executeBulkAddTags(tagList);
        }
      }
      return;
    }

    case "enrich": {
      const confirmed = await modals.confirmDialog({
        eyebrow: "Bulk action",
        title: "Enrich Loops",
        description: `Run AI enrichment for ${count} selected loop${count !== 1 ? "s" : ""}?`,
        confirmLabel: "Enrich loops",
      });
      if (confirmed) {
        await executeBulkEnrich();
      }
      return;
    }

    case "clear":
      clearLoopSelection();
      syncBulkActionBar();
      return;

    default:
      return;
  }
}
