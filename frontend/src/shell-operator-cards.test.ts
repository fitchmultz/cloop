/**
 * shell-operator-cards.test.ts - Regression tests for working-set-aware operator handoff cards.
 *
 * Purpose:
 *   Guard operator-card assembly so propagated working-set context and the
 *   primary continuity recommendation remain visible in operator zones.
 *
 * Responsibilities:
 *   - Assert planning execution and launch cards keep propagated working-set metadata.
 *   - Assert primary-next-move and since-last digest cards render from durable continuity.
 *   - Assert since-last handoff cards expose working-set context.
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

import { recordRecentShellAction } from "./continuity-intelligence";
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
    run_id: 44,
    checkpoint_index: 0,
    checkpoint_title: "Execute checkpoint",
    operation_count: 2,
    executed_at_utc: "2026-03-18T18:05:00Z",
    is_active: true,
    rollback: null,
    rollback_cues: {
      undoable_operation_count: 1,
      rollback_supported_operation_count: 1,
      rollback_action_count: 1,
      operations: [],
    },
    results: [
      {
        rollback_actions: [
          {
            kind: "loop.undo",
            resource_type: "loop",
            resource_id: 5,
            summary: "Undo loop update for loop 5",
            payload: { loop_id: 5, expected_event_id: 88 },
          },
        ],
      },
    ],
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

function makePlanningRerunAction(sessionId: number, sessionName: string) {
  return {
    label: "Refresh plan",
    description: "Land back in the saved planning session with refreshed checkpoints, trust metadata, and handoff cues.",
    rerun: {
      kind: "planning_session",
      session_id: sessionId,
      session_name: sessionName,
    },
    contract: {
      mode: "refresh",
      provenance_label: `Planning session: ${sessionName}`,
      freshness_label: "Updated 2026-03-18T18:05:00Z",
      strategy_summary: "Reuse the saved planning session and refresh it against current loop state.",
      strict_invariants: ["Same planning session identity"],
      may_vary: ["Checkpoint wording and emphasis"],
      post_run: {
        summary: "Land back in the saved planning session with refreshed checkpoints, trust metadata, and handoff cues.",
        location: {
          state: "plan",
          recall_tool: "chat",
          review_focus: "planning",
          session_id: sessionId,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: null,
        },
      },
    },
  };
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
    rerun_action: makePlanningRerunAction(14, "Weekly reset"),
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

const WORKFLOW_SUMMARIES_CACHE_KEY = "cloop.continuity.workflow-summaries.cache.v2";
const NOTIFICATION_RECORDS_CACHE_KEY = "cloop.continuity.notification-records.cache.v1";

function seedWorkflowSummaries(summaries: unknown[]): void {
  window.localStorage.setItem(WORKFLOW_SUMMARIES_CACHE_KEY, JSON.stringify(summaries));
  window.localStorage.setItem(
    NOTIFICATION_RECORDS_CACHE_KEY,
    JSON.stringify(
      summaries.flatMap((summary) => {
        if (
          typeof summary !== "object"
          || summary === null
          || typeof (summary as { id?: unknown }).id !== "string"
          || typeof (summary as { displayTitle?: unknown }).displayTitle !== "string"
          || typeof (summary as { displaySummary?: unknown }).displaySummary !== "string"
          || typeof (summary as { workflowThread?: { id?: unknown; kind?: unknown; title?: unknown; summary?: unknown; parentOutcomeId?: unknown } }).workflowThread?.id !== "string"
          || typeof (summary as { resolvedResume?: { resolvedLocation?: unknown } }).resolvedResume?.resolvedLocation !== "object"
          || (summary as { resolvedResume?: { resolvedLocation?: unknown } }).resolvedResume?.resolvedLocation === null
        ) {
          return [];
        }
        const typed = summary as {
          id: string;
          displayTitle: string;
          displaySummary: string;
          rankingSignals?: { driftSeverity?: unknown; workingSetRelevant?: unknown; downstreamReady?: unknown };
          workflowThread: {
            id: string;
            kind: string;
            title: string;
            summary: string | null;
            parentOutcomeId: number | null;
          };
          resolvedResume: { resolvedLocation: unknown };
          whyNow?: unknown;
          changedSinceLastSeen?: unknown;
        };
        return [{
          id: typed.id,
          title: typed.rankingSignals?.driftSeverity === "gone"
            ? `${typed.displayTitle} needs a recovery decision`
            : typed.rankingSignals?.workingSetRelevant === true
              ? `${typed.displayTitle} is ready in your working set`
              : typed.rankingSignals?.downstreamReady === true
                ? `${typed.displayTitle} is ready to resume`
                : typed.displayTitle,
          body: [
            ...(Array.isArray(typed.whyNow) ? typed.whyNow : []),
            ...(Array.isArray(typed.changedSinceLastSeen) ? typed.changedSinceLastSeen : []),
            typed.displaySummary,
          ].filter((value): value is string => typeof value === "string").slice(0, 2).join(" · "),
          severity: typed.rankingSignals?.driftSeverity === "gone" ? "alert" : "info",
          workflowThread: typed.workflowThread,
          resolvedLocation: typed.resolvedResume.resolvedLocation,
        }];
      }),
    ),
  );
}

function summaryRecord(input: {
  id: string;
  rank: number;
  occurredAt: string;
  workflowThreadId: string;
  workflowThreadTitle: string;
  workflowThreadSummary: string | null;
  representativeOutcomeId?: number | null;
  resolvedLocation: ShellLocation;
  requestedLocation?: ShellLocation | null;
  displayTitle: string;
  displaySummary: string;
  workingSetName?: string | null;
  source?: "receipt" | "recent";
  outcomeCount?: number;
  outcomePreviewTitles?: string[];
  driftSeverity?: "none" | "minor" | "moderate" | "major" | "replaced" | "gone";
  driftScore?: number;
  workingSetRelevant?: boolean;
  downstreamReady?: boolean;
  degraded?: boolean;
  degradedLabel?: string | null;
  whyNow?: string[];
  changedSinceLastSeen?: string[];
  priorState?: { kind: "replaced" | "gone"; title: string; summary: string } | null;
}) {
  return {
    id: input.id,
    source: input.source ?? "receipt",
    rank: input.rank,
    rankingSignals: {
      driftSeverity: input.driftSeverity ?? "moderate",
      driftScore: input.driftScore ?? 52,
      workingSetRelevant: input.workingSetRelevant ?? false,
      downstreamReady: input.downstreamReady ?? true,
      degraded: input.degraded ?? false,
      recencyTieBreaker: 18,
    },
    workflowThread: {
      id: input.workflowThreadId,
      kind: "planning_checkpoint",
      title: input.workflowThreadTitle,
      summary: input.workflowThreadSummary,
      parentOutcomeId: null,
    },
    representativeOutcomeId: input.representativeOutcomeId ?? null,
    latestOutcomeId: input.representativeOutcomeId ?? null,
    occurredAt: input.occurredAt,
    outcomeCount: input.outcomeCount ?? 1,
    outcomePreviewTitles: input.outcomePreviewTitles ?? [input.displayTitle],
    requestedResumeLocation: input.requestedLocation ?? input.resolvedLocation,
    resolvedResume: {
      requestedLocation: input.requestedLocation ?? input.resolvedLocation,
      resolvedLocation: input.resolvedLocation,
      status: input.degraded ? "home_fallback" : "ok",
      message: input.degradedLabel ?? null,
      successor: null,
    },
    displayTitle: input.displayTitle,
    displaySummary: input.displaySummary,
    displayCard: {
      kind: "context",
      tone: input.degraded ? "attention" : "neutral",
      eyebrow: "Workflow summary",
      title: input.displayTitle,
      summary: input.displaySummary,
      rationale: "Backend continuity summary",
      preview: [],
      trust: {
        generationLabel: "Backend continuity summary",
        generationTone: "neutral",
        contextSources: ["Durable continuity workflow summary"],
        assumptions: [],
        confidenceLabel: "Deterministic continuity ranking",
        confidenceTone: "progress",
        freshnessLabel: null,
        freshnessTone: "neutral",
        rollbackLabel: null,
        rollbackTone: "neutral",
        impactSummary: input.displaySummary,
        impactTone: "neutral",
      },
      handoff: input.workingSetName
        ? {
            changeSummary: input.displaySummary,
            createdResources: [],
            nextStep: null,
            breadcrumbs: ["Home", input.workflowThreadTitle],
            workingSet: {
              workingSetId: input.resolvedLocation.workingSetId ?? 0,
              workingSetName: input.workingSetName,
              itemCount: 0,
              missingItemCount: 0,
            },
          }
        : null,
      actionContextLabel: "Continue from here",
      actionWarning: input.degradedLabel ?? null,
    },
    workingSetId: input.resolvedLocation.workingSetId ?? null,
    workingSetName: input.workingSetName ?? null,
    degraded: input.degraded ?? false,
    degradedLabel: input.degradedLabel ?? null,
    whyNow: input.whyNow ?? ["This workflow has fresh unseen movement."],
    changedSinceLastSeen: input.changedSinceLastSeen ?? ["This workflow has never been seen from durable continuity."],
    priorState: input.priorState ?? null,
  };
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

  it("renders a primary next move at the top of the Now zone", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Created launch review queue",
      description: "Created the downstream queue.",
      location: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
      outcome: {
        card: {
          id: "receipt-primary",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Launch review queue is ready",
          summary: "Open the prepared queue.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Undo remains available.",
          },
          handoff: {
            changeSummary: "Queue created",
            createdResources: ["Launch review queue"],
            nextStep: "Open the queue.",
            breadcrumbs: ["Home", "Plan"],
          },
          actions: [],
        },
        resumeLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
        rollbackLabel: "Undo remains available.",
        undoAction: null,
        workflowThread: {
          id: "planning:41",
          kind: "planning_checkpoint",
          title: "Weekly reset",
          summary: "Planning checkpoint thread",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
          resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
      persistence: { status: "synced", persistedOutcomeId: 12, syncedAtUtc: "2026-03-18T18:10:00Z" },
    });
    seedWorkflowSummaries([
      summaryRecord({
        id: "planning:41",
        rank: 5400,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "planning:41",
        workflowThreadTitle: "Weekly reset",
        workflowThreadSummary: "Planning checkpoint thread",
        representativeOutcomeId: 12,
        resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
        displayTitle: "Launch review queue is ready",
        displaySummary: "Open the prepared queue.",
      }),
    ]);

    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
    });

    renderer.renderNowZone(makeWorkspaceData(null));

    expect(elements.operatorNow.querySelector(".operator-action-card--primary h3")?.textContent)
      .toBe("Launch review queue is ready");
  });

  it("surfaces explicit recovery cards near the top of since-last", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Created launch review queue",
      description: "Created the downstream queue.",
      location: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
      outcome: {
        card: {
          id: "receipt-recovery",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Launch review queue is ready",
          summary: "Open the prepared queue.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Undo remains available.",
          },
          handoff: {
            changeSummary: "Queue created",
            createdResources: ["Launch review queue"],
            nextStep: "Open the queue.",
            breadcrumbs: ["Home", "Plan"],
          },
          actions: [],
        },
        resumeLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
        rollbackLabel: "Undo remains available.",
        undoAction: null,
        workflowThread: {
          id: "planning:99",
          kind: "planning_checkpoint",
          title: "Replacement plan",
          summary: "New planning thread",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
          resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
      persistence: { status: "synced", persistedOutcomeId: 12, syncedAtUtc: "2026-03-18T18:10:00Z" },
    });
    seedWorkflowSummaries([
      summaryRecord({
        id: "planning:99",
        rank: 5400,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "planning:99",
        workflowThreadTitle: "Replacement plan",
        workflowThreadSummary: "New planning thread",
        representativeOutcomeId: 12,
        resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
        displayTitle: "Launch review queue is ready",
        displaySummary: "Open the prepared queue.",
        whyNow: ["A newer workflow superseded the prior path you last saved."],
        changedSinceLastSeen: ["This workflow has never been seen from durable continuity."],
        priorState: {
          kind: "replaced",
          title: "Old launch plan",
          summary: "Old launch plan was superseded by Launch review queue is ready.",
        },
      }),
      {
        ...summaryRecord({
          id: "planning:41",
          rank: 3200,
          occurredAt: "2026-03-18T18:09:00Z",
          workflowThreadId: "planning:41",
          workflowThreadTitle: "Old launch plan",
          workflowThreadSummary: "Prior planning path",
          source: "recent",
          resolvedLocation: createLocation({ state: "operator" }),
          requestedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          displayTitle: "Old launch plan",
          displaySummary: "Prior planning path",
          degraded: true,
          degradedLabel: "Original landed target is unavailable, so continuity falls back to home.",
          whyNow: ["The prior landing target disappeared, so this is the safest surviving path."],
          changedSinceLastSeen: ["This workflow has never been seen from durable continuity."],
        }),
        resolvedResume: {
          requestedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          resolvedLocation: createLocation({ state: "operator" }),
          status: "home_fallback",
          message: "Original landed target is unavailable, so continuity falls back to home.",
          successor: {
            kind: "replacement",
            outcomeId: 12,
            title: "Launch review queue is ready",
            summary: "Open the prepared queue.",
            workflowThread: {
              id: "planning:99",
              kind: "planning_checkpoint",
              title: "Replacement plan",
              summary: "New planning thread",
              parentOutcomeId: null,
            },
            requestedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
            resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
            status: "ok",
            message: "Old launch plan was superseded by Launch review queue is ready.",
          },
        },
      },
    ]);

    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    const headings = Array.from(elements.operatorSinceLast.querySelectorAll("h3")).map((node) => node.textContent);
    expect(headings[0]).toBe("Why this workflow became the top recommendation");
    expect(findCard(elements.operatorSinceLast, "Old launch plan")).not.toBeNull();
    expect(elements.operatorSinceLast.textContent).toContain("Open replacement workflow");
  });

  it("renders a calm digest explaining why the workflow became the top recommendation", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Created launch review queue",
      description: "Created the downstream queue.",
      location: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
      outcome: {
        card: {
          id: "receipt-primary-digest",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Launch review queue is ready",
          summary: "Open the prepared queue.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Undo remains available.",
          },
          handoff: {
            changeSummary: "Queue created",
            createdResources: ["Launch review queue"],
            nextStep: "Open the queue.",
            breadcrumbs: ["Home", "Plan"],
          },
          actions: [],
        },
        resumeLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
        rollbackLabel: "Undo remains available.",
        undoAction: null,
        workflowThread: {
          id: "planning:41",
          kind: "planning_checkpoint",
          title: "Weekly reset",
          summary: "Planning checkpoint thread",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
          resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
      persistence: { status: "synced", persistedOutcomeId: 12, syncedAtUtc: "2026-03-18T18:10:00Z" },
    });
    seedWorkflowSummaries([
      summaryRecord({
        id: "planning:41",
        rank: 5400,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "planning:41",
        workflowThreadTitle: "Weekly reset",
        workflowThreadSummary: "Planning checkpoint thread",
        representativeOutcomeId: 12,
        resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52 }),
        displayTitle: "Launch review queue is ready",
        displaySummary: "Open the prepared queue.",
      }),
    ]);

    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    expect(findCard(elements.operatorSinceLast, "Why this workflow became the top recommendation")).not.toBeNull();
  });

  it("renders notification inbox controls from durable continuity state", () => {
    seedWorkflowSummaries([
      summaryRecord({
        id: "planning:41",
        rank: 5400,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "planning:41",
        workflowThreadTitle: "Weekly reset",
        workflowThreadSummary: "Planning checkpoint thread",
        resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 2 }),
        displayTitle: "Created launch review queue",
        displaySummary: "Open the prepared queue.",
        workingSetName: "Review Prep",
        workingSetRelevant: true,
      }),
    ]);

    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [makeWorkingSet(2, "Review Prep")],
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    expect(elements.operatorSinceLast.querySelector('button[data-acknowledgement-key="notification:planning:41"]')).not.toBeNull();
    expect(elements.operatorSinceLast.querySelector('button[data-notification-suppress-id="planning:41"]')).not.toBeNull();
    expect(elements.operatorSinceLast.textContent).toContain("Hide for 1 day");
  });

  it("renders the next-ranked follow-through card with propagated working-set context after the top outcome is reserved for the rail", () => {
    const propagatedSet = makeWorkingSet(2, "Review Prep");
    vi.setSystemTime(new Date("2026-03-18T18:11:00Z"));
    seedWorkflowSummaries([
      summaryRecord({
        id: "review:enrichment:27",
        rank: 5100,
        occurredAt: "2026-03-18T18:11:00Z",
        workflowThreadId: "review:enrichment:27",
        workflowThreadTitle: "Resume enrichment queue · Review Prep",
        workflowThreadSummary: "Return to the saved enrichment queue.",
        source: "recent",
        resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 2 }),
        displayTitle: "Resume enrichment queue · Review Prep",
        displaySummary: "Return to the saved enrichment queue.",
        workingSetName: "Review Prep",
        workingSetRelevant: true,
      }),
      summaryRecord({
        id: "planning:41",
        rank: 4800,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "planning:41",
        workflowThreadTitle: "Resume plan · Weekly reset",
        workflowThreadSummary: "Return to the saved planning session.",
        source: "recent",
        resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 2 }),
        displayTitle: "Resume plan · Weekly reset",
        displaySummary: "Return to the saved planning session.",
        workingSetName: "Review Prep",
        workingSetRelevant: true,
      }),
    ]);
    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [propagatedSet],
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    const card = findCard(elements.operatorSinceLast, "Resume plan · Weekly reset");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("Review Prep");

    const button = card?.querySelector<HTMLButtonElement>(
      'button[data-open-state="plan"][data-open-review-focus="planning"][data-open-session-id="41"]',
    );
    expect(button?.getAttribute("data-open-working-set-id")).toBe("2");
  });

  it("keeps the top recent outcome out of since-last so the receipt rail can own it", () => {
    recordRecentShellAction({
      kind: "review",
      label: "Applied enrichment suggestion",
      description: "Applied suggestion #41 and refreshed the queue.",
      location: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 2 }),
      outcome: {
        card: {
          id: "receipt-1",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Enrichment receipt",
          title: "Applied enrichment suggestion",
          summary: "Applied suggestion #41 and refreshed the queue.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Saved enrichment session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Rejecting is no longer available after apply.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 2 }),
        rollbackLabel: "Rejecting is no longer available after apply.",
        undoAction: null,
      },
    });
    seedWorkflowSummaries([
      summaryRecord({
        id: "review:enrichment:27",
        rank: 5400,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "review:enrichment:27",
        workflowThreadTitle: "Applied enrichment suggestion",
        workflowThreadSummary: "Applied suggestion #41 and refreshed the queue.",
        representativeOutcomeId: 1,
        resolvedLocation: createLocation({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 2 }),
        displayTitle: "Applied enrichment suggestion",
        displaySummary: "Applied suggestion #41 and refreshed the queue.",
        workingSetRelevant: true,
      }),
      summaryRecord({
        id: "planning:41",
        rank: 4800,
        occurredAt: "2026-03-18T18:09:00Z",
        workflowThreadId: "planning:41",
        workflowThreadTitle: "Resume plan · Weekly reset",
        workflowThreadSummary: "Return to the saved planning session.",
        source: "recent",
        resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 2 }),
        displayTitle: "Resume plan · Weekly reset",
        displaySummary: "Return to the saved planning session.",
        workingSetName: "Review Prep",
        workingSetRelevant: true,
      }),
    ]);
    const { elements, renderer } = createHarness({
      visitBaseline: new Date("2026-03-18T18:00:00Z"),
      workingSets: [makeWorkingSet(2, "Review Prep")],
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    const firstHeading = elements.operatorSinceLast.querySelector("h3");
    expect(firstHeading?.textContent).toBe("Why this workflow became the top recommendation");
    expect(elements.operatorSinceLast.textContent).toContain("Resume plan · Weekly reset");
    expect(findCard(elements.operatorSinceLast, "Applied enrichment suggestion")).toBeNull();
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

  it("renders durable since-last cards even without a browser-local visit baseline", () => {
    recordRecentShellAction({
      kind: "planning",
      label: "Refreshed weekly reset",
      description: "The planning session was refreshed.",
      location: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
      outcome: {
        card: {
          id: "receipt-durable-1",
          kind: "receipt",
          tone: "progress",
          eyebrow: "Planning receipt",
          title: "Refreshed weekly reset",
          summary: "The planning session was refreshed.",
          rationale: "Receipt",
          preview: [],
          trust: {
            contextSources: ["Planning session"],
            assumptions: [],
            confidenceLabel: "Recorded",
            freshnessLabel: "Saved just now",
            rollbackLabel: "Open the plan to continue.",
          },
          handoff: null,
          actions: [],
        },
        resumeLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
        rollbackLabel: "Open the plan to continue.",
        undoAction: null,
        workflowThread: {
          id: "planning:41",
          kind: "planning_checkpoint",
          title: "Weekly reset",
          summary: "Planning checkpoint thread",
          parentOutcomeId: null,
        },
        resolvedResume: {
          requestedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          status: "ok",
          message: null,
          successor: null,
        },
      },
    });
    seedWorkflowSummaries([
      summaryRecord({
        id: "planning:41",
        rank: 5200,
        occurredAt: "2026-03-18T18:10:00Z",
        workflowThreadId: "planning:41",
        workflowThreadTitle: "Weekly reset",
        workflowThreadSummary: "Planning checkpoint thread",
        resolvedLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
        displayTitle: "Refreshed weekly reset",
        displaySummary: "The planning session was refreshed.",
      }),
    ]);

    const { elements, renderer } = createHarness({
      visitBaseline: null,
      workingSets: [],
    });

    renderer.renderSinceLastVisit(makeWorkspaceData(null));

    expect(findCard(elements.operatorSinceLast, "Why this workflow became the top recommendation")).not.toBeNull();
    expect(elements.operatorSinceLast.textContent).not.toContain("first recorded visit");
  });
});
