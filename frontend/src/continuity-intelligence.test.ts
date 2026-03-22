/**
 * continuity-intelligence.test.ts - Regression tests for browser-local continuity helpers.
 *
 * Purpose:
 *   Verify deterministic continuity storage stays stable for resume anchors and
 *   recent shell action history.
 *
 * Responsibilities:
 *   - Assert planning and review resume anchors persist to localStorage.
 *   - Assert recent shell actions remain newest-first.
 *   - Guard duplicate action deduplication for immediate repeats.
 *
 * Scope:
 *   - Pure browser-local continuity helper behavior under jsdom.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests use jsdom localStorage.
 *   - Continuity history remains deterministic for identical inputs.
 */

import type { ShellLocationContract } from "./contracts-ui";
import type {
  LoopMetricsResponse,
  LoopReviewResponse,
  PlanningSessionSnapshotResponse,
} from "./domain";
import {
  buildContinuityBaseline,
  acknowledgeContinuityNotification,
  hydrateDurableContinuityState,
  isContinuityRecoveryAcknowledged,
  markContinuityNotificationSeen,
  markContinuityRecoveryAcknowledged,
  markRerunActionUnavailable,
  readActiveContinuityNotificationRecords,
  readBannerContinuityNotificationRecords,
  readContinuityNotificationRecords,
  readContinuityWorkflowSummaries,
  readRecentShellActions,
  readRecentShellReceiptEntries,
  readResumeAnchors,
  recordRecentShellAction,
  rememberPlanningAnchor,
  rememberReviewAnchor,
  suppressContinuityNotification,
} from "./continuity-intelligence";

function location(overrides: Partial<ShellLocationContract> = {}): ShellLocationContract {
  return {
    state: overrides.state ?? "operator",
    recallTool: overrides.recallTool ?? "chat",
    reviewFocus: overrides.reviewFocus ?? null,
    sessionId: overrides.sessionId ?? null,
    loopId: overrides.loopId ?? null,
    viewId: overrides.viewId ?? null,
    memoryId: overrides.memoryId ?? null,
    workingSetId: overrides.workingSetId ?? null,
    query: overrides.query ?? null,
  };
}

function createMemoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length(): number {
      return values.size;
    },
    clear(): void {
      values.clear();
    },
    getItem(key: string): string | null {
      return values.get(key) ?? null;
    },
    key(index: number): string | null {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      values.delete(key);
    },
    setItem(key: string, value: string): void {
      values.set(key, value);
    },
  } satisfies Storage;
}

let originalLocalStorage: Storage;
let originalFetch: typeof fetch;

