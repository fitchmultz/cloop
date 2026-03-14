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
import * as modals from './modals.js';
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
    const clarificationItems = Array.isArray(suggestion.clarifications)
      ? suggestion.clarifications
      : [];
    if (clarificationItems.length > 0) {
      clarifyHtml = `
        <div class="needs-clarification">
          <div class="needs-clarification-title">AI needs clarification:</div>
          ${clarificationItems.map((clarification) => `
            <div class="needs-clarification-item">
              <div class="clarification-question">${escapeHtml(clarification.question)}</div>
              <input type="text"
                     class="clarification-input"
                     data-clarification-id="${clarification.id}"
                     placeholder="Type your answer...">
            </div>
          `).join('')}
          <button class="clarification-submit-btn"
                  data-action="submit-clarification"
                  data-loop-id="${loop.id}"
                  data-suggestion-id="${suggestion.id}">
            Submit Answers & Re-enrich
          </button>
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
    await modals.alertDialog({
      title: "Could Not Apply Suggestion",
      description: err.message,
      eyebrow: "Suggestions",
    });
  }
}

/**
 * Reject a suggestion
 */
export async function rejectSuggestion(suggestionId, loopId, panel, badge) {
  const confirmed = await modals.confirmDialog({
    eyebrow: "Suggestions",
    title: "Reject Suggestion",
    description: "Discard this suggestion for the current loop?",
    confirmLabel: "Reject suggestion",
    confirmVariant: "danger",
  });
  if (!confirmed) return;

  try {
    await api.rejectSuggestion(suggestionId);

    // Remove panel and badge
    if (badge && badge.classList.contains('suggestion-badge')) {
      badge.remove();
    }
    panel.remove();
  } catch (err) {
    console.error("rejectSuggestion error:", err);
    await modals.alertDialog({
      title: "Could Not Reject Suggestion",
      description: err.message,
      eyebrow: "Suggestions",
    });
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

    const clarifyBtn = e.target.closest('[data-action="submit-clarification"]');
    if (clarifyBtn) {
      const loopId = parseInt(clarifyBtn.dataset.loopId);
      const panel = clarifyBtn.closest('.suggestion-panel');
      await submitClarificationAnswers(loopId, panel);
      return;
    }
  });
}

/**
 * Submit clarification answers
 */
async function submitClarificationAnswers(loopId, panel) {
  const inputs = panel.querySelectorAll('.clarification-input');
  const answers = [];

  inputs.forEach(input => {
    const clarificationId = Number.parseInt(input.dataset.clarificationId || '', 10);
    const answer = input.value.trim();
    if (Number.isInteger(clarificationId) && answer) {
      answers.push({ clarification_id: clarificationId, answer });
    }
  });

  if (answers.length === 0) {
    await modals.alertDialog({
      title: "Add At Least One Answer",
      description: "The assistant needs at least one clarification response before it can re-enrich this loop.",
      eyebrow: "Suggestions",
    });
    return;
  }

  try {
    const result = await api.submitClarification(loopId, answers);
    await modals.alertDialog({
      title: "Clarification Submitted",
      description: result.message,
      eyebrow: "Suggestions",
    });

    // Trigger re-enrichment
    await api.enrichLoop(loopId);

    // Refresh the loop to show updated suggestions
    refreshLoop(loopId);
  } catch (err) {
    console.error("submitClarificationAnswers error:", err);
    await modals.alertDialog({
      title: "Could Not Submit Clarification",
      description: err.message,
      eyebrow: "Suggestions",
    });
  }
}
