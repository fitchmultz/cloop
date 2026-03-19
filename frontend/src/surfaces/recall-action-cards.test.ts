/**
 * recall-action-cards.test.ts - Regression tests for recall surface action cards.
 *
 * Purpose:
 *   Verify recall surfaces build canonical action cards with preserved working-set
 *   scope and tool-specific guidance.
 *
 * Responsibilities:
 *   - Assert chat cards carry working-set-scoped recall locations.
 *   - Assert document cards change guidance when no indexed knowledge exists.
 *
 * Scope:
 *   - Pure card-building helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Card actions stay declarative and shell-routable.
 *   - Recall card copy remains deterministic for the same context.
 */

import { buildRecallActionCards } from "./recall-action-cards";

describe("buildRecallActionCards", () => {
  it("keeps working-set scope on chat recall actions", () => {
    const cards = buildRecallActionCards({
      tool: "chat",
      workingSetId: 9,
      chatGroundingSummary: "Loops · memory (10)",
    });

    expect(cards[0]?.actions[0]?.type).toBe("open");
    if (cards[0]?.actions[0]?.type === "open") {
      expect(cards[0].actions[0].location.workingSetId).toBe(9);
      expect(cards[0].actions[0].location.recallTool).toBe("chat");
    }
  });

  it("marks document recall as index-first when knowledge is missing", () => {
    const cards = buildRecallActionCards({
      tool: "rag",
      workingSetId: null,
      hasKnowledge: false,
    });

    expect(cards[0]?.title).toContain("Index evidence");
    expect(cards[0]?.trust.confidenceLabel).toBe("Index first");
  });
});