describe("continuity-intelligence", () => {
  beforeEach(() => {
    originalLocalStorage = window.localStorage as Storage;
    originalFetch = globalThis.fetch;
    Object.defineProperty(window, "localStorage", {
      value: createMemoryStorage(),
      configurable: true,
      writable: true,
    });
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ recorded_at_utc: "2026-03-17T12:00:00Z", outcomes: [], anchors: { planning: null, review: null }, workflow_summaries: [], notification_records: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-17T12:00:00Z"));
  });

  afterEach(() => {
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
  });

  it("persists continuity recovery acknowledgements", () => {
    expect(isContinuityRecoveryAcknowledged("replacement::planning:99")).toBe(false);
    markContinuityRecoveryAcknowledged("replacement::planning:99");
    expect(isContinuityRecoveryAcknowledged("replacement::planning:99")).toBe(true);
  });

  it("persists planning and review resume anchors", () => {
    rememberPlanningAnchor({
      sessionId: 41,
      launchLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 3 }),
      resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 3 }),
      outcomeTitle: "Resume plan · Weekly reset",
      outcomeSummary: "Return to the saved planning session.",
      workingSetId: 3,
    });
    vi.setSystemTime(new Date("2026-03-17T12:05:00Z"));
    rememberReviewAnchor({
      reviewFocus: "relationship",
      sessionId: 7,
      launchLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 7, workingSetId: 5 }),
      resumeLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 7, workingSetId: 5 }),
      outcomeTitle: "Resume relationship queue · Launch duplicates",
      outcomeSummary: "Return to the saved relationship queue.",
      workingSetId: 5,
    });

    expect(readResumeAnchors()).toEqual({
      planning: {
        kind: "planning",
        reviewFocus: "planning",
        sessionId: 41,
        visitedAtUtc: "2026-03-17T12:00:00.000Z",
        launchLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 3 }),
        resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 3 }),
        outcomeTitle: "Resume plan · Weekly reset",
        outcomeSummary: "Return to the saved planning session.",
        workingSetId: 3,
        workflowThreadId: "planning:41",
        resolvedResume: null,
        degraded: false,
        degradedLabel: null,
      },
      review: {
        kind: "review",
        reviewFocus: "relationship",
        sessionId: 7,
        visitedAtUtc: "2026-03-17T12:05:00.000Z",
        launchLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 7, workingSetId: 5 }),
        resumeLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 7, workingSetId: 5 }),
        outcomeTitle: "Resume relationship queue · Launch duplicates",
        outcomeSummary: "Return to the saved relationship queue.",
        workingSetId: 5,
        workflowThreadId: "review:relationship:7",
        resolvedResume: null,
        degraded: false,
        degradedLabel: null,
      },
    });
  });

  it("hydrates durable continuity state into the local cache", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        recorded_at_utc: "2026-03-17T12:00:00Z",
        outcomes: [
          {
            id: 7,
            kind: "planning",
            label: "Created launch review queue",
            description: "The enrichment queue is ready to resume.",
            occurred_at_utc: "2026-03-17T11:55:00Z",
            launch_location: {
              state: "plan",
              recall_tool: "chat",
              review_focus: "planning",
              session_id: 41,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: null,
              query: null,
            },
            outcome_card: {
              id: "receipt-1",
              kind: "receipt",
              tone: "progress",
              eyebrow: "Planning receipt",
              title: "Created launch review queue",
              summary: "The enrichment queue is ready to resume.",
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
            resume_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "enrichment",
              session_id: 52,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 7,
              query: null,
            },
            resolved_resume: {
              requested_location: {
                state: "decide",
                recall_tool: "chat",
                review_focus: "enrichment",
                session_id: 52,
                loop_id: null,
                view_id: null,
                memory_id: null,
                working_set_id: 7,
                query: null,
              },
              resolved_location: {
                state: "decide",
                recall_tool: "chat",
                review_focus: "enrichment",
                session_id: 52,
                loop_id: null,
                view_id: null,
                memory_id: null,
                working_set_id: 7,
                query: null,
              },
              status: "ok",
              message: null,
              successor: null,
            },
            workflow_thread: {
              id: "planning:41:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Planning checkpoint thread",
              parent_outcome_id: null,
            },
            working_set_id: 7,
            degraded: false,
            degraded_label: null,
            metadata: { sessionId: 41 },
          },
        ],
        anchors: {
          planning: {
            kind: "planning",
            review_focus: "planning",
            session_id: 41,
            visited_at_utc: "2026-03-17T11:56:00Z",
            launch_location: null,
            resume_location: {
              state: "plan",
              recall_tool: "chat",
              review_focus: "planning",
              session_id: 41,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 7,
              query: null,
            },
            outcome_title: "Resume weekly reset",
            outcome_summary: "Continue the saved planning session.",
            working_set_id: 7,
            workflow_thread_id: "planning:41",
            metadata: {},
          },
          review: null,
        },
        workflow_summaries: [
          {
            id: "planning:41:checkpoint:0",
            source: "receipt",
            rank: 5418,
            ranking_signals: {
              drift_severity: "moderate",
              drift_score: 52,
              working_set_relevant: true,
              downstream_ready: true,
              degraded: false,
              recency_tie_breaker: 18,
            },
            workflow_thread: {
              id: "planning:41:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Planning checkpoint thread",
              parent_outcome_id: null,
            },
            representative_outcome_id: 7,
            latest_outcome_id: 7,
            occurred_at_utc: "2026-03-17T11:55:00Z",
            outcome_count: 1,
            outcome_preview_titles: ["Created launch review queue"],
            requested_resume_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "enrichment",
              session_id: 52,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 7,
              query: null,
            },
            resolved_resume: {
              requested_location: {
                state: "decide",
                recall_tool: "chat",
                review_focus: "enrichment",
                session_id: 52,
                loop_id: null,
                view_id: null,
                memory_id: null,
                working_set_id: 7,
                query: null,
              },
              resolved_location: {
                state: "decide",
                recall_tool: "chat",
                review_focus: "enrichment",
                session_id: 52,
                loop_id: null,
                view_id: null,
                memory_id: null,
                working_set_id: 7,
                query: null,
              },
              status: "ok",
              message: null,
              successor: null,
            },
            display_title: "Created launch review queue",
            display_summary: "The enrichment queue is ready to resume.",
            working_set_id: 7,
            degraded: false,
            degraded_label: null,
            why_now: ["This workflow has fresh unseen movement."],
            changed_since_last_seen: ["This workflow has never been seen from durable continuity."],
            prior_state: null,
          },
        ],
        notification_records: [
          {
            id: "planning:41:checkpoint:0",
            title: "Created launch review queue is ready in your working set",
            body: "This workflow has fresh unseen movement. · This workflow has never been seen from durable continuity.",
            severity: "info",
            workflow_thread: {
              id: "planning:41:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Planning checkpoint thread",
              parent_outcome_id: null,
            },
            resolved_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "enrichment",
              session_id: 52,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 7,
              query: null,
            },
            state: {
              inboxed_at_utc: null,
              seen_at_utc: null,
              acknowledged_at_utc: null,
              suppressed_until_utc: null,
            },
          },
        ],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await hydrateDurableContinuityState();

    expect(readRecentShellActions()).toHaveLength(1);
    expect(readRecentShellActions()[0]?.outcome?.workflowThread?.id).toBe("planning:41:checkpoint:0");
    expect(readResumeAnchors().planning?.workflowThreadId).toBe("planning:41");
    expect(readContinuityWorkflowSummaries()[0]?.id).toBe("planning:41:checkpoint:0");
    expect(readContinuityNotificationRecords()[0]?.title).toBe("Created launch review queue is ready in your working set");
  });

  it("persists local notification seen and acknowledgement state", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        recorded_at_utc: "2026-03-17T12:00:00Z",
        outcomes: [],
        anchors: { planning: null, review: null },
        workflow_summaries: [],
        notification_records: [
          {
            id: "planning:41:checkpoint:0",
            title: "Created launch review queue is ready in your working set",
            body: "This workflow has fresh unseen movement.",
            severity: "info",
            workflow_thread: {
              id: "planning:41:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Planning checkpoint thread",
              parent_outcome_id: null,
            },
            resolved_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "enrichment",
              session_id: 52,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 7,
              query: null,
            },
            state: {
              inboxed_at_utc: null,
              seen_at_utc: null,
              acknowledged_at_utc: null,
              suppressed_until_utc: null,
            },
          },
        ],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await hydrateDurableContinuityState();
    markContinuityNotificationSeen("planning:41:checkpoint:0");
    acknowledgeContinuityNotification("planning:41:checkpoint:0");

    const state = readContinuityNotificationRecords()[0]?.state;
    expect(state?.inboxedAtUtc).not.toBeNull();
    expect(state?.seenAtUtc).not.toBeNull();
    expect(state?.acknowledgedAtUtc).not.toBeNull();
  });

  it("filters active and banner notification records from durable state", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        recorded_at_utc: "2026-03-17T12:00:00Z",
        outcomes: [],
        anchors: { planning: null, review: null },
        workflow_summaries: [],
        notification_records: [
          {
            id: "planning:41:checkpoint:0",
            title: "Created launch review queue is ready in your working set",
            body: "This workflow has fresh unseen movement.",
            severity: "info",
            workflow_thread: {
              id: "planning:41:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Planning checkpoint thread",
              parent_outcome_id: null,
            },
            resolved_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "enrichment",
              session_id: 52,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 7,
              query: null,
            },
            state: {
              inboxed_at_utc: "2026-03-17T12:00:00Z",
              seen_at_utc: "2026-03-17T12:01:00Z",
              acknowledged_at_utc: null,
              suppressed_until_utc: null,
            },
          },
          {
            id: "planning:42:checkpoint:0",
            title: "Review queue needs attention",
            body: "Fresh follow-up exists.",
            severity: "warning",
            workflow_thread: {
              id: "planning:42:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Launch prep",
              summary: "Planning checkpoint thread",
              parent_outcome_id: null,
            },
            resolved_location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "relationship",
              session_id: 7,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: null,
              query: null,
            },
            state: {
              inboxed_at_utc: null,
              seen_at_utc: null,
              acknowledged_at_utc: null,
              suppressed_until_utc: null,
            },
          },
        ],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await hydrateDurableContinuityState();
    suppressContinuityNotification("planning:41:checkpoint:0", 24);

    expect(readActiveContinuityNotificationRecords().map((item) => item.id)).toEqual(["planning:42:checkpoint:0"]);
    expect(readBannerContinuityNotificationRecords().map((item) => item.id)).toEqual(["planning:42:checkpoint:0"]);
  });

  it("keeps recent shell actions newest-first", () => {
    recordRecentShellAction({
      kind: "navigation",
      label: "Opened do",
      description: "Moved into the do workspace.",
      location: location({ state: "do", loopId: 11 }),
    });
    vi.setSystemTime(new Date("2026-03-17T12:01:00Z"));
    recordRecentShellAction({
      kind: "recall",
      label: "Opened recall · chat",
      description: "Moved into grounded chat.",
      location: location({ state: "recall", recallTool: "chat" }),
    });

    expect(readRecentShellActions().map((entry) => entry.label)).toEqual([
      "Opened recall · chat",
      "Opened do",
    ]);
  });

  it("dedupes immediate duplicates by landed outcome identity", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Opened planning session from review",
      description: "Jumped to the saved planning session.",
      location: location({ state: "review", reviewFocus: "cohorts" }),
      outcome: {
        card: {
          id: "receipt-plan-a",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Executed checkpoint",
          summary: "The downstream review queue is ready.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Undo from planning if needed.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 19 }),
        rollbackLabel: "Undo from planning if needed.",
        undoAction: null,
      },
    });
    vi.setSystemTime(new Date("2026-03-17T12:00:10Z"));
    recordRecentShellAction({
      kind: "planning",
      label: "Reopened the same checkpoint outcome",
      description: "Started from a different launch point.",
      location: location({ state: "operator" }),
      outcome: {
        card: {
          id: "receipt-plan-b",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Executed checkpoint",
          summary: "The downstream review queue is ready.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Undo from planning if needed.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 19 }),
        rollbackLabel: "Undo from planning if needed.",
        undoAction: null,
      },
    });

    const recent = readRecentShellActions();
    expect(recent).toHaveLength(1);
    expect(recent[0]?.occurredAt).toBe("2026-03-17T12:00:10.000Z");
    expect(recent[0]?.outcome?.resumeLocation?.sessionId).toBe(19);
  });

  it("keeps distinct working-set session launches separate", () => {
    recordRecentShellAction({
      kind: "working_set_session",
      label: "Opened working set · Launch",
      description: "Opened one working-set session.",
      location: location({ state: "working_set", workingSetId: 4 }),
    });
    vi.setSystemTime(new Date("2026-03-17T12:00:05Z"));
    recordRecentShellAction({
      kind: "working_set_session",
      label: "Opened working set · Review",
      description: "Opened another working-set session.",
      location: location({ state: "working_set", workingSetId: 7 }),
    });

    expect(readRecentShellActions().map((entry) => entry.location?.workingSetId ?? null)).toEqual([7, 4]);
  });

  it("reads receipt-bearing recent actions separately", () => {
    recordRecentShellAction({
      kind: "review",
      label: "Applied enrichment suggestion",
      description: "Applied the top suggestion and refreshed the queue.",
      location: location({ state: "decide", reviewFocus: "enrichment", sessionId: 9 }),
      outcome: {
        card: {
          id: "receipt-1",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Enrichment receipt",
          title: "Applied enrichment suggestion",
          summary: "Applied the top suggestion and refreshed the queue.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Saved enrichment session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Rejecting is no longer available after apply.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 9 }),
        rollbackLabel: "Rejecting is no longer available after apply.",
        undoAction: null,
      },
    });

    expect(readRecentShellReceiptEntries()).toHaveLength(1);
    expect(readRecentShellReceiptEntries()[0]?.outcome.card.title).toBe("Applied enrichment suggestion");
  });

  it("keeps distinct receipts when the landed summaries differ", () => {
    recordRecentShellAction({
      kind: "working_set",
      label: "Pinned evidence",
      description: "Saved a resume anchor.",
      location: location({ state: "recall", recallTool: "rag", query: "evidence" }),
      outcome: {
        card: {
          id: "receipt-a",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Working-set receipt",
          title: "Pinned evidence",
          summary: "Saved Evidence A.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Working set"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Remove the anchor to undo this.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "recall", recallTool: "rag", query: "evidence" }),
        rollbackLabel: "Remove the anchor to undo this.",
        undoAction: null,
      },
    });
    vi.setSystemTime(new Date("2026-03-17T12:00:10Z"));
    recordRecentShellAction({
      kind: "working_set",
      label: "Pinned evidence",
      description: "Saved a resume anchor.",
      location: location({ state: "recall", recallTool: "rag", query: "evidence" }),
      outcome: {
        card: {
          id: "receipt-b",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Working-set receipt",
          title: "Pinned evidence",
          summary: "Saved Evidence B.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Working set"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Remove the anchor to undo this.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "recall", recallTool: "rag", query: "evidence" }),
        rollbackLabel: "Remove the anchor to undo this.",
        undoAction: null,
      },
    });

    expect(readRecentShellActions()).toHaveLength(2);
  });

  it("marks stored rerun actions unavailable by handle identity", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Refreshed weekly reset",
      description: "The planning session was refreshed.",
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
      outcome: {
        card: {
          id: "receipt-plan-rerun",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Refreshed weekly reset",
          summary: "The planning session was refreshed.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Opening the plan is still safe.",
          },
          handoff: null,
          actions: [
            {
              type: "rerun",
              label: "Refresh plan",
              variant: "secondary",
              description: "Land back in the saved planning session.",
              rerun: {
                kind: "planning_session",
                sessionId: 41,
                sessionName: "weekly-reset",
              },
              contract: {
                mode: "refresh",
                provenanceLabel: "Planning session: weekly-reset",
                freshnessLabel: "1 target changed",
                strategySummary: "Reuse the saved planning session and refresh it against current loop state.",
                strictInvariants: ["Same planning session identity"],
                mayVary: ["Checkpoint wording"],
                postRun: {
                  summary: "Land back in the saved planning session.",
                  location: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
                },
              },
            },
          ],
        },
        resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
        rollbackLabel: "Opening the plan is still safe.",
        undoAction: null,
      },
    });

    markRerunActionUnavailable(
      {
        kind: "planning_session",
        sessionId: 41,
        sessionName: "weekly-reset",
      },
      "This rerun target is no longer available.",
    );

    const stored = readRecentShellActions();
    expect(stored[0]?.outcome?.card.actions[0]).toMatchObject({
      type: "rerun",
      disabledReason: "This rerun target is no longer available.",
    });
  });

  it("captures richer planning-session continuity baseline fields", () => {
    const baseline = buildContinuityBaseline({
      metrics: {
        stale_open_count: 0,
        blocked_too_long_count: 0,
        no_next_action_count: 0,
      } as LoopMetricsResponse,
      reviewData: {
        generated_at_utc: "2026-03-17T12:00:00Z",
        daily: [],
        weekly: [],
      } as LoopReviewResponse,
      planningSnapshot: {
        session: {
          id: 19,
          name: "weekly-reset",
          prompt: "Reset the launch work",
          query: "status:open",
          loop_limit: 10,
          include_memory_context: true,
          include_rag_context: false,
          rag_k: 5,
          rag_scope: null,
          current_checkpoint_index: 1,
          checkpoint_count: 2,
          executed_checkpoint_count: 1,
          next_unexecuted_checkpoint_index: 1,
          generated_at_utc: "2026-03-17T12:00:00Z",
          last_executed_at_utc: "2026-03-17T12:05:00Z",
          status: "in_progress",
          created_at_utc: "2026-03-17T12:00:00Z",
          updated_at_utc: "2026-03-17T12:05:00Z",
        },
        plan_title: "Weekly reset",
        plan_summary: "Bring launch work back under control.",
        assumptions: [],
        context_summary: {},
        context_freshness: {
          generated_at_utc: "2026-03-17T12:00:00Z",
          target_loop_count: 2,
          stale_target_loop_ids: [7],
          stale_target_loop_count: 1,
          missing_target_loop_ids: [],
          missing_target_loop_count: 0,
          latest_target_loop_update_at_utc: "2026-03-17T12:04:00Z",
          changed_targets: [],
          changed_field_counts: { status: 1 },
          status_changed_count: 1,
          next_action_changed_count: 0,
          summary_label: "1 target loop changed",
          is_stale: true,
        },
        execution_analytics: {},
        resource_change_summary: {
          total_change_count: 3,
          loop_change_count: 2,
          downstream_change_count: 1,
          group_count: 2,
          created_resource_count: 1,
          updated_resource_count: 2,
          groups: [],
          loop_groups: [],
          downstream_groups: [],
          summary_label: "2 loop changes · 1 downstream resource change",
          downstream_summary_label: "1 downstream resource change",
        },
        target_loops: [
          { id: 7, raw_text: "Prepare launch checklist", status: "actionable", tags: [] },
          { id: 8, raw_text: "Confirm launch owner", status: "blocked", tags: [] },
        ],
        sources: [],
        checkpoints: [],
        current_checkpoint: null,
        execution_history: [],
      } as PlanningSessionSnapshotResponse,
      relationshipSnapshot: null,
      enrichmentSnapshot: null,
      allLoops: [],
      workingSetContext: null,
    });

    expect(baseline.planningSession).toEqual(expect.objectContaining({
      sessionId: 19,
      sessionName: "weekly-reset",
      status: "in_progress",
      generatedAtUtc: "2026-03-17T12:00:00Z",
      contextIsStale: true,
      staleTargetLoopCount: 1,
      targetLoopIds: [7, 8],
      lastExecutedAtUtc: "2026-03-17T12:05:00Z",
      resourceChangeCount: 3,
      downstreamResourceChangeCount: 1,
    }));
  });
});
