/**
 * sse.js - Server-Sent Events handling
 *
 * Purpose:
 *   Manage real-time updates via SSE connection.
 *
 * Responsibilities:
 *   - Establish SSE connection
 *   - Handle reconnection with backoff
 *   - Process loop events
 *   - Update connection status indicator
 *
 * Non-scope:
 *   - Loop rendering (see render.js, loop.js)
 *   - API calls (see api.js)
 */

import { refreshLoop, handleLoopClosed } from './loop.js';

/**
 * Scheduler notification handlers
 */
async function handleDueSoonNudge(payload) {
  const { details, escalation_summary } = payload;
  if (!details || details.length === 0) return;

  const { showSchedulerNotification } = await import('./notifications.js');

  const urgentCount = escalation_summary ? (escalation_summary[3] || 0) : 0;
  const overdueCount = details.filter(d => d.is_overdue).length;

  showSchedulerNotification({
    type: 'due_soon',
    title: overdueCount > 0 ? `${overdueCount} overdue loops` : `${details.length} loops due soon`,
    body: details.slice(0, 3).map(d => d.title).join(', '),
    severity: urgentCount > 0 ? 'alert' : overdueCount > 0 ? 'warning' : 'info',
    details: details,
    action: { type: 'navigate', tab: 'review' }
  });
}

async function handleStaleNudge(payload) {
  const { details } = payload;
  if (!details || details.length === 0) return;

  const { showSchedulerNotification } = await import('./notifications.js');

  showSchedulerNotification({
    type: 'stale',
    title: `${details.length} stale loops need attention`,
    body: details.slice(0, 3).map(d => d.title).join(', '),
    severity: 'warning',
    details: details,
    action: { type: 'navigate', tab: 'review' }
  });
}

async function handleReviewGenerated(payload) {
  const { review_type, cohorts, total_items } = payload;
  if (total_items === 0) return;

  const { showReviewBanner } = await import('./notifications.js');

  showReviewBanner({
    type: review_type,
    itemCount: total_items,
    cohorts: cohorts
  });
}

let eventSource = null;
let lastEventId = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 1000;

/**
 * Connect to SSE stream
 */
export function connectSSE() {
  const url = lastEventId
    ? `/loops/events/stream?cursor=${lastEventId}`
    : '/loops/events/stream';

  eventSource = new EventSource(url);

  eventSource.addEventListener('loop_event', (e) => {
    reconnectAttempts = 0;
    updateConnectionStatus('connected');
    try {
      const data = JSON.parse(e.data);
      lastEventId = data.event_id;
      handleLoopEvent(data);
    } catch (err) {
      console.error('SSE parse error:', err);
    }
  });

  eventSource.onerror = () => {
    eventSource.close();
    eventSource = null;
    updateConnectionStatus('reconnecting');

    // Exponential backoff reconnection with cap at 30s
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts), 30000);
      reconnectAttempts++;
      setTimeout(connectSSE, delay);
    } else {
      updateConnectionStatus('disconnected');
    }
  };

  eventSource.onopen = () => {
    reconnectAttempts = 0;
    updateConnectionStatus('connected');
  };
}

/**
 * Disconnect from SSE stream
 */
export function disconnectSSE() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

/**
 * Handle incoming loop event
 */
async function handleLoopEvent(event) {
  const { event_type, loop_id, payload } = event;

  switch (event_type) {
    case 'capture':
      // New loop created - fetch and add to inbox
      await fetchAndReplaceLoop(loop_id);
      break;

    case 'update':
    case 'status_change':
    case 'enrich_requested':
    case 'enrich_succeeded':
    case 'enrich_failed':
    case 'timer_started':
    case 'timer_stopped':
      // Loop modified - update in place
      await fetchAndReplaceLoop(loop_id);
      break;

    case 'close':
      // Loop closed - may need to remove from view
      handleLoopClosed(loop_id, payload);
      break;

    case 'nudge_due_soon':
      await handleDueSoonNudge(payload);
      break;

    case 'nudge_stale':
      await handleStaleNudge(payload);
      break;

    case 'review_generated':
      await handleReviewGenerated(payload);
      break;

    default:
      // Unknown event type - refresh loop to be safe
      if (loop_id && loop_id > 0) {
        await fetchAndReplaceLoop(loop_id);
      }
  }
}

/**
 * Fetch loop and update in DOM
 */
async function fetchAndReplaceLoop(loopId) {
  try {
    await refreshLoop(loopId);
  } catch (err) {
    console.error('fetchAndReplaceLoop error:', err);
  }
}

/**
 * Update connection status indicator
 */
function updateConnectionStatus(status) {
  const indicator = document.getElementById('sse-status');
  if (!indicator) return;

  indicator.className = 'sse-status ' + status;
  indicator.title = {
    connected: 'Connected - real-time updates active',
    reconnecting: 'Reconnecting...',
    disconnected: 'Disconnected - refresh to reconnect'
  }[status] || status;
}

/**
 * Setup visibility change handler for reconnection
 */
export function setupVisibilityHandler() {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (!eventSource || eventSource.readyState === EventSource.CLOSED)) {
      reconnectAttempts = 0;
      connectSSE();
    }
  });
}
