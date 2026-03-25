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
  EnrichmentReviewSessionSnapshotResponse,
  RelationshipReviewCandidateResponse,
  RelationshipReviewSessionSnapshotResponse,
  WorkingSetResponse,
} from "./domain";
import type { TrustSurfaceMetadata } from "./contracts-ui";
import {
  buildEnrichmentDecisionReceiptCard,
  buildEnrichmentSuggestionCard,
  buildPlanningExecutionReceiptCard,
  buildRelationshipDecisionReceiptCard,
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

  it("builds relationship decision receipts with resume and do actions", () => {
    const snapshot = {
      session: {
        id: 11,
        name: "Duplicate review",
        updated_at_utc: "2026-03-19T16:20:00Z",
      },
      loop_count: 6,
      current_index: 2,
      current_item: {
        loop: { id: 5, raw_text: "Ship launch checklist", title: null },
        duplicate_candidates: [],
        related_candidates: [],
      },
    } as unknown as RelationshipReviewSessionSnapshotResponse;
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

    const card = buildRelationshipDecisionReceiptCard({
      snapshot,
      trust,
      workingSets,
      sessionName: "Duplicate review",
      workingSetId: 7,
      loopId: 5,
      candidate,
      actionType: "confirm",
      relationshipType: "duplicate",
    });

    expect(card.kind).toBe("receipt");
    expect(card.actions.some((action) => action.type === "open" && action.label === "Resume queue")).toBe(true);
    expect(card.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(card.actions.some((action) => action.type === "open" && action.label === "Open affected loop in Do")).toBe(true);
    expect(card.handoff?.workingSet?.workingSetName).toBe("Hiring loop");
  });

  it("builds enrichment decision receipts with queue continuity", () => {
    const item = {
      loop: { id: 31, raw_text: "Prep candidate brief", title: "Prep candidate brief" },
      pending_suggestions: [],
      pending_clarification_count: 0,
    } as unknown as EnrichmentReviewQueueItemResponse;
    const snapshot = {
      session: {
        id: 15,
        name: "Enrichment review",
        updated_at_utc: "2026-03-19T16:25:00Z",
      },
      loop_count: 4,
      current_index: 1,
      current_item: item,
    } as unknown as EnrichmentReviewSessionSnapshotResponse;

    const card = buildEnrichmentDecisionReceiptCard({
      snapshot,
      trust,
      workingSets,
      sessionName: "Enrichment review",
      workingSetId: 7,
      item,
      suggestionId: 41,
      actionType: "apply",
      resultLoop: {
        ...(item.loop as unknown as import("./domain").LoopResponse),
        latest_reversible_event_id: 88,
        latest_reversible_event_type: "update",
      },
    });

    expect(card.kind).toBe("receipt");
    expect(card.summary).toContain("Applied suggestion #41");
    expect(card.actions.some((action) => action.type === "open" && action.label === "Resume queue")).toBe(true);
    expect(card.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(card.actions.some((action) => action.type === "undo")).toBe(true);
  });

  it("builds planning execution receipts with rollback cues", () => {
    const snapshot = {
      session: {
        id: 19,
        name: "Weekly reset",
      },
    } as unknown as import("./domain").PlanningSessionSnapshotResponse;
    const latestExecution = {
      run_id: 44,
      checkpoint_index: 1,
      checkpoint_title: "Create review queue",
      operation_count: 2,
      executed_at_utc: "2026-03-19T16:30:00Z",
      launch_surfaces: [],
      follow_up_resources: [],
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
      summary: { summary: "Created the downstream review queue." },
    } as unknown as import("./domain").PlanningExecutionHistoryItemResponse;

    const card = buildPlanningExecutionReceiptCard({
      snapshot,
      latestExecution,
      rollbackSummary: "1 operation is directly undoable.",
      context: {
        breadcrumbPrefix: ["Home", "Plan"],
        fallbackWorkingSetId: 7,
        workingSets,
        sessionName: "Weekly reset",
      },
    });

    expect(card.kind).toBe("receipt");
    expect(card.trust.rollbackLabel).toBe("1 operation is directly undoable.");
    expect(card.actions.some((action) => action.type === "open")).toBe(true);
    expect(card.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(card.actions.some((action) => action.type === "undo")).toBe(true);
  });
});
