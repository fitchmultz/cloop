/**
 * suggestion-receipts.test.ts - Regression tests for suggestion-surface receipts.
 *
 * Purpose:
 *   Verify answer-only clarification submissions emit reversible shared receipt
 *   outcomes for recent history and command-palette reuse.
 *
 * Responsibilities:
 *   - Assert direct clarification answers land as receipt outcomes.
 *   - Assert the shared clarification-answer undo action is attached.
 *   - Guard the loop resume target and workflow-thread contract.
 *
 * Scope:
 *   - Pure receipt-builder behavior for suggestion-surface clarification flows.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Answer-only clarification submissions remain reversible.
 *   - Receipt cards should reopen the affected loop.
 */

import { describe, expect, it } from "vitest";

import { buildClarificationAnswerReceiptEntry } from "./suggestion-receipts";

describe("suggestion-receipts", () => {
  it("builds a receipt outcome with clarification-answer undo for direct answers", () => {
    const entry = buildClarificationAnswerReceiptEntry({
      loop: {
        id: 19,
        title: "Clarify launch date",
        raw_text: "Clarify launch date",
      },
      result: {
        loop_id: 19,
        answered_count: 2,
        clarifications: [
          {
            id: 7,
            loop_id: 19,
            question: "When should this happen?",
            answer: "Friday",
            answered_at: "2026-03-29T18:10:00Z",
            created_at: "2026-03-29T18:00:00Z",
          },
          {
            id: 11,
            loop_id: 19,
            question: "Who owns this?",
            answer: "Mitch",
            answered_at: "2026-03-29T18:11:00Z",
            created_at: "2026-03-29T18:01:00Z",
          },
        ],
        superseded_suggestion_ids: [44],
        message: "Clarifications recorded. Re-enrich to generate an updated suggestion.",
      },
    });

    expect(entry.kind).toBe("review");
    expect(entry.outcome?.card.title).toBe("Saved 2 clarification answers for Clarify launch date");
    expect(entry.outcome?.undoAction?.undo).toEqual({
      kind: "clarification_answer",
      loopId: 19,
      clarificationIds: [7, 11],
    });
    expect(entry.outcome?.resumeLocation).toMatchObject({
      state: "do",
      loopId: 19,
    });
    expect(entry.outcome?.card.preview).toContainEqual({ label: "Superseded suggestions", value: "1" });
    expect(entry.outcome?.workflowThread).toEqual({
      id: "clarification-answer:loop:19",
      kind: "ad_hoc",
      title: "Saved 2 clarification answers for Clarify launch date",
      summary: "Clarifications recorded. Re-enrich to generate an updated suggestion.",
      parentOutcomeId: null,
    });
  });
});
