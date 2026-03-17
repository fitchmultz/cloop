/**
 * memory.js - Direct memory-management tab.
 *
 * Purpose:
 *   Provide web UI controls for durable memory CRUD and search/list workflows.
 *
 * Responsibilities:
 *   - Load and render memory entries with filters and cursor pagination
 *   - Create new memory entries from the web UI
 *   - Edit and delete existing entries through shared dialogs
 *   - Keep the tab aligned with the canonical memory-management API contract
 *
 * Non-scope:
 *   - Chat grounding controls (see chat.js)
 *   - Global tab switching (see init.js)
 */

import * as api from './api.js';
import * as modals from './modals.js';
import { escapeHtml, formatTime } from './utils.js';

let memoryListEl;
let memoryStatusEl;
let memoryFilterFormEl;
let memoryQueryEl;
let memoryCategoryFilterEl;
let memorySourceFilterEl;
let memoryMinPriorityEl;
let memoryClearFiltersBtnEl;
let memoryRefreshBtnEl;
let memoryLoadMoreBtnEl;
let memoryCreateFormEl;
let memoryKeyEl;
let memoryContentEl;
let memoryCategoryEl;
let memoryPriorityEl;
let memorySourceEl;
let memoryMetadataEl;

let entriesById = new Map();
let nextCursor = null;
let isLoading = false;

function currentFilters() {
  return {
    category: memoryCategoryFilterEl?.value || null,
    source: memorySourceFilterEl?.value || null,
    minPriority: memoryMinPriorityEl?.value ? Number.parseInt(memoryMinPriorityEl.value, 10) : null,
    limit: 25,
  };
}

function currentQuery() {
  return memoryQueryEl?.value?.trim() || '';
}

function setMemoryStatus(message, { isError = false } = {}) {
  if (!memoryStatusEl) {
    return;
  }
  memoryStatusEl.textContent = message;
  memoryStatusEl.classList.toggle('is-error', isError);
}

