/**
 * utils.test.ts - Focused regression tests for shared surface utilities.
 *
 * Purpose:
 *   Guard the manual-QA hardening around due-date input formatting and
 *   actionable knowledge-ingest failure messaging.
 *
 * Responsibilities:
 *   - Assert digit-only due-date typing still auto-formats predictably.
 *   - Assert pasted ISO due dates are preserved until normalization.
 *   - Assert embedding-provider guidance stays actionable on generic ingest failures.
 *
 * Scope:
 *   - Pure utility behavior only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend exec vitest run src/surfaces/utils.test.ts`.
 *
 * Invariants/Assumptions:
 *   - Due-date display formatting remains MM/DD/YYYY.
 *   - Generic ingest failures should become provider-specific guidance when health data is available.
 */

import { describe, expect, it } from "vitest";

import { describeKnowledgeIngestError, formatDateInputValue, INVALID_DUE_DATE_MESSAGE } from "./utils";

describe("surface utils", () => {
  it("auto-formats digit-only due-date input", () => {
    expect(formatDateInputValue("03292026")).toBe("03/29/2026");
  });

  it("preserves pasted ISO dates until blur-time normalization", () => {
    expect(formatDateInputValue("2026-03-29")).toBe("2026-03-29");
  });

  it("turns generic Ollama ingest failures into actionable guidance", () => {
    expect(
      describeKnowledgeIngestError(new Error("Unexpected server error"), { embed_model: "ollama/nomic-embed-text" }),
    ).toContain("Start Ollama");
  });

  it("preserves specific ingest error messages", () => {
    expect(
      describeKnowledgeIngestError(new Error("Path does not exist"), { embed_model: "ollama/nomic-embed-text" }),
    ).toBe("Path does not exist");
  });

  it("keeps the shared due-date validation copy stable", () => {
    expect(INVALID_DUE_DATE_MESSAGE).toBe("Enter a valid due date as MM/DD/YYYY.");
  });
});
