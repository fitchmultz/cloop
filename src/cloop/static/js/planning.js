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

const STATUS_LABELS = {
  draft: 'Draft',
  in_progress: 'In progress',
  completed: 'Completed',
};

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

function parseTimestamp(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTimestamp(value) {
  const date = parseTimestamp(value);
  if (!date) {
    return value ? escapeHtml(String(value)) : '—';
  }
  return escapeHtml(date.toLocaleString());
}

function formatRelativeTimestamp(value) {
  const date = parseTimestamp(value);
  if (!date) {
    return value ? escapeHtml(String(value)) : 'unknown time';
  }

  const diffMs = Date.now() - date.getTime();
  const absMs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  let amount;
  let unit;
  if (absMs < hour) {
    amount = Math.max(1, Math.round(absMs / minute));
    unit = amount === 1 ? 'minute' : 'minutes';
  } else if (absMs < day) {
    amount = Math.max(1, Math.round(absMs / hour));
    unit = amount === 1 ? 'hour' : 'hours';
  } else {
    amount = Math.max(1, Math.round(absMs / day));
    unit = amount === 1 ? 'day' : 'days';
  }

  return escapeHtml(`${amount} ${unit} ${diffMs >= 0 ? 'ago' : 'from now'}`);
}

function formatLoopTitle(loop) {
  return escapeHtml(loop?.title || loop?.raw_text || `Loop #${loop?.id ?? '—'}`);
}

function formatLoopPreview(loop) {
  return escapeHtml(loop?.summary || loop?.raw_text || 'No summary available.');
}

function formatStatusLabel(status) {
  if (!status) {
    return 'Unknown';
  }
  return escapeHtml(STATUS_LABELS[status] || String(status).replace(/_/g, ' '));
}

function getPlanningSessions() {
  return Array.isArray(state.state.reviewPlanningSessions) ? state.state.reviewPlanningSessions : [];
}

function getPlanningSnapshot() {
  return state.state.reviewPlanningSessionSnapshot;
}

function planningGeneratedAt(snapshot) {
  return snapshot?.context_summary?.generated_at_utc || snapshot?.session?.updated_at_utc || null;
}

function planningCurrentCheckpointStatus(snapshot, checkpointIndex) {
  const session = snapshot?.session;
  if (!session) {
    return 'pending';
  }
  const executed = executedCheckpointIndexSet(snapshot);
  if (executed.has(checkpointIndex)) {
    return 'executed';
  }
  if (session.current_checkpoint_index === checkpointIndex) {
    return 'current';
  }
  return checkpointIndex < session.current_checkpoint_index ? 'passed' : 'pending';
}

function planningStatusClass(status) {
  return String(status || 'draft').replace(/_/g, '-');
}

function findTargetLoop(snapshot, loopId) {
  const targetLoops = Array.isArray(snapshot?.target_loops) ? snapshot.target_loops : [];
  return targetLoops.find((loop) => loop.id === loopId) || null;
}

function renderSessionSummary(summaryEl, snapshot, summaryBits) {
  if (!summaryEl) {
    return;
  }
  if (!snapshot?.session) {
    summaryEl.innerHTML = '';
    return;
  }

  const generatedAt = planningGeneratedAt(snapshot);
  const generatedLabel = generatedAt
    ? `Plan generated ${formatRelativeTimestamp(generatedAt)} · ${formatTimestamp(generatedAt)}`
    : 'Plan generation time unavailable';

  summaryEl.innerHTML = `
    <div class="review-session-chip-group">
      ${summaryBits.map((bit) => `<span class="review-session-chip">${escapeHtml(bit)}</span>`).join('')}
      <span class="review-session-chip">${generatedLabel}</span>
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

  reviewPlanningSessionList.innerHTML = snapshot.checkpoints.map((checkpoint, index) => {
    const checkpointStatus = planningCurrentCheckpointStatus(snapshot, index);
    const focusCount = Array.isArray(checkpoint.focus_loop_ids) ? checkpoint.focus_loop_ids.length : 0;
    return `
      <article class="review-session-item planning-checkpoint-item is-${checkpointStatus}">
        <span class="review-session-item-order planning-checkpoint-badge">${index + 1}</span>
        <span class="review-session-item-body">
          <span class="review-session-item-title">${escapeHtml(checkpoint.title || `Checkpoint ${index + 1}`)}</span>
          <span class="review-session-item-copy">${escapeHtml(checkpoint.summary || 'No summary provided.')}</span>
          <span class="review-session-item-meta">
            <span class="cohort-count ${checkpointStatus === 'pending' ? 'alert' : ''}">${escapeHtml(checkpointStatus)}</span>
            <span class="cohort-count">${(checkpoint.operations || []).length} action${(checkpoint.operations || []).length === 1 ? '' : 's'}</span>
            <span class="cohort-count">Focus loops ${focusCount}</span>
          </span>
        </span>
      </article>
    `;
  }).join('');
}

function renderLoopSummaryCard(loop, { label = null } = {}) {
  return `
    <article class="planning-loop-summary-card">
      <div class="planning-loop-summary-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(label || `Loop #${loop?.id ?? '—'}`)}</p>
          <h5>${formatLoopTitle(loop)}</h5>
        </div>
        <span class="review-session-chip">${escapeHtml(loop?.status || 'unknown')}</span>
      </div>
      <p>${formatLoopPreview(loop)}</p>
      <div class="review-session-chip-group">
        ${loop?.project ? `<span class="review-session-chip">Project: ${escapeHtml(loop.project)}</span>` : ''}
        ${(loop?.tags || []).length ? `<span class="review-session-chip">Tags: ${escapeHtml(loop.tags.join(', '))}</span>` : ''}
        ${loop?.next_action ? `<span class="review-session-chip">Next: ${escapeHtml(loop.next_action)}</span>` : ''}
        ${loop?.due_date ? `<span class="review-session-chip">Due: ${escapeHtml(loop.due_date)}</span>` : ''}
        ${loop?.due_at_utc ? `<span class="review-session-chip">Due at: ${formatTimestamp(loop.due_at_utc)}</span>` : ''}
      </div>
    </article>
  `;
}

function renderLoopCollection(title, loops, emptyMessage) {
  const normalized = Array.isArray(loops) ? loops : [];
  return `
    <section class="planning-loop-collection">
      <div class="planning-loop-collection-header">
        <h5>${escapeHtml(title)}</h5>
        <span class="cohort-count">${normalized.length}</span>
      </div>
      ${normalized.length
        ? `<div class="planning-loop-summary-grid">${normalized.map((loop) => renderLoopSummaryCard(loop)).join('')}</div>`
        : `<div class="review-session-empty">${escapeHtml(emptyMessage)}</div>`}
    </section>
  `;
}

function renderOperationCard(operation) {
  const operationCopy = { ...operation };
  delete operationCopy.summary;
  delete operationCopy.focus_loop_ids;
  return `
    <article class="planning-operation-card">
      <div class="planning-operation-card-header">
        <span class="planning-operation-kind">${escapeHtml(operation.kind || 'operation')}</span>
      </div>
      <p class="planning-operation-summary">${escapeHtml(operation.summary || 'No summary provided.')}</p>
      <details class="planning-operation-details">
        <summary>Inspect operation payload</summary>
        <pre class="planning-operation-payload">${escapeHtml(JSON.stringify(operationCopy, null, 2))}</pre>
      </details>
    </article>
  `;
}

function summarizePlanningExecutionOutputs(result) {
  const summary = [];
  const payload = result?.result && typeof result.result === 'object' ? result.result : {};
  const loop = payload.loop && typeof payload.loop === 'object' ? payload.loop : null;
  const session = payload.session && typeof payload.session === 'object' ? payload.session : null;
  const snapshot = payload.snapshot && typeof payload.snapshot === 'object' ? payload.snapshot : null;

  if (loop) {
    summary.push({
      label: result.kind === 'create_loop' ? 'Created loop' : 'Loop',
      value: loop.title || loop.raw_text || `Loop #${loop.id ?? '—'}`,
    });
  }
  if (session?.name) {
    summary.push({ label: 'Saved session', value: session.name });
  }
  if (snapshot?.session?.name) {
    summary.push({ label: 'Saved session', value: snapshot.session.name });
  }
  if (typeof payload.suggestion_id === 'number') {
    summary.push({ label: 'Suggestion', value: `#${payload.suggestion_id}` });
  }
  if (typeof payload.matched_count === 'number') {
    summary.push({ label: 'Matched loops', value: String(payload.matched_count) });
  }
  if (typeof payload.succeeded === 'number') {
    summary.push({ label: 'Succeeded', value: String(payload.succeeded) });
  }
  if (typeof payload.failed === 'number') {
    summary.push({ label: 'Failed', value: String(payload.failed) });
  }

  return summary;
}

