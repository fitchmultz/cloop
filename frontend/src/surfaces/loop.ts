/**
 * loop.ts - Loop card logic and inbox management.
 *
 * Purpose:
 *   Manage loop rendering, updates, and inbox interactions for the shared
 *   capture/do work surfaces.
 *
 * Responsibilities:
 *   - Load loops into the inbox using current filters and query mode.
 *   - Render or replace loop cards in place.
 *   - Handle inline updates, completion notes, tags, snooze, and recurrence.
 *   - Coordinate with timer and next-surface refresh behavior.
 *
 * Scope:
 *   - Capture/do loop-card behavior only.
 *
 * Usage:
 *   - Imported by bootstrap.ts, timer.ts, and suggestions.ts.
 *
 * Invariants/Assumptions:
 *   - Loop cards render through render.ts.
 *   - Inbox filters are shell-owned DOM controls passed through init().
 */

import { recordRecentShellAction } from "../continuity-intelligence";
import * as api from "./api";
import * as render from "./render";
import * as timer from "./timer";
import type { QueryMode, SurfaceLoop } from "./contracts";
import {
  formatTime,
  isoFromLocalDateAndTime,
  messageFromError,
  normalizeTags,
  parseUserDateInput,
} from "./utils";

interface LoopModuleElements {
  inbox: HTMLElement;
  status: HTMLElement;
  queryFilter: HTMLInputElement;
  queryModeFilter?: HTMLSelectElement | null;
  statusFilter: HTMLSelectElement;
  tagFilter: HTMLSelectElement;
  viewFilter: HTMLSelectElement;
}

let inbox: HTMLElement | null = null;
let statusEl: HTMLElement | null = null;
let queryFilter: HTMLInputElement | null = null;
let queryModeFilter: HTMLSelectElement | null = null;
let statusFilter: HTMLSelectElement | null = null;
let tagFilter: HTMLSelectElement | null = null;
let viewFilter: HTMLSelectElement | null = null;

const OPEN_STATUSES = new Set(["inbox", "actionable", "blocked", "scheduled"]);
const ALL_LOOP_STATUSES = new Set(["inbox", "actionable", "blocked", "scheduled", "completed", "dropped"]);
let inboxReloadScheduled = false;
let nextRefreshScheduled = false;

function isLoopStatus(value: unknown): value is SurfaceLoop["status"] {
  return typeof value === "string" && ALL_LOOP_STATUSES.has(value);
}

function removeInboxEmptyState(): void {
  inbox?.querySelector(".inbox-empty-state")?.remove();
}

function activeInboxQuery(): string {
  return queryFilter?.value.trim() || "";
}

function activeQueryMode(): QueryMode {
  return queryModeFilter?.value === "semantic" ? "semantic" : "dsl";
}

function usesServerDrivenInboxResults(): boolean {
  return Boolean(activeInboxQuery());
}

function activeStatusFilter(): string {
  return statusFilter?.value || "open";
}

function activeTagFilter(): string {
  return tagFilter?.value || "";
}

function loopMatchesInboxFilters(loop: Pick<SurfaceLoop, "status" | "tags">): boolean {
  const statusValue = activeStatusFilter();
  if (statusValue === "open") {
    if (!OPEN_STATUSES.has(loop.status)) {
      return false;
    }
  } else if (statusValue !== "all" && statusValue && loop.status !== statusValue) {
    return false;
  }

  const tagValue = activeTagFilter();
  const tags = Array.isArray(loop.tags) ? loop.tags : [];
  if (tagValue && tagValue !== "all" && !tags.includes(tagValue)) {
    return false;
  }

  return true;
}

function ensureInboxState(): void {
  if (!inbox) {
    return;
  }

  if (inbox.querySelector(".loop-card")) {
    removeInboxEmptyState();
    return;
  }

  removeInboxEmptyState();
  inbox.appendChild(
    render.renderInboxEmptyState({
      query: activeInboxQuery(),
      status: activeStatusFilter(),
      tag: activeTagFilter(),
    }),
  );
}

function removeLoopFromInbox(loopId: number | string): void {
  const card = inbox?.querySelector(`[data-loop-id="${loopId}"]`);
  card?.remove();
  ensureInboxState();
}

function queueInboxReload(): void {
  if (inboxReloadScheduled) {
    return;
  }
  inboxReloadScheduled = true;
  queueMicrotask(async () => {
    inboxReloadScheduled = false;
    await loadInbox();
  });
}

