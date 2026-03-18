/**
 * suggestions.ts - Loop suggestion UI.
 *
 * Purpose:
 *   Display and manage AI suggestions for loop cards inside the unified surface
 *   runtime.
 *
 * Responsibilities:
 *   - Fetch loop suggestions and render suggestion badges/panels.
 *   - Apply/reject suggestions.
 *   - Submit clarification answers for follow-up enrichment.
 *
 * Scope:
 *   - Suggestion UI inside capture/do loop cards only.
 *
 * Usage:
 *   - Imported by bootstrap.ts and render hooks.
 *
 * Invariants/Assumptions:
 *   - Loop cards expose a .badges mount for suggestion/duplicate badges.
 *   - Suggestion responses may contain either parsed JSON or suggestion_json.
 */

import * as api from "./api";
import * as modals from "./modals";
import type { ClarificationResponse, SurfaceLoop, SurfaceSuggestion, SurfaceSuggestionParsedFieldMap } from "./contracts";
import { refreshLoop } from "./loop";
import { closestFromEventTarget, escapeHtml, messageFromError } from "./utils";

async function fetchLoopSuggestions(loopId: number): Promise<SurfaceSuggestion[]> {
  try {
    return await api.fetchSuggestions(loopId, true);
  } catch {
    return [];
  }
}

function parseSuggestionPayload(suggestion: SurfaceSuggestion): SurfaceSuggestionParsedFieldMap | null {
  if (suggestion.parsed && typeof suggestion.parsed === "object") {
    return suggestion.parsed;
  }

  if (typeof suggestion.suggestion_json !== "string") {
    return null;
  }

  try {
    const parsed = JSON.parse(suggestion.suggestion_json) as unknown;
    return parsed && typeof parsed === "object" ? parsed as SurfaceSuggestionParsedFieldMap : null;
  } catch {
    return null;
  }
}

export function renderSuggestionPanel(loopCard: HTMLElement, loop: SurfaceLoop): void {
  const suggestionPanel = document.createElement("div");
  suggestionPanel.className = "suggestion-panel";
  suggestionPanel.id = `suggestions-${loop.id}`;

  void fetchLoopSuggestions(loop.id).then((suggestions) => {
    const suggestion = suggestions[0];
    if (!suggestion) {
      return;
    }
    const parsed = parseSuggestionPayload(suggestion);
    if (!parsed) {
      return;
    }

    const badges = loopCard.querySelector(".badges");
    if (!(badges instanceof HTMLElement)) {
      return;
    }

    const badge = document.createElement("span");
    badge.className = "suggestion-badge";
    badge.innerHTML = `💡 ${suggestions.length} suggestion${suggestions.length > 1 ? "s" : ""}`;
    badge.addEventListener("click", (event) => {
      event.stopPropagation();
      suggestionPanel.classList.toggle("visible");
    });
    badges.appendChild(badge);

    const fieldLabels: Record<string, string> = {
      title: "Title",
      summary: "Summary",
      next_action: "Next Action",
      tags: "Tags",
      project: "Project",
      due_at: "Due",
      urgency: "Urgency",
      importance: "Importance",
    };

    let fieldsHtml = "";
    for (const [field, label] of Object.entries(fieldLabels)) {
      const value = parsed[field];
      if (value === null || value === undefined) {
        continue;
      }

      const currentValue = loop[field as keyof SurfaceLoop] ?? "";
      const isConflict = Boolean(currentValue) && currentValue !== value;
      fieldsHtml += `
        <div class="suggestion-field">
          <input type="checkbox" class="suggestion-field-checkbox" data-field="${field}" checked>
          <span class="suggestion-field-label">${label}:</span>
          <span class="suggestion-field-value ${isConflict ? "conflict" : ""}" title="${isConflict ? `Current: ${escapeHtml(String(currentValue))}` : ""}">
            ${escapeHtml(Array.isArray(value) ? value.join(", ") : String(value))}
          </span>
        </div>
      `;
    }

    const clarificationItems = Array.isArray(suggestion.clarifications)
      ? suggestion.clarifications as ClarificationResponse[]
      : [];
    const clarifyHtml = clarificationItems.length > 0
      ? `
        <div class="needs-clarification">
          <div class="needs-clarification-title">AI needs clarification:</div>
          ${clarificationItems.map((clarification) => `
            <div class="needs-clarification-item">
              <div class="clarification-question">${escapeHtml(clarification.question)}</div>
              <input
                type="text"
                class="clarification-input"
                data-clarification-id="${clarification.id}"
                placeholder="Type your answer..."
              >
            </div>
          `).join("")}
          <button
            class="clarification-submit-btn"
            data-action="submit-clarification"
            data-loop-id="${loop.id}"
            data-suggestion-id="${suggestion.id}"
          >
            Submit Answers & Re-enrich
          </button>
        </div>
      `
      : "";

    const confidence = parsed.confidence?.["title"] ?? 0.5;
    suggestionPanel.innerHTML = `
      <div class="suggestion-header">
        <span class="suggestion-title">AI Suggestion #${suggestion.id}</span>
        <span style="font-size: 11px; color: var(--muted);">
          Confidence: ${Math.round(confidence * 100)}%
        </span>
      </div>
      <div class="suggestion-fields">${fieldsHtml}</div>
      ${clarifyHtml}
      <div class="suggestion-actions">
        <button class="suggestion-btn suggestion-btn-reject" data-action="reject-suggestion" data-suggestion-id="${suggestion.id}" data-loop-id="${loop.id}">
          Reject
        </button>
        <button class="suggestion-btn suggestion-btn-apply" data-action="apply-suggestion" data-suggestion-id="${suggestion.id}" data-loop-id="${loop.id}">
          Apply Selected
        </button>
      </div>
    `;
  });

  loopCard.appendChild(suggestionPanel);
}

