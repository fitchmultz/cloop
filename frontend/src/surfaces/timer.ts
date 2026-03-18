/**
 * timer.ts - Browser-side loop timer functionality.
 *
 * Purpose:
 *   Manage time tracking for loops with start/stop functionality and live timer
 *   display updates.
 *
 * Responsibilities:
 *   - Load/start/stop timer API flows.
 *   - Keep timer button and elapsed-time UI synchronized.
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
 */

import * as api from "./api";
import * as state from "./state";
import type { SurfaceTimeSessionResponse, SurfaceTimerStatusResponse } from "./contracts";
import { formatDuration } from "./render";
import { refreshLoop } from "./loop";
import { messageFromError } from "./utils";

interface TimerModuleElements {
  status: HTMLElement;
}

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

type TimerUiData = {
  active_session: SurfaceTimeSessionResponse | null;
};

export function startTimerUI(loopId: number | string, timerData: TimerUiData): void {
  stopTimerUI(loopId);

  const button = document.querySelector(`button[data-action="timer-toggle"][data-id="${loopId}"]`);
  const display = document.querySelector(`[data-timer-display="${loopId}"]`);

  if (button instanceof HTMLButtonElement) {
    button.classList.add("running");
    button.textContent = "⏹ Stop";
    button.dataset["running"] = "true";
  }
  if (display instanceof HTMLElement) {
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

  const button = document.querySelector(`button[data-action="timer-toggle"][data-id="${loopId}"]`);
  const display = document.querySelector(`[data-timer-display="${loopId}"]`);

  if (button instanceof HTMLButtonElement) {
    button.classList.remove("running");
    button.textContent = "▶ Start";
    button.dataset["running"] = "false";
  }
  if (display instanceof HTMLElement) {
    display.classList.remove("active");
  }
}

function updateTimerDisplay(loopId: number | string, elapsedSeconds: number): void {
  const display = document.querySelector(`[data-timer-display="${loopId}"]`);
  if (display instanceof HTMLElement) {
    display.textContent = formatDuration(elapsedSeconds);
  }
}

export async function toggleTimer(loopId: number | string): Promise<void> {
  const button = document.querySelector(`button[data-action="timer-toggle"][data-id="${loopId}"]`);
  const isRunning = button instanceof HTMLButtonElement && button.dataset["running"] === "true";

  try {
    if (isRunning) {
      const session = await api.stopTimer(loopId);
      stopTimerUI(loopId);
      if (statusEl) {
        statusEl.textContent = `Timer stopped: ${formatDuration(session.duration_seconds ?? 0)}`;
      }
      await refreshLoop(loopId);
      return;
    }

    try {
      const session = await api.startTimer(loopId);
      startTimerUI(loopId, { active_session: session });
      if (statusEl) {
        statusEl.textContent = "Timer started.";
      }
    } catch (error: unknown) {
      if (messageFromError(error) === "already_running") {
        if (statusEl) {
          statusEl.textContent = "Timer already running for this loop.";
        }
        const timerStatus = await loadTimerStatus(loopId);
        if (timerStatus?.has_active_session) {
          startTimerUI(loopId, timerStatus);
        }
      } else {
        throw error;
      }
    }
  } catch (error: unknown) {
    if (statusEl) {
      statusEl.textContent = messageFromError(error, "Timer operation failed.");
    }
  }
}
