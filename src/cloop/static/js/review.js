/**
 * review.js - Review tab functionality
 *
 * Purpose:
 *   Display operator review workspaces for saved relationship-review and
 *   enrichment-review sessions, alongside review cohorts and bulk enrichment.
 *
 * Responsibilities:
 *   - Load review cohorts from API
 *   - Load saved relationship/enrichment review actions and sessions
 *   - Render session-preserving filtered review workspaces
 *   - Execute review actions, clarification answers, and session navigation
 *   - Handle review mode toggle (daily/weekly)
 *   - Trigger bulk enrichment previews/runs
 *
 * Non-scope:
 *   - Loop editing (see loop.js)
 *   - Tab switching (see init.js)
 *   - Metrics display (see init.js)
 */

import * as api from './api.js';
import * as modals from './modals.js';
import * as state from './state.js';
import { escapeHtml } from './utils.js';
import { loadInbox } from './loop.js';
import { openMergeModal } from './duplicates.js';

let reviewCohorts;
let reviewRelationshipSessionSelect;
let reviewRelationshipSessionNew;
let reviewRelationshipSessionEdit;
let reviewRelationshipSessionDelete;
let reviewRelationshipSessionRefresh;
let reviewRelationshipActionSelect;
let reviewRelationshipActionNew;
let reviewRelationshipActionEdit;
let reviewRelationshipActionDelete;
let reviewRelationshipSessionStatus;
let reviewRelationshipSessionSummary;
let reviewRelationshipSessionList;
let reviewRelationshipSessionDetail;
let reviewEnrichmentSessionSelect;
let reviewEnrichmentSessionNew;
let reviewEnrichmentSessionEdit;
let reviewEnrichmentSessionDelete;
let reviewEnrichmentSessionRefresh;
let reviewEnrichmentActionSelect;
let reviewEnrichmentActionNew;
let reviewEnrichmentActionEdit;
let reviewEnrichmentActionDelete;
let reviewEnrichmentSessionStatus;
let reviewEnrichmentSessionSummary;
let reviewEnrichmentSessionList;
let reviewEnrichmentSessionDetail;
let reviewBulkEnrichQuery;
let reviewBulkEnrichLimit;
let reviewBulkEnrichPreview;
let reviewBulkEnrichRun;
let reviewBulkEnrichStatus;
let reviewBulkEnrichPreviewResults;
let reviewBulkEnrichRunResults;

const COHORT_CONFIG = {
  stale: { icon: '🕰️', title: 'Stale Loops' },
  no_next_action: { icon: '⚠️', title: 'Missing Next Action' },
  blocked_too_long: { icon: '🚧', title: 'Blocked Too Long' },
  due_soon_unplanned: { icon: '⏰', title: 'Due Soon (Unplanned)' },
};

const RELATIONSHIP_TYPE_LABELS = {
  duplicate: 'Duplicate',
  related: 'Related',
  suggested: 'Suggested',
};

const RELATIONSHIP_ACTION_LABELS = {
  confirm: 'Confirm',
  dismiss: 'Dismiss',
};

const ENRICHMENT_ACTION_LABELS = {
  apply: 'Apply',
  reject: 'Reject',
};

const ENRICHMENT_FIELD_LABELS = {
  title: 'Title',
  summary: 'Summary',
  next_action: 'Next action',
  tags: 'Tags',
  project: 'Project',
  due_at: 'Due',
  due_date: 'Due date',
  urgency: 'Urgency',
  importance: 'Importance',
  activation_energy: 'Activation energy',
  time_minutes: 'Minutes',
};

export function init(elements) {
  reviewCohorts = elements.reviewCohorts;
  reviewRelationshipSessionSelect = elements.reviewRelationshipSessionSelect;
  reviewRelationshipSessionNew = elements.reviewRelationshipSessionNew;
  reviewRelationshipSessionEdit = elements.reviewRelationshipSessionEdit;
  reviewRelationshipSessionDelete = elements.reviewRelationshipSessionDelete;
  reviewRelationshipSessionRefresh = elements.reviewRelationshipSessionRefresh;
  reviewRelationshipActionSelect = elements.reviewRelationshipActionSelect;
  reviewRelationshipActionNew = elements.reviewRelationshipActionNew;
  reviewRelationshipActionEdit = elements.reviewRelationshipActionEdit;
  reviewRelationshipActionDelete = elements.reviewRelationshipActionDelete;
  reviewRelationshipSessionStatus = elements.reviewRelationshipSessionStatus;
  reviewRelationshipSessionSummary = elements.reviewRelationshipSessionSummary;
  reviewRelationshipSessionList = elements.reviewRelationshipSessionList;
  reviewRelationshipSessionDetail = elements.reviewRelationshipSessionDetail;
  reviewEnrichmentSessionSelect = elements.reviewEnrichmentSessionSelect;
  reviewEnrichmentSessionNew = elements.reviewEnrichmentSessionNew;
  reviewEnrichmentSessionEdit = elements.reviewEnrichmentSessionEdit;
  reviewEnrichmentSessionDelete = elements.reviewEnrichmentSessionDelete;
  reviewEnrichmentSessionRefresh = elements.reviewEnrichmentSessionRefresh;
  reviewEnrichmentActionSelect = elements.reviewEnrichmentActionSelect;
  reviewEnrichmentActionNew = elements.reviewEnrichmentActionNew;
  reviewEnrichmentActionEdit = elements.reviewEnrichmentActionEdit;
  reviewEnrichmentActionDelete = elements.reviewEnrichmentActionDelete;
  reviewEnrichmentSessionStatus = elements.reviewEnrichmentSessionStatus;
  reviewEnrichmentSessionSummary = elements.reviewEnrichmentSessionSummary;
  reviewEnrichmentSessionList = elements.reviewEnrichmentSessionList;
  reviewEnrichmentSessionDetail = elements.reviewEnrichmentSessionDetail;
  reviewBulkEnrichQuery = elements.reviewBulkEnrichQuery;
  reviewBulkEnrichLimit = elements.reviewBulkEnrichLimit;
  reviewBulkEnrichPreview = elements.reviewBulkEnrichPreview;
  reviewBulkEnrichRun = elements.reviewBulkEnrichRun;
  reviewBulkEnrichStatus = elements.reviewBulkEnrichStatus;
  reviewBulkEnrichPreviewResults = elements.reviewBulkEnrichPreviewResults;
  reviewBulkEnrichRunResults = elements.reviewBulkEnrichRunResults;

  reviewRelationshipSessionSelect?.addEventListener('change', () => {
    void selectRelationshipSession(parseInteger(reviewRelationshipSessionSelect?.value));
  });
  reviewRelationshipSessionNew?.addEventListener('click', () => {
    void createRelationshipSession();
  });
  reviewRelationshipSessionEdit?.addEventListener('click', () => {
    void editRelationshipSession();
  });
  reviewRelationshipSessionDelete?.addEventListener('click', () => {
    void deleteRelationshipSession();
  });
  reviewRelationshipSessionRefresh?.addEventListener('click', () => {
    void loadRelationshipReviewWorkspace();
  });
  reviewRelationshipActionSelect?.addEventListener('change', () => {
    state.updateState({ reviewRelationshipActionId: parseInteger(reviewRelationshipActionSelect?.value) });
    renderRelationshipWorkspace();
  });
  reviewRelationshipActionNew?.addEventListener('click', () => {
    void createRelationshipAction();
  });
  reviewRelationshipActionEdit?.addEventListener('click', () => {
    void editRelationshipAction();
  });
  reviewRelationshipActionDelete?.addEventListener('click', () => {
    void deleteRelationshipAction();
  });
  reviewRelationshipSessionList?.addEventListener('click', handleRelationshipSessionListClick);
  reviewRelationshipSessionDetail?.addEventListener('click', handleRelationshipDetailClick);

  reviewEnrichmentSessionSelect?.addEventListener('change', () => {
    void selectEnrichmentSession(parseInteger(reviewEnrichmentSessionSelect?.value));
  });
  reviewEnrichmentSessionNew?.addEventListener('click', () => {
    void createEnrichmentSession();
  });
  reviewEnrichmentSessionEdit?.addEventListener('click', () => {
    void editEnrichmentSession();
  });
  reviewEnrichmentSessionDelete?.addEventListener('click', () => {
    void deleteEnrichmentSession();
  });
  reviewEnrichmentSessionRefresh?.addEventListener('click', () => {
    void loadEnrichmentReviewWorkspace();
  });
  reviewEnrichmentActionSelect?.addEventListener('change', () => {
    state.updateState({ reviewEnrichmentActionId: parseInteger(reviewEnrichmentActionSelect?.value) });
    renderEnrichmentWorkspace();
  });
  reviewEnrichmentActionNew?.addEventListener('click', () => {
    void createEnrichmentAction();
  });
  reviewEnrichmentActionEdit?.addEventListener('click', () => {
    void editEnrichmentAction();
  });
  reviewEnrichmentActionDelete?.addEventListener('click', () => {
    void deleteEnrichmentAction();
  });
  reviewEnrichmentSessionList?.addEventListener('click', handleEnrichmentSessionListClick);
  reviewEnrichmentSessionDetail?.addEventListener('click', handleEnrichmentDetailClick);

  reviewBulkEnrichPreview?.addEventListener('click', () => {
    void previewBulkEnrichment();
  });
  reviewBulkEnrichRun?.addEventListener('click', () => {
    void runBulkEnrichment();
  });
}

