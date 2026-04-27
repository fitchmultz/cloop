/**
 * next.test.ts - Regression tests for Do-surface focused-loop rendering.
 *
 * Purpose:
 *   Verify focused Do-loop rendering preserves timer state during timer-status
 *   reconciliation edge cases.
 *
 * Responsibilities:
 *   - Exercise focused-loop timer hydration behavior in jsdom.
 *   - Guard against rendering a running loop as stopped when status hydration
 *     is unavailable.
 *
 * Scope:
 *   - Frontend next/do surface module only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test -- src/surfaces/next.test.ts`.
 *
 * Invariants/Assumptions:
 *   - api.fetchTimerStatus returns null when timer-status hydration fails.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SurfaceLoop, SurfaceTimerStatusResponse } from "./contracts";

const mocks = vi.hoisted(() => ({
  fetchLoop: vi.fn(),
  fetchTimerStatus: vi.fn(),
  fetchNextLoops: vi.fn(),
  searchLoops: vi.fn(),
}));

vi.mock("./api", () => ({
  fetchLoop: mocks.fetchLoop,
  fetchTimerStatus: mocks.fetchTimerStatus,
  fetchNextLoops: mocks.fetchNextLoops,
  searchLoops: mocks.searchLoops,
}));

import { init, loadFocusedLoop } from "./next";

const baseLoop: SurfaceLoop = {
  captured_at_utc: "2026-04-27T16:00:00.000Z",
  captured_tz_offset_min: 0,
  created_at_utc: "2026-04-27T16:00:00.000Z",
  id: 7,
  raw_text: "Focus the timer bug",
  status: "actionable",
  tags: [],
  title: "Focus the timer bug",
  updated_at_utc: "2026-04-27T16:00:00.000Z",
};

const inactiveTimerStatus: SurfaceTimerStatusResponse = {
  active_session: null,
  estimated_minutes: null,
  estimation_accuracy: null,
  has_active_session: false,
  loop_id: 7,
  total_tracked_minutes: 12,
  total_tracked_seconds: 720,
};

function setupFocusedSurface(): HTMLElement {
  document.body.innerHTML = `
    <input id="do-query-filter" value="" />
    <section id="next-buckets"></section>
  `;
  const nextBuckets = document.querySelector<HTMLElement>("#next-buckets");
  const nextQueryFilter = document.querySelector<HTMLInputElement>("#do-query-filter");
  if (!nextBuckets || !nextQueryFilter) {
    throw new Error("Failed to build focused Do surface fixture");
  }
  init({ nextBuckets, nextQueryFilter });
  return nextBuckets;
}

describe("surfaces/next focused loop timer hydration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-27T16:01:00.000Z"));
  });

  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("preserves existing running timer fields when timer-status hydration is unavailable", async () => {
    const nextBuckets = setupFocusedSurface();
    mocks.fetchLoop.mockResolvedValueOnce({
      ...baseLoop,
      timer_display: "1m 00s",
      timer_running: true,
      total_tracked_minutes: 3,
    });
    mocks.fetchTimerStatus.mockResolvedValueOnce(null);

    await loadFocusedLoop(7);

    const button = nextBuckets.querySelector<HTMLButtonElement>("button[data-action='timer-toggle']");
    const display = nextBuckets.querySelector<HTMLElement>("[data-timer-display='7']");
    expect(button?.dataset["running"]).toBe("true");
    expect(button?.textContent?.trim()).toBe("⏹ Stop focus");
    expect(display?.textContent).toBe("1m 00s");
    expect(display?.classList.contains("active")).toBe(true);
  });

  it("clears focused timer fields when canonical timer status says the loop is stopped", async () => {
    const nextBuckets = setupFocusedSurface();
    mocks.fetchLoop.mockResolvedValueOnce({
      ...baseLoop,
      timer_display: "1m 00s",
      timer_running: true,
      total_tracked_minutes: 3,
    });
    mocks.fetchTimerStatus.mockResolvedValueOnce(inactiveTimerStatus);

    await loadFocusedLoop(7);

    const button = nextBuckets.querySelector<HTMLButtonElement>("button[data-action='timer-toggle']");
    const display = nextBuckets.querySelector<HTMLElement>("[data-timer-display='7']");
    expect(button?.dataset["running"]).toBe("false");
    expect(button?.textContent?.trim()).toBe("▶ Start focus");
    expect(display?.textContent).toBe("");
    expect(display?.classList.contains("active")).toBe(false);
  });
});
