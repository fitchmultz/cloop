/**
 * http.test.ts - Regression tests for frontend HTTP error extraction.
 *
 * Purpose:
 *   Verify shared HTTP helpers preserve structured backend error details.
 *
 * Responsibilities:
 *   - Cover FastAPI-style error code extraction from JSON payloads.
 *   - Guard request callers that branch on HttpRequestError.code.
 *
 * Scope:
 *   - Pure frontend HTTP helper behavior with synthetic Response objects.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test -- src/http.test.ts`.
 *
 * Invariants/Assumptions:
 *   - Backend failures may encode machine-readable errors as detail.error.
 */

import { describe, expect, it } from "vitest";

import { extractErrorDetails } from "./http";

function jsonResponse(payload: unknown, status = 409): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("http error detail extraction", () => {
  it("extracts FastAPI detail.error as a structured error code", async () => {
    const details = await extractErrorDetails(
      jsonResponse({ detail: { error: "timer_already_active", message: "Timer already active" } }),
      "Fallback message",
    );

    expect(details).toEqual({
      message: "Timer already active",
      code: "timer_already_active",
    });
  });

  it("keeps extracting detail.code for existing backend payloads", async () => {
    const details = await extractErrorDetails(
      jsonResponse({ detail: { code: "no_active_timer", message: "No active timer" } }, 400),
      "Fallback message",
    );

    expect(details).toEqual({
      message: "No active timer",
      code: "no_active_timer",
    });
  });
});
