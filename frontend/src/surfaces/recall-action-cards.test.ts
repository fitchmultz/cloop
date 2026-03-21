/**
 * recall-action-cards.test.ts - Regression tests for recall surface action cards.
 *
 * Purpose:
 *   Verify recall surfaces build canonical action cards with preserved working-set
 *   scope and richer stage/edit/defer follow-through for grounded results.
 *
 * Responsibilities:
 *   - Assert chat cards carry working-set-scoped recall locations.
 *   - Assert document cards change guidance when no indexed knowledge exists.
 *   - Guard inline recall result cards from regressing back to open/pin-only handoffs.
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

  it("builds in-thread chat result cards with stage/edit/defer follow-through", () => {
    const cards = buildRecallResultActionCards({
      tool: "chat",
      workingSetId: 9,
      chatPrompt: "What changed, what is blocked, and what should I do now?",
      answerSummary: "Focus on the missing-next-action loops first, then reopen the duplicate review queue.",
      sourceCount: 2,
      sourceLabels: ["/notes/review.md", "/notes/qa.md"],
      loopContextApplied: true,
      ragContextApplied: true,
      ragChunksUsed: 4,
    });

    expect(cards[0]?.title).toContain("Stage this grounded brief");
    expect(cards[0]?.actions.some((action) => action.type === "stage" && action.location.state === "do")).toBe(true);
    expect(cards[0]?.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(cards[0]?.actions.some((action) => action.type === "edit" && action.location.recallTool === "chat")).toBe(true);
    expect(cards[0]?.actions.some((action) => action.type === "defer" && action.location.state === "do")).toBe(true);
    expect(cards[1]?.title).toContain("source-backed follow-up");
    expect(cards[1]?.actions.some((action) => action.type === "stage" && action.location.recallTool === "rag")).toBe(true);
  });

  it("builds in-thread rag result cards with deterministic evidence follow-through", () => {
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

    expect(cards[0]?.actions.some((action) => action.type === "stage" && action.location.state === "recall")).toBe(true);
    expect(cards[0]?.actions.some((action) => action.type === "rerun")).toBe(true);
    expect(cards[0]?.actions.some((action) => action.type === "edit" && action.location.recallTool === "rag")).toBe(true);
    expect(cards[0]?.actions.some((action) => action.type === "defer" && action.location.recallTool === "rag")).toBe(true);
    expect(cards[1]?.actions.some((action) => action.type === "defer" && action.location.state === "do")).toBe(true);
  });

  it("renders inline answer-card decks with stage/edit/defer attributes", () => {
    const markup = renderRecallResultActionCards({
      tool: "chat",
      workingSetId: 12,
      chatPrompt: "What should I do next?",
      answerSummary: "Review the duplicate queue and then finish the top actionable loop.",
      sourceCount: 1,
      sourceLabels: ["/docs/review.md"],
      loopContextApplied: true,
      ragContextApplied: true,
    });

    expect(markup).toContain("recall-inline-action-card-deck");
    expect(markup).toContain("Grounded answer action cards");
    expect(markup).toContain('data-card-action="stage"');
    expect(markup).toContain('data-card-action="rerun"');
    expect(markup).toContain('data-card-action="edit"');
    expect(markup).toContain('data-card-action="defer"');
  });
});
