/**
 * api.test.ts - Regression tests for surface transport helpers.
 *
 * Purpose:
 *   Verify surface-facing API helpers preserve backend response contracts used by
 *   browser work surfaces.
 *
 * Responsibilities:
 *   - Assert suggestion fetching unwraps the list response payload.
 *   - Assert suggestion mutations hit the canonical `/loops/suggestions/*` routes.
 *   - Guard the loop suggestion surface against transport-shape regressions.
 *
 * Scope:
 *   - Pure API helper behavior with mocked HTTP requests.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Backend suggestion endpoints return `{ suggestions, count }`.
 *   - Surface helpers should return the suggestion array only.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { requestJson } from "../http";
import { applySuggestion, captureLoop, fetchSuggestions, rejectSuggestion } from "./api";

vi.mock("../http", () => ({
  requestJson: vi.fn(),
  requestStream: vi.fn(),
  HttpRequestError: class HttpRequestError extends Error {},
}));

describe("surfaces/api", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("unwraps suggestion list responses for the suggestion surface", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce({
      count: 1,
      suggestions: [
        {
          id: 7,
          loop_id: 19,
          suggestion_json: '{"title":"Clarify launch date"}',
          parsed: { title: "Clarify launch date" },
          clarifications: [],
          model: "test-model",
          created_at: "2026-03-30 06:22:50",
          resolution: null,
          resolved_at: null,
          resolved_fields_json: null,
        },
      ],
    });

    await expect(fetchSuggestions(19, true)).resolves.toEqual([
      expect.objectContaining({ id: 7, loop_id: 19 }),
    ]);
    expect(requestJson).toHaveBeenCalledWith(
      expect.stringContaining("/loops/19/suggestions?pending_only=true"),
      {},
      "Failed to load suggestions",
    );
  });

  it("posts captures to the canonical loop capture route", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce({ id: 1, raw_text: "Task", status: "inbox", tags: [] });

    await captureLoop({
      raw_text: "Task",
      captured_at: "2026-04-27T16:00:00.000Z",
      client_tz_offset_min: 0,
      actionable: false,
      scheduled: false,
      blocked: false,
    });

    expect(requestJson).toHaveBeenCalledWith(
      "/loops/capture",
      {
        method: "POST",
        body: expect.objectContaining({
          raw_text: "Task",
          captured_at: "2026-04-27T16:00:00.000Z",
          client_tz_offset_min: 0,
        }),
      },
      "Capture failed",
    );
  });

  it("uses canonical loop-scoped suggestion mutation routes", async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true });

    await applySuggestion(7, ["title"]);
    await rejectSuggestion(7);

    expect(requestJson).toHaveBeenNthCalledWith(
      1,
      "/loops/suggestions/7/apply",
      { method: "POST", body: { fields: ["title"] } },
      "Failed to apply suggestion",
    );
    expect(requestJson).toHaveBeenNthCalledWith(
      2,
      "/loops/suggestions/7/reject",
      { method: "POST" },
      "Failed to reject suggestion",
    );
  });
});
