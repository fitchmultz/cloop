/**
 * loop.test.ts - Regression tests for loop-surface rendering orchestration.
 *
 * Purpose:
 *   Verify loop cards receive the shared suggestion-surface decoration after the
 *   inbox renders or refreshes them.
 *
 * Responsibilities:
 *   - Assert inbox rendering calls the suggestion-panel renderer for each loop.
 *   - Guard direct clarification UI entrypoints against accidental render drift.
 *
 * Scope:
 *   - Focused loop-surface orchestration tests with mocked collaborators.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Loop cards expose a `.badges` mount for suggestion UI.
 *   - Suggestion decoration happens after the base loop card is rendered.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchLoops: vi.fn(),
  renderSuggestionPanel: vi.fn(),
  renderLoop: vi.fn((loop: { id: number }) => {
    const card = document.createElement("div");
    card.className = "loop-card";
    card.dataset["loopId"] = String(loop.id);
    const badges = document.createElement("div");
    badges.className = "badges";
    card.appendChild(badges);
    return card;
  }),
}));

vi.mock("./api", () => ({
  fetchLoops: mocks.fetchLoops,
  searchLoops: vi.fn(),
  searchLoopsSemantic: vi.fn(),
}));

vi.mock("./render", () => ({
  renderLoop: mocks.renderLoop,
  renderInboxEmptyState: vi.fn(() => document.createElement("div")),
  queueNextActionResize: vi.fn(),
  setCompactCardExpanded: vi.fn(),
  setMobileCardTextExpanded: vi.fn(),
}));

vi.mock("./suggestions", () => ({
  renderSuggestionPanel: mocks.renderSuggestionPanel,
}));

vi.mock("./next", () => ({
  loadNext: vi.fn(),
}));

vi.mock("./timer", () => ({}));

import { init, loadInbox } from "./loop";

describe("surfaces/loop", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  it("decorates rendered inbox cards with suggestion panels", async () => {
    mocks.fetchLoops.mockResolvedValueOnce([
      {
        id: 19,
        status: "inbox",
        tags: [],
        title: "Clarify launch date",
        raw_text: "Clarify launch date",
      },
    ]);

    const inbox = document.createElement("div");
    const status = document.createElement("div");
    const queryFilter = document.createElement("input");
    const statusFilter = document.createElement("select");
    statusFilter.value = "open";
    const tagFilter = document.createElement("select");
    tagFilter.value = "";
    const viewFilter = document.createElement("select");

    init({
      inbox,
      status,
      queryFilter,
      statusFilter,
      tagFilter,
      viewFilter,
    });

    await loadInbox();

    expect(mocks.renderLoop).toHaveBeenCalledTimes(1);
    expect(mocks.renderSuggestionPanel).toHaveBeenCalledTimes(1);
    expect(mocks.renderSuggestionPanel.mock.calls[0]?.[1]).toMatchObject({ id: 19, title: "Clarify launch date" });
    expect(inbox.querySelector('.loop-card[data-loop-id="19"]')).not.toBeNull();
  });
});