function queueNextRefresh(): void {
  if (nextRefreshScheduled) {
    return;
  }
  nextRefreshScheduled = true;
  queueMicrotask(async () => {
    nextRefreshScheduled = false;
    const nextBuckets = document.getElementById("next-buckets");
    if (!nextBuckets) {
      return;
    }
    const nextModule = await import("./next");
    await nextModule.loadNext();
  });
}

function syncInboxLoop(loop: SurfaceLoop): void {
  if (!inbox) {
    return;
  }

  if (usesServerDrivenInboxResults()) {
    queueInboxReload();
    return;
  }

  const existingInbox = inbox.querySelector(`[data-loop-id="${loop.id}"]`);
  if (!loopMatchesInboxFilters(loop)) {
    existingInbox?.remove();
    ensureInboxState();
    return;
  }

  const rendered = render.renderLoop(loop);
  if (existingInbox) {
    existingInbox.replaceWith(rendered);
  } else {
    removeInboxEmptyState();
    inbox.prepend(rendered);
  }

  render.queueNextActionResize(rendered);
}

function findLoopCard(loopId: number | string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`.loop-card[data-loop-id="${loopId}"]`);
}

export function init(elements: LoopModuleElements): void {
  inbox = elements.inbox;
  statusEl = elements.status;
  queryFilter = elements.queryFilter;
  queryModeFilter = elements.queryModeFilter ?? null;
  statusFilter = elements.statusFilter;
  tagFilter = elements.tagFilter;
  viewFilter = elements.viewFilter;
}

export function replaceLoop(loop: SurfaceLoop): void {
  syncInboxLoop(loop);
  queueNextRefresh();
}

export function toggleCompactCard(loopId: number | string | null | undefined): void {
  if (loopId == null) {
    return;
  }
  const card = findLoopCard(loopId);
  if (!card?.classList.contains("compact-card")) {
    return;
  }

  const expanded = !card.classList.contains("compact-expanded");
  render.setCompactCardExpanded(card, expanded);
}

export function toggleMobileCardText(loopId: number | string | null | undefined): void {
  if (loopId == null) {
    return;
  }
  const card = findLoopCard(loopId);
  if (!card?.classList.contains("mobile-text-collapsible")) {
    return;
  }

  const expanded = !card.classList.contains("mobile-text-expanded");
  render.setMobileCardTextExpanded(card, expanded);
}

export async function loadInbox(): Promise<void> {
  if (!inbox || !statusEl || !queryFilter || !statusFilter || !tagFilter) {
    return;
  }

  const inboxEl = inbox;
  const queryValue = queryFilter.value.trim();
  let data: SurfaceLoop[] = [];

  try {
    if (queryValue) {
      if (activeQueryMode() === "semantic") {
        const result = await api.searchLoopsSemantic(queryValue, {
          status: statusFilter.value,
        });
        data = result.items as SurfaceLoop[];
        statusEl.textContent = result.indexed_count
          ? `Semantic search refreshed ${result.indexed_count} loop embeddings.`
          : `Semantic search returned ${result.match_count} loop matches.`;
      } else {
        data = await api.searchLoops(queryValue);
      }
    } else {
      data = await api.fetchLoops(statusFilter.value, tagFilter.value || null);
    }

    inboxEl.innerHTML = "";
    if (data.length === 0) {
      inboxEl.appendChild(render.renderInboxEmptyState({
        query: queryValue,
        status: statusFilter.value,
        tag: tagFilter.value,
      }));
      return;
    }

    data.forEach((loopItem) => inboxEl.appendChild(render.renderLoop(loopItem)));
    render.queueNextActionResize(inboxEl);
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to load inbox.");
  }
}

export async function refreshLoop(loopId: number | string): Promise<void> {
  if (!statusEl) {
    return;
  }

  try {
    const loop = await api.fetchLoop(loopId);
    if (!loop) {
      removeLoopFromInbox(loopId);
      queueNextRefresh();
      return;
    }

    const timerStatus = await timer.loadTimerStatus(loopId);
    loop.timer_running = timerStatus?.has_active_session || false;
    loop.timer_display = "";
    if (timerStatus?.has_active_session && timerStatus.active_session) {
      const elapsed = Math.floor((Date.now() - new Date(timerStatus.active_session.started_at_utc).getTime()) / 1000);
      loop.timer_display = render.formatDuration(elapsed);
    }
    loop.total_tracked_minutes = timerStatus?.total_tracked_minutes ?? 0;

    replaceLoop(loop);
    if (timerStatus?.has_active_session && timerStatus.active_session) {
      timer.startTimerUI(loopId, { active_session: timerStatus.active_session });
    }
  } catch {
    statusEl.textContent = "Failed to refresh loop.";
  }
}

