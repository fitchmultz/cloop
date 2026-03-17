/**
 * notifications.js - Scheduler notification UI
 *
 * Purpose:
 *   Display scheduler-generated notifications as UI banners and review prompts.
 *
 * Responsibilities:
 *   - Show notification cards for nudge_due_soon and nudge_stale events
 *   - Display review banners for review_generated events
 *   - Auto-dismiss notifications after timeout
 *   - Handle user interactions (dismiss, navigate)
 *
 * Non-scope:
 *   - Push notification delivery (handled by service worker)
 *   - Event source handling (see sse.js)
 */

let notificationContainer = null;
const NOTIFICATION_TIMEOUT = 30000; // 30 seconds auto-dismiss

function initNotificationContainer() {
  if (notificationContainer) return;

  notificationContainer = document.createElement('div');
  notificationContainer.id = 'scheduler-notifications';
  notificationContainer.className = 'notification-container';
  document.body.appendChild(notificationContainer);
}

function iconForType(type) {
  const icons = {
    due_soon: '⏰',
    stale: '🦥',
    blocked: '🚧'
  };
  return icons[type] || '🔔';
}

function renderDetails(details) {
  return `<ul>${details.slice(0, 5).map(d =>
    `<li data-loop-id="${d.id}">${d.title}${d.is_overdue ? ' (OVERDUE)' : ''}</li>`
  ).join('')}</ul>`;
}

function switchToTab(tabName) {
  const tab = document.querySelector(`[data-tab="${tabName}"]`);
  if (tab) tab.click();
}

export function showSchedulerNotification({ type, title, body, severity, details, action }) {
  initNotificationContainer();

  const notification = document.createElement('div');
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
    ${details ? `<div class="notification-details collapsed">${renderDetails(details)}</div>` : ''}
  `;

  // Click to expand/action
  notification.querySelector('.notification-content').addEventListener('click', (e) => {
    if (e.target.classList.contains('notification-dismiss')) return;
    if (action?.type === 'navigate') {
      switchToTab(action.tab);
    }
  });

  // Dismiss button
  notification.querySelector('.notification-dismiss').addEventListener('click', () => {
    notification.remove();
  });

  notificationContainer.appendChild(notification);

  // Auto-dismiss
  setTimeout(() => {
    notification.classList.add('fade-out');
    setTimeout(() => notification.remove(), 300);
  }, NOTIFICATION_TIMEOUT);

  return notification;
}

export function showReviewBanner({ type, itemCount, cohorts }) {
  initNotificationContainer();

  const banner = document.createElement('div');
  banner.className = 'review-banner';
  banner.innerHTML = `
    <div class="banner-content">
      <span class="banner-icon">${type === 'daily' ? '📋' : '📅'}</span>
      <span class="banner-text">
        <strong>${type === 'daily' ? 'Daily' : 'Weekly'} review ready:</strong>
        ${itemCount} items across ${cohorts ? cohorts.length : 0} cohorts
      </span>
      <button class="banner-action">Review Now</button>
      <button class="banner-dismiss" aria-label="Dismiss">×</button>
    </div>
  `;

  banner.querySelector('.banner-action').addEventListener('click', () => {
    switchToTab('review');
    banner.remove();
  });

  banner.querySelector('.banner-dismiss').addEventListener('click', () => {
    banner.remove();
  });

  notificationContainer.appendChild(banner);

  // Auto-dismiss after 60 seconds for review banners
  setTimeout(() => banner.remove(), 60000);

  return banner;
}
