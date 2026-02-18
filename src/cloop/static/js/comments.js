/**
 * comments.js - Comment handling
 *
 * Purpose:
 *   Manage comments and threaded replies on loops.
 *
 * Responsibilities:
 *   - Load comments for a loop
 *   - Post new comments
 *   - Delete comments
 *   - Render comment threads
 *   - Toggle comment section visibility
 *
 * Non-scope:
 *   - Loop rendering (see render.js)
 *   - API calls (see api.js)
 */

import * as api from './api.js';
import { escapeHtml, formatTime } from './utils.js';

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
 * Format relative time
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
 * Render a comment with replies
 */
function renderComment(comment, loopId, isReply = false) {
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
 * Load comments for a loop
 */
export async function loadComments(loopId) {
  const countEl = document.querySelector(`[data-comments-count="${loopId}"]`);
  const listEl = document.querySelector(`[data-comments-list="${loopId}"]`);

  if (!countEl || !listEl) return;

  try {
    const data = await api.fetchComments(loopId);
    const total = data.total_count;

    countEl.textContent = total === 0 ? "No comments" : `${total} comment${total !== 1 ? "s" : ""}`;

    if (total === 0) {
      listEl.innerHTML = "";
    } else {
      listEl.innerHTML = data.comments.map(c => renderComment(c, loopId)).join("");
    }
  } catch (err) {
    console.error("loadComments error:", err);
    countEl.textContent = "Comments error";
  }
}

/**
 * Post a comment
 */
export async function postComment(loopId, author, body, parentId = null) {
  if (!author.trim() || !body.trim()) return false;

  try {
    await api.postComment(loopId, author, body, parentId);
    await loadComments(loopId);
    return true;
  } catch (err) {
    console.error("postComment error:", err);
    return false;
  }
}

/**
 * Delete a comment
 */
export async function deleteComment(loopId, commentId) {
  try {
    await api.deleteComment(loopId, commentId);
    await loadComments(loopId);
    return true;
  } catch (err) {
    console.error("deleteComment error:", err);
    return false;
  }
}

/**
 * Setup comment event handlers
 */
export function setupCommentHandlers() {
  document.addEventListener("click", async (event) => {
    // Toggle comments section
    const toggle = event.target.closest("[data-comments-toggle]");
    if (toggle) {
      const loopId = toggle.dataset.commentsToggle;
      const body = document.querySelector(`[data-comments-body="${loopId}"]`);
      const header = toggle.closest(".comments-header");

      if (body && header) {
        const isVisible = body.classList.contains("visible");
        if (!isVisible) {
          await loadComments(loopId);
        }
        body.classList.toggle("visible");
        header.classList.toggle("expanded");
      }
      return;
    }

    // Post comment
    const postBtn = event.target.closest("[data-action='post-comment']");
    if (postBtn) {
      const loopId = postBtn.dataset.loopId;
      const authorInput = document.querySelector(`[data-comment-author="${loopId}"]`);
      const bodyInput = document.querySelector(`[data-comment-body="${loopId}"]`);

      if (authorInput && bodyInput) {
        const success = await postComment(loopId, authorInput.value, bodyInput.value);
        if (success) {
          bodyInput.value = "";
        }
      }
      return;
    }

    // Reply button
    const replyBtn = event.target.closest("[data-action='reply-comment']");
    if (replyBtn) {
      const commentId = replyBtn.dataset.commentId;
      const replyForm = document.querySelector(`[data-reply-form="${commentId}"]`);
      if (replyForm) {
        replyForm.classList.toggle("visible");
        if (replyForm.classList.contains("visible")) {
          replyForm.querySelector("textarea")?.focus();
        }
      }
      return;
    }

    // Submit reply
    const submitReplyBtn = event.target.closest("[data-action='submit-reply']");
    if (submitReplyBtn) {
      const loopId = submitReplyBtn.dataset.loopId;
      const parentId = parseInt(submitReplyBtn.dataset.parentId, 10);
      const bodyInput = document.querySelector(`[data-reply-body="${parentId}"]`);
      const authorInput = document.querySelector(`[data-comment-author="${loopId}"]`);

      if (bodyInput && authorInput) {
        const success = await postComment(loopId, authorInput.value, bodyInput.value, parentId);
        if (success) {
          bodyInput.value = "";
          const replyForm = document.querySelector(`[data-reply-form="${parentId}"]`);
          if (replyForm) replyForm.classList.remove("visible");
        }
      }
      return;
    }

    // Delete comment
    const deleteBtn = event.target.closest("[data-action='delete-comment']");
    if (deleteBtn) {
      const loopId = deleteBtn.dataset.loopId;
      const commentId = deleteBtn.dataset.commentId;

      if (confirm("Delete this comment?")) {
        await deleteComment(loopId, commentId);
      }
      return;
    }
  });
}
