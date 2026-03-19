/**
 * shell-operator-cards.test.ts - Regression tests for working-set-aware operator handoff cards.
 *
 * Purpose:
 *   Guard operator-card assembly so propagated working-set context remains
 *   visible on planning and since-last handoff cards.
 *
 * Responsibilities:
 *   - Assert planning execution and launch cards keep propagated working-set metadata.
 *   - Assert since-last handoff and resume-anchor cards expose working-set context.
 *   - Assert focus-mode filtering still keeps matching handoff cards when legacy launches omit working-set ids.
 *
 * Scope:
 *   - Renderer-driven operator-card output only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests run under jsdom.
 *   - Card actions continue to encode navigation through `data-open-*` attributes.
 *   - Working-set propagation stays frontend-only in this slice.
 */

import { rememberPlanningAnchor, rememberReviewAnchor } from "./continuity-intelligence";
import type {
  PlanningExecutionHistoryItemResponse,
  PlanningSessionSnapshotResponse,
  WorkingSetContextResponse,
  WorkingSetItemResponse,
  WorkingSetResponse,
} from "./domain";
import { createLocation } from "./shell-routing";
import { createShellOperatorCardRenderer } from "./shell-operator-cards";
import type { ShellElements, ShellLocation, WorkspaceData } from "./shell-types";

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

function makeWorkingSet(
  id: number,
  name: string,
  items: WorkingSetItemResponse[] = [],
): WorkingSetResponse {
  return {
    id,
    name,
    description: `${name} description`,
    item_count: items.length || 1,
    missing_item_count: items.filter((item) => item.missing).length,
    items,
  } as WorkingSetResponse;
}

function makeWorkingSetItem(
  sessionId: number,
  workingSetId: number | null,
): WorkingSetItemResponse {
  return {
    id: 1,
    label: `Enrichment queue #${sessionId}`,
    description: "Focused downstream review queue",
    kind: "location",
    kind_label: "Review queue",
    status_label: "Ready",
    missing: false,
    launch: {
      state: "decide",
      recall_tool: "chat",
      review_focus: "enrichment",
      session_id: sessionId,
      loop_id: null,
      view_id: null,
      memory_id: null,
      working_set_id: workingSetId,
      query: null,
    },
  } as unknown as WorkingSetItemResponse;
}

function makeWorkingSetContext(
  activeWorkingSet: WorkingSetResponse | null,
  focusModeEnabled = false,
): WorkingSetContextResponse | null {
  if (!activeWorkingSet) {
    return null;
  }
  return {
    active_working_set_id: activeWorkingSet.id,
    active_working_set: activeWorkingSet,
    focus_mode_enabled: focusModeEnabled,
  } as WorkingSetContextResponse;
}

function makeExecution(
  workingSetId: number,
  sessionId = 27,
): PlanningExecutionHistoryItemResponse {
  return {
    checkpoint_index: 0,
    checkpoint_title: "Execute checkpoint",
    operation_count: 2,
    executed_at_utc: "2026-03-18T18:05:00Z",
    rollback_cues: {
      undoable_operation_count: 1,
      rollback_supported_operation_count: 0,
      operations: [],
    },
    follow_up_resources: [
      {
        resource_type: "review_session",
        resource_id: sessionId,
        label: "Enrichment review queue",
        role: "Next workflow",
        operation_kind: "create_enrichment_review_session",
        operation_summary: "Created enrichment review queue",
        launch_surface: {
          resource_type: "review_session",
          resource_id: sessionId,
          surface: "review_session",
          label: "Enrichment review queue",
          reason: "Continue with the created enrichment review queue.",
          web: {
            surface: "review_session",
            review_kind: "enrichment",
            session_id: sessionId,
            working_set_id: workingSetId,
          },
        },
      },
    ],
    launch_surfaces: [
      {
        resource_type: "review_session",
        resource_id: sessionId,
        surface: "review_session",
        label: "Enrichment review queue",
        reason: "Continue with the created enrichment review queue.",
        web: {
          surface: "review_session",
          review_kind: "enrichment",
          session_id: sessionId,
          working_set_id: workingSetId,
        },
      },
    ],
    resource_change_summary: {
      total_change_count: 1,
      loop_change_count: 0,
      downstream_change_count: 1,
      group_count: 1,
      created_resource_count: 1,
      updated_resource_count: 0,
      groups: [],
      loop_groups: [],
      downstream_groups: [],
      summary_label: "1 downstream resource change",
      downstream_summary_label: "1 downstream resource change",
    },
  } as unknown as PlanningExecutionHistoryItemResponse;
}

