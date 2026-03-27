/**
 * command-palette.test.ts - Notification command regression tests.
 * Purpose: verify durable continuity notification commands in the palette.
 * Responsibilities: cover render, open, acknowledge, and suppress behavior.
 * Scope: command-palette notification commands only.
 * Usage: run with `pnpm --dir frontend test`.
 * Invariants/Assumptions: commands read shared local continuity cache and local state updates land before background sync.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { bootstrapCommandPalette } from "./command-palette";
import type { ContinuityNotificationRecord, ResumeAnchorState, ShellLocationContract } from "./contracts-ui";

const NOTIFICATION_RECORDS_CACHE_KEY = "cloop.continuity.notification-records.cache.v1";
const RESUME_ANCHORS_CACHE_KEY = "cloop.continuity.resume-anchors.cache.v3";

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

function seedAnchors(anchors: ResumeAnchorState): void {
  window.localStorage.setItem(RESUME_ANCHORS_CACHE_KEY, JSON.stringify(anchors));
}

function readNotifications(): ContinuityNotificationRecord[] {
  return JSON.parse(window.localStorage.getItem(NOTIFICATION_RECORDS_CACHE_KEY) ?? "[]") as ContinuityNotificationRecord[];
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

  it("opens saved review queues through the durable anchor target instead of the active working-set guess", async () => {
    buildPaletteDom();
    seedAnchors({
      planning: null,
      review: {
        kind: "review",
        reviewFocus: "relationship",
        sessionId: 91,
        visitedAtUtc: "2026-03-27T12:00:00Z",
        launchLocation: null,
        resumeLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 91, workingSetId: 7 }),
        resolvedResume: {
          requestedLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 91, workingSetId: 7 }),
          resolvedLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 91 }),
          status: "working_set_scope_removed",
          message: "The original working-set scope is gone, so the queue reopens unscoped.",
          successor: null,
        },
        outcomeTitle: "Resume relationship queue · Launch duplicates",
        outcomeSummary: "Return to the saved relationship queue.",
        workingSetId: 7,
        workflowThreadId: "review:relationship:91",
        degraded: true,
        degradedLabel: "The original working-set scope is gone, so the queue reopens unscoped.",
      },
    });
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const controller = createController({
      openLocation,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [],
        workingSetContext: {
          active_working_set_id: 3,
          focus_mode_enabled: false,
          active_working_set: {
            id: 3,
            name: "Today",
            description: null,
            item_count: 0,
            missing_item_count: 0,
            created_at_utc: "2026-03-27T10:00:00Z",
            updated_at_utc: "2026-03-27T10:00:00Z",
            items: [],
            launch: location({ state: "working_set", workingSetId: 3 }),
          } as never,
        } as never,
        planningSessions: [],
        relationshipSessions: [{
          id: 91,
          name: "Launch duplicates",
          query: "project:launch status:open",
          relationship_kind: "all",
          review_kind: "relationship",
          candidate_limit: 25,
          item_limit: 100,
          created_at_utc: "2026-03-27T10:00:00Z",
          updated_at_utc: "2026-03-27T11:00:00Z",
        }],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();

    const input = document.getElementById("command-palette-input") as HTMLInputElement;
    input.value = "Launch duplicates";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();

    findCommandButton("Open relationship queue · Launch duplicates").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(location({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 91,
    }));
  });
});