function parseInteger(value) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isInteger(parsed) ? parsed : null;
}

function formatCohortName(name) {
  return name.replace(/_/g, ' ');
}

function formatLoopTitle(loop) {
  return escapeHtml(loop?.title || loop?.raw_text || `Loop #${loop?.id ?? '—'}`);
}

function formatLoopPreview(loop) {
  return escapeHtml(loop?.summary || loop?.raw_text || 'No summary available.');
}

function formatSessionCount(currentIndex, total) {
  if (!Number.isInteger(currentIndex) || total <= 0) {
    return `${total} items`;
  }
  return `Item ${currentIndex + 1} of ${total}`;
}

function formatTimestamp(value) {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return escapeHtml(String(value));
  }
  return escapeHtml(date.toLocaleString());
}

function getRelationshipActions() {
  return Array.isArray(state.state.reviewRelationshipActions) ? state.state.reviewRelationshipActions : [];
}

function getRelationshipSessions() {
  return Array.isArray(state.state.reviewRelationshipSessions) ? state.state.reviewRelationshipSessions : [];
}

function getRelationshipSnapshot() {
  return state.state.reviewRelationshipSessionSnapshot;
}

function getSelectedRelationshipAction() {
  const selectedId = state.state.reviewRelationshipActionId;
  return getRelationshipActions().find((action) => action.id === selectedId) || null;
}

function getEnrichmentActions() {
  return Array.isArray(state.state.reviewEnrichmentActions) ? state.state.reviewEnrichmentActions : [];
}

function getEnrichmentSessions() {
  return Array.isArray(state.state.reviewEnrichmentSessions) ? state.state.reviewEnrichmentSessions : [];
}

function getEnrichmentSnapshot() {
  return state.state.reviewEnrichmentSessionSnapshot;
}

function getSelectedEnrichmentAction() {
  const selectedId = state.state.reviewEnrichmentActionId;
  return getEnrichmentActions().find((action) => action.id === selectedId) || null;
}

function choosePersistedId(items, persistedId) {
  if (!items.length) {
    return null;
  }
  return items.some((item) => item.id === persistedId) ? persistedId : items[0].id;
}

function populateSelect(selectEl, items, selectedId, placeholderText, getLabel) {
  if (!selectEl) {
    return;
  }

  selectEl.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = placeholderText;
  selectEl.appendChild(placeholder);

  items.forEach((item) => {
    const option = document.createElement('option');
    option.value = String(item.id);
    option.textContent = getLabel(item);
    option.selected = selectedId === item.id;
    selectEl.appendChild(option);
  });

  if (selectedId == null) {
    selectEl.value = '';
  }
}

function setRelationshipStatus(message) {
  if (reviewRelationshipSessionStatus) {
    reviewRelationshipSessionStatus.textContent = message;
  }
}

