/**
 * stream.test.ts - Regression tests for shared recall stream parsing.
 *
 * Purpose:
 *   Verify streamed recall parsing fails cleanly for terminal error events and
 *   incomplete streams.
 *
 * Responsibilities:
 *   - Assert terminal SSE error events raise the backend-authored message.
 *   - Assert streams without a terminal done event fail fast.
 *
 * Scope:
 *   - Browser-side SSE parsing only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend exec vitest run src/surfaces/stream.test.ts`.
 *
 * Invariants/Assumptions:
 *   - Tests run with a fetch-compatible Response implementation.
 *   - Recall streams must terminate with either `done` or `error`.
 */

import { describe, expect, it } from "vitest";

import { consumeJsonEventStream } from "./stream";

function streamResponse(body: string): Response {
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("consumeJsonEventStream", () => {
  it("throws the backend-authored message for terminal error events", async () => {
    const seenEvents: string[] = [];

    await expect(consumeJsonEventStream(
      streamResponse([
        'event: token',
        'data: {"token":"partial"}',
        "",
        'event: error',
        'data: {"error":{"message":"Primary selector became unavailable during streaming."}}',
        "",
      ].join("\n")),
      (eventName) => {
        seenEvents.push(eventName);
      },
    )).rejects.toThrow("Primary selector became unavailable during streaming.");

    expect(seenEvents).toEqual(["token"]);
  });

  it("rejects streams that end without a terminal done event", async () => {
    await expect(consumeJsonEventStream(
      streamResponse([
        'event: token',
        'data: {"token":"partial"}',
        "",
      ].join("\n")),
      () => {},
    )).rejects.toThrow("Streaming request ended before completion.");
  });
});
