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
 *   - Submit clarification answers directly or with immediate re-enrichment.
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

import { recordRecentShellAction } from "../continuity-intelligence";
import * as api from "./api";
import * as modals from "./modals";
import type { ClarificationResponse, SurfaceLoop, SurfaceSuggestion, SurfaceSuggestionParsedFieldMap } from "./contracts";
import { refreshLoop } from "./loop";
import { buildClarificationAnswerReceiptEntry } from "./suggestion-receipts";
import { closestFromEventTarget, escapeHtml, messageFromError } from "./utils";

let suggestionHandlersInstalled = false;

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

function suggestionFieldCurrentValue(loop: SurfaceLoop, field: string): unknown {
  if (field === "due_at") {
    return loop.due_at_utc ?? loop.due_date ?? "";
  }
  if (field === "snooze_until") {
    return loop.snooze_until_utc ?? "";
  }
  return loop[field as keyof SurfaceLoop] ?? "";
}

function hasMeaningfulSuggestionValue(value: unknown): boolean {
  if (value == null) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return true;
}

function suggestionFieldConflicts(field: string, currentValue: unknown, nextValue: unknown): boolean {
  if (Array.isArray(currentValue) || Array.isArray(nextValue)) {
    if (!Array.isArray(currentValue) || !Array.isArray(nextValue)) {
      return hasMeaningfulSuggestionValue(currentValue) || hasMeaningfulSuggestionValue(nextValue);
    }
    if (field === "tags") {
      return JSON.stringify([...currentValue].map(String).sort()) !== JSON.stringify([...nextValue].map(String).sort());
    }
    return JSON.stringify(currentValue) !== JSON.stringify(nextValue);
  }
  return hasMeaningfulSuggestionValue(currentValue) && currentValue !== nextValue;
}

