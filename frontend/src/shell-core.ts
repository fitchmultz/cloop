/**
 * shell-core.ts - Shared shell constants, DOM lookup, and display helpers.
 *
 * Purpose:
 *   Provide the extracted operator-shell modules with one shared set of
 *   constants, formatting helpers, and DOM element builders.
 *
 * Responsibilities:
 *   - Define storage/event constants shared across shell modules.
 *   - Build and validate required shell DOM elements.
 *   - Expose shared escaping, formatting, and display helpers.
 *
 * Scope:
 *   - Browser-only shell helper utilities.
 *
 * Usage:
 *   - Import from shell routing, working-set, workspace, event, and
 *     coordinator modules.
 *
 * Invariants/Assumptions:
 *   - frontend/index.html preserves the required shell element ids.
 *   - These helpers remain behavior-preserving utilities, not business logic.
 */

import type { ShellElements } from "./shell-types";

export const SHELL_LOCATION_STORAGE_KEY = "cloop.shell.location.v1";
export const LAST_VISIT_STORAGE_KEY = "cloop.shell.lastVisitAt.v1";
export const HIGHLIGHT_CLASS = "operator-highlight";
export const REVIEW_FOCUS_EVENT = "cloop:review-focus";
export const WORKSPACE_REFRESH_EVENT = "cloop:workspace-refresh-requested";

export function requireElement<T extends HTMLElement>(id: string, ctor: { new (): T }): T {
  const element = document.getElementById(id);
  if (!(element instanceof ctor)) {
    throw new Error(`Missing required shell element: ${id}`);
  }
  return element;
}

export function buildShellElements(): ShellElements {
  return {
    operatorMain: requireElement("operator-main", HTMLElement),
    inboxMain: requireElement("inbox-main", HTMLElement),
    nextMain: requireElement("next-main", HTMLElement),
    reviewMain: requireElement("review-main", HTMLElement),
    chatMain: requireElement("chat-main", HTMLElement),
    memoryMain: requireElement("memory-main", HTMLElement),
    ragMain: requireElement("rag-main", HTMLElement),
    workingSetMain: requireElement("working-set-main", HTMLElement),
    shellTitle: requireElement("shell-title", HTMLElement),
    shellDescription: requireElement("shell-description", HTMLElement),
    shellContext: requireElement("shell-context", HTMLElement),
    shellRoutePill: requireElement("shell-route-pill", HTMLElement),
    shellLastVisit: requireElement("shell-last-visit", HTMLElement),
    shellReceiptRail: requireElement("shell-receipts", HTMLElement),
    shellPrimaryAction: requireElement("shell-primary-action", HTMLButtonElement),
    refreshWorkspaceButton: requireElement("shell-refresh-workspace-btn", HTMLButtonElement),
    commandPaletteButton: requireElement("shell-command-palette-btn", HTMLButtonElement),
    createWorkingSetButton: requireElement("operator-create-working-set-btn", HTMLButtonElement),
    stateButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("[data-shell-state]")),
    recallSubnav: requireElement("recall-subnav", HTMLElement),
    recallButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("[data-recall-tool]")),
    operatorNow: requireElement("operator-now", HTMLElement),
    operatorDecisions: requireElement("operator-decisions", HTMLElement),
    operatorPlan: requireElement("operator-plan", HTMLElement),
    operatorRecall: requireElement("operator-recall", HTMLElement),
    operatorSinceLast: requireElement("operator-since-last", HTMLElement),
    operatorWorkingSet: requireElement("operator-working-set", HTMLElement),
    workingSetFocusBanner: requireElement("working-set-focus-banner", HTMLElement),
    workingSetFocusSummary: requireElement("working-set-focus-summary", HTMLElement),
    workingSetFocusItems: requireElement("working-set-focus-items", HTMLElement),
    workingSetFocusToggleButton: requireElement("working-set-focus-toggle-btn", HTMLButtonElement),
    workingSetExitFocusButton: requireElement("working-set-exit-focus-btn", HTMLButtonElement),
  };
}

export function safeJsonParse<T>(raw: string | null, fallback: T): T {
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatRelativeTime(value: string | Date | null | undefined): string {
  const date = value instanceof Date ? value : value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return "unknown time";
  }

  const diffMs = Date.now() - date.getTime();
  const absMs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  let amount: number;
  let unit: string;
  if (absMs < hour) {
    amount = Math.max(1, Math.round(absMs / minute));
    unit = amount === 1 ? "minute" : "minutes";
  } else if (absMs < day) {
    amount = Math.max(1, Math.round(absMs / hour));
    unit = amount === 1 ? "hour" : "hours";
  } else {
    amount = Math.max(1, Math.round(absMs / day));
    unit = amount === 1 ? "day" : "days";
  }

  return `${amount} ${unit} ${diffMs >= 0 ? "ago" : "from now"}`;
}

export function loopTitle(loop: { title?: string | null; raw_text: string; id: number }): string {
  return loop.title?.trim() || loop.raw_text.trim() || `Loop #${loop.id}`;
}

export function loopPreview(loop: { summary?: string | null; next_action?: string | null; raw_text: string }): string {
  return loop.summary?.trim() || loop.next_action?.trim() || loop.raw_text.trim();
}

export function displayElement(element: HTMLElement | null, visible: boolean, display = "grid"): void {
  if (!element) {
    return;
  }
  element.style.display = visible ? display : "none";
}

export function parseOptionalInteger(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) ? parsed : null;
}
