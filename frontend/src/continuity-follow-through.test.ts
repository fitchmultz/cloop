/**
 * continuity-follow-through.test.ts - Regression tests for backend-authored continuity summaries.
 *
 * Purpose:
 *   Verify the shared frontend follow-through helpers consume the canonical
 *   backend workflow-summary feed without re-ranking it locally.
 *
 * Responsibilities:
 *   - Assert hydrated workflow summaries stay ordered by backend rank.
 *   - Assert representative receipt cards, rerun actions, and undo actions reattach.
 *   - Assert recovery lookup reads from backend-authored summary targets.
 *
 * Scope:
 *   - Frontend continuity-summary hydration and lookup helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Backend workflow summaries are the only ranking truth.
 *   - Durable recent actions remain the source of representative receipt cards.
 */

import type { ShellLocationContract } from "./contracts-ui";
import {
  hydrateDurableContinuityState,
  markContinuityRecoveryAcknowledged,
} from "./continuity-intelligence";
import {
  findRecoveryPlanForLocation,
  readRankedWorkflowSummaries,
} from "./continuity-follow-through";
import {
  buildPrimaryRecommendationDigestCard,
  derivePrimaryRecommendation,
} from "./continuity-recommendations";

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

function continuitySnapshot() {
  return {
    recorded_at_utc: "2026-03-20T12:00:00Z",
    outcomes: [
      {
        id: 9,
        kind: "planning",
        label: "Created launch review queue",
        description: "The enrichment queue is ready to resume.",
        occurred_at_utc: "2026-03-20T11:55:00Z",
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
          handoff: {
            change_summary: "Queue created.",
            created_resources: ["Launch enrichment queue"],
            next_step: "Open the queue.",
            breadcrumbs: ["Home", "Plan"],
            working_set: {
              working_set_id: 7,
              working_set_name: "Launch Prep",
              item_count: 5,
              missing_item_count: 0,
            },
          },
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
          success_location: {
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
              location: {
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
    anchors: {
      planning: null,
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
        representative_outcome_id: 9,
        latest_outcome_id: 9,
        occurred_at_utc: "2026-03-20T11:55:00Z",
        outcome_count: 2,
        outcome_preview_titles: ["Created launch review queue", "Updated launch queue filters"],
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
          handoff: {
            change_summary: "Queue created.",
            created_resources: ["Launch enrichment queue"],
            next_step: "Open the queue.",
            breadcrumbs: ["Home", "Plan"],
            working_set: {
              working_set_id: 7,
              working_set_name: "Launch Prep",
              item_count: 5,
              missing_item_count: 0,
            },
          },
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
          success_location: {
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
              location: {
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
            },
          },
        },
        working_set_id: 7,
        degraded: false,
        degraded_label: null,
        why_now: [
          "This workflow has fresh unseen movement.",
          "It stays inside the active working set.",
        ],
        changed_since_last_seen: [
          "This workflow has never been seen from durable continuity.",
          "2 outcomes are grouped under this workflow thread.",
        ],
        prior_state: null,
      },
      {
        id: "planning:99",
        source: "anchor",
        rank: 3300,
        ranking_signals: {
          drift_severity: "gone",
          drift_score: 100,
          working_set_relevant: false,
          downstream_ready: false,
          degraded: true,
          recency_tie_breaker: 16,
        },
        workflow_thread: {
          id: "planning:99",
          kind: "planning_checkpoint",
          title: "Replacement plan",
          summary: "Replacement planning thread",
          parent_outcome_id: null,
        },
        representative_outcome_id: null,
        latest_outcome_id: null,
        occurred_at_utc: "2026-03-20T11:50:00Z",
        outcome_count: 1,
        outcome_preview_titles: ["Replacement plan"],
        requested_resume_location: {
          state: "plan",
          recall_tool: "chat",
          review_focus: "planning",
          session_id: 99,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: null,
        },
        resolved_resume: {
          requested_location: {
            state: "plan",
            recall_tool: "chat",
            review_focus: "planning",
            session_id: 99,
            loop_id: null,
            view_id: null,
            memory_id: null,
            working_set_id: null,
            query: null,
          },
          resolved_location: {
            state: "operator",
            recall_tool: "chat",
            review_focus: null,
            session_id: null,
            loop_id: null,
            view_id: null,
            memory_id: null,
            working_set_id: null,
            query: null,
          },
          status: "home_fallback",
          message: "Original landed target is unavailable, so continuity falls back to home.",
          successor: null,
        },
        display_title: "Replacement plan",
        display_summary: "Return to the surviving workflow.",
        display_card: {
          kind: "handoff",
          tone: "attention",
          eyebrow: "Resume anchor",
          title: "Replacement plan",
          summary: "Return to the surviving workflow.",
          rationale: "This card is rendered from the canonical backend continuity summary instead of client-side ranking heuristics.",
          preview: [
            {
              label: "Why now",
              value: "The prior landing target disappeared, so this is the safest surviving path.",
            },
            {
              label: "Changed",
              value: "This workflow has never been seen from durable continuity.",
            },
          ],
          trust: {
            generation_label: "Backend continuity summary",
            generation_tone: "neutral",
            context_sources: ["Durable continuity workflow summary"],
            assumptions: [],
            confidence_label: "Deterministic continuity ranking",
            confidence_tone: "progress",
            freshness_label: "Updated 2026-03-20T11:50:00Z",
            freshness_tone: "neutral",
            rollback_label: null,
            rollback_tone: "neutral",
            impact_summary: "The prior landing target disappeared, so this is the safest surviving path. · This workflow has never been seen from durable continuity.",
            impact_tone: "neutral",
          },
          handoff: {
            change_summary: "This workflow has never been seen from durable continuity.",
            created_resources: ["Replacement plan"],
            next_step: "Open the ranked workflow and continue from the durable landed state.",
            breadcrumbs: ["Home", "Since last visit", "Replacement plan"],
            working_set: null,
          },
          action_context_label: "Continue from here",
          action_warning: "Original landed target is unavailable, so continuity falls back to home.",
        },
        working_set_id: null,
        degraded: true,
        degraded_label: "Original landed target is unavailable, so continuity falls back to home.",
        why_now: ["The prior landing target disappeared, so this is the safest surviving path."],
        changed_since_last_seen: ["This workflow has never been seen from durable continuity."],
        prior_state: {
          kind: "gone",
          title: "Prior path",
          summary: "The prior primary path is no longer available.",
        },
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
      },
      {
        id: "planning:99",
        title: "Replacement plan needs a recovery decision",
        body: "The prior landing target disappeared, so this is the safest surviving path. · This workflow has never been seen from durable continuity.",
        severity: "alert",
        workflow_thread: {
          id: "planning:99",
          kind: "planning_checkpoint",
          title: "Replacement plan",
          summary: "Replacement planning thread",
          parent_outcome_id: null,
        },
        resolved_location: {
          state: "operator",
          recall_tool: "chat",
          review_focus: null,
          session_id: null,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: null,
        },
      },
    ],
    last_seen_markers: [],
    recovery_acknowledgements: [],
  };
}

let originalLocalStorage: Storage;
let originalFetch: typeof fetch;

describe("readRankedWorkflowSummaries", () => {
  beforeEach(() => {
    originalLocalStorage = window.localStorage as Storage;
    originalFetch = globalThis.fetch;
    Object.defineProperty(window, "localStorage", {
      value: createMemoryStorage(),
      configurable: true,
      writable: true,
    });
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(continuitySnapshot()), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  });

  afterEach(() => {
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    globalThis.fetch = originalFetch;
  });

  it("hydrates backend-ranked workflow summaries in backend order", async () => {
    await hydrateDurableContinuityState();

    const summaries = readRankedWorkflowSummaries();
    expect(summaries).toHaveLength(2);
    expect(summaries[0]?.id).toBe("planning:41:checkpoint:0");
    expect(summaries[0]?.whyNow[0]).toBe("This workflow has fresh unseen movement.");
    expect(summaries[1]?.id).toBe("planning:99");
  });

  it("hydrates backend-owned display, undo, and rerun actions onto ranked workflow cards", async () => {
    await hydrateDurableContinuityState();

    const summary = readRankedWorkflowSummaries()[0]!;
    expect(summary.card.title).toBe("Created launch review queue");
    expect(summary.card.rationale).toBe("Receipt");
    expect(summary.undoAction?.type).toBe("undo");
    expect(summary.rerunAction?.type).toBe("rerun");
    expect(summary.card.actions[0]?.type).toBe("open");
    expect(summary.card.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(summary.card.actions.some((action) => action.type === "undo")).toBe(true);
  });

  it("finds recovery plans from backend summary targets and durable acknowledgements", async () => {
    await hydrateDurableContinuityState();

    let recovery = findRecoveryPlanForLocation(readRankedWorkflowSummaries(), {
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
      workflowThreadId: "planning:99",
    });
    expect(recovery?.acknowledged).toBe(false);
    expect(recovery?.kind).toBe("home_fallback");

    markContinuityRecoveryAcknowledged(recovery!.key);
    recovery = findRecoveryPlanForLocation(readRankedWorkflowSummaries(), {
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
      workflowThreadId: "planning:99",
    });
    expect(recovery?.acknowledged).toBe(true);
  });

  it("builds one canonical notification and digest from the primary recommendation", async () => {
    await hydrateDurableContinuityState();

    const recommendation = derivePrimaryRecommendation(readRankedWorkflowSummaries());
    expect(recommendation).not.toBeNull();

    const notification = recommendation!.notification;
    expect(notification.resolvedLocation.state).toBe("decide");
    expect(notification.title).toBe("Created launch review queue is ready in your working set");
    expect(notification.body).toContain("This workflow has fresh unseen movement.");

    const digest = buildPrimaryRecommendationDigestCard(recommendation!);
    expect(digest.title).toBe("Why this workflow became the top recommendation");
    expect(digest.summary).toBe(notification.body);
  });
});
