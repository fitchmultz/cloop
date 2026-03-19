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

import {
  buildRecallActionCards,
  buildRecallResultActionCards,
  renderRecallResultActionCards,
} from "./recall-action-cards";

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

  it("builds in-thread chat result cards with execution and evidence handoffs", () => {
    const cards = buildRecallResultActionCards({
      tool: "chat",
      workingSetId: 9,
      answerSummary: "Focus on the missing-next-action loops first, then reopen the duplicate review queue.",
      sourceCount: 2,
      sourceLabels: ["/notes/review.md", "/notes/qa.md"],
      loopContextApplied: true,
      ragContextApplied: true,
      ragChunksUsed: 4,
    });

    expect(cards[0]?.title).toContain("Open Do");
    expect(cards[0]?.actionContextLabel).toBe("Next action");
    expect(cards[1]?.title).toContain("source-backed context");
  });

  it("builds in-thread rag result cards that hand off into chat", () => {
    const cards = buildRecallResultActionCards({
      tool: "rag",
      workingSetId: null,
      ragQuestion: "What changed in the operator workflow?",
      answerSummary: "The operator workflow now surfaces clear queue health and decision-required cues.",
      sourceCount: 1,
      sourceLabels: ["/docs/operator.md"],
      ragContextApplied: true,
      ragChunksUsed: 2,
    });

    expect(cards[0]?.actions[0]?.type).toBe("open");
    expect(cards[0]?.summary).toContain("grounded chat");
    expect(cards[1]?.title).toContain("Open Do");
  });

  it("renders inline answer-card decks with the shared deck wrapper", () => {
    const markup = renderRecallResultActionCards({
      tool: "chat",
      workingSetId: 12,
      answerSummary: "Review the duplicate queue and then finish the top actionable loop.",
      sourceCount: 1,
      sourceLabels: ["/docs/review.md"],
      loopContextApplied: true,
      ragContextApplied: true,
    });

    expect(markup).toContain("recall-inline-action-card-deck");
    expect(markup).toContain("Grounded answer action cards");
    expect(markup).toContain("Open Do with this grounded brief");
  });
});
