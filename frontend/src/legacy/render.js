/**
 * render.js - DOM rendering utilities
 *
 * Purpose:
 *   Generate HTML for loops, comments, and UI components.
 *
 * Responsibilities:
 *   - Render loop cards with all fields
 *   - Render comment threads
 *   - Format dates and times
 *   - Escape HTML for security
 *   - Handle textarea auto-resize
 *   - Status badge rendering
 *
 * Non-scope:
 *   - API calls (see api.js)
 *   - Event handling (see individual modules)
 *   - State management (see state.js)
 */

import {
  dueDateInputValueFromLoop,
  escapeHtml,
  formatDueLabel,
  formatDueValue,
  formatTime,
  localTimeInputValueFromIso,
} from './utils.js';

// Status options for dropdown
const statusOptions = [
  "inbox",
  "actionable",
  "blocked",
  "scheduled",
  "completed",
  "dropped",
];

/**
 * Generate status select dropdown HTML
 */
export function statusSelectOptions(current) {
  return statusOptions
    .map(
      (status) =>
        `<option value="${status}" ${status === current ? "selected" : ""}>${status}</option>`,
    )
    .join("");
}

/**
 * Auto-resize textarea to fit content
 */
export function autoResizeTextarea(textarea) {
  textarea.style.height = "0px";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

/**
 * Queue auto-resize for all next_action textareas in a container
 */
export function queueNextActionResize(root) {
  const targets = root.querySelectorAll
    ? root.querySelectorAll('[data-field="next_action"]')
    : [];
  requestAnimationFrame(() => {
    targets.forEach(autoResizeTextarea);
  });
}

function isCompactLoop(loop) {
  return new Set(["completed", "dropped"]).has(loop.status);
}

function hasLongMobileCardText(compactCard, capturedText, summary) {
  if (compactCard) {
    return false;
  }
  return capturedText.length > 260 || summary.length > 180;
}

function buildDueEditor(loop) {
  const dueLabel = formatDueLabel(loop);
  const hasDueValue = Boolean(loop.due_date || loop.due_at_utc);
  const dueFieldClass = hasDueValue ? "due-field has-value" : "due-field";

  return `
    <div class="${dueFieldClass}" data-due-field>
      <button
        type="button"
        class="badge due-display ${hasDueValue ? "has-value" : "empty"}"
        data-action="edit-due"
        aria-label="${escapeHtml(dueLabel)}"
      >
        ${escapeHtml(dueLabel)}
      </button>
      <div class="due-editor">
        <label class="due-editor-label">
          <span>Due date</span>
          <input
            class="badge-input due-input"
            type="text"
            data-field="due_date"
            placeholder="MM/DD/YYYY"
            inputmode="numeric"
            autocomplete="off"
            maxlength="10"
            aria-label="Due date"
          >
        </label>
        <label class="due-editor-label due-editor-label-time">
          <span>Time (optional)</span>
          <input
            class="badge-input due-time-input"
            type="time"
            data-field="due_time"
            aria-label="Due time"
          >
        </label>
        <button type="button" class="secondary due-clear" data-action="clear-due">Clear</button>
      </div>
    </div>
  `;
}

export function setCompactCardExpanded(card, expanded) {
  if (!card?.classList?.contains("compact-card")) {
    return;
  }

  card.classList.toggle("compact-expanded", expanded);
  card.dataset.compactMode = expanded ? "expanded" : "summary";

  const toggle = card.querySelector('[data-action="toggle-compact"]');
  if (toggle) {
    card.querySelectorAll('[data-action="toggle-compact"]').forEach((button) => {
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
  }

  const readonlySelectors = [
    '[data-field="title"]',
    '[data-field="next_action"]',
    '[data-field="blocked_reason"]',
    ".completion-note-input",
    '[data-field="tags_add"]',
  ];

  readonlySelectors.forEach((selector) => {
    const field = card.querySelector(selector);
    if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
      field.readOnly = !expanded;
      field.tabIndex = expanded ? 0 : -1;
    }
  });

  const disabledSelectors = [
    '[data-field="status"]',
    '[data-field="due_date"]',
    '[data-field="due_time"]',
    '[data-recurrence-toggle]',
    '[data-recurrence-schedule]',
  ];

  disabledSelectors.forEach((selector) => {
    const field = card.querySelector(selector);
    if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
      field.disabled = !expanded;
      field.tabIndex = expanded ? 0 : -1;
    }
  });

  card.querySelectorAll('[data-action="remove-tag"], [data-action="edit-tags"]').forEach((button) => {
    if (button instanceof HTMLButtonElement) {
      button.disabled = !expanded;
      button.tabIndex = expanded ? 0 : -1;
    }
  });

  if (!expanded) {
    setDueEditorExpanded(card, false);
  }
}

export function setMobileCardTextExpanded(card, expanded) {
  if (!card?.classList?.contains("mobile-text-collapsible")) {
    return;
  }

  card.classList.toggle("mobile-text-expanded", expanded);
  card.dataset.mobileTextMode = expanded ? "expanded" : "collapsed";

  const toggle = card.querySelector('[data-action="toggle-card-body"]');
  if (toggle instanceof HTMLButtonElement) {
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggle.textContent = expanded ? "Show less" : "Show full context";
  }
}

export function setDueEditorExpanded(card, expanded) {
  const dueField = card?.querySelector?.('[data-due-field]');
  if (!dueField) {
    return;
  }

  dueField.classList.toggle("editing", expanded);
  const trigger = dueField.querySelector('[data-action="edit-due"]');
  const dateInput = dueField.querySelector('[data-field="due_date"]');
  const timeInput = dueField.querySelector('[data-field="due_time"]');
  const clearButton = dueField.querySelector('[data-action="clear-due"]');

  if (trigger instanceof HTMLButtonElement) {
    trigger.hidden = expanded;
    trigger.tabIndex = expanded ? -1 : 0;
  }

  [dateInput, timeInput].forEach((input) => {
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    input.disabled = !expanded;
    input.tabIndex = expanded ? 0 : -1;
  });

  if (dateInput instanceof HTMLInputElement && expanded) {
    requestAnimationFrame(() => {
      dateInput.focus();
      dateInput.select?.();
    });
  }

  if (clearButton instanceof HTMLButtonElement) {
    clearButton.disabled = !expanded;
    clearButton.tabIndex = expanded ? 0 : -1;
  }
}

function formatLoopStateLabel(value) {
  return String(value ?? "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function buildLoopContextBadges(loop) {
  const badges = [];
  const projectName = String(loop.project ?? "").trim();
  const semanticScore = typeof loop.semantic_score === "number" ? loop.semantic_score : null;
  const tags = Array.isArray(loop.tags)
    ? loop.tags
        .map((tag) => String(tag ?? "").trim())
        .filter(Boolean)
    : [];

  if (semanticScore !== null) {
    badges.push(`
      <span class="loop-context-badge semantic-score">
        <span class="loop-context-badge-label">Semantic</span>
        <span class="loop-context-badge-value">${escapeHtml(semanticScore.toFixed(3))}</span>
      </span>
    `);
  }

  if (projectName) {
    badges.push(`
      <span class="loop-context-badge project">
        <span class="loop-context-badge-label">Project</span>
        <span class="loop-context-badge-value">${escapeHtml(projectName)}</span>
      </span>
    `);
  }

  tags.forEach((tag) => {
    badges.push(`
      <span class="loop-context-badge tag-pill">
        <span class="loop-context-badge-label">Tag</span>
        <span class="loop-context-badge-value">${escapeHtml(tag)}</span>
      </span>
    `);
  });

  return badges.join("");
}

function buildNextMetaBadges(loop, enrichmentLabel, snoozeIndicatorHtml) {
  const meta = [
    `<span class="badge">${escapeHtml(formatLoopStateLabel(loop.status))}</span>`,
  ];

  if (loop.due_date || loop.due_at_utc) {
    meta.push(`<span class="badge next-card-badge-strong">Due ${escapeHtml(formatDueValue(loop))}</span>`);
  }

  if (loop.total_tracked_minutes) {
    meta.push(`<span class="badge">${loop.total_tracked_minutes}m tracked</span>`);
  } else if (loop.time_minutes) {
    meta.push(`<span class="badge pending">Est. ${loop.time_minutes}m</span>`);
  }

  meta.push(`<span class="badge">${escapeHtml(enrichmentLabel)}</span>`);

  if (snoozeIndicatorHtml) {
    meta.push(snoozeIndicatorHtml);
  }

  return meta.join("");
}

function renderNextLoop(loop) {
  const card = document.createElement("article");
  const title = loop.title || loop.raw_text;
  const summary = loop.summary || loop.definition_of_done || "";
  const nextActionSummary = loop.next_action?.trim() || "Open this loop in Inbox to capture a crisp next action.";
  const capturedText =
    loop.raw_text && loop.raw_text.trim() && loop.raw_text.trim() !== title
      ? loop.raw_text.trim()
      : "";
  const contextBadges = buildLoopContextBadges(loop);
  const enrichmentState = loop.enrichment_state || "idle";
  const enrichmentLabel =
    enrichmentState === "pending"
      ? "Enrichment pending"
      : enrichmentState === "complete"
        ? "Enrichment complete"
        : enrichmentState === "failed"
          ? "Enrichment failed"
          : "Enrichment idle";
  const snoozedUntil = loop.snooze_until_utc;
  const isSnoozed = snoozedUntil && new Date(snoozedUntil) > new Date();
  const snoozeIndicatorHtml = isSnoozed
    ? `<span class="snooze-indicator">Snoozed until ${escapeHtml(formatTime(snoozedUntil))}</span>`
    : "";
  const supportingCopy = summary || capturedText;
  const timerDisplay = loop.timer_display || "";
  const timerLabel = loop.timer_running ? "Stop focus" : "Start focus";

  card.dataset.loopId = loop.id;
  card.dataset.status = loop.status;
  card.dataset.tags = JSON.stringify(loop.tags || []);
  card.className = "loop-card next-card";
  card.innerHTML = `
    <div class="next-card-shell">
      <div class="next-card-header">
        <div class="next-card-title-block">
          <h4 class="next-card-title">${escapeHtml(title)}</h4>
          ${supportingCopy ? `<p class="next-card-summary">${escapeHtml(supportingCopy)}</p>` : ""}
        </div>
        <div class="next-card-stamp">
          <span>Updated ${escapeHtml(formatTime(loop.updated_at_utc))}</span>
          ${loop.captured_at_utc ? `<span>Captured ${escapeHtml(formatTime(loop.captured_at_utc))}</span>` : ""}
        </div>
      </div>
      <div class="next-card-meta">
        ${buildNextMetaBadges(loop, enrichmentLabel, snoozeIndicatorHtml)}
      </div>
      <div class="next-card-focus">
        <span class="inline-label">Do next</span>
        <p>${escapeHtml(nextActionSummary)}</p>
      </div>
      ${contextBadges ? `<div class="loop-context-strip next-card-context">${contextBadges}</div>` : ""}
      <div class="next-card-actions">
        <button
          class="timer-btn next-card-focus-btn ${loop.timer_running ? "running" : ""}"
          data-action="timer-toggle"
          data-id="${loop.id}"
          data-running="${loop.timer_running ? "true" : "false"}"
          aria-keyshortcuts="T"
          title="${timerLabel} (T)"
        >
          ${loop.timer_running ? "⏹ Stop focus" : "▶ Start focus"}
        </button>
        ${timerDisplay ? `<span class="timer-display ${loop.timer_running ? "active" : ""}" data-timer-display="${loop.id}">${escapeHtml(timerDisplay)}</span>` : ""}
        <button
          type="button"
          class="secondary next-card-review-btn"
          data-action="jump-to-inbox"
          data-loop-id="${loop.id}"
        >
          Review in Inbox
        </button>
      </div>
    </div>
  `;

  return card;
}

export function renderInboxEmptyState({ query = "", status = "open", tag = "" } = {}) {
  const hasActiveFilters = Boolean(query || tag || !["open", "all"].includes(status));
  const title = hasActiveFilters ? "No loops match this view." : "Inbox is clear.";
  const body = hasActiveFilters
    ? "Try a broader query, switch the status filter, or clear the tag filter to bring loops back into view."
    : "Capture your first loop above to start organizing work, or switch to Next once you have actionable items.";
  const hint = hasActiveFilters
    ? `Current view: ${escapeHtml(formatLoopStateLabel(status))}${tag ? ` • tag:${escapeHtml(tag)}` : ""}${query ? ` • query:${escapeHtml(query)}` : ""}`
    : "Fresh start: your Inbox will fill here as soon as you capture a loop, idea, or reminder.";

  const emptyState = document.createElement("section");
  emptyState.className = "inbox-empty-state";
  emptyState.setAttribute("aria-live", "polite");
  emptyState.innerHTML = `
    <div class="inbox-empty-icon" aria-hidden="true">+</div>
    <div class="inbox-empty-copy">
      <h3>${title}</h3>
      <p>${body}</p>
      <p class="inbox-empty-hint">${hint}</p>
    </div>
  `;
  return emptyState;
}

/**
 * Render a single loop card
 */
export function renderLoop(loop, options = {}) {
  if (options.surface === "next") {
    return renderNextLoop(loop);
  }

  const card = document.createElement("div");
  const compactCard = isCompactLoop(loop);
  card.dataset.loopId = loop.id;
  card.dataset.status = loop.status;
  card.dataset.tags = JSON.stringify(loop.tags || []);

  const checkboxHtml = `
    <div class="loop-select">
      <input
        type="checkbox"
        class="loop-checkbox"
        data-loop-id="${loop.id}"
        aria-label="Select loop ${loop.id}"
      >
    </div>
  `;

  const title = loop.title || loop.raw_text;
  const summary = loop.summary || loop.definition_of_done || "";
  const contextBadges = buildLoopContextBadges(loop);
  const hasContextBadges = Boolean(contextBadges);
  const capturedText =
    loop.raw_text && loop.raw_text.trim() && loop.raw_text.trim() !== title
      ? loop.raw_text.trim()
      : "";
  const mobileTextCollapsible = hasLongMobileCardText(compactCard, capturedText, summary);
  card.className = `loop-card has-checkbox${compactCard ? " compact-card" : ""}${mobileTextCollapsible ? " mobile-text-collapsible" : ""}`;
  const closed = loop.closed_at_utc ? `Closed: ${formatTime(loop.closed_at_utc)}` : "";
  const completionNoteValue = loop.completion_note || "";
  const completionVisible = Boolean(completionNoteValue.trim());
  const nextActionSummary = loop.next_action?.trim() || "";
  const timerDisplay = loop.timer_display || "";
  const hasTimerMeta = Boolean(timerDisplay || loop.total_tracked_minutes || loop.time_minutes);

  const tagChips = Array.isArray(loop.tags) && loop.tags.length
    ? loop.tags
        .map(
          (tag) => `
            <span class="tag tag-chip" data-tag="${escapeHtml(tag)}">
              <span class="tag-text">${escapeHtml(tag)}</span>
              <button
                class="tag-remove"
                type="button"
                data-action="remove-tag"
                data-tag="${escapeHtml(tag)}"
                aria-label="Remove tag ${escapeHtml(tag)}"
              >
                x
              </button>
            </span>
          `,
        )
        .join("")
    : "";

  const tags = `
    <div class="tags-edit">
      <div class="tags tags-chips">${tagChips}</div>
      <button class="tag-add" type="button" data-action="edit-tags">${tagChips ? "+ add" : "Add tags"}</button>
      <input
        class="tag-input"
        type="text"
        data-field="tags_add"
        placeholder="tag1, tag2"
      >
    </div>
  `;

  const enrichmentState = loop.enrichment_state || "idle";
  const enrichmentLabel =
    enrichmentState === "pending"
      ? "Enrichment pending"
      : enrichmentState === "complete"
        ? "Enrichment complete"
        : enrichmentState === "failed"
          ? "Enrichment failed"
          : "Enrichment idle";

  const snoozedUntil = loop.snooze_until_utc;
  const isSnoozed = snoozedUntil && new Date(snoozedUntil) > new Date();
  const snoozeIndicatorHtml = isSnoozed
    ? `<span class="snooze-indicator">Snoozed until ${formatTime(snoozedUntil)}</span>`
    : "";

  const recurrenceEnabled = loop.recurrence_enabled || false;
  const recurrenceRrule = loop.recurrence_rrule || "";
  const nextDueAt = loop.next_due_at_utc || "";
  const showRecurrenceSection = recurrenceEnabled || !compactCard;
  const dueEditorHtml = buildDueEditor(loop);
  const compactSummaryStateHtml = compactCard
    ? `
      <div class="compact-summary-strip">
        <span class="badge">${loop.status}</span>
        ${loop.due_date || loop.due_at_utc ? `<span class="badge">Due ${escapeHtml(formatDueValue(loop))}</span>` : ""}
        ${closed ? `<span class="badge">${closed}</span>` : ""}
        <span class="badge ${enrichmentState}">${enrichmentLabel}</span>
        ${snoozeIndicatorHtml}
        <button type="button" class="secondary compact-toggle compact-toggle-summary" data-action="toggle-compact" aria-expanded="false">Edit</button>
      </div>
      <div class="compact-edit-strip">
        <select class="badge-select" data-field="status" aria-label="Loop status">
          ${statusSelectOptions(loop.status)}
        </select>
        ${dueEditorHtml}
        ${closed ? `<span class="badge">${closed}</span>` : ""}
        <span class="badge ${enrichmentState}">${enrichmentLabel}</span>
        ${snoozeIndicatorHtml}
        <button type="button" class="secondary compact-toggle compact-toggle-edit" data-action="toggle-compact" aria-expanded="true">Done</button>
      </div>
    `
    : `
      <select class="badge-select" data-field="status" aria-label="Loop status">
        ${statusSelectOptions(loop.status)}
      </select>
      ${dueEditorHtml}
      ${closed ? `<span class="badge">${closed}</span>` : ""}
      <span class="badge ${enrichmentState}">${enrichmentLabel}</span>
      ${snoozeIndicatorHtml}
    `;
  const secondaryActionsHtml = `
    <div class="snooze-wrapper">
      <button class="secondary snooze-btn" data-action="snooze" data-id="${loop.id}" aria-keyshortcuts="S" title="Snooze (S)">
        Snooze
      </button>
      <div class="snooze-dropdown" data-snooze-dropdown="${loop.id}">
        <button type="button" class="snooze-option" data-snooze-duration="1h">1 hour</button>
        <button type="button" class="snooze-option" data-snooze-duration="4h">4 hours</button>
        <button type="button" class="snooze-option" data-snooze-duration="1d">1 day</button>
        <button type="button" class="snooze-option" data-snooze-duration="1w">1 week</button>
        <div class="snooze-custom">
          <label for="snooze-custom-${loop.id}">Custom</label>
          <input type="datetime-local" id="snooze-custom-${loop.id}" class="snooze-datetime" data-snooze-custom="${loop.id}" aria-label="Custom snooze date and time">
        </div>
      </div>
    </div>
    <button class="secondary" data-action="enrich" data-id="${loop.id}" aria-keyshortcuts="E" title="Re-run enrichment (E)">Enrich</button>
    <button class="secondary" data-action="refresh" data-id="${loop.id}" aria-keyshortcuts="R" title="Refresh loop details (R)">Refresh</button>
    <button class="secondary" data-action="save-template" data-id="${loop.id}" title="Save as template">Template</button>
  `;

  card.innerHTML = `
    ${checkboxHtml}
    <div class="loop-card-shell">
      <div class="loop-header">
        <div class="loop-identity">
          ${compactCard ? `<div class="compact-title-summary">${escapeHtml(title)}</div>` : ""}
          <input
            class="title-input ${compactCard ? "compact-edit-field" : ""}"
            type="text"
            data-field="title"
            placeholder="Untitled"
          >
          <div class="loop-meta">
            <span>Captured: ${formatTime(loop.captured_at_utc)}</span>
            <span>Updated: ${formatTime(loop.updated_at_utc)}</span>
          </div>
        </div>
        <div class="loop-state-strip">
          ${compactSummaryStateHtml}
        </div>
      </div>
      <div class="loop-content">
        ${capturedText ? `<div class="captured-text"><span class="captured-text-label">Captured text</span><p>${escapeHtml(capturedText)}</p></div>` : ""}
        ${summary ? `<div class="loop-summary">${escapeHtml(summary)}</div>` : ""}
        ${hasContextBadges ? `<div class="loop-context-strip">${contextBadges}</div>` : ""}
        ${mobileTextCollapsible ? `
          <button
            type="button"
            class="secondary mobile-card-toggle"
            data-action="toggle-card-body"
            aria-expanded="false"
          >
            Show full context
          </button>
        ` : ""}
        <div class="loop-planning-grid">
          ${compactCard ? `
            <div class="compact-next-action-summary ${nextActionSummary ? "" : "empty"}">
              <span class="inline-label">Next action</span>
              <p>${nextActionSummary ? escapeHtml(nextActionSummary) : "No next action captured."}</p>
            </div>
          ` : ""}
          <div class="inline-row loop-next-action ${compactCard ? "compact-edit-field" : ""}">
            <span class="inline-label">Next action</span>
            <textarea
              class="inline-input inline-textarea"
              rows="1"
              data-field="next_action"
              placeholder="Add next action"
            ></textarea>
          </div>
          <div class="loop-supporting-fields">
            ${tags}
            <div class="blocked-reason-row ${loop.status === "blocked" ? "visible" : ""}">
              <span class="inline-label">Blocked by</span>
              <input
                class="inline-input"
                type="text"
                data-field="blocked_reason"
                placeholder="What's blocking this?"
              >
            </div>
          </div>
        </div>
      </div>
      <div class="loop-operations">
        <div class="timer-section">
          <button
            class="timer-btn ${loop.timer_running ? 'running' : ''}"
            data-action="timer-toggle"
            data-id="${loop.id}"
            data-running="${loop.timer_running ? 'true' : 'false'}"
            aria-keyshortcuts="T"
            title="Toggle timer (T)"
          >
            ${loop.timer_running ? '⏹ Stop' : '▶ Start'}
          </button>
          ${hasTimerMeta ? `
            <div class="timer-meta">
              ${timerDisplay ? `<span class="timer-display ${loop.timer_running ? 'active' : ''}" data-timer-display="${loop.id}">${timerDisplay}</span>` : ''}
              ${loop.total_tracked_minutes ? `<span class="badge">${loop.total_tracked_minutes}m tracked</span>` : ''}
              ${loop.time_minutes ? `<span class="badge pending">est: ${loop.time_minutes}m</span>` : ''}
            </div>
          ` : ''}
        </div>
        ${showRecurrenceSection ? `
          <div class="recurrence-section ${recurrenceEnabled ? 'expanded' : ''}" data-recurrence-section="${loop.id}">
            <div class="recurrence-header">
              <label class="recurrence-toggle">
                <input type="checkbox" data-recurrence-toggle="${loop.id}" ${recurrenceEnabled ? 'checked' : ''}>
                <span class="recurrence-slider"></span>
              </label>
              <span class="recurrence-label">Recurring</span>
            </div>
            <div class="recurrence-config ${recurrenceEnabled ? 'visible' : ''}">
              <input
                type="text"
                class="recurrence-schedule-input"
                data-recurrence-schedule="${loop.id}"
                placeholder="e.g., 'every weekday', 'every Monday at 9am', 'every 2 weeks'"
                value="${escapeHtml(recurrenceRrule)}"
              >
              <div class="recurrence-preview" data-recurrence-preview="${loop.id}">
                ${nextDueAt ? `Next: ${formatTime(nextDueAt)}` : 'Enter a schedule to see next occurrence'}
              </div>
              <div class="recurrence-error" data-recurrence-error="${loop.id}"></div>
            </div>
          </div>
        ` : ""}
      </div>
      <div class="loop-footer">
        <div class="loop-actions">
          <button class="secondary" data-action="complete" data-id="${loop.id}" aria-keyshortcuts="C" title="Complete with note (C)">
            Complete…
          </button>
          ${compactCard ? `
            <details class="compact-actions-menu">
              <summary class="secondary compact-actions-trigger">More</summary>
              <div class="compact-actions-panel">
                ${secondaryActionsHtml}
              </div>
            </details>
          ` : secondaryActionsHtml}
        </div>
        <div class="completion-note-row ${completionVisible ? "visible" : ""}">
          <span class="inline-label">completion note</span>
          <input
            class="inline-input completion-note-input"
            type="text"
            placeholder="Add a note (optional)"
            data-action="completion-note"
          >
          <button class="completion-confirm" data-action="confirm-complete" data-id="${loop.id}" type="button">
            Mark done
          </button>
          <button class="completion-cancel" data-action="cancel-complete" data-id="${loop.id}" aria-label="Cancel completion note">
            ×
          </button>
          <span class="completion-hint">Press Enter to confirm or Esc to cancel.</span>
        </div>
        <div class="comments-section" data-comments-section="${loop.id}">
          <div class="comments-header" data-comments-toggle="${loop.id}">
            <span class="comments-count" data-comments-count="${loop.id}">Comments</span>
            <span class="comments-toggle">▼</span>
          </div>
          <div class="comments-body" data-comments-body="${loop.id}">
            <div class="comments-list" data-comments-list="${loop.id}"></div>
            <div class="comment-form">
              <div class="comment-form-header">
                <div class="comment-form-title">Add context</div>
                <p class="comment-form-hint">Capture decisions, blockers, or useful history without crowding the card itself.</p>
              </div>
              <div class="comment-form-grid">
                <label class="comment-field comment-author-field">
                  <span class="comment-field-label">Author</span>
                  <input
                    type="text"
                    class="comment-author-input"
                    data-comment-author="${loop.id}"
                    placeholder="Your name"
                  >
                </label>
                <label class="comment-field comment-body-field">
                  <span class="comment-field-label">Comment</span>
                  <textarea
                    class="comment-textarea"
                    data-comment-body="${loop.id}"
                    placeholder="Add a note or context... (markdown supported)"
                  ></textarea>
                </label>
              </div>
              <div class="comment-form-actions">
                <span class="comment-form-note">Markdown supported for links, code, and emphasis.</span>
                <button class="comment-submit-btn" data-action="post-comment" data-loop-id="${loop.id}">
                  Post Comment
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;

  // Set initial values
  const titleInput = card.querySelector('[data-field="title"]');
  const tagsInput = card.querySelector('[data-field="tags_add"]');
  const nextInput = card.querySelector('[data-field="next_action"]');
  const dueDateInput = card.querySelector('[data-field="due_date"]');
  const dueTimeInput = card.querySelector('[data-field="due_time"]');
  const statusSelect = card.querySelector('[data-field="status"]');

  if (titleInput) {
    titleInput.value = title;
    titleInput.dataset.initial = title;
  }
  if (tagsInput) {
    tagsInput.value = "";
  }
  if (nextInput) {
    nextInput.value = loop.next_action || "";
    nextInput.dataset.initial = loop.next_action || "";
    autoResizeTextarea(nextInput);
  }
  if (dueDateInput) {
    dueDateInput.value = dueDateInputValueFromLoop(loop);
    dueDateInput.dataset.initialDate = loop.due_date || "";
    dueDateInput.dataset.initialTimestamp = loop.due_at_utc || "";
  }
  if (dueTimeInput) {
    dueTimeInput.value = loop.due_date ? "" : localTimeInputValueFromIso(loop.due_at_utc);
    dueTimeInput.dataset.initialTime = loop.due_date ? "" : localTimeInputValueFromIso(loop.due_at_utc);
  }
  if (statusSelect) {
    statusSelect.dataset.initial = loop.status;
  }

  const blockedInput = card.querySelector('[data-field="blocked_reason"]');
  if (blockedInput) {
    blockedInput.value = loop.blocked_reason || "";
    blockedInput.dataset.initial = loop.blocked_reason || "";
  }

  const completionInput = card.querySelector(".completion-note-input");
  if (completionInput) {
    completionInput.value = completionNoteValue;
    completionInput.dataset.initial = completionNoteValue;
    completionInput.dataset.mode = completionVisible ? "edit" : "";
  }

  if (mobileTextCollapsible) {
    setMobileCardTextExpanded(card, false);
  }
  if (compactCard) {
    setCompactCardExpanded(card, false);
  }
  setDueEditorExpanded(card, false);

  return card;
}

/**
 * Render a comment with replies
 */
export function renderComment(comment, loopId, isReply = false) {
  const bodyHtml = comment.is_deleted
    ? '<em>[deleted]</em>'
    : markdownToHtml(comment.body_md);

  const replyFormHtml = `
    <div class="reply-form" data-reply-form="${comment.id}">
      <textarea
        class="comment-textarea"
        data-reply-body="${comment.id}"
        placeholder="Write a reply..."
      ></textarea>
      <button class="comment-submit-btn" data-action="submit-reply" data-loop-id="${loopId}" data-parent-id="${comment.id}">
        Reply
      </button>
    </div>
  `;

  const repliesHtml = comment.replies?.length
    ? `<div class="comment-replies">${comment.replies.map(r => renderComment(r, loopId, true)).join("")}</div>`
    : "";

  return `
    <div class="comment ${isReply ? 'reply' : ''} ${comment.is_deleted ? 'deleted' : ''}" data-comment-id="${comment.id}">
      <div class="comment-meta">
        <span class="comment-author">${escapeHtml(comment.author)}</span>
        <span class="comment-time" title="${formatTime(comment.created_at_utc)}">${formatRelativeTime(comment.created_at_utc)}</span>
      </div>
      <div class="comment-body">${bodyHtml}</div>
      ${!comment.is_deleted ? `
        <div class="comment-actions">
          <button class="comment-action-btn" data-action="reply-comment" data-comment-id="${comment.id}">Reply</button>
          <button class="comment-action-btn" data-action="delete-comment" data-loop-id="${loopId}" data-comment-id="${comment.id}">Delete</button>
        </div>
        ${replyFormHtml}
      ` : ""}
      ${repliesHtml}
    </div>
  `;
}

/**
 * Simple markdown to HTML converter
 */
function markdownToHtml(markdown) {
  if (!markdown) return "";
  let html = escapeHtml(markdown);
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  // Code inline
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");
  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
    const safeUrl = /^(https?:|mailto:)/i.test(url) ? url : '#';
    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  });
  // Line breaks
  html = html.replace(/\n/g, "<br>");
  return html;
}

/**
 * Format relative time (e.g., "5m ago")
 */
function formatRelativeTime(isoString) {
  const date = new Date(isoString);
  const now = new Date();
  const diff = now - date;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

/**
 * Format duration in seconds to readable string
 */
export function formatDuration(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs.toString().padStart(2, '0')}s`;
}