function setEnrichmentStatus(message) {
  if (reviewEnrichmentSessionStatus) {
    reviewEnrichmentSessionStatus.textContent = message;
  }
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

function renderSessionSummary(summaryEl, snapshot, summaryBits) {
  if (!summaryEl) {
    return;
  }
  if (!snapshot?.session) {
    summaryEl.innerHTML = '';
    return;
  }

  summaryEl.innerHTML = `
    <div class="review-session-chip-group">
      ${summaryBits.map((bit) => `<span class="review-session-chip">${escapeHtml(bit)}</span>`).join('')}
    </div>
  `;
}

function renderRelationshipSessionList() {
  if (!reviewRelationshipSessionList) {
    return;
  }
  const snapshot = getRelationshipSnapshot();
  if (!snapshot?.session) {
    reviewRelationshipSessionList.innerHTML = '<div class="review-session-empty">No relationship-review session selected.</div>';
    return;
  }
  if (!snapshot.items?.length) {
    reviewRelationshipSessionList.innerHTML = '<div class="review-session-empty">This relationship-review session currently has no queued items.</div>';
    return;
  }

  reviewRelationshipSessionList.innerHTML = snapshot.items.map((item, index) => {
    const isActive = snapshot.session.current_loop_id === item.loop.id;
    return `
      <button
        type="button"
        class="review-session-item ${isActive ? 'is-active' : ''}"
        data-action="relationship-select-loop"
        data-loop-id="${item.loop.id}"
      >
        <span class="review-session-item-order">${index + 1}</span>
        <span class="review-session-item-body">
          <span class="review-session-item-title">${formatLoopTitle(item.loop)}</span>
          <span class="review-session-item-copy">${formatLoopPreview(item.loop)}</span>
          <span class="review-session-item-meta">
            <span class="cohort-count alert">Duplicates ${item.duplicate_count}</span>
            <span class="cohort-count">Related ${item.related_count}</span>
          </span>
        </span>
      </button>
    `;
  }).join('');
}

function renderRelationshipPresetButton(loopId, candidate, selectedAction) {
  if (!selectedAction) {
    return '';
  }
  const isCompatible = selectedAction.relationship_type === 'suggested'
    || selectedAction.relationship_type === candidate.relationship_type;
  return `
    <button
      type="button"
      class="secondary"
      data-action="relationship-apply-preset"
      data-loop-id="${loopId}"
      data-candidate-id="${candidate.id}"
      data-candidate-type="${candidate.relationship_type}"
      data-action-id="${selectedAction.id}"
      ${isCompatible ? '' : 'disabled'}
      title="${isCompatible ? escapeHtml(selectedAction.name) : 'Selected action is not compatible with this candidate'}"
    >
      ${isCompatible ? `Use “${escapeHtml(selectedAction.name)}”` : `Preset “${escapeHtml(selectedAction.name)}” incompatible`}
    </button>
  `;
}

function renderRelationshipCandidateActions(loopId, candidate, selectedAction) {
  const confirmLabel = candidate.relationship_type === 'duplicate' ? 'Confirm duplicate' : 'Confirm related';
  const extraAction = candidate.relationship_type === 'duplicate'
    ? `
      <button type="button" class="secondary" data-action="relationship-merge" data-loop-id="${loopId}" data-candidate-id="${candidate.id}">
        Merge into current loop
      </button>
    `
    : `
      <button
        type="button"
        class="secondary"
        data-action="relationship-inline"
        data-loop-id="${loopId}"
        data-candidate-id="${candidate.id}"
        data-candidate-type="${candidate.relationship_type}"
        data-inline-action="confirm"
        data-relationship-type="duplicate"
      >
        Confirm as duplicate
      </button>
    `;

  return `
    <div class="relationship-candidate-actions">
      ${renderRelationshipPresetButton(loopId, candidate, selectedAction)}
      <button
        type="button"
        data-action="relationship-inline"
        data-loop-id="${loopId}"
        data-candidate-id="${candidate.id}"
        data-candidate-type="${candidate.relationship_type}"
        data-inline-action="confirm"
        data-relationship-type="${candidate.relationship_type}"
      >
        ${confirmLabel}
      </button>
      ${extraAction}
      <button
        type="button"
        class="secondary"
        data-action="relationship-inline"
        data-loop-id="${loopId}"
        data-candidate-id="${candidate.id}"
        data-candidate-type="${candidate.relationship_type}"
        data-inline-action="dismiss"
        data-relationship-type="${candidate.relationship_type}"
      >
        Dismiss
      </button>
    </div>
  `;
}

function renderRelationshipCandidateGroup(loopId, title, candidates, emptyMessage, selectedAction) {
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
            <h5>${formatLoopTitle(candidate)}</h5>
            <p class="relationship-candidate-preview">${escapeHtml(candidate.raw_text_preview || candidate.raw_text || '')}</p>
            ${renderRelationshipCandidateActions(loopId, candidate, selectedAction)}
          </article>
        `).join('')}
      </div>
    </section>
  `;
}

function renderRelationshipWorkspace() {
  const snapshot = getRelationshipSnapshot();
  const selectedAction = getSelectedRelationshipAction();

  populateSelect(
    reviewRelationshipSessionSelect,
    getRelationshipSessions(),
    state.state.reviewRelationshipSessionId,
    'No saved session',
    (session) => `${session.name} · ${session.query}`,
  );
  populateSelect(
    reviewRelationshipActionSelect,
    getRelationshipActions(),
    state.state.reviewRelationshipActionId,
    'No saved action',
    (action) => `${action.name} · ${RELATIONSHIP_ACTION_LABELS[action.action_type]} ${RELATIONSHIP_TYPE_LABELS[action.relationship_type]}`,
  );

  const relationshipBits = snapshot?.session
    ? [
        `Query: ${snapshot.session.query}`,
        `Kind: ${snapshot.session.relationship_kind}`,
        formatSessionCount(snapshot.current_index, snapshot.loop_count),
      ]
    : [];
  renderSessionSummary(reviewRelationshipSessionSummary, snapshot, relationshipBits);
  renderRelationshipSessionList();

  if (!reviewRelationshipSessionDetail) {
    return;
  }
  if (!snapshot?.session) {
    reviewRelationshipSessionDetail.innerHTML = '<div class="review-session-empty">Create or select a relationship-review session to start reviewing queued duplicate and related-loop decisions.</div>';
    return;
  }
  if (!snapshot.current_item) {
    reviewRelationshipSessionDetail.innerHTML = `
      <div class="review-session-empty">
        <h3>${escapeHtml(snapshot.session.name)}</h3>
        <p>This session is empty right now. Adjust the query or refresh after more relationship suggestions appear.</p>
      </div>
    `;
    return;
  }

  const item = snapshot.current_item;
  const canMovePrev = Number.isInteger(snapshot.current_index) && snapshot.current_index > 0;
  const canMoveNext = Number.isInteger(snapshot.current_index) && snapshot.current_index < snapshot.items.length - 1;

  reviewRelationshipSessionDetail.innerHTML = `
    <div class="review-session-card">
      <div class="review-session-card-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(snapshot.session.name)}</p>
          <h3>${formatLoopTitle(item.loop)}</h3>
          <p class="review-session-copy">${formatLoopPreview(item.loop)}</p>
        </div>
        <div class="review-session-card-actions">
          <button type="button" class="secondary" data-action="relationship-move" data-direction="prev" ${canMovePrev ? '' : 'disabled'}>Previous</button>
          <button type="button" class="secondary" data-action="relationship-move" data-direction="next" ${canMoveNext ? '' : 'disabled'}>Next</button>
        </div>
      </div>
      <div class="review-session-chip-group">
        <span class="review-session-chip">Loop #${item.loop.id}</span>
        <span class="review-session-chip">Duplicates ${item.duplicate_count}</span>
        <span class="review-session-chip">Related ${item.related_count}</span>
        ${selectedAction ? `<span class="review-session-chip">Selected action: ${escapeHtml(selectedAction.name)}</span>` : ''}
      </div>
      <div class="relationship-review-card-groups">
        ${renderRelationshipCandidateGroup(item.loop.id, 'Duplicate candidates', item.duplicate_candidates || [], 'No duplicate candidates remain in this session.', selectedAction)}
        ${renderRelationshipCandidateGroup(item.loop.id, 'Related candidates', item.related_candidates || [], 'No related candidates remain in this session.', selectedAction)}
      </div>
    </div>
  `;
}

function renderEnrichmentSessionList() {
  if (!reviewEnrichmentSessionList) {
    return;
  }
  const snapshot = getEnrichmentSnapshot();
  if (!snapshot?.session) {
    reviewEnrichmentSessionList.innerHTML = '<div class="review-session-empty">No enrichment-review session selected.</div>';
    return;
  }
  if (!snapshot.items?.length) {
    reviewEnrichmentSessionList.innerHTML = '<div class="review-session-empty">This enrichment-review session currently has no queued items.</div>';
    return;
  }

  reviewEnrichmentSessionList.innerHTML = snapshot.items.map((item, index) => {
    const isActive = snapshot.session.current_loop_id === item.loop.id;
    return `
      <button
        type="button"
        class="review-session-item ${isActive ? 'is-active' : ''}"
        data-action="enrichment-select-loop"
        data-loop-id="${item.loop.id}"
      >
        <span class="review-session-item-order">${index + 1}</span>
        <span class="review-session-item-body">
          <span class="review-session-item-title">${formatLoopTitle(item.loop)}</span>
          <span class="review-session-item-copy">${formatLoopPreview(item.loop)}</span>
          <span class="review-session-item-meta">
            <span class="cohort-count alert">Suggestions ${item.pending_suggestion_count}</span>
            <span class="cohort-count">Clarifications ${item.pending_clarification_count}</span>
          </span>
        </span>
      </button>
    `;
  }).join('');
}

function renderParsedSuggestionFields(suggestion) {
  const parsed = suggestion?.parsed && typeof suggestion.parsed === 'object' ? suggestion.parsed : {};
  const entries = Object.entries(parsed).filter(([field, value]) => {
    return !['confidence', 'needs_clarification'].includes(field) && value !== null && value !== undefined && value !== '';
  });
  if (!entries.length) {
    return '<div class="cohort-empty">No structured fields available in this suggestion.</div>';
  }

  return `
    <div class="review-suggestion-fields">
      ${entries.map(([field, value]) => `
        <div class="review-suggestion-field">
          <span class="review-suggestion-field-label">${escapeHtml(ENRICHMENT_FIELD_LABELS[field] || field)}</span>
          <span class="review-suggestion-field-value">${escapeHtml(Array.isArray(value) ? value.join(', ') : String(value))}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function renderEnrichmentPresetButton(suggestion, selectedAction) {
  if (!selectedAction) {
    return '';
  }
  return `
    <button
      type="button"
      class="secondary"
      data-action="enrichment-apply-preset"
      data-suggestion-id="${suggestion.id}"
      data-action-id="${selectedAction.id}"
    >
      Use “${escapeHtml(selectedAction.name)}”
    </button>
  `;
}

function renderSuggestionCard(suggestion, selectedAction) {
  return `
    <article class="review-suggestion-card">
      <div class="review-suggestion-card-header">
        <div>
          <p class="support-eyebrow">Suggestion #${suggestion.id}</p>
          <h4>${escapeHtml((suggestion.parsed?.title || suggestion.parsed?.summary || 'Pending suggestion'))}</h4>
        </div>
        <span class="review-session-chip">${escapeHtml(suggestion.model || 'unknown model')}</span>
      </div>
      ${renderParsedSuggestionFields(suggestion)}
      <div class="review-suggestion-actions">
        ${renderEnrichmentPresetButton(suggestion, selectedAction)}
        <button type="button" data-action="enrichment-inline" data-suggestion-id="${suggestion.id}" data-inline-action="apply">Apply</button>
        <button type="button" class="secondary" data-action="enrichment-inline" data-suggestion-id="${suggestion.id}" data-inline-action="reject">Reject</button>
      </div>
    </article>
  `;
}

function renderClarificationForm(item) {
  const clarifications = Array.isArray(item?.pending_clarifications) ? item.pending_clarifications : [];
  if (!clarifications.length) {
    return '<div class="review-session-empty">No pending clarifications for this loop.</div>';
  }

  return `
    <form class="review-clarification-form" data-loop-id="${item.loop.id}">
      <div class="review-clarification-list">
        ${clarifications.map((clarification) => `
          <label class="review-clarification-card" for="review-clarification-${clarification.id}">
            <span class="review-clarification-question">${escapeHtml(clarification.question)}</span>
            <input
              id="review-clarification-${clarification.id}"
              class="clarification-input"
              type="text"
              data-clarification-id="${clarification.id}"
              placeholder="Type an answer"
              autocomplete="off"
            >
          </label>
        `).join('')}
      </div>
      <div class="review-suggestion-actions">
        <button type="button" data-action="enrichment-submit-clarifications" data-loop-id="${item.loop.id}">
          Answer clarifications & re-enrich
        </button>
      </div>
    </form>
  `;
}

function renderEnrichmentWorkspace() {
  const snapshot = getEnrichmentSnapshot();
  const selectedAction = getSelectedEnrichmentAction();

  populateSelect(
    reviewEnrichmentSessionSelect,
    getEnrichmentSessions(),
    state.state.reviewEnrichmentSessionId,
    'No saved session',
    (session) => `${session.name} · ${session.query}`,
  );
  populateSelect(
    reviewEnrichmentActionSelect,
    getEnrichmentActions(),
    state.state.reviewEnrichmentActionId,
    'No saved action',
    (action) => {
      const detail = action.action_type === 'apply'
        ? (Array.isArray(action.fields) && action.fields.length ? action.fields.join(', ') : 'auto fields')
        : 'reject';
      return `${action.name} · ${ENRICHMENT_ACTION_LABELS[action.action_type]} ${detail}`;
    },
  );

  const enrichmentBits = snapshot?.session
    ? [
        `Query: ${snapshot.session.query}`,
        `Pending: ${snapshot.session.pending_kind}`,
        formatSessionCount(snapshot.current_index, snapshot.loop_count),
      ]
    : [];
  renderSessionSummary(reviewEnrichmentSessionSummary, snapshot, enrichmentBits);
  renderEnrichmentSessionList();

  if (!reviewEnrichmentSessionDetail) {
    return;
  }
  if (!snapshot?.session) {
    reviewEnrichmentSessionDetail.innerHTML = '<div class="review-session-empty">Create or select an enrichment-review session to step through pending suggestions and clarifications.</div>';
    return;
  }
  if (!snapshot.current_item) {
    reviewEnrichmentSessionDetail.innerHTML = `
      <div class="review-session-empty">
        <h3>${escapeHtml(snapshot.session.name)}</h3>
        <p>This session is empty right now. Refresh it after enrichment produces new suggestions or clarifications.</p>
      </div>
    `;
    return;
  }

  const item = snapshot.current_item;
  const canMovePrev = Number.isInteger(snapshot.current_index) && snapshot.current_index > 0;
  const canMoveNext = Number.isInteger(snapshot.current_index) && snapshot.current_index < snapshot.items.length - 1;

  reviewEnrichmentSessionDetail.innerHTML = `
    <div class="review-session-card">
      <div class="review-session-card-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(snapshot.session.name)}</p>
          <h3>${formatLoopTitle(item.loop)}</h3>
          <p class="review-session-copy">${formatLoopPreview(item.loop)}</p>
        </div>
        <div class="review-session-card-actions">
          <button type="button" class="secondary" data-action="enrichment-move" data-direction="prev" ${canMovePrev ? '' : 'disabled'}>Previous</button>
          <button type="button" class="secondary" data-action="enrichment-move" data-direction="next" ${canMoveNext ? '' : 'disabled'}>Next</button>
          <button type="button" class="secondary" data-action="enrichment-rerun" data-loop-id="${item.loop.id}">Re-enrich loop</button>
        </div>
      </div>
      <div class="review-session-chip-group">
        <span class="review-session-chip">Loop #${item.loop.id}</span>
        <span class="review-session-chip">Suggestions ${item.pending_suggestion_count}</span>
        <span class="review-session-chip">Clarifications ${item.pending_clarification_count}</span>
        <span class="review-session-chip">Newest pending ${formatTimestamp(item.newest_pending_at)}</span>
        ${selectedAction ? `<span class="review-session-chip">Selected action: ${escapeHtml(selectedAction.name)}</span>` : ''}
      </div>
      <div class="review-enrichment-sections">
        <section class="review-enrichment-section">
          <div class="relationship-candidate-group-header">
            <h4>Pending suggestions</h4>
            <span class="cohort-count alert">${item.pending_suggestion_count}</span>
          </div>
          <div class="review-suggestion-list">
            ${item.pending_suggestions?.length ? item.pending_suggestions.map((suggestion) => renderSuggestionCard(suggestion, selectedAction)).join('') : '<div class="review-session-empty">No pending suggestions for this loop.</div>'}
          </div>
        </section>
        <section class="review-enrichment-section">
          <div class="relationship-candidate-group-header">
            <h4>Pending clarifications</h4>
            <span class="cohort-count">${item.pending_clarification_count}</span>
          </div>
          ${renderClarificationForm(item)}
        </section>
      </div>
    </div>
  `;
}

async function fetchRelationshipWorkspaceData() {
  const [actions, sessions] = await Promise.all([
    api.fetchRelationshipReviewActions(),
    api.fetchRelationshipReviewSessions(),
  ]);
  const sessionId = choosePersistedId(sessions, state.state.reviewRelationshipSessionId);
  const actionId = choosePersistedId(actions, state.state.reviewRelationshipActionId);
  state.updateState({
    reviewRelationshipActions: actions,
    reviewRelationshipSessions: sessions,
    reviewRelationshipSessionId: sessionId,
    reviewRelationshipActionId: actionId,
  });
  return { actions, sessions, sessionId, actionId };
}

async function fetchEnrichmentWorkspaceData() {
  const [actions, sessions] = await Promise.all([
    api.fetchEnrichmentReviewActions(),
    api.fetchEnrichmentReviewSessions(),
  ]);
  const sessionId = choosePersistedId(sessions, state.state.reviewEnrichmentSessionId);
  const actionId = choosePersistedId(actions, state.state.reviewEnrichmentActionId);
  state.updateState({
    reviewEnrichmentActions: actions,
    reviewEnrichmentSessions: sessions,
    reviewEnrichmentSessionId: sessionId,
    reviewEnrichmentActionId: actionId,
  });
  return { actions, sessions, sessionId, actionId };
}

export async function loadReviewData() {
  if (reviewCohorts) {
    reviewCohorts.innerHTML = '<div class="cohort-loading">Loading review cohorts...</div>';
  }
  if (reviewRelationshipSessionList) {
    reviewRelationshipSessionList.innerHTML = '<div class="cohort-loading">Loading relationship review sessions...</div>';
  }
  if (reviewRelationshipSessionDetail) {
    reviewRelationshipSessionDetail.innerHTML = '<div class="cohort-loading">Loading relationship review details...</div>';
  }
  if (reviewEnrichmentSessionList) {
    reviewEnrichmentSessionList.innerHTML = '<div class="cohort-loading">Loading enrichment review sessions...</div>';
  }
  if (reviewEnrichmentSessionDetail) {
    reviewEnrichmentSessionDetail.innerHTML = '<div class="cohort-loading">Loading enrichment review details...</div>';
  }

  try {
    const [cohortData] = await Promise.all([
      api.fetchReviewData(),
      loadRelationshipReviewWorkspace(),
      loadEnrichmentReviewWorkspace(),
    ]);
    state.updateState({ reviewData: cohortData });
    renderReviewCohorts();
  } catch (err) {
    console.error('loadReviewData error:', err);
    if (reviewCohorts) {
      reviewCohorts.innerHTML = '<div class="cohort-empty">Error loading review data.</div>';
    }
    setRelationshipStatus(err.message || 'Failed to load the review workspace.');
    setEnrichmentStatus(err.message || 'Failed to load the review workspace.');
  }
}

export async function loadRelationshipReviewWorkspace() {
  try {
    const { sessionId } = await fetchRelationshipWorkspaceData();
    let snapshot = null;
    if (sessionId != null) {
      snapshot = await api.fetchRelationshipReviewSession(sessionId);
    }
    state.updateState({ reviewRelationshipSessionSnapshot: snapshot });
    renderRelationshipWorkspace();
    setRelationshipStatus(
      snapshot?.session
        ? `Loaded ${snapshot.session.name}. ${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? '' : 's'}.`
        : 'Create a saved relationship-review session to start stepping through filtered relationship work.',
    );
    return snapshot;
  } catch (err) {
    console.error('loadRelationshipReviewWorkspace error:', err);
    state.updateState({ reviewRelationshipSessionSnapshot: null });
    renderRelationshipWorkspace();
    setRelationshipStatus(err.message || 'Failed to load relationship review sessions.');
    return null;
  }
}

export async function loadRelationshipReviewQueue() {
  return loadRelationshipReviewWorkspace();
}

async function loadEnrichmentReviewWorkspace() {
  try {
    const { sessionId } = await fetchEnrichmentWorkspaceData();
    let snapshot = null;
    if (sessionId != null) {
      snapshot = await api.fetchEnrichmentReviewSession(sessionId);
    }
    state.updateState({ reviewEnrichmentSessionSnapshot: snapshot });
    renderEnrichmentWorkspace();
    setEnrichmentStatus(
      snapshot?.session
        ? `Loaded ${snapshot.session.name}. ${snapshot.loop_count} queued loop${snapshot.loop_count === 1 ? '' : 's'}.`
        : 'Create a saved enrichment-review session to step through pending suggestions and clarifications.',
    );
    return snapshot;
  } catch (err) {
    console.error('loadEnrichmentReviewWorkspace error:', err);
    state.updateState({ reviewEnrichmentSessionSnapshot: null });
    renderEnrichmentWorkspace();
    setEnrichmentStatus(err.message || 'Failed to load enrichment review sessions.');
    return null;
  }
}

async function selectRelationshipSession(sessionId) {
  state.updateState({
    reviewRelationshipSessionId: sessionId,
    reviewRelationshipSessionSnapshot: null,
  });
  renderRelationshipWorkspace();
  if (sessionId == null) {
    setRelationshipStatus('No relationship-review session selected.');
    return;
  }
  try {
    const snapshot = await api.fetchRelationshipReviewSession(sessionId);
    state.updateState({ reviewRelationshipSessionSnapshot: snapshot });
    renderRelationshipWorkspace();
    setRelationshipStatus(`Loaded ${snapshot.session.name}.`);
  } catch (err) {
    console.error('selectRelationshipSession error:', err);
    setRelationshipStatus(err.message || 'Failed to load relationship-review session.');
  }
}

async function selectEnrichmentSession(sessionId) {
  state.updateState({
    reviewEnrichmentSessionId: sessionId,
    reviewEnrichmentSessionSnapshot: null,
  });
  renderEnrichmentWorkspace();
  if (sessionId == null) {
    setEnrichmentStatus('No enrichment-review session selected.');
    return;
  }
  try {
    const snapshot = await api.fetchEnrichmentReviewSession(sessionId);
    state.updateState({ reviewEnrichmentSessionSnapshot: snapshot });
    renderEnrichmentWorkspace();
    setEnrichmentStatus(`Loaded ${snapshot.session.name}.`);
  } catch (err) {
    console.error('selectEnrichmentSession error:', err);
    setEnrichmentStatus(err.message || 'Failed to load enrichment-review session.');
  }
}

function validatePositiveInteger(value, label) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return `${label} must be a positive integer.`;
  }
  return null;
}

