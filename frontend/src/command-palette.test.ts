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
import * as modals from "./modals";
import type { ContinuityNotificationRecord, ShellLocationContract } from "./contracts-ui";
import type { WorkingSetResponse } from "./domain";

const NOTIFICATION_RECORDS_CACHE_KEY = "cloop.continuity.notification-records.cache.v1";
const RECENT_ACTIONS_CACHE_KEY = "cloop.continuity.recent-actions.cache.v4";
const WORKFLOW_SUMMARIES_CACHE_KEY = "cloop.continuity.workflow-summaries.cache.v2";

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
    includeLoopContext: input.includeLoopContext ?? null,
    includeMemoryContext: input.includeMemoryContext ?? null,
    includeRagContext: input.includeRagContext ?? null,
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

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function workingSetFixture(id = 7, name = "Launch Prep"): WorkingSetResponse {
  return {
    id,
    name,
    description: null,
    item_count: 3,
    missing_item_count: 0,
    created_at_utc: "2026-03-21T09:00:00Z",
    updated_at_utc: "2026-03-21T09:00:00Z",
    launch: {
      state: "working_set",
      recall_tool: "chat",
      review_focus: null,
      session_id: null,
      loop_id: null,
      view_id: null,
      memory_id: null,
      working_set_id: id,
      query: null,
      include_loop_context: null,
      include_memory_context: null,
      include_rag_context: null,
    },
    items: [],
    last_activated_at_utc: null,
    latest_reversible_event_id: null,
    latest_reversible_event_type: null,
  } as WorkingSetResponse;
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

    expect(openLocation.mock.calls.at(-1)?.[0]).toEqual(expect.objectContaining({
      state: "decide",
      recallTool: "chat",
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

    expect(openLocation.mock.calls.at(-1)?.[0]).toEqual(expect.objectContaining({
      state: "decide",
      recallTool: "chat",
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

    expect(openLocation.mock.calls.at(-1)?.[0]).toEqual(expect.objectContaining({
      state: "recall",
      recallTool: "rag",
      query: "launch notes",
      workingSetId: 7,
    }));
  });

  it("prefers hydrated durable recall outcomes in Recent commands after sync", async () => {
    buildPaletteDom();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);

    recordRecentShellAction({
      kind: "recall",
      label: "Local recall receipt",
      description: "Temporary browser-local recall result.",
      location: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
      outcome: {
        card: {
          id: "receipt-recall-local",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Recall receipt",
          title: "Local recall receipt",
          summary: "Temporary browser-local recall result.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Local recall bridge"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Rerun recall to refresh this answer.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
        rollbackLabel: "Rerun recall to refresh this answer.",
        undoAction: null,
        workflowThread: {
          id: "local:recall:launch-checklist",
          kind: "recall",
          title: "Local recall receipt",
          summary: "Temporary browser-local recall result.",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
          resolvedLocation: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
    });

    window.localStorage.setItem(WORKFLOW_SUMMARIES_CACHE_KEY, JSON.stringify([
      {
        id: "recall:rag:where is the launch checklist?",
        source: "receipt",
        rank: 5330,
        rankingSignals: {
          driftSeverity: "moderate",
          driftScore: 56,
          workingSetRelevant: true,
          downstreamReady: true,
          degraded: false,
          recencyTieBreaker: 19,
        },
        workflowThread: {
          id: "recall:rag:where is the launch checklist?",
          kind: "recall",
          title: "Evidence answer · where is the launch checklist?",
          summary: "The launch checklist lives in docs/launch.md.",
          parentOutcomeId: null,
        },
        representativeOutcomeId: 31,
        latestOutcomeId: 31,
        occurredAt: "2026-03-21T09:28:00Z",
        outcomeCount: 1,
        outcomePreviewTitles: ["Evidence answer · where is the launch checklist?"],
        requestedResumeLocation: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
        resolvedResume: {
          requestedLocation: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
          resolvedLocation: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
          status: "ok",
          message: null,
          successor: null,
        },
        displayTitle: "Evidence answer · where is the launch checklist?",
        displaySummary: "The launch checklist lives in docs/launch.md.",
        displayCard: {
          kind: "receipt",
          tone: "attention",
          eyebrow: "Recall receipt",
          title: "Evidence answer · where is the launch checklist?",
          summary: "The launch checklist lives in docs/launch.md.",
          rationale: "Document answers should reopen the landed result.",
          preview: [],
          trust: {
            generationLabel: "Recall receipt",
            generationTone: "attention",
            contextSources: ["Indexed local documents", "Source: docs/launch.md"],
            assumptions: [],
            confidenceLabel: "1 retrieved source",
            confidenceTone: "attention",
            freshnessLabel: "Saved just now",
            freshnessTone: "progress",
            rollbackLabel: "Rerun the same document question to refresh this answer.",
            rollbackTone: "progress",
            impactSummary: "The launch checklist lives in docs/launch.md.",
            impactTone: "attention",
          },
          handoff: {
            changeSummary: "This keeps the landed recall result resumable from continuity, the receipt rail, and Recent commands.",
            createdResources: [],
            nextStep: "Reopen the evidence-backed answer or rerun it.",
            breadcrumbs: ["Home", "Recall", "Documents"],
            workingSet: {
              workingSetId: 7,
              workingSetName: "Launch Prep",
              itemCount: 4,
              missingItemCount: 0,
            },
          },
          actionContextLabel: "Continue from here",
          actionWarning: null,
        },
        undoAction: null,
        rerunAction: {
          type: "rerun",
          label: "Refresh evidence",
          variant: "secondary",
          description: "Land back in Recall with a fresh evidence-backed result.",
          rerun: {
            kind: "recall_query",
            recallTool: "rag",
            query: "Where is the launch checklist?",
            workingSetId: 7,
            includeLoopContext: undefined,
            includeMemoryContext: undefined,
            includeRagContext: true,
          },
          contract: {
            mode: "rerun",
            provenanceLabel: "Document-backed recall result",
            freshnessLabel: "1 retrieved source in the prior answer",
            strategySummary: "Reuse the same document question against the current indexed evidence.",
            strictInvariants: ["Same document recall surface", "Same query text"],
            mayVary: ["Retrieved source set"],
            postRun: {
              summary: "Land back in Recall with a fresh evidence-backed result.",
              location: location({ state: "recall", recallTool: "rag", query: "Where is the launch checklist?", workingSetId: 7 }),
            },
          },
        },
        workingSetId: 7,
        workingSetName: "Launch Prep",
        degraded: false,
        degradedLabel: null,
        whyNow: ["This workflow has fresh unseen movement."],
        changedSinceLastSeen: ["This workflow has never been seen from durable continuity."],
        priorState: null,
      },
    ]));

    const controller = createController({ openLocation });
    controller.open();
    await settle();

    expect(() => findCommandButton("Local recall receipt")).toThrow();
    findCommandButton("Evidence answer · where is the launch checklist?").click();
    await settle();

    expect(openLocation.mock.calls.at(-1)?.[0]).toEqual(expect.objectContaining({
      state: "recall",
      recallTool: "rag",
      query: "Where is the launch checklist?",
      workingSetId: 7,
    }));
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

  it("executes the current planning checkpoint from the palette and records the planning receipt", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/planning/sessions/12") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 12,
            name: "Launch prep",
            prompt: "Prepare launch review",
            query: null,
            loop_limit: 10,
            include_memory_context: false,
            include_rag_context: false,
            rag_k: 5,
            rag_scope: null,
            status: "active",
            checkpoint_count: 1,
            executed_checkpoint_count: 0,
            current_checkpoint_index: 0,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          plan_title: "Launch prep",
          plan_summary: "Prepare the launch review queue.",
          current_checkpoint: {
            title: "Review launch queue",
            summary: "Create the saved review queue.",
            success_criteria: "Queue created",
            operations: [{ kind: "review.session.create" }],
          },
          checkpoints: [],
          execution_history: [],
          rerun_action: {
            label: "Refresh plan",
            description: "Land back in the saved planning session with refreshed checkpoints.",
            rerun: {
              kind: "planning_session",
              session_id: 12,
              session_name: "Launch prep",
            },
            contract: {
              mode: "refresh",
              provenance_label: "Planning session: Launch prep",
              freshness_label: "Updated 2026-03-21T12:00:00Z",
              strategy_summary: "Reuse the saved planning session and refresh it against current loop state.",
              strict_invariants: ["Same planning session identity"],
              may_vary: ["Checkpoint wording and emphasis"],
              post_run: {
                summary: "Land back in the saved planning session with refreshed checkpoints.",
                location: {
                  state: "plan",
                  recall_tool: "chat",
                  review_focus: "planning",
                  session_id: 12,
                  loop_id: null,
                  view_id: null,
                  memory_id: null,
                  working_set_id: 7,
                  query: null,
                },
              },
            },
          },
        }));
      }
      if (url.endsWith("/loops/planning/sessions/12/execute") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 12,
              name: "Launch prep",
              prompt: "Prepare launch review",
              query: null,
              loop_limit: 10,
              include_memory_context: false,
              include_rag_context: false,
              rag_k: 5,
              rag_scope: null,
              status: "active",
              checkpoint_count: 1,
              executed_checkpoint_count: 1,
              current_checkpoint_index: 0,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:05:00Z",
            },
            plan_title: "Launch prep",
            plan_summary: "Prepare the launch review queue.",
            current_checkpoint: {
              title: "Review launch queue",
              summary: "Create the saved review queue.",
              success_criteria: "Queue created",
              operations: [{ kind: "review.session.create" }],
            },
            checkpoints: [],
            execution_history: [],
            rerun_action: {
              label: "Refresh plan",
              description: "Land back in the saved planning session with refreshed checkpoints.",
              rerun: {
                kind: "planning_session",
                session_id: 12,
                session_name: "Launch prep",
              },
              contract: {
                mode: "refresh",
                provenance_label: "Planning session: Launch prep",
                freshness_label: "Updated 2026-03-21T12:05:00Z",
                strategy_summary: "Reuse the saved planning session and refresh it against current loop state.",
                strict_invariants: ["Same planning session identity"],
                may_vary: ["Checkpoint wording and emphasis"],
                post_run: {
                  summary: "Land back in the saved planning session with refreshed checkpoints.",
                  location: {
                    state: "plan",
                    recall_tool: "chat",
                    review_focus: "planning",
                    session_id: 12,
                    loop_id: null,
                    view_id: null,
                    memory_id: null,
                    working_set_id: 7,
                    query: null,
                  },
                },
              },
            },
          },
          execution: {
            checkpoint_index: 0,
            checkpoint_title: "Review launch queue",
            executed_at_utc: "2026-03-21T12:05:00Z",
            operation_count: 1,
            launch_surfaces: [
              {
                label: "Open relationship queue",
                summary: "Review duplicates",
                kind: "review_session",
                web: {
                  surface: "review_session",
                  review_kind: "relationship",
                  session_id: 41,
                  working_set_id: 7,
                },
              },
            ],
            follow_up_resources: [],
            rollback_cues: [
              {
                mode: "direct_undo",
                summary: "Undo available",
                undoable_operation_count: 1,
              },
            ],
            results: [{ rollback_actions: [{ kind: "loop.undo" }] }],
            summary: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 12, workingSetId: 7 }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Execute checkpoint · Review launch queue").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "plan",
      reviewFocus: "planning",
      sessionId: 12,
      workingSetId: 7,
    }));
    expect(refreshWorkspace).toHaveBeenCalled();
    const stored = readRecentActions()[0] as { kind: string; location: { state: string; sessionId: number | null; workingSetId: number | null }; label: string };
    expect(stored.kind).toBe("planning");
    expect(stored.location).toEqual(expect.objectContaining({ state: "plan", sessionId: 12, workingSetId: 7 }));
    expect(stored.label).toContain("Executed Review launch queue");
  });

  it("executes the current relationship saved action from the palette with the current candidate", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const actionBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/relationship/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 5,
            name: "Confirm duplicate",
            action_type: "confirm",
            relationship_type: "duplicate",
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: 11,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [],
          loop_count: 1,
          current_index: 0,
          current_item: {
            loop: { id: 11, title: "Launch checklist", raw_text: "Launch checklist", status: "actionable" },
            duplicate_candidates: [
              {
                id: 21,
                title: "Launch checklist duplicate",
                raw_text: "Launch checklist duplicate",
                relationship_type: "duplicate",
                score: 0.99,
                status: "actionable",
                captured_at_utc: "2026-03-21T12:00:00Z",
                captured_tz_offset_min: 0,
                created_at_utc: "2026-03-21T12:00:00Z",
                updated_at_utc: "2026-03-21T12:00:00Z",
              },
            ],
            related_candidates: [],
            duplicate_count: 1,
            related_count: 0,
            top_score: 0.99,
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 18,
              name: "Duplicate queue",
              query: "status:actionable",
              relationship_kind: "all",
              candidate_limit: 5,
              item_limit: 5,
              current_loop_id: 11,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:02:00Z",
            },
            items: [],
            loop_count: 0,
            current_index: null,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "confirmed", relationship_type: "duplicate" },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Duplicate recorded",
              summary: "The duplicate decision was stored.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Duplicate queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Duplicate recorded",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Relationship review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "relationship",
              session_id: 18,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:18",
              kind: "review_session",
              title: "Duplicate queue",
              summary: "Review the current relationship candidates.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 18, workingSetId: 7 }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Confirm duplicate").click();
    await settle();

    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      loop_id: 11,
      candidate_loop_id: 21,
      candidate_relationship_type: "duplicate",
      action_preset_id: 5,
    }));
    const stored = readRecentActions()[0] as { kind: string; location: { sessionId: number | null; workingSetId: number | null; reviewFocus: string | null } };
    expect(stored.kind).toBe("review");
    expect(stored.location).toEqual(expect.objectContaining({ sessionId: 18, workingSetId: 7, reviewFocus: "relationship" }));
  });

  it("executes the current enrichment saved action from the palette with the top suggestion", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const actionBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/enrichment/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 9,
            name: "Apply core fields",
            action_type: "apply",
            fields: ["summary", "next_action"],
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: 14,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [],
          loop_count: 1,
          current_index: 0,
          current_item: {
            loop: { id: 14, title: "Inbox note", raw_text: "Inbox note", status: "inbox" },
            newest_pending_at: "2026-03-21T12:00:00Z",
            pending_clarification_count: 0,
            pending_clarifications: [],
            pending_suggestion_count: 1,
            pending_suggestions: [
              {
                id: 31,
                loop_id: 14,
                model: "pi",
                created_at: "2026-03-21T12:00:00Z",
                parsed: { summary: "Condense note", next_action: "Send recap", confidence: 0.9 },
                suggestion_json: "{}",
                resolution: null,
                resolved_at: null,
                resolved_fields_json: null,
                clarifications: [],
              },
            ],
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 22,
              name: "Enrichment queue",
              query: "status:inbox",
              pending_kind: "suggestions",
              suggestion_limit: 5,
              clarification_limit: 3,
              item_limit: 5,
              current_loop_id: 14,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:02:00Z",
            },
            items: [],
            loop_count: 0,
            current_index: null,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "applied", suggestion_id: 31 },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Suggestion applied",
              summary: "The enrichment suggestion was applied.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Enrichment queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Suggestion applied",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Enrichment review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "enrichment",
              session_id: 22,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:22",
              kind: "review_session",
              title: "Enrichment queue",
              summary: "Review the current enrichment suggestions.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 22, workingSetId: 7 }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Apply core fields").click();
    await settle();

    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      suggestion_id: 31,
      action_preset_id: 9,
    }));
    const stored = readRecentActions()[0] as { kind: string; location: { sessionId: number | null; workingSetId: number | null; reviewFocus: string | null } };
    expect(stored.kind).toBe("review");
    expect(stored.location).toEqual(expect.objectContaining({ sessionId: 22, workingSetId: 7, reviewFocus: "enrichment" }));
  });

  it("executes a saved planning checkpoint from operator home", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/planning/sessions/44") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 44,
            name: "Launch prep",
            prompt: "Prepare launch review",
            query: null,
            loop_limit: 10,
            include_memory_context: false,
            include_rag_context: false,
            rag_k: 5,
            rag_scope: null,
            status: "active",
            checkpoint_count: 2,
            executed_checkpoint_count: 1,
            current_checkpoint_index: 1,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          plan_title: "Launch prep",
          plan_summary: "Prepare the launch review queue.",
          current_checkpoint: {
            title: "Review launch queue",
            summary: "Create the saved review queue.",
            success_criteria: "Queue created",
            operations: [{ kind: "review.session.create" }],
          },
          checkpoints: [],
          execution_history: [],
          rerun_action: {
            label: "Refresh plan",
            description: "Land back in the saved planning session with refreshed checkpoints.",
            rerun: {
              kind: "planning_session",
              session_id: 44,
              session_name: "Launch prep",
            },
            contract: {
              mode: "refresh",
              provenance_label: "Planning session: Launch prep",
              freshness_label: "Updated 2026-03-21T12:00:00Z",
              strategy_summary: "Reuse the saved planning session and refresh it against current loop state.",
              strict_invariants: ["Same planning session identity"],
              may_vary: ["Checkpoint wording and emphasis"],
              post_run: {
                summary: "Land back in the saved planning session with refreshed checkpoints.",
                location: {
                  state: "plan",
                  recall_tool: "chat",
                  review_focus: "planning",
                  session_id: 44,
                  loop_id: null,
                  view_id: null,
                  memory_id: null,
                  working_set_id: 7,
                  query: null,
                },
              },
            },
          },
        }));
      }
      if (url.endsWith("/loops/planning/sessions/44/execute") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 44,
              name: "Launch prep",
              prompt: "Prepare launch review",
              query: null,
              loop_limit: 10,
              include_memory_context: false,
              include_rag_context: false,
              rag_k: 5,
              rag_scope: null,
              status: "active",
              checkpoint_count: 2,
              executed_checkpoint_count: 2,
              current_checkpoint_index: 1,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:05:00Z",
            },
            plan_title: "Launch prep",
            plan_summary: "Prepare the launch review queue.",
            current_checkpoint: null,
            checkpoints: [],
            execution_history: [],
            rerun_action: {
              label: "Refresh plan",
              description: "Land back in the saved planning session with refreshed checkpoints.",
              rerun: {
                kind: "planning_session",
                session_id: 44,
                session_name: "Launch prep",
              },
              contract: {
                mode: "refresh",
                provenance_label: "Planning session: Launch prep",
                freshness_label: "Updated 2026-03-21T12:05:00Z",
                strategy_summary: "Reuse the saved planning session and refresh it against current loop state.",
                strict_invariants: ["Same planning session identity"],
                may_vary: ["Checkpoint wording and emphasis"],
                post_run: {
                  summary: "Land back in the saved planning session with refreshed checkpoints.",
                  location: {
                    state: "plan",
                    recall_tool: "chat",
                    review_focus: "planning",
                    session_id: 44,
                    loop_id: null,
                    view_id: null,
                    memory_id: null,
                    working_set_id: 7,
                    query: null,
                  },
                },
              },
            },
          },
          execution: {
            checkpoint_index: 1,
            checkpoint_title: "Review launch queue",
            executed_at_utc: "2026-03-21T12:05:00Z",
            operation_count: 1,
            launch_surfaces: [],
            follow_up_resources: [],
            rollback_cues: [],
            results: [],
            summary: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [
          {
            id: 44,
            name: "Launch prep",
            prompt: "Prepare launch review",
            query: null,
            loop_limit: 10,
            include_memory_context: false,
            include_rag_context: false,
            rag_k: 5,
            rag_scope: null,
            status: "in_progress",
            checkpoint_count: 2,
            executed_checkpoint_count: 1,
            current_checkpoint_index: 1,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
        relationshipSessions: [],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Execute checkpoint · Review launch queue · Launch prep").click();
    await settle();

    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "plan",
      reviewFocus: "planning",
      sessionId: 44,
      workingSetId: 7,
    }));
    expect(refreshWorkspace).toHaveBeenCalled();
    const stored = readRecentActions()[0] as { kind: string; location: { state: string; sessionId: number | null; workingSetId: number | null } };
    expect(stored.kind).toBe("planning");
    expect(stored.location).toEqual(expect.objectContaining({ state: "plan", sessionId: 44, workingSetId: 7 }));
  });

  it("executes a saved relationship action from operator home", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const actionBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/relationship/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 5,
            name: "Confirm duplicate",
            action_type: "confirm",
            relationship_type: "duplicate",
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: 11,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [],
          loop_count: 1,
          current_index: 0,
          current_item: {
            loop: { id: 11, title: "Launch checklist", raw_text: "Launch checklist", status: "actionable" },
            duplicate_candidates: [
              {
                id: 21,
                title: "Launch checklist duplicate",
                raw_text: "Launch checklist duplicate",
                relationship_type: "duplicate",
                score: 0.99,
                status: "actionable",
                captured_at_utc: "2026-03-21T12:00:00Z",
                captured_tz_offset_min: 0,
                created_at_utc: "2026-03-21T12:00:00Z",
                updated_at_utc: "2026-03-21T12:00:00Z",
              },
            ],
            related_candidates: [],
            duplicate_count: 1,
            related_count: 0,
            top_score: 0.99,
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 18,
              name: "Duplicate queue",
              query: "status:actionable",
              relationship_kind: "all",
              candidate_limit: 5,
              item_limit: 5,
              current_loop_id: 11,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:02:00Z",
            },
            items: [],
            loop_count: 0,
            current_index: null,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "confirmed", relationship_type: "duplicate" },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Duplicate recorded",
              summary: "The duplicate decision was stored.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Duplicate queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Duplicate recorded",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Relationship review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "relationship",
              session_id: 18,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:18",
              kind: "review_session",
              title: "Duplicate queue",
              summary: "Review the current relationship candidates.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [
          {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: 11,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Confirm duplicate · Duplicate queue").click();
    await settle();

    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      loop_id: 11,
      candidate_loop_id: 21,
      candidate_relationship_type: "duplicate",
      action_preset_id: 5,
    }));
    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 18,
      workingSetId: 7,
    }));
    expect(refreshWorkspace).toHaveBeenCalled();
  });

  it("executes a saved enrichment action from operator home", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const actionBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/enrichment/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 9,
            name: "Apply core fields",
            action_type: "apply",
            fields: ["summary", "next_action"],
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: 14,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [],
          loop_count: 1,
          current_index: 0,
          current_item: {
            loop: { id: 14, title: "Inbox note", raw_text: "Inbox note", status: "inbox" },
            newest_pending_at: "2026-03-21T12:00:00Z",
            pending_clarification_count: 0,
            pending_clarifications: [],
            pending_suggestion_count: 1,
            pending_suggestions: [
              {
                id: 31,
                loop_id: 14,
                model: "pi",
                created_at: "2026-03-21T12:00:00Z",
                parsed: { summary: "Condense note", next_action: "Send recap", confidence: 0.9 },
                suggestion_json: "{}",
                resolution: null,
                resolved_at: null,
                resolved_fields_json: null,
                clarifications: [],
              },
            ],
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 22,
              name: "Enrichment queue",
              query: "status:inbox",
              pending_kind: "suggestions",
              suggestion_limit: 5,
              clarification_limit: 3,
              item_limit: 5,
              current_loop_id: 14,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:02:00Z",
            },
            items: [],
            loop_count: 0,
            current_index: null,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "applied", suggestion_id: 31 },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Suggestion applied",
              summary: "The enrichment suggestion was applied.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Enrichment queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Suggestion applied",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Enrichment review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "enrichment",
              session_id: 22,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:22",
              kind: "review_session",
              title: "Enrichment queue",
              summary: "Review the current enrichment suggestions.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [
          {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: 14,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Apply core fields · Enrichment queue").click();
    await settle();

    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      suggestion_id: 31,
      action_preset_id: 9,
    }));
    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "enrichment",
      sessionId: 22,
      workingSetId: 7,
    }));
    expect(refreshWorkspace).toHaveBeenCalled();
  });

  it("prompts for the exact saved relationship target from operator home", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const promptSpy = vi.spyOn(modals, "chooseOptionDialog").mockResolvedValue("12:22:duplicate");
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const actionBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/relationship/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 5,
            name: "Confirm duplicate",
            action_type: "confirm",
            relationship_type: "duplicate",
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: 11,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [
            {
              loop: { id: 11, title: "Launch checklist", raw_text: "Launch checklist", status: "actionable" },
              duplicate_candidates: [
                {
                  id: 21,
                  title: "Launch checklist duplicate",
                  raw_text: "Launch checklist duplicate",
                  relationship_type: "duplicate",
                  score: 0.99,
                  status: "actionable",
                  captured_at_utc: "2026-03-21T12:00:00Z",
                  captured_tz_offset_min: 0,
                  created_at_utc: "2026-03-21T12:00:00Z",
                  updated_at_utc: "2026-03-21T12:00:00Z",
                },
              ],
              related_candidates: [],
              duplicate_count: 1,
              related_count: 0,
              top_score: 0.99,
            },
            {
              loop: { id: 12, title: "QA checklist", raw_text: "QA checklist", status: "actionable" },
              duplicate_candidates: [
                {
                  id: 22,
                  title: "QA checklist duplicate",
                  raw_text: "QA checklist duplicate",
                  relationship_type: "duplicate",
                  score: 0.97,
                  status: "actionable",
                  captured_at_utc: "2026-03-21T12:00:00Z",
                  captured_tz_offset_min: 0,
                  created_at_utc: "2026-03-21T12:00:00Z",
                  updated_at_utc: "2026-03-21T12:00:00Z",
                },
              ],
              related_candidates: [],
              duplicate_count: 1,
              related_count: 0,
              top_score: 0.97,
            },
          ],
          loop_count: 2,
          current_index: 0,
          current_item: {
            loop: { id: 11, title: "Launch checklist", raw_text: "Launch checklist", status: "actionable" },
            duplicate_candidates: [
              {
                id: 21,
                title: "Launch checklist duplicate",
                raw_text: "Launch checklist duplicate",
                relationship_type: "duplicate",
                score: 0.99,
                status: "actionable",
                captured_at_utc: "2026-03-21T12:00:00Z",
                captured_tz_offset_min: 0,
                created_at_utc: "2026-03-21T12:00:00Z",
                updated_at_utc: "2026-03-21T12:00:00Z",
              },
            ],
            related_candidates: [],
            duplicate_count: 1,
            related_count: 0,
            top_score: 0.99,
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 18,
              name: "Duplicate queue",
              query: "status:actionable",
              relationship_kind: "all",
              candidate_limit: 5,
              item_limit: 5,
              current_loop_id: 12,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:02:00Z",
            },
            items: [],
            loop_count: 1,
            current_index: 0,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "confirmed", relationship_type: "duplicate" },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Duplicate recorded",
              summary: "The duplicate decision was stored.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Duplicate queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Duplicate recorded",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Relationship review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "relationship",
              session_id: 18,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:18",
              kind: "review_session",
              title: "Duplicate queue",
              summary: "Review the current relationship candidates.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [
          {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: 11,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Confirm duplicate · Duplicate queue").click();
    await settle();

    expect(promptSpy).toHaveBeenCalled();
    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      loop_id: 12,
      candidate_loop_id: 22,
      candidate_relationship_type: "duplicate",
      action_preset_id: 5,
    }));
    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 18,
      workingSetId: 7,
    }));
    expect(refreshWorkspace).toHaveBeenCalled();
  });

  it("prompts for the exact saved enrichment target from operator home", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const promptSpy = vi.spyOn(modals, "chooseOptionDialog").mockResolvedValue("32");
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const actionBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/enrichment/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 9,
            name: "Apply core fields",
            action_type: "apply",
            fields: ["summary", "next_action"],
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: 14,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [
            {
              loop: { id: 14, title: "Inbox note", raw_text: "Inbox note", status: "inbox" },
              newest_pending_at: "2026-03-21T12:00:00Z",
              pending_clarification_count: 0,
              pending_clarifications: [],
              pending_suggestion_count: 1,
              pending_suggestions: [
                {
                  id: 31,
                  loop_id: 14,
                  model: "pi",
                  created_at: "2026-03-21T12:00:00Z",
                  parsed: { summary: "Condense note", next_action: "Send recap", confidence: 0.9 },
                  suggestion_json: "{}",
                  resolution: null,
                  resolved_at: null,
                  resolved_fields_json: null,
                  clarifications: [],
                },
              ],
            },
            {
              loop: { id: 15, title: "Retro notes", raw_text: "Retro notes", status: "inbox" },
              newest_pending_at: "2026-03-21T12:00:00Z",
              pending_clarification_count: 0,
              pending_clarifications: [],
              pending_suggestion_count: 1,
              pending_suggestions: [
                {
                  id: 32,
                  loop_id: 15,
                  model: "pi",
                  created_at: "2026-03-21T12:00:00Z",
                  parsed: { summary: "Summarize retro", next_action: "Share action items", confidence: 0.85 },
                  suggestion_json: "{}",
                  resolution: null,
                  resolved_at: null,
                  resolved_fields_json: null,
                  clarifications: [],
                },
              ],
            },
          ],
          loop_count: 2,
          current_index: 0,
          current_item: {
            loop: { id: 14, title: "Inbox note", raw_text: "Inbox note", status: "inbox" },
            newest_pending_at: "2026-03-21T12:00:00Z",
            pending_clarification_count: 0,
            pending_clarifications: [],
            pending_suggestion_count: 1,
            pending_suggestions: [
              {
                id: 31,
                loop_id: 14,
                model: "pi",
                created_at: "2026-03-21T12:00:00Z",
                parsed: { summary: "Condense note", next_action: "Send recap", confidence: 0.9 },
                suggestion_json: "{}",
                resolution: null,
                resolved_at: null,
                resolved_fields_json: null,
                clarifications: [],
              },
            ],
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 22,
              name: "Enrichment queue",
              query: "status:inbox",
              pending_kind: "suggestions",
              suggestion_limit: 5,
              clarification_limit: 3,
              item_limit: 5,
              current_loop_id: 15,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:02:00Z",
            },
            items: [],
            loop_count: 1,
            current_index: 0,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "applied", suggestion_id: 32 },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Suggestion applied",
              summary: "The enrichment suggestion was applied.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Enrichment queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Suggestion applied",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Enrichment review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "enrichment",
              session_id: 22,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:22",
              kind: "review_session",
              title: "Enrichment queue",
              summary: "Review the current enrichment suggestions.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [
          {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: 14,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Apply core fields · Enrichment queue").click();
    await settle();

    expect(promptSpy).toHaveBeenCalled();
    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      suggestion_id: 32,
      action_preset_id: 9,
    }));
    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "enrichment",
      sessionId: 22,
      workingSetId: 7,
    }));
    expect(refreshWorkspace).toHaveBeenCalled();
  });

  it("refreshes the saved relationship target picker before execution when the cached queue is empty", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const pickerSpy = vi.spyOn(modals, "chooseOptionDialog").mockImplementation(async (config) => {
      const refreshed = await config.onRefresh?.();
      return refreshed?.options[0]?.value ?? null;
    });
    const actionBodies: Array<Record<string, unknown>> = [];
    let refreshCount = 0;

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/relationship/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 5,
            name: "Confirm duplicate",
            action_type: "confirm",
            relationship_type: "duplicate",
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: null,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [],
          loop_count: 0,
          current_index: null,
          current_item: null,
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18/refresh") && init?.method === "POST") {
        refreshCount += 1;
        return Promise.resolve(jsonResponse({
          session: {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: 12,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:03:00Z",
          },
          items: [
            {
              loop: { id: 12, title: "QA checklist", raw_text: "QA checklist", status: "actionable" },
              duplicate_candidates: [
                {
                  id: 22,
                  title: "QA checklist duplicate",
                  raw_text: "QA checklist duplicate",
                  relationship_type: "duplicate",
                  score: 0.97,
                  status: "actionable",
                  captured_at_utc: "2026-03-21T12:00:00Z",
                  captured_tz_offset_min: 0,
                  created_at_utc: "2026-03-21T12:00:00Z",
                  updated_at_utc: "2026-03-21T12:00:00Z",
                },
              ],
              related_candidates: [],
              duplicate_count: 1,
              related_count: 0,
              top_score: 0.97,
            },
          ],
          loop_count: 1,
          current_index: 0,
          current_item: {
            loop: { id: 12, title: "QA checklist", raw_text: "QA checklist", status: "actionable" },
            duplicate_candidates: [
              {
                id: 22,
                title: "QA checklist duplicate",
                raw_text: "QA checklist duplicate",
                relationship_type: "duplicate",
                score: 0.97,
                status: "actionable",
                captured_at_utc: "2026-03-21T12:00:00Z",
                captured_tz_offset_min: 0,
                created_at_utc: "2026-03-21T12:00:00Z",
                updated_at_utc: "2026-03-21T12:00:00Z",
              },
            ],
            related_candidates: [],
            duplicate_count: 1,
            related_count: 0,
            top_score: 0.97,
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/relationship/sessions/18/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 18,
              name: "Duplicate queue",
              query: "status:actionable",
              relationship_kind: "all",
              candidate_limit: 5,
              item_limit: 5,
              current_loop_id: 12,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:04:00Z",
            },
            items: [],
            loop_count: 0,
            current_index: null,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "confirmed", relationship_type: "duplicate" },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Duplicate recorded",
              summary: "The duplicate decision was stored.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Duplicate queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Duplicate recorded",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Relationship review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "relationship",
              session_id: 18,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:18",
              kind: "review_session",
              title: "Duplicate queue",
              summary: "Review the current relationship candidates.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [
          {
            id: 18,
            name: "Duplicate queue",
            query: "status:actionable",
            relationship_kind: "all",
            candidate_limit: 5,
            item_limit: 5,
            current_loop_id: null,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
        enrichmentSessions: [],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Confirm duplicate · Duplicate queue").click();
    await settle();

    expect(pickerSpy).toHaveBeenCalled();
    expect(refreshCount).toBe(1);
    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      loop_id: 12,
      candidate_loop_id: 22,
      candidate_relationship_type: "duplicate",
      action_preset_id: 5,
    }));
    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 18,
      workingSetId: 7,
    }));
  });

  it("refreshes the saved enrichment target picker before execution when the cached queue is empty", async () => {
    buildPaletteDom();
    const workingSet = workingSetFixture();
    const openLocation = vi.fn(async (_location: ShellLocationContract) => undefined);
    const refreshWorkspace = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(modals, "confirmDialog").mockResolvedValue(true);
    const pickerSpy = vi.spyOn(modals, "chooseOptionDialog").mockImplementation(async (config) => {
      const refreshed = await config.onRefresh?.();
      return refreshed?.options[0]?.value ?? null;
    });
    const actionBodies: Array<Record<string, unknown>> = [];
    let refreshCount = 0;

    globalThis.fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/loops/views")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (url.endsWith("/loops/review/enrichment/actions")) {
        return Promise.resolve(jsonResponse([
          {
            id: 9,
            name: "Apply core fields",
            action_type: "apply",
            fields: ["summary", "next_action"],
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ]));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({
          session: {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: null,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
          items: [],
          loop_count: 0,
          current_index: null,
          current_item: null,
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22/refresh") && init?.method === "POST") {
        refreshCount += 1;
        return Promise.resolve(jsonResponse({
          session: {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: 15,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:03:00Z",
          },
          items: [
            {
              loop: { id: 15, title: "Retro notes", raw_text: "Retro notes", status: "inbox" },
              newest_pending_at: "2026-03-21T12:00:00Z",
              pending_clarification_count: 0,
              pending_clarifications: [],
              pending_suggestion_count: 1,
              pending_suggestions: [
                {
                  id: 32,
                  loop_id: 15,
                  model: "pi",
                  created_at: "2026-03-21T12:00:00Z",
                  parsed: { summary: "Summarize retro", next_action: "Share action items", confidence: 0.85 },
                  suggestion_json: "{}",
                  resolution: null,
                  resolved_at: null,
                  resolved_fields_json: null,
                  clarifications: [],
                },
              ],
            },
          ],
          loop_count: 1,
          current_index: 0,
          current_item: {
            loop: { id: 15, title: "Retro notes", raw_text: "Retro notes", status: "inbox" },
            newest_pending_at: "2026-03-21T12:00:00Z",
            pending_clarification_count: 0,
            pending_clarifications: [],
            pending_suggestion_count: 1,
            pending_suggestions: [
              {
                id: 32,
                loop_id: 15,
                model: "pi",
                created_at: "2026-03-21T12:00:00Z",
                parsed: { summary: "Summarize retro", next_action: "Share action items", confidence: 0.85 },
                suggestion_json: "{}",
                resolution: null,
                resolved_at: null,
                resolved_fields_json: null,
                clarifications: [],
              },
            ],
          },
          rerun_action: null,
        }));
      }
      if (url.endsWith("/loops/review/enrichment/sessions/22/action") && init?.method === "POST") {
        actionBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          snapshot: {
            session: {
              id: 22,
              name: "Enrichment queue",
              query: "status:inbox",
              pending_kind: "suggestions",
              suggestion_limit: 5,
              clarification_limit: 3,
              item_limit: 5,
              current_loop_id: 15,
              created_at_utc: "2026-03-21T12:00:00Z",
              updated_at_utc: "2026-03-21T12:04:00Z",
            },
            items: [],
            loop_count: 0,
            current_index: null,
            current_item: null,
            rerun_action: null,
          },
          result: { resolution: "applied", suggestion_id: 32 },
          follow_through: {
            working_set_id: 7,
            display_card: {
              title: "Suggestion applied",
              summary: "The enrichment suggestion was applied.",
              rationale: "Review receipt",
              preview: [],
              trust: {
                generation_label: "Saved review action",
                generation_tone: "progress",
                context_sources: ["Enrichment queue"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: "progress",
                freshness_label: "Saved just now",
                freshness_tone: "progress",
                rollback_label: "Resume the queue",
                rollback_tone: "caution",
              },
              handoff: {
                change_summary: "Suggestion applied",
                created_resources: [],
                next_step: "Continue the queue.",
                breadcrumbs: ["Home", "Review", "Enrichment review"],
                working_set: {
                  working_set_id: 7,
                  working_set_name: "Launch Prep",
                  item_count: 3,
                  missing_item_count: 0,
                },
              },
              tone: "progress",
            },
            resume_location: {
              state: "decide",
              review_focus: "enrichment",
              session_id: 22,
              working_set_id: 7,
            },
            workflow_thread: {
              id: "review:22",
              kind: "review_session",
              title: "Enrichment queue",
              summary: "Review the current enrichment suggestions.",
              parent_outcome_id: null,
            },
            grounded_chat_location: null,
            undo_action: null,
            rerun_action: null,
          },
        }));
      }
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const controller = createController({
      openLocation,
      refreshWorkspace,
      getContext: () => ({
        currentLocation: location({ state: "operator" }),
        loops: [],
        workingSets: [workingSet],
        workingSetContext: {
          active_working_set: workingSet,
          active_working_set_id: workingSet.id,
          focus_mode_enabled: true,
          latest_reversible_event_id: null,
          latest_reversible_event_type: null,
          updated_at_utc: "2026-03-21T12:00:00Z",
        },
        nowFeed: [],
        planningSessions: [],
        relationshipSessions: [],
        enrichmentSessions: [
          {
            id: 22,
            name: "Enrichment queue",
            query: "status:inbox",
            pending_kind: "suggestions",
            suggestion_limit: 5,
            clarification_limit: 3,
            item_limit: 5,
            current_loop_id: null,
            created_at_utc: "2026-03-21T12:00:00Z",
            updated_at_utc: "2026-03-21T12:00:00Z",
          },
        ],
      }),
    });

    controller.open();
    await settle();
    findCommandButton("Use saved action · Apply core fields · Enrichment queue").click();
    await settle();

    expect(pickerSpy).toHaveBeenCalled();
    expect(refreshCount).toBe(1);
    expect(confirmSpy).toHaveBeenCalled();
    expect(actionBodies[0]).toEqual(expect.objectContaining({
      suggestion_id: 32,
      action_preset_id: 9,
    }));
    expect(openLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "enrichment",
      sessionId: 22,
      workingSetId: 7,
    }));
  });
});
