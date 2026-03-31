/**
 * shell-workspace.test.ts - Regression tests for operator-home refresh orchestration.
 *
 * Purpose:
 *   Verify the shell workspace coordinates workspace fetches and durable continuity
 *   hydration through one queued refresh path.
 *
 * Responsibilities:
 *   - Assert operator rendering waits for continuity hydration before settling.
 *   - Assert queued refresh requests rerun after an in-flight refresh completes.
 *   - Assert background refreshes keep settled cards visible and surface continuity errors.
 *
 * Scope:
 *   - Shell workspace controller behavior only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests use jsdom DOM elements for shell containers.
 *   - Shared HTTP requests remain mocked at the transport boundary.
 */

import type { ContinuityBaselineSnapshot } from "./contracts-ui";
import type {
  EnrichmentReviewSessionResponse,
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewResponse,
  NowFeedResponse,
  PlanningSessionResponse,
  RelationshipReviewSessionResponse,
  WorkingSetContextResponse,
} from "./domain";
import type { ShellElements, WorkspaceData } from "./shell-types";
import { createShellWorkspaceController } from "./shell-workspace";
import { requestJson } from "./http";
import {
  buildContinuityBaseline,
  hydrateDurableContinuityState,
  readContinuityBaseline,
  readContinuityWorkflowSummaries,
  writeContinuityBaseline,
} from "./continuity-intelligence";

vi.mock("./http", () => ({
  requestJson: vi.fn(),
}));