async function relationshipSessionDialog(existingSession = null) {
  const result = await modals.promptDialog({
    eyebrow: 'Relationship review',
    title: existingSession ? 'Edit review session' : 'Create review session',
    description: 'Persist a filtered relationship-review worklist so you can leave and return without losing your place.',
    confirmLabel: existingSession ? 'Save session' : 'Create session',
    fields: [
      {
        name: 'name',
        label: 'Session name',
        value: existingSession?.name || '',
        required: true,
        maxLength: 120,
        autocomplete: 'off',
      },
      {
        name: 'query',
        label: 'DSL query',
        value: existingSession?.query || 'status:open',
        required: true,
        maxLength: 500,
        autocomplete: 'off',
      },
      {
        name: 'relationship_kind',
        label: 'Relationship kind',
        type: 'select',
        value: existingSession?.relationship_kind || 'all',
        options: [
          { value: 'all', label: 'All' },
          { value: 'duplicate', label: 'Duplicates' },
          { value: 'related', label: 'Related' },
        ],
      },
      {
        name: 'candidate_limit',
        label: 'Candidates per loop',
        type: 'number',
        value: String(existingSession?.candidate_limit || 3),
        inputMode: 'numeric',
      },
      {
        name: 'item_limit',
        label: 'Loop limit',
        type: 'number',
        value: String(existingSession?.item_limit || 25),
        inputMode: 'numeric',
      },
    ],
    validate: (values) => {
      if (!values.name) {
        return 'Enter a session name.';
      }
      if (!values.query) {
        return 'Enter a DSL query.';
      }
      return validatePositiveInteger(values.candidate_limit, 'Candidates per loop')
        || validatePositiveInteger(values.item_limit, 'Loop limit');
    },
  });

  if (!result) {
    return null;
  }

  return {
    name: result.name,
    query: result.query,
    relationship_kind: result.relationship_kind,
    candidate_limit: Number.parseInt(result.candidate_limit, 10),
    item_limit: Number.parseInt(result.item_limit, 10),
  };
}

