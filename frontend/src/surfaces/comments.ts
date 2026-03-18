/**
 * comments.ts - Loop comment handling.
 *
 * Purpose:
 *   Manage threaded loop comments inside the shared work-surface runtime.
 *
 * Responsibilities:
 *   - Load and render comments for a loop.
 *   - Post replies and delete existing comments.
 *   - Toggle comment thread visibility on loop cards.
 *
 * Scope:
 *   - Surface comment UI only.
 *
 * Usage:
 *   - Imported by bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - Loop cards expose stable data-comments-* hooks.
 *   - The backend comment API returns a threaded LoopCommentListResponse.
 */

import * as api from "./api";
import * as modals from "./modals";
import type { CommentNode } from "./contracts";
import { closestFromEventTarget, escapeHtml, formatTime } from "./utils";

function markdownToHtml(markdown: string | null | undefined): string {
  if (!markdown) {
    return "";
  }
  let html = escapeHtml(markdown);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, text: string, url: string) => {
    const safeUrl = /^(https?:|mailto:)/i.test(url) ? url : "#";
    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  });
  html = html.replace(/\n/g, "<br>");
  return html;
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = Date.now();
  const diff = now - date.getTime();
  const minutes = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);

  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  if (hours < 24) {
    return `${hours}h ago`;
  }
  if (days < 7) {
    return `${days}d ago`;
  }
  return date.toLocaleDateString();
}

function renderComment(comment: CommentNode, loopId: number | string, isReply = false): string {
  const bodyHtml = comment.is_deleted ? "<em>[deleted]</em>" : markdownToHtml(comment.body_md);
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

  const repliesHtml = Array.isArray(comment.replies) && comment.replies.length > 0
    ? `<div class="comment-replies">${comment.replies.map((reply) => renderComment(reply, loopId, true)).join("")}</div>`
    : "";

  return `
    <div class="comment ${isReply ? "reply" : ""} ${comment.is_deleted ? "deleted" : ""}" data-comment-id="${comment.id}">
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

export async function loadComments(loopId: number | string): Promise<void> {
  const countEl = document.querySelector(`[data-comments-count="${loopId}"]`);
  const listEl = document.querySelector(`[data-comments-list="${loopId}"]`);

  if (!(countEl instanceof HTMLElement) || !(listEl instanceof HTMLElement)) {
    return;
  }

  try {
    countEl.textContent = "Loading comments...";
    const data = await api.fetchComments(loopId);
    const total = data.total_count;

    countEl.textContent = total === 0 ? "No comments" : `${total} comment${total !== 1 ? "s" : ""}`;
    listEl.innerHTML = total === 0 ? "" : data.comments.map((comment: CommentNode) => renderComment(comment, loopId)).join("");
  } catch {
    countEl.textContent = "Comments error";
  }
}

export async function postComment(
  loopId: number | string,
  author: string,
  body: string,
  parentId: number | null = null,
): Promise<boolean> {
  if (!author.trim() || !body.trim()) {
    return false;
  }

  try {
    await api.postComment(loopId, author, body, parentId ?? undefined);
    await loadComments(loopId);
    return true;
  } catch {
    return false;
  }
}

export async function deleteComment(loopId: number | string, commentId: number | string): Promise<boolean> {
  try {
    await api.deleteComment(loopId, commentId);
    await loadComments(loopId);
    return true;
  } catch {
    return false;
  }
}

export function setupCommentHandlers(): void {
  document.addEventListener("click", async (event: MouseEvent) => {
    const toggle = closestFromEventTarget<HTMLElement>(event.target, "[data-comments-toggle]");
    if (toggle) {
      const loopId = toggle.dataset["commentsToggle"];
      const body = loopId ? document.querySelector(`[data-comments-body="${loopId}"]`) : null;
      const header = toggle.closest(".comments-header");

      if (body instanceof HTMLElement && header instanceof HTMLElement) {
        const isVisible = body.classList.contains("visible");
        if (!isVisible && loopId) {
          await loadComments(loopId);
        }
        body.classList.toggle("visible");
        header.classList.toggle("expanded");
      }
      return;
    }

    const postButton = closestFromEventTarget<HTMLElement>(event.target, "[data-action='post-comment']");
    if (postButton) {
      const loopId = postButton.dataset["loopId"];
      const authorInput = loopId ? document.querySelector(`[data-comment-author="${loopId}"]`) : null;
      const bodyInput = loopId ? document.querySelector(`[data-comment-body="${loopId}"]`) : null;

      if (loopId && authorInput instanceof HTMLInputElement && bodyInput instanceof HTMLTextAreaElement) {
        const success = await postComment(loopId, authorInput.value, bodyInput.value);
        if (success) {
          bodyInput.value = "";
        }
      }
      return;
    }

    const replyButton = closestFromEventTarget<HTMLElement>(event.target, "[data-action='reply-comment']");
    if (replyButton) {
      const commentId = replyButton.dataset["commentId"];
      const replyForm = commentId ? document.querySelector(`[data-reply-form="${commentId}"]`) : null;
      if (replyForm instanceof HTMLElement) {
        replyForm.classList.toggle("visible");
        if (replyForm.classList.contains("visible")) {
          const textarea = replyForm.querySelector("textarea");
          if (textarea instanceof HTMLTextAreaElement) {
            textarea.focus();
          }
        }
      }
      return;
    }

    const submitReplyButton = closestFromEventTarget<HTMLElement>(event.target, "[data-action='submit-reply']");
    if (submitReplyButton) {
      const loopId = submitReplyButton.dataset["loopId"];
      const parentId = Number.parseInt(submitReplyButton.dataset["parentId"] ?? "", 10);
      const bodyInput = Number.isInteger(parentId) ? document.querySelector(`[data-reply-body="${parentId}"]`) : null;
      const authorInput = loopId ? document.querySelector(`[data-comment-author="${loopId}"]`) : null;

      if (loopId && bodyInput instanceof HTMLTextAreaElement && authorInput instanceof HTMLInputElement) {
        const success = await postComment(loopId, authorInput.value, bodyInput.value, parentId);
        if (success) {
          bodyInput.value = "";
          const replyForm = document.querySelector(`[data-reply-form="${parentId}"]`);
          if (replyForm instanceof HTMLElement) {
            replyForm.classList.remove("visible");
          }
        }
      }
      return;
    }

    const deleteButton = closestFromEventTarget<HTMLElement>(event.target, "[data-action='delete-comment']");
    if (deleteButton) {
      const loopId = deleteButton.dataset["loopId"];
      const commentId = deleteButton.dataset["commentId"];
      if (!loopId || !commentId) {
        return;
      }

      const confirmed = await modals.confirmDialog({
        eyebrow: "Comments",
        title: "Delete Comment",
        description: "Remove this comment from the thread? Replies will remain visible if they still have content.",
        confirmLabel: "Delete comment",
        confirmVariant: "danger",
      });

      if (confirmed) {
        await deleteComment(loopId, commentId);
      }
    }
  });
}