export async function transitionStatus(
  loopId: number | string,
  nextStatus: string,
): Promise<SurfaceLoop | null> {
  if (!statusEl) {
    return null;
  }

  try {
    const result = await api.transitionLoopStatus(loopId, nextStatus);
    replaceLoop(result);
    return result;
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Status transition failed.");
    return null;
  }
}

export async function applyInlineUpdate(target: HTMLElement): Promise<boolean> {
  if (!statusEl) {
    return false;
  }

  const card = target.closest(".loop-card");
  if (!(card instanceof HTMLElement)) {
    return false;
  }
  const loopId = card.dataset["loopId"];
  const field = target.dataset["field"];
  if (!loopId || !field || field === "tags_add") {
    return false;
  }

  if (field === "title" && target instanceof HTMLInputElement && target.dataset["initial"] === target.value.trim()) {
    return true;
  }

  if (field === "status" && target instanceof HTMLSelectElement) {
    const nextStatus = target.value;
    const initialStatus = target.dataset["initial"] || "";
    if (nextStatus === initialStatus) {
      return true;
    }

    if (nextStatus === "completed") {
      card.dataset["pendingStatus"] = "completed";
      card.dataset["previousStatus"] = initialStatus;
      card.dataset["status"] = "completed";
      showCompletionNote(loopId);
      return true;
    }

    await transitionStatus(loopId, nextStatus);
    return true;
  }

  const payload: Record<string, unknown> = {};
  const nextInput = card.querySelector('[data-field="next_action"]');
  const dueDateInput = card.querySelector<HTMLInputElement>('[data-field="due_date"]');
  const dueTimeInput = card.querySelector<HTMLInputElement>('[data-field="due_time"]');
  const blockedInput = card.querySelector<HTMLInputElement>('[data-field="blocked_reason"]');
  const titleInput = card.querySelector('[data-field="title"]');

  if (nextInput instanceof HTMLTextAreaElement) {
    const nextValue = nextInput.value.trim();
    const initialNext = nextInput.dataset["initial"] || "";
    if (nextValue !== initialNext) {
      payload["next_action"] = nextValue || null;
    }
  }

  if (titleInput instanceof HTMLInputElement) {
    const titleValue = titleInput.value.trim();
    const initialTitle = titleInput.dataset["initial"] || "";
    if (titleValue !== initialTitle) {
      payload["title"] = titleValue || null;
    }
  }

  if (dueDateInput instanceof HTMLInputElement) {
    const rawDueDate = dueDateInput.value.trim();
    const rawDueTime = dueTimeInput instanceof HTMLInputElement ? dueTimeInput.value : "";
    const initialDate = dueDateInput.dataset["initialDate"] || "";
    const initialTimestamp = dueDateInput.dataset["initialTimestamp"] || "";
    const initialTime = dueTimeInput instanceof HTMLInputElement ? dueTimeInput.dataset["initialTime"] || "" : "";

    if (!rawDueDate) {
      if (initialDate || initialTimestamp) {
        payload["due_date"] = null;
        payload["due_at_utc"] = null;
      }
    } else {
      const parsedDueDate = parseUserDateInput(rawDueDate);
      if (!parsedDueDate) {
        dueDateInput.setAttribute("aria-invalid", "true");
        statusEl.textContent = "Enter a valid due date as MM/DD/YYYY.";
        dueDateInput.focus();
        dueDateInput.select();
        return false;
      }

      dueDateInput.value = parsedDueDate.displayValue;
      dueDateInput.removeAttribute("aria-invalid");

      if (rawDueTime) {
        const dueIso = isoFromLocalDateAndTime(parsedDueDate.isoDate, rawDueTime);
        if (!dueIso) {
          statusEl.textContent = "Enter a valid due time.";
          dueTimeInput?.focus();
          return false;
        }
        if (dueIso !== initialTimestamp || rawDueTime !== initialTime || initialDate) {
          payload["due_date"] = null;
          payload["due_at_utc"] = dueIso;
        }
      } else if (parsedDueDate.isoDate !== initialDate || initialTime || initialTimestamp) {
        payload["due_date"] = parsedDueDate.isoDate;
      }
    }
  }

  if (blockedInput instanceof HTMLInputElement) {
    const blockedValue = blockedInput.value.trim();
    const initialBlocked = blockedInput.dataset["initial"] || "";
    if (blockedValue !== initialBlocked) {
      payload["blocked_reason"] = blockedValue || null;
    }
  }

  if (Object.keys(payload).length > 0) {
    try {
      const updated = await api.updateLoop(loopId, payload);
      if (updated) {
        replaceLoop(updated);
      }
      return true;
    } catch (error: unknown) {
      statusEl.textContent = messageFromError(error, "Failed to update loop.");
      return false;
    }
  }

  return true;
}