vi.mock("./continuity-intelligence", () => ({
  buildContinuityBaseline: vi.fn(() => ({ marker: "baseline" })),
  hydrateDurableContinuityState: vi.fn(async () => undefined),
  readContinuityBaseline: vi.fn(() => ({ marker: "baseline" })),
  readContinuityWorkflowSummaries: vi.fn(() => []),
  writeContinuityBaseline: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createElements(): ShellElements {
  const div = (): HTMLDivElement => document.createElement("div");
  const button = (): HTMLButtonElement => document.createElement("button");

  return {
    operatorMain: div(),
    inboxMain: div(),
    nextMain: div(),
    reviewMain: div(),
    chatMain: div(),
    memoryMain: div(),
    ragMain: div(),
    workingSetMain: div(),
    shellTitle: div(),
    shellDescription: div(),
    shellContext: div(),
    shellRoutePill: div(),
    shellLastVisit: div(),
    shellReceiptRail: div(),
    shellPrimaryAction: button(),
    refreshWorkspaceButton: button(),
    commandPaletteButton: button(),
    createWorkingSetButton: button(),
    stateButtons: [],
    recallSubnav: div(),
    recallButtons: [],
    operatorNow: div(),
    operatorDecisions: div(),
    operatorPlan: div(),
    operatorRecall: div(),
    operatorSinceLast: div(),
    operatorWorkingSet: div(),
    workingSetFocusBanner: div(),
    workingSetFocusSummary: div(),
    workingSetFocusItems: div(),
    workingSetFocusToggleButton: button(),
    workingSetExitFocusButton: button(),
  };
}

function emptyNowFeed(): NowFeedResponse {
  return { generated_at_utc: "2026-03-27T00:00:00Z", items: [] };
}

function emptyReviewData(): LoopReviewResponse {
  return { daily: [], generated_at_utc: "2026-03-27T00:00:00Z", weekly: [] };
}

function emptyMetrics(): LoopMetricsResponse {
  return {
    generated_at_utc: "2026-03-27T00:00:00Z",
    total_loops: 0,
    status_counts: {
      inbox: 0,
      actionable: 0,
      blocked: 0,
      scheduled: 0,
      completed: 0,
      dropped: 0,
    },
    stale_open_count: 0,
    blocked_too_long_count: 0,
    no_next_action_count: 0,
    enrichment_pending_count: 0,
    enrichment_failed_count: 0,
    capture_count_24h: 0,
    completion_count_24h: 0,
    avg_age_open_hours: null,
    project_breakdown: null,
    trend_metrics: null,
  };
}

function mockWorkspaceRequest(url: string): Promise<unknown> {
  switch (url) {
    case "/loops/now?limit=8":
      return Promise.resolve(emptyNowFeed());
    case "/loops/review?daily=true&weekly=true&limit=50":
      return Promise.resolve(emptyReviewData());
    case "/loops/metrics":
      return Promise.resolve(emptyMetrics());
    case "/loops/planning/sessions":
      return Promise.resolve([] satisfies PlanningSessionResponse[]);
    case "/loops/review/relationship/sessions":
      return Promise.resolve([] satisfies RelationshipReviewSessionResponse[]);
    case "/loops/review/enrichment/sessions":
      return Promise.resolve([] satisfies EnrichmentReviewSessionResponse[]);
    case "/loops/?status=all":
      return Promise.resolve([] satisfies LoopResponse[]);
    default:
      throw new Error(`Unexpected request: ${url}`);
  }
}

function createHarness(overrides: {
  loadWorkingSetState?: () => Promise<void>;
  renderOperatorZones?: (data: WorkspaceData) => void;
  getWorkingSetContext?: () => WorkingSetContextResponse | null;
} = {}) {
  const elements = createElements();
  let visitStatePersisted = false;
  let continuityBaseline: ContinuityBaselineSnapshot | null = null;
  const renderOperatorZones = vi.fn((data: WorkspaceData) => {
    elements.operatorNow.innerHTML = `ready ${data.metrics.total_loops}`;
    elements.operatorSinceLast.innerHTML = "since last ready";
    overrides.renderOperatorZones?.(data);
  });
  const renderWorkingSet = vi.fn();
  const renderWorkingSetFocusBanner = vi.fn();
  const syncFocusModeClass = vi.fn();
  const renderWorkingSetSessionSurface = vi.fn();
  const onWorkspaceSettled = vi.fn();
  const loadWorkingSetState = vi.fn(overrides.loadWorkingSetState ?? (async () => undefined));

  const controller = createShellWorkspaceController({
    getElements: () => elements,
    getCurrentLocation: () => ({
      state: "operator",
      recallTool: "chat",
      reviewFocus: null,
      sessionId: null,
      loopId: null,
      viewId: null,
      memoryId: null,
      workingSetId: null,
      query: null,
    }),
    getVisitStatePersisted: () => visitStatePersisted,
    setVisitStatePersisted: (value) => {
      visitStatePersisted = value;
    },
    setContinuityBaseline: (value) => {
      continuityBaseline = value;
    },
    writeLastVisitNow: vi.fn(),
    getWorkingSetContext: overrides.getWorkingSetContext ?? (() => null),
    loadWorkingSetState,
    renderOperatorZones,
    renderWorkingSet,
    renderWorkingSetFocusBanner,
    syncFocusModeClass,
    renderWorkingSetSessionSurface,
    onWorkspaceSettled,
  });

  return {
    controller,
    elements,
    renderOperatorZones,
    renderWorkingSet,
    renderWorkingSetFocusBanner,
    syncFocusModeClass,
    renderWorkingSetSessionSurface,
    onWorkspaceSettled,
    loadWorkingSetState,
    getContinuityBaseline: () => continuityBaseline,
  };
}

describe("shell-workspace", () => {
  beforeEach(() => {
    vi.mocked(requestJson).mockImplementation((url: string) => mockWorkspaceRequest(url));
    vi.mocked(hydrateDurableContinuityState).mockResolvedValue(undefined);
    vi.mocked(readContinuityWorkflowSummaries).mockReturnValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("waits for continuity hydration and replays queued refresh requests", async () => {
    const nextLoopsDeferred = deferred<NowFeedResponse>();
    const continuityDeferred = deferred<void>();
    let nextRequestCount = 0;
    let continuityRequestCount = 0;

    vi.mocked(requestJson).mockImplementation((url: string) => {
      if (url === "/loops/now?limit=8") {
        nextRequestCount += 1;
        return nextRequestCount === 1 ? nextLoopsDeferred.promise : Promise.resolve(emptyNowFeed());
      }
      return mockWorkspaceRequest(url);
    });
    vi.mocked(hydrateDurableContinuityState).mockImplementation(() => {
      continuityRequestCount += 1;
      return continuityRequestCount === 1 ? continuityDeferred.promise : Promise.resolve();
    });

    const { controller, renderOperatorZones, onWorkspaceSettled } = createHarness();

    const firstRefresh = controller.renderOperatorWorkspace();
    const secondRefresh = controller.renderOperatorWorkspace();

    expect(renderOperatorZones).not.toHaveBeenCalled();

    nextLoopsDeferred.resolve(emptyNowFeed());
    continuityDeferred.resolve();

    await firstRefresh;
    await secondRefresh;

    expect(renderOperatorZones).toHaveBeenCalledTimes(2);
    expect(onWorkspaceSettled).toHaveBeenCalledTimes(2);
    expect(continuityRequestCount).toBe(2);
  });

  it("keeps settled cards visible during background refreshes", async () => {
    const { controller, elements, renderOperatorZones } = createHarness({
      renderOperatorZones: (data) => {
        elements.operatorNow.innerHTML = `ready card ${data.metrics.total_loops}`;
      },
    });

    await controller.renderOperatorWorkspace();
    expect(elements.operatorNow.innerHTML).toBe("ready card 0");

    const nextLoopsDeferred = deferred<NowFeedResponse>();
    const continuityDeferred = deferred<void>();
    let nextRequestCount = 0;
    let continuityRequestCount = 0;

    vi.mocked(requestJson).mockImplementation((url: string) => {
      if (url === "/loops/now?limit=8") {
        nextRequestCount += 1;
        return nextRequestCount === 1 ? nextLoopsDeferred.promise : Promise.resolve(emptyNowFeed());
      }
      return mockWorkspaceRequest(url);
    });
    vi.mocked(hydrateDurableContinuityState).mockImplementation(() => {
      continuityRequestCount += 1;
      return continuityRequestCount === 1 ? continuityDeferred.promise : Promise.resolve();
    });

    const pendingRefresh = controller.renderOperatorWorkspace();

    expect(elements.operatorNow.innerHTML).toBe("ready card 0");
    expect(elements.operatorNow.textContent).not.toContain("Loading prioritized work");

    nextLoopsDeferred.resolve(emptyNowFeed());
    continuityDeferred.resolve();
    await pendingRefresh;

    expect(renderOperatorZones).toHaveBeenCalledTimes(2);
    expect(continuityRequestCount).toBe(1);
    expect(elements.operatorNow.innerHTML).toBe("ready card 0");
  });

  it("shows a recoverable continuity state when hydration fails without warm cache", async () => {
    vi.mocked(hydrateDurableContinuityState).mockRejectedValue(new Error("offline"));
    vi.mocked(readContinuityWorkflowSummaries).mockReturnValue([]);

    const { controller, elements, renderOperatorZones, renderWorkingSet, getContinuityBaseline } = createHarness();

    await controller.renderOperatorWorkspace();

    expect(renderOperatorZones).toHaveBeenCalledTimes(1);
    expect(renderWorkingSet).toHaveBeenCalledTimes(1);
    expect(elements.operatorSinceLast.textContent).toContain("Continuity could not refresh right now");
    expect(vi.mocked(buildContinuityBaseline)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(writeContinuityBaseline)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(readContinuityBaseline)).toHaveBeenCalledTimes(1);
    expect(getContinuityBaseline()).toEqual({ marker: "baseline" });
  });
});
