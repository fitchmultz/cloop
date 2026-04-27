/**
 * bootstrap-saved-view.test.ts - Regression tests for saved-view filter feedback.
 *
 * Purpose:
 *   Ensure saved-view validation stays attached to the Inbox filter controls
 *   instead of overwriting Quick capture feedback.
 *
 * Responsibilities:
 *   - Bootstrap the surface runtime against a minimal DOM fixture.
 *   - Verify empty-query saved-view validation copy, placement, and live region.
 *
 * Scope:
 *   - Saved-view UI wiring in frontend/src/surfaces/bootstrap.ts only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend exec vitest run src/surfaces/bootstrap-saved-view.test.ts`.
 *
 * Invariants/Assumptions:
 *   - The fixture mirrors the ids required by buildElements().
 */

import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  fetchViews: vi.fn(async () => []),
  fetchTemplates: vi.fn(async () => []),
  fetchTags: vi.fn(async () => []),
  saveView: vi.fn(),
}));

vi.mock("./loop", () => ({
  init: vi.fn(),
  loadInbox: vi.fn(async () => undefined),
  replaceLoop: vi.fn(),
  showCompletionNote: vi.fn(),
  enrichLoop: vi.fn(),
  refreshLoop: vi.fn(),
  toggleSnoozeDropdown: vi.fn(),
}));

vi.mock("./capture", () => ({
  init: vi.fn(),
  submitCaptureLoop: vi.fn(),
  formatDueDateInput: vi.fn(),
  reportDueDateValidationResult: vi.fn(),
}));

vi.mock("./timer", () => ({
  init: vi.fn(),
  toggleTimer: vi.fn(),
}));

vi.mock("./bulk", () => ({
  init: vi.fn(),
  handleBulkAction: vi.fn(),
  updateBulkActionBar: vi.fn(),
}));

vi.mock("./next", () => ({
  init: vi.fn(),
  setTimerToggleHandler: vi.fn(),
  loadNext: vi.fn(),
  loadFocusedLoop: vi.fn(),
}));

vi.mock("./chat", () => ({
  init: vi.fn(),
  submitChat: vi.fn(),
}));

vi.mock("./memory", () => ({
  init: vi.fn(),
  loadMemories: vi.fn(),
}));

vi.mock("./rag", () => ({
  init: vi.fn(),
  submitRagQuestion: vi.fn(),
  submitIngestPath: vi.fn(),
  handleEmptyStateAction: vi.fn(),
}));

vi.mock("./modals", () => ({
  init: vi.fn(),
  promptDialog: vi.fn(),
}));

vi.mock("./keyboard", () => ({
  init: vi.fn(),
}));

vi.mock("./comments", () => ({
  setupCommentHandlers: vi.fn(),
}));

vi.mock("./suggestions", () => ({
  setupSuggestionHandlers: vi.fn(),
}));

vi.mock("./duplicates", () => ({
  SURFACE_RUNTIME_REFRESH_EVENT: "cloop:surface-refresh",
  setupMergeHandlers: vi.fn(),
  checkAndShowDuplicateBadges: vi.fn(),
}));

vi.mock("./render", () => ({
  setDueEditorExpanded: vi.fn(),
  autoResizeTextarea: vi.fn(),
}));

vi.mock("./sse", () => ({
  connectSSE: vi.fn(),
  setupVisibilityHandler: vi.fn(),
  disconnectSSE: vi.fn(),
}));

vi.mock("./state", () => ({
  state: { templatesCache: null },
  hydrateStateFromStorage: vi.fn(),
  updateState: vi.fn(),
}));

