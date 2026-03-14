/**
 * review.js - Review tab functionality
 *
 * Purpose:
 *   Display and manage loop review cohorts plus duplicate/related-loop review.
 *
 * Responsibilities:
 *   - Load review cohorts from API
 *   - Load relationship-review queue from API
 *   - Handle review mode toggle (daily/weekly)
 *   - Confirm, dismiss, or merge relationship candidates
 *
 * Non-scope:
 *   - Loop editing (see loop.js)
 *   - Tab switching (see init.js)
 *   - Metrics display (see init.js)
 */

import * as api from './api.js';
import * as state from './state.js';
import { escapeHtml } from './utils.js';
import { loadInbox } from './loop.js';
import { openMergeModal } from './duplicates.js';

let reviewCohorts;
let reviewRelationshipQueue;
let reviewRelationshipStatus;
let reviewRelationshipKind;
let reviewRelationshipRefresh;
let reviewStatus;

const COHORT_CONFIG = {
  stale: { icon: "🕰️", title: "Stale Loops" },
  no_next_action: { icon: "⚠️", title: "Missing Next Action" },
  blocked_too_long: { icon: "🚧", title: "Blocked Too Long" },
  due_soon_unplanned: { icon: "⏰", title: "Due Soon (Unplanned)" },
};

export function init(elements) {
  reviewCohorts = elements.reviewCohorts;
  reviewRelationshipQueue = elements.reviewRelationshipQueue;
  reviewRelationshipStatus = elements.reviewRelationshipStatus;
  reviewRelationshipKind = elements.reviewRelationshipKind;
  reviewRelationshipRefresh = elements.reviewRelationshipRefresh;
  reviewStatus = elements.reviewStatus;

  reviewRelationshipQueue?.addEventListener('click', handleRelationshipQueueClick);
  reviewRelationshipStatus?.addEventListener('change', () => {
    void loadRelationshipReviewQueue();
  });
  reviewRelationshipKind?.addEventListener('change', () => {
    void loadRelationshipReviewQueue();
  });
  reviewRelationshipRefresh?.addEventListener('click', () => {
    void loadRelationshipReviewQueue();
  });
}

function formatCohortName(name) {
  return name.replace(/_/g, ' ');
}

