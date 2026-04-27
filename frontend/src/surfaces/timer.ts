/**
 * timer.ts - Browser-side loop timer functionality.
 *
 * Purpose:
 *   Manage time tracking for loops with start/stop functionality and live timer
 *   display updates.
 *
 * Responsibilities:
 *   - Load/start/stop timer API flows.
 *   - Keep all visible timer buttons, feedback, and elapsed-time UI synchronized.
 *   - Track active timer intervals in browser state.
 *
 * Scope:
 *   - Capture/do loop timer behavior only.
 *
 * Usage:
 *   - Imported by loop.ts and bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - frontend/src/surfaces/state.ts owns active browser timer records.
 *   - Timer buttons use data-action="timer-toggle" and data-id attributes.
 *   - Timer feedback slots use data-timer-feedback attributes.
 */

import { HttpRequestError } from "../http";
import * as api from "./api";
import * as state from "./state";
import type { SurfaceTimeSessionResponse, SurfaceTimerStatusResponse } from "./contracts";
import { formatDuration } from "./render";
import { refreshLoop } from "./loop";
import { messageFromError } from "./utils";

interface TimerModuleElements {
  status: HTMLElement;
}

type TimerPendingState = "starting" | "stopping";

type TimerUiData = {
  active_session: SurfaceTimeSessionResponse | null;
};

const STARTING_LABEL = "Starting…";
const STOPPING_LABEL = "Stopping…";

let statusEl: HTMLElement | null = null;

export function init(elements: TimerModuleElements): void {
  statusEl = elements.status;
}

export async function loadTimerStatus(loopId: number | string): Promise<SurfaceTimerStatusResponse | null> {
  return api.fetchTimerStatus(loopId);
}

export async function loadAllTimerStatuses(): Promise<void> {
  const cards = document.querySelectorAll<HTMLElement>("#inbox .loop-card");
  for (const card of cards) {
    const loopId = card.dataset["loopId"];
    if (!loopId) {
      continue;
    }

    const timerStatus = await loadTimerStatus(loopId);
    if (timerStatus?.has_active_session && timerStatus.active_session) {
      startTimerUI(loopId, timerStatus);
    }
  }
}

function timerButtons(loopId: number | string): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>(
    `button[data-action="timer-toggle"][data-id="${loopId}"]`,
  ));
}

function timerDisplays(loopId: number | string): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(`[data-timer-display="${loopId}"]`));
}

function timerFeedbackNodes(loopId: number | string): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(`[data-timer-feedback="${loopId}"]`));
}

function timerRunningLabel(button: HTMLButtonElement): string {
  return button.classList.contains("next-card-focus-btn") ? "⏹ Stop focus" : "⏹ Stop";
}

function timerStoppedLabel(button: HTMLButtonElement): string {
  return button.classList.contains("next-card-focus-btn") ? "▶ Start focus" : "▶ Start";
}

function setTimerFeedback(loopId: number | string, message = "", kind: "info" | "error" = "info"): void {
  for (const node of timerFeedbackNodes(loopId)) {
    node.textContent = message;
    node.classList.toggle("error", kind === "error");
  }
}

function setPendingTimerUI(loopId: number | string, pending: TimerPendingState): void {
  for (const button of timerButtons(loopId)) {
    button.disabled = true;
    button.classList.add("pending");
    button.dataset["pending"] = pending;
    button.textContent = pending === "starting" ? STARTING_LABEL : STOPPING_LABEL;
    button.setAttribute("aria-busy", "true");
  }
  setTimerFeedback(loopId, pending === "starting" ? "Starting focus…" : "Stopping focus…");
}

function clearPendingTimerUI(loopId: number | string): void {
  for (const button of timerButtons(loopId)) {
    button.disabled = false;
    button.classList.remove("pending");
    delete button.dataset["pending"];
    button.removeAttribute("aria-busy");
  }
}

function hasPendingTimerAction(loopId: number | string): boolean {
  return timerButtons(loopId).some((button) => Boolean(button.dataset["pending"]));
}

function timerErrorCode(error: unknown): string | null {
  return error instanceof HttpRequestError ? error.code : null;
}

function restoreRunningTimerUI(loopId: number | string): void {
  clearPendingTimerUI(loopId);
  for (const button of timerButtons(loopId)) {
    button.classList.add("running");
    button.textContent = timerRunningLabel(button);
    button.dataset["running"] = "true";
  }
  for (const display of timerDisplays(loopId)) {
    display.classList.add("active");
  }
}

