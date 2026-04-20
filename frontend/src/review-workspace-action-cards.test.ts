/**
 * review-workspace-action-cards.test.ts - Regression tests for review action-card builders.
 *
 * Purpose:
 *   Verify review workspace card builders preserve working-set context and emit
 *   executable review-event actions through the shared card contract.
 *
 * Responsibilities:
 *   - Assert relationship impact cards encode review event actions.
 *   - Assert enrichment suggestion cards keep propagated working-set metadata.
 *
 * Scope:
 *   - Pure action-card shaping helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests operate on typed payload fragments only.
 *   - Working-set lookup stays deterministic for the same input arrays.
 */

import type {
  EnrichmentReviewQueueItemResponse,
  RelationshipReviewCandidateResponse,
  RelationshipReviewSessionSnapshotResponse,
  WorkingSetResponse,
} from "./domain";
import type { TrustSurfaceMetadata } from "./contracts-ui";
import type { PlanningExecutionHistoryItemResponse, PlanningExecutionLaunchSurfaceResponse } from "./domain";
import {
  buildEnrichmentSuggestionCard,
  buildPlanningExecutionReceiptCard,
  buildPlanningLaunchSurfaceCard,
  buildRelationshipImpactCard,
} from "./review-workspace-action-cards";

const workingSets: WorkingSetResponse[] = [
  {
    id: 7,
    name: "Hiring loop",
    description: "Current recruiting focus",
    item_count: 4,
    missing_item_count: 0,
    items: [],
  } as unknown as WorkingSetResponse,
];

const trust: TrustSurfaceMetadata = {
  generationLabel: "AI-assisted suggestion",
  contextSources: ["Saved session"],
  assumptions: ["Human review remains required."],
  confidenceLabel: "Ready",
  freshnessLabel: "Generated just now",
  rollbackLabel: "Explicit apply/reject",
};

function makeReviewRerunAction(
  reviewFocus: "relationship" | "enrichment",
  sessionId: number,
  sessionName: string,
) {
  return {
    label: reviewFocus === "relationship" ? "Refresh queue" : "Refresh enrichment",
    description: `Land back in the saved ${reviewFocus} queue with refreshed items and trust copy.`,
    rerun: {
      kind: "review_session",
      review_focus: reviewFocus,
      session_id: sessionId,
      session_name: sessionName,
    },
    contract: {
      mode: "refresh",
      provenance_label: `${sessionName} · status:open`,
      freshness_label: "Updated 2026-03-19T16:20:00Z",
      strategy_summary: `Reuse the saved review query and rebuild the current ${reviewFocus} queue from live state.`,
      strict_invariants: ["Same saved review session identity"],
      may_vary: ["Queue size and cursor target"],
      post_run: {
        summary: `Land back in the saved ${reviewFocus} queue with refreshed items and trust copy.`,
        location: {
          state: "decide",
          recall_tool: "chat",
          review_focus: reviewFocus,
          session_id: sessionId,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: null,
        },
      },
    },
  };
}

function makePlanningRerunAction(sessionId: number, sessionName: string) {
  return {
    label: "Refresh plan",
    description: "Land back in the saved planning session with refreshed checkpoints, trust metadata, and handoff cues.",
    rerun: {
      kind: "planning_session",
      session_id: sessionId,
      session_name: sessionName,
    },
    contract: {
      mode: "refresh",
      provenance_label: `Planning session: ${sessionName}`,
      freshness_label: "Updated 2026-03-19T16:30:00Z",
      strategy_summary: "Reuse the saved planning session and refresh it against current loop state.",
      strict_invariants: ["Same planning session identity"],
      may_vary: ["Checkpoint wording and emphasis"],
      post_run: {
        summary: "Land back in the saved planning session with refreshed checkpoints, trust metadata, and handoff cues.",
        location: {
          state: "plan",
          recall_tool: "chat",
          review_focus: "planning",
          session_id: sessionId,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: null,
        },
      },
    },
  };
}