function parseMetadataJson(rawValue, { emptyValue = {}, fieldLabel = 'Metadata JSON' } = {}) {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return emptyValue;
  }

  let parsed;
  try {
    parsed = JSON.parse(trimmed);
  } catch (error) {
    throw new Error(`${fieldLabel} must be valid JSON.`);
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${fieldLabel} must be a JSON object.`);
  }
  return parsed;
}

function badgeMarkup(text, modifier = '') {
  const modifierClass = modifier ? ` memory-badge-${modifier}` : '';
  return `<span class="memory-badge${modifierClass}">${escapeHtml(text)}</span>`;
}

function metadataMarkup(metadata) {
  if (!metadata || Object.keys(metadata).length === 0) {
    return '';
  }
  return `
    <details class="memory-card-details">
      <summary>Metadata</summary>
      <pre>${escapeHtml(JSON.stringify(metadata, null, 2))}</pre>
    </details>
  `;
}

function renderMemoryEntry(entry) {
  const keyLine = entry.key
    ? `<div class="memory-card-key">${escapeHtml(entry.key)}</div>`
    : '<div class="memory-card-key memory-card-key-empty">No key</div>';
  const updatedAt = formatTime(entry.updated_at) || entry.updated_at || '';
  return `
    <article class="memory-card" data-memory-id="${entry.id}">
      <div class="memory-card-main">
        <div class="memory-card-header">
          <div>
            ${keyLine}
            <div class="memory-card-meta">
              ${badgeMarkup(entry.category, 'category')}
              ${badgeMarkup(entry.source, 'source')}
              ${badgeMarkup(`Priority ${entry.priority}`, 'priority')}
            </div>
          </div>
          <div class="memory-card-actions">
            <button type="button" class="secondary" data-memory-action="edit" data-memory-id="${entry.id}">Edit</button>
            <button type="button" class="secondary" data-memory-action="delete" data-memory-id="${entry.id}">Delete</button>
          </div>
        </div>
        <p class="memory-card-content">${escapeHtml(entry.content).replace(/\n/g, '<br>')}</p>
        ${metadataMarkup(entry.metadata)}
      </div>
      <div class="memory-card-footer">Updated ${escapeHtml(updatedAt || 'unknown time')}</div>
    </article>
  `;
}

function renderEmptyState(message) {
  memoryListEl.innerHTML = `
    <div class="memory-empty-state">
      <strong>${escapeHtml(message)}</strong>
      <p>Create a durable memory entry on the right, or widen your filters and search.</p>
    </div>
  `;
}

function renderMemoryList(items, { append = false } = {}) {
  if (!memoryListEl) {
    return;
  }

  if (!append) {
    entriesById = new Map();
    memoryListEl.innerHTML = '';
  }

  items.forEach((entry) => entriesById.set(entry.id, entry));

  if (!append && items.length === 0) {
    const query = currentQuery();
    renderEmptyState(query ? `No memories matched “${query}”.` : 'No memory entries yet.');
    return;
  }

  const markup = items.map((entry) => renderMemoryEntry(entry)).join('');
  if (append) {
    memoryListEl.insertAdjacentHTML('beforeend', markup);
  } else {
    memoryListEl.innerHTML = markup;
  }
}

function syncLoadMoreButton() {
  if (!memoryLoadMoreBtnEl) {
    return;
  }
  memoryLoadMoreBtnEl.hidden = !nextCursor;
  memoryLoadMoreBtnEl.disabled = isLoading || !nextCursor;
}

function createPayloadFromForm() {
  return {
    key: memoryKeyEl?.value?.trim() || null,
    content: memoryContentEl?.value?.trim() || '',
    category: memoryCategoryEl?.value || 'fact',
    priority: Number.parseInt(memoryPriorityEl?.value || '0', 10) || 0,
    source: memorySourceEl?.value || 'user_stated',
    metadata: parseMetadataJson(memoryMetadataEl?.value || '', { emptyValue: {} }),
  };
}

function resetCreateForm() {
  memoryCreateFormEl?.reset();
  if (memoryCategoryEl) {
    memoryCategoryEl.value = 'fact';
  }
  if (memoryPriorityEl) {
    memoryPriorityEl.value = '0';
  }
  if (memorySourceEl) {
    memorySourceEl.value = 'user_stated';
  }
}

export async function loadMemories({ append = false } = {}) {
  if (!memoryListEl || isLoading) {
    return;
  }

  const filters = currentFilters();
  const query = currentQuery();
  const cursor = append ? nextCursor : null;
  isLoading = true;
  syncLoadMoreButton();

  if (!append) {
    setMemoryStatus(query ? 'Searching memory…' : 'Loading memory…');
  }

  try {
    const result = query
      ? await api.searchMemoryEntries(query, { ...filters, cursor })
      : await api.fetchMemoryEntries({ ...filters, cursor });

    nextCursor = result.next_cursor || null;
    renderMemoryList(result.items || [], { append });

    const loadedCount = entriesById.size;
    if (query) {
      setMemoryStatus(loadedCount ? `Showing ${loadedCount} memory match${loadedCount === 1 ? '' : 'es'}.` : `No memories matched “${query}”.`);
    } else {
      setMemoryStatus(loadedCount ? `Showing ${loadedCount} memory entr${loadedCount === 1 ? 'y' : 'ies'}.` : 'No memory entries yet.');
    }
  } catch (error) {
    setMemoryStatus(error.message, { isError: true });
  } finally {
    isLoading = false;
    syncLoadMoreButton();
  }
}

async function handleCreateMemory(event) {
  event.preventDefault();

  let payload;
  try {
    payload = createPayloadFromForm();
  } catch (error) {
    setMemoryStatus(error.message, { isError: true });
    return;
  }

  if (!payload.content) {
    setMemoryStatus('Enter memory content first.', { isError: true });
    memoryContentEl?.focus();
    return;
  }

  setMemoryStatus('Creating memory entry…');
  try {
    const created = await api.createMemoryEntry(payload);
    resetCreateForm();
    setMemoryStatus(`Created memory ${created.id}.`);
    await loadMemories();
  } catch (error) {
    setMemoryStatus(error.message, { isError: true });
  }
}

async function editMemoryEntry(entryId) {
  const entry = entriesById.get(entryId) || await api.fetchMemoryEntry(entryId);
  const metadataValue = entry.metadata && Object.keys(entry.metadata).length
    ? JSON.stringify(entry.metadata, null, 2)
    : '';

  const result = await modals.promptDialog({
    eyebrow: 'Memory',
    title: `Edit memory ${entryId}`,
    description: 'Update the durable memory entry using the shared direct-memory contract.',
    confirmLabel: 'Save memory',
    fields: [
      {
        name: 'key',
        label: 'Key',
        value: entry.key || '',
        placeholder: 'Optional identifier',
        maxLength: 120,
        autocomplete: 'off',
      },
      {
        name: 'content',
        label: 'Content',
        value: entry.content,
        type: 'textarea',
        rows: 4,
        required: true,
        maxLength: 4000,
      },
      {
        name: 'category',
        label: 'Category',
        type: 'select',
        value: entry.category,
        options: [
          { value: 'fact', label: 'Fact' },
          { value: 'preference', label: 'Preference' },
          { value: 'commitment', label: 'Commitment' },
          { value: 'context', label: 'Context' },
        ],
      },
      {
        name: 'priority',
        label: 'Priority',
        value: String(entry.priority),
        type: 'number',
        inputMode: 'numeric',
      },
      {
        name: 'source',
        label: 'Source',
        type: 'select',
        value: entry.source,
        options: [
          { value: 'user_stated', label: 'User stated' },
          { value: 'inferred', label: 'Inferred' },
          { value: 'imported', label: 'Imported' },
          { value: 'system', label: 'System' },
        ],
      },
      {
        name: 'metadata',
        label: 'Metadata JSON',
        value: metadataValue,
        type: 'textarea',
        rows: 5,
        placeholder: '{"source_app": "web"}',
      },
    ],
    validate: (values) => {
      if (!values.content) {
        return 'Content is required.';
      }
      try {
        parseMetadataJson(values.metadata || '', { emptyValue: {}, fieldLabel: 'Metadata JSON' });
      } catch (error) {
        return error.message;
      }
      const parsedPriority = Number.parseInt(values.priority || '0', 10);
      if (Number.isNaN(parsedPriority) || parsedPriority < 0 || parsedPriority > 100) {
        return 'Priority must be between 0 and 100.';
      }
      return null;
    },
  });

  if (!result) {
    return;
  }

  const payload = {
    key: result.key || null,
    content: result.content,
    category: result.category,
    priority: Number.parseInt(result.priority || '0', 10),
    source: result.source,
    metadata: parseMetadataJson(result.metadata || '', { emptyValue: {} }),
  };

  setMemoryStatus(`Saving memory ${entryId}…`);
  try {
    const updated = await api.updateMemoryEntry(entryId, payload);
    entriesById.set(updated.id, updated);
    setMemoryStatus(`Updated memory ${entryId}.`);
    await loadMemories();
  } catch (error) {
    setMemoryStatus(error.message, { isError: true });
  }
}

async function deleteMemoryEntryById(entryId) {
  const confirmed = await modals.confirmDialog({
    eyebrow: 'Memory',
    title: `Delete memory ${entryId}?`,
    description: 'This removes the durable memory entry immediately.',
    confirmLabel: 'Delete memory',
    confirmVariant: 'danger',
  });
  if (!confirmed) {
    return;
  }

  setMemoryStatus(`Deleting memory ${entryId}…`);
  try {
    await api.deleteMemoryEntry(entryId);
    entriesById.delete(entryId);
    setMemoryStatus(`Deleted memory ${entryId}.`);
    await loadMemories();
  } catch (error) {
    setMemoryStatus(error.message, { isError: true });
  }
}

function handleMemoryListClick(event) {
  const button = event.target.closest('[data-memory-action]');
  if (!button) {
    return;
  }

  const entryId = Number.parseInt(button.dataset.memoryId || '', 10);
  if (Number.isNaN(entryId)) {
    return;
  }

  if (button.dataset.memoryAction === 'edit') {
    void editMemoryEntry(entryId);
    return;
  }

  if (button.dataset.memoryAction === 'delete') {
    void deleteMemoryEntryById(entryId);
  }
}

function clearFiltersAndReload() {
  if (memoryQueryEl) memoryQueryEl.value = '';
  if (memoryCategoryFilterEl) memoryCategoryFilterEl.value = '';
  if (memorySourceFilterEl) memorySourceFilterEl.value = '';
  if (memoryMinPriorityEl) memoryMinPriorityEl.value = '';
  nextCursor = null;
  void loadMemories();
}

export function init(elements) {
  memoryListEl = elements.memoryList;
  memoryStatusEl = elements.memoryStatus;
  memoryFilterFormEl = elements.memoryFilterForm;
  memoryQueryEl = elements.memoryQuery;
  memoryCategoryFilterEl = elements.memoryCategoryFilter;
  memorySourceFilterEl = elements.memorySourceFilter;
  memoryMinPriorityEl = elements.memoryMinPriority;
  memoryClearFiltersBtnEl = elements.memoryClearFiltersBtn;
  memoryRefreshBtnEl = elements.memoryRefreshBtn;
  memoryLoadMoreBtnEl = elements.memoryLoadMoreBtn;
  memoryCreateFormEl = elements.memoryCreateForm;
  memoryKeyEl = elements.memoryKey;
  memoryContentEl = elements.memoryContent;
  memoryCategoryEl = elements.memoryCategory;
  memoryPriorityEl = elements.memoryPriority;
  memorySourceEl = elements.memorySource;
  memoryMetadataEl = elements.memoryMetadata;

  memoryFilterFormEl?.addEventListener('submit', (event) => {
    event.preventDefault();
    nextCursor = null;
    void loadMemories();
  });
  memoryClearFiltersBtnEl?.addEventListener('click', clearFiltersAndReload);
  memoryRefreshBtnEl?.addEventListener('click', () => {
    nextCursor = null;
    void loadMemories();
  });
  memoryLoadMoreBtnEl?.addEventListener('click', () => {
    if (!nextCursor) {
      return;
    }
    void loadMemories({ append: true });
  });
  memoryCreateFormEl?.addEventListener('submit', handleCreateMemory);
  memoryListEl?.addEventListener('click', handleMemoryListClick);

  syncLoadMoreButton();
  setMemoryStatus('Direct memory CRUD uses the shared memory-management contract.');
}
