/**
 * modals.test.ts - Shared modal runtime regression tests.
 * Purpose: verify app dialogs stay keyboard-first, preview-rich, and properly isolated from background UI.
 * Responsibilities: cover modal background isolation, focus trapping, listbox selection movement, preview rendering, and submit wiring.
 * Scope: shared modal runtime behavior only.
 * Usage: run with `pnpm --dir frontend test modals.test.ts`.
 * Invariants/Assumptions: the shared app-dialog markup matches frontend/index.html ids.
 */

import { describe, expect, it } from "vitest";

import { chooseOptionDialog, init, promptDialog, showHelpModal } from "./modals";

function buildModalDom(): void {
  document.body.innerHTML = `
    <header id="app-header"><button id="background-plan-tab">Plan</button></header>
    <main id="operator-main"><button id="background-export">Export data</button></main>
    <div id="bulk-action-bar"><button id="background-bulk-complete">Complete</button></div>
    <section id="already-hidden" aria-hidden="true"><button id="hidden-before-modal">Already hidden</button></section>
    <div id="help-modal" role="dialog" aria-modal="true" aria-hidden="true" hidden>
      <div class="help-modal" tabindex="-1"><button type="button" data-action="close-help">Close help</button></div>
    </div>
    <div class="app-dialog-overlay" id="app-dialog" role="dialog" aria-modal="true" hidden>
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

describe("promptDialog", () => {
  it("isolates background content while open and restores it after Escape closes the dialog", async () => {
    buildModalDom();
    init({
      helpModal: document.getElementById("help-modal"),
      appDialog: document.getElementById("app-dialog"),
    });

    const trigger = document.getElementById("background-plan-tab") as HTMLButtonElement;
    trigger.focus();

    const resultPromise = promptDialog({
      title: "New planning session",
      description: "Create a checkpointed plan.",
      confirmLabel: "Create session",
      fields: [
        { name: "name", label: "Session name", required: true },
        { name: "prompt", label: "Planning prompt", type: "textarea", rows: 5, required: true },
      ],
    });
    await settle();

    const appDialog = document.getElementById("app-dialog") as HTMLElement;
    const header = document.getElementById("app-header") as HTMLElement;
    const main = document.getElementById("operator-main") as HTMLElement;
    const bulkBar = document.getElementById("bulk-action-bar") as HTMLElement;
    const alreadyHidden = document.getElementById("already-hidden") as HTMLElement;

    expect(appDialog.hidden).toBe(false);
    expect(appDialog.getAttribute("aria-hidden")).toBeNull();
    expect(appDialog.inert).not.toBe(true);
    expect(header.inert).toBe(true);
    expect(header.getAttribute("aria-hidden")).toBe("true");
    expect(main.inert).toBe(true);
    expect(main.getAttribute("aria-hidden")).toBe("true");
    expect(bulkBar.inert).toBe(true);
    expect(bulkBar.getAttribute("aria-hidden")).toBe("true");
    expect(alreadyHidden.inert).toBe(true);
    expect(alreadyHidden.getAttribute("aria-hidden")).toBe("true");

    appDialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    await expect(resultPromise).resolves.toBeNull();

    expect(header.inert).toBe(false);
    expect(header.getAttribute("aria-hidden")).toBeNull();
    expect(main.inert).toBe(false);
    expect(main.getAttribute("aria-hidden")).toBeNull();
    expect(bulkBar.inert).toBe(false);
    expect(bulkBar.getAttribute("aria-hidden")).toBeNull();
    expect(alreadyHidden.inert).toBe(false);
    expect(alreadyHidden.getAttribute("aria-hidden")).toBe("true");
    expect(document.activeElement).toBe(trigger);
  });

  it("wraps Tab focus inside the dialog and re-enters when focus starts outside", async () => {
    buildModalDom();
    init({
      helpModal: document.getElementById("help-modal"),
      appDialog: document.getElementById("app-dialog"),
    });

    const resultPromise = promptDialog({
      title: "New planning session",
      fields: [
        { name: "name", label: "Session name", required: true },
        { name: "prompt", label: "Planning prompt", type: "textarea", required: true },
      ],
    });
    await settle();

    const appDialog = document.getElementById("app-dialog") as HTMLElement;
    const closeButton = document.querySelector<HTMLButtonElement>("[data-action='close-app-dialog']");
    const confirmButton = document.getElementById("app-dialog-confirm") as HTMLButtonElement;
    const backgroundButton = document.getElementById("background-export") as HTMLButtonElement;
    if (!closeButton) {
      throw new Error("Close button did not render.");
    }

    confirmButton.focus();
    appDialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(closeButton);

    closeButton.focus();
    appDialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(confirmButton);

    backgroundButton.focus();
    appDialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(closeButton);

    closeButton.click();
    await expect(resultPromise).resolves.toBeNull();
  });
});

describe("help modal", () => {
  it("uses the shared modal isolation while visible", () => {
    buildModalDom();
    init({
      helpModal: document.getElementById("help-modal"),
      appDialog: document.getElementById("app-dialog"),
    });

    const trigger = document.getElementById("background-plan-tab") as HTMLButtonElement;
    const header = document.getElementById("app-header") as HTMLElement;
    const helpModal = document.getElementById("help-modal") as HTMLElement;
    trigger.focus();

    showHelpModal(true);
    expect(helpModal.hidden).toBe(false);
    expect(helpModal.getAttribute("aria-hidden")).toBeNull();
    expect(header.inert).toBe(true);
    expect(header.getAttribute("aria-hidden")).toBe("true");

    showHelpModal(false);
    expect(helpModal.hidden).toBe(true);
    expect(helpModal.getAttribute("aria-hidden")).toBe("true");
    expect(header.inert).toBe(false);
    expect(header.getAttribute("aria-hidden")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

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