function makePlanningSnapshot(executionHistory: PlanningExecutionHistoryItemResponse[]): PlanningSessionSnapshotResponse {
  return {
    session: {
      id: 14,
      name: "Weekly reset",
      prompt: "Review the execution state",
      query: "status:open",
      loop_limit: 10,
      include_memory_context: true,
      include_rag_context: false,
      rag_k: 5,
      rag_scope: null,
      current_checkpoint_index: 0,
      checkpoint_count: 1,
      executed_checkpoint_count: executionHistory.length,
      next_unexecuted_checkpoint_index: null,
      generated_at_utc: "2026-03-18T18:00:00Z",
      last_executed_at_utc: executionHistory.at(-1)?.executed_at_utc ?? null,
      status: "in_progress",
      created_at_utc: "2026-03-18T18:00:00Z",
      updated_at_utc: "2026-03-18T18:05:00Z",
    },
    plan_title: "Weekly reset",
    plan_summary: "Resume the current operating slice.",
    assumptions: [],
    context_summary: {},
    context_freshness: null,
    execution_analytics: {},
    resource_change_summary: {
      total_change_count: 1,
      loop_change_count: 0,
      downstream_change_count: 1,
      group_count: 1,
      created_resource_count: 1,
      updated_resource_count: 0,
      groups: [],
      loop_groups: [],
      downstream_groups: [],
      summary_label: "1 downstream resource change",
      downstream_summary_label: "1 downstream resource change",
    },
    target_loops: [
      {
        id: 44,
        raw_text: "Check the generated review queue",
        status: "actionable",
        tags: [],
      },
    ],
    sources: [],
    checkpoints: [],
    current_checkpoint: null,
    execution_history: executionHistory,
  } as unknown as PlanningSessionSnapshotResponse;
}

function makeWorkspaceData(planningSnapshot: PlanningSessionSnapshotResponse | null): WorkspaceData {
  return {
    nextLoops: {} as WorkspaceData["nextLoops"],
    reviewData: {
      generated_at_utc: "2026-03-18T18:10:00Z",
      daily: [],
      weekly: [],
    } as WorkspaceData["reviewData"],
    metrics: {
      stale_open_count: 0,
      blocked_too_long_count: 0,
      no_next_action_count: 0,
    } as WorkspaceData["metrics"],
    planningSessions: [],
    planningSnapshot,
    relationshipSessions: [],
    relationshipSnapshot: null,
    enrichmentSessions: [],
    enrichmentSnapshot: null,
    allLoops: [],
  } as WorkspaceData;
}

function workingSetItemLocation(item: WorkingSetItemResponse): ShellLocation {
  return createLocation({
    state: item.launch.state,
    recallTool: item.launch.recall_tool,
    reviewFocus: item.launch.review_focus,
    sessionId: item.launch.session_id,
    loopId: item.launch.loop_id,
    viewId: item.launch.view_id,
    memoryId: item.launch.memory_id,
    workingSetId: item.launch.working_set_id,
    query: item.launch.query,
  });
}

function createHarness(options: {
  visitBaseline: Date | null;
  workingSets?: WorkingSetResponse[];
  workingSetContext?: WorkingSetContextResponse | null;
}) {
  const elements = createElements();
  const renderer = createShellOperatorCardRenderer({
    getElements: () => elements,
    getVisitBaseline: () => options.visitBaseline,
    getContinuityBaseline: () => null,
    getLatestWorkingSets: () => options.workingSets ?? [],
    getWorkingSetContext: () => options.workingSetContext ?? null,
    workingSetItemLocation,
    focusModeActiveSet: () => options.workingSetContext?.active_working_set ?? null,
  });
  return { elements, renderer };
}

