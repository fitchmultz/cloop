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
  readRecentShellActions,
  readResumeAnchors,
  recordRecentShellAction,
  rememberPlanningAnchor,
  rememberReviewAnchor,
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

describe("continuity-intelligence", () => {
  beforeEach(() => {
    originalLocalStorage = window.localStorage as Storage;
    Object.defineProperty(window, "localStorage", {
      value: createMemoryStorage(),
      configurable: true,
      writable: true,
    });
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-17T12:00:00Z"));
  });

  afterEach(() => {
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    vi.useRealTimers();
  });

  it("persists planning and review resume anchors", () => {
    rememberPlanningAnchor(41);
    vi.setSystemTime(new Date("2026-03-17T12:05:00Z"));
    rememberReviewAnchor("relationship", 7);

    expect(readResumeAnchors()).toEqual({
      lastPlanningSessionId: 41,
      lastPlanningVisitedAtUtc: "2026-03-17T12:00:00.000Z",
      lastReviewFocus: "relationship",
      lastReviewSessionId: 7,
      lastReviewVisitedAtUtc: "2026-03-17T12:05:00.000Z",
    });
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

  it("dedupes immediate duplicate recent actions for the same location", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Resumed plan #19",
      description: "Opened a saved planning session.",
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 19 }),
    });
    vi.setSystemTime(new Date("2026-03-17T12:00:10Z"));
    recordRecentShellAction({
      kind: "planning",
      label: "Resumed plan #19",
      description: "Opened a saved planning session again.",
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 19 }),
    });

    const recent = readRecentShellActions();
    expect(recent).toHaveLength(1);
    expect(recent[0]?.occurredAt).toBe("2026-03-17T12:00:10.000Z");
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
