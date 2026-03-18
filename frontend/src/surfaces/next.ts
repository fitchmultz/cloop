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
import { renderLoop } from "./render";
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
let nextHandlersBound = false;

export function init(elements: NextModuleElements): void {
  nextBucketsEl = elements.nextBuckets;
  nextQueryFilterEl = elements.nextQueryFilter ?? null;
  if (nextBucketsEl && !nextHandlersBound) {
    nextBucketsEl.addEventListener("click", handleNextBucketClick);
    nextHandlersBound = true;
  }
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

function handleNextBucketClick(event: MouseEvent): void {
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
