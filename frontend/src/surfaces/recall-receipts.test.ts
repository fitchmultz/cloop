/**
 * recall-receipts.test.ts - Regression tests for recall mutation receipts.
 *
 * Purpose:
 *   Verify recall-side mutation receipts keep durable resume targets intact.
 *
 * Responsibilities:
 *   - Assert memory create/update receipts reopen the entry.
 *   - Assert memory delete falls back to the Memory surface.
 *   - Assert document ingestion keeps the Documents recall target.
 *
 * Scope:
 *   - Pure recall receipt-builder behavior only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Receipt helpers stay deterministic and frontend-only.
 *   - Working-set scope should remain visible through resume targets.
 */

import { describe, expect, it } from "vitest";

import { buildRecallIngestReceiptEntry, buildRecallMemoryReceiptEntry } from "./recall-receipts";

describe("recall-receipts", () => {
  it("reopens the saved memory entry after a recall memory mutation", () => {
    const entry = buildRecallMemoryReceiptEntry({
      action: "created",
      entry: { id: 41, key: "launch-preference", content: "Prefer concise summaries.", category: "preference", source: "user_stated" },
      workingSetId: 7,
      query: null,
    });

    expect(entry.outcome?.resumeLocation?.memoryId).toBe(41);
    expect(entry.outcome?.resumeLocation?.workingSetId).toBe(7);
    expect(entry.outcome?.card.preview.some((item) => item.value === "Working set #7")).toBe(true);
  });

  it("falls back to the Memory surface query after delete", () => {
    const entry = buildRecallMemoryReceiptEntry({
      action: "deleted",
      entry: { id: 8, key: null, content: "Old launch note", category: "context", source: "user_stated" },
      workingSetId: null,
      query: "launch",
    });

    expect(entry.outcome?.resumeLocation?.memoryId).toBeNull();
    expect(entry.outcome?.resumeLocation?.query).toBe("launch");
  });

  it("keeps the documents recall target on ingestion receipts", () => {
    const entry = buildRecallIngestReceiptEntry({
      path: "/tmp/launch-notes",
      mode: "add",
      recursive: true,
      result: { files: 3, chunks: 18, files_skipped: 0, failed_files: [] },
      workingSetId: 5,
      query: "what changed",
    });

    expect(entry.outcome?.resumeLocation?.recallTool).toBe("rag");
    expect(entry.outcome?.resumeLocation?.query).toBe("what changed");
    expect(entry.outcome?.card.title).toContain("Indexed knowledge");
    expect(entry.outcome?.card.preview.some((item) => item.value === "Working set #5")).toBe(true);
  });
});