export function showCompletionNote(loopId: number | string): void {
  const card = findLoopCard(loopId);
  if (!card) {
    return;
  }

  const noteRow = card.querySelector(".completion-note-row");
  if (noteRow instanceof HTMLElement) {
    noteRow.classList.add("visible", "completing");
    const input = noteRow.querySelector(".completion-note-input");
    if (input instanceof HTMLInputElement) {
      input.dataset["mode"] = "complete";
      input.value = input.dataset["initial"] || "";
      input.focus();
    }
  }
}

export function hideCompletionNote(loopId: number | string): void {
  const card = findLoopCard(loopId);
  if (!card) {
    return;
  }

  const noteRow = card.querySelector(".completion-note-row");
  if (!(noteRow instanceof HTMLElement)) {
    return;
  }

  const input = noteRow.querySelector(".completion-note-input");
  noteRow.classList.remove("completing");

  if (input instanceof HTMLInputElement) {
    input.dataset["mode"] = "edit";
    input.value = input.dataset["initial"] || "";

    const statusSelect = card.querySelector('[data-field="status"]');
    const currentStatus = statusSelect instanceof HTMLSelectElement ? statusSelect.value : card.dataset["status"] || "";
    const pinned = currentStatus === "completed" || Boolean(input.dataset["initial"]?.trim());

    if (card.dataset["pendingStatus"] === "completed") {
      const previous = card.dataset["previousStatus"] || "";
      if (statusSelect instanceof HTMLSelectElement && previous) {
        statusSelect.value = previous;
        statusSelect.dataset["initial"] = previous;
      }
      if (previous) {
        card.dataset["status"] = previous;
      }
      delete card.dataset["pendingStatus"];
      delete card.dataset["previousStatus"];
    }

    if (!pinned) {
      noteRow.classList.remove("visible");
    }
  } else {
    noteRow.classList.remove("visible");
  }
}

export async function saveCompletionNote(loopId: number | string, input: HTMLInputElement): Promise<void> {
  if (!statusEl) {
    return;
  }

  const noteValue = input.value.trim();
  const initialValue = input.dataset["initial"] || "";
  if (noteValue === initialValue) {
    return;
  }

  try {
    const updated = await api.updateLoop(loopId, { completion_note: noteValue || null });
    if (updated) {
      replaceLoop(updated);
    }
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to save completion note.");
  }
}

export async function confirmComplete(loopId: number | string, note: string): Promise<void> {
  if (!statusEl) {
    return;
  }

  try {
    const updated = await api.transitionLoopStatus(loopId, "completed", note);
    replaceLoop(updated);
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to complete loop.");
  }
}

export async function enrichLoop(loopId: number | string): Promise<void> {
  if (!statusEl) {
    return;
  }

  statusEl.textContent = "Enriching loop...";
  try {
    const result = await api.enrichLoop(loopId);
    replaceLoop(result.loop);
    const clarificationCount = Array.isArray(result.needs_clarification) ? result.needs_clarification.length : 0;
    statusEl.textContent = clarificationCount
      ? `Enrichment complete. ${clarificationCount} clarification question${clarificationCount === 1 ? "" : "s"} added.`
      : "Enrichment complete.";
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Enrichment failed.");
  }
}

export function toggleSnoozeDropdown(loopId: number | string): void {
  const dropdown = document.querySelector(`[data-snooze-dropdown="${loopId}"]`);
  if (!(dropdown instanceof HTMLElement)) {
    return;
  }

  document.querySelectorAll<HTMLElement>(".snooze-dropdown.visible").forEach((openDropdown) => {
    if (openDropdown !== dropdown) {
      openDropdown.classList.remove("visible");
    }
  });
  dropdown.classList.toggle("visible");
}

export async function snoozeLoop(loopId: number | string, snoozeUntilUtc: string | null): Promise<void> {
  if (!statusEl) {
    return;
  }

  try {
    const updated = await api.snoozeLoop(loopId, snoozeUntilUtc);
    replaceLoop(updated);
    recordRecentShellAction({
      kind: "snooze",
      label: snoozeUntilUtc ? `Snoozed loop #${updated.id}` : `Cleared snooze for loop #${updated.id}`,
      description: updated.title?.trim() || updated.raw_text.trim() || `Loop #${updated.id}`,
      location: {
        state: "do",
        recallTool: "chat",
        reviewFocus: null,
        sessionId: null,
        loopId: updated.id,
        viewId: null,
        memoryId: null,
        query: null,
      },
      metadata: {
        snoozeUntilUtc,
      },
    });
    statusEl.textContent = snoozeUntilUtc ? "Loop snoozed successfully." : "Snooze cleared.";
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to snooze loop.");
  }
}