export async function applySuggestion(suggestionId: number, loopId: number, panel: HTMLElement): Promise<void> {
  const checkboxes = panel.querySelectorAll<HTMLInputElement>(".suggestion-field-checkbox:checked");
  const fields = Array.from(checkboxes)
    .map((checkbox) => checkbox.dataset["field"])
    .filter((field): field is string => typeof field === "string" && field.length > 0);

  try {
    await api.applySuggestion(suggestionId, fields.length > 0 ? fields : undefined);
    await refreshLoop(loopId);
  } catch (error: unknown) {
    await modals.alertDialog({
      title: "Could Not Apply Suggestion",
      description: messageFromError(error, "Could not apply suggestion."),
      eyebrow: "Suggestions",
    });
  }
}

export async function rejectSuggestion(
  suggestionId: number,
  _loopId: number,
  panel: HTMLElement,
  badge: HTMLElement | null,
): Promise<void> {
  const confirmed = await modals.confirmDialog({
    eyebrow: "Suggestions",
    title: "Reject Suggestion",
    description: "Discard this suggestion for the current loop?",
    confirmLabel: "Reject suggestion",
    confirmVariant: "danger",
  });
  if (!confirmed) {
    return;
  }

  try {
    await api.rejectSuggestion(suggestionId);
    if (badge?.classList.contains("suggestion-badge")) {
      badge.remove();
    }
    panel.remove();
  } catch (error: unknown) {
    await modals.alertDialog({
      title: "Could Not Reject Suggestion",
      description: messageFromError(error, "Could not reject suggestion."),
      eyebrow: "Suggestions",
    });
  }
}

export function setupSuggestionHandlers(): void {
  document.addEventListener("click", async (event: MouseEvent) => {
    const applyButton = closestFromEventTarget<HTMLElement>(event.target, '[data-action="apply-suggestion"]');
    if (applyButton) {
      const suggestionId = Number.parseInt(applyButton.dataset["suggestionId"] ?? "", 10);
      const loopId = Number.parseInt(applyButton.dataset["loopId"] ?? "", 10);
      const panel = applyButton.closest(".suggestion-panel");
      if (Number.isInteger(suggestionId) && Number.isInteger(loopId) && panel instanceof HTMLElement) {
        await applySuggestion(suggestionId, loopId, panel);
      }
      return;
    }

    const rejectButton = closestFromEventTarget<HTMLElement>(event.target, '[data-action="reject-suggestion"]');
    if (rejectButton) {
      const suggestionId = Number.parseInt(rejectButton.dataset["suggestionId"] ?? "", 10);
      const loopId = Number.parseInt(rejectButton.dataset["loopId"] ?? "", 10);
      const panel = rejectButton.closest(".suggestion-panel");
      const badge = panel?.previousElementSibling;
      if (Number.isInteger(suggestionId) && Number.isInteger(loopId) && panel instanceof HTMLElement) {
        await rejectSuggestion(suggestionId, loopId, panel, badge instanceof HTMLElement ? badge : null);
      }
      return;
    }

    const clarifyButton = closestFromEventTarget<HTMLElement>(event.target, '[data-action="submit-clarification"]');
    if (clarifyButton) {
      const loopId = Number.parseInt(clarifyButton.dataset["loopId"] ?? "", 10);
      const panel = clarifyButton.closest(".suggestion-panel");
      if (Number.isInteger(loopId) && panel instanceof HTMLElement) {
        await submitClarificationAnswers(loopId, panel);
      }
    }
  });
}

async function submitClarificationAnswers(loopId: number, panel: HTMLElement): Promise<void> {
  const inputs = panel.querySelectorAll<HTMLInputElement>(".clarification-input");
  const answers: Array<{ clarification_id: number; answer: string }> = [];

  inputs.forEach((input) => {
    const clarificationId = Number.parseInt(input.dataset["clarificationId"] ?? "", 10);
    const answer = input.value.trim();
    if (Number.isInteger(clarificationId) && answer) {
      answers.push({ clarification_id: clarificationId, answer });
    }
  });

  if (answers.length === 0) {
    await modals.alertDialog({
      title: "Add At Least One Answer",
      description: "The assistant needs at least one clarification response before it can re-enrich this loop.",
      eyebrow: "Suggestions",
    });
    return;
  }

  try {
    const result = await api.refineClarification(loopId, answers);
    const nextQuestions = result.enrichment_result?.needs_clarification?.length ?? 0;
    const description = nextQuestions > 0
      ? `${result.message} The refreshed suggestion still needs ${nextQuestions} clarification${nextQuestions === 1 ? "" : "s"}.`
      : result.message;
    await modals.alertDialog({
      title: "Clarification Submitted",
      description,
      eyebrow: "Suggestions",
    });
    await refreshLoop(loopId);
  } catch (error: unknown) {
    await modals.alertDialog({
      title: "Could Not Submit Clarification",
      description: messageFromError(error, "Could not submit clarification."),
      eyebrow: "Suggestions",
    });
  }
}
