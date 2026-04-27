/**
 * next.ts - Do-surface bucket and query rendering.
 *
 * Purpose:
 *   Load the focused execution surface for next-work buckets and optional
 *   query-scoped result sets.
 *
 * Responsibilities:
 *   - Load and render next-action buckets.
 *   - Render query-scoped loop results inside the do surface.
 *   - Keep the do-surface search input synchronized with the active view.
 *
 * Scope:
 *   - Browser-only do-surface rendering and event wiring.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/bootstrap.ts.
 *
 * Invariants/Assumptions:
 *   - The do surface owns #next-buckets and optionally #do-query-filter.
 *   - Loop cards still render through render.ts so shared handlers keep working.
 */

import * as api from "./api";
import type { NextLoopsResponse, SurfaceLoop } from "./contracts";
import { formatDuration, renderLoop } from "./render";
import { escapeHtml, closestFromEventTarget, messageFromError } from "./utils";

interface NextModuleElements {
  nextBuckets: HTMLElement;
  nextQueryFilter?: HTMLInputElement | null;
}

interface NextLoadOptions {
  query?: string;
}

interface NextBucket {
  key: string;
  title: string;
  items: SurfaceLoop[];
}

let nextBucketsEl: HTMLElement | null = null;
let nextQueryFilterEl: HTMLInputElement | null = null;
let nextHandlersBoundEl: HTMLElement | null = null;
let toggleTimerHandler: ((loopId: number | string) => void | Promise<void>) | null = null;

export function init(elements: NextModuleElements): void {
  nextBucketsEl = elements.nextBuckets;
  nextQueryFilterEl = elements.nextQueryFilter ?? null;
  ensureNextBucketHandlersBound();
}

export function setTimerToggleHandler(handler: (loopId: number | string) => void | Promise<void>): void {
  toggleTimerHandler = handler;
}

function ensureNextBucketHandlersBound(): void {
  if (!nextBucketsEl || nextHandlersBoundEl === nextBucketsEl) {
    return;
  }
  nextBucketsEl.addEventListener("click", handleNextBucketClick);
  nextHandlersBoundEl = nextBucketsEl;
}

export async function loadNext(options: NextLoadOptions = {}): Promise<void> {
  if (!nextBucketsEl) {
    return;
  }

  const activeQuery = typeof options.query === "string"
    ? options.query.trim()
    : nextQueryFilterEl?.value.trim() || "";

  if (nextQueryFilterEl && nextQueryFilterEl.value !== activeQuery) {
    nextQueryFilterEl.value = activeQuery;
  }

  try {
    if (activeQuery) {
      const items = await api.searchLoops(activeQuery);
      renderQueryResults(items, activeQuery);
      return;
    }

    const data = await api.fetchNextLoops();
    renderNextBuckets(normalizeBuckets(data));
  } catch (error: unknown) {
    nextBucketsEl.innerHTML = `<p class="error">Failed to load next actions: ${escapeHtml(messageFromError(error, "Failed to load next actions."))}</p>`;
  }
}

export async function loadFocusedLoop(loopId: number): Promise<void> {
  if (!nextBucketsEl) {
    return;
  }

  if (nextQueryFilterEl && nextQueryFilterEl.value) {
    nextQueryFilterEl.value = "";
  }

  try {
    const loop = await api.fetchLoop(loopId);
    if (!loop) {
      nextBucketsEl.innerHTML = `
        <section class="next-bucket bucket-query-results">
          <div class="next-bucket-header">
            <div>
              <h3 class="next-bucket-title">Focused loop</h3>
              <p class="next-bucket-description">Loop #${loopId} is no longer available.</p>
            </div>
            <span class="next-bucket-count">0</span>
          </div>
        </section>
      `;
      return;
    }
    await applyFocusedLoopTimerStatus(loop);
    renderFocusedLoop(loop);
  } catch (error: unknown) {
    nextBucketsEl.innerHTML = `<p class="error">Failed to load focused loop: ${escapeHtml(messageFromError(error, `Failed to load loop #${loopId}.`))}</p>`;
  }
}

async function applyFocusedLoopTimerStatus(loop: SurfaceLoop): Promise<void> {
  const timerStatus = await api.fetchTimerStatus(loop.id);
  if (!timerStatus) {
    return;
  }

  if (timerStatus.has_active_session && timerStatus.active_session) {
    const startedAt = new Date(timerStatus.active_session.started_at_utc).getTime();
    const elapsed = Number.isFinite(startedAt)
      ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
      : timerStatus.total_tracked_seconds;
    loop.timer_running = true;
    loop.timer_display = formatDuration(elapsed);
    loop.total_tracked_minutes = timerStatus.total_tracked_minutes;
    return;
  }
  loop.timer_running = false;
  loop.timer_display = "";
  if (timerStatus) {
    loop.total_tracked_minutes = timerStatus.total_tracked_minutes;
  }
}

