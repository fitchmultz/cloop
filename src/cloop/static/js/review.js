/**
 * review.js - Review tab functionality
 *
 * Purpose:
 *   Display and manage loop review cohorts (daily/weekly).
 *
 * Responsibilities:
 *   - Load review data from API
 *   - Render cohort cards with items
 *   - Handle review mode toggle (daily/weekly)
 *   - Navigate to loops from review
 *
 * Non-scope:
 *   - Loop editing (see loop.js)
 *   - Tab switching (see init.js)
 *   - Metrics display (see init.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { escapeHtml, formatTime } from './utils.js';

let reviewCohorts;

const COHORT_CONFIG = {
  stale: { icon: "🕰️", title: "Stale Loops" },
  no_next_action: { icon: "⚠️", title: "Missing Next Action" },
  blocked_too_long: { icon: "🚧", title: "Blocked Too Long" },
  due_soon_unplanned: { icon: "⏰", title: "Due Soon (Unplanned)" }
};

/**
 * Initialize review module
 */
export function init(elements) {
  reviewCohorts = elements.reviewCohorts;
}

/**
 * Format cohort name for display
 */
function formatCohortName(name) {
  return name.replace(/_/g, " ");
}

/**
 * Render a single cohort
 */
function renderReviewCohort(cohort) {
  const config = COHORT_CONFIG[cohort.cohort] || { icon: "📋", title: formatCohortName(cohort.cohort) };
  const card = document.createElement("div");
  card.className = "cohort-card";

  const hasItems = cohort.items && cohort.items.length > 0;
  const countClass = cohort.count > 0 ? "alert" : "";

  let itemsHtml = "";
  if (hasItems) {
    itemsHtml = cohort.items.map(item => `
      <div class="cohort-item">
        <span class="cohort-item-link" data-loop-id="${item.id}">
          ${escapeHtml(item.title || item.raw_text || "Untitled")}
        </span>
        <span class="cohort-item-status">${item.status}</span>
      </div>
    `).join("");
  } else {
    itemsHtml = '<div class="cohort-empty">No items in this cohort</div>';
  }

  card.innerHTML = `
    <div class="cohort-header">
      <span class="cohort-name">${config.icon} ${config.title}</span>
      <span class="cohort-count ${countClass}">${cohort.count} items</span>
    </div>
    <div class="cohort-items">${itemsHtml}</div>
  `;

  return card;
}

/**
 * Load review data from API
 */
export async function loadReviewData() {
  if (!reviewCohorts) return;

  reviewCohorts.innerHTML = '<div class="cohort-loading">Loading review data...</div>';

  try {
    const data = await api.fetchReviewData();
    state.updateState({ reviewData: data });
    renderReviewCohorts();
  } catch (err) {
    console.error("loadReview error:", err);
    reviewCohorts.innerHTML = '<div class="cohort-empty">Error loading review data.</div>';
  }
}

/**
 * Render cohorts based on current review mode
 */
export function renderReviewCohorts() {
  if (!reviewCohorts || !state.state.reviewData) return;

  reviewCohorts.innerHTML = "";

  const cohorts = state.state.reviewMode === "daily"
    ? state.state.reviewData.daily
    : state.state.reviewData.weekly;

  if (!cohorts || cohorts.length === 0) {
    reviewCohorts.innerHTML = '<div class="cohort-empty">No cohorts available.</div>';
    return;
  }

  cohorts.forEach(cohort => {
    reviewCohorts.appendChild(renderReviewCohort(cohort));
  });
}

/**
 * Set review mode and re-render
 */
export function setReviewMode(mode) {
  state.updateState({ reviewMode: mode });
  renderReviewCohorts();
}
