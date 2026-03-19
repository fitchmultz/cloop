/**
 * operator-action-cards.ts - Typed operator action-card rendering helpers.
 *
 * Purpose:
 *   Render the operator workspace's canonical action-card model so planning,
 *   review, recall, and execution handoffs share one visual/output contract.
 *
 * Responsibilities:
 *   - Render typed action cards and card decks to HTML strings.
 *   - Encode shell-navigation and pin actions as data attributes.
 *   - Keep card anatomy consistent across workflow-specific shell sections.
 *
 * Scope:
 *   - Operator-workspace presentation helpers only.
 *
 * Usage:
 *   - Import renderActionCardDeck from frontend/src/shell.ts when a workspace
 *     zone needs executable cards instead of summary-only markup.
 *
 * Invariants/Assumptions:
 *   - Action-card text is supplied as plain strings and must be escaped here.
 *   - Shell actions are wired through data-open-* and data-pin-* attributes.
 *   - Cards remain transport-agnostic; they describe work and launch targets
 *     without embedding feature-local business logic.
 */

import type {
  OperatorActionCard,
  OperatorActionCardAction,
  ShellLocationContract,
} from "./contracts-ui";
import { renderTrustSurface } from "./trust-surface";
import { renderWorkflowHandoff } from "./workflow-handoff";

const KIND_LABELS = {
  mutation: "Mutation",
  decision: "Decision",
  handoff: "Handoff",
  refresh: "Refresh",
  context: "Context",
} as const satisfies Record<OperatorActionCard["kind"], string>;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function locationAttributes(prefix: "open" | "pin", location: ShellLocationContract): string {
  const attributes = [
    ["state", location.state],
    ["recall-tool", location.recallTool],
    ["review-focus", location.reviewFocus ?? ""],
    ["session-id", location.sessionId != null ? String(location.sessionId) : ""],
    ["loop-id", location.loopId != null ? String(location.loopId) : ""],
    ["view-id", location.viewId != null ? String(location.viewId) : ""],
    ["memory-id", location.memoryId != null ? String(location.memoryId) : ""],
    ["working-set-id", location.workingSetId != null ? String(location.workingSetId) : ""],
    ["query", location.query ?? ""],
  ] as const;

  return attributes
    .map(([name, value]) => `data-${prefix}-${name}="${escapeHtml(value)}"`)
    .join(" ");
}

function renderEventAttributes(attributes: Record<string, string>): string {
  return Object.entries(attributes)
    .map(([name, value]) => `${name}="${escapeHtml(value)}"`)
    .join(" ");
}

function renderActionButton(card: OperatorActionCard, action: OperatorActionCardAction): string {
  const className = action.variant === "secondary" ? ' class="secondary"' : "";
  if (action.type === "pin") {
    return `
      <button
        type="button"
        ${className}
        data-pin-label="${escapeHtml(action.pinLabel ?? card.title)}"
        data-pin-description="${escapeHtml(action.description)}"
        ${locationAttributes("pin", action.location)}
      >${escapeHtml(action.label)}</button>
    `;
  }

  if (action.type === "event") {
    return `
      <button
        type="button"
        ${className}
        ${renderEventAttributes(action.attributes)}
      >${escapeHtml(action.label)}</button>
    `;
  }

  return `
    <button
      type="button"
      ${className}
      ${locationAttributes("open", action.location)}
    >${escapeHtml(action.label)}</button>
  `;
}

function renderPreview(card: OperatorActionCard): string {
  if (!card.preview.length) {
    return "";
  }
  return `
    <section class="operator-action-section" aria-label="Preview">
      <p class="operator-action-section-title">Preview</p>
      <dl class="operator-action-preview-list">
        ${card.preview
          .map((item) => {
            return `
              <div class="operator-action-preview-item">
                <dt>${escapeHtml(item.label)}</dt>
                <dd>${escapeHtml(item.value)}</dd>
              </div>
            `;
          })
          .join("")}
      </dl>
    </section>
  `;
}

function defaultGenerationLabel(card: OperatorActionCard): string {
  if (card.kind === "handoff") {
    return "Prepared workflow handoff";
  }
  if (card.kind === "decision") {
    return "Decision support surface";
  }
  if (card.kind === "mutation") {
    return "Explicit action recommendation";
  }
  if (card.kind === "refresh") {
    return "Refresh or resume signal";
  }
  return "Context support surface";
}

function renderTrust(card: OperatorActionCard): string {
  return renderTrustSurface(
    {
      ...card.trust,
      generationLabel: card.trust.generationLabel ?? defaultGenerationLabel(card),
      generationTone: card.trust.generationTone ?? (card.kind === "handoff" || card.kind === "decision" ? "attention" : "neutral"),
      impactSummary: card.trust.impactSummary ?? card.handoff?.changeSummary ?? null,
    },
    {
      variant: "compact",
      title: "Trust surface",
      showContextLists: true,
    },
  );
}

function renderHandoff(card: OperatorActionCard): string {
  return renderWorkflowHandoff(card.handoff ?? null);
}

function renderActionCard(card: OperatorActionCard): string {
  return `
    <article class="operator-action-card operator-action-card--${escapeHtml(card.kind)} operator-action-card--${escapeHtml(card.tone)}">
      <div class="operator-action-card-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(card.eyebrow)}</p>
          <h3>${escapeHtml(card.title)}</h3>
        </div>
        <span class="operator-chip">${escapeHtml(KIND_LABELS[card.kind])}</span>
      </div>
      <p class="operator-action-summary">${escapeHtml(card.summary)}</p>
      <section class="operator-action-section" aria-label="Why this exists">
        <p class="operator-action-section-title">Why this exists</p>
        <p>${escapeHtml(card.rationale)}</p>
      </section>
      ${renderPreview(card)}
      ${renderTrust(card)}
      ${renderHandoff(card)}
      <div class="operator-card-actions operator-action-card-actions">
        ${card.actions.map((action) => renderActionButton(card, action)).join("")}
      </div>
    </article>
  `;
}

export function renderActionCardDeck(cards: readonly OperatorActionCard[], emptyStateHtml: string): string {
  if (!cards.length) {
    return emptyStateHtml;
  }
  return cards.map((card) => renderActionCard(card)).join("");
}