async function relationshipActionDialog(existingAction = null) {
  const result = await modals.promptDialog({
    eyebrow: 'Relationship review',
    title: existingAction ? 'Edit saved action' : 'Create saved action',
    description: 'Save a reusable duplicate or related-loop decision so repeated review work stays consistent.',
    confirmLabel: existingAction ? 'Save action' : 'Create action',
    fields: [
      {
        name: 'name',
        label: 'Action name',
        value: existingAction?.name || '',
        required: true,
        maxLength: 120,
        autocomplete: 'off',
      },
      {
        name: 'action_type',
        label: 'Action',
        type: 'select',
        value: existingAction?.action_type || 'confirm',
        options: [
          { value: 'confirm', label: 'Confirm' },
          { value: 'dismiss', label: 'Dismiss' },
        ],
      },
      {
        name: 'relationship_type',
        label: 'Relationship target',
        type: 'select',
        value: existingAction?.relationship_type || 'suggested',
        options: [
          { value: 'suggested', label: 'Use queued candidate type' },
          { value: 'duplicate', label: 'Duplicate only' },
          { value: 'related', label: 'Related only' },
        ],
      },
      {
        name: 'description',
        label: 'Description',
        type: 'textarea',
        rows: 3,
        value: existingAction?.description || '',
      },
    ],
    validate: (values) => (!values.name ? 'Enter an action name.' : null),
  });

  if (!result) {
    return null;
  }

  return {
    name: result.name,
    action_type: result.action_type,
    relationship_type: result.relationship_type,
    description: result.description || null,
  };
}

async function enrichmentSessionDialog(existingSession = null) {
  const result = await modals.promptDialog({
    eyebrow: 'Enrichment review',
    title: existingSession ? 'Edit review session' : 'Create review session',
    description: 'Persist a filtered suggestion and clarification queue so you can work through follow-ups without losing your place.',
    confirmLabel: existingSession ? 'Save session' : 'Create session',
    fields: [
      {
        name: 'name',
        label: 'Session name',
        value: existingSession?.name || '',
        required: true,
        maxLength: 120,
        autocomplete: 'off',
      },
      {
        name: 'query',
        label: 'DSL query',
        value: existingSession?.query || 'status:open',
        required: true,
        maxLength: 500,
        autocomplete: 'off',
      },
      {
        name: 'pending_kind',
        label: 'Pending work kind',
        type: 'select',
        value: existingSession?.pending_kind || 'all',
        options: [
          { value: 'all', label: 'Suggestions and clarifications' },
          { value: 'suggestions', label: 'Suggestions only' },
          { value: 'clarifications', label: 'Clarifications only' },
        ],
      },
      {
        name: 'suggestion_limit',
        label: 'Suggestions per loop',
        type: 'number',
        value: String(existingSession?.suggestion_limit || 3),
        inputMode: 'numeric',
      },
      {
        name: 'clarification_limit',
        label: 'Clarifications per loop',
        type: 'number',
        value: String(existingSession?.clarification_limit || 3),
        inputMode: 'numeric',
      },
      {
        name: 'item_limit',
        label: 'Loop limit',
        type: 'number',
        value: String(existingSession?.item_limit || 25),
        inputMode: 'numeric',
      },
    ],
    validate: (values) => {
      if (!values.name) {
        return 'Enter a session name.';
      }
      if (!values.query) {
        return 'Enter a DSL query.';
      }
      return validatePositiveInteger(values.suggestion_limit, 'Suggestions per loop')
        || validatePositiveInteger(values.clarification_limit, 'Clarifications per loop')
        || validatePositiveInteger(values.item_limit, 'Loop limit');
    },
  });

  if (!result) {
    return null;
  }

  return {
    name: result.name,
    query: result.query,
    pending_kind: result.pending_kind,
    suggestion_limit: Number.parseInt(result.suggestion_limit, 10),
    clarification_limit: Number.parseInt(result.clarification_limit, 10),
    item_limit: Number.parseInt(result.item_limit, 10),
  };
}

