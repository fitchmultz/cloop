/**
 * next.js - Next actions (What should I do now?)
 *
 * Purpose:
 *   Show prioritized next actions organized by energy level/buckets.
 *
 * Responsibilities:
 *   - Load and display next action buckets
 *   - Handle refresh button
 *   - Render prioritized loop suggestions
 *
 * Non-scope:
 *   - Loop capture (see init.js)
 *   - Inbox management (see loop.js)
 */

import * as api from './api.js';

let nextBucketsEl = null;

/**
 * Initialize next module
 */
export function init(elements) {
  nextBucketsEl = elements.nextBuckets;
}

/**
 * Load next actions from API
 */
export async function loadNext() {
  if (!nextBucketsEl) return;

  try {
    const data = await api.fetchNextLoops();
    renderNextBuckets(normalizeBuckets(data));
  } catch (error) {
    nextBucketsEl.innerHTML = `<p class="error">Failed to load next actions: ${error.message}</p>`;
  }
}

/**
 * Normalize backend next-loop payloads into UI bucket objects.
 *
 * The API returns keyed bucket arrays (`due_soon`, `quick_wins`, etc.), while
 * the renderer expects a list with display titles.
 */
function normalizeBuckets(data) {
  const bucketTitles = {
    due_soon: 'Due soon',
    quick_wins: 'Quick wins',
    high_leverage: 'High leverage',
    standard: 'Standard',
  };

  return Object.entries(bucketTitles)
    .map(([key, title]) => ({
      key,
      title,
      items: Array.isArray(data?.[key]) ? data[key] : [],
    }))
    .filter(bucket => bucket.items.length > 0);
}

/**
 * Render next action buckets
 */
function renderNextBuckets(buckets) {
  if (!nextBucketsEl) return;

  if (buckets.length === 0) {
    nextBucketsEl.innerHTML = '<p class="empty">No next actions found. Capture some loops first!</p>';
    return;
  }

  const html = buckets.map(bucket => `
    <div class="next-bucket">
      <h3 class="bucket-title">${escapeHtml(bucket.title)}</h3>
      <div class="bucket-items">
        ${(bucket.items || []).map(item => `
          <div class="bucket-item" data-loop-id="${item.id}">
            <span class="item-text">${escapeHtml(item.raw_text || item.title || 'Untitled')}</span>
            ${item.time_minutes ? `<span class="item-meta">${item.time_minutes}m</span>` : ''}
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');

  nextBucketsEl.innerHTML = html;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
