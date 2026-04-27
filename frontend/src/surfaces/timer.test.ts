/**
 * timer.test.ts - Regression tests for browser-side timer UI feedback.
 *
 * Purpose:
 *   Verify loop timer actions give immediate pending feedback, reconcile after
 *   API success, and surface action-scoped errors.
 *
 * Responsibilities:
 *   - Exercise Start/Stop focus UI state transitions in jsdom.
 *   - Guard stale backend-state recovery paths for timer mutations.
 *   - Ensure duplicate visible loop instances stay synchronized.
 *
 * Scope:
 *   - Frontend surface timer module only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test -- src/surfaces/timer.test.ts`.
 *
 * Invariants/Assumptions:
 *   - Timer buttons use data-action="timer-toggle" and data-id attributes.
 *   - Timer feedback slots use data-timer-feedback attributes.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpRequestError } from "../http";
import type { SurfaceTimeSessionResponse, SurfaceTimerStatusResponse } from "./contracts";

const mocks = vi.hoisted(() => ({
  startTimer: vi.fn(),
  stopTimer: vi.fn(),
  fetchTimerStatus: vi.fn(),
  refreshLoop: vi.fn(),
}));

vi.mock("./api", () => ({
  startTimer: mocks.startTimer,
  stopTimer: mocks.stopTimer,
  fetchTimerStatus: mocks.fetchTimerStatus,
}));

vi.mock("./loop", () => ({
  refreshLoop: mocks.refreshLoop,
}));

import { init, stopTimerUI, toggleTimer } from "./timer";

const activeSession: SurfaceTimeSessionResponse = {
  id: 55,
  loop_id: 7,
  started_at_utc: "2026-04-27T16:00:00.000Z",
  ended_at_utc: null,
  duration_seconds: null,
  notes: null,
  is_active: true,
};

const inactiveSession: SurfaceTimeSessionResponse = {
  ...activeSession,
  ended_at_utc: "2026-04-27T16:10:00.000Z",
  duration_seconds: 600,
  is_active: false,
};

const activeTimerStatus: SurfaceTimerStatusResponse = {
  active_session: activeSession,
  estimated_minutes: null,
  estimation_accuracy: null,
  has_active_session: true,
  loop_id: 7,
  total_tracked_minutes: 0,
  total_tracked_seconds: 0,
};

function requireElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Missing fixture element: ${selector}`);
  }
  return element;
}

function renderTimerFixture({ running = false } = {}): { button: HTMLButtonElement; feedback: HTMLElement; status: HTMLElement } {
  document.body.innerHTML = `
    <article class="loop-card next-card" data-loop-id="7">
      <button
        class="timer-btn next-card-focus-btn ${running ? "running" : ""}"
        data-action="timer-toggle"
        data-id="7"
        data-running="${running ? "true" : "false"}"
      >${running ? "⏹ Stop focus" : "▶ Start focus"}</button>
      <span class="timer-display ${running ? "active" : ""}" data-timer-display="7"></span>
      <span class="timer-feedback" data-timer-feedback="7" role="status" aria-live="polite"></span>
    </article>
    <div id="status"></div>
  `;
  const status = requireElement<HTMLElement>("#status");
  const button = requireElement<HTMLButtonElement>("button[data-action='timer-toggle']");
  const feedback = requireElement<HTMLElement>("[data-timer-feedback='7']");
  init({ status });
  return { button, feedback, status };
}

function renderTwoInstanceTimerFixture(): { buttons: HTMLButtonElement[]; displays: HTMLElement[] } {
  document.body.innerHTML = `
    <article class="loop-card next-card" data-loop-id="7">
      <button
        class="timer-btn next-card-focus-btn"
        data-action="timer-toggle"
        data-id="7"
        data-running="false"
      >▶ Start focus</button>
      <span class="timer-display" data-timer-display="7"></span>
      <span class="timer-feedback" data-timer-feedback="7" role="status" aria-live="polite"></span>
    </article>
    <article class="loop-card" data-loop-id="7">
      <button
        class="timer-btn"
        data-action="timer-toggle"
        data-id="7"
        data-running="false"
      >▶ Start</button>
      <span class="timer-display" data-timer-display="7"></span>
      <span class="timer-feedback" data-timer-feedback="7" role="status" aria-live="polite"></span>
    </article>
    <div id="status"></div>
  `;
  init({ status: requireElement<HTMLElement>("#status") });
  return {
    buttons: Array.from(document.querySelectorAll<HTMLButtonElement>("button[data-action='timer-toggle']")),
    displays: Array.from(document.querySelectorAll<HTMLElement>("[data-timer-display='7']")),
  };
}

describe("surfaces/timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-27T16:00:00.000Z"));
    mocks.refreshLoop.mockResolvedValue(undefined);
    mocks.fetchTimerStatus.mockResolvedValue(null);
  });

  afterEach(() => {
    stopTimerUI(7);
    document.body.innerHTML = "";
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("shows immediate pending feedback before a start request resolves", async () => {
    const { button, feedback } = renderTimerFixture();
    let resolveStart: (session: SurfaceTimeSessionResponse) => void = () => undefined;
    mocks.startTimer.mockReturnValueOnce(new Promise<SurfaceTimeSessionResponse>((resolve) => {
      resolveStart = resolve;
    }));

    const action = toggleTimer(7);

    expect(button.disabled).toBe(true);
    expect(button.classList.contains("pending")).toBe(true);
    expect(button.dataset["pending"]).toBe("starting");
    expect(button.textContent).toBe("Starting…");
    expect(feedback.textContent).toBe("Starting focus…");

    resolveStart(activeSession);
    await action;

    expect(button.disabled).toBe(false);
    expect(button.classList.contains("pending")).toBe(false);
    expect(button.classList.contains("running")).toBe(true);
    expect(button.textContent).toBe("⏹ Stop focus");
    expect(mocks.refreshLoop).toHaveBeenCalledWith(7);
  });

  it("updates elapsed display and reconciles after start success", async () => {
    const { button, status } = renderTimerFixture();
    mocks.startTimer.mockResolvedValueOnce(activeSession);

    await toggleTimer(7);

    const display = requireElement<HTMLElement>("[data-timer-display='7']");
    expect(button.dataset["running"]).toBe("true");
    expect(display.classList.contains("active")).toBe(true);
    expect(display.textContent).toBe("0s");
    expect(status.textContent).toBe("Timer started.");
    expect(mocks.refreshLoop).toHaveBeenCalledTimes(1);
    expect(mocks.refreshLoop).toHaveBeenCalledWith(7);
  });

  it("keeps running UI when start succeeds but reconciliation refresh fails", async () => {
    const { button, feedback, status } = renderTimerFixture();
    mocks.startTimer.mockResolvedValueOnce(activeSession);
    mocks.refreshLoop.mockRejectedValueOnce(new Error("Refresh unavailable"));

    await toggleTimer(7);

    const display = requireElement<HTMLElement>("[data-timer-display='7']");
    expect(button.disabled).toBe(false);
    expect(button.dataset["running"]).toBe("true");
    expect(button.textContent).toBe("⏹ Stop focus");
    expect(display.classList.contains("active")).toBe(true);
    expect(feedback.classList.contains("error")).toBe(true);
    expect(feedback.textContent).toBe("Refresh unavailable");
    expect(status.textContent).toBe("Refresh unavailable");
  });

  it("rolls back and shows inline error feedback when start fails", async () => {
    const { button, feedback, status } = renderTimerFixture();
    mocks.startTimer.mockRejectedValueOnce(new Error("Network down"));

    await toggleTimer(7);

    expect(button.disabled).toBe(false);
    expect(button.classList.contains("pending")).toBe(false);
    expect(button.classList.contains("running")).toBe(false);
    expect(button.dataset["running"]).toBe("false");
    expect(button.textContent).toBe("▶ Start focus");
    expect(feedback.classList.contains("error")).toBe(true);
    expect(feedback.textContent).toBe("Network down");
    expect(status.textContent).toBe("Network down");
  });

  it("recovers to running UI when the server reports an already-active timer", async () => {
    const { button, feedback, status } = renderTimerFixture();
    mocks.startTimer.mockRejectedValueOnce(new HttpRequestError("Already active", 409, "timer_already_active"));
    mocks.fetchTimerStatus.mockResolvedValueOnce(activeTimerStatus);

    await toggleTimer(7);

    expect(button.classList.contains("running")).toBe(true);
    expect(button.dataset["running"]).toBe("true");
    expect(button.textContent).toBe("⏹ Stop focus");
    expect(feedback.classList.contains("error")).toBe(false);
    expect(feedback.textContent).toBe("Timer was already running.");
    expect(status.textContent).toBe("Timer already running for this loop.");
    expect(mocks.refreshLoop).toHaveBeenCalledWith(7);
  });

  it("recovers to stopped UI when the server reports no active timer", async () => {
    const { button, feedback, status } = renderTimerFixture({ running: true });
    mocks.stopTimer.mockRejectedValueOnce(new HttpRequestError("No active timer", 400, "no_active_timer"));

    await toggleTimer(7);

    expect(button.disabled).toBe(false);
    expect(button.classList.contains("pending")).toBe(false);
    expect(button.classList.contains("running")).toBe(false);
    expect(button.dataset["running"]).toBe("false");
    expect(button.textContent).toBe("▶ Start focus");
    expect(feedback.classList.contains("error")).toBe(true);
    expect(feedback.textContent).toBe("Timer was already stopped.");
    expect(status.textContent).toBe("Timer was already stopped.");
    expect(mocks.refreshLoop).toHaveBeenCalledWith(7);
  });

  it("synchronizes all visible instances for a loop after start success", async () => {
    const { buttons, displays } = renderTwoInstanceTimerFixture();
    mocks.startTimer.mockResolvedValueOnce(activeSession);

    await toggleTimer(7);

    expect(buttons.map((button) => button.textContent)).toEqual(["⏹ Stop focus", "⏹ Stop"]);
    for (const button of buttons) {
      expect(button.dataset["running"]).toBe("true");
      expect(button.classList.contains("running")).toBe(true);
    }
    for (const display of displays) {
      expect(display.classList.contains("active")).toBe(true);
      expect(display.textContent).toBe("0s");
    }
  });

  it("keeps the focused Do card running if reconciliation re-renders another stale instance", async () => {
    const { buttons } = renderTwoInstanceTimerFixture();
    const focusedButton = buttons[0];
    if (!focusedButton) {
      throw new Error("Missing focused timer button fixture");
    }
    mocks.startTimer.mockResolvedValueOnce(activeSession);
    mocks.refreshLoop.mockImplementationOnce(() => {
      focusedButton.classList.remove("running");
      focusedButton.dataset["running"] = "false";
      focusedButton.textContent = "▶ Start focus";
      return Promise.resolve();
    });

    await toggleTimer(7);

    expect(buttons.map((button) => button.textContent)).toEqual(["⏹ Stop focus", "⏹ Stop"]);
    for (const button of buttons) {
      expect(button.dataset["running"]).toBe("true");
      expect(button.classList.contains("running")).toBe(true);
    }
  });

  it("suppresses duplicate clicks while start is pending", async () => {
    renderTimerFixture();
    let resolveStart: (session: SurfaceTimeSessionResponse) => void = () => undefined;
    mocks.startTimer.mockReturnValueOnce(new Promise<SurfaceTimeSessionResponse>((resolve) => {
      resolveStart = resolve;
    }));

    const firstAction = toggleTimer(7);
    await toggleTimer(7);

    expect(mocks.startTimer).toHaveBeenCalledTimes(1);

    resolveStart(activeSession);
    await firstAction;
  });

  it("stops a running timer and refreshes the loop after success", async () => {
    const { button, status } = renderTimerFixture({ running: true });
    mocks.stopTimer.mockResolvedValueOnce(inactiveSession);

    await toggleTimer(7);

    expect(button.classList.contains("running")).toBe(false);
    expect(button.dataset["running"]).toBe("false");
    expect(button.textContent).toBe("▶ Start focus");
    expect(status.textContent).toBe("Timer stopped: 10m 00s");
    expect(mocks.refreshLoop).toHaveBeenCalledWith(7);
  });

  it("keeps stopped UI when stop succeeds but reconciliation refresh fails", async () => {
    const { button, feedback, status } = renderTimerFixture({ running: true });
    mocks.stopTimer.mockResolvedValueOnce(inactiveSession);
    mocks.refreshLoop.mockRejectedValueOnce(new Error("Refresh unavailable"));

    await toggleTimer(7);

    expect(button.disabled).toBe(false);
    expect(button.classList.contains("running")).toBe(false);
    expect(button.dataset["running"]).toBe("false");
    expect(button.textContent).toBe("▶ Start focus");
    expect(feedback.classList.contains("error")).toBe(true);
    expect(feedback.textContent).toBe("Refresh unavailable");
    expect(status.textContent).toBe("Refresh unavailable");
  });

  it("restores running UI and shows inline error feedback when stop fails generically", async () => {
    const { button, feedback, status } = renderTimerFixture({ running: true });
    mocks.stopTimer.mockRejectedValueOnce(new Error("Stop request failed"));

    await toggleTimer(7);

    expect(button.disabled).toBe(false);
    expect(button.classList.contains("pending")).toBe(false);
    expect(button.classList.contains("running")).toBe(true);
    expect(button.dataset["running"]).toBe("true");
    expect(button.textContent).toBe("⏹ Stop focus");
    expect(feedback.classList.contains("error")).toBe(true);
    expect(feedback.textContent).toBe("Stop request failed");
    expect(status.textContent).toBe("Stop request failed");
  });
});