async function enrichmentActionDialog(existingAction = null) {
  const result = await modals.promptDialog({
    eyebrow: 'Enrichment review',
    title: existingAction ? 'Edit saved action' : 'Create saved action',
    description: 'Save a reusable suggestion follow-up action so repeated review work stays consistent.',
    confirmLabel: existingAction ? 'Save action' : 'Create action',
    fields: [
      {
        name: 'name',
        label: 'Action name',
        value: existingAction?.name || '',
        required: true,
        maxLength: 120,
        autocomplete: 'off',
      },
      {
        name: 'action_type',
        label: 'Action',
        type: 'select',
        value: existingAction?.action_type || 'apply',
        options: [
          { value: 'apply', label: 'Apply suggestion' },
          { value: 'reject', label: 'Reject suggestion' },
        ],
      },
      {
        name: 'fields',
        label: 'Apply fields (comma separated)',
        value: Array.isArray(existingAction?.fields) ? existingAction.fields.join(', ') : '',
        helpText: 'Leave blank to use the default auto-apply field set. Reject actions must leave this empty.',
      },
      {
        name: 'description',
        label: 'Description',
        type: 'textarea',
        rows: 3,
        value: existingAction?.description || '',
      },
    ],
    validate: (values) => {
      if (!values.name) {
        return 'Enter an action name.';
      }
      if (values.action_type === 'reject' && values.fields) {
        return 'Reject actions cannot define fields.';
      }
      return null;
    },
  });

  if (!result) {
    return null;
  }

  const fields = result.fields
    ? result.fields.split(',').map((field) => field.trim()).filter(Boolean)
    : null;

  return {
    name: result.name,
    action_type: result.action_type,
    fields,
    description: result.description || null,
  };
}

async function createRelationshipSession() {
  const payload = await relationshipSessionDialog();
  if (!payload) {
    return;
  }
  try {
    const snapshot = await api.createRelationshipReviewSession(payload);
    state.updateState({ reviewRelationshipSessionId: snapshot.session.id });
    await loadRelationshipReviewWorkspace();
    setRelationshipStatus(`Created ${snapshot.session.name}.`);
  } catch (err) {
    console.error('createRelationshipSession error:', err);
    setRelationshipStatus(err.message || 'Failed to create relationship-review session.');
  }
}

async function editRelationshipSession() {
  const snapshot = getRelationshipSnapshot();
  if (!snapshot?.session) {
    await modals.alertDialog({
      eyebrow: 'Relationship review',
      title: 'No Session Selected',
      description: 'Select a relationship-review session before editing it.',
    });
    return;
  }
  const payload = await relationshipSessionDialog(snapshot.session);
  if (!payload) {
    return;
  }
  try {
    const updated = await api.updateRelationshipReviewSession(snapshot.session.id, payload);
    state.updateState({ reviewRelationshipSessionId: updated.session.id, reviewRelationshipSessionSnapshot: updated });
    await loadRelationshipReviewWorkspace();
    setRelationshipStatus(`Saved ${updated.session.name}.`);
  } catch (err) {
    console.error('editRelationshipSession error:', err);
    setRelationshipStatus(err.message || 'Failed to update relationship-review session.');
  }
}

async function deleteRelationshipSession() {
  const snapshot = getRelationshipSnapshot();
  if (!snapshot?.session) {
    return;
  }
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Relationship review',
    title: 'Delete review session',
    description: `Delete “${snapshot.session.name}”? The saved session and cursor will be removed.`,
    confirmLabel: 'Delete session',
    confirmVariant: 'danger',
  });
  if (!confirmed) {
    return;
  }
  try {
    await api.deleteRelationshipReviewSession(snapshot.session.id);
    state.updateState({ reviewRelationshipSessionId: null, reviewRelationshipSessionSnapshot: null });
    await loadRelationshipReviewWorkspace();
    setRelationshipStatus('Deleted relationship-review session.');
  } catch (err) {
    console.error('deleteRelationshipSession error:', err);
    setRelationshipStatus(err.message || 'Failed to delete relationship-review session.');
  }
}

async function createRelationshipAction() {
  const payload = await relationshipActionDialog();
  if (!payload) {
    return;
  }
  try {
    const action = await api.createRelationshipReviewAction(payload);
    state.updateState({ reviewRelationshipActionId: action.id });
    await loadRelationshipReviewWorkspace();
    setRelationshipStatus(`Created action “${action.name}”.`);
  } catch (err) {
    console.error('createRelationshipAction error:', err);
    setRelationshipStatus(err.message || 'Failed to create relationship-review action.');
  }
}

async function editRelationshipAction() {
  const action = getSelectedRelationshipAction();
  if (!action) {
    await modals.alertDialog({
      eyebrow: 'Relationship review',
      title: 'No Action Selected',
      description: 'Select a saved relationship-review action before editing it.',
    });
    return;
  }
  const payload = await relationshipActionDialog(action);
  if (!payload) {
    return;
  }
  try {
    const updated = await api.updateRelationshipReviewAction(action.id, payload);
    state.updateState({ reviewRelationshipActionId: updated.id });
    await loadRelationshipReviewWorkspace();
    setRelationshipStatus(`Saved action “${updated.name}”.`);
  } catch (err) {
    console.error('editRelationshipAction error:', err);
    setRelationshipStatus(err.message || 'Failed to update relationship-review action.');
  }
}

async function deleteRelationshipAction() {
  const action = getSelectedRelationshipAction();
  if (!action) {
    return;
  }
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Relationship review',
    title: 'Delete saved action',
    description: `Delete “${action.name}”?`,
    confirmLabel: 'Delete action',
    confirmVariant: 'danger',
  });
  if (!confirmed) {
    return;
  }
  try {
    await api.deleteRelationshipReviewAction(action.id);
    state.updateState({ reviewRelationshipActionId: null });
    await loadRelationshipReviewWorkspace();
    setRelationshipStatus('Deleted relationship-review action.');
  } catch (err) {
    console.error('deleteRelationshipAction error:', err);
    setRelationshipStatus(err.message || 'Failed to delete relationship-review action.');
  }
}

async function createEnrichmentSession() {
  const payload = await enrichmentSessionDialog();
  if (!payload) {
    return;
  }
  try {
    const snapshot = await api.createEnrichmentReviewSession(payload);
    state.updateState({ reviewEnrichmentSessionId: snapshot.session.id });
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus(`Created ${snapshot.session.name}.`);
  } catch (err) {
    console.error('createEnrichmentSession error:', err);
    setEnrichmentStatus(err.message || 'Failed to create enrichment-review session.');
  }
}

async function editEnrichmentSession() {
  const snapshot = getEnrichmentSnapshot();
  if (!snapshot?.session) {
    await modals.alertDialog({
      eyebrow: 'Enrichment review',
      title: 'No Session Selected',
      description: 'Select an enrichment-review session before editing it.',
    });
    return;
  }
  const payload = await enrichmentSessionDialog(snapshot.session);
  if (!payload) {
    return;
  }
  try {
    const updated = await api.updateEnrichmentReviewSession(snapshot.session.id, payload);
    state.updateState({ reviewEnrichmentSessionId: updated.session.id, reviewEnrichmentSessionSnapshot: updated });
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus(`Saved ${updated.session.name}.`);
  } catch (err) {
    console.error('editEnrichmentSession error:', err);
    setEnrichmentStatus(err.message || 'Failed to update enrichment-review session.');
  }
}

async function deleteEnrichmentSession() {
  const snapshot = getEnrichmentSnapshot();
  if (!snapshot?.session) {
    return;
  }
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Enrichment review',
    title: 'Delete review session',
    description: `Delete “${snapshot.session.name}”? The saved session and cursor will be removed.`,
    confirmLabel: 'Delete session',
    confirmVariant: 'danger',
  });
  if (!confirmed) {
    return;
  }
  try {
    await api.deleteEnrichmentReviewSession(snapshot.session.id);
    state.updateState({ reviewEnrichmentSessionId: null, reviewEnrichmentSessionSnapshot: null });
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus('Deleted enrichment-review session.');
  } catch (err) {
    console.error('deleteEnrichmentSession error:', err);
    setEnrichmentStatus(err.message || 'Failed to delete enrichment-review session.');
  }
}

async function createEnrichmentAction() {
  const payload = await enrichmentActionDialog();
  if (!payload) {
    return;
  }
  try {
    const action = await api.createEnrichmentReviewAction(payload);
    state.updateState({ reviewEnrichmentActionId: action.id });
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus(`Created action “${action.name}”.`);
  } catch (err) {
    console.error('createEnrichmentAction error:', err);
    setEnrichmentStatus(err.message || 'Failed to create enrichment-review action.');
  }
}