function renderExecutionResult(result) {
  const afterLoops = Array.isArray(result.after_loops) ? result.after_loops : [];
  const beforeLoops = Array.isArray(result.before_loops) ? result.before_loops : [];
  const outputs = summarizePlanningExecutionOutputs(result);

  return `
    <article class="planning-execution-result ${result.ok ? 'is-success' : 'is-error'}">
      <div class="planning-execution-result-header">
        <div>
          <strong>${escapeHtml(result.summary || result.kind || 'Operation')}</strong>
          <p class="planning-execution-result-copy">${escapeHtml(result.kind || 'operation')}</p>
        </div>
        <span class="review-session-chip">${result.undoable ? 'Undo snapshot kept' : 'No undo snapshot'}</span>
      </div>
      ${outputs.length ? `
        <div class="planning-execution-output-list">
          ${outputs.map((item) => `
            <div class="planning-execution-output-item">
              <span class="planning-execution-output-label">${escapeHtml(item.label)}</span>
              <span class="planning-execution-output-value">${escapeHtml(item.value)}</span>
            </div>
          `).join('')}
        </div>
      ` : ''}
      <div class="review-session-chip-group">
        <span class="review-session-chip">Before loops: ${beforeLoops.length}</span>
        <span class="review-session-chip">After loops: ${afterLoops.length}</span>
        <span class="review-session-chip">${result.ok ? 'Executed' : 'Failed'}</span>
      </div>
      ${renderLoopCollection('Before loops', beforeLoops, 'No before-loop snapshot was recorded.')}
      ${renderLoopCollection('After loops', afterLoops, 'No after-loop snapshot was recorded.')}
      <details class="planning-operation-details">
        <summary>Inspect raw execution payload</summary>
        <pre class="planning-operation-payload">${escapeHtml(JSON.stringify(result.result || {}, null, 2))}</pre>
      </details>
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
              <span class="review-session-chip">Executed ${formatRelativeTimestamp(item.executed_at_utc)}</span>
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

function renderCheckpointFocusLoops(snapshot, checkpoint) {
  const focusLoopIds = Array.isArray(checkpoint?.focus_loop_ids) ? checkpoint.focus_loop_ids : [];
  const loops = focusLoopIds
    .map((loopId) => findTargetLoop(snapshot, loopId))
    .filter(Boolean);

  return `
    <section class="planning-loop-collection">
      <div class="planning-loop-collection-header">
        <h5>Focus loops</h5>
        <span class="cohort-count">${focusLoopIds.length}</span>
      </div>
      ${!focusLoopIds.length
        ? '<div class="review-session-empty">This checkpoint does not target existing loops directly. It may create new work or queue a follow-up review session.</div>'
        : loops.length
          ? `<div class="planning-loop-summary-grid">${loops.map((loop) => renderLoopSummaryCard(loop, { label: `Focus loop #${loop.id}` })).join('')}</div>`
          : '<div class="review-session-empty">Focus-loop IDs exist, but none of those loops were present in the grounded target snapshot.</div>'}
    </section>
  `;
}

function renderGroundingSnapshot(snapshot) {
  const contextSummary = snapshot?.context_summary && typeof snapshot.context_summary === 'object'
    ? snapshot.context_summary
    : {};
  const targetLoops = Array.isArray(snapshot?.target_loops) ? snapshot.target_loops : [];
  const sources = Array.isArray(snapshot?.sources) ? snapshot.sources : [];
  const query = snapshot?.session?.query || contextSummary.query || 'next-loop focus';

  return `
    <section class="planning-section-block">
      <div class="planning-section-heading">
        <h4>Grounding snapshot</h4>
        <span class="cohort-count">${targetLoops.length} loops</span>
      </div>
      <div class="planning-grounding-grid">
        <article class="planning-grounding-card">
          <span class="planning-grounding-label">Query</span>
          <strong>${escapeHtml(query)}</strong>
          <p>${snapshot?.session?.query ? 'The planner was scoped with an explicit DSL query.' : 'The planner used the default next-loop focus ordering.'}</p>
        </article>
        <article class="planning-grounding-card">
          <span class="planning-grounding-label">Plan generated</span>
          <strong>${formatRelativeTimestamp(planningGeneratedAt(snapshot))}</strong>
          <p>${formatTimestamp(planningGeneratedAt(snapshot))}</p>
        </article>
        <article class="planning-grounding-card">
          <span class="planning-grounding-label">Memory grounding</span>
          <strong>${Number(contextSummary.memory_entries_used || 0)}</strong>
          <p>Stored memory entries included when the plan was generated.</p>
        </article>
        <article class="planning-grounding-card">
          <span class="planning-grounding-label">RAG grounding</span>
          <strong>${Number(contextSummary.rag_chunks_used || 0)}</strong>
          <p>${sources.length} source${sources.length === 1 ? '' : 's'} captured in the plan snapshot.</p>
        </article>
      </div>
    </section>
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
    (item) => `${item.name} · ${formatStatusLabel(item.status)} · ${item.executed_checkpoint_count}/${item.checkpoint_count}`,
  );

  const summaryBits = session
    ? [
        `Status: ${STATUS_LABELS[session.status] || session.status.replace(/_/g, ' ')}`,
        `Executed: ${session.executed_checkpoint_count}/${session.checkpoint_count}`,
        `Current checkpoint: ${session.checkpoint_count ? session.current_checkpoint_index + 1 : 0}`,
        session.query ? `Query: ${session.query}` : 'Query: next-loop focus',
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
  const targetLoops = Array.isArray(snapshot.target_loops) ? snapshot.target_loops : [];
  const assumptions = Array.isArray(snapshot.assumptions) ? snapshot.assumptions : [];
  const generatedAt = planningGeneratedAt(snapshot);
  const generatedLabel = generatedAt ? `${formatRelativeTimestamp(generatedAt)} · ${formatTimestamp(generatedAt)}` : 'unknown time';

  reviewPlanningSessionDetail.innerHTML = `
    <div class="review-session-card planning-session-card">
      <div class="planning-status-banner is-${planningStatusClass(session.status)}">
        <div>
          <p class="support-eyebrow">${escapeHtml(session.name)}</p>
          <h3>${escapeHtml(snapshot.plan_title || session.name)}</h3>
          <p class="review-session-copy">${escapeHtml(snapshot.plan_summary || session.prompt)}</p>
        </div>
        <div class="planning-status-banner-meta">
          <span class="review-session-chip">${formatStatusLabel(session.status)}</span>
          <span class="review-session-chip">Generated ${generatedLabel}</span>
          <span class="review-session-chip">${session.executed_checkpoint_count}/${session.checkpoint_count} checkpoints executed</span>
        </div>
      </div>
      <div class="review-session-card-header">
        <div class="planning-operator-briefing">
          <div class="review-session-chip-group">
            <span class="review-session-chip">Prompt: ${escapeHtml(session.prompt)}</span>
            <span class="review-session-chip">Loop limit: ${session.loop_limit}</span>
            <span class="review-session-chip">Memory: ${session.include_memory_context ? 'on' : 'off'}</span>
            <span class="review-session-chip">RAG: ${session.include_rag_context ? `on · k=${session.rag_k}` : 'off'}</span>
          </div>
          <div class="planning-operator-callout">
            <strong>${session.status === 'completed' ? 'Plan complete.' : currentExecuted ? 'Current checkpoint already executed.' : 'Ready for operator execution.'}</strong>
            <span>${session.status === 'completed'
              ? 'Refresh the plan if loop state has drifted and you want a fresh grounded workflow.'
              : currentExecuted
                ? 'Move to the next checkpoint or refresh the plan if the surrounding context has changed.'
                : 'Review the focus loops and deterministic operations below before executing the current checkpoint.'}</span>
          </div>
        </div>
        <div class="review-session-card-actions">
          <button type="button" class="secondary" data-action="planning-move" data-direction="previous" ${canMovePrev ? '' : 'disabled'}>Previous</button>
          <button type="button" class="secondary" data-action="planning-move" data-direction="next" ${canMoveNext ? '' : 'disabled'}>Next</button>
          <button type="button" class="secondary" data-action="planning-refresh">Refresh plan</button>
          <button type="button" data-action="planning-execute" ${currentCheckpoint && !currentExecuted ? '' : 'disabled'}>Execute current checkpoint</button>
        </div>
      </div>
      ${renderGroundingSnapshot(snapshot)}
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
          </div>
        ` : '<div class="review-session-empty">No current checkpoint available.</div>'}
        ${currentCheckpoint ? renderCheckpointFocusLoops(snapshot, currentCheckpoint) : ''}
        ${currentCheckpoint ? `<div class="planning-operation-list">${(currentCheckpoint.operations || []).map((operation) => renderOperationCard(operation)).join('')}</div>` : ''}
      </section>
      <section class="planning-section-block">
        <div class="planning-section-heading">
          <h4>Grounded target loops</h4>
          <span class="cohort-count">${targetLoops.length} loaded</span>
        </div>
        ${targetLoops.length ? `<div class="planning-loop-summary-grid">${targetLoops.map((loop) => renderLoopSummaryCard(loop)).join('')}</div>` : '<div class="review-session-empty">No grounded target loops were included in this planning session.</div>'}
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
