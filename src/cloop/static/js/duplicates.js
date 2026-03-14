/**
 * duplicates.js - Merge modal and duplicate detection
 *
 * Purpose:
 *   Handle duplicate detection and merge workflow.
 *
 * Responsibilities:
 *   - Check for duplicate candidates
 *   - Show duplicate badges on loops
 *   - Render merge modal with comparison
 *   - Execute merge operation
 *
 * Non-scope:
 *   - Loop rendering (see render.js)
 *   - API calls (see api.js)
 */

import * as api from './api.js';
import * as modals from './modals.js';
import { loadInbox } from './loop.js';

let currentDuplicateLoopId = null;
let currentSurvivingLoopId = null;
let currentMergePreview = null;

/**
 * Check for duplicates on all visible loops
 */
export async function checkAndShowDuplicateBadges() {
  const cards = document.querySelectorAll('.loop-card[data-loop-id]');
  for (const card of cards) {
    const loopId = card.dataset.loopId;
    if (!loopId) continue;
    await checkDuplicateStatus(parseInt(loopId, 10), card);
  }
}

/**
 * Check duplicate status for a single loop
 */
async function checkDuplicateStatus(loopId, card) {
  try {
    const data = await api.fetchDuplicateCandidates(loopId);
    if (data?.candidates?.length > 0) {
      showDuplicateBadge(card, loopId, data.candidates);
    }
  } catch (err) {
    console.warn('Failed to check duplicate status:', err);
  }
}

/**
 * Show duplicate badge on a loop card
 */
function showDuplicateBadge(card, loopId, candidates) {
  const badges = card.querySelector('.badges');
  if (!badges) return;

  // Check if badge already exists
  if (badges.querySelector('.duplicate-badge')) return;

  const badge = document.createElement('span');
  badge.className = 'duplicate-badge';
  badge.innerHTML = `Possible duplicate`;
  badge.onclick = (e) => {
    e.stopPropagation();
    openMergeModal(loopId, candidates[0].loop_id);
  };
  badges.appendChild(badge);
}

/**
 * Open merge modal
 */
export async function openMergeModal(duplicateLoopId, survivingLoopId) {
  currentDuplicateLoopId = duplicateLoopId;
  currentSurvivingLoopId = survivingLoopId;

  try {
    currentMergePreview = await api.fetchMergePreview(duplicateLoopId, survivingLoopId);
    renderMergeModal(currentMergePreview);
    document.getElementById('mergeModal').classList.add('visible');
  } catch (err) {
    console.error('Failed to load merge preview:', err);
    await modals.alertDialog({
      title: "Could Not Load Merge Preview",
      description: err.message,
      eyebrow: "Duplicates",
    });
  }
}

/**
 * Render merge modal content
 */
function renderMergeModal(preview) {
  // Surviving loop content
  const survivingHtml = `
    <div class="merge-field">
      <div class="merge-field-label">Title</div>
      <div class="merge-field-value ${preview.field_conflicts.title ? 'conflict' : ''}">${preview.merged_title || '<em>empty</em>'}</div>
    </div>
    <div class="merge-field">
      <div class="merge-field-label">Summary</div>
      <div class="merge-field-value ${preview.field_conflicts.summary ? 'conflict' : ''}">${preview.merged_summary || '<em>empty</em>'}</div>
    </div>
    <div class="merge-field">
      <div class="merge-field-label">Next Action</div>
      <div class="merge-field-value ${preview.field_conflicts.next_action ? 'conflict' : ''}">${preview.merged_next_action || '<em>empty</em>'}</div>
    </div>
    <div class="merge-field">
      <div class="merge-field-label">Tags</div>
      <div class="merge-field-value">${preview.merged_tags.join(', ') || '<em>none</em>'}</div>
    </div>
  `;

  document.getElementById('mergeSurvivingContent').innerHTML = survivingHtml;

  // Duplicate side shows link to the loop
  const duplicateHtml = `
    <div class="merge-field">
      <div class="merge-field-label">Loop ID</div>
      <div class="merge-field-value">#${preview.duplicate_loop_id}</div>
    </div>
    <p style="color: var(--muted); font-size: 13px; margin-top: 12px;">
      This loop will be closed with status "dropped" after merge.
    </p>
  `;

  document.getElementById('mergeDuplicateContent').innerHTML = duplicateHtml;
}

/**
 * Close merge modal
 */
export function closeMergeModal() {
  document.getElementById('mergeModal').classList.remove('visible');
  currentDuplicateLoopId = null;
  currentSurvivingLoopId = null;
  currentMergePreview = null;
}

/**
 * Confirm and execute merge
 */
export async function confirmMerge() {
  if (!currentDuplicateLoopId || !currentSurvivingLoopId) return;

  try {
    await api.mergeLoops(currentDuplicateLoopId, currentSurvivingLoopId, {});
    closeMergeModal();
    // Reload to show updated state across inbox and review surfaces
    await loadInbox();
    const review = await import('./review.js');
    await review.loadRelationshipReviewQueue();
  } catch (err) {
    console.error('Merge failed:', err);
    await modals.alertDialog({
      title: "Merge Failed",
      description: err.message,
      eyebrow: "Duplicates",
    });
  }
}

/**
 * Setup merge modal event handlers
 */
export function setupMergeHandlers() {
  // Close merge modal on escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const mergeModal = document.getElementById('mergeModal');
      if (mergeModal?.classList.contains('visible')) {
        closeMergeModal();
      }
    }
  });
}
