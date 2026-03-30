/**
 * continuity-intelligence.test.ts - Regression tests for browser-local continuity helpers.
 *
 * Purpose:
 *   Verify deterministic continuity storage stays stable for recent shell action
 *   history and durable continuity hydration.
 *
 * Responsibilities:
 *   - Assert recent shell actions remain newest-first.
 *   - Guard duplicate action deduplication for immediate repeats.
 *   - Assert durable continuity hydration preserves receipt metadata.
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
  markUndoActionUnavailable,
  readActiveContinuityNotificationRecords,
  readBannerContinuityNotificationRecords,
  readContinuityNotificationRecords,
  readContinuityWorkflowSummaries,
  readRecentShellActions,
  recordRecentShellAction,
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

function buildReviewContinuitySnapshot(input: {
  outcomeId: number;
  reviewFocus: "relationship" | "enrichment";
  sessionId: number;
  sessionName: string;
  title: string;
  summary: string;
  eyebrow: string;
  undoAction: Record<string, unknown> | null;
  workingSetId: number | null;
}): Record<string, unknown> {
  const location = {
    state: "decide",
    recall_tool: "chat",
    review_focus: input.reviewFocus,
    session_id: input.sessionId,
    loop_id: null,
    view_id: null,
    memory_id: null,
    working_set_id: input.workingSetId,
    query: null,
  };
  const workflowThread = {
    id: `review:${input.reviewFocus}:${input.sessionId}`,
    kind: "review_session",
    title: input.sessionName,
    summary: `${input.eyebrow} thread`,
    parent_outcome_id: null,
  };
  const rerunAction = {
    label: input.reviewFocus === "relationship" ? "Refresh queue" : "Refresh enrichment",
    description: `Refresh ${input.sessionName}.`,
    rerun: {
      kind: "review_session",
      review_focus: input.reviewFocus,
      session_id: input.sessionId,
      session_name: input.sessionName,
    },
    contract: {
      mode: "refresh",
      provenance_label: `${input.sessionName} · status:open`,
      freshness_label: "Updated 2026-03-28T18:30:00Z",
      strategy_summary: `Reuse the saved ${input.reviewFocus} review session.`,
      strict_invariants: ["Same saved review session identity"],
      may_vary: ["Queue membership and cursor target"],
      post_run: {
        summary: `Land back in ${input.sessionName}.`,
        location,
      },
    },
  };
  const displayCard = {
    kind: "receipt",
    tone: "progress",
    eyebrow: input.eyebrow,
    title: input.title,
    summary: input.summary,
    rationale: "Receipt",
    preview: [],
    trust: {
      generation_label: null,
      generation_tone: null,
      context_sources: [`Saved ${input.reviewFocus} review session`],
      assumptions: [],
      confidence_label: "Recorded",
      confidence_tone: null,
      freshness_label: "Saved just now",
      freshness_tone: null,
      rollback_label: input.undoAction ? "Undo remains available." : "Undo is not available.",
      rollback_tone: null,
      impact_summary: input.summary,
      impact_tone: null,
    },
    handoff: null,
    action_context_label: "Continue from here",
    action_warning: null,
  };
  const resolvedResume = {
    requested_location: location,
    resolved_location: location,
    status: "ok",
    message: null,
    successor: null,
  };
  return {
    recorded_at_utc: "2026-03-17T12:00:00Z",
    outcomes: [
      {
        id: input.outcomeId,
        kind: "review",
        label: input.title,
        description: input.summary,
        occurred_at_utc: "2026-03-17T11:55:00Z",
        launch_location: location,
        display_card: displayCard,
        undo_action: input.undoAction,
        rerun_action: rerunAction,
        resume_location: location,
        resolved_resume: resolvedResume,
        workflow_thread: workflowThread,
        working_set_id: input.workingSetId,
        degraded: false,
        degraded_label: null,
        metadata: { source: "review-workspace", sessionId: input.sessionId },
      },
    ],
    workflow_summaries: [
      {
        id: workflowThread.id,
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
        workflow_thread: workflowThread,
        representative_outcome_id: input.outcomeId,
        latest_outcome_id: input.outcomeId,
        occurred_at_utc: "2026-03-17T11:55:00Z",
        outcome_count: 1,
        outcome_preview_titles: [input.title],
        requested_resume_location: location,
        resolved_resume: resolvedResume,
        display_title: input.title,
        display_summary: input.summary,
        display_card: displayCard,
        undo_action: input.undoAction,
        rerun_action: rerunAction,
        working_set_id: input.workingSetId,
        degraded: false,
        degraded_label: null,
        why_now: ["This workflow has fresh unseen movement."],
        changed_since_last_seen: ["This workflow has never been seen from durable continuity."],
        prior_state: null,
      },
    ],
    notification_records: [
      {
        id: workflowThread.id,
        title: `${input.title} is ready in your review queue`,
        body: "This workflow has fresh unseen movement.",
        severity: "info",
        workflow_thread: workflowThread,
        resolved_location: location,
        state: {
          inboxed_at_utc: null,
          seen_at_utc: null,
          acknowledged_at_utc: null,
          suppressed_until_utc: null,
        },
      },
    ],
    last_seen_markers: [],
    recovery_acknowledgements: [],
  };
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
      new Response(JSON.stringify({ recorded_at_utc: "2026-03-17T12:00:00Z", outcomes: [], workflow_summaries: [], notification_records: [], last_seen_markers: [], recovery_acknowledgements: [] }), {
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
            display_card: {
              kind: "receipt",
              tone: "progress",
              eyebrow: "Planning receipt",
              title: "Created launch review queue",
              summary: "The enrichment queue is ready to resume.",
              rationale: "Receipt",
              preview: [],
              trust: {
                generation_label: null,
                generation_tone: null,
                context_sources: ["Planning session"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: null,
                freshness_label: "Saved just now",
                freshness_tone: null,
                rollback_label: "Undo remains available.",
                rollback_tone: null,
                impact_summary: null,
                impact_tone: null,
              },
              handoff: null,
              action_context_label: null,
              action_warning: null,
            },
            undo_action: {
              label: "Undo checkpoint",
              description: "Undo the checkpoint execution.",
              undo: {
                kind: "planning_run",
                session_id: 41,
                run_id: 8,
                checkpoint_index: 1,
                checkpoint_title: "Create queue",
                action_count: 2,
                best_effort: false,
              },
              requires_confirmation: false,
              confirm_title: null,
              confirm_description: null,
              success_location: null,
            },
            rerun_action: {
              label: "Refresh plan",
              description: "Refresh the saved planning session.",
              rerun: {
                kind: "planning_session",
                session_id: 41,
                session_name: "Weekly reset",
              },
              contract: {
                mode: "refresh",
                provenance_label: "Planning session: Weekly reset",
                freshness_label: "1 target changed",
                strategy_summary: "Reuse the saved planning session.",
                strict_invariants: ["Same planning session identity"],
                may_vary: ["Checkpoint wording"],
                post_run: {
                  summary: "Land back in the saved planning session.",
                  location: null,
                },
              },
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
        last_seen_markers: [],
        recovery_acknowledgements: [],
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
            display_card: {
              kind: "receipt",
              tone: "progress",
              eyebrow: "Planning receipt",
              title: "Created launch review queue",
              summary: "The enrichment queue is ready to resume.",
              rationale: "Receipt",
              preview: [],
              trust: {
                generation_label: null,
                generation_tone: null,
                context_sources: ["Planning session"],
                assumptions: [],
                confidence_label: "Recorded",
                confidence_tone: null,
                freshness_label: "Saved just now",
                freshness_tone: null,
                rollback_label: "Undo remains available.",
                rollback_tone: null,
                impact_summary: null,
                impact_tone: null,
              },
              handoff: null,
              action_context_label: "Continue from here",
              action_warning: null,
            },
            undo_action: {
              label: "Undo checkpoint",
              description: "Undo the checkpoint execution.",
              undo: {
                kind: "planning_run",
                session_id: 41,
                run_id: 8,
                checkpoint_index: 1,
                checkpoint_title: "Create queue",
                action_count: 2,
                best_effort: false,
              },
              requires_confirmation: false,
              confirm_title: null,
              confirm_description: null,
              success_location: null,
            },
            rerun_action: {
              label: "Refresh plan",
              description: "Refresh the saved planning session.",
              rerun: {
                kind: "planning_session",
                session_id: 41,
                session_name: "Weekly reset",
              },
              contract: {
                mode: "refresh",
                provenance_label: "Planning session: Weekly reset",
                freshness_label: "1 target changed",
                strategy_summary: "Reuse the saved planning session.",
                strict_invariants: ["Same planning session identity"],
                may_vary: ["Checkpoint wording"],
                post_run: {
                  summary: "Land back in the saved planning session.",
                  location: null,
                },
              },
            },
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
    expect(readRecentShellActions()[0]?.outcome?.undoAction?.undo.kind).toBe("planning_run");
    expect(readRecentShellActions()[0]?.outcome?.rerunAction?.rerun.kind).toBe("planning_session");
    expect(readContinuityWorkflowSummaries()[0]?.id).toBe("planning:41:checkpoint:0");
    expect(readContinuityWorkflowSummaries()[0]?.undoAction?.undo.kind).toBe("planning_run");
    expect(readContinuityWorkflowSummaries()[0]?.rerunAction?.rerun.kind).toBe("planning_session");
    expect(readContinuityNotificationRecords()[0]?.title).toBe("Created launch review queue is ready in your working set");
  });

  it("hydrates relationship review outcomes and keeps stale undo/rerun disablement synchronized", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(buildReviewContinuitySnapshot({
        outcomeId: 9,
        reviewFocus: "relationship",
        sessionId: 17,
        sessionName: "duplicate-pass",
        title: "Dismissed duplicate suggestion",
        summary: "The relationship queue advanced after the saved decision.",
        eyebrow: "Relationship receipt",
        undoAction: {
          label: "Undo decision",
          description: "Restore the pair to the saved queue.",
          undo: {
            kind: "relationship_decision",
            session_id: 17,
            loop_id: 8,
            candidate_loop_id: 11,
            expected_pair_state: {
              duplicate: { state: "dismissed", confidence: 1, source: "human_review" },
              related: null,
            },
            restore_pair_state: {
              duplicate: { state: "active", confidence: 0.82, source: "similarity" },
              related: null,
            },
          },
          requires_confirmation: false,
          confirm_title: null,
          confirm_description: null,
          success_location: null,
        },
        workingSetId: 9,
      })), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await hydrateDurableContinuityState();

    expect(readRecentShellActions()[0]?.outcome?.resumeLocation).toEqual(
      location({ state: "decide", reviewFocus: "relationship", sessionId: 17, workingSetId: 9 }),
    );
    expect(readRecentShellActions()[0]?.outcome?.undoAction?.undo.kind).toBe("relationship_decision");
    expect(readRecentShellActions()[0]?.outcome?.rerunAction?.rerun.kind).toBe("review_session");
    expect(readContinuityWorkflowSummaries()[0]?.requestedResumeLocation).toEqual(
      location({ state: "decide", reviewFocus: "relationship", sessionId: 17, workingSetId: 9 }),
    );

    markUndoActionUnavailable(
      readRecentShellActions()[0]!.outcome!.undoAction!.undo,
      "This saved relationship decision is stale.",
    );
    markRerunActionUnavailable(
      readRecentShellActions()[0]!.outcome!.rerunAction!.rerun,
      "This saved review session moved.",
    );

    expect(readRecentShellActions()[0]?.outcome?.undoAction?.disabledReason).toBe(
      "This saved relationship decision is stale.",
    );
    expect(readContinuityWorkflowSummaries()[0]?.undoAction?.disabledReason).toBe(
      "This saved relationship decision is stale.",
    );
    expect(readRecentShellActions()[0]?.outcome?.rerunAction?.disabledReason).toBe(
      "This saved review session moved.",
    );
    expect(readContinuityWorkflowSummaries()[0]?.rerunAction?.disabledReason).toBe(
      "This saved review session moved.",
    );
  });

  it("persists clarification-answer undo handles through recent-action storage", () => {
    recordRecentShellAction({
      kind: "review",
      label: "Saved clarification answers",
      description: "Clarifications recorded. Re-enrich to generate an updated suggestion.",
      location: location({ state: "do", loopId: 19 }),
      metadata: {
        loopId: 19,
        reviewFocus: "enrichment",
      },
      outcome: {
        card: {
          id: "clarification-answer-19-7-11",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Suggestion receipt",
          title: "Saved clarification answers",
          summary: "Clarifications recorded. Re-enrich to generate an updated suggestion.",
          rationale: "Receipt",
          preview: [],
          trust: {
            generationLabel: "Recorded clarification answers",
            generationTone: "progress",
            contextSources: ["Loop suggestion surface"],
            assumptions: [],
            confidenceLabel: "Answers saved",
            confidenceTone: "progress",
            freshnessLabel: "Saved just now",
            freshnessTone: "progress",
            rollbackLabel: "Undo restores these clarifications to their unanswered state.",
            rollbackTone: "caution",
            impactSummary: "The answers are saved without rerunning enrichment.",
            impactTone: "progress",
          },
          handoff: null,
          actionContextLabel: null,
          actionWarning: null,
          actions: [],
        },
        resumeLocation: location({ state: "do", loopId: 19 }),
        rollbackLabel: "Undo restores these clarifications to their unanswered state.",
        undoAction: {
          type: "undo",
          label: "Undo answers",
          variant: "secondary",
          description: "Restore these 2 clarifications to their unanswered state.",
          undo: {
            kind: "clarification_answer",
            loopId: 19,
            clarificationIds: [7, 11],
          },
          successLocation: location({ state: "do", loopId: 19 }),
        },
        rerunAction: null,
        workflowThread: {
          id: "clarification-answer:loop:19",
          kind: "ad_hoc",
          title: "Saved clarification answers",
          summary: "Clarifications recorded. Re-enrich to generate an updated suggestion.",
          parentOutcomeId: null,
        },
        resolvedResume: null,
      },
    });

    expect(readRecentShellActions()[0]?.outcome?.undoAction?.undo.kind).toBe("clarification_answer");
    expect(readRecentShellActions()[0]?.outcome?.undoAction?.undo).toEqual({
      kind: "clarification_answer",
      loopId: 19,
      clarificationIds: [7, 11],
    });
  });

  it("hydrates enrichment review outcomes with executable reopen, undo, and rerun state", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(buildReviewContinuitySnapshot({
        outcomeId: 10,
        reviewFocus: "enrichment",
        sessionId: 52,
        sessionName: "enrichment-pass",
        title: "Applied title suggestion",
        summary: "The enrichment queue refreshed after the saved suggestion landed.",
        eyebrow: "Enrichment receipt",
        undoAction: {
          label: "Undo enrichment",
          description: "Restore the loop before the suggestion landed.",
          undo: {
            kind: "loop_event",
            loop_id: 41,
            expected_event_id: 91,
            event_type: "update",
            claim_token: null,
          },
          requires_confirmation: false,
          confirm_title: null,
          confirm_description: null,
          success_location: null,
        },
        workingSetId: 7,
      })), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await hydrateDurableContinuityState();

    expect(readRecentShellActions()[0]?.outcome?.resumeLocation).toEqual(
      location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
    );
    expect(readRecentShellActions()[0]?.outcome?.undoAction?.undo.kind).toBe("loop_event");
    expect(readRecentShellActions()[0]?.outcome?.rerunAction?.rerun.kind).toBe("review_session");
    expect(readContinuityWorkflowSummaries()[0]?.requestedResumeLocation).toEqual(
      location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
    );
    expect(readContinuityWorkflowSummaries()[0]?.undoAction?.undo.kind).toBe("loop_event");
    expect(readContinuityNotificationRecords()[0]?.workflowThread.id).toBe("review:enrichment:52");
  });

  it("persists local notification seen and acknowledgement state", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        recorded_at_utc: "2026-03-17T12:00:00Z",
        outcomes: [],
        last_seen_markers: [],
        recovery_acknowledgements: [],
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
        last_seen_markers: [],
        recovery_acknowledgements: [],
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

    expect(readRecentShellActions()).toHaveLength(1);
    expect(readRecentShellActions()[0]?.outcome?.card.title).toBe("Applied enrichment suggestion");
  });

  it("drops malformed stored relationship undo handles from recent actions", () => {
    window.localStorage.setItem("cloop.continuity.recent-actions.cache.v4", JSON.stringify([
      {
        kind: "review",
        label: "Undo relationship decision",
        description: "Restore the relationship pair.",
        location: location({ state: "decide", reviewFocus: "relationship", sessionId: 17 }),
        occurredAt: "2026-03-17T12:00:00Z",
        outcome: {
          card: {
            id: "receipt-relationship-undo-invalid",
            kind: "receipt",
            tone: "progress",
            eyebrow: "Relationship receipt",
            title: "Undo relationship decision",
            summary: "Restore the relationship pair.",
            rationale: "Receipt",
            preview: [],
            trust: {
              contextSources: ["Relationship review"],
              assumptions: [],
              confidenceLabel: "Recorded",
              freshnessLabel: "Saved just now",
              rollbackLabel: "Undo remains available.",
            },
            handoff: null,
            actions: [],
          },
          resumeLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 17 }),
          rollbackLabel: "Undo remains available.",
          undoAction: {
            type: "undo",
            label: "Undo decision",
            variant: "secondary",
            description: "Restore the relationship pair.",
            undo: {
              kind: "relationship_decision",
              sessionId: 17,
              loopId: 8,
              candidateLoopId: 11,
              expectedPairState: {
                duplicate: { state: "bogus", confidence: 1, source: "human_review" },
                related: null,
              },
              restorePairState: {
                duplicate: null,
                related: null,
              },
            },
            successLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 17 }),
          },
        },
      },
    ]));

    const recent = readRecentShellActions();
    expect(recent).toHaveLength(1);
    expect(recent[0]?.outcome?.undoAction).toBeNull();
  });

  it("does not infer typed follow-through from stored receipt card actions", () => {
    window.localStorage.setItem("cloop.continuity.recent-actions.cache.v4", JSON.stringify([
      {
        kind: "planning",
        label: "Refreshed weekly reset",
        description: "The planning session was refreshed.",
        location: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
        occurredAt: "2026-03-17T12:00:00Z",
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
        },
      },
    ]));

    expect(readRecentShellActions()[0]?.outcome?.rerunAction).toBeNull();
  });

  it("keeps distinct receipts when the landed summaries differ", () => {
    recordRecentShellAction({
      kind: "working_set",
      label: "Pinned evidence",
      description: "Saved a resumable item.",
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
            rollbackLabel: "Remove the item to undo this.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "recall", recallTool: "rag", query: "evidence" }),
        rollbackLabel: "Remove the item to undo this.",
        undoAction: null,
      },
    });
    vi.setSystemTime(new Date("2026-03-17T12:00:10Z"));
    recordRecentShellAction({
      kind: "working_set",
      label: "Pinned evidence",
      description: "Saved a resumable item.",
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
            rollbackLabel: "Remove the item to undo this.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: location({ state: "recall", recallTool: "rag", query: "evidence" }),
        rollbackLabel: "Remove the item to undo this.",
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