async function editEnrichmentAction() {
  const action = getSelectedEnrichmentAction();
  if (!action) {
    await modals.alertDialog({
      eyebrow: 'Enrichment review',
      title: 'No Action Selected',
      description: 'Select a saved enrichment-review action before editing it.',
    });
    return;
  }
  const payload = await enrichmentActionDialog(action);
  if (!payload) {
    return;
  }
  try {
    const updated = await api.updateEnrichmentReviewAction(action.id, payload);
    state.updateState({ reviewEnrichmentActionId: updated.id });
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus(`Saved action “${updated.name}”.`);
  } catch (err) {
    console.error('editEnrichmentAction error:', err);
    setEnrichmentStatus(err.message || 'Failed to update enrichment-review action.');
  }
}

async function deleteEnrichmentAction() {
  const action = getSelectedEnrichmentAction();
  if (!action) {
    return;
  }
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Enrichment review',
    title: 'Delete saved action',
    description: `Delete “${action.name}”?`,
    confirmLabel: 'Delete action',
    confirmVariant: 'danger',
  });
  if (!confirmed) {
    return;
  }
  try {
    await api.deleteEnrichmentReviewAction(action.id);
    state.updateState({ reviewEnrichmentActionId: null });
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus('Deleted enrichment-review action.');
  } catch (err) {
    console.error('deleteEnrichmentAction error:', err);
    setEnrichmentStatus(err.message || 'Failed to delete enrichment-review action.');
  }
}

async function setRelationshipCurrentLoop(loopId) {
  const sessionId = state.state.reviewRelationshipSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const snapshot = await api.updateRelationshipReviewSession(sessionId, { current_loop_id: loopId });
    state.updateState({ reviewRelationshipSessionSnapshot: snapshot });
    renderRelationshipWorkspace();
    setRelationshipStatus(`Moved to loop #${loopId}.`);
  } catch (err) {
    console.error('setRelationshipCurrentLoop error:', err);
    setRelationshipStatus(err.message || 'Failed to update relationship-review cursor.');
  }
}

async function setEnrichmentCurrentLoop(loopId) {
  const sessionId = state.state.reviewEnrichmentSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const snapshot = await api.updateEnrichmentReviewSession(sessionId, { current_loop_id: loopId });
    state.updateState({ reviewEnrichmentSessionSnapshot: snapshot });
    renderEnrichmentWorkspace();
    setEnrichmentStatus(`Moved to loop #${loopId}.`);
  } catch (err) {
    console.error('setEnrichmentCurrentLoop error:', err);
    setEnrichmentStatus(err.message || 'Failed to update enrichment-review cursor.');
  }
}

async function moveRelationshipCursor(direction) {
  const snapshot = getRelationshipSnapshot();
  if (!snapshot?.items?.length || !Number.isInteger(snapshot.current_index)) {
    return;
  }
  const targetIndex = direction === 'next' ? snapshot.current_index + 1 : snapshot.current_index - 1;
  if (targetIndex < 0 || targetIndex >= snapshot.items.length) {
    return;
  }
  await setRelationshipCurrentLoop(snapshot.items[targetIndex].loop.id);
}

async function moveEnrichmentCursor(direction) {
  const snapshot = getEnrichmentSnapshot();
  if (!snapshot?.items?.length || !Number.isInteger(snapshot.current_index)) {
    return;
  }
  const targetIndex = direction === 'next' ? snapshot.current_index + 1 : snapshot.current_index - 1;
  if (targetIndex < 0 || targetIndex >= snapshot.items.length) {
    return;
  }
  await setEnrichmentCurrentLoop(snapshot.items[targetIndex].loop.id);
}

async function executeRelationshipAction(payload, successMessage) {
  const sessionId = state.state.reviewRelationshipSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const result = await api.runRelationshipReviewSessionAction(sessionId, payload);
    state.updateState({ reviewRelationshipSessionSnapshot: result.snapshot });
    renderRelationshipWorkspace();
    setRelationshipStatus(successMessage || 'Applied relationship review action.');
    await loadInbox();
  } catch (err) {
    console.error('executeRelationshipAction error:', err);
    setRelationshipStatus(err.message || 'Failed to apply relationship review action.');
  }
}

async function executeEnrichmentAction(payload, successMessage) {
  const sessionId = state.state.reviewEnrichmentSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const result = await api.runEnrichmentReviewSessionAction(sessionId, payload);
    state.updateState({ reviewEnrichmentSessionSnapshot: result.snapshot });
    renderEnrichmentWorkspace();
    setEnrichmentStatus(successMessage || 'Applied enrichment review action.');
    await loadInbox();
  } catch (err) {
    console.error('executeEnrichmentAction error:', err);
    setEnrichmentStatus(err.message || 'Failed to apply enrichment review action.');
  }
}

async function submitEnrichmentClarifications(loopId) {
  const sessionId = state.state.reviewEnrichmentSessionId;
  if (sessionId == null || !reviewEnrichmentSessionDetail) {
    return;
  }
  const container = reviewEnrichmentSessionDetail.querySelector(`.review-clarification-form[data-loop-id="${loopId}"]`);
  if (!(container instanceof HTMLElement)) {
    return;
  }

  const answers = Array.from(container.querySelectorAll('[data-clarification-id]'))
    .map((input) => ({
      clarification_id: parseInteger(input.dataset.clarificationId),
      answer: input.value?.trim() || '',
    }))
    .filter((item) => item.clarification_id != null && item.answer);

  if (!answers.length) {
    await modals.alertDialog({
      eyebrow: 'Enrichment review',
      title: 'Add At Least One Answer',
      description: 'Enter at least one clarification answer before submitting this loop.',
    });
    return;
  }

  try {
    await api.answerEnrichmentReviewSessionClarifications(sessionId, {
      loop_id: loopId,
      answers,
    });
    await api.enrichLoop(loopId);
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus(`Recorded clarifications for loop #${loopId} and reran enrichment.`);
    await loadInbox();
  } catch (err) {
    console.error('submitEnrichmentClarifications error:', err);
    setEnrichmentStatus(err.message || 'Failed to answer clarifications.');
  }
}

async function rerunEnrichment(loopId) {
  try {
    await api.enrichLoop(loopId);
    await loadEnrichmentReviewWorkspace();
    setEnrichmentStatus(`Re-enriched loop #${loopId}.`);
    await loadInbox();
  } catch (err) {
    console.error('rerunEnrichment error:', err);
    setEnrichmentStatus(err.message || 'Failed to rerun enrichment.');
  }
}

async function handleRelationshipSessionListClick(event) {
  const button = event.target.closest('[data-action="relationship-select-loop"]');
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  const loopId = parseInteger(button.dataset.loopId);
  if (loopId != null) {
    await setRelationshipCurrentLoop(loopId);
  }
}

async function handleRelationshipDetailClick(event) {
  const button = event.target.closest('[data-action]');
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  if (button.dataset.action === 'relationship-move') {
    await moveRelationshipCursor(button.dataset.direction);
    return;
  }

  if (button.dataset.action === 'relationship-merge') {
    const loopId = parseInteger(button.dataset.loopId);
    const candidateId = parseInteger(button.dataset.candidateId);
    if (loopId != null && candidateId != null) {
      await openMergeModal(candidateId, loopId);
    }
    return;
  }

  if (button.dataset.action === 'relationship-inline') {
    const loopId = parseInteger(button.dataset.loopId);
    const candidateId = parseInteger(button.dataset.candidateId);
    if (loopId == null || candidateId == null || !button.dataset.candidateType || !button.dataset.inlineAction) {
      return;
    }
    await executeRelationshipAction(
      {
        loop_id: loopId,
        candidate_loop_id: candidateId,
        candidate_relationship_type: button.dataset.candidateType,
        action_type: button.dataset.inlineAction,
        relationship_type: button.dataset.relationshipType,
      },
      `Applied ${button.dataset.inlineAction} to loop #${candidateId}.`,
    );
    return;
  }

  if (button.dataset.action === 'relationship-apply-preset') {
    const loopId = parseInteger(button.dataset.loopId);
    const candidateId = parseInteger(button.dataset.candidateId);
    const actionId = parseInteger(button.dataset.actionId);
    if (loopId == null || candidateId == null || actionId == null || !button.dataset.candidateType) {
      return;
    }
    await executeRelationshipAction(
      {
        loop_id: loopId,
        candidate_loop_id: candidateId,
        candidate_relationship_type: button.dataset.candidateType,
        action_preset_id: actionId,
      },
      `Applied saved action to loop #${candidateId}.`,
    );
  }
}

