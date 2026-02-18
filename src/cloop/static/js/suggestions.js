/**
 * suggestions.js - Suggestions UI
 *
 * Purpose:
 *   Display and manage AI suggestions for loops.
 *
 * Responsibilities:
 *   - Fetch suggestions from API
 *   - Render suggestion badges and panels
 *   - Apply/reject suggestions
 *   - Show conflicts and clarifications
 *
 * Non-scope:
 *   - Loop rendering (see render.js)
 *   - API calls (see api.js)
 */

import * as api from './api.js';
import { escapeHtml } from './utils.js';
import { refreshLoop } from './loop.js';

/**
 * Fetch suggestions for a loop
 */
async function fetchLoopSuggestions(loopId) {
  try {
    return await api.fetchSuggestions(loopId, true);
  } catch (err) {
    console.error("fetchLoopSuggestions error:", err);
    return [];
  }
}

/**
 * Render suggestion badge and panel on a loop card
 */
export function renderSuggestionPanel(loopCard, loop) {
  const suggestionPanel = document.createElement('div');
  suggestionPanel.className = 'suggestion-panel';
  suggestionPanel.id = `suggestions-${loop.id}`;

  fetchLoopSuggestions(loop.id).then(suggestions => {
    if (suggestions.length === 0) return;

    const suggestion = suggestions[0];  // Show most recent pending
    let parsed;
    try {
      parsed = suggestion.parsed || JSON.parse(suggestion.suggestion_json);
    } catch (e) {
      console.error("Failed to parse suggestion_json:", e);
      return;
    }

    // Create badge
    const badges = loopCard.querySelector('.badges');
    if (!badges) return;

    const badge = document.createElement('span');
    badge.className = 'suggestion-badge';
    badge.innerHTML = `💡 ${suggestions.length} suggestion${suggestions.length > 1 ? 's' : ''}`;
    badge.onclick = (e) => {
      e.stopPropagation();
      suggestionPanel.classList.toggle('visible');
    };
    badges.appendChild(badge);

    // Build panel content
    let fieldsHtml = '';
    const fieldLabels = {
      title: 'Title', summary: 'Summary', next_action: 'Next Action',
      tags: 'Tags', project: 'Project', due_at: 'Due',
      urgency: 'Urgency', importance: 'Importance'
    };

    for (const [field, label] of Object.entries(fieldLabels)) {
      const value = parsed[field];
      if (value === null || value === undefined) continue;

      const currentValue = (loop && loop[field]) || '';
      const isConflict = currentValue && currentValue !== value;

      fieldsHtml += `
        <div class="suggestion-field">
          <input type="checkbox" class="suggestion-field-checkbox"
                 data-field="${field}" checked>
          <span class="suggestion-field-label">${label}:</span>
          <span class="suggestion-field-value ${isConflict ? 'conflict' : ''}"
                title="${isConflict ? 'Current: ' + currentValue : ''}">
            ${Array.isArray(value) ? value.join(', ') : value}
          </span>
        </div>
      `;
    }

    // Needs clarification section
    let clarifyHtml = '';
    if (parsed.needs_clarification && parsed.needs_clarification.length > 0) {
      clarifyHtml = `
        <div class="needs-clarification">
          <div class="needs-clarification-title">AI needs clarification:</div>
          ${parsed.needs_clarification.map(q =>
            `<div class="needs-clarification-item">${q}</div>`
          ).join('')}
        </div>
      `;
    }

    suggestionPanel.innerHTML = `
      <div class="suggestion-header">
        <span class="suggestion-title">AI Suggestion #${suggestion.id}</span>
        <span style="font-size: 11px; color: var(--muted);">
          Confidence: ${Math.round((parsed.confidence?.title || 0.5) * 100)}%
        </span>
      </div>
      <div class="suggestion-fields">${fieldsHtml}</div>
      ${clarifyHtml}
      <div class="suggestion-actions">
        <button class="suggestion-btn suggestion-btn-reject"
                data-action="reject-suggestion"
                data-suggestion-id="${suggestion.id}"
                data-loop-id="${loop.id}">
          Reject
        </button>
        <button class="suggestion-btn suggestion-btn-apply"
                data-action="apply-suggestion"
                data-suggestion-id="${suggestion.id}"
                data-loop-id="${loop.id}">
          Apply Selected
        </button>
      </div>
    `;
  });

  loopCard.appendChild(suggestionPanel);
}

/**
 * Apply a suggestion
 */
export async function applySuggestion(suggestionId, loopId, panel) {
  const checkboxes = panel.querySelectorAll('.suggestion-field-checkbox:checked');
  const fields = Array.from(checkboxes).map(cb => cb.dataset.field);

  try {
    await api.applySuggestion(suggestionId, fields.length > 0 ? fields : null);
    refreshLoop(loopId);
  } catch (err) {
    console.error("applySuggestion error:", err);
    alert('Failed to apply: ' + err.message);
  }
}

/**
 * Reject a suggestion
 */
export async function rejectSuggestion(suggestionId, loopId, panel, badge) {
  if (!confirm('Reject this suggestion?')) return;

  try {
    await api.rejectSuggestion(suggestionId);

    // Remove panel and badge
    if (badge && badge.classList.contains('suggestion-badge')) {
      badge.remove();
    }
    panel.remove();
  } catch (err) {
    console.error("rejectSuggestion error:", err);
    alert('Failed to reject: ' + err.message);
  }
}

/**
 * Setup suggestion event handlers
 */
export function setupSuggestionHandlers() {
  document.addEventListener('click', async (e) => {
    const applyBtn = e.target.closest('[data-action="apply-suggestion"]');
    if (applyBtn) {
      const suggestionId = parseInt(applyBtn.dataset.suggestionId);
      const loopId = parseInt(applyBtn.dataset.loopId);
      const panel = applyBtn.closest('.suggestion-panel');
      await applySuggestion(suggestionId, loopId, panel);
      return;
    }

    const rejectBtn = e.target.closest('[data-action="reject-suggestion"]');
    if (rejectBtn) {
      const suggestionId = parseInt(rejectBtn.dataset.suggestionId);
      const loopId = parseInt(rejectBtn.dataset.loopId);
      const panel = rejectBtn.closest('.suggestion-panel');
      const badge = panel?.previousElementSibling;
      await rejectSuggestion(suggestionId, loopId, panel, badge);
      return;
    }
  });
}