function findCard(container: HTMLElement, title: string): HTMLElement | null {
  return Array.from(container.querySelectorAll<HTMLElement>("article")).find((card) => {
    return card.querySelector("h3")?.textContent === title;
  }) ?? null;
}

function createMemoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length(): number {
      return values.size;
    },
    clear(): void {
      values.clear();
    },
    getItem(key: string): string | null {
      return values.get(key) ?? null;
    },
    key(index: number): string | null {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      values.delete(key);
    },
    setItem(key: string, value: string): void {
      values.set(key, value);
    },
  } satisfies Storage;
}

let originalLocalStorage: Storage;

describe("shell-operator-cards", () => {
  beforeEach(() => {
    originalLocalStorage = window.localStorage as Storage;
    Object.defineProperty(window, "localStorage", {
      value: createMemoryStorage(),
      configurable: true,
      writable: true,
    });
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-18T18:10:00Z"));
  });

  afterEach(() => {
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    vi.useRealTimers();
  });

  it("keeps propagated working-set context on planning handoff cards", () => {
    const propagatedSet = makeWorkingSet(2, "Review Prep");
    const activeSet = makeWorkingSet(9, "Active Focus");
    const execution = makeExecution(2);
    const data = makeWorkspaceData(makePlanningSnapshot([execution]));
    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [propagatedSet, activeSet],
      workingSetContext: makeWorkingSetContext(activeSet, false),
    });

    renderer.renderPlanZone(data);

    const executionCard = findCard(elements.operatorPlan, "Execute checkpoint");
    const launchCard = findCard(elements.operatorPlan, "Enrichment review queue");
    expect(executionCard).not.toBeNull();
    expect(launchCard).not.toBeNull();
    expect(executionCard?.textContent).toContain("Review Prep");
    expect(executionCard?.textContent).not.toContain("Active Focus");
    expect(launchCard?.textContent).toContain("Review Prep");

    const executionButton = executionCard?.querySelector<HTMLButtonElement>(
      'button[data-open-state="decide"][data-open-review-focus="enrichment"][data-open-session-id="27"]',
    );
    expect(executionButton?.getAttribute("data-open-working-set-id")).toBe("2");
  });

  it("renders since-last handoff cards with propagated working-set context", () => {
    const propagatedSet = makeWorkingSet(2, "Review Prep");
    const execution = makeExecution(2);
    const data = makeWorkspaceData(makePlanningSnapshot([execution]));
    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [propagatedSet],
    });

    renderer.renderSinceLastVisit(data);

    const card = findCard(elements.operatorSinceLast, "Plan-created downstream handoffs");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("Review Prep");

    const button = card?.querySelector<HTMLButtonElement>(
      'button[data-open-state="decide"][data-open-review-focus="enrichment"][data-open-session-id="27"]',
    );
    expect(button?.getAttribute("data-open-working-set-id")).toBe("2");
  });

  it("names working-set context in resume-anchor cards", () => {
    const propagatedSet = makeWorkingSet(2, "Review Prep");
    rememberPlanningAnchor(41, 2);
    vi.setSystemTime(new Date("2026-03-18T18:11:00Z"));
    rememberReviewAnchor("enrichment", 27, 2);
    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [propagatedSet],
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    const card = findCard(elements.operatorSinceLast, "Pick up where you left off");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("Review Prep");

    const button = card?.querySelector<HTMLButtonElement>(
      'button[data-open-state="decide"][data-open-review-focus="enrichment"][data-open-session-id="27"]',
    );
    expect(button?.getAttribute("data-open-working-set-id")).toBe("2");
  });

  it("keeps matching handoff cards visible in focus mode when saved items omit working-set ids", () => {
    const activeSet = makeWorkingSet(2, "Review Prep", [makeWorkingSetItem(27, null)]);
    const execution = makeExecution(2);
    const data = makeWorkspaceData(makePlanningSnapshot([execution]));
    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [activeSet],
      workingSetContext: makeWorkingSetContext(activeSet, true),
    });

    renderer.renderPlanZone(data);

    expect(findCard(elements.operatorPlan, "Execute checkpoint")).not.toBeNull();
    expect(findCard(elements.operatorPlan, "Enrichment review queue")).not.toBeNull();
  });
});
