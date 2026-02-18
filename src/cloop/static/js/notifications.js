/**
 * notifications.js - Scheduler/system notification toasts
 *
 * Purpose:
 *   Display user-visible notification toasts for scheduler events.
 *
 * Responsibilities:
 *   - Show toast notifications for nudge_due_soon, nudge_stale, review_generated
 *   - Navigate to review tab on toast click
 *   - Cap toast list length
 *
 * Non-scope:
 *   - SSE connection (see sse.js)
 *   - Push notification subscription (see push.js)
 */

import * as review from './review.js';

let container;

/**
 * Initialize the notifications module.
 * @param {Object} options
 * @param {HTMLElement} options.notificationsContainer - DOM element for toasts
 */
export function init({ notificationsContainer }) {
  container = notificationsContainer;
}

/**
 * Navigate to the review tab.
 */
function clickTab(tabName) {
  const tab = document.querySelector(`.tab[data-tab="${tabName}"]`);
  tab?.click();
}

/**
 * Set the review mode (daily/weekly).
 */
function setReviewMode(mode) {
  const btn = document.querySelector(`[data-review-mode="${mode}"]`);
  btn?.click();
}

/**
 * Push a toast notification.
 * @param {Object} options
 * @param {string} options.title - Toast title
 * @param {string} options.body - Toast body text
 * @param {string} [options.variant='scheduler'] - Toast style variant
 * @param {string} [options.ctaLabel='View'] - Call-to-action button label
 * @param {Function} [options.onView] - Callback when View is clicked
 */
export function pushToast({ title, body, variant = 'scheduler', ctaLabel = 'View', onView }) {
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `notification-toast ${variant}`;

  toast.innerHTML = `
    <div>
      <div class="title"></div>
      <div class="body"></div>
    </div>
    <div class="actions">
      <button data-action="view">${ctaLabel}</button>
      <button data-action="dismiss">Dismiss</button>
    </div>
  `;
  toast.querySelector('.title').textContent = title;
  toast.querySelector('.body').textContent = body || '';

  toast.addEventListener('click', async (e) => {
    const action = e.target?.dataset?.action;
    if (action === 'dismiss') {
      toast.remove();
      return;
    }
    if (action === 'view') {
      try {
        await onView?.();
      } finally {
        toast.remove();
      }
    }
  });

  container.prepend(toast);

  // Cap list length
  const toasts = container.querySelectorAll('.notification-toast');
  if (toasts.length > 5) {
    toasts[toasts.length - 1].remove();
  }
}

/**
 * Navigate to the review tab with specified mode.
 * @param {Object} [options]
 * @param {string} [options.mode='daily'] - Review mode
 */
export async function navigateToReview({ mode = 'daily' } = {}) {
  window.location.hash = '#review';
  clickTab('review');
  setReviewMode(mode);
  await review.loadReviewData();
}

/**
 * Show a toast for a scheduler event.
 * @param {Object} event - SSE event with event_type and payload
 */
export function showSchedulerEventToast(event) {
  const { event_type, payload } = event;

  if (event_type === 'nudge_due_soon') {
    const count = payload?.loop_ids?.length || 0;
    const first = payload?.details?.[0]?.title || 'A loop';
    pushToast({
      title: `Due soon: ${count} loop${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} a next action`,
      body: count > 1 ? `First: ${first}` : first,
      onView: () => navigateToReview({ mode: 'daily' }),
    });
    return;
  }

  if (event_type === 'nudge_stale') {
    const count = payload?.loop_ids?.length || 0;
    const first = payload?.details?.[0]?.title || 'A loop';
    pushToast({
      title: `Stale rescue: ${count} loop${count === 1 ? '' : 's'} haven't been touched`,
      body: count > 1 ? `Oldest: ${first}` : first,
      onView: () => navigateToReview({ mode: 'daily' }),
    });
    return;
  }

  if (event_type === 'review_generated') {
    const reviewType = payload?.review_type || 'daily';
    const total = payload?.total_items ?? 0;
    pushToast({
      title: `${reviewType[0].toUpperCase() + reviewType.slice(1)} review generated`,
      body: `Items: ${total}`,
      onView: () => navigateToReview({ mode: reviewType === 'weekly' ? 'weekly' : 'daily' }),
    });
    return;
  }
}