export function startTimerUI(loopId: number | string, timerData: TimerUiData): void {
  stopTimerUI(loopId);
  clearPendingTimerUI(loopId);

  for (const button of timerButtons(loopId)) {
    button.classList.add("running");
    button.textContent = timerRunningLabel(button);
    button.dataset["running"] = "true";
  }
  for (const display of timerDisplays(loopId)) {
    display.classList.add("active");
  }

  const startedAtValue = typeof timerData.active_session?.started_at_utc === "string"
    ? timerData.active_session.started_at_utc
    : null;
  const startedAt = new Date(startedAtValue ?? Date.now());
  const updateDisplay = (): void => {
    const elapsed = Math.floor((Date.now() - startedAt.getTime()) / 1000);
    updateTimerDisplay(loopId, elapsed);
  };

  updateDisplay();
  const intervalId = window.setInterval(updateDisplay, 1000);

  state.addActiveTimer(Number(loopId), {
    session_id: timerData.active_session?.id ?? null,
    started_at: startedAt,
    interval_id: intervalId,
  });
}

export function stopTimerUI(loopId: number | string): void {
  state.removeActiveTimer(Number(loopId));
  clearPendingTimerUI(loopId);

  for (const button of timerButtons(loopId)) {
    button.classList.remove("running");
    button.textContent = timerStoppedLabel(button);
    button.dataset["running"] = "false";
  }
  for (const display of timerDisplays(loopId)) {
    display.classList.remove("active");
  }
}

function updateTimerDisplay(loopId: number | string, elapsedSeconds: number): void {
  for (const display of timerDisplays(loopId)) {
    display.textContent = formatDuration(elapsedSeconds);
  }
}

async function refreshLoopAfterTimerMutation(loopId: number | string, fallbackMessage: string): Promise<boolean> {
  try {
    await refreshLoop(loopId);
    return true;
  } catch (error: unknown) {
    const message = messageFromError(error, fallbackMessage);
    setTimerFeedback(loopId, message, "error");
    if (statusEl) {
      statusEl.textContent = message;
    }
    return false;
  }
}

async function handleTimerError(
  loopId: number | string,
  error: unknown,
  attemptedAction: TimerPendingState,
): Promise<void> {
  clearPendingTimerUI(loopId);
  const code = timerErrorCode(error);

  if (code === "timer_already_active") {
    const timerStatus = await loadTimerStatus(loopId);
    if (timerStatus?.has_active_session && timerStatus.active_session) {
      startTimerUI(loopId, timerStatus);
      setTimerFeedback(loopId, "Timer was already running.");
      if (statusEl) {
        statusEl.textContent = "Timer already running for this loop.";
      }
      await refreshLoopAfterTimerMutation(loopId, "Timer was already running, but refresh failed.");
      startTimerUI(loopId, timerStatus);
      setTimerFeedback(loopId, "Timer was already running.");
      return;
    }
  }

  if (code === "no_active_timer") {
    stopTimerUI(loopId);
    setTimerFeedback(loopId, "Timer was already stopped.", "error");
    if (statusEl) {
      statusEl.textContent = "Timer was already stopped.";
    }
    await refreshLoopAfterTimerMutation(loopId, "Timer was already stopped, but refresh failed.");
    stopTimerUI(loopId);
    setTimerFeedback(loopId, "Timer was already stopped.", "error");
    return;
  }

  const message = messageFromError(error, "Timer operation failed.");
  const timerStatus = await loadTimerStatus(loopId).catch(() => null);
  if (timerStatus?.has_active_session && timerStatus.active_session) {
    startTimerUI(loopId, timerStatus);
  } else if (attemptedAction === "stopping") {
    restoreRunningTimerUI(loopId);
  } else {
    stopTimerUI(loopId);
  }
  setTimerFeedback(loopId, message, "error");
  if (statusEl) {
    statusEl.textContent = message;
  }
}

export async function toggleTimer(loopId: number | string): Promise<void> {
  if (hasPendingTimerAction(loopId)) {
    return;
  }

  const isRunning = timerButtons(loopId).some((button) => button.dataset["running"] === "true");
  setTimerFeedback(loopId);

  let attemptedAction: TimerPendingState = isRunning ? "stopping" : "starting";

  try {
    if (isRunning) {
      attemptedAction = "stopping";
      setPendingTimerUI(loopId, attemptedAction);
      const session = await api.stopTimer(loopId);
      stopTimerUI(loopId);
      if (statusEl) {
        statusEl.textContent = `Timer stopped: ${formatDuration(session.duration_seconds ?? 0)}`;
      }
      const refreshed = await refreshLoopAfterTimerMutation(loopId, "Timer stopped, but refresh failed.");
      stopTimerUI(loopId);
      if (refreshed) {
        setTimerFeedback(loopId);
      }
      return;
    }

    attemptedAction = "starting";
    setPendingTimerUI(loopId, attemptedAction);
    const session = await api.startTimer(loopId);
    startTimerUI(loopId, { active_session: session });
    if (statusEl) {
      statusEl.textContent = "Timer started.";
    }
    const refreshed = await refreshLoopAfterTimerMutation(loopId, "Timer started, but refresh failed.");
    startTimerUI(loopId, { active_session: session });
    if (refreshed) {
      setTimerFeedback(loopId);
    }
  } catch (error: unknown) {
    await handleTimerError(loopId, error, attemptedAction);
  }
}
