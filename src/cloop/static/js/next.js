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
import { renderLoop } from './render.js';

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

  nextBucketsEl.innerHTML = "";

  buckets.forEach((bucket) => {
    const section = document.createElement("section");
    section.className = `next-bucket bucket-${bucket.key}`;
    section.innerHTML = `
      <div class="next-bucket-header">
        <div>
          <h3 class="next-bucket-title">${escapeHtml(bucket.title)}</h3>
          <p class="next-bucket-description">${escapeHtml(getBucketDescription(bucket.key))}</p>
        </div>
        <span class="next-bucket-count">${bucket.items.length}</span>
      </div>
      <div class="next-bucket-list"></div>
    `;

    const list = section.querySelector(".next-bucket-list");
    (bucket.items || []).forEach((item) => {
      list?.appendChild(renderLoop(item));
    });

    nextBucketsEl.appendChild(section);
  });
}

function getBucketDescription(key) {
  switch (key) {
    case "due_soon":
      return "Time-sensitive work that needs attention quickly.";
    case "quick_wins":
      return "Low-friction tasks you can finish fast.";
    case "high_leverage":
      return "Important work with outsized payoff.";
    case "standard":
      return "Solid actionable work to pick up next.";
    default:
      return "Actionable loops ready to move.";
  }
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
