/**
 * command-palette.test.ts - Command-palette continuity regression tests.
 * Purpose: verify palette continuity controls, stale recent-action visibility, and low-signal navigation behavior stay stable.
 * Responsibilities: cover notification state writes, durable reopen commands, disabled recent follow-through commands, and navigation commands that should not emit continuity receipts.
 * Scope: command-palette continuity behavior only.
 * Usage: run with `pnpm --dir frontend test`.
 * Invariants/Assumptions: commands read shared local continuity cache and local state updates land before background sync.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { bootstrapCommandPalette } from "./command-palette";
import {
  recordRecentShellAction,
} from "./continuity-intelligence";
import * as executableUndo from "./executable-undo";
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

function activeCommandButton(): HTMLButtonElement {
  const match = document.querySelector<HTMLButtonElement>('button[data-command-id].is-active');
  if (!match) {
    throw new Error("Missing active command button");
  }
  return match;
}

function activeCommandGroup(): string {
  const group = activeCommandButton().closest<HTMLElement>(".command-palette-group");
  const label = group?.getAttribute("aria-label")?.trim();
  if (!label) {
    throw new Error("Missing active command group");
  }
  return label;
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
      nowFeed: [],
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
    vi.restoreAllMocks();
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

  it("reuses the backend-ranked now feed for the recommended next move", async () => {
    buildPaletteDom();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const controller = createController({
      openLocation,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [],
        workingSetContext: null,
        nowFeed: [
          {
            id: "planning:41",
            rank: 5400,
            source: "planning_session",
            display_kind: "handoff",
            display_tone: "attention",
            eyebrow: "Plan in motion",
            title: "Launch review queue is ready",
            summary: "Open the prepared queue.",
            rationale: "Backend-ranked rationale.",
            reason_labels: ["Queue is prepared", "Resume from the saved session"],
            freshness_at_utc: "2026-03-20T12:00:00Z",
            freshness_prefix: "Updated",
            action_label: "Open decision queue",
            launch_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "enrichment",
              session_id: 52,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: null,
              query: null,
            },
            working_set_id: null,
          },
        ],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Next move · Launch review queue is ready").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(location({
      state: "decide",
      reviewFocus: "enrichment",
      sessionId: 52,
    }));
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

  it("keeps recent undo commands available after transient failures", async () => {
    buildPaletteDom();
    vi.spyOn(executableUndo, "executeUndoAction").mockRejectedValueOnce(new Error("Network down"));

    recordRecentShellAction({
      kind: "planning",
      label: "Undid launch checkpoint",
      description: "Undo the launch checkpoint.",
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
      outcome: {
        card: {
          id: "receipt-planning-undo",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Launch checkpoint updated",
          summary: "The launch checkpoint can still be undone.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Undo remains available.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
        rollbackLabel: "Undo remains available.",
        undoAction: {
          type: "undo",
          label: "Undo checkpoint",
          variant: "secondary",
          description: "Undo the launch checkpoint.",
          undo: {
            kind: "planning_run",
            sessionId: 12,
            runId: 44,
            checkpointIndex: 0,
            checkpointTitle: "Launch prep",
            actionCount: 1,
            bestEffort: false,
          },
          requiresConfirmation: false,
          confirmTitle: null,
          confirmDescription: null,
          successLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
        },
        workflowThread: {
          id: "planning:12",
          kind: "planning_checkpoint",
          title: "Launch prep",
          summary: "Checkpoint updated",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
          resolvedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
    });

    const controller = createController();
    controller.open();
    await settle();

    findCommandButton("Undo checkpoint: Launch prep").click();
    await settle();

    expect(document.getElementById("command-palette-status")?.textContent).toBe("Network down");
    const stored = readRecentActions()[0] as {
      outcome?: { undoAction?: { disabledReason?: string | null } | null } | null;
    };
    expect(stored.outcome?.undoAction?.disabledReason ?? null).toBeNull();
    expect(findCommandButton("Undo checkpoint: Launch prep")).toBeTruthy();
  });

  it("keeps stale recent undo and rerun commands visible but disabled", async () => {
    buildPaletteDom();

    recordRecentShellAction({
      kind: "planning",
      label: "Launch checkpoint updated",
      description: "Undo the launch checkpoint.",
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
      outcome: {
        card: {
          id: "receipt-planning-undo-disabled",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Launch checkpoint updated",
          summary: "Undo is no longer safe.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Resume the planning session instead.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
        rollbackLabel: "Resume the planning session instead.",
        undoAction: {
          type: "undo",
          label: "Undo checkpoint",
          variant: "secondary",
          description: "Undo the launch checkpoint.",
          disabledReason: "This checkpoint can no longer be undone.",
          undo: {
            kind: "planning_run",
            sessionId: 12,
            runId: 45,
            checkpointIndex: 0,
            checkpointTitle: "Launch prep",
            actionCount: 1,
            bestEffort: false,
          },
          requiresConfirmation: false,
          confirmTitle: null,
          confirmDescription: null,
          successLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
        },
        workflowThread: {
          id: "planning:12:disabled",
          kind: "planning_checkpoint",
          title: "Launch prep",
          summary: "Checkpoint updated",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
          resolvedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
    });
    recordRecentShellAction({
      kind: "review",
      label: "Duplicate queue refreshed",
      description: "Refresh the duplicate review queue.",
      location: location({ state: "decide", reviewFocus: "relationship", sessionId: 18 }),
      outcome: {
        card: {
          id: "receipt-review-rerun-disabled",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Review receipt",
          title: "Duplicate queue refreshed",
          summary: "Refresh is no longer safe.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Saved review session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Resume the review queue instead.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 18 }),
        rollbackLabel: "Resume the review queue instead.",
        undoAction: null,
        rerunAction: {
          type: "rerun",
          label: "Refresh duplicate review",
          variant: "secondary",
          description: "Refresh the duplicate review queue against current loop state.",
          disabledReason: "This saved review session moved.",
          rerun: {
            kind: "review_session",
            reviewFocus: "relationship",
            sessionId: 18,
            sessionName: "Duplicate queue",
          },
          contract: {
            mode: "refresh",
            provenanceLabel: "Saved review session: Duplicate queue",
            freshnessLabel: "Queue moved",
            strategySummary: "Reuse the saved review session and refresh it against current loop state.",
            strictInvariants: ["Same saved review session identity"],
            mayVary: ["Queue contents"],
            postRun: {
              summary: "Land back in the saved review session.",
              location: location({ state: "decide", reviewFocus: "relationship", sessionId: 18 }),
            },
          },
        },
        workflowThread: {
          id: "review:18:disabled",
          kind: "review_session",
          title: "Duplicate queue",
          summary: "Review the current relationship candidates.",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 18 }),
          resolvedLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 18 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
    });

    const controller = createController();
    controller.open();
    await settle();

    const disabledUndo = findCommandButton("Undo checkpoint: Launch prep");
    expect(disabledUndo.getAttribute("aria-disabled")).toBe("true");
    expect(disabledUndo.textContent).toContain("Unavailable");

    const disabledRerun = findCommandButton("Refresh duplicate review: Duplicate queue");
    expect(disabledRerun.getAttribute("aria-disabled")).toBe("true");
    expect(disabledRerun.textContent).toContain("Unavailable");
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

describe("command-palette keyboard navigation", () => {
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
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = originalFetch as typeof fetch;
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    document.body.innerHTML = "";
    vi.useRealTimers();
  });

  it("cycles results with Tab and Shift+Tab without leaving the search field", async () => {
    buildPaletteDom();
    const controller = createController();

    controller.open();
    await settle();

    const input = document.getElementById("command-palette-input") as HTMLInputElement;
    const initial = activeCommandButton().dataset["commandId"];

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(input);
    expect(activeCommandButton().dataset["commandId"]).not.toBe(initial);

    const afterForward = activeCommandButton().dataset["commandId"];
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(input);
    expect(activeCommandButton().dataset["commandId"]).toBe(initial);
    expect(activeCommandButton().dataset["commandId"]).not.toBe(afterForward);
  });

  it("supports Ctrl+N and Ctrl+P result movement for keyboard-only workflows", async () => {
    buildPaletteDom();
    const controller = createController();

    controller.open();
    await settle();

    const input = document.getElementById("command-palette-input") as HTMLInputElement;
    const initial = activeCommandButton().dataset["commandId"];

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "n", ctrlKey: true, bubbles: true, cancelable: true }));
    const afterForward = activeCommandButton().dataset["commandId"];
    expect(afterForward).not.toBe(initial);

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "p", ctrlKey: true, bubbles: true, cancelable: true }));
    expect(activeCommandButton().dataset["commandId"]).toBe(initial);
  });

  it("jumps between result groups with PageDown and PageUp while keeping focus in the search field", async () => {
    buildPaletteDom();
    const controller = createController();

    controller.open();
    await settle();

    const input = document.getElementById("command-palette-input") as HTMLInputElement;
    const initialGroup = activeCommandGroup();

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "PageDown", bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(input);
    const nextGroup = activeCommandGroup();
    expect(nextGroup).not.toBe(initialGroup);

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "PageUp", bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(input);
    expect(activeCommandGroup()).toBe(initialGroup);
  });
});
