/**
 * timer.js - Timer functionality
 *
 * Purpose:
 *   Manage time tracking for loops with start/stop functionality.
 *
 * Responsibilities:
 *   - Start/stop timer API calls
 *   - Timer UI updates (display, button states)
 *   - Active timer tracking
 *   - Format duration display
 *
 * Non-scope:
 *   - Loop rendering (see render.js)
 *   - State management (see state.js)
 *   - Bulk operations (see bulk.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { formatDuration } from './render.js';
import { refreshLoop } from './loop.js';

let statusEl;

/**
 * Initialize timer module
 */
export function init(elements) {
  statusEl = elements.status;
}

/**
 * Load timer status for a loop
 */
export async function loadTimerStatus(loopId) {
  return await api.fetchTimerStatus(loopId);
}

/**
 * Load timer status for all visible loops
 */
export async function loadAllTimerStatuses() {
  const cards = document.querySelectorAll('#inbox .loop-card');
  for (const card of cards) {
    const loopId = card.dataset.loopId;
    if (!loopId) continue;

    const timerStatus = await loadTimerStatus(loopId);
    if (timerStatus?.has_active_session && timerStatus.active_session) {
      startTimerUI(loopId, timerStatus);
    }
  }
}

/**
 * Start timer UI updates
 */
export function startTimerUI(loopId, timerData) {
  // Clear any existing timer
  stopTimerUI(loopId);

  const btn = document.querySelector(`button[data-action="timer-toggle"][data-id="${loopId}"]`);
  const display = document.querySelector(`[data-timer-display="${loopId}"]`);

  if (btn) {
    btn.classList.add('running');
    btn.textContent = '⏹ Stop';
    btn.dataset.running = 'true';
  }
  if (display) {
    display.classList.add('active');
  }

  // Calculate elapsed time
  const startedAt = new Date(timerData.active_session?.started_at_utc || timerData.started_at_utc);
  const updateDisplay = () => {
    const elapsed = Math.floor((Date.now() - startedAt.getTime()) / 1000);
    updateTimerDisplay(loopId, elapsed);
  };

  // Update immediately and then every second
  updateDisplay();
  const intervalId = setInterval(updateDisplay, 1000);

  state.addActiveTimer(loopId, {
    session_id: timerData.active_session?.id || timerData.session_id,
    started_at: startedAt,
    interval_id: intervalId
  });
}

/**
 * Stop timer UI updates
 */
export function stopTimerUI(loopId) {
  const timer = state.removeActiveTimer(loopId);

  const btn = document.querySelector(`button[data-action="timer-toggle"][data-id="${loopId}"]`);
  const display = document.querySelector(`[data-timer-display="${loopId}"]`);

  if (btn) {
    btn.classList.remove('running');
    btn.textContent = '▶ Start';
    btn.dataset.running = 'false';
  }
  if (display) {
    display.classList.remove('active');
  }
}

/**
 * Update timer display
 */
function updateTimerDisplay(loopId, elapsedSeconds) {
  const display = document.querySelector(`[data-timer-display="${loopId}"]`);
  if (display) {
    display.textContent = formatDuration(elapsedSeconds);
  }
}

/**
 * Toggle timer for a loop
 */
export async function toggleTimer(loopId) {
  const btn = document.querySelector(`button[data-action="timer-toggle"][data-id="${loopId}"]`);
  const isRunning = btn && btn.dataset.running === 'true';

  try {
    if (isRunning) {
      // Stop timer
      const session = await api.stopTimer(loopId);
      stopTimerUI(loopId);
      statusEl.textContent = `Timer stopped: ${formatDuration(session.duration_seconds || 0)}`;
      // Refresh loop to update tracked time display
      await refreshLoop(loopId);
    } else {
      // Start timer
      try {
        const session = await api.startTimer(loopId);
        startTimerUI(loopId, { active_session: session });
        statusEl.textContent = "Timer started.";
      } catch (error) {
        if (error.message === "already_running") {
          statusEl.textContent = "Timer already running for this loop.";
          // Reload timer status
          const timerStatus = await loadTimerStatus(loopId);
          if (timerStatus?.has_active_session) {
            startTimerUI(loopId, timerStatus);
          }
        } else {
          throw error;
        }
      }
    }
  } catch (error) {
    console.error("Timer error:", error);
    statusEl.textContent = error.message || "Timer operation failed.";
  }
}
