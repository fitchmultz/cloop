/**
 * trust-surface.ts - Shared trust-surface presentation helpers.
 *
 * Purpose:
 *   Render one consistent trust and impact layer anywhere the operator needs to
 *   judge provenance, assumptions, freshness, reversibility, and change scope.
 *
 * Responsibilities:
 *   - Render reusable trust-surface HTML for cards, detail panes, and panels.
 *   - Keep trust metadata phrasing and layout consistent across frontend flows.
 *   - Support compact and full-density variants without forking trust markup.
 *
 * Scope:
 *   - Frontend-only presentation helpers for trust metadata.
 *
 * Usage:
 *   - Import renderTrustSurface from operator action cards, the command palette,
 *     or review workspaces when meaningful recommendations or mutations need
 *     consistent trust framing.
 *
 * Invariants/Assumptions:
 *   - All incoming text is plain strings and must be escaped here.
 *   - Trust rendering is presentation-only and does not own business logic.
 *   - Compact variants may hide source/assumption lists, but summary signals
 *     stay visible at the point of action.
 */

import type { TrustSurfaceMetadata, TrustTone } from "./contracts-ui";

export interface RenderTrustSurfaceOptions {
  variant: "compact" | "detail" | "panel";
  title?: string | null;
  showContextLists?: boolean;
  showEmptyStates?: boolean;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toneClass(tone: TrustTone | null | undefined): string {
  return `trust-surface-tone--${tone ?? "neutral"}`;
}

function renderSignal(
  label: string,
  value: string | null | undefined,
  tone: TrustTone | null | undefined,
): string {
  if (!value) {
    return "";
  }
  return `
    <li class="trust-surface-signal ${toneClass(tone)}">
      <span class="trust-surface-signal-label">${escapeHtml(label)}</span>
      <span class="trust-surface-signal-value">${escapeHtml(value)}</span>
    </li>
  `;
}

function renderListSection(
  title: string,
  items: readonly string[],
  emptyLabel: string,
  options: Pick<RenderTrustSurfaceOptions, "showEmptyStates">,
): string {
  if (!items.length && !options.showEmptyStates) {
    return "";
  }

  return `
    <section class="trust-surface-section trust-surface-section--list" aria-label="${escapeHtml(title)}">
      <p class="trust-surface-section-title">${escapeHtml(title)}</p>
      ${items.length
        ? `
          <ul class="trust-surface-list">
            ${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
          </ul>
        `
        : `<p class="trust-surface-empty">${escapeHtml(emptyLabel)}</p>`}
    </section>
  `;
}

export function renderTrustSurface(
  metadata: TrustSurfaceMetadata,
  options: RenderTrustSurfaceOptions,
): string {
  const signals = [
    renderSignal("Mode", metadata.generationLabel ?? null, metadata.generationTone),
    renderSignal("Confidence", metadata.confidenceLabel ?? null, metadata.confidenceTone),
    renderSignal("Freshness", metadata.freshnessLabel ?? null, metadata.freshnessTone),
    renderSignal("Rollback", metadata.rollbackLabel ?? null, metadata.rollbackTone),
  ].filter(Boolean);

  const showContextLists = options.showContextLists ?? true;
  const showEmptyStates = options.showEmptyStates ?? options.variant !== "compact";

  const impactSummary = metadata.impactSummary?.trim() || null;

  if (!signals.length && !impactSummary && !showContextLists) {
    return "";
  }

  return `
    <section class="trust-surface trust-surface--${options.variant}" aria-label="${escapeHtml(options.title ?? "Trust surface")}">
      ${options.title ? `<p class="trust-surface-title">${escapeHtml(options.title)}</p>` : ""}
      ${signals.length
        ? `
          <ul class="trust-surface-signal-list">
            ${signals.join("")}
          </ul>
        `
        : ""}
      ${impactSummary
        ? `
          <section class="trust-surface-section trust-surface-section--impact ${toneClass(metadata.impactTone)}" aria-label="Impact summary">
            <p class="trust-surface-section-title">Impact</p>
            <p class="trust-surface-impact-copy">${escapeHtml(impactSummary)}</p>
          </section>
        `
        : ""}
      ${showContextLists
        ? `
          <div class="trust-surface-grid">
            ${renderListSection(
              "Context used",
              metadata.contextSources,
              "No explicit context sources were recorded.",
              { showEmptyStates },
            )}
            ${renderListSection(
              "Assumptions",
              metadata.assumptions,
              "No explicit assumptions were recorded.",
              { showEmptyStates },
            )}
          </div>
        `
        : ""}
    </section>
  `;
}
