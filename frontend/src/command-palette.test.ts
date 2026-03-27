/**
 * command-palette.test.ts - Command-palette continuity regression tests.
 * Purpose: verify palette notification controls and low-signal navigation behavior stay stable.
 * Responsibilities: cover notification state writes, durable reopen commands, and navigation commands that should not emit continuity receipts.
 * Scope: command-palette continuity behavior only.
 * Usage: run with `pnpm --dir frontend test`.
 * Invariants/Assumptions: commands read shared local continuity cache and local state updates land before background sync.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { bootstrapCommandPalette } from "./command-palette";
import {
  recordRecentShellAction,
} from "./continuity-intelligence";
import type { ContinuityNotificationRecord, ShellLocationContract } from "./contracts-ui";

const NOTIFICATION_RECORDS_CACHE_KEY = "cloop.continuity.notification-records.cache.v1";
const RECENT_ACTIONS_CACHE_KEY = "cloop.continuity.recent-actions.cache.v4";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length(): number { return values.size; },
    clear(): void { values.clear(); },
    getItem(key: string): string | null { return values.get(key) ?? null; },
    key(index: number): string | null { return Array.from(values.keys())[index] ?? null; },
    removeItem(key: string): void { values.delete(key); },
    setItem(key: string, value: string): void { values.set(key, value); },
  } as Storage;
}

function location(input: Partial<ShellLocationContract> & Pick<ShellLocationContract, "state">): ShellLocationContract {
  return {
    state: input.state,
    recallTool: input.recallTool ?? "chat",
    reviewFocus: input.reviewFocus ?? null,
    sessionId: input.sessionId ?? null,
    loopId: input.loopId ?? null,
    viewId: input.viewId ?? null,
    memoryId: input.memoryId ?? null,
    workingSetId: input.workingSetId ?? null,
    query: input.query ?? null,
  };
}

function notificationRecord(id: string, title: string): ContinuityNotificationRecord {
  return {
    id,
    title,
    body: "This workflow has fresh unseen movement.",
    severity: "warning",
    workflowThread: {
      id: `thread-${id}`,
      kind: "planning_checkpoint",
      title: "Launch review",
      summary: "Review the launch handoff.",
      parentOutcomeId: null,
    },
    resolvedLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 41, workingSetId: 7 }),
    state: { inboxedAtUtc: null, seenAtUtc: null, acknowledgedAtUtc: null, suppressedUntilUtc: null },
  };
}

function seedNotifications(records: ContinuityNotificationRecord[]): void {
  window.localStorage.setItem(NOTIFICATION_RECORDS_CACHE_KEY, JSON.stringify(records));
}

function readNotifications(): ContinuityNotificationRecord[] {
  return JSON.parse(window.localStorage.getItem(NOTIFICATION_RECORDS_CACHE_KEY) ?? "[]") as ContinuityNotificationRecord[];
}

function readRecentActions(): unknown[] {
  return JSON.parse(window.localStorage.getItem(RECENT_ACTIONS_CACHE_KEY) ?? "[]") as unknown[];
}

function buildPaletteDom(): void {
  document.body.innerHTML = `
    <div id="command-palette" hidden>
      <button type="button" data-command-palette-close>Close</button>
      <div id="command-palette-overlay"></div>
      <div id="command-palette-panel">
        <input id="command-palette-input" />
        <div id="command-palette-results"></div>
        <div id="command-palette-detail"></div>
        <div id="command-palette-status"></div>
      </div>
    </div>
  `;
}

function findCommandButton(label: string): HTMLButtonElement {
  const match = Array.from(document.querySelectorAll<HTMLButtonElement>("button[data-command-id]"))
    .find((button) => button.textContent?.includes(label));
  if (!match) {
    throw new Error(`Missing command button containing: ${label}`);
  }
  return match;
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await vi.runAllTimersAsync();
  await Promise.resolve();
}

function createController(overrides: {
  openLocation?: (location: ShellLocationContract) => Promise<void>;
  refreshWorkspace?: () => Promise<void>;
  getContext?: () => Parameters<typeof bootstrapCommandPalette>[0]["getContext"] extends () => infer T ? T : never;
} = {}) {
  return bootstrapCommandPalette({
    getContext: overrides.getContext ?? (() => ({
      currentLocation: location({ state: "operator" }),
      loops: [],
      workingSets: [],
      workingSetContext: null,
      planningSessions: [],
      relationshipSessions: [],
      enrichmentSessions: [],
    })),
    openLocation: overrides.openLocation ?? vi.fn(async () => undefined),
    refreshWorkspace: overrides.refreshWorkspace ?? vi.fn(async () => undefined),
    createWorkingSet: vi.fn(async () => null),
    setWorkingSetContext: vi.fn(async () => undefined),
    pinLocation: vi.fn(async () => undefined),
    addLoopIdsToActiveWorkingSet: vi.fn(async () => undefined),
    askGroundedChat: vi.fn(async () => undefined),
    runMemorySearch: vi.fn(async () => undefined),
    runDocumentAsk: vi.fn(async () => undefined),
  });
}

let originalFetch: typeof fetch | undefined;
let originalLocalStorage: Storage;

describe("command-palette notification commands", () => {
  beforeEach(() => {
    originalLocalStorage = window.localStorage as Storage;
    Object.defineProperty(window, "localStorage", {
      value: memoryStorage(),
      configurable: true,
      writable: true,
    });
    originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-21T12:00:00Z"));
  });

  afterEach(() => {
    globalThis.fetch = originalFetch as typeof fetch;
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    document.body.innerHTML = "";
    vi.useRealTimers();
  });

  it("renders notification commands and opens the exact durable target", async () => {
    buildPaletteDom();
    seedNotifications([notificationRecord("planning:41", "Launch review is ready")]);
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const controller = createController({ openLocation });

    controller.open();
    await settle();

    expect(document.getElementById("command-palette-results")?.textContent).toContain("Notifications");
    findCommandButton("Open notification · Launch review is ready").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(location({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 41,
      workingSetId: 7,
    }));
  });

  it("does not create continuity receipts for pure navigation commands", async () => {
    buildPaletteDom();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const controller = createController({ openLocation });

    controller.open();
    await settle();
    findCommandButton("Open home workspace").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(location({ state: "operator" }));
    expect(readRecentActions()).toEqual([]);
  });

  it("surfaces fresh local receipts in recent commands before durable sync", async () => {
    buildPaletteDom();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    recordRecentShellAction({
      kind: "recall",
      label: "Indexed launch notes",
      description: "Indexed 3 files into 18 chunks.",
      location: location({ state: "recall", recallTool: "rag", query: "launch notes", workingSetId: 7 }),
      outcome: {
        card: {
          id: "receipt-rag-local",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Recall receipt",
          title: "Indexed launch notes",
          summary: "Indexed 3 files into 18 chunks.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Recall surface contract"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Reindex with a corrected path if needed.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "recall", recallTool: "rag", query: "launch notes", workingSetId: 7 }),
        rollbackLabel: "Reindex with a corrected path if needed.",
        undoAction: null,
        workflowThread: {
          id: "recall:rag:launch-notes",
          kind: "recall",
          title: "Indexed launch notes",
          summary: "Indexed 3 files into 18 chunks.",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: location({ state: "recall", recallTool: "rag", query: "launch notes", workingSetId: 7 }),
          resolvedLocation: location({ state: "recall", recallTool: "rag", query: "launch notes", workingSetId: 7 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
    });
    const controller = createController({ openLocation });

    controller.open();
    await settle();
    findCommandButton("Indexed launch notes").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(location({ state: "recall", recallTool: "rag", query: "launch notes", workingSetId: 7 }));
  });

  it("persists acknowledge and suppress notification controls through shared state writes", async () => {
    const refreshWorkspace = vi.fn(async () => undefined);

    buildPaletteDom();
    seedNotifications([notificationRecord("planning:41", "Launch review is ready")]);
    let controller = createController({ refreshWorkspace });
    controller.open();
    await settle();
    findCommandButton("Acknowledge notification · Launch review is ready").click();
    await settle();

    let stored = readNotifications()[0]?.state;
    expect(stored?.inboxedAtUtc).not.toBeNull();
    expect(stored?.seenAtUtc).toBe(stored?.inboxedAtUtc ?? null);
    expect(stored?.acknowledgedAtUtc).toBe(stored?.inboxedAtUtc ?? null);

    buildPaletteDom();
    seedNotifications([notificationRecord("planning:42", "Launch recovery is ready")]);
    controller = createController({ refreshWorkspace });
    controller.open();
    await settle();
    findCommandButton("Hide notification for 1 day · Launch recovery is ready").click();
    await settle();

    stored = readNotifications()[0]?.state;
    expect(stored?.inboxedAtUtc).not.toBeNull();
    expect(stored?.seenAtUtc).toBe(stored?.inboxedAtUtc ?? null);
    expect(stored?.acknowledgedAtUtc).toBeNull();
    expect(stored?.suppressedUntilUtc).not.toBeNull();
    expect(Date.parse(stored?.suppressedUntilUtc ?? "") - Date.parse(stored?.inboxedAtUtc ?? "")).toBe(24 * 60 * 60 * 1000);
    expect(refreshWorkspace).toHaveBeenCalledTimes(2);
  });

});
