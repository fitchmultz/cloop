/**
 * notifications.ts - Scheduler notification UI.
 *
 * Purpose:
 *   Display scheduler-generated notifications as a single in-app banner system.
 *
 * Responsibilities:
 *   - Show notification cards for scheduler-owned continuity nudges and review readiness.
 *   - Auto-dismiss notifications after timeout.
 *   - Handle user interactions (dismiss, navigate).
 *
 * Scope:
 *   - Surface-runtime notification banners only.
 *
 * Usage:
 *   - Imported lazily by sse.ts when scheduler events arrive.
 *
 * Invariants/Assumptions:
 *   - The unified shell uses hash routing for navigation.
 *   - Notifications render into a browser-global container appended to body.
 */

import type { SchedulerNotificationLoopDetail, SchedulerNotificationPayload } from "./contracts";

let notificationContainer: HTMLDivElement | null = null;
const NOTIFICATION_TIMEOUT = 30_000;

const TAB_HASH: Record<string, string> = {
  operator: "#operator",
  review: "#review",
  capture: "#capture",
  do: "#do",
  chat: "#recall/chat",
  memory: "#recall/memory",
  rag: "#recall/rag",
};

function initNotificationContainer(): HTMLDivElement {
  if (notificationContainer) {
    return notificationContainer;
  }

  notificationContainer = document.createElement("div");
  notificationContainer.id = "scheduler-notifications";
  notificationContainer.className = "notification-container";
  document.body.appendChild(notificationContainer);
  return notificationContainer;
}

function iconForType(type: string): string {
  const icons: Record<string, string> = {
    due_soon: "⏰",
    stale: "🦥",
    blocked: "🚧",
    review: "📋",
  };
  return icons[type] ?? "🔔";
}

function renderDetails(details: SchedulerNotificationLoopDetail[]): string {
  return `<ul>${details.slice(0, 5).map((detail) => (
    `<li data-loop-id="${detail.id}">${detail.title}${detail.is_overdue ? " (OVERDUE)" : ""}</li>`
  )).join("")}</ul>`;
}

function switchToTab(tabName: string): void {
  const hash = TAB_HASH[tabName];
  if (hash) {
    window.location.hash = hash;
  }
}

export function showSchedulerNotification({
  type,
  title,
  body,
  severity,
  details,
  action,
}: SchedulerNotificationPayload): HTMLDivElement {
  const container = initNotificationContainer();

  const notification = document.createElement("div");
  notification.className = `scheduler-notification ${severity}`;
  notification.innerHTML = `
    <div class="notification-content">
      <span class="notification-icon">${iconForType(type)}</span>
      <div class="notification-text">
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
      <button class="notification-dismiss" aria-label="Dismiss">×</button>
    </div>
    ${details && details.length > 0 ? `<div class="notification-details collapsed">${renderDetails(details)}</div>` : ""}
  `;

  const content = notification.querySelector(".notification-content");
  if (content instanceof HTMLElement) {
    content.addEventListener("click", (event: MouseEvent) => {
      if (event.target instanceof Element && event.target.classList.contains("notification-dismiss")) {
        return;
      }
      if (action?.type === "navigate") {
        switchToTab(action.tab);
      }
    });
  }

  const dismissButton = notification.querySelector(".notification-dismiss");
  if (dismissButton instanceof HTMLButtonElement) {
    dismissButton.addEventListener("click", () => {
      notification.remove();
    });
  }

  container.appendChild(notification);

  window.setTimeout(() => {
    notification.classList.add("fade-out");
    window.setTimeout(() => notification.remove(), 300);
  }, NOTIFICATION_TIMEOUT);

  return notification;
}
