/**
 * operator-action-cards.ts - Typed operator action-card rendering helpers.
 *
 * Purpose:
 *   Render the operator workspace's canonical action-card model so planning,
 *   review, recall, and execution handoffs share one visual/output contract.
 *
 * Responsibilities:
 *   - Render typed action cards and card decks to HTML strings.
 *   - Encode shell-navigation, pin, follow-through, and recovery actions as data attributes.
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
 *   - Shell actions are wired through data-open-*, data-pin-*, and data-card-action attributes.
 *   - Cards remain transport-agnostic; they describe work and launch targets
 *     without embedding feature-local business logic.
 */

import type {
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardRerunAction,
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
  receipt: "Receipt",
} as const satisfies Record<OperatorActionCard["kind"], string>;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function locationAttributes(prefix: "open" | "pin" | "stage" | "edit" | "defer" | "undo-success" | "recover", location: ShellLocationContract): string {
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

function renderRerunContract(action: OperatorActionCardRerunAction): string {
  return `
    <section class="operator-action-section" aria-label="${escapeHtml(action.contract.mode === "refresh" ? "Refresh contract" : "Rerun contract")}">
      <p class="operator-action-section-title">${escapeHtml(action.contract.mode === "refresh" ? "Refresh contract" : "Rerun contract")}</p>
      <p><strong>Provenance:</strong> ${escapeHtml(action.contract.provenanceLabel)}</p>
      ${action.contract.freshnessLabel ? `<p><strong>Freshness:</strong> ${escapeHtml(action.contract.freshnessLabel)}</p>` : ""}
      <p><strong>Strategy:</strong> ${escapeHtml(action.contract.strategySummary)}</p>
      <p><strong>Strict:</strong> ${escapeHtml(action.contract.strictInvariants.join(" · "))}</p>
      <p><strong>May vary:</strong> ${escapeHtml(action.contract.mayVary.join(" · "))}</p>
      <p><strong>After run:</strong> ${escapeHtml(action.contract.postRun.summary)}</p>
    </section>
  `;
}

function renderActionButton(card: OperatorActionCard, action: OperatorActionCardAction): string {
  const className = action.variant === "secondary" ? ' class="secondary"' : "";
  const disabledAttributes = action.disabledReason?.trim()
    ? ` disabled aria-disabled="true" title="${escapeHtml(action.disabledReason)}"`
    : "";

  switch (action.type) {
    case "pin":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-pin-label="${escapeHtml(action.pinLabel ?? card.title)}"
          data-pin-description="${escapeHtml(action.description)}"
          ${locationAttributes("pin", action.location)}
        >${escapeHtml(action.label)}</button>
      `;
    case "event":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          ${renderEventAttributes(action.attributes)}
        >${escapeHtml(action.label)}</button>
      `;
    case "stage":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="stage"
          data-stage-label="${escapeHtml(action.stageLabel)}"
          data-stage-description="${escapeHtml(action.stageDescription?.trim() || action.description)}"
          data-stage-open-after="${action.openAfterStage === false ? "false" : "true"}"
          ${locationAttributes("stage", action.location)}
        >${escapeHtml(action.label)}</button>
      `;
    case "edit":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="edit"
          data-edit-query="${escapeHtml(action.query)}"
          ${locationAttributes("edit", action.location)}
        >${escapeHtml(action.label)}</button>
      `;
    case "defer":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="defer"
          data-defer-label="${escapeHtml(action.deferLabel)}"
          data-defer-description="${escapeHtml(action.deferDescription?.trim() || action.description)}"
          ${locationAttributes("defer", action.location)}
        >${escapeHtml(action.label)}</button>
      `;
    case "undo":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="undo"
          data-undo-kind="${escapeHtml(action.undo.kind)}"
          data-undo-handle="${escapeHtml(action.undo.kind === "relationship_decision" ? JSON.stringify(action.undo) : "")}"
          data-undo-loop-id="${escapeHtml(action.undo.kind === "loop_event" ? String(action.undo.loopId) : "")}"
          data-undo-expected-event-id="${escapeHtml(action.undo.kind === "loop_event" || action.undo.kind === "working_set_event" ? String(action.undo.expectedEventId) : "")}"
          data-undo-event-type="${escapeHtml(action.undo.kind === "loop_event" || action.undo.kind === "working_set_event" ? action.undo.eventType ?? "" : "")}"
          data-undo-claim-token="${escapeHtml(action.undo.kind === "loop_event" ? action.undo.claimToken ?? "" : "")}"
          data-undo-working-set-id="${escapeHtml(action.undo.kind === "working_set_event" && action.undo.workingSetId != null ? String(action.undo.workingSetId) : "")}"
          data-undo-working-set-name="${escapeHtml(action.undo.kind === "working_set_event" ? action.undo.workingSetName ?? "" : "")}"
          data-undo-session-id="${escapeHtml(action.undo.kind === "planning_run" ? String(action.undo.sessionId) : "")}"
          data-undo-run-id="${escapeHtml(action.undo.kind === "planning_run" ? String(action.undo.runId) : "")}"
          data-undo-checkpoint-index="${escapeHtml(action.undo.kind === "planning_run" ? String(action.undo.checkpointIndex) : "")}"
          data-undo-checkpoint-title="${escapeHtml(action.undo.kind === "planning_run" ? action.undo.checkpointTitle : "")}"
          data-undo-action-count="${escapeHtml(action.undo.kind === "planning_run" ? String(action.undo.actionCount) : "")}"
          data-undo-best-effort="${escapeHtml(action.undo.kind === "planning_run" && action.undo.bestEffort ? "true" : "false")}" 
          data-undo-confirm-title="${escapeHtml(action.confirmTitle?.trim() || "")}" 
          data-undo-confirm-description="${escapeHtml(action.confirmDescription?.trim() || "")}"
          ${action.successLocation ? locationAttributes("undo-success", action.successLocation) : ""}
        >${escapeHtml(action.label)}</button>
      `;
    case "rerun":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="rerun"
          data-rerun-handle="${escapeHtml(JSON.stringify(action.rerun))}"
          data-rerun-contract="${escapeHtml(JSON.stringify(action.contract))}"
        >${escapeHtml(action.label)}</button>
      `;
    case "recover":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="recover"
          data-recovery-key="${escapeHtml(action.recoveryKey)}"
          data-recovery-kind="${escapeHtml(action.recoveryKind)}"
          ${locationAttributes("recover", action.location)}
        >${escapeHtml(action.label)}</button>
      `;
    case "acknowledge":
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          data-card-action="acknowledge"
          data-acknowledgement-key="${escapeHtml(action.acknowledgementKey)}"
        >${escapeHtml(action.label)}</button>
      `;
    case "open":
    default:
      return `
        <button
          type="button"
          ${className}
          ${disabledAttributes}
          ${locationAttributes("open", action.location)}
        >${escapeHtml(action.label)}</button>
      `;
  }
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
  if (card.kind === "receipt") {
    return "Recorded outcome";
  }
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
      generationTone: card.trust.generationTone ?? (card.kind === "handoff" || card.kind === "decision"
        ? "attention"
        : card.kind === "receipt"
          ? "progress"
          : "neutral"),
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

function renderActionArea(card: OperatorActionCard): string {
  const contextLabel = card.actionContextLabel?.trim()
    || (card.kind === "receipt" && card.actions.length ? "Continue from here" : "");
  const warning = card.actionWarning?.trim() ?? "";
  const recoveryBlock = card.recovery
    ? `
      <div class="operator-action-recovery operator-action-recovery--${escapeHtml(card.recovery.kind)}">
        <p class="operator-action-section-title">${escapeHtml(card.recovery.title)}</p>
        ${!card.recovery.acknowledged ? `<p class="operator-action-warning">${escapeHtml(card.recovery.summary)}</p>` : ""}
        <p><strong>Do this now:</strong> ${escapeHtml(card.recovery.nextStep)}</p>
      </div>
    `
    : "";
  const rerunContracts = card.actions
    .filter((action): action is OperatorActionCardRerunAction => action.type === "rerun")
    .map((action) => renderRerunContract(action))
    .join("");
  if (!card.actions.length && !contextLabel && !warning && !recoveryBlock && !rerunContracts) {
    return "";
  }
  return `
    <section class="operator-action-section" aria-label="Actions">
      ${contextLabel ? `<p class="operator-action-section-title">${escapeHtml(contextLabel)}</p>` : ""}
      ${recoveryBlock}
      ${warning && !card.recovery ? `<p class="operator-action-warning">${escapeHtml(warning)}</p>` : ""}
      ${card.actions.length
        ? `
          <div class="operator-card-actions operator-action-card-actions">
            ${card.actions.map((action) => renderActionButton(card, action)).join("")}
          </div>
        `
        : ""}
      ${rerunContracts}
    </section>
  `;
}

function renderActionCard(card: OperatorActionCard): string {
  return `
    <article class="operator-action-card operator-action-card--${escapeHtml(card.kind)} operator-action-card--${escapeHtml(card.tone)}${card.emphasis === "primary" ? " operator-action-card--primary" : ""}">
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
      ${renderActionArea(card)}
    </article>
  `;
}

export function renderActionCardDeck(cards: readonly OperatorActionCard[], emptyStateHtml: string): string {
  if (!cards.length) {
    return emptyStateHtml;
  }
  return cards.map((card) => renderActionCard(card)).join("");
}
