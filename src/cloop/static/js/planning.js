/**
 * planning.js - Planning workflow workspace functionality
 *
 * Purpose:
 *   Display and operate saved AI-native planning sessions inside the review tab.
 *
 * Responsibilities:
 *   - Load saved planning sessions and snapshots from the API
 *   - Render checkpointed plans, target loops, and execution history
 *   - Create, delete, refresh, move, and execute planning sessions
 *   - Keep review/inbox surfaces refreshed after deterministic execution
 *
 * Non-scope:
 *   - Planning generation business logic
 *   - Generic review cohorts (see review.js)
 *   - Tab switching (see init.js)
 */

import * as api from './api.js';
import * as modals from './modals.js';
import * as review from './review.js';
import * as state from './state.js';
import { loadInbox } from './loop.js';
import { escapeHtml } from './utils.js';

let reviewPlanningSessionSelect;
let reviewPlanningSessionNew;
let reviewPlanningSessionDelete;
let reviewPlanningSessionRefresh;
let reviewPlanningSessionExecute;
let reviewPlanningSessionStatus;
let reviewPlanningSessionSummary;
let reviewPlanningSessionList;
let reviewPlanningSessionDetail;

export function init(elements) {
  reviewPlanningSessionSelect = elements.reviewPlanningSessionSelect;
  reviewPlanningSessionNew = elements.reviewPlanningSessionNew;
  reviewPlanningSessionDelete = elements.reviewPlanningSessionDelete;
  reviewPlanningSessionRefresh = elements.reviewPlanningSessionRefresh;
  reviewPlanningSessionExecute = elements.reviewPlanningSessionExecute;
  reviewPlanningSessionStatus = elements.reviewPlanningSessionStatus;
  reviewPlanningSessionSummary = elements.reviewPlanningSessionSummary;
  reviewPlanningSessionList = elements.reviewPlanningSessionList;
  reviewPlanningSessionDetail = elements.reviewPlanningSessionDetail;

  reviewPlanningSessionSelect?.addEventListener('change', () => {
    void selectPlanningSession(parseInteger(reviewPlanningSessionSelect?.value));
  });
  reviewPlanningSessionNew?.addEventListener('click', () => {
    void createPlanningSession();
  });
  reviewPlanningSessionDelete?.addEventListener('click', () => {
    void deletePlanningSession();
  });
  reviewPlanningSessionRefresh?.addEventListener('click', () => {
    void refreshPlanningSession();
  });
  reviewPlanningSessionExecute?.addEventListener('click', () => {
    void executePlanningSession();
  });
  reviewPlanningSessionDetail?.addEventListener('click', handlePlanningDetailClick);
}

function parseInteger(value) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isInteger(parsed) ? parsed : null;
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

