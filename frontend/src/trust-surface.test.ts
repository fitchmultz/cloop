/**
 * trust-surface.test.ts - Regression tests for shared trust-surface rendering.
 *
 * Purpose:
 *   Verify the shared trust presentation layer renders core trust signals and
 *   respects compact-density settings.
 *
 * Responsibilities:
 *   - Assert summary trust signals render consistently.
 *   - Assert context and assumptions render when requested.
 *   - Guard compact mode from accidentally re-expanding hidden list sections.
 *
 * Scope:
 *   - Pure trust-surface HTML rendering helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests operate on HTML-string output without a DOM.
 *   - Shared trust rendering stays deterministic for identical inputs.
 */

import { renderTrustSurface } from "./trust-surface";

describe("renderTrustSurface", () => {
  const metadata = {
    generationLabel: "AI-assisted queue",
    contextSources: ["Saved query: status:open", "Model: test-model"],
    assumptions: ["Human review remains required."],
    confidenceLabel: "High-confidence review signal",
    freshnessLabel: "Generated 2 minutes ago",
    rollbackLabel: "No mutation until confirmation",
    impactSummary: "Applying the suggestion updates summary and next action.",
  };

  it("renders core trust signals, context, assumptions, and impact", () => {
    const html = renderTrustSurface(metadata, {
      variant: "detail",
      title: "Trust surface",
      showContextLists: true,
    });

    expect(html).toContain("Mode");
    expect(html).toContain("AI-assisted queue");
    expect(html).toContain("Context used");
    expect(html).toContain("Saved query: status:open");
    expect(html).toContain("Assumptions");
    expect(html).toContain("Human review remains required.");
    expect(html).toContain("Impact");
    expect(html).toContain("Applying the suggestion updates summary and next action.");
  });

  it("keeps compact mode calm when context lists are disabled", () => {
    const html = renderTrustSurface(metadata, {
      variant: "compact",
      showContextLists: false,
    });

    expect(html).toContain("AI-assisted queue");
    expect(html).toContain("Generated 2 minutes ago");
    expect(html).not.toContain("Context used");
    expect(html).not.toContain("Assumptions");
  });
});