function renderReviewCohort(cohort) {
  const config = COHORT_CONFIG[cohort.cohort] || { icon: '📋', title: formatCohortName(cohort.cohort) };
  const card = document.createElement('div');
  card.className = 'cohort-card';

  const hasItems = cohort.items && cohort.items.length > 0;
  const countClass = cohort.count > 0 ? 'alert' : '';

  let itemsHtml = '';
  if (hasItems) {
    itemsHtml = cohort.items.map((item) => `
      <div class="cohort-item">
        <span class="cohort-item-link" data-loop-id="${item.id}">
          ${escapeHtml(item.title || item.raw_text || 'Untitled')}
        </span>
        <span class="cohort-item-status">${escapeHtml(item.status)}</span>
      </div>
    `).join('');
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

function renderCandidateActions(loopId, candidate, suggestedType) {
  const candidateId = Number(candidate.id);
  const confirmLabel = suggestedType === 'duplicate' ? 'Confirm duplicate' : 'Confirm related';
  const extraAction = suggestedType === 'related'
    ? `<button type="button" class="secondary" data-action="relationship-confirm" data-loop-id="${loopId}" data-candidate-id="${candidateId}" data-relationship-type="duplicate">Mark duplicate</button>`
    : `<button type="button" class="secondary" data-action="relationship-merge" data-loop-id="${loopId}" data-candidate-id="${candidateId}">Merge into this loop</button>`;

  return `
    <div class="relationship-candidate-actions">
      <button type="button" data-action="relationship-confirm" data-loop-id="${loopId}" data-candidate-id="${candidateId}" data-relationship-type="${suggestedType}">${confirmLabel}</button>
      ${extraAction}
      <button type="button" class="secondary" data-action="relationship-dismiss" data-loop-id="${loopId}" data-candidate-id="${candidateId}" data-relationship-type="${suggestedType}">Dismiss</button>
    </div>
  `;
}

function renderCandidateList(loopId, title, candidates, emptyMessage) {
  if (!candidates.length) {
    return `
      <section class="relationship-candidate-group empty">
        <div class="relationship-candidate-group-header">
          <h4>${escapeHtml(title)}</h4>
        </div>
        <p class="cohort-empty">${escapeHtml(emptyMessage)}</p>
      </section>
    `;
  }

  return `
    <section class="relationship-candidate-group">
      <div class="relationship-candidate-group-header">
        <h4>${escapeHtml(title)}</h4>
        <span class="cohort-count alert">${candidates.length} shown</span>
      </div>
      <div class="relationship-candidate-list">
        ${candidates.map((candidate) => `
          <article class="relationship-candidate-card relationship-candidate-${escapeHtml(candidate.relationship_type)}">
            <div class="relationship-candidate-meta">
              <span class="relationship-candidate-score">${escapeHtml(candidate.score.toFixed(3))}</span>
              <span class="relationship-candidate-status">${escapeHtml(candidate.status)}</span>
            </div>
            <h5>${escapeHtml(candidate.title || candidate.raw_text || 'Untitled')}</h5>
            <p class="relationship-candidate-preview">${escapeHtml(candidate.raw_text_preview || candidate.raw_text || '')}</p>
            ${renderCandidateActions(loopId, candidate, candidate.relationship_type)}
          </article>
        `).join('')}
      </div>
    </section>
  `;
}

function renderRelationshipQueueItem(item) {
  const loop = item.loop;
  const card = document.createElement('article');
  card.className = 'relationship-review-card';
  card.dataset.loopId = String(loop.id);

  card.innerHTML = `
    <div class="relationship-review-card-header">
      <div>
        <p class="support-eyebrow">Loop #${loop.id}</p>
        <h3>${escapeHtml(loop.title || loop.raw_text || 'Untitled')}</h3>
        <p class="relationship-review-loop-preview">${escapeHtml(loop.summary || loop.raw_text || '')}</p>
      </div>
      <div class="relationship-review-card-badges">
        <span class="cohort-count alert">Duplicates ${item.duplicate_count}</span>
        <span class="cohort-count">Related ${item.related_count}</span>
      </div>
    </div>
    <div class="relationship-review-card-groups">
      ${renderCandidateList(loop.id, 'Duplicate candidates', item.duplicate_candidates, 'No duplicate candidates in this scope.')}
      ${renderCandidateList(loop.id, 'Related candidates', item.related_candidates, 'No related candidates in this scope.')}
    </div>
  `;

  return card;
}

export async function loadReviewData() {
  if (reviewCohorts) {
    reviewCohorts.innerHTML = '<div class="cohort-loading">Loading review cohorts...</div>';
  }
  if (reviewRelationshipQueue) {
    reviewRelationshipQueue.innerHTML = '<div class="cohort-loading">Loading relationship review queue...</div>';
  }

  try {
    const [cohortData] = await Promise.all([
      api.fetchReviewData(),
      loadRelationshipReviewQueue(),
    ]);
    state.updateState({ reviewData: cohortData });
    renderReviewCohorts();
  } catch (err) {
    console.error('loadReview error:', err);
    if (reviewCohorts) {
      reviewCohorts.innerHTML = '<div class="cohort-empty">Error loading review data.</div>';
    }
    if (reviewStatus) {
      reviewStatus.textContent = err.message || 'Failed to load review workspace.';
    }
  }
}

export async function loadRelationshipReviewQueue() {
  if (!reviewRelationshipQueue) return null;

  reviewRelationshipQueue.innerHTML = '<div class="cohort-loading">Loading relationship review queue...</div>';

  try {
    const data = await api.fetchRelationshipReviewQueue({
      status: reviewRelationshipStatus?.value || 'open',
      relationshipKind: reviewRelationshipKind?.value || 'all',
      limit: 25,
      candidateLimit: 3,
    });
    state.updateState({ relationshipReviewQueue: data });
    renderRelationshipReviewQueue();
    if (reviewStatus) {
      reviewStatus.textContent = data.indexed_count
        ? `Relationship review refreshed ${data.indexed_count} loop embeddings.`
        : `Relationship review found ${data.loop_count} loops with pending relationship work.`;
    }
    return data;
  } catch (err) {
    console.error('loadRelationshipReviewQueue error:', err);
    reviewRelationshipQueue.innerHTML = '<div class="cohort-empty">Error loading relationship review queue.</div>';
    if (reviewStatus) {
      reviewStatus.textContent = err.message || 'Failed to load relationship review queue.';
    }
    return null;
  }
}

export function renderReviewCohorts() {
  if (!reviewCohorts || !state.state.reviewData) return;

  reviewCohorts.innerHTML = '';

  const cohorts = state.state.reviewMode === 'daily'
    ? state.state.reviewData.daily
    : state.state.reviewData.weekly;

  if (!cohorts || cohorts.length === 0) {
    reviewCohorts.innerHTML = '<div class="cohort-empty">No cohorts available.</div>';
    return;
  }

  cohorts.forEach((cohort) => {
    reviewCohorts.appendChild(renderReviewCohort(cohort));
  });
}

export function renderRelationshipReviewQueue() {
  if (!reviewRelationshipQueue) return;
  const queue = state.state.relationshipReviewQueue;
  if (!queue) {
    reviewRelationshipQueue.innerHTML = '<div class="cohort-empty">No relationship review data loaded.</div>';
    return;
  }

  reviewRelationshipQueue.innerHTML = '';
  if (!queue.items || queue.items.length === 0) {
    reviewRelationshipQueue.innerHTML = '<div class="cohort-empty">No duplicate or related-loop review work in this scope.</div>';
    return;
  }

  queue.items.forEach((item) => {
    reviewRelationshipQueue.appendChild(renderRelationshipQueueItem(item));
  });
}

export function setReviewMode(mode) {
  state.updateState({ reviewMode: mode });
  renderReviewCohorts();
}

async function handleRelationshipQueueClick(event) {
  const button = event.target.closest('[data-action]');
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  const action = button.dataset.action;
  const loopId = Number(button.dataset.loopId);
  const candidateId = Number(button.dataset.candidateId);
  const relationshipType = button.dataset.relationshipType;

  try {
    if (action === 'relationship-confirm' && Number.isInteger(loopId) && Number.isInteger(candidateId) && relationshipType) {
      await api.confirmLoopRelationship(loopId, candidateId, relationshipType);
      await Promise.all([loadRelationshipReviewQueue(), loadInbox()]);
      return;
    }

    if (action === 'relationship-dismiss' && Number.isInteger(loopId) && Number.isInteger(candidateId) && relationshipType) {
      await api.dismissLoopRelationship(loopId, candidateId, relationshipType);
      await Promise.all([loadRelationshipReviewQueue(), loadInbox()]);
      return;
    }

    if (action === 'relationship-merge' && Number.isInteger(loopId) && Number.isInteger(candidateId)) {
      await openMergeModal(candidateId, loopId);
    }
  } catch (err) {
    console.error('relationship review action failed:', err);
    if (reviewStatus) {
      reviewStatus.textContent = err.message || 'Relationship review action failed.';
    }
  }
}