function setPlanningStatus(message, { isError = false } = {}) {
  if (!reviewPlanningSessionStatus) {
    return;
  }
  reviewPlanningSessionStatus.textContent = message;
  reviewPlanningSessionStatus.classList.toggle('is-error', isError);
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

function formatLoopTitle(loop) {
  return escapeHtml(loop?.title || loop?.raw_text || `Loop #${loop?.id ?? '—'}`);
}

function formatLoopPreview(loop) {
  return escapeHtml(loop?.summary || loop?.raw_text || 'No summary available.');
}

function getPlanningSessions() {
  return Array.isArray(state.state.reviewPlanningSessions) ? state.state.reviewPlanningSessions : [];
}

function getPlanningSnapshot() {
  return state.state.reviewPlanningSessionSnapshot;
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

function executedCheckpointIndexSet(snapshot) {
  return new Set((snapshot?.execution_history || []).map((item) => item.checkpoint_index));
}

function renderPlanningSessionList() {
  if (!reviewPlanningSessionList) {
    return;
  }
  const snapshot = getPlanningSnapshot();
  if (!snapshot?.session) {
    reviewPlanningSessionList.innerHTML = '<div class="review-session-empty">No planning session selected.</div>';
    return;
  }
  if (!snapshot.checkpoints?.length) {
    reviewPlanningSessionList.innerHTML = '<div class="review-session-empty">This planning session currently has no checkpoints.</div>';
    return;
  }

  const executed = executedCheckpointIndexSet(snapshot);
  reviewPlanningSessionList.innerHTML = snapshot.checkpoints.map((checkpoint, index) => {
    const isCurrent = snapshot.session.current_checkpoint_index === index;
    const isExecuted = executed.has(index);
    return `
      <article class="review-session-item planning-checkpoint-item ${isCurrent ? 'is-active' : ''} ${isExecuted ? 'is-complete' : ''}">
        <span class="review-session-item-order planning-checkpoint-badge">${index + 1}</span>
        <span class="review-session-item-body">
          <span class="review-session-item-title">${escapeHtml(checkpoint.title || `Checkpoint ${index + 1}`)}</span>
          <span class="review-session-item-copy">${escapeHtml(checkpoint.summary || 'No summary provided.')}</span>
          <span class="review-session-item-meta">
            <span class="cohort-count ${isExecuted ? '' : 'alert'}">${isExecuted ? 'Executed' : 'Pending'}</span>
            <span class="cohort-count">${(checkpoint.operations || []).length} action${(checkpoint.operations || []).length === 1 ? '' : 's'}</span>
            ${isCurrent ? '<span class="cohort-count">Current</span>' : ''}
          </span>
        </span>
      </article>
    `;
  }).join('');
}

function renderTargetLoop(loop) {
  return `
    <article class="planning-target-loop">
      <h5>${formatLoopTitle(loop)}</h5>
      <p>${formatLoopPreview(loop)}</p>
      <div class="review-session-chip-group">
        <span class="review-session-chip">Status: ${escapeHtml(loop.status || 'unknown')}</span>
        ${loop.project ? `<span class="review-session-chip">Project: ${escapeHtml(loop.project)}</span>` : ''}
        ${(loop.tags || []).length ? `<span class="review-session-chip">Tags: ${escapeHtml(loop.tags.join(', '))}</span>` : ''}
      </div>
    </article>
  `;
}

function renderOperationCard(operation) {
  const operationCopy = { ...operation };
  delete operationCopy.summary;
  return `
    <article class="planning-operation-card">
      <div class="planning-operation-card-header">
        <span class="planning-operation-kind">${escapeHtml(operation.kind || 'operation')}</span>
      </div>
      <p class="planning-operation-summary">${escapeHtml(operation.summary || 'No summary provided.')}</p>
      <pre class="planning-operation-payload">${escapeHtml(JSON.stringify(operationCopy, null, 2))}</pre>
    </article>
  `;
}

function renderExecutionResult(result) {
  const afterCount = Array.isArray(result.after_loops) ? result.after_loops.length : 0;
  const beforeCount = Array.isArray(result.before_loops) ? result.before_loops.length : 0;
  return `
    <article class="planning-execution-result">
      <div class="planning-execution-result-header">
        <strong>${escapeHtml(result.summary || result.kind || 'Operation')}</strong>
        <span class="review-session-chip">${escapeHtml(result.kind || 'operation')}</span>
      </div>
      <div class="review-session-chip-group">
        <span class="review-session-chip">Before loops: ${beforeCount}</span>
        <span class="review-session-chip">After loops: ${afterCount}</span>
        <span class="review-session-chip">${result.undoable ? 'Undo-friendly snapshot' : 'No undo snapshot'}</span>
      </div>
      <pre class="planning-operation-payload">${escapeHtml(JSON.stringify(result.result || {}, null, 2))}</pre>
    </article>
  `;
}

function renderExecutionHistory(snapshot) {
  const history = Array.isArray(snapshot?.execution_history) ? snapshot.execution_history : [];
  if (!history.length) {
    return '<div class="review-session-empty">No checkpoints have been executed yet.</div>';
  }

  return `
    <div class="planning-execution-history-list">
      ${history.map((item) => `
        <section class="planning-execution-history-item">
          <div class="planning-execution-history-header">
            <div>
              <p class="support-eyebrow">Checkpoint ${item.checkpoint_index + 1}</p>
              <h5>${escapeHtml(item.checkpoint_title || `Checkpoint ${item.checkpoint_index + 1}`)}</h5>
            </div>
            <div class="review-session-chip-group">
              <span class="review-session-chip">${item.operation_count} result${item.operation_count === 1 ? '' : 's'}</span>
              <span class="review-session-chip">${formatTimestamp(item.executed_at_utc)}</span>
            </div>
          </div>
          <div class="planning-execution-results">
            ${(item.results || []).map((result) => renderExecutionResult(result)).join('')}
          </div>
        </section>
      `).join('')}
    </div>
  `;
}

function renderPlanningWorkspace() {
  const sessions = getPlanningSessions();
  const snapshot = getPlanningSnapshot();
  const session = snapshot?.session || null;
  const currentCheckpoint = snapshot?.current_checkpoint || null;
  const executed = executedCheckpointIndexSet(snapshot);
  const currentExecuted = session ? executed.has(session.current_checkpoint_index) : false;

  populateSelect(
    reviewPlanningSessionSelect,
    sessions,
    state.state.reviewPlanningSessionId,
    'No saved session',
    (item) => `${item.name} · ${item.status} · ${item.executed_checkpoint_count}/${item.checkpoint_count}`,
  );

  const summaryBits = session
    ? [
        session.query ? `Query: ${session.query}` : 'Query: next-loop focus',
        `Status: ${session.status.replace(/_/g, ' ')}`,
        `Executed: ${session.executed_checkpoint_count}/${session.checkpoint_count}`,
      ]
    : [];
  renderSessionSummary(reviewPlanningSessionSummary, snapshot, summaryBits);
  renderPlanningSessionList();

  if (reviewPlanningSessionExecute) {
    reviewPlanningSessionExecute.disabled = !session || !currentCheckpoint || currentExecuted;
  }
  if (reviewPlanningSessionDelete) {
    reviewPlanningSessionDelete.disabled = !session;
  }
  if (reviewPlanningSessionRefresh) {
    reviewPlanningSessionRefresh.disabled = !session;
  }

  if (!reviewPlanningSessionDetail) {
    return;
  }
  if (!session) {
    reviewPlanningSessionDetail.innerHTML = '<div class="review-session-empty">Create or select a planning session to generate a checkpointed workflow you can execute step by step.</div>';
    return;
  }

  const canMovePrev = session.current_checkpoint_index > 0;
  const canMoveNext = session.current_checkpoint_index < session.checkpoint_count - 1;
  const targetLoops = Array.isArray(snapshot.target_loops) ? snapshot.target_loops.slice(0, 6) : [];
  const assumptions = Array.isArray(snapshot.assumptions) ? snapshot.assumptions : [];

  reviewPlanningSessionDetail.innerHTML = `
    <div class="review-session-card planning-session-card">
      <div class="review-session-card-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(session.name)}</p>
          <h3>${escapeHtml(snapshot.plan_title || session.name)}</h3>
          <p class="review-session-copy">${escapeHtml(snapshot.plan_summary || session.prompt)}</p>
        </div>
        <div class="review-session-card-actions">
          <button type="button" class="secondary" data-action="planning-move" data-direction="previous" ${canMovePrev ? '' : 'disabled'}>Previous</button>
          <button type="button" class="secondary" data-action="planning-move" data-direction="next" ${canMoveNext ? '' : 'disabled'}>Next</button>
          <button type="button" class="secondary" data-action="planning-refresh">Refresh plan</button>
          <button type="button" data-action="planning-execute" ${currentCheckpoint && !currentExecuted ? '' : 'disabled'}>Execute current checkpoint</button>
        </div>
      </div>
      <div class="review-session-chip-group">
        <span class="review-session-chip">Prompt: ${escapeHtml(session.prompt)}</span>
        <span class="review-session-chip">Loop limit: ${session.loop_limit}</span>
        <span class="review-session-chip">Memory: ${session.include_memory_context ? 'on' : 'off'}</span>
        <span class="review-session-chip">RAG: ${session.include_rag_context ? `on · k=${session.rag_k}` : 'off'}</span>
      </div>
      <section class="planning-section-block">
        <div class="planning-section-heading">
          <h4>Current checkpoint</h4>
          <span class="cohort-count ${currentExecuted ? '' : 'alert'}">
            ${currentCheckpoint ? `Checkpoint ${session.current_checkpoint_index + 1} of ${session.checkpoint_count}` : 'No current checkpoint'}
          </span>
        </div>
        ${currentCheckpoint ? `
          <div class="planning-current-checkpoint">
            <h5>${escapeHtml(currentCheckpoint.title || `Checkpoint ${session.current_checkpoint_index + 1}`)}</h5>
            <p>${escapeHtml(currentCheckpoint.summary || 'No summary provided.')}</p>
            <div class="review-session-chip-group">
              <span class="review-session-chip">Success criteria</span>
              <span class="review-session-chip">${escapeHtml(currentCheckpoint.success_criteria || 'No success criteria provided.')}</span>
              ${currentExecuted ? '<span class="review-session-chip">Already executed</span>' : '<span class="review-session-chip">Ready to execute</span>'}
            </div>
            <div class="planning-operation-list">
              ${(currentCheckpoint.operations || []).map((operation) => renderOperationCard(operation)).join('')}
            </div>
          </div>
        ` : '<div class="review-session-empty">No current checkpoint available.</div>'}
      </section>
      <section class="planning-section-block">
        <div class="planning-section-heading">
          <h4>Grounded target loops</h4>
          <span class="cohort-count">${Array.isArray(snapshot.target_loops) ? snapshot.target_loops.length : 0} loaded</span>
        </div>
        ${targetLoops.length ? `<div class="planning-target-loop-list">${targetLoops.map((loop) => renderTargetLoop(loop)).join('')}</div>` : '<div class="review-session-empty">No grounded target loops were included in this planning session.</div>'}
      </section>
      <section class="planning-section-block">
        <div class="planning-section-heading">
          <h4>Assumptions</h4>
          <span class="cohort-count">${assumptions.length}</span>
        </div>
        ${assumptions.length ? `<ul class="planning-assumptions">${assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : '<div class="review-session-empty">No assumptions were recorded.</div>'}
      </section>
      <section class="planning-section-block">
        <div class="planning-section-heading">
          <h4>Execution history</h4>
          <span class="cohort-count">${(snapshot.execution_history || []).length}</span>
        </div>
        ${renderExecutionHistory(snapshot)}
      </section>
    </div>
  `;
}

async function planningSessionDialog() {
  const result = await modals.promptDialog({
    eyebrow: 'Planning workflows',
    title: 'Create planning session',
    description: 'Generate a checkpointed workflow grounded in current loops, memory, and optional retrieval context.',
    confirmLabel: 'Create session',
    fields: [
      { name: 'name', label: 'Session name', required: true, value: '' },
      {
        name: 'prompt',
        label: 'Planning prompt',
        type: 'textarea',
        rows: 5,
        required: true,
        value: '',
        placeholder: 'Create a checkpointed plan for ...',
      },
      {
        name: 'query',
        label: 'DSL query (optional)',
        value: 'status:open',
        placeholder: 'status:open project:launch',
      },
      {
        name: 'loop_limit',
        label: 'Loop limit',
        type: 'number',
        value: '10',
        inputMode: 'numeric',
      },
      {
        name: 'include_memory_context',
        label: 'Include memory context',
        type: 'select',
        value: 'true',
        options: [
          { value: 'true', label: 'Yes' },
          { value: 'false', label: 'No' },
        ],
      },
      {
        name: 'include_rag_context',
        label: 'Include RAG context',
        type: 'select',
        value: 'false',
        options: [
          { value: 'false', label: 'No' },
          { value: 'true', label: 'Yes' },
        ],
      },
      {
        name: 'rag_k',
        label: 'RAG chunk count',
        type: 'number',
        value: '5',
        inputMode: 'numeric',
      },
      {
        name: 'rag_scope',
        label: 'RAG scope (optional)',
        value: '',
        placeholder: 'launch-notes',
      },
    ],
    validate: (values) => {
      if (!values.name) {
        return 'Enter a planning session name.';
      }
      if (!values.prompt) {
        return 'Enter a planning prompt.';
      }
      if (!Number.isInteger(parseInteger(values.loop_limit)) || parseInteger(values.loop_limit) < 1) {
        return 'Loop limit must be a positive integer.';
      }
      if (!Number.isInteger(parseInteger(values.rag_k)) || parseInteger(values.rag_k) < 1) {
        return 'RAG chunk count must be a positive integer.';
      }
      return null;
    },
  });

  if (!result) {
    return null;
  }

  return {
    name: result.name,
    prompt: result.prompt,
    query: result.query || null,
    loop_limit: parseInteger(result.loop_limit) || 10,
    include_memory_context: result.include_memory_context === 'true',
    include_rag_context: result.include_rag_context === 'true',
    rag_k: parseInteger(result.rag_k) || 5,
    rag_scope: result.rag_scope || null,
  };
}

async function createPlanningSession() {
  const payload = await planningSessionDialog();
  if (!payload) {
    return;
  }
  try {
    const snapshot = await api.createPlanningSession(payload);
    state.updateState({
      reviewPlanningSessionId: snapshot.session.id,
      reviewPlanningSessionSnapshot: snapshot,
    });
    await loadPlanningWorkspace();
    setPlanningStatus(`Created ${snapshot.session.name}.`);
  } catch (err) {
    console.error('createPlanningSession error:', err);
    setPlanningStatus(err.message || 'Failed to create planning session.', { isError: true });
  }
}

async function deletePlanningSession() {
  const snapshot = getPlanningSnapshot();
  if (!snapshot?.session) {
    return;
  }
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Planning workflows',
    title: 'Delete planning session',
    description: `Delete “${snapshot.session.name}”? The saved plan and execution history will be removed.`,
    confirmLabel: 'Delete session',
    confirmVariant: 'danger',
  });
  if (!confirmed) {
    return;
  }
  try {
    await api.deletePlanningSession(snapshot.session.id);
    state.updateState({ reviewPlanningSessionId: null, reviewPlanningSessionSnapshot: null });
    await loadPlanningWorkspace();
    setPlanningStatus('Deleted planning session.');
  } catch (err) {
    console.error('deletePlanningSession error:', err);
    setPlanningStatus(err.message || 'Failed to delete planning session.', { isError: true });
  }
}

async function refreshPlanningSession() {
  const sessionId = state.state.reviewPlanningSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const snapshot = await api.refreshPlanningSession(sessionId);
    state.updateState({ reviewPlanningSessionSnapshot: snapshot });
    renderPlanningWorkspace();
    setPlanningStatus(`Refreshed ${snapshot.session.name}.`);
  } catch (err) {
    console.error('refreshPlanningSession error:', err);
    setPlanningStatus(err.message || 'Failed to refresh planning session.', { isError: true });
  }
}

async function executePlanningSession() {
  const sessionId = state.state.reviewPlanningSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const payload = await api.executePlanningSession(sessionId);
    state.updateState({ reviewPlanningSessionSnapshot: payload.snapshot });
    renderPlanningWorkspace();
    await Promise.all([loadInbox(), review.loadReviewData()]);
    setPlanningStatus(`Executed ${payload.execution.checkpoint_title}.`);
  } catch (err) {
    console.error('executePlanningSession error:', err);
    setPlanningStatus(err.message || 'Failed to execute planning checkpoint.', { isError: true });
  }
}

async function movePlanningSession(direction) {
  const sessionId = state.state.reviewPlanningSessionId;
  if (sessionId == null) {
    return;
  }
  try {
    const snapshot = await api.movePlanningSession(sessionId, direction);
    state.updateState({ reviewPlanningSessionSnapshot: snapshot });
    renderPlanningWorkspace();
    setPlanningStatus(`Moved to checkpoint ${snapshot.session.current_checkpoint_index + 1}.`);
  } catch (err) {
    console.error('movePlanningSession error:', err);
    setPlanningStatus(err.message || 'Failed to move planning checkpoint.', { isError: true });
  }
}

async function selectPlanningSession(sessionId) {
  state.updateState({
    reviewPlanningSessionId: sessionId,
    reviewPlanningSessionSnapshot: null,
  });
  renderPlanningWorkspace();
  if (sessionId == null) {
    setPlanningStatus('No planning session selected.');
    return;
  }
  try {
    const snapshot = await api.fetchPlanningSession(sessionId);
    state.updateState({ reviewPlanningSessionSnapshot: snapshot });
    renderPlanningWorkspace();
    setPlanningStatus(`Loaded ${snapshot.session.name}.`);
  } catch (err) {
    console.error('selectPlanningSession error:', err);
    setPlanningStatus(err.message || 'Failed to load planning session.', { isError: true });
  }
}

function handlePlanningDetailClick(event) {
  const button = event.target.closest('[data-action]');
  if (!button) {
    return;
  }

  const { action, direction } = button.dataset;
  if (action === 'planning-move' && direction) {
    void movePlanningSession(direction);
    return;
  }
  if (action === 'planning-refresh') {
    void refreshPlanningSession();
    return;
  }
  if (action === 'planning-execute') {
    void executePlanningSession();
  }
}

export async function loadPlanningWorkspace() {
  if (reviewPlanningSessionList) {
    reviewPlanningSessionList.innerHTML = '<div class="cohort-loading">Loading planning sessions...</div>';
  }
  if (reviewPlanningSessionDetail) {
    reviewPlanningSessionDetail.innerHTML = '<div class="cohort-loading">Loading planning details...</div>';
  }

  try {
    const sessions = await api.fetchPlanningSessions();
    const sessionId = choosePersistedId(sessions, state.state.reviewPlanningSessionId);
    let snapshot = null;
    if (sessionId != null) {
      snapshot = await api.fetchPlanningSession(sessionId);
    }
    state.updateState({
      reviewPlanningSessions: sessions,
      reviewPlanningSessionId: sessionId,
      reviewPlanningSessionSnapshot: snapshot,
    });
    renderPlanningWorkspace();
    setPlanningStatus(
      snapshot?.session
        ? `Loaded ${snapshot.session.name}. ${snapshot.session.executed_checkpoint_count}/${snapshot.session.checkpoint_count} checkpoints executed.`
        : 'Create a planning session to generate a checkpointed workflow grounded in your current loops.',
    );
    return snapshot;
  } catch (err) {
    console.error('loadPlanningWorkspace error:', err);
    state.updateState({
      reviewPlanningSessions: [],
      reviewPlanningSessionSnapshot: null,
      reviewPlanningSessionId: null,
    });
    renderPlanningWorkspace();
    setPlanningStatus(err.message || 'Failed to load planning sessions.', { isError: true });
    return null;
  }
}
