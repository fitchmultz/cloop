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
import {
  buildEnrichmentSuggestionCard,
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

    expect(card.actions.some((action) => action.type === "event" && action.attributes["data-review-action"] === "relationship-confirm")).toBe(true);
    expect(card.actions.some((action) => action.type === "event" && action.attributes["data-review-action"] === "relationship-dismiss")).toBe(true);
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
    expect(card.handoff?.workingSet?.workingSetName).toBe("Hiring loop");
  });
});