describe("review-workspace-action-cards", () => {
  it("builds relationship impact cards with executable review actions", () => {
    const candidate = {
      id: 22,
      relationship_type: "duplicate",
      score: 0.97,
      raw_text: "Ship the launch checklist",
      raw_text_preview: "Ship the launch checklist",
      status: "actionable",
      tags: [],
      updated_at_utc: "2026-03-19T16:10:00Z",
    } as unknown as RelationshipReviewCandidateResponse;
    const snapshot = {
      session: {
        id: 11,
        name: "Duplicate review",
      },
      items: [candidate],
      rerun_action: makeReviewRerunAction("relationship", 11, "Duplicate review"),
    } as unknown as RelationshipReviewSessionSnapshotResponse;

    const card = buildRelationshipImpactCard({
      snapshot,
      candidate,
      recommendedDecision: "Confirming duplicate would consolidate the two loops.",
      recommendationTitle: "Confirm duplicate candidate",
      trust,
      selectedAction: null,
      context: {
        breadcrumbPrefix: ["Home", "Review"],
        fallbackWorkingSetId: 7,
        workingSets,
        sessionName: "Duplicate review",
        loopId: 5,
      },
    });

    expect(card.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(card.actions.some((action) => action.type === "event" && action.attributes["data-review-action"] === "relationship-confirm")).toBe(true);
    expect(card.actions.some((action) => action.type === "event" && action.attributes["data-review-action"] === "relationship-dismiss")).toBe(true);
    expect(card.actionContextLabel).toBe("Decision required");
    expect(card.actionWarning).toContain("not reversible");
    expect(card.handoff?.breadcrumbs).toContain("Relationship review");
    expect(card.handoff?.workingSet?.workingSetName).toBe("Hiring loop");
  });

  it("builds enrichment suggestion cards with shared working-set handoff metadata", () => {
    const suggestion = {
      id: 41,
      model: "test-model",
      parsed: {
        title: "Clarify interview prep",
        summary: "Tighten the prep checklist",
        next_action: "Confirm the interview panel",
      },
    } as unknown as EnrichmentReviewQueueItemResponse["pending_suggestions"][number];

    const card = buildEnrichmentSuggestionCard({
      suggestion,
      selectedAction: null,
      context: {
        breadcrumbPrefix: ["Home", "Review"],
        fallbackWorkingSetId: 7,
        workingSets,
        sessionName: "Enrichment review",
      },
    });

    expect(card.preview.some((item) => item.label === "next action")).toBe(true);
    expect(card.actions.some((action) => action.type === "event" && action.attributes["data-review-action"] === "enrichment-apply")).toBe(true);
    expect(card.actionContextLabel).toBe("Decision required");
    expect(card.actionWarning).toContain("mutates");
    expect(card.handoff?.breadcrumbs).toContain("Enrichment review");
    expect(card.handoff?.workingSet?.workingSetName).toBe("Hiring loop");
  });

  it("builds planning execution receipts from the shared follow-through fields", () => {
    const snapshot = {
      session: {
        id: 19,
        name: "Weekly reset",
      },
      rerun_action: makePlanningRerunAction(19, "Weekly reset"),
    } as unknown as import("./domain").PlanningSessionSnapshotResponse;
    const latestExecution = {
      run_id: 44,
      checkpoint_index: 1,
      checkpoint_title: "Create review queue",
      operation_count: 2,
      executed_at_utc: "2026-03-19T16:30:00Z",
      launch_surfaces: [],
      follow_up_resources: [],
      resource_change_summary: {
        total_change_count: 2,
        summary_label: "Created the downstream review queue.",
        downstream_summary_label: "1 downstream review queue is ready.",
        groups: [
          {
            resource_type: "relationship_review_session",
            resource_type_label: "Relationship review sessions",
            role: "follow_up_queue",
            role_label: "Follow-up queue",
            display_label: "Relationship review sessions · 1 queue",
            count: 1,
            resource_ids: [27],
            preview_labels: ["Relationship review queue"],
            operation_indexes: [0],
            operation_summaries: ["Created the downstream review queue."],
          },
        ],
        loop_groups: [],
        downstream_groups: [],
      },
      rollback: null,
      is_active: true,
      rollback_cues: {
        rollback_supported_operation_count: 1,
        undoable_operation_count: 1,
        rollback_action_count: 1,
        operations: [],
      },
      undo_action: {
        label: "Undo checkpoint",
        description: "Undo Create review queue and return the plan to its prior checkpoint state.",
        undo: {
          kind: "planning_run",
          session_id: 19,
          run_id: 44,
          checkpoint_index: 1,
          checkpoint_title: "Create review queue",
          action_count: 1,
          best_effort: false,
        },
        requires_confirmation: false,
        confirm_title: null,
        confirm_description: null,
        success_location: {
          state: "plan",
          review_focus: "planning",
          session_id: 19,
        },
      },
      results: [
        {
          rollback_actions: [
            {
              kind: "loop.undo",
              resource_type: "loop",
              resource_id: 31,
              summary: "Undo loop update for loop 31",
              payload: { loop_id: 31, expected_event_id: 88 },
            },
          ],
        },
      ],
      summary: null,
    } as unknown as import("./domain").PlanningExecutionHistoryItemResponse;

    const card = buildPlanningExecutionReceiptCard({
      snapshot,
      latestExecution,
      context: {
        breadcrumbPrefix: ["Home", "Plan"],
        fallbackWorkingSetId: 7,
        workingSets,
        sessionName: "Weekly reset",
      },
    });

    expect(card.kind).toBe("receipt");
    expect(card.summary).toBe("Created the downstream review queue.");
    expect(card.handoff?.createdResources).toContain("Relationship review sessions · 1 queue");
    expect(card.trust.rollbackLabel).toBe("1 operation is directly undoable.");
    expect(card.actions.some((action) => action.type === "open")).toBe(true);
    expect(card.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(card.actions.some((action) => action.type === "undo")).toBe(true);
  });

  it("builds planning launch cards with string session and working-set ids in the web payload", () => {
    const surface: PlanningExecutionLaunchSurfaceResponse = {
      resource_type: "review_session",
      resource_id: 55,
      surface: "review_session",
      label: "Relationship queue",
      reason: "Continue review",
      web: {
        surface: "review_session",
        review_kind: "relationship",
        session_id: "55",
        working_set_id: "7",
      },
    } as PlanningExecutionLaunchSurfaceResponse;
    const latestExecution = {
      checkpoint_index: 0,
      checkpoint_title: "Checkpoint",
      operation_count: 1,
      executed_at_utc: "2026-03-19T16:30:00Z",
      follow_up_resources: [],
      rollback_cues: null,
    } as unknown as PlanningExecutionHistoryItemResponse;

    const card = buildPlanningLaunchSurfaceCard(
      surface,
      latestExecution,
      {
        breadcrumbPrefix: ["Home", "Review"],
        fallbackWorkingSetId: 1,
        workingSets,
        sessionName: "Weekly reset",
      },
    );
    expect(card).not.toBeNull();
    const open = card!.actions.find((action) => action.type === "open" && action.label === "Open next queue");
    expect(open && open.type === "open").toBe(true);
    if (open && open.type === "open") {
      expect(open.location.sessionId).toBe(55);
      expect(open.location.workingSetId).toBe(7);
    }
  });
});
