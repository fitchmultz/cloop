/**
 * suggestions.test.ts - Regression tests for suggestion-surface interactions.
 *
 * Purpose:
 *   Verify suggestion-surface helpers avoid stale DOM assumptions and only
 *   render suggestion affordances when real data exists.
 *
 * Responsibilities:
 *   - Assert empty suggestion fetches do not leave inert panels behind.
 *   - Assert rejecting a suggestion refreshes the loop instead of mutating the
 *     DOM with a fragile sibling assumption.
 *
 * Scope:
 *   - Focused suggestion-surface behavior with mocked transport and modal deps.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Suggestion panels should only exist when a suggestion was fetched.
 *   - Successful rejection should reuse the canonical loop refresh path.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import type { SurfaceLoop } from "./contracts";

const mocks = vi.hoisted(() => ({
  fetchSuggestions: vi.fn(),
  applySuggestionApi: vi.fn(),
  rejectSuggestionApi: vi.fn(),
  refreshLoop: vi.fn(),
  confirmDialog: vi.fn(),
  alertDialog: vi.fn(),
}));

vi.mock("./api", () => ({
  fetchSuggestions: mocks.fetchSuggestions,
  applySuggestion: mocks.applySuggestionApi,
  rejectSuggestion: mocks.rejectSuggestionApi,
}));

vi.mock("./loop", () => ({
  refreshLoop: mocks.refreshLoop,
}));

vi.mock("./modals", () => ({
  confirmDialog: mocks.confirmDialog,
  alertDialog: mocks.alertDialog,
}));

vi.mock("../continuity-intelligence", () => ({
  recordRecentShellAction: vi.fn(),
}));

vi.mock("./suggestion-receipts", () => ({
  buildClarificationAnswerReceiptEntry: vi.fn(),
}));

import { applySuggestion, rejectSuggestion, renderSuggestionPanel, setupSuggestionHandlers } from "./suggestions";

describe("surfaces/suggestions", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  it("renders suggestion UI when the card is attached before async fetch settles", async () => {
    mocks.fetchSuggestions.mockResolvedValueOnce([
      {
        id: 6,
        loop_id: 19,
        suggestion_json: '{"title":"Clarify launch date"}',
        parsed: { title: "Clarify launch date" },
        clarifications: [],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
    } as SurfaceLoop);
    document.body.appendChild(loopCard);
    await Promise.resolve();
    await Promise.resolve();

    expect(loopCard.querySelector(".suggestion-badge")?.textContent).toContain("1 suggestion");
    expect(loopCard.querySelector(".suggestion-panel")).not.toBeNull();
  });

  it("does not duplicate suggestion UI when renderSuggestionPanel is called twice for one card", async () => {
    mocks.fetchSuggestions.mockResolvedValue([
      {
        id: 5,
        loop_id: 19,
        suggestion_json: '{"title":"Clarify launch date"}',
        parsed: { title: "Clarify launch date" },
        clarifications: [],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    document.body.appendChild(loopCard);

    const loop = {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
    } as SurfaceLoop;
    renderSuggestionPanel(loopCard, loop);
    renderSuggestionPanel(loopCard, loop);
    await Promise.resolve();
    await Promise.resolve();

    expect(loopCard.querySelectorAll(".suggestion-badge")).toHaveLength(1);
    expect(loopCard.querySelectorAll(".suggestion-panel")).toHaveLength(1);
    expect(mocks.fetchSuggestions).toHaveBeenCalledTimes(1);
  });

  it("does not append suggestion UI onto loop cards that were removed before fetch completed", async () => {
    let resolveSuggestions!: (value: Array<Record<string, unknown>>) => void;
    mocks.fetchSuggestions.mockReturnValueOnce(new Promise((resolve) => {
      resolveSuggestions = resolve as (value: Array<Record<string, unknown>>) => void;
    }));

    const host = document.createElement("div");
    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    host.appendChild(loopCard);
    document.body.appendChild(host);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
    } as SurfaceLoop);

    loopCard.remove();
    resolveSuggestions([
      {
        id: 7,
        loop_id: 19,
        suggestion_json: '{"title":"Clarify launch date"}',
        parsed: { title: "Clarify launch date" },
        clarifications: [],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);
    await Promise.resolve();
    await Promise.resolve();

    expect(loopCard.querySelector(".suggestion-badge")).toBeNull();
    expect(loopCard.querySelector(".suggestion-panel")).toBeNull();
  });

  it("does not append an empty suggestion panel when no suggestions exist", async () => {
    mocks.fetchSuggestions.mockResolvedValueOnce([]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    document.body.appendChild(loopCard);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
    } as SurfaceLoop);
    await Promise.resolve();

    expect(loopCard.querySelector(".suggestion-panel")).toBeNull();
    expect(loopCard.querySelector(".suggestion-badge")).toBeNull();
  });

  it("does not mark equal tag and due suggestions as conflicts", async () => {
    mocks.fetchSuggestions.mockResolvedValueOnce([
      {
        id: 7,
        loop_id: 19,
        suggestion_json: JSON.stringify({
          tags: ["launch", "urgent"],
          due_at: "2026-04-01T12:00:00Z",
        }),
        parsed: {
          tags: ["launch", "urgent"],
          due_at: "2026-04-01T12:00:00Z",
        },
        clarifications: [],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    document.body.appendChild(loopCard);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
      tags: ["urgent", "launch"],
      due_at_utc: "2026-04-01T12:00:00Z",
      due_date: null,
    } as SurfaceLoop);
    await Promise.resolve();
    await Promise.resolve();

    const conflictValues = Array.from(loopCard.querySelectorAll(".suggestion-field-value.conflict"))
      .map((node) => node.textContent?.trim());
    expect(conflictValues).toEqual([]);
    const badge = loopCard.querySelector<HTMLButtonElement>(".suggestion-badge");
    expect(badge).not.toBeNull();
    expect(badge?.getAttribute("aria-expanded")).toBe("false");
  });

  it("renders backend-applicable fields that were previously omitted from the browser surface", async () => {
    mocks.fetchSuggestions.mockResolvedValueOnce([
      {
        id: 10,
        loop_id: 19,
        suggestion_json: JSON.stringify({
          definition_of_done: "Ship with verified undo receipts.",
          activation_energy: 2,
          time_minutes: 30,
          snooze_until: "2026-04-02T12:00:00Z",
        }),
        parsed: {
          definition_of_done: "Ship with verified undo receipts.",
          activation_energy: 2,
          time_minutes: 30,
          snooze_until: "2026-04-02T12:00:00Z",
        },
        clarifications: [],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    document.body.appendChild(loopCard);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
    } as SurfaceLoop);
    await Promise.resolve();
    await Promise.resolve();

    const labels = Array.from(loopCard.querySelectorAll(".suggestion-field-label"))
      .map((node) => node.textContent?.trim());
    expect(labels).toEqual(expect.arrayContaining([
      "Definition of Done:",
      "Activation Energy:",
      "Estimated Minutes:",
      "Snooze Until:",
    ]));
    expect(loopCard.querySelector('[data-action="apply-suggestion"]')).not.toBeNull();
  });

  it("still renders clarification-only suggestions when parsed details are unavailable", async () => {
    mocks.fetchSuggestions.mockResolvedValueOnce([
      {
        id: 9,
        loop_id: 19,
        suggestion_json: "{not-json}",
        parsed: null,
        clarifications: [
          {
            id: 3,
            loop_id: 19,
            question: "When should this happen?",
            answer: null,
            answered_at: null,
            created_at: "2026-03-30 06:22:50",
          },
        ],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    document.body.appendChild(loopCard);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
    } as SurfaceLoop);
    await Promise.resolve();
    await Promise.resolve();

    expect(loopCard.querySelector(".suggestion-badge")).not.toBeNull();
    expect(loopCard.querySelector(".suggestion-empty")?.textContent).toContain("Suggestion details are unavailable");
    expect(loopCard.querySelector('[data-action="submit-clarification-direct"]')).not.toBeNull();
    expect(loopCard.querySelector('[data-action="apply-suggestion"]')).toBeNull();
  });

  it("marks changed zero-valued numeric suggestions as conflicts", async () => {
    mocks.fetchSuggestions.mockResolvedValueOnce([
      {
        id: 8,
        loop_id: 19,
        suggestion_json: JSON.stringify({ importance: 1 }),
        parsed: { importance: 1 },
        clarifications: [],
        model: "test-model",
        created_at: "2026-03-30 06:22:50",
        resolution: null,
        resolved_at: null,
        resolved_fields_json: null,
      },
    ]);

    const loopCard = document.createElement("div");
    const badges = document.createElement("div");
    badges.className = "badges";
    loopCard.appendChild(badges);
    document.body.appendChild(loopCard);

    renderSuggestionPanel(loopCard, {
      id: 19,
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
      importance: 0,
    } as SurfaceLoop);
    await Promise.resolve();
    await Promise.resolve();

    const conflictValues = Array.from(loopCard.querySelectorAll(".suggestion-field-value.conflict"))
      .map((node) => node.textContent?.trim());
    expect(conflictValues).toEqual(["1"]);
  });

  it("requires at least one selected field before applying a suggestion", async () => {
    const panel = document.createElement("div");
    panel.innerHTML = `
      <input type="checkbox" class="suggestion-field-checkbox" data-field="title">
      <input type="checkbox" class="suggestion-field-checkbox" data-field="summary">
    `;

    await applySuggestion(7, 19, panel);

    expect(mocks.applySuggestionApi).not.toHaveBeenCalled();
    expect(mocks.refreshLoop).not.toHaveBeenCalled();
    expect(mocks.alertDialog).toHaveBeenCalledWith(expect.objectContaining({
      title: "Select At Least One Field",
    }));
  });

  it("installs suggestion handlers only once", async () => {
    const button = document.createElement("button");
    button.dataset["action"] = "apply-suggestion";
    button.dataset["suggestionId"] = "7";
    button.dataset["loopId"] = "19";

    const panel = document.createElement("div");
    panel.className = "suggestion-panel";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "suggestion-field-checkbox";
    checkbox.dataset["field"] = "title";
    checkbox.checked = true;
    panel.appendChild(checkbox);
    panel.appendChild(button);
    document.body.appendChild(panel);

    mocks.applySuggestionApi.mockResolvedValueOnce({ ok: true });

    setupSuggestionHandlers();
    setupSuggestionHandlers();
    button.click();
    await Promise.resolve();
    await Promise.resolve();

    expect(mocks.applySuggestionApi).toHaveBeenCalledTimes(1);
    expect(mocks.refreshLoop).toHaveBeenCalledTimes(1);
  });

  it("refreshes the loop after rejecting a suggestion", async () => {
    mocks.confirmDialog.mockResolvedValueOnce(true);
    mocks.rejectSuggestionApi.mockResolvedValueOnce({ ok: true });

    await rejectSuggestion(7, 19);

    expect(mocks.rejectSuggestionApi).toHaveBeenCalledWith(7);
    expect(mocks.refreshLoop).toHaveBeenCalledWith(19);
    expect(mocks.alertDialog).not.toHaveBeenCalled();
  });
});