function normalizeBuckets(data: NextLoopsResponse): NextBucket[] {
  const bucketTitles: Record<keyof NextLoopsResponse, string> = {
    due_soon: "Due soon",
    quick_wins: "Quick wins",
    high_leverage: "High leverage",
    standard: "Standard",
  };

  return Object.entries(bucketTitles)
    .map(([key, title]) => ({
      key,
      title,
      items: Array.isArray(data[key as keyof NextLoopsResponse])
        ? (data[key as keyof NextLoopsResponse] as SurfaceLoop[])
        : [],
    }))
    .filter((bucket) => bucket.items.length > 0);
}

function renderNextBuckets(buckets: NextBucket[]): void {
  if (!nextBucketsEl) {
    return;
  }
  ensureNextBucketHandlersBound();

  if (buckets.length === 0) {
    nextBucketsEl.innerHTML = '<p class="empty">No next actions found. Capture some loops first!</p>';
    return;
  }

  nextBucketsEl.innerHTML = "";

  for (const bucket of buckets) {
    const section = document.createElement("section");
    section.className = `next-bucket bucket-${bucket.key}`;
    section.innerHTML = `
      <div class="next-bucket-header">
        <div>
          <h3 class="next-bucket-title">${escapeHtml(bucket.title)}</h3>
          <p class="next-bucket-description">${escapeHtml(getBucketDescription(bucket.key))}</p>
        </div>
        <span class="next-bucket-count">${bucket.items.length}</span>
      </div>
      <div class="next-bucket-list"></div>
    `;

    const list = section.querySelector(".next-bucket-list");
    if (list instanceof HTMLElement) {
      bucket.items.forEach((item) => {
        list.appendChild(renderLoop(item, { surface: "next" }));
      });
    }

    nextBucketsEl.appendChild(section);
  }
}

function renderQueryResults(items: SurfaceLoop[], query: string): void {
  if (!nextBucketsEl) {
    return;
  }
  ensureNextBucketHandlersBound();

  if (items.length === 0) {
    nextBucketsEl.innerHTML = `
      <section class="next-bucket bucket-query-results">
        <div class="next-bucket-header">
          <div>
            <h3 class="next-bucket-title">Query results</h3>
            <p class="next-bucket-description">No loops matched “${escapeHtml(query)}”.</p>
          </div>
          <span class="next-bucket-count">0</span>
        </div>
      </section>
    `;
    return;
  }

  nextBucketsEl.innerHTML = `
    <section class="next-bucket bucket-query-results">
      <div class="next-bucket-header">
        <div>
          <h3 class="next-bucket-title">Query results</h3>
          <p class="next-bucket-description">Focused execution results for “${escapeHtml(query)}”.</p>
        </div>
        <span class="next-bucket-count">${items.length}</span>
      </div>
      <div class="next-bucket-list"></div>
    </section>
  `;

  const list = nextBucketsEl.querySelector(".next-bucket-list");
  if (!(list instanceof HTMLElement)) {
    return;
  }

  items.forEach((item) => {
    list.appendChild(renderLoop(item, { surface: "next" }));
  });
}

function renderFocusedLoop(loop: SurfaceLoop): void {
  if (!nextBucketsEl) {
    return;
  }
  ensureNextBucketHandlersBound();

  nextBucketsEl.innerHTML = `
    <section class="next-bucket bucket-query-results">
      <div class="next-bucket-header">
        <div>
          <h3 class="next-bucket-title">Focused loop</h3>
          <p class="next-bucket-description">Direct handoff from review or operator context.</p>
        </div>
        <span class="next-bucket-count">1</span>
      </div>
      <div class="next-bucket-list"></div>
    </section>
  `;

  const list = nextBucketsEl.querySelector(".next-bucket-list");
  if (!(list instanceof HTMLElement)) {
    return;
  }
  list.appendChild(renderLoop(loop, { surface: "next" }));
}

function handleNextBucketClick(event: MouseEvent): void {
  const timerButton = closestFromEventTarget<HTMLElement>(event.target, "[data-action='timer-toggle']");
  if (timerButton) {
    const loopId = timerButton.dataset["id"];
    if (loopId && toggleTimerHandler) {
      void toggleTimerHandler(loopId);
    }
    return;
  }

  const reviewBtn = closestFromEventTarget<HTMLElement>(event.target, "[data-action='jump-to-inbox']");
  if (!reviewBtn) {
    return;
  }

  const loopId = reviewBtn.dataset["loopId"];
  if (window.location.hash !== "#capture") {
    window.location.hash = "#capture";
  }

  if (!loopId) {
    return;
  }

  requestAnimationFrame(() => {
    const card = document.querySelector(`.loop-card[data-loop-id="${loopId}"]`);
    if (card instanceof HTMLElement) {
      card.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });
}

function getBucketDescription(key: string): string {
  switch (key) {
    case "due_soon":
      return "Time-sensitive work that needs attention quickly.";
    case "quick_wins":
      return "Low-friction tasks you can finish fast.";
    case "high_leverage":
      return "Important work with outsized payoff.";
    case "standard":
      return "Solid actionable work to pick up next.";
    default:
      return "Actionable loops ready to move.";
  }
}