export function renderSuggestionPanel(loopCard: HTMLElement, loop: SurfaceLoop): void {
  if (loopCard.dataset["suggestionUiBound"] === "true") {
    return;
  }
  loopCard.dataset["suggestionUiBound"] = "true";

  void fetchLoopSuggestions(loop.id).then((suggestions) => {
    const suggestion = suggestions[0];
    if (!suggestion) {
      return;
    }

    const clarificationItems = Array.isArray(suggestion.clarifications)
      ? suggestion.clarifications as ClarificationResponse[]
      : [];
    const parsed = parseSuggestionPayload(suggestion);
    if (!parsed && clarificationItems.length === 0) {
      return;
    }

    if (!loopCard.isConnected) {
      return;
    }

    const badges = loopCard.querySelector(".badges");
    if (!(badges instanceof HTMLElement)) {
      return;
    }
    if (loopCard.querySelector(".suggestion-badge, .suggestion-panel")) {
      return;
    }

    const suggestionPanel = document.createElement("div");
    suggestionPanel.className = "suggestion-panel";
    suggestionPanel.id = `suggestions-${loop.id}`;

    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "suggestion-badge";
    badge.setAttribute("aria-controls", suggestionPanel.id);
    badge.setAttribute("aria-expanded", "false");
    badge.textContent = `💡 ${suggestions.length} suggestion${suggestions.length > 1 ? "s" : ""}`;
    badge.addEventListener("click", (event) => {
      event.stopPropagation();
      const visible = !suggestionPanel.classList.contains("visible");
      suggestionPanel.classList.toggle("visible", visible);
      badge.setAttribute("aria-expanded", visible ? "true" : "false");
    });
    badges.appendChild(badge);

    const fieldLabels: Record<string, string> = {
      title: "Title",
      summary: "Summary",
      definition_of_done: "Definition of Done",
      next_action: "Next Action",
      tags: "Tags",
      project: "Project",
      due_at: "Due",
      snooze_until: "Snooze Until",
      activation_energy: "Activation Energy",
      time_minutes: "Estimated Minutes",
      urgency: "Urgency",
      importance: "Importance",
    };

    let fieldsHtml = "";
    if (parsed) {
      for (const [field, label] of Object.entries(fieldLabels)) {
        const value = parsed[field];
        if (!hasMeaningfulSuggestionValue(value)) {
          continue;
        }

        const currentValue = suggestionFieldCurrentValue(loop, field);
        const isConflict = suggestionFieldConflicts(field, currentValue, value);
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
    }
    const hasSelectableFields = fieldsHtml.trim().length > 0;
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
          <div class="clarification-submit-actions">
            <button
              class="clarification-submit-btn"
              data-action="submit-clarification-direct"
              data-loop-id="${loop.id}"
              data-loop-title="${escapeHtml(loop.title ?? "")}"
              data-loop-raw-text="${escapeHtml(loop.raw_text)}"
            >
              Save Answers
            </button>
            <button
              class="clarification-submit-btn"
              data-action="submit-clarification-refine"
              data-loop-id="${loop.id}"
            >
              Submit Answers & Re-enrich
            </button>
          </div>
        </div>
      `
      : "";

    const confidence = typeof parsed?.confidence?.["title"] === "number"
      ? parsed.confidence["title"]
      : null;
    const detailsHtml = hasSelectableFields
      ? `<div class="suggestion-fields">${fieldsHtml}</div>`
      : '<div class="suggestion-empty">Suggestion details are unavailable in this view.</div>';
    suggestionPanel.innerHTML = `
      <div class="suggestion-header">
        <span class="suggestion-title">AI Suggestion #${suggestion.id}</span>
        ${confidence != null
          ? `<span style="font-size: 11px; color: var(--muted);">Confidence: ${Math.round(confidence * 100)}%</span>`
          : ""}
      </div>
      ${detailsHtml}
      ${clarifyHtml}
      <div class="suggestion-actions">
        <button class="suggestion-btn suggestion-btn-reject" data-action="reject-suggestion" data-suggestion-id="${suggestion.id}" data-loop-id="${loop.id}">
          Reject
        </button>
        ${hasSelectableFields
          ? `<button class="suggestion-btn suggestion-btn-apply" data-action="apply-suggestion" data-suggestion-id="${suggestion.id}" data-loop-id="${loop.id}">
          Apply Selected
        </button>`
          : ""}
      </div>
    `;
    loopCard.appendChild(suggestionPanel);
  });
}

export async function applySuggestion(suggestionId: number, loopId: number, panel: HTMLElement): Promise<void> {
  const checkboxes = panel.querySelectorAll<HTMLInputElement>(".suggestion-field-checkbox:checked");
  const fields = Array.from(checkboxes)
    .map((checkbox) => checkbox.dataset["field"])
    .filter((field): field is string => typeof field === "string" && field.length > 0);

  if (fields.length === 0) {
    await modals.alertDialog({
      title: "Select At Least One Field",
      description: "Choose one or more suggestion fields before applying them to the loop.",
      eyebrow: "Suggestions",
    });
    return;
  }

  try {
    await api.applySuggestion(suggestionId, fields);
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
  loopId: number,
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
    await refreshLoop(loopId);
  } catch (error: unknown) {
    await modals.alertDialog({
      title: "Could Not Reject Suggestion",
      description: messageFromError(error, "Could not reject suggestion."),
      eyebrow: "Suggestions",
    });
  }
}

export function setupSuggestionHandlers(): void {
  if (suggestionHandlersInstalled) {
    return;
  }
  suggestionHandlersInstalled = true;

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
      if (Number.isInteger(suggestionId) && Number.isInteger(loopId)) {
        await rejectSuggestion(suggestionId, loopId);
      }
      return;
    }

    const directClarifyButton = closestFromEventTarget<HTMLElement>(event.target, '[data-action="submit-clarification-direct"]');
    if (directClarifyButton) {
      const loopId = Number.parseInt(directClarifyButton.dataset["loopId"] ?? "", 10);
      const panel = directClarifyButton.closest(".suggestion-panel");
      if (Number.isInteger(loopId) && panel instanceof HTMLElement) {
        await submitClarificationAnswers(loopId, panel, {
          mode: "direct",
          loopTitle: directClarifyButton.dataset["loopTitle"] ?? "",
          loopRawText: directClarifyButton.dataset["loopRawText"] ?? "",
        });
      }
      return;
    }

    const refineClarifyButton = closestFromEventTarget<HTMLElement>(event.target, '[data-action="submit-clarification-refine"]');
    if (refineClarifyButton) {
      const loopId = Number.parseInt(refineClarifyButton.dataset["loopId"] ?? "", 10);
      const panel = refineClarifyButton.closest(".suggestion-panel");
      if (Number.isInteger(loopId) && panel instanceof HTMLElement) {
        await submitClarificationAnswers(loopId, panel, {
          mode: "refine",
        });
      }
    }
  });
}

async function submitClarificationAnswers(
  loopId: number,
  panel: HTMLElement,
  options:
    | {
      mode: "direct";
      loopTitle: string;
      loopRawText: string;
    }
    | {
      mode: "refine";
    },
): Promise<void> {
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
      description: options.mode === "direct"
        ? "Cloop needs at least one clarification response before it can save answer-only clarification work."
        : "Cloop needs at least one clarification response before it can re-enrich this loop.",
      eyebrow: "Suggestions",
    });
    return;
  }

  try {
    if (options.mode === "direct") {
      const result = await api.submitClarification(loopId, answers);
      recordRecentShellAction(buildClarificationAnswerReceiptEntry({
        loop: {
          id: loopId,
          title: options.loopTitle,
          raw_text: options.loopRawText,
        },
        result,
      }));
      const supersededCount = result.superseded_suggestion_ids?.length ?? 0;
      await modals.alertDialog({
        title: "Clarifications Saved",
        description: supersededCount > 0
          ? `${result.message ?? "Clarifications recorded."} Undo is available from recent actions and the command palette.`
          : `${result.message ?? "Clarifications recorded."} Undo is available from recent actions if you need to restore these questions.`,
        eyebrow: "Suggestions",
      });
      await refreshLoop(loopId);
      return;
    }

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
