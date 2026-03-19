/**
 * operator-action-cards.test.ts - Regression tests for shared action-card rendering.
 *
 * Purpose:
 *   Verify the canonical action-card renderer supports open, pin, and custom
 *   event actions without losing the shared trust and handoff anatomy.
 *
 * Responsibilities:
 *   - Assert event-style action buttons keep their custom data attributes.
 *   - Guard shared card rendering from dropping trust or handoff sections.
 *
 * Scope:
 *   - Pure HTML-string rendering only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Button attributes remain declarative so shell/review handlers can attach
 *     behavior outside the renderer.
 *   - Rendered HTML stays deterministic for the same card payload.
 */

import type { OperatorActionCard } from "./contracts-ui";
import { renderActionCardDeck } from "./operator-action-cards";

describe("renderActionCardDeck", () => {
  it("renders event actions alongside trust and handoff content", () => {
    const cards: OperatorActionCard[] = [
      {
        id: "decision-1",
        kind: "decision",
        tone: "attention",
        eyebrow: "Review",
        title: "Apply the top suggestion",
        summary: "A structured suggestion is ready for review.",
        rationale: "Action cards keep the next mutation explicit and local to the queue.",
        preview: [{ label: "Loop", value: "Weekly reset" }],
        trust: {
          contextSources: ["Saved enrichment session", "Model: test-model"],
          assumptions: ["Human review remains required before mutating the loop."],
          confidenceLabel: "Structured suggestion ready",
          freshnessLabel: "Generated 2 minutes ago",
          rollbackLabel: "Apply or reject remains explicit",
        },
        handoff: {
          changeSummary: "Applying this suggestion updates the loop inside the current queue.",
          createdResources: [],
          nextStep: "Apply, reject, or inspect the loop in Do.",
          breadcrumbs: ["Home", "Review", "Enrichment queue"],
        },
        actionContextLabel: "Decision required",
        actionWarning: "Applying this suggestion mutates loop fields immediately.",
        actions: [
          {
            type: "event",
            label: "Apply",
            variant: "primary",
            description: "Apply the top suggestion",
            attributes: {
              "data-review-action": "enrichment-apply",
              "data-suggestion-id": "42",
            },
          },
        ],
      },
    ];

    const html = renderActionCardDeck(cards, "<p>Empty</p>");

    expect(html).toContain('data-review-action="enrichment-apply"');
    expect(html).toContain('data-suggestion-id="42"');
    expect(html).toContain("Decision required");
    expect(html).toContain("mutates loop fields immediately");
    expect(html).toContain("Trust surface");
    expect(html).toContain("Workflow handoff");
  });
});