export function toggleRecurrenceSection(loopId: number | string, show: boolean): void {
  const section = document.querySelector(`[data-recurrence-section="${loopId}"]`);
  if (!(section instanceof HTMLElement)) {
    return;
  }

  const config = section.querySelector(".recurrence-config");
  if (config instanceof HTMLElement) {
    config.classList.toggle("visible", show);
  }
  section.classList.toggle("expanded", show);
}

export async function updateRecurrence(
  loopId: number | string,
  rrule: string,
  tz: string,
  enabled: boolean,
): Promise<void> {
  if (!statusEl) {
    return;
  }

  try {
    const updated = await api.updateRecurrence(loopId, rrule, tz, enabled);
    replaceLoop(updated);

    const preview = document.querySelector(`[data-recurrence-preview="${loopId}"]`);
    if (preview instanceof HTMLElement) {
      if (updated.next_due_at_utc) {
        preview.textContent = `Next: ${formatTime(updated.next_due_at_utc)}`;
        preview.style.display = "flex";
      } else if (enabled) {
        preview.textContent = "Enter a schedule to see next occurrence";
        preview.style.display = "flex";
      } else {
        preview.style.display = "none";
      }
    }

    const errorEl = document.querySelector(`[data-recurrence-error="${loopId}"]`);
    if (errorEl instanceof HTMLElement) {
      errorEl.classList.remove("visible");
    }

    statusEl.textContent = enabled ? "Recurrence enabled." : "Recurrence disabled.";
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to update recurrence.");

    const errorEl = document.querySelector(`[data-recurrence-error="${loopId}"]`);
    if (errorEl instanceof HTMLElement) {
      errorEl.textContent = messageFromError(error, "Failed to update recurrence.");
      errorEl.classList.add("visible");
    }
  }
}

export function getTagsFromCard(card: HTMLElement): string[] {
  return Array.from(card.querySelectorAll<HTMLElement>(".tag-chip"))
    .map((chip) => chip.dataset["tag"] || "")
    .filter(Boolean);
}

export async function appendTagsFromInput(input: HTMLInputElement): Promise<void> {
  if (!statusEl) {
    return;
  }

  const card = input.closest(".loop-card");
  const tagsWrap = input.closest(".tags-edit");
  if (!(card instanceof HTMLElement) || !(tagsWrap instanceof HTMLElement)) {
    return;
  }

  const newTags = normalizeTags(input.value);
  input.value = "";
  tagsWrap.classList.remove("editing");
  if (newTags.length === 0) {
    return;
  }

  const existing = getTagsFromCard(card);
  const combined = [...existing];
  newTags.forEach((tag) => {
    if (!combined.includes(tag)) {
      combined.push(tag);
    }
  });

  if (combined.length === existing.length && combined.every((tag, index) => tag === existing[index])) {
    return;
  }

  try {
    const updated = await api.updateLoop(card.dataset["loopId"] || "", { tags: combined });
    if (updated) {
      replaceLoop(updated);
    }
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to update tags.");
  }
}

export async function removeTag(loopId: number | string, tag: string, card: HTMLElement): Promise<void> {
  if (!statusEl) {
    return;
  }

  const existing = getTagsFromCard(card);
  const updatedTags = existing.filter((value) => value !== tag);
  if (updatedTags.length === existing.length) {
    return;
  }

  try {
    const updated = await api.updateLoop(loopId, { tags: updatedTags });
    if (updated) {
      replaceLoop(updated);
    }
  } catch (error: unknown) {
    statusEl.textContent = messageFromError(error, "Failed to remove tag.");
  }
}

export function handleLoopClosed(loopId: number, payload: Record<string, unknown> | null | undefined): void {
  const nextStatus = payload?.["to"];
  if (usesServerDrivenInboxResults()) {
    queueInboxReload();
  } else if ((activeTagFilter() || "") !== "" && activeTagFilter() !== "all") {
    void refreshLoop(loopId);
  } else if (isLoopStatus(nextStatus) && !loopMatchesInboxFilters({ status: nextStatus, tags: [] })) {
    removeLoopFromInbox(loopId);
  } else {
    void refreshLoop(loopId);
  }
  queueNextRefresh();
}
