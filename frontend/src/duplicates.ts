/**
 * duplicates.ts - Shared duplicate-badge and merge-modal runtime.
 *
 * Purpose:
 *   Own duplicate detection badges and the merge confirmation modal in
 *   TypeScript so review workspace flows no longer depend on legacy JS.
 *
 * Responsibilities:
 *   - Fetch duplicate candidates for visible loop cards.
 *   - Open, render, confirm, and close the merge modal.
 *   - Notify the shell, review workspace, and residual legacy surfaces when a
 *     merge changes loop state.
 *
 * Scope:
 *   - Browser-only duplicate review helpers and merge-modal orchestration.
 *
 * Usage:
 *   - Imported by frontend/src/review-workspace.ts.
 *   - Re-exported from frontend/src/legacy/duplicates.js for untouched legacy
 *     duplicate-badge surfaces.
 *
 * Invariants/Assumptions:
 *   - frontend/index.html preserves the merge-modal DOM ids.
 *   - The merge preview API remains the canonical source of merge impact data.
 *   - Merge execution should refresh both the review workspace and any residual
 *     legacy list surfaces that may still be visible.
 */

import { alertDialog, MERGE_MODAL_CLOSE_REQUEST_EVENT } from "./modals";

interface DuplicateCandidateResponse {
  loop_id: number;
  score: number;
  title: string | null;
  raw_text_preview: string;
  status: string;
  captured_at_utc: string;
}

interface DuplicatesListResponse {
  loop_id: number;
  candidates: DuplicateCandidateResponse[];
}

interface MergePreviewResponse {
  surviving_loop_id: number;
  duplicate_loop_id: number;
  merged_title: string | null;
  merged_summary: string | null;
  merged_tags: string[];
  merged_next_action: string | null;
  field_conflicts: Record<string, Record<string, unknown>>;
}

interface MergeResultResponse {
  surviving_loop_id: number;
  closed_loop_id: number;
  merged_tags: string[];
  fields_updated: string[];
}

export const LEGACY_RUNTIME_REFRESH_EVENT = "cloop:legacy-runtime-refresh-requested";
const REVIEW_WORKSPACE_REFRESH_EVENT = "cloop:review-workspace-refresh-requested";
const WORKSPACE_REFRESH_EVENT = "cloop:workspace-refresh-requested";

let currentDuplicateLoopId: number | null = null;
let currentSurvivingLoopId: number | null = null;
let currentMergePreview: MergePreviewResponse | null = null;
let handlersInitialized = false;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function mergeModal(): HTMLElement | null {
  return typeof document === "undefined" ? null : document.getElementById("mergeModal");
}

function mergeModalPanel(): HTMLElement | null {
  return mergeModal()?.querySelector<HTMLElement>(".merge-modal") ?? null;
}

async function safeJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    const detail = (payload as Record<string, unknown>)["detail"];
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const message = (detail as Record<string, unknown>)["message"];
      if (typeof message === "string" && message.trim()) {
        return message;
      }
    }
  }
  return fallback;
}

async function fetchDuplicateCandidates(loopId: number): Promise<DuplicatesListResponse | null> {
  const response = await fetch(`/loops/${loopId}/duplicates`);
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as DuplicatesListResponse;
}

async function fetchMergePreview(
  duplicateLoopId: number,
  survivingLoopId: number,
): Promise<MergePreviewResponse> {
  const response = await fetch(`/loops/${duplicateLoopId}/merge-preview/${survivingLoopId}`);
  if (!response.ok) {
    throw new Error(errorMessage(await safeJson(response), "Failed to load merge preview"));
  }
  return (await response.json()) as MergePreviewResponse;
}

