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
  enrichLoop: vi.fn(),
  fetchLoop: vi.fn(),
  fetchLoops: vi.fn(),
  loadTimerStatus: vi.fn(),
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
  enrichLoop: mocks.enrichLoop,
  fetchLoop: mocks.fetchLoop,
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

vi.mock("./timer", () => ({
  loadTimerStatus: mocks.loadTimerStatus,
}));

import { enrichLoop as runEnrichLoop, init, loadInbox } from "./loop";

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

  it("refreshes the loop and reports a calm retry message when enrichment fails", async () => {
    mocks.enrichLoop.mockRejectedValueOnce({});
    mocks.fetchLoop.mockResolvedValueOnce({
      id: 19,
      status: "inbox",
      tags: [],
      title: "Clarify launch date",
      raw_text: "Clarify launch date",
      enrichment_state: "failed",
      enrichment_status: {
        state: "failed",
        label: "AI organization needs attention",
        message: "This loop is usable, but AI organization could not finish.",
        tone: "attention",
        retryable: true,
        action_label: "Retry AI organization",
        reason: "AI provider settings need attention.",
        last_event_id: 42,
        last_event_at_utc: "2026-04-27T00:01:00Z",
      },
    });
    mocks.loadTimerStatus.mockResolvedValueOnce(null);

    const inbox = document.createElement("div");
    const status = document.createElement("div");
    const existingCard = document.createElement("div");
    existingCard.className = "loop-card";
    existingCard.dataset["loopId"] = "19";
    inbox.appendChild(existingCard);

    init({
      inbox,
      status,
      queryFilter: document.createElement("input"),
      statusFilter: document.createElement("select"),
      tagFilter: document.createElement("select"),
      viewFilter: document.createElement("select"),
    });

    await runEnrichLoop(19);

    expect(mocks.enrichLoop).toHaveBeenCalledWith(19);
    expect(mocks.fetchLoop).toHaveBeenCalledWith(19);
    expect(status.textContent).toContain("loop is still usable");
  });

  it("reports when failed enrichment could not refresh persisted card state", async () => {
    mocks.enrichLoop.mockRejectedValueOnce({});
    mocks.fetchLoop.mockRejectedValueOnce(new Error("network down"));

    const inbox = document.createElement("div");
    const status = document.createElement("div");
    init({
      inbox,
      status,
      queryFilter: document.createElement("input"),
      statusFilter: document.createElement("select"),
      tagFilter: document.createElement("select"),
      viewFilter: document.createElement("select"),
    });

    await runEnrichLoop(19);

    expect(mocks.fetchLoop).toHaveBeenCalledWith(19);
    expect(status.textContent).toContain("card could not be refreshed");
    expect(status.textContent).toContain("refresh the page before retrying");
  });
});
