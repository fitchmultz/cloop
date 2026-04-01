/**
 * modals.test.ts - Searchable picker modal regression tests.
 * Purpose: verify the shared option picker stays keyboard-first and preview-rich.
 * Responsibilities: cover listbox selection movement, preview rendering, and submit wiring.
 * Scope: shared modal picker behavior only.
 * Usage: run with `pnpm --dir frontend test modals.test.ts`.
 * Invariants/Assumptions: the shared app-dialog markup matches frontend/index.html ids.
 */

import { describe, expect, it } from "vitest";

import { chooseOptionDialog, init } from "./modals";

function buildModalDom(): void {
  document.body.innerHTML = `
    <div id="help-modal"></div>
    <div class="app-dialog-overlay" id="app-dialog" hidden>
      <div class="app-dialog" tabindex="-1">
        <div class="app-dialog-header">
          <div class="app-dialog-heading">
            <p id="app-dialog-eyebrow" class="app-dialog-eyebrow" hidden></p>
            <h2 id="app-dialog-title">Dialog</h2>
          </div>
          <button class="app-dialog-close" type="button" data-action="close-app-dialog" aria-label="Close dialog">&times;</button>
        </div>
        <p id="app-dialog-description" class="app-dialog-description" hidden></p>
        <form id="app-dialog-form" class="app-dialog-form" novalidate>
          <div id="app-dialog-fields" class="app-dialog-fields"></div>
          <p id="app-dialog-error" class="app-dialog-error" role="alert" hidden></p>
          <div class="app-dialog-actions">
            <button id="app-dialog-cancel" class="secondary" type="button" data-action="cancel-app-dialog">Cancel</button>
            <button id="app-dialog-confirm" class="app-dialog-confirm" type="submit">Continue</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("chooseOptionDialog", () => {
  it("renders a preview-rich keyboard listbox and submits the selected value", async () => {
    buildModalDom();
    init({
      helpModal: document.getElementById("help-modal"),
      appDialog: document.getElementById("app-dialog"),
    });

    const resultPromise = chooseOptionDialog({
      title: "Choose queue target",
      description: "Pick the exact saved review target.",
      options: [
        {
          value: "11",
          label: "Launch checklist → Launch checklist duplicate",
          description: "duplicate · 99% similarity",
          badge: "Current focus",
          preview: {
            eyebrow: "Relationship candidate",
            title: "Launch checklist duplicate",
            description: "Launch checklist duplicate",
            badges: ["duplicate"],
            meta: [
              { label: "Queue loop", value: "Launch checklist" },
              { label: "Similarity", value: "99% similarity" },
            ],
          },
        },
        {
          value: "15",
          label: "Retro notes",
          description: "Summarize retro · summary, next_action · 85% confidence",
          preview: {
            eyebrow: "Enrichment suggestion",
            title: "Retro notes",
            description: "Summarize retro",
            badges: ["2 fields"],
            meta: [
              { label: "Suggested fields", value: "summary, next_action" },
              { label: "Confidence", value: "85% confidence" },
            ],
          },
        },
      ],
      value: "11",
    });

    await settle();

    const preview = document.querySelector<HTMLElement>(".app-dialog-picker-preview");
    const searchInput = document.querySelector<HTMLInputElement>("#app-dialog-field-picker-search");
    if (!preview || !searchInput) {
      throw new Error("Picker UI did not render.");
    }

    expect(preview.textContent).toContain("Launch checklist duplicate");
    expect(preview.textContent).toContain("Current focus");
    expect(preview.textContent).toContain("99% similarity");

    searchInput.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    await settle();

    const selectedOption = document.querySelector<HTMLElement>(".app-dialog-picker-option.is-selected");
    expect(selectedOption?.textContent ?? "").toContain("Retro notes");
    expect(preview.textContent).toContain("Retro notes");
    expect(preview.textContent).toContain("85% confidence");

    document.getElementById("app-dialog-form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await expect(resultPromise).resolves.toBe("15");
  });
});