async function mergeLoops(
  duplicateLoopId: number,
  survivingLoopId: number,
): Promise<MergeResultResponse> {
  const response = await fetch(`/loops/${duplicateLoopId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_loop_id: survivingLoopId,
      field_overrides: {},
    }),
  });
  if (!response.ok) {
    throw new Error(errorMessage(await safeJson(response), "Merge failed"));
  }
  return (await response.json()) as MergeResultResponse;
}

function fieldHasConflict(preview: MergePreviewResponse, field: string): boolean {
  return Boolean(preview.field_conflicts?.[field]);
}

function renderMergeModal(preview: MergePreviewResponse): void {
  const survivingContent = document.getElementById("mergeSurvivingContent");
  const duplicateContent = document.getElementById("mergeDuplicateContent");
  if (!survivingContent || !duplicateContent) {
    return;
  }

  survivingContent.innerHTML = `
    <div class="merge-field">
      <div class="merge-field-label">Title</div>
      <div class="merge-field-value ${fieldHasConflict(preview, "title") ? "conflict" : ""}">${preview.merged_title ? escapeHtml(preview.merged_title) : "<em>empty</em>"}</div>
    </div>
    <div class="merge-field">
      <div class="merge-field-label">Summary</div>
      <div class="merge-field-value ${fieldHasConflict(preview, "summary") ? "conflict" : ""}">${preview.merged_summary ? escapeHtml(preview.merged_summary) : "<em>empty</em>"}</div>
    </div>
    <div class="merge-field">
      <div class="merge-field-label">Next Action</div>
      <div class="merge-field-value ${fieldHasConflict(preview, "next_action") ? "conflict" : ""}">${preview.merged_next_action ? escapeHtml(preview.merged_next_action) : "<em>empty</em>"}</div>
    </div>
    <div class="merge-field">
      <div class="merge-field-label">Tags</div>
      <div class="merge-field-value">${preview.merged_tags.length ? escapeHtml(preview.merged_tags.join(", ")) : "<em>none</em>"}</div>
    </div>
  `;

  duplicateContent.innerHTML = `
    <div class="merge-field">
      <div class="merge-field-label">Loop ID</div>
      <div class="merge-field-value">#${preview.duplicate_loop_id}</div>
    </div>
    <p style="color: var(--muted); font-size: 13px; margin-top: 12px;">
      This loop will be closed with status “dropped” after merge.
    </p>
  `;
}

function requestRuntimeRefresh(): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_REFRESH_EVENT));
  window.dispatchEvent(new CustomEvent(REVIEW_WORKSPACE_REFRESH_EVENT));
  window.dispatchEvent(
    new CustomEvent(LEGACY_RUNTIME_REFRESH_EVENT, {
      detail: {
        inbox: true,
        next: true,
        relationshipReview: true,
      },
    }),
  );
}

export async function checkAndShowDuplicateBadges(): Promise<void> {
  if (typeof document === "undefined") {
    return;
  }
  const cards = document.querySelectorAll<HTMLElement>(".loop-card[data-loop-id]");
  for (const card of cards) {
    const loopIdRaw = card.dataset["loopId"];
    const loopId = loopIdRaw ? Number.parseInt(loopIdRaw, 10) : NaN;
    if (!Number.isInteger(loopId)) {
      continue;
    }
    try {
      const data = await fetchDuplicateCandidates(loopId);
      const candidate = data?.candidates?.[0] ?? null;
      if (candidate) {
        showDuplicateBadge(card, loopId, candidate.loop_id);
      }
    } catch {
      // Ignore badge lookup failures so the surrounding loop UI remains usable.
    }
  }
}

function showDuplicateBadge(card: HTMLElement, loopId: number, survivingLoopId: number): void {
  const badges = card.querySelector<HTMLElement>(".badges");
  if (!badges || badges.querySelector(".duplicate-badge")) {
    return;
  }

  const badge = document.createElement("span");
  badge.className = "duplicate-badge";
  badge.textContent = "Possible duplicate";
  badge.tabIndex = 0;
  badge.setAttribute("role", "button");
  const open = (event: Event) => {
    event.stopPropagation();
    void openMergeModal(loopId, survivingLoopId);
  };
  badge.addEventListener("click", open);
  badge.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open(event);
    }
  });
  badges.appendChild(badge);
}

export async function openMergeModal(duplicateLoopId: number, survivingLoopId: number): Promise<void> {
  currentDuplicateLoopId = duplicateLoopId;
  currentSurvivingLoopId = survivingLoopId;

  try {
    currentMergePreview = await fetchMergePreview(duplicateLoopId, survivingLoopId);
    renderMergeModal(currentMergePreview);
    const modal = mergeModal();
    if (!modal) {
      return;
    }
    modal.classList.add("visible");
    mergeModalPanel()?.focus();
  } catch (error) {
    await alertDialog({
      title: "Could not load merge preview",
      description: error instanceof Error ? error.message : "Failed to load merge preview.",
      eyebrow: "Duplicates",
    });
  }
}

export function closeMergeModal(): void {
  mergeModal()?.classList.remove("visible");
  currentDuplicateLoopId = null;
  currentSurvivingLoopId = null;
  currentMergePreview = null;
}

export async function confirmMerge(): Promise<void> {
  if (currentDuplicateLoopId == null || currentSurvivingLoopId == null) {
    return;
  }

  try {
    await mergeLoops(currentDuplicateLoopId, currentSurvivingLoopId);
    closeMergeModal();
    requestRuntimeRefresh();
  } catch (error) {
    await alertDialog({
      title: "Merge failed",
      description: error instanceof Error ? error.message : "Merge failed.",
      eyebrow: "Duplicates",
    });
  }
}

export function setupMergeHandlers(): void {
  if (handlersInitialized || typeof document === "undefined") {
    return;
  }
  handlersInitialized = true;

  document.addEventListener(MERGE_MODAL_CLOSE_REQUEST_EVENT, () => {
    closeMergeModal();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mergeModal()?.classList.contains("visible")) {
      event.preventDefault();
      closeMergeModal();
    }
  });

  mergeModal()?.addEventListener("click", (event) => {
    if (event.target === mergeModal()) {
      closeMergeModal();
    }
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const action = target.closest<HTMLElement>("[data-merge-modal-action]")?.dataset["mergeModalAction"];
    if (action === "close") {
      event.preventDefault();
      closeMergeModal();
      return;
    }
    if (action === "confirm") {
      event.preventDefault();
      void confirmMerge();
    }
  });
}
