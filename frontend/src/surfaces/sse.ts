/**
 * sse.ts - Surface runtime Server-Sent Events handling.
 *
 * Purpose:
 *   Manage real-time loop and scheduler updates via a browser EventSource.
 *
 * Responsibilities:
 *   - Establish and reconnect the SSE stream.
 *   - Refresh loops after mutations/events.
 *   - Route scheduler events to the shared notification helper.
 *
 * Scope:
 *   - Surface runtime real-time event handling only.
 *
 * Usage:
 *   - Imported by bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - Loop events arrive on /loops/events/stream.
 *   - Notification UI is loaded lazily to avoid eager scheduler code.
 */

import {
  acknowledgeContinuityNotification,
  hydrateDurableContinuityState,
  markContinuityNotificationSeen,
  readBannerContinuityNotificationRecords,
} from "../continuity-intelligence";
import { handleLoopClosed, refreshLoop } from "./loop";

interface SchedulerDetail {
  id: number;
  title: string;
  is_overdue?: boolean;
}

interface LoopStreamEvent {
  event_id?: string | null;
  event_type: string;
  loop_id?: number | null;
  payload?: Record<string, unknown> | null;
}

let eventSource: EventSource | null = null;
let lastEventId: string | null = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 1000;

async function currentContinuityNotification() {
  await hydrateDurableContinuityState();
  return readBannerContinuityNotificationRecords()[0] ?? null;
}

function wireNotificationState(notificationId: string, banner: HTMLDivElement): void {
  markContinuityNotificationSeen(notificationId);
  const dismissButton = banner.querySelector<HTMLButtonElement>(".notification-dismiss");
  dismissButton?.addEventListener("click", () => {
    acknowledgeContinuityNotification(notificationId);
  });
}

async function showCurrentContinuityNotification(input: {
  type: "due_soon" | "stale" | "review";
  details?: SchedulerDetail[];
}): Promise<void> {
  const { showSchedulerNotification } = await import("./notifications");
  const notification = await currentContinuityNotification();
  if (!notification) {
    return;
  }

  const banner = showSchedulerNotification({
    type: input.type,
    title: notification.title,
    body: notification.body,
    severity: notification.severity,
    ...(input.details ? { details: input.details } : {}),
    action: { type: "navigate", location: notification.resolvedLocation },
  });
  wireNotificationState(notification.id, banner);
}

async function handleDueSoonNudge(payload: Record<string, unknown>): Promise<void> {
  const details = Array.isArray(payload["details"]) ? payload["details"] as SchedulerDetail[] : [];
  if (details.length === 0) {
    return;
  }
  await showCurrentContinuityNotification({ type: "due_soon", details });
}

async function handleStaleNudge(payload: Record<string, unknown>): Promise<void> {
  const details = Array.isArray(payload["details"]) ? payload["details"] as SchedulerDetail[] : [];
  if (details.length === 0) {
    return;
  }
  await showCurrentContinuityNotification({ type: "stale", details });
}

async function handleReviewGenerated(payload: Record<string, unknown>): Promise<void> {
  const totalItems = typeof payload["total_items"] === "number" ? payload["total_items"] : 0;
  if (totalItems === 0) {
    return;
  }
  await showCurrentContinuityNotification({ type: "review" });
}

export function connectSSE(): void {
  const url = lastEventId ? `/loops/events/stream?cursor=${lastEventId}` : "/loops/events/stream";
  eventSource = new EventSource(url);

  eventSource.addEventListener("loop_event", (event) => {
    reconnectAttempts = 0;
    updateConnectionStatus("connected");
    try {
      const data = JSON.parse(event.data) as LoopStreamEvent;
      lastEventId = data.event_id ?? null;
      void handleLoopEvent(data);
    } catch {
      // Ignore malformed events.
    }
  });

  eventSource.onerror = () => {
    eventSource?.close();
    eventSource = null;
    updateConnectionStatus("reconnecting");

    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      const delay = Math.min(BASE_RECONNECT_DELAY * (2 ** reconnectAttempts), 30_000);
      reconnectAttempts += 1;
      window.setTimeout(connectSSE, delay);
    } else {
      updateConnectionStatus("disconnected");
    }
  };

  eventSource.onopen = () => {
    reconnectAttempts = 0;
    updateConnectionStatus("connected");
  };
}

export function disconnectSSE(): void {
  eventSource?.close();
  eventSource = null;
}

async function handleLoopEvent(event: LoopStreamEvent): Promise<void> {
  const payload = event.payload ?? {};
  switch (event.event_type) {
    case "capture":
    case "update":
    case "status_change":
    case "enrich_requested":
    case "enrich_succeeded":
    case "enrich_failed":
    case "timer_started":
    case "timer_stopped":
      if (typeof event.loop_id === "number") {
        await fetchAndReplaceLoop(event.loop_id);
      }
      return;

    case "close":
      if (typeof event.loop_id === "number") {
        handleLoopClosed(event.loop_id, payload);
      }
      return;

    case "nudge_due_soon":
      await handleDueSoonNudge(payload);
      return;

    case "nudge_stale":
      await handleStaleNudge(payload);
      return;

    case "review_generated":
      await handleReviewGenerated(payload);
      return;

    default:
      if (typeof event.loop_id === "number" && event.loop_id > 0) {
        await fetchAndReplaceLoop(event.loop_id);
      }
  }
}

async function fetchAndReplaceLoop(loopId: number): Promise<void> {
  try {
    await refreshLoop(loopId);
  } catch {
    // Best-effort refresh only.
  }
}

function updateConnectionStatus(status: "connected" | "reconnecting" | "disconnected"): void {
  const indicator = document.getElementById("sse-status");
  if (!(indicator instanceof HTMLElement)) {
    return;
  }

  indicator.className = `sse-status ${status}`;
  const titles: Record<typeof status, string> = {
    connected: "Connected - real-time updates active",
    reconnecting: "Reconnecting...",
    disconnected: "Disconnected - refresh to reconnect",
  };
  indicator.title = titles[status];
}

export function setupVisibilityHandler(): void {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && (!eventSource || eventSource.readyState === EventSource.CLOSED)) {
      reconnectAttempts = 0;
      connectSSE();
    }
  });
}