async function handleEnrichmentSessionListClick(event) {
  const button = event.target.closest('[data-action="enrichment-select-loop"]');
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  const loopId = parseInteger(button.dataset.loopId);
  if (loopId != null) {
    await setEnrichmentCurrentLoop(loopId);
  }
}

async function handleEnrichmentDetailClick(event) {
  const button = event.target.closest('[data-action]');
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  if (button.dataset.action === 'enrichment-move') {
    await moveEnrichmentCursor(button.dataset.direction);
    return;
  }

  if (button.dataset.action === 'enrichment-rerun') {
    const loopId = parseInteger(button.dataset.loopId);
    if (loopId != null) {
      await rerunEnrichment(loopId);
    }
    return;
  }

  if (button.dataset.action === 'enrichment-inline') {
    const suggestionId = parseInteger(button.dataset.suggestionId);
    if (suggestionId == null || !button.dataset.inlineAction) {
      return;
    }
    await executeEnrichmentAction(
      {
        suggestion_id: suggestionId,
        action_type: button.dataset.inlineAction,
      },
      `Applied ${button.dataset.inlineAction} to suggestion #${suggestionId}.`,
    );
    return;
  }

  if (button.dataset.action === 'enrichment-apply-preset') {
    const suggestionId = parseInteger(button.dataset.suggestionId);
    const actionId = parseInteger(button.dataset.actionId);
    if (suggestionId == null || actionId == null) {
      return;
    }
    await executeEnrichmentAction(
      {
        suggestion_id: suggestionId,
        action_preset_id: actionId,
      },
      `Applied saved action to suggestion #${suggestionId}.`,
    );
    return;
  }

  if (button.dataset.action === 'enrichment-submit-clarifications') {
    const loopId = parseInteger(button.dataset.loopId);
    if (loopId != null) {
      await submitEnrichmentClarifications(loopId);
    }
  }
}

export function renderReviewCohorts() {
  if (!reviewCohorts || !state.state.reviewData) {
    return;
  }

  reviewCohorts.innerHTML = '';
  const cohorts = state.state.reviewMode === 'daily'
    ? state.state.reviewData.daily
    : state.state.reviewData.weekly;

  if (!cohorts?.length) {
    reviewCohorts.innerHTML = '<div class="cohort-empty">No cohorts available.</div>';
    return;
  }

  cohorts.forEach((cohort) => {
    reviewCohorts.appendChild(renderReviewCohort(cohort));
  });
}

function getBulkEnrichmentLimit() {
  const limit = Number.parseInt(reviewBulkEnrichLimit?.value || '25', 10);
  if (!Number.isFinite(limit) || limit < 1) {
    return 25;
  }
  return Math.min(limit, 100);
}

function renderBulkEnrichmentLoopList(targets = []) {
  if (!targets.length) {
    return '<div class="cohort-empty">No loops matched this query.</div>';
  }

  return `
    <div class="bulk-enrichment-target-list">
      ${targets.map((loop) => `
        <article class="bulk-enrichment-target-card">
          <div class="bulk-enrichment-target-meta">
            <span class="support-eyebrow">Loop #${loop.id}</span>
            <span class="cohort-count">${escapeHtml(loop.status)}</span>
          </div>
          <h3>${formatLoopTitle(loop)}</h3>
          <p>${formatLoopPreview(loop)}</p>
        </article>
      `).join('')}
    </div>
  `;
}

function renderBulkEnrichmentResultList(results = []) {
  if (!results.length) {
    return '<div class="cohort-empty">No loops were enriched in this run.</div>';
  }

  return `
    <div class="bulk-enrichment-target-list">
      ${results.map((item) => `
        <article class="bulk-enrichment-target-card ${item.ok ? 'is-success' : 'is-error'}">
          <div class="bulk-enrichment-target-meta">
            <span class="support-eyebrow">Loop #${item.loop_id}</span>
            <span class="cohort-count ${item.ok ? '' : 'alert'}">${item.ok ? 'enriched' : 'failed'}</span>
          </div>
          <h3>${formatLoopTitle(item.loop || { id: item.loop_id, raw_text: `Loop #${item.loop_id}` })}</h3>
          ${item.ok ? `
            <p>${formatLoopPreview(item.loop || {})}</p>
            <div class="bulk-enrichment-result-meta">
              <span>Suggestion #${item.suggestion_id ?? '—'}</span>
              <span>Applied: ${escapeHtml((item.applied_fields || []).join(', ') || 'none')}</span>
              <span>Clarifications: ${item.needs_clarification?.length || 0}</span>
            </div>
          ` : `
            <p>${escapeHtml(item.error?.message || 'Enrichment failed.')}</p>
          `}
        </article>
      `).join('')}
    </div>
  `;
}

async function previewBulkEnrichment() {
  if (!reviewBulkEnrichQuery || !reviewBulkEnrichPreviewResults || !reviewBulkEnrichStatus) {
    return;
  }

  const query = reviewBulkEnrichQuery.value.trim();
  if (!query) {
    reviewBulkEnrichStatus.textContent = 'Enter a DSL query before previewing bulk enrichment.';
    return;
  }

  reviewBulkEnrichStatus.textContent = 'Previewing bulk enrichment targets…';
  reviewBulkEnrichPreviewResults.innerHTML = '<div class="cohort-loading">Loading preview…</div>';
  if (reviewBulkEnrichRunResults) {
    reviewBulkEnrichRunResults.innerHTML = '';
  }

  try {
    const result = await api.bulkEnrichQuery(query, { dryRun: true, limit: getBulkEnrichmentLimit() });
    state.updateState({ reviewBulkEnrichmentPreview: result });
    reviewBulkEnrichPreviewResults.innerHTML = renderBulkEnrichmentLoopList(result.targets || []);
    reviewBulkEnrichStatus.textContent = result.targets?.length
      ? `Preview matched ${result.matched_count} loop${result.matched_count !== 1 ? 's' : ''}.`
      : 'No loops matched this query.';
  } catch (err) {
    console.error('previewBulkEnrichment error:', err);
    reviewBulkEnrichPreviewResults.innerHTML = '<div class="cohort-empty">Error loading bulk enrichment preview.</div>';
    reviewBulkEnrichStatus.textContent = err.message || 'Bulk enrichment preview failed.';
  }
}

async function runBulkEnrichment() {
  if (!reviewBulkEnrichQuery || !reviewBulkEnrichRunResults || !reviewBulkEnrichStatus) {
    return;
  }

  const query = reviewBulkEnrichQuery.value.trim();
  if (!query) {
    reviewBulkEnrichStatus.textContent = 'Enter a DSL query before running bulk enrichment.';
    return;
  }

  const preview = state.state.reviewBulkEnrichmentPreview;
  const previewCount = preview?.query === query ? Number(preview.matched_count || 0) : null;
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Bulk enrichment',
    title: 'Enrich filtered loop set',
    description: previewCount !== null
      ? `Run explicit enrichment across ${previewCount} matched loop${previewCount !== 1 ? 's' : ''}?`
      : 'Run explicit enrichment across the loops matched by this query?',
    confirmLabel: 'Enrich loops',
  });
  if (!confirmed) {
    return;
  }

  reviewBulkEnrichStatus.textContent = 'Running bulk enrichment…';
  reviewBulkEnrichRunResults.innerHTML = '<div class="cohort-loading">Running enrichment…</div>';

  try {
    const result = await api.bulkEnrichQuery(query, { dryRun: false, limit: getBulkEnrichmentLimit() });
    state.updateState({ reviewBulkEnrichmentResult: result });
    reviewBulkEnrichRunResults.innerHTML = renderBulkEnrichmentResultList(result.results || []);
    reviewBulkEnrichStatus.textContent = result.failed
      ? `Bulk enrichment finished: ${result.succeeded} succeeded, ${result.failed} failed.`
      : `Bulk enrichment finished: ${result.succeeded} loop${result.succeeded !== 1 ? 's' : ''} enriched.`;
    await Promise.all([loadInbox(), loadRelationshipReviewWorkspace(), loadEnrichmentReviewWorkspace()]);
  } catch (err) {
    console.error('runBulkEnrichment error:', err);
    reviewBulkEnrichRunResults.innerHTML = '<div class="cohort-empty">Bulk enrichment failed.</div>';
    reviewBulkEnrichStatus.textContent = err.message || 'Bulk enrichment failed.';
  }
}

export function setReviewMode(mode) {
  state.updateState({ reviewMode: mode });
  renderReviewCohorts();
}