function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn((query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function setFixture(): void {
  document.body.innerHTML = `
    <main id="inbox-main">
      <form id="capture-form" aria-busy="false">
        <textarea id="raw-text"></textarea>
        <input type="checkbox" id="actionable">
        <input type="checkbox" id="scheduled">
        <input type="checkbox" id="blocked">
        <input id="due-date">
        <input id="next-action">
        <input id="time-minutes" type="number">
        <select id="activation-energy"><option value=""></option></select>
        <input id="project">
        <input id="tags">
        <div id="capture-details"></div>
        <button id="capture-details-toggle" type="button"></button>
        <select id="template-select"><option value=""></option></select>
        <span id="status" role="status" aria-live="polite" aria-atomic="true">Ready.</span>
        <p id="capture-error" role="alert" hidden></p>
        <button id="capture-save-btn" type="submit">Save to Inbox</button>
      </form>
      <select id="query-mode-filter"><option value="dsl" selected>dsl</option><option value="semantic">semantic</option></select>
      <input id="query-filter" value="">
      <select id="status-filter"><option value="open" selected>open</option></select>
      <select id="tag-filter"><option value="" selected>all tags</option></select>
      <select id="view-filter"><option value="" selected>-</option></select>
      <button id="save-view-btn" type="button" aria-describedby="saved-view-status">Save view</button>
      <span id="saved-view-status" role="status" aria-live="polite" aria-atomic="true"></span>
      <div id="inbox"></div>
    </main>
    <main id="next-main"><div id="next-buckets"></div><input id="do-query-filter"><button id="refresh-next-btn" type="button"></button></main>
    <main id="chat-main"><div id="chat-action-cards"></div><div id="chat-messages"></div><input id="chat-input"><form id="chat-form"></form><p id="chat-thread-status"></p><button id="chat-reset-btn"></button><select id="chat-tool-mode"></select><input id="chat-loop-context" type="checkbox"><input id="chat-memory-context" type="checkbox"><input id="chat-memory-limit" type="number"><input id="chat-rag-context" type="checkbox"><input id="chat-rag-k" type="number"><input id="chat-rag-scope"><p id="chat-controls-status"></p><p id="chat-runtime-status"></p></main>
    <main id="memory-main"><div id="memory-action-cards"></div><div id="memory-list"></div><p id="memory-status"></p><form id="memory-filter-form"></form><input id="memory-query"><select id="memory-category-filter"></select><select id="memory-source-filter"></select><input id="memory-min-priority"><button id="memory-clear-filters-btn"></button><button id="memory-refresh-btn"></button><button id="memory-load-more-btn"></button><form id="memory-create-form"></form><input id="memory-key"><textarea id="memory-content"></textarea><select id="memory-category"></select><input id="memory-priority"><select id="memory-source"></select><textarea id="memory-metadata"></textarea></main>
    <main id="rag-main"><div id="rag-action-cards"></div><input id="rag-input"><form id="rag-form"></form><div id="rag-answer"><div class="rag-answer-text"></div><div class="rag-sources"></div><div class="rag-sources-list"></div></div><div id="rag-empty-state"></div><button id="rag-focus-ingest-btn"></button><form id="rag-ingest-form"></form><input id="rag-ingest-path"><select id="rag-ingest-mode"></select><input id="rag-ingest-recursive" type="checkbox"><p id="rag-ingest-status"></p></main>
    <input id="import-file" type="file">
    <div id="bulk-action-bar"></div>
    <div id="help-modal"></div>
    <div id="app-dialog"></div>
  `;
}

describe("saved-view filter feedback", () => {
  afterEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    document.body.innerHTML = "";
  });

  it("announces empty-query validation beside saved-view controls without overwriting Quick capture status", async () => {
    installMatchMedia();
    setFixture();
    const { bootstrapSurfaceRuntime } = await import("./bootstrap");
    bootstrapSurfaceRuntime();

    document.getElementById("save-view-btn")?.click();

    const savedViewStatus = document.getElementById("saved-view-status");
    expect(document.getElementById("save-view-btn")?.textContent).toBe("Save view");
    expect(savedViewStatus?.textContent).toBe("Enter a query before saving a view.");
    expect(savedViewStatus?.getAttribute("role")).toBe("status");
    expect(savedViewStatus?.getAttribute("aria-live")).toBe("polite");
    expect(savedViewStatus?.getAttribute("aria-atomic")).toBe("true");
    expect(document.getElementById("status")?.textContent).toBe("Ready.");
    expect(document.getElementById("query-filter")?.getAttribute("aria-invalid")).toBe("true");
  });

  it("explains disabled saved-view controls in semantic query mode", async () => {
    installMatchMedia();
    setFixture();
    const { bootstrapSurfaceRuntime } = await import("./bootstrap");
    bootstrapSurfaceRuntime();

    const queryFilter = document.getElementById("query-filter");
    queryFilter?.setAttribute("aria-invalid", "true");
    const modeFilter = document.getElementById("query-mode-filter") as HTMLSelectElement | null;
    if (modeFilter) {
      modeFilter.value = "semantic";
      modeFilter.dispatchEvent(new Event("change"));
    }

    expect(document.getElementById("save-view-btn")?.getAttribute("disabled")).toBe("");
    expect(document.getElementById("saved-view-status")?.textContent).toBe(
      "Saved views currently support DSL queries only.",
    );
    expect(queryFilter?.hasAttribute("aria-invalid")).toBe(false);
    expect(document.getElementById("status")?.textContent).toBe("Ready.");
  });
});
