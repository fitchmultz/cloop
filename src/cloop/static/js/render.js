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

import { escapeHtml, formatTime, toLocalInputValue, normalizeTags } from './utils.js';

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

/**
 * Render a single loop card
 */
export function renderLoop(loop) {
  const card = document.createElement("div");
  card.className = "loop-card has-checkbox";
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
  const closed = loop.closed_at_utc ? `Closed: ${formatTime(loop.closed_at_utc)}` : "";
  const completionNoteValue = loop.completion_note || "";
  const completionVisible =
    loop.status === "completed" || Boolean(completionNoteValue.trim());

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
      <button class="tag-add" type="button" data-action="edit-tags">+ add</button>
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

  card.innerHTML = `
    ${checkboxHtml}
    <input
      class="title-input"
      type="text"
      data-field="title"
      placeholder="Untitled"
    >
    <div class="loop-meta">
      <span>Captured: ${formatTime(loop.captured_at_utc)}</span>
      <span>Updated: ${formatTime(loop.updated_at_utc)}</span>
    </div>
    ${summary ? `<div class="loop-summary">${escapeHtml(summary)}</div>` : ""}
    <div class="inline-row">
      <span class="inline-label">Next action</span>
      <textarea
        class="inline-input inline-textarea"
        rows="1"
        data-field="next_action"
        placeholder="Add next action"
      ></textarea>
    </div>
    <div class="badges">
      <select class="badge-select" data-field="status">
        ${statusSelectOptions(loop.status)}
      </select>
      <input
        class="badge-input"
        type="datetime-local"
        data-field="due_at_utc"
        placeholder="Due"
      >
      ${closed ? `<span class="badge">${closed}</span>` : ""}
      <span class="badge ${enrichmentState}">${enrichmentLabel}</span>
      ${snoozeIndicatorHtml}
    </div>
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
    <div class="timer-section">
      <button class="timer-btn ${loop.timer_running ? 'running' : ''}" data-action="timer-toggle" data-id="${loop.id}" data-running="${loop.timer_running ? 'true' : 'false'}">
        ${loop.timer_running ? '⏹ Stop' : '▶ Start'}<span class="shortcut-hint">t</span>
      </button>
      <span class="timer-display ${loop.timer_running ? 'active' : ''}" data-timer-display="${loop.id}">
        ${loop.timer_display || ''}
      </span>
      ${loop.total_tracked_minutes ? `<span class="badge">${loop.total_tracked_minutes}m tracked</span>` : ''}
      ${loop.time_minutes ? `<span class="badge pending">est: ${loop.time_minutes}m</span>` : ''}
    </div>
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
    <div class="loop-actions">
      <button class="secondary" data-action="complete" data-id="${loop.id}">
        Complete<span class="shortcut-hint">c</span>
      </button>
      <div class="snooze-wrapper">
        <button class="secondary snooze-btn" data-action="snooze" data-id="${loop.id}">
          Snooze<span class="shortcut-hint">s</span>
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
      <button class="secondary" data-action="enrich" data-id="${loop.id}">Enrich<span class="shortcut-hint">e</span></button>
      <button class="secondary" data-action="refresh" data-id="${loop.id}">Refresh<span class="shortcut-hint">r</span></button>
      <button class="secondary" data-action="save-template" data-id="${loop.id}" title="Save as template">Template</button>
    </div>
    <div class="completion-note-row ${completionVisible ? "visible" : ""}">
      <span class="inline-label">completion note</span>
      <input
        class="inline-input completion-note-input"
        type="text"
        placeholder="Add a note (optional)"
        data-action="completion-note"
      >
      <button class="completion-cancel" data-action="cancel-complete" data-id="${loop.id}" aria-label="Cancel completion note">
        ×
      </button>
    </div>
    <div class="comments-section" data-comments-section="${loop.id}">
      <div class="comments-header" data-comments-toggle="${loop.id}">
        <span class="comments-count" data-comments-count="${loop.id}">Loading comments...</span>
        <span class="comments-toggle">▼</span>
      </div>
      <div class="comments-body" data-comments-body="${loop.id}">
        <div class="comments-list" data-comments-list="${loop.id}"></div>
        <div class="comment-form">
          <input
            type="text"
            class="comment-author-input"
            data-comment-author="${loop.id}"
            placeholder="Your name"
          >
          <textarea
            class="comment-textarea"
            data-comment-body="${loop.id}"
            placeholder="Add a note or context... (markdown supported)"
          ></textarea>
          <button class="comment-submit-btn" data-action="post-comment" data-loop-id="${loop.id}">
            Post Comment
          </button>
        </div>
      </div>
    </div>
  `;

  // Set initial values
  const titleInput = card.querySelector('[data-field="title"]');
  const tagsInput = card.querySelector('[data-field="tags_add"]');
  const nextInput = card.querySelector('[data-field="next_action"]');
  const dueInput = card.querySelector('[data-field="due_at_utc"]');
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
  if (dueInput) {
    dueInput.value = toLocalInputValue(loop.due_at_utc);
    dueInput.dataset.initial = loop.due_at_utc || "";
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
