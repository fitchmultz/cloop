/**
 * shell.ts - Operator workspace and state-driven navigation bootstrap.
 *
 * Purpose:
 *   Establish the operator-first shell on top of the TypeScript-owned frontend runtime.
 *
 * Responsibilities:
 *   - Drive the top-level state-oriented navigation model.
 *   - Render the operator workspace using typed backend contracts.
 *   - Launch capture, do, and recall through typed surface contracts.
 *   - Preserve deep-linkable context for plan/review/recall launches.
 *   - Maintain durable working-set/focus-mode context and since-last-visit summary.
 *
 * Scope:
 *   - Top-level shell routing, workspace aggregation, and shell-specific
 *     keyboard/navigation behaviors.
 *
 * Usage:
 *   - Imported and invoked from frontend/src/main.ts.
 *
 * Invariants/Assumptions:
 *   - Existing deep-work DOM surfaces remain present in frontend/index.html.
 *   - Hash routes are the canonical shareable/deep-link format for shell state.
 */

import { bootstrapCommandPalette } from "./command-palette";
import { renderActionCardDeck } from "./operator-action-cards";
import { requestJson } from "./http";
import * as modals from "./modals";
import type {
  ClarificationResponse,
  EnrichmentReviewSessionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewCohortItem,
  LoopReviewCohortResponse,
  LoopReviewResponse,
  NextLoopsResponse,
  PlanningContextFreshnessTargetChangeResponse,
  PlanningExecutionFollowUpResourceResponse,
  PlanningExecutionHistoryItemResponse,
  PlanningExecutionLaunchSurfaceResponse,
  PlanningExecutionRollbackCueResponse,
  PlanningSessionResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewCandidateResponse,
  RelationshipReviewSessionResponse,
  RelationshipReviewSessionSnapshotResponse,
  SuggestionResponse,
  WorkingSetContextResponse,
  WorkingSetContextUpdateRequest,
  WorkingSetItemCreateRequest,
  WorkingSetItemResponse,
  WorkingSetResponse,
} from "./domain";
import type {
  ContinuityBaselineSnapshot,
  OperatorActionCard,
  OperatorActionCardAction,
  RecentShellActionEntry,
  RecallTool,
  ReviewFocus,
  ShellLocationContract,
  ShellState,
  WorkingSetSessionMetadata,
} from "./contracts-ui";
import {
  buildContinuityBaseline,
  readContinuityBaseline,
  readRecentShellActions,
  readResumeAnchors,
  recordRecentShellAction,
  rememberPlanningAnchor,
  rememberReviewAnchor,
  writeContinuityBaseline,
} from "./continuity-intelligence";
import {
  buildChangedCountPreviewItems,
  buildGroupedChangePreviewItems,
  buildPlanningResourcePreviewItems,
  buildRepeatedSnoozeSignal,
  mergePlanningResourceChangeGroups,
  sortLoopsByMostRecentUpdate,
} from "./continuity-card-helpers";
import { contractFromLocation, type FrontendSurfaceRegistry } from "./surface-runtime";

type ShellLocation = ShellLocationContract;

interface ShellLocationInput {
  state?: ShellState | undefined;
  recallTool?: RecallTool | undefined;
  reviewFocus?: ReviewFocus | null | undefined;
  sessionId?: number | null | undefined;
  loopId?: number | null | undefined;
  viewId?: number | null | undefined;
  memoryId?: number | null | undefined;
  workingSetId?: number | null | undefined;
  query?: string | null | undefined;
}

interface WorkspaceData {
  nextLoops: NextLoopsResponse;
  reviewData: LoopReviewResponse;
  metrics: LoopMetricsResponse;
  planningSessions: PlanningSessionResponse[];
  planningSnapshot: PlanningSessionSnapshotResponse | null;
  relationshipSessions: RelationshipReviewSessionResponse[];
  relationshipSnapshot: RelationshipReviewSessionSnapshotResponse | null;
  enrichmentSessions: EnrichmentReviewSessionResponse[];
  enrichmentSnapshot: EnrichmentReviewSessionSnapshotResponse | null;
  allLoops: LoopResponse[];
}

interface ShellElements {
  operatorMain: HTMLElement;
  inboxMain: HTMLElement;
  nextMain: HTMLElement;
  reviewMain: HTMLElement;
  chatMain: HTMLElement;
  memoryMain: HTMLElement;
  ragMain: HTMLElement;
  workingSetMain: HTMLElement;
  shellTitle: HTMLElement;
  shellDescription: HTMLElement;
  shellContext: HTMLElement;
  shellRoutePill: HTMLElement;
  shellLastVisit: HTMLElement;
  shellPrimaryAction: HTMLButtonElement;
  refreshWorkspaceButton: HTMLButtonElement;
  commandPaletteButton: HTMLButtonElement;
  createWorkingSetButton: HTMLButtonElement;
  stateButtons: HTMLButtonElement[];
  recallSubnav: HTMLElement;
  recallButtons: HTMLButtonElement[];
  operatorNow: HTMLElement;
  operatorDecisions: HTMLElement;
  operatorPlan: HTMLElement;
  operatorRecall: HTMLElement;
  operatorSinceLast: HTMLElement;
  operatorWorkingSet: HTMLElement;
  workingSetFocusBanner: HTMLElement;
  workingSetFocusSummary: HTMLElement;
  workingSetFocusItems: HTMLElement;
  workingSetFocusToggleButton: HTMLButtonElement;
  workingSetExitFocusButton: HTMLButtonElement;
}

interface ShellRuntimeDependencies {
  surfaces: FrontendSurfaceRegistry;
}

interface StateDescriptor {
  title: string;
  description: string;
  context: string;
  pill: string;
  primaryActionLabel: string;
  primaryActionLocation: ShellLocation;
}

const SHELL_LOCATION_STORAGE_KEY = "cloop.shell.location.v1";
const LAST_VISIT_STORAGE_KEY = "cloop.shell.lastVisitAt.v1";
const HIGHLIGHT_CLASS = "operator-highlight";
const REVIEW_FOCUS_EVENT = "cloop:review-focus";
const WORKSPACE_REFRESH_EVENT = "cloop:workspace-refresh-requested";

const DEFAULT_LOCATION: ShellLocation = {
  state: "operator",
  recallTool: "chat",
  reviewFocus: null,
  sessionId: null,
  loopId: null,
  workingSetId: null,
};

const STATE_DESCRIPTORS: Record<ShellState, StateDescriptor> = {
  operator: {
    title: "Operator workspace",
    description:
      "See the highest-signal work, active sessions, and recent changes in one calm home surface.",
    context:
      "Start from what deserves attention now, then launch straight into the next queue or work mode.",
    pill: "Home",
    primaryActionLabel: "Capture something",
    primaryActionLocation: {
      state: "capture",
      recallTool: "chat",
      reviewFocus: null,
      sessionId: null,
      loopId: null,
    },
  },
  capture: {
    title: "Capture",
    description:
      "Collect new loops and context without friction, then decide later what deserves deeper structure.",
    context:
      "Keep raw capture visible, then use filters and saved views to clarify what just arrived.",
    pill: "Capture",
    primaryActionLabel: "Return home",
    primaryActionLocation: DEFAULT_LOCATION,
  },
  do: {
    title: "Do",
    description: "Work from prioritized next actions and focused execution surfaces instead of broad backlog lists.",
    context: "This surface is for ready work: due-soon items, quick wins, and high-leverage loops.",
    pill: "Do",
    primaryActionLabel: "Open ready work",
    primaryActionLocation: {
      state: "do",
      recallTool: "chat",
      reviewFocus: null,
      sessionId: null,
      loopId: null,
    },
  },
  decide: {
    title: "Decide",
    description:
      "Step through saved review queues, clarifications, and ambiguous relationship decisions with context preserved.",
    context:
      "Relationship and enrichment sessions should feel like one judgment workspace, not multiple disconnected tabs.",
    pill: "Decide",
    primaryActionLabel: "Open decision queues",
    primaryActionLocation: {
      state: "decide",
      recallTool: "chat",
      reviewFocus: "relationship",
      sessionId: null,
      loopId: null,
    },
  },
  plan: {
    title: "Plan",
    description: "Resume checkpointed planning sessions and execute deterministic next steps with handoff cues visible.",
    context:
      "This surface keeps plan status, the current checkpoint, and the downstream queue together.",
    pill: "Plan",
    primaryActionLabel: "Open planning",
    primaryActionLocation: {
      state: "plan",
      recallTool: "chat",
      reviewFocus: "planning",
      sessionId: null,
      loopId: null,
    },
  },
  review: {
    title: "Review",
    description:
      "Run broader hygiene passes, drift checks, and review cohorts that keep the whole system trustworthy.",
    context:
      "Use daily and weekly cohorts to reduce stale work, blocked drift, and other quality problems.",
    pill: "Review",
    primaryActionLabel: "Open review cohorts",
    primaryActionLocation: {
      state: "review",
      recallTool: "chat",
      reviewFocus: "cohorts",
      sessionId: null,
      loopId: null,
    },
  },
  recall: {
    title: "Recall",
    description:
      "Move between grounded chat, durable memory, and document-backed retrieval without leaving the same work state.",
    context: "Recall is for reconstructing context and evidence, then moving back into execution with less friction.",
    pill: "Recall",
    primaryActionLabel: "Open grounded chat",
    primaryActionLocation: {
      state: "recall",
      recallTool: "chat",
      reviewFocus: null,
      sessionId: null,
      loopId: null,
      workingSetId: null,
    },
  },
  working_set: {
    title: "Working-set session",
    description:
      "Restore a bounded cross-surface context as one dedicated session surface.",
    context:
      "Review the full set, then jump into any member without losing the surrounding context.",
    pill: "Working set",
    primaryActionLabel: "Return home",
    primaryActionLocation: DEFAULT_LOCATION,
  },
};

interface PrioritizedCard {
  priority: number;
  card: OperatorActionCard;
}

type DecisionSessionSnapshot =
  | RelationshipReviewSessionSnapshotResponse
  | EnrichmentReviewSessionSnapshotResponse;

let elements: ShellElements | null = null;
let runtimeDependencies: ShellRuntimeDependencies | null = null;
let currentLocation: ShellLocation = DEFAULT_LOCATION;
let suppressHashChange = false;
let visitBaseline: Date | null = null;
let continuityBaseline: ContinuityBaselineSnapshot | null = null;
let visitStatePersisted = false;
let workspaceLoading = false;
let latestWorkspaceData: WorkspaceData | null = null;
let latestWorkingSets: WorkingSetResponse[] = [];
let workingSetContext: WorkingSetContextResponse | null = null;
let commandPaletteController:
  | ReturnType<typeof bootstrapCommandPalette>
  | null = null;

function createLocation(overrides: ShellLocationInput = {}): ShellLocation {
  return {
    state: overrides.state ?? DEFAULT_LOCATION.state,
    recallTool: overrides.recallTool ?? DEFAULT_LOCATION.recallTool,
    reviewFocus: overrides.reviewFocus ?? DEFAULT_LOCATION.reviewFocus,
    sessionId: overrides.sessionId ?? DEFAULT_LOCATION.sessionId,
    loopId: overrides.loopId ?? DEFAULT_LOCATION.loopId,
    viewId: overrides.viewId ?? null,
    memoryId: overrides.memoryId ?? null,
    workingSetId: overrides.workingSetId ?? null,
    query: overrides.query ?? null,
  };
}

function workingSetSessionLocation(workingSetId: number | null): ShellLocation {
  return createLocation({
    state: "working_set",
    workingSetId,
  });
}

function openLocationAttributes(location: ShellLocation): string {
  const attributes = [
    ["state", location.state],
    ["recall-tool", location.recallTool],
    ["review-focus", location.reviewFocus ?? ""],
    ["session-id", location.sessionId != null ? String(location.sessionId) : ""],
    ["loop-id", location.loopId != null ? String(location.loopId) : ""],
    ["view-id", location.viewId != null ? String(location.viewId) : ""],
    ["memory-id", location.memoryId != null ? String(location.memoryId) : ""],
    ["working-set-id", location.workingSetId != null ? String(location.workingSetId) : ""],
    ["query", location.query ?? ""],
  ] as const;

  return attributes
    .map(([name, value]) => `data-open-${name}="${escapeHtml(value)}"`)
    .join(" ");
}

function requireElement<T extends HTMLElement>(id: string, ctor: { new (): T }): T {
  const element = document.getElementById(id);
  if (!(element instanceof ctor)) {
    throw new Error(`Missing required shell element: ${id}`);
  }
  return element;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function formatRelativeTime(value: string | Date | null | undefined): string {
  const date = value instanceof Date ? value : value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return "unknown time";
  }

  const diffMs = Date.now() - date.getTime();
  const absMs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  let amount: number;
  let unit: string;
  if (absMs < hour) {
    amount = Math.max(1, Math.round(absMs / minute));
    unit = amount === 1 ? "minute" : "minutes";
  } else if (absMs < day) {
    amount = Math.max(1, Math.round(absMs / hour));
    unit = amount === 1 ? "hour" : "hours";
  } else {
    amount = Math.max(1, Math.round(absMs / day));
    unit = amount === 1 ? "day" : "days";
  }

  return `${amount} ${unit} ${diffMs >= 0 ? "ago" : "from now"}`;
}

function loopTitle(loop: { title?: string | null; raw_text: string; id: number }): string {
  return loop.title?.trim() || loop.raw_text.trim() || `Loop #${loop.id}`;
}

function loopPreview(loop: { summary?: string | null; next_action?: string | null; raw_text: string }): string {
  return loop.summary?.trim() || loop.next_action?.trim() || loop.raw_text.trim();
}

function displayElement(element: HTMLElement | null, visible: boolean, display = "grid"): void {
  if (!element) {
    return;
  }
  element.style.display = visible ? display : "none";
}

function buildShellElements(): ShellElements {
  return {
    operatorMain: requireElement("operator-main", HTMLElement),
    inboxMain: requireElement("inbox-main", HTMLElement),
    nextMain: requireElement("next-main", HTMLElement),
    reviewMain: requireElement("review-main", HTMLElement),
    chatMain: requireElement("chat-main", HTMLElement),
    memoryMain: requireElement("memory-main", HTMLElement),
    ragMain: requireElement("rag-main", HTMLElement),
    workingSetMain: requireElement("working-set-main", HTMLElement),
    shellTitle: requireElement("shell-title", HTMLElement),
    shellDescription: requireElement("shell-description", HTMLElement),
    shellContext: requireElement("shell-context", HTMLElement),
    shellRoutePill: requireElement("shell-route-pill", HTMLElement),
    shellLastVisit: requireElement("shell-last-visit", HTMLElement),
    shellPrimaryAction: requireElement("shell-primary-action", HTMLButtonElement),
    refreshWorkspaceButton: requireElement("shell-refresh-workspace-btn", HTMLButtonElement),
    commandPaletteButton: requireElement("shell-command-palette-btn", HTMLButtonElement),
    createWorkingSetButton: requireElement("operator-create-working-set-btn", HTMLButtonElement),
    stateButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("[data-shell-state]")),
    recallSubnav: requireElement("recall-subnav", HTMLElement),
    recallButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("[data-recall-tool]")),
    operatorNow: requireElement("operator-now", HTMLElement),
    operatorDecisions: requireElement("operator-decisions", HTMLElement),
    operatorPlan: requireElement("operator-plan", HTMLElement),
    operatorRecall: requireElement("operator-recall", HTMLElement),
    operatorSinceLast: requireElement("operator-since-last", HTMLElement),
    operatorWorkingSet: requireElement("operator-working-set", HTMLElement),
    workingSetFocusBanner: requireElement("working-set-focus-banner", HTMLElement),
    workingSetFocusSummary: requireElement("working-set-focus-summary", HTMLElement),
    workingSetFocusItems: requireElement("working-set-focus-items", HTMLElement),
    workingSetFocusToggleButton: requireElement("working-set-focus-toggle-btn", HTMLButtonElement),
    workingSetExitFocusButton: requireElement("working-set-exit-focus-btn", HTMLButtonElement),
  };
}

function safeJsonParse<T>(raw: string | null, fallback: T): T {
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function readPersistedLocation(): ShellLocation {
  const stored = safeJsonParse<Partial<ShellLocation>>(
    window.localStorage.getItem(SHELL_LOCATION_STORAGE_KEY),
    {},
  );
  return normalizeLocation(stored);
}

function persistLocation(location: ShellLocation): void {
  window.localStorage.setItem(SHELL_LOCATION_STORAGE_KEY, JSON.stringify(location));
}

async function promptForWorkingSetDetails(
  defaults: { name?: string; description?: string } = {},
): Promise<{ name: string; description: string | null } | null> {
  const result = await modals.promptDialog({
    eyebrow: "Working set",
    title: defaults.name ? "Update working set" : "Create a working set",
    description:
      "Save a bounded cross-surface context so you can resume the exact loops, sessions, and anchors that matter later.",
    confirmLabel: defaults.name ? "Save changes" : "Create set",
    fields: [
      {
        name: "name",
        label: "Name",
        value: defaults.name ?? "",
        required: true,
        maxLength: 120,
        placeholder: "Launch cleanup, hiring pass, weekly reset…",
      },
      {
        name: "description",
        label: "Description",
        type: "textarea",
        rows: 4,
        value: defaults.description ?? "",
        maxLength: 280,
        placeholder: "What bounded slice of the system does this set hold together?",
      },
    ],
    validate(values: Record<string, string>): string | null {
      const name = values["name"]?.trim() ?? "";
      if (!name) {
        return "Name is required.";
      }
      return null;
    },
  });
  if (!result) {
    return null;
  }
  const name = typeof result["name"] === "string" ? result["name"].trim() : "";
  if (!name) {
    return null;
  }
  const descriptionValue = typeof result["description"] === "string" ? result["description"].trim() : "";
  return {
    name,
    description: descriptionValue || null,
  };
}

async function confirmWorkingSetDeletion(name: string): Promise<boolean> {
  return modals.confirmDialog({
    eyebrow: "Working set",
    title: "Delete working set",
    description: `Delete “${name}”? The saved context, ordering, and focus history will be removed.`,
    confirmLabel: "Delete set",
  });
}

async function loadWorkingSetState(): Promise<void> {
  try {
    const [sets, context] = await Promise.all([
      requestJson<WorkingSetResponse[]>("/loops/working-sets", {}, "Failed to load working sets"),
      requestJson<WorkingSetContextResponse>(
        "/loops/working-sets/context",
        {},
        "Failed to load working-set focus state",
      ),
    ]);
    latestWorkingSets = sets;
    workingSetContext = context;
  } catch {
    latestWorkingSets = [];
    workingSetContext = null;
  }
}

async function refreshWorkingSetState(): Promise<void> {
  await loadWorkingSetState();
  if (latestWorkspaceData) {
    renderNowZone(latestWorkspaceData);
    renderDecisionsZone(latestWorkspaceData);
    renderPlanZone(latestWorkspaceData);
    renderRecallZone(latestWorkspaceData);
    renderSinceLastVisit(latestWorkspaceData);
  }
  renderWorkingSet(latestWorkspaceData);
  renderWorkingSetFocusBanner();
  syncFocusModeClass();
  if (currentLocation.state === "working_set") {
    renderWorkingSetSessionSurface();
  }
}

function readLastVisit(): Date | null {
  const raw = window.localStorage.getItem(LAST_VISIT_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function writeLastVisitNow(): void {
  window.localStorage.setItem(LAST_VISIT_STORAGE_KEY, new Date().toISOString());
}

function normalizeLocation(value: ShellLocationInput): ShellLocation {
  const state =
    value.state && ["operator", "capture", "do", "decide", "plan", "review", "recall", "working_set"].includes(value.state)
      ? value.state
      : DEFAULT_LOCATION.state;
  const recallTool =
    value.recallTool && ["chat", "memory", "rag"].includes(value.recallTool)
      ? value.recallTool
      : DEFAULT_LOCATION.recallTool;
  const reviewFocus =
    value.reviewFocus && ["planning", "relationship", "enrichment", "cohorts"].includes(value.reviewFocus)
      ? value.reviewFocus
      : null;
  return {
    state,
    recallTool,
    reviewFocus,
    sessionId: typeof value.sessionId === "number" && Number.isInteger(value.sessionId) ? value.sessionId : null,
    loopId: typeof value.loopId === "number" && Number.isInteger(value.loopId) ? value.loopId : null,
    viewId: typeof value.viewId === "number" && Number.isInteger(value.viewId) ? value.viewId : null,
    memoryId: typeof value.memoryId === "number" && Number.isInteger(value.memoryId) ? value.memoryId : null,
    workingSetId:
      typeof value.workingSetId === "number" && Number.isInteger(value.workingSetId)
        ? value.workingSetId
        : null,
    query: typeof value.query === "string" && value.query.trim() ? value.query.trim() : null,
  };
}

function locationToHash(location: ShellLocation): string {
  switch (location.state) {
    case "operator":
      return "#operator";
    case "capture":
      if (location.viewId != null) {
        return `#capture/view/${location.viewId}`;
      }
      if (location.query) {
        return `#capture/query/${encodeURIComponent(location.query)}`;
      }
      return "#capture";
    case "do":
      if (location.loopId != null) {
        return `#do/loop/${location.loopId}`;
      }
      if (location.query) {
        return `#do/query/${encodeURIComponent(location.query)}`;
      }
      return "#do";
    case "decide":
      if (location.reviewFocus && location.sessionId != null) {
        return `#decide/${location.reviewFocus}/${location.sessionId}`;
      }
      if (location.reviewFocus) {
        return `#decide/${location.reviewFocus}`;
      }
      return "#decide";
    case "plan":
      return location.sessionId != null ? `#plan/session/${location.sessionId}` : "#plan";
    case "review":
      return location.query ? `#review/query/${encodeURIComponent(location.query)}` : "#review";
    case "recall":
      if (location.recallTool === "memory" && location.memoryId != null) {
        return `#recall/memory/${location.memoryId}`;
      }
      if (location.query) {
        return `#recall/${location.recallTool}/query/${encodeURIComponent(location.query)}`;
      }
      return `#recall/${location.recallTool}`;
    case "working_set":
      return location.workingSetId != null ? `#working-set/${location.workingSetId}` : "#working-set";
  }
}

function parseHash(hash: string): ShellLocation | null {
  const cleaned = hash.replace(/^#/, "").trim();
  if (!cleaned) {
    return null;
  }
  const parts = cleaned.split("/").filter(Boolean);
  const [first, second, third] = parts;

  switch (first) {
    case "operator":
      return DEFAULT_LOCATION;
    case "capture":
      if (second === "view" && third) {
        return createLocation({ state: "capture", viewId: Number.parseInt(third, 10) || null });
      }
      if (second === "query" && third) {
        return createLocation({ state: "capture", query: decodeURIComponent(third) });
      }
      return createLocation({ state: "capture" });
    case "do":
      if (second === "loop" && third) {
        return createLocation({ state: "do", loopId: Number.parseInt(third, 10) || null });
      }
      if (second === "query" && third) {
        return createLocation({ state: "do", query: decodeURIComponent(third) });
      }
      return createLocation({ state: "do" });
    case "decide": {
      const focus = second && ["relationship", "enrichment", "cohorts"].includes(second)
        ? (second as ReviewFocus)
        : null;
      return createLocation({
        state: "decide",
        reviewFocus: focus,
        sessionId: focus && third ? Number.parseInt(third, 10) || null : null,
      });
    }
    case "plan":
      return createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: second === "session" && third ? Number.parseInt(third, 10) || null : null,
      });
    case "review":
      if (second === "query" && third) {
        return createLocation({ state: "review", reviewFocus: "cohorts", query: decodeURIComponent(third) });
      }
      return createLocation({ state: "review", reviewFocus: "cohorts" });
    case "recall": {
      const recallTool =
        second && ["chat", "memory", "rag"].includes(second)
          ? (second as RecallTool)
          : DEFAULT_LOCATION.recallTool;
      return createLocation({
        state: "recall",
        recallTool,
        memoryId: second === "memory" && third && parts[3] !== "query" ? Number.parseInt(third, 10) || null : null,
        query: parts[2] === "query" && parts[3] ? decodeURIComponent(parts[3]) : null,
      });
    }
    case "working-set":
      return createLocation({
        state: "working_set",
        workingSetId: second ? Number.parseInt(second, 10) || null : null,
      });
    default:
      return null;
  }
}

function updateShellHeader(location: ShellLocation): void {
  if (!elements) {
    return;
  }
  const descriptor = STATE_DESCRIPTORS[location.state];
  elements.shellTitle.textContent = descriptor.title;
  elements.shellDescription.textContent = descriptor.description;
  elements.shellContext.textContent = descriptor.context;
  elements.shellRoutePill.textContent = descriptor.pill;
  elements.shellPrimaryAction.textContent = descriptor.primaryActionLabel;
  elements.shellPrimaryAction.dataset["primaryState"] = descriptor.primaryActionLocation.state;
  elements.shellPrimaryAction.dataset["primaryRecallTool"] = descriptor.primaryActionLocation.recallTool;
  elements.shellPrimaryAction.dataset["primaryReviewFocus"] = descriptor.primaryActionLocation.reviewFocus ?? "";
  elements.shellPrimaryAction.dataset["primarySessionId"] =
    descriptor.primaryActionLocation.sessionId != null
      ? String(descriptor.primaryActionLocation.sessionId)
      : "";
  elements.shellPrimaryAction.dataset["primaryLoopId"] =
    descriptor.primaryActionLocation.loopId != null ? String(descriptor.primaryActionLocation.loopId) : "";
  elements.shellPrimaryAction.dataset["primaryViewId"] =
    descriptor.primaryActionLocation.viewId != null ? String(descriptor.primaryActionLocation.viewId) : "";
  elements.shellPrimaryAction.dataset["primaryMemoryId"] =
    descriptor.primaryActionLocation.memoryId != null ? String(descriptor.primaryActionLocation.memoryId) : "";
  elements.shellPrimaryAction.dataset["primaryWorkingSetId"] =
    descriptor.primaryActionLocation.workingSetId != null ? String(descriptor.primaryActionLocation.workingSetId) : "";
  elements.shellPrimaryAction.dataset["primaryQuery"] = descriptor.primaryActionLocation.query ?? "";
}

function syncNavState(location: ShellLocation): void {
  if (!elements) {
    return;
  }
  elements.stateButtons.forEach((button) => {
    const isActive = button.dataset["shellState"] === location.state;
    button.classList.toggle("active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });

  const showRecallSubnav = location.state === "recall";
  elements.recallSubnav.hidden = !showRecallSubnav;
  elements.recallButtons.forEach((button) => {
    const isActive = button.dataset["recallTool"] === location.recallTool;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function syncVisiblePanels(location: ShellLocation): void {
  if (!elements) {
    return;
  }

  displayElement(elements.operatorMain, location.state === "operator", "grid");
  displayElement(elements.inboxMain, location.state === "capture", "grid");
  displayElement(elements.nextMain, location.state === "do", "grid");
  displayElement(
    elements.reviewMain,
    location.state === "decide" || location.state === "plan" || location.state === "review",
    "grid",
  );
  displayElement(elements.chatMain, location.state === "recall" && location.recallTool === "chat", "grid");
  displayElement(
    elements.memoryMain,
    location.state === "recall" && location.recallTool === "memory",
    "grid",
  );
  displayElement(elements.ragMain, location.state === "recall" && location.recallTool === "rag", "grid");
  displayElement(elements.workingSetMain, location.state === "working_set", "grid");
}

async function activateOwnedSurface(location: ShellLocation): Promise<void> {
  if (!runtimeDependencies) {
    return;
  }

  const contract = contractFromLocation(location);
  if (!contract) {
    return;
  }

  await runtimeDependencies.surfaces.activate(contract);
}

function clearReviewFocusClasses(): void {
  const panels = document.querySelectorAll<HTMLElement>(
    ".planning-review-panel, .relationship-review-panel, .enrichment-review-panel, .bulk-enrichment-panel, #review-cohorts",
  );
  panels.forEach((panel) => panel.classList.remove("is-shell-focus"));
}

function getReviewFocusElement(focus: ReviewFocus | null): HTMLElement | null {
  const redesignedShell = document.getElementById("review-redesign-shell");
  if (redesignedShell) {
    return redesignedShell;
  }

  switch (focus) {
    case "planning":
      return document.querySelector<HTMLElement>(".planning-review-panel");
    case "relationship":
      return document.querySelector<HTMLElement>(".relationship-review-panel");
    case "enrichment":
      return document.querySelector<HTMLElement>(".enrichment-review-panel");
    case "cohorts":
      return document.getElementById("review-cohorts");
    default:
      return null;
  }
}

function emphasizeElement(element: HTMLElement | null): void {
  if (!element) {
    return;
  }
  element.classList.remove(HIGHLIGHT_CLASS);
  void element.offsetWidth;
  element.classList.add(HIGHLIGHT_CLASS);
  window.setTimeout(() => element.classList.remove(HIGHLIGHT_CLASS), 2200);
}

function focusReviewPanel(location: ShellLocation): void {
  clearReviewFocusClasses();
  const panel = getReviewFocusElement(location.reviewFocus);
  if (!panel) {
    return;
  }
  panel.classList.add("is-shell-focus");
  panel.scrollIntoView({ block: "start", behavior: "smooth" });
  emphasizeElement(panel);
}

function waitForCondition(predicate: () => boolean, attempts = 24, delayMs = 120): Promise<boolean> {
  return new Promise((resolve) => {
    let remaining = attempts;
    const tick = () => {
      if (predicate()) {
        resolve(true);
        return;
      }
      remaining -= 1;
      if (remaining <= 0) {
        resolve(false);
        return;
      }
      window.setTimeout(tick, delayMs);
    };
    tick();
  });
}

async function focusLoopCard(loopId: number): Promise<void> {
  const found = await waitForCondition(() => {
    return document.querySelector(`[data-loop-id="${loopId}"]`) instanceof HTMLElement;
  });
  if (!found) {
    return;
  }

  const cards = Array.from(document.querySelectorAll<HTMLElement>("[data-loop-id]"));
  const card = document.querySelector<HTMLElement>(`[data-loop-id="${loopId}"]`);
  cards.forEach((candidate) => {
    candidate.classList.toggle("shell-focus-hidden", candidate !== card && Boolean(workingSetContext?.focus_mode_enabled));
  });
  if (!card) {
    return;
  }
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  emphasizeElement(card);
}

async function selectViewFilter(viewId: number | null): Promise<void> {
  if (viewId == null) {
    return;
  }
  const available = await waitForCondition(() => {
    const select = document.getElementById("view-filter");
    return select instanceof HTMLSelectElement && select.options.length >= 1;
  });
  if (!available) {
    return;
  }
  const select = document.getElementById("view-filter");
  if (!(select instanceof HTMLSelectElement)) {
    return;
  }
  select.value = String(viewId);
  select.dispatchEvent(new Event("change", { bubbles: true }));
  emphasizeElement(select);
}

async function applyQueryAnchor(state: ShellState, query: string | null): Promise<void> {
  if (!query) {
    return;
  }
  const inputId =
    state === "review"
      ? "review-bulk-enrich-query"
      : state === "do"
        ? "do-query-filter"
        : "query-filter";
  const available = await waitForCondition(() => {
    const input = document.getElementById(inputId);
    return input instanceof HTMLInputElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById(inputId);
  if (!(input instanceof HTMLInputElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  if (state !== "review") {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
  emphasizeElement(input);
}

async function focusMemoryEntry(memoryId: number | null): Promise<void> {
  if (memoryId == null) {
    return;
  }
  const found = await waitForCondition(() => {
    return document.querySelector(`[data-memory-id="${memoryId}"]`) instanceof HTMLElement;
  });
  if (!found) {
    return;
  }
  const card = document.querySelector<HTMLElement>(`[data-memory-id="${memoryId}"]`);
  if (!card) {
    return;
  }
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  emphasizeElement(card);
}

async function runMemorySearchSurface(query: string | null): Promise<void> {
  if (!query) {
    return;
  }
  const available = await waitForCondition(() => {
    return document.getElementById("memory-query") instanceof HTMLInputElement
      && document.getElementById("memory-filter-form") instanceof HTMLFormElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById("memory-query");
  const form = document.getElementById("memory-filter-form");
  if (!(input instanceof HTMLInputElement) || !(form instanceof HTMLFormElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  form.requestSubmit();
  emphasizeElement(input);
}

async function runDocumentAskSurface(query: string | null): Promise<void> {
  if (!query) {
    return;
  }
  const available = await waitForCondition(() => {
    return document.getElementById("rag-input") instanceof HTMLInputElement
      && document.getElementById("rag-form") instanceof HTMLFormElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById("rag-input");
  const form = document.getElementById("rag-form");
  if (!(input instanceof HTMLInputElement) || !(form instanceof HTMLFormElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  form.requestSubmit();
  emphasizeElement(input);
}

async function askGroundedChatSurface(query: string): Promise<void> {
  const available = await waitForCondition(() => {
    return document.getElementById("chat-input") instanceof HTMLInputElement
      && document.getElementById("chat-form") instanceof HTMLFormElement;
  });
  if (!available) {
    return;
  }
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  if (!(input instanceof HTMLInputElement) || !(form instanceof HTMLFormElement)) {
    return;
  }
  input.value = query;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  form.requestSubmit();
  emphasizeElement(input);
}

async function selectReviewSession(focus: ReviewFocus | null, sessionId: number | null): Promise<void> {
  if (focus) {
    window.dispatchEvent(
      new CustomEvent(REVIEW_FOCUS_EVENT, {
        detail: { focus, sessionId },
      }),
    );
  }

  if (sessionId == null) {
    return;
  }

  const selectId =
    focus === "planning"
      ? "review-shell-planning-session-select"
      : focus === "relationship"
        ? "review-shell-relationship-session-select"
        : focus === "enrichment"
          ? "review-shell-enrichment-session-select"
          : null;

  if (!selectId) {
    return;
  }

  const available = await waitForCondition(() => {
    const select = document.getElementById(selectId);
    return select instanceof HTMLSelectElement && select.options.length > 1;
  });
  if (!available) {
    return;
  }

  const select = document.getElementById(selectId);
  if (!(select instanceof HTMLSelectElement)) {
    return;
  }
  select.value = String(sessionId);
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function updateLastVisitStatus(): void {
  if (!elements) {
    return;
  }
  if (!visitBaseline) {
    elements.shellLastVisit.textContent = "First visit in this browser. The workspace is showing a calm current-state overview.";
    return;
  }
  elements.shellLastVisit.textContent = `Last visit ${formatRelativeTime(visitBaseline)} · ${formatTimestamp(
    visitBaseline.toISOString(),
  )}`;
}

function launchSurfaceToLocation(surface: PlanningExecutionLaunchSurfaceResponse): ShellLocation | null {
  const webValue = surface.web;
  const web = webValue && typeof webValue === "object" ? webValue : null;
  const reviewKind = typeof web?.["review_kind"] === "string" ? web["review_kind"] : null;
  const sessionIdRaw = web?.["session_id"];
  const sessionId = typeof sessionIdRaw === "number" ? sessionIdRaw : null;

  if (web?.["surface"] === "review_session" && reviewKind === "relationship") {
    return createLocation({ state: "decide", reviewFocus: "relationship", sessionId });
  }
  if (web?.["surface"] === "review_session" && reviewKind === "enrichment") {
    return createLocation({ state: "decide", reviewFocus: "enrichment", sessionId });
  }
  return null;
}

function workingSetItemLocation(item: WorkingSetItemResponse): ShellLocation {
  const launch = item.launch;
  return createLocation({
    state: launch.state,
    recallTool: launch.recall_tool,
    reviewFocus: launch.review_focus,
    sessionId: launch.session_id,
    loopId: launch.loop_id,
    viewId: launch.view_id,
    memoryId: launch.memory_id,
    workingSetId: launch.working_set_id,
    query: launch.query,
  });
}

function focusModeActiveSet(): WorkingSetResponse | null {
  return workingSetContext?.active_working_set ?? null;
}

function workingSetFromLocation(location: ShellLocation): WorkingSetResponse | null {
  const requestedId =
    location.state === "working_set"
      ? (location.workingSetId ?? workingSetContext?.active_working_set_id ?? null)
      : null;
  if (requestedId == null) {
    return null;
  }
  return latestWorkingSets.find((set) => set.id === requestedId)
    ?? (workingSetContext?.active_working_set_id === requestedId ? workingSetContext.active_working_set : null)
    ?? null;
}

function renderWorkingSetItemCard(workingSetId: number, item: WorkingSetItemResponse): string {
  const location = workingSetItemLocation(item);
  return `
    <article class="working-set-item-card${item.missing ? " working-set-item-card--missing" : ""}">
      <div class="working-set-card-header">
        <div>
          <p class="support-eyebrow">${escapeHtml(item.kind_label)}</p>
          <h4>${escapeHtml(item.label)}</h4>
          <p>${escapeHtml(item.description)}</p>
        </div>
        <span class="operator-chip">${escapeHtml(item.missing ? "Missing" : item.status_label ?? "Ready")}</span>
      </div>
      <div class="operator-card-actions">
        <button type="button" ${openLocationAttributes(location)}>Open</button>
        <button class="secondary" type="button" data-working-set-move="${workingSetId}:${item.id}:up">Earlier</button>
        <button class="secondary" type="button" data-working-set-move="${workingSetId}:${item.id}:down">Later</button>
        <button class="secondary" type="button" data-remove-working-set-item="${workingSetId}:${item.id}">Remove</button>
      </div>
    </article>
  `;
}

function renderWorkingSetSessionSurface(): void {
  if (!elements) {
    return;
  }

  const workingSet = workingSetFromLocation(currentLocation);
  if (!workingSet) {
    elements.workingSetMain.innerHTML = `
      <section class="working-set-session-hero">
        <p class="operator-empty">This working-set session is no longer available. Return home and choose another working set.</p>
        <div class="operator-inline-actions">
          <button type="button" data-open-state="operator">Return home</button>
        </div>
      </section>
    `;
    return;
  }

  const focusEnabled =
    Boolean(workingSetContext?.focus_mode_enabled)
    && workingSetContext?.active_working_set_id === workingSet.id;
  const firstLaunchable = (workingSet.items ?? []).find((item) => !item.missing)
    ?? workingSet.items?.[0]
    ?? null;

  elements.workingSetMain.innerHTML = `
    <section class="working-set-session-hero panel">
      <div class="working-set-card-header">
        <div>
          <p class="support-eyebrow">Working-set session</p>
          <h2>${escapeHtml(workingSet.name)}</h2>
          <p>${escapeHtml(workingSet.description ?? "Saved bounded cross-surface context.")}</p>
        </div>
        <div class="operator-chip-row">
          <span class="operator-chip">${workingSet.item_count} item${workingSet.item_count === 1 ? "" : "s"}</span>
          ${workingSet.missing_item_count ? `<span class="operator-chip">${workingSet.missing_item_count} missing</span>` : ""}
          ${focusEnabled ? '<span class="operator-chip">Focus mode</span>' : '<span class="operator-chip">Session</span>'}
        </div>
      </div>
      <div class="operator-card-actions">
        <button type="button" data-working-set-focus="${workingSet.id}">${focusEnabled ? "Pause focus mode" : "Enter focus mode"}</button>
        ${
          firstLaunchable
            ? `<button class="secondary" type="button" ${openLocationAttributes(workingSetItemLocation(firstLaunchable))}>Open first item</button>`
            : ""
        }
        <button class="secondary" type="button" data-open-state="operator">Return home</button>
      </div>
    </section>

    <section class="working-set-session-list panel">
      <div class="working-set-card-header">
        <div>
          <p class="support-eyebrow">Ordered context</p>
          <h3>All anchors</h3>
          <p>Launch any member without losing the rest of the working set.</p>
        </div>
      </div>
      <div class="working-set-item-grid">
        ${
          (workingSet.items ?? []).length
            ? (workingSet.items ?? []).map((item) => renderWorkingSetItemCard(workingSet.id, item)).join("")
            : '<p class="operator-empty">This working set is empty. Pin loops, sessions, views, or anchors to make it resumable.</p>'
        }
      </div>
    </section>
  `;
}

function renderWorkingSetFocusBanner(): void {
  if (!elements) {
    return;
  }
  const activeSet = focusModeActiveSet();
  const focusEnabled = Boolean(workingSetContext?.focus_mode_enabled && activeSet);
  elements.workingSetFocusBanner.hidden = !activeSet;
  if (!activeSet) {
    elements.workingSetFocusSummary.innerHTML = "";
    elements.workingSetFocusItems.innerHTML = "";
    return;
  }
  elements.workingSetFocusToggleButton.textContent = focusEnabled ? "Pause focus mode" : "Enter focus mode";
  elements.workingSetFocusSummary.innerHTML = `
    <div>
      <p class="support-eyebrow">${focusEnabled ? "Focus mode" : "Active working set"}</p>
      <h2>${escapeHtml(activeSet.name)}</h2>
      <p>${escapeHtml(activeSet.description ?? "A saved bounded slice of loops, sessions, and anchors.")}</p>
    </div>
    <div class="working-set-focus-meta">
      <span class="operator-chip">${activeSet.item_count} item${activeSet.item_count === 1 ? "" : "s"}</span>
      ${activeSet.missing_item_count ? `<span class="operator-chip">${activeSet.missing_item_count} missing</span>` : ""}
      ${activeSet.last_activated_at_utc ? `<span class="support-status">Resumed ${escapeHtml(formatRelativeTime(activeSet.last_activated_at_utc))}</span>` : ""}
    </div>
  `;
  const activeItems = activeSet.items ?? [];
  elements.workingSetFocusItems.innerHTML = activeItems.length
    ? activeItems.slice(0, 4).map((item) => renderWorkingSetItemCard(activeSet.id, item)).join("")
    : '<p class="operator-empty">This working set is empty. Pin a loop, session, or anchor to make focus mode useful.</p>';
}

function syncFocusModeClass(): void {
  const enabled = Boolean(workingSetContext?.focus_mode_enabled && workingSetContext.active_working_set);
  document.body.classList.toggle("shell-focus-mode", enabled);
}

function renderWorkingSet(_data: WorkspaceData | null): void {
  if (!elements) {
    return;
  }

  if (!latestWorkingSets.length) {
    elements.operatorWorkingSet.innerHTML = `
      <p class="operator-empty">Save a bounded slice of loops, sessions, and anchors so you can resume the exact operational context later.</p>
      <div class="operator-inline-actions">
        <button type="button" id="operator-working-set-empty-create" data-working-set-create>Build your first working set</button>
      </div>
    `;
    return;
  }

  const activeId = workingSetContext?.active_working_set_id ?? null;
  elements.operatorWorkingSet.innerHTML = latestWorkingSets
    .map((set) => {
      const isActive = activeId === set.id;
      const isFocused = isActive && Boolean(workingSetContext?.focus_mode_enabled);
      const setItems = set.items ?? [];
      return `
        <article class="working-set-card${isActive ? " working-set-card--active" : ""}">
          <div class="working-set-card-header">
            <div>
              <h3>${escapeHtml(set.name)}</h3>
              <p>${escapeHtml(set.description ?? "Saved cross-surface operator context.")}</p>
            </div>
            <div class="operator-chip-row">
              <span class="operator-chip">${set.item_count} item${set.item_count === 1 ? "" : "s"}</span>
              ${set.missing_item_count ? `<span class="operator-chip">${set.missing_item_count} missing</span>` : ""}
              ${isFocused ? '<span class="operator-chip">Focus</span>' : isActive ? '<span class="operator-chip">Active</span>' : ""}
            </div>
          </div>
          <div class="working-set-item-grid">
            ${setItems.length
              ? setItems.slice(0, 3).map((item) => renderWorkingSetItemCard(set.id, item)).join("")
              : '<p class="operator-empty">This set is empty. Add a loop, session, or anchor from the operator workspace.</p>'}
          </div>
          <div class="operator-card-actions">
            <button type="button" ${openLocationAttributes(workingSetSessionLocation(set.id))}>${isActive ? "Resume set" : "Open session"}</button>
            <button class="secondary" type="button" data-working-set-focus="${set.id}">${isFocused ? "Pause focus" : "Focus"}</button>
            <button class="secondary" type="button" data-working-set-edit="${set.id}">Rename</button>
            <button class="secondary" type="button" data-working-set-delete="${set.id}">Delete</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function locationsMatch(left: ShellLocationContract, right: ShellLocationContract): boolean {
  return left.state === right.state
    && left.recallTool === right.recallTool
    && left.reviewFocus === right.reviewFocus
    && left.sessionId === right.sessionId
    && left.loopId === right.loopId
    && (left.viewId ?? null) === (right.viewId ?? null)
    && (left.memoryId ?? null) === (right.memoryId ?? null)
    && (left.workingSetId ?? null) === (right.workingSetId ?? null)
    && (left.query ?? null) === (right.query ?? null);
}

function filterCardsForFocus(cards: OperatorActionCard[]): OperatorActionCard[] {
  const activeSet = focusModeActiveSet();
  if (!workingSetContext?.focus_mode_enabled || !activeSet) {
    return cards;
  }
  const focusLocations = (activeSet.items ?? []).map((item) => workingSetItemLocation(item));
  return cards.filter((card) => {
    return card.actions.some((action) => {
      return focusLocations.some((location) => locationsMatch(action.location, location));
    });
  });
}

function buildOpenAction(
  label: string,
  location: ShellLocation,
  description: string,
  variant: OperatorActionCardAction["variant"] = "primary",
): OperatorActionCardAction {
  return {
    type: "open",
    label,
    variant,
    location,
    description,
  };
}

function buildPinAction(
  label: string,
  location: ShellLocation,
  description: string,
  pinLabel?: string,
): OperatorActionCardAction {
  return {
    type: "pin",
    label,
    variant: "secondary",
    location,
    description,
    pinLabel,
  };
}

function buildLocationAction(location: ShellLocation): Omit<RecentShellActionEntry, "occurredAt"> {
  if (location.state === "working_set" && location.workingSetId != null) {
    const workingSet = latestWorkingSets.find((set) => set.id === location.workingSetId)
      ?? (workingSetContext?.active_working_set_id === location.workingSetId ? workingSetContext.active_working_set : null)
      ?? null;
    return {
      kind: "working_set_session",
      label: `Opened working set · ${workingSet?.name ?? `#${location.workingSetId}`}`,
      description: "Opened the dedicated working-set session surface.",
      location,
    };
  }
  if (location.state === "plan" && location.sessionId != null) {
    return {
      kind: "planning",
      label: `Resumed plan #${location.sessionId}`,
      description: "Opened a saved planning session from the shell.",
      location,
    };
  }
  if (location.state === "decide" && location.sessionId != null) {
    return {
      kind: "review",
      label: `Opened ${location.reviewFocus ?? "review"} queue #${location.sessionId}`,
      description: "Opened a saved review session from the shell.",
      location,
    };
  }
  if (location.state === "recall") {
    return {
      kind: "recall",
      label: `Opened recall · ${location.recallTool}`,
      description: "Moved into a recall surface.",
      location,
    };
  }
  return {
    kind: "navigation",
    label: `Opened ${location.state}`,
    description: "Navigated within the operator shell.",
    location,
  };
}

function rememberLocationAnchor(location: ShellLocation): void {
  if (location.state === "plan" && location.sessionId != null) {
    rememberPlanningAnchor(location.sessionId);
    return;
  }
  if (
    location.state === "decide"
    && location.sessionId != null
    && (location.reviewFocus === "relationship" || location.reviewFocus === "enrichment")
  ) {
    rememberReviewAnchor(location.reviewFocus, location.sessionId);
  }
}

function summarizeFollowUpResources(resources: PlanningExecutionFollowUpResourceResponse[] | undefined): string[] {
  return (resources ?? []).slice(0, 3).map((resource) => {
    return `${resource.label || `${resource.resource_type} #${resource.resource_id}`}: ${resource.operation_summary}`;
  });
}

function summarizeRollbackCue(cues: PlanningExecutionRollbackCueResponse | null | undefined): string {
  if (!cues) {
    return "Rollback information is not available.";
  }
  if (cues.undoable_operation_count > 0) {
    return `${cues.undoable_operation_count} operation${cues.undoable_operation_count === 1 ? "" : "s"} are directly undoable.`;
  }
  if (cues.rollback_supported_operation_count > 0) {
    return `${cues.rollback_supported_operation_count} operation${cues.rollback_supported_operation_count === 1 ? "" : "s"} include guided rollback cues.`;
  }
  return "No explicit rollback path was captured for this execution.";
}

function formatChangedFieldLabel(field: string): string {
  return field.replaceAll("_", " ");
}

function recentPlanningExecutions(data: WorkspaceData): PlanningExecutionHistoryItemResponse[] {
  if (!visitBaseline) {
    return [];
  }
  const baselineTime = visitBaseline.getTime();
  return (data.planningSnapshot?.execution_history ?? []).filter((item) => {
    return Date.parse(item.executed_at_utc) > baselineTime;
  });
}

function buildPlanningReplacementCue(
  baseline: NonNullable<ContinuityBaselineSnapshot["planningSession"]>,
  current: PlanningSessionSnapshotResponse,
): { summary: string; detail: string; overlapLabel: string } {
  const previousName = baseline.sessionName || `Plan #${baseline.sessionId}`;
  const baselineTargetIds = baseline.targetLoopIds ?? [];
  const currentTargetIds = new Set((current.target_loops ?? []).map((loop) => loop.id));
  const overlapCount = baselineTargetIds.filter((loopId) => currentTargetIds.has(loopId)).length;
  const overlapLabel = `${overlapCount}/${Math.max(baselineTargetIds.length, current.target_loops?.length ?? 0, 1)} overlapping targets`;

  if (baseline.status === "completed") {
    return {
      summary: `${current.session.name} replaced the completed plan you last saw.`,
      detail: overlapLabel,
      overlapLabel,
    };
  }
  if (overlapCount === 0) {
    return {
      summary: `${current.session.name} targets a different slice of work than ${previousName}.`,
      detail: "No prior target loops overlap",
      overlapLabel,
    };
  }
  if (overlapCount < baselineTargetIds.length) {
    return {
      summary: `${current.session.name} partially overlaps ${previousName} while refreshing the work mix.`,
      detail: overlapLabel,
      overlapLabel,
    };
  }
  return {
    summary: `${current.session.name} is a newer grounded version of ${previousName}.`,
    detail: overlapLabel,
    overlapLabel,
  };
}

function relationCandidateLabel(candidate: RelationshipReviewCandidateResponse | null): string {
  if (!candidate) {
    return "No candidate preview available";
  }
  return `${loopTitle(candidate)} · ${Math.round(candidate.score * 100)}% similarity`;
}

function suggestionFieldSummary(suggestion: SuggestionResponse | null): string {
  if (!suggestion || typeof suggestion.parsed !== "object" || suggestion.parsed === null) {
    return "No structured suggestion preview available";
  }
  const keys = Object.keys(suggestion.parsed);
  return keys.length ? `Suggests ${keys.join(", ")}` : "No parsed fields surfaced";
}

function clarificationLabel(clarification: ClarificationResponse | null): string {
  if (!clarification) {
    return "No clarification preview available";
  }
  return clarification.question;
}

function buildNowCards(data: WorkspaceData): OperatorActionCard[] {
  const buckets: Array<{ label: string; tone: OperatorActionCard["tone"]; items: LoopResponse[] }> = [
    { label: "Due soon", tone: "attention", items: data.nextLoops.due_soon },
    { label: "Quick wins", tone: "progress", items: data.nextLoops.quick_wins },
    { label: "High leverage", tone: "progress", items: data.nextLoops.high_leverage },
    { label: "Standard", tone: "neutral", items: data.nextLoops.standard },
  ];

  return buckets.flatMap((bucket) => {
    return bucket.items.slice(0, 2).map((loop) => {
      const location = createLocation({ state: "do", loopId: loop.id });
      const dueMeta =
        loop.due_at_utc || loop.due_date
          ? `Due ${formatRelativeTime(loop.due_at_utc ?? loop.due_date ?? null)}`
          : "No due date";
      const nextStep = loop.next_action?.trim() || "Open the loop to choose the next concrete move.";
      return {
        id: `now-${bucket.label}-${loop.id}`,
        kind: "mutation",
        tone: bucket.tone,
        eyebrow: bucket.label,
        title: loopTitle(loop),
        summary: loopPreview(loop),
        rationale:
          bucket.label === "Due soon"
            ? "This loop is surfacing because timing pressure is higher than the rest of the queue."
            : bucket.label === "Quick wins"
              ? "This loop looks easy to move quickly, so it is a strong momentum candidate."
              : bucket.label === "High leverage"
                ? "This loop appears to unlock outsized value relative to the rest of the queue."
                : "This loop is ready enough to work without waiting on additional system preparation.",
        preview: [
          { label: "Loop", value: loopTitle(loop) },
          { label: "Status", value: loop.status },
          { label: "Timing", value: dueMeta },
          { label: "Next step", value: nextStep },
        ],
        trust: {
          contextSources: [
            "Live /loops/next prioritization",
            `Bucket: ${bucket.label}`,
            loop.project ? `Project: ${loop.project}` : "Loop-level prioritization only",
          ],
          assumptions: [
            loop.next_action ? "Existing next action remains valid." : "A new next action may still need operator clarification.",
          ],
          confidenceLabel: bucket.label === "Standard" ? "Ready-work signal" : `${bucket.label} priority signal`,
          rollbackLabel: "This card launches the loop; no mutation happens until you act inside Do.",
          freshnessLabel: `Updated ${formatRelativeTime(loop.updated_at_utc)}`,
        },
        handoff: {
          changeSummary: "Opening this card hands off into the exact loop detail inside the Do workspace.",
          createdResources: [],
          nextStep: "Review the loop, then execute or edit the next action in-context.",
          breadcrumbs: ["Home", "Do", `Loop #${loop.id}`],
        },
        actions: [
          buildOpenAction("Open in Do", location, loopPreview(loop)),
          buildPinAction("Pin for later", location, loopPreview(loop), loopTitle(loop)),
        ],
      } satisfies OperatorActionCard;
    });
  });
}

function buildRelationshipDecisionCard(
  snapshot: RelationshipReviewSessionSnapshotResponse,
): OperatorActionCard | null {
  if (!snapshot.session || snapshot.loop_count <= 0) {
    return null;
  }

  const item = snapshot.current_item ?? snapshot.items[0] ?? null;
  const candidate = item?.duplicate_candidates[0] ?? item?.related_candidates[0] ?? null;
  const location = createLocation({
    state: "decide",
    reviewFocus: "relationship",
    sessionId: snapshot.session.id,
  });

  return {
    id: `relationship-session-${snapshot.session.id}`,
    kind: "decision",
    tone: item?.top_score && item.top_score >= 0.9 ? "attention" : "neutral",
    eyebrow: "Relationship queue",
    title: snapshot.session.name,
    summary: `${snapshot.loop_count} duplicate/related-loop decision${snapshot.loop_count === 1 ? "" : "s"} are waiting in a saved queue.`,
    rationale:
      "This queue preserves your review cursor so you can keep making similarity judgments without rebuilding the candidate set.",
    preview: [
      { label: "Current loop", value: item ? loopTitle(item.loop) : "Queue ready" },
      { label: "Top candidate", value: relationCandidateLabel(candidate) },
      { label: "Queued", value: `${snapshot.loop_count} decision${snapshot.loop_count === 1 ? "" : "s"}` },
      { label: "Cursor", value: snapshot.current_index != null ? `${snapshot.current_index + 1} of ${snapshot.loop_count}` : "Start of queue" },
    ],
    trust: {
      contextSources: [
        `Saved query: ${snapshot.session.query}`,
        `${snapshot.session.relationship_kind} similarity review`,
        item ? `Top score ${Math.round(item.top_score * 100)}%` : "Session-level similarity scan",
      ],
      assumptions: [
        "Human review remains required before any relationship is confirmed or dismissed.",
      ],
      confidenceLabel: item ? `${Math.round(item.top_score * 100)}% top-similarity signal` : "Queue-level review signal",
      rollbackLabel: "No relationship mutation happens until you choose confirm or dismiss inside the queue.",
      freshnessLabel: `Updated ${formatRelativeTime(snapshot.session.updated_at_utc)}`,
    },
    handoff: {
      changeSummary: "Opening this card launches the saved relationship review session at the preserved cursor.",
      createdResources: candidate ? [`Candidate preview: ${relationCandidateLabel(candidate)}`] : [],
      nextStep: "Confirm or dismiss the current duplicate/related recommendation.",
      breadcrumbs: ["Home", "Decide", snapshot.session.name],
    },
    actions: [
      buildOpenAction("Open decision queue", location, `${snapshot.loop_count} relationship decisions queued`),
      buildPinAction("Pin queue", location, `${snapshot.loop_count} relationship decisions queued`, `Decide · ${snapshot.session.name}`),
    ],
  } satisfies OperatorActionCard;
}

function buildEnrichmentDecisionCard(
  snapshot: EnrichmentReviewSessionSnapshotResponse,
): OperatorActionCard | null {
  if (!snapshot.session || snapshot.loop_count <= 0) {
    return null;
  }

  const item = snapshot.current_item ?? snapshot.items[0] ?? null;
  const suggestion = item?.pending_suggestions[0] ?? null;
  const clarification = item?.pending_clarifications[0] ?? null;
  const location = createLocation({
    state: "decide",
    reviewFocus: "enrichment",
    sessionId: snapshot.session.id,
  });

  return {
    id: `enrichment-session-${snapshot.session.id}`,
    kind: "decision",
    tone: item?.pending_clarification_count ? "attention" : "progress",
    eyebrow: "Enrichment queue",
    title: snapshot.session.name,
    summary: `${snapshot.loop_count} enrichment follow-up item${snapshot.loop_count === 1 ? "" : "s"} are ready for apply/reject or clarification answers.`,
    rationale:
      "This queue keeps pending suggestions and clarifications together so you can resolve AI-prepared follow-up work without losing place.",
    preview: [
      { label: "Current loop", value: item ? loopTitle(item.loop) : "Queue ready" },
      { label: "Suggestion", value: suggestionFieldSummary(suggestion) },
      { label: "Clarification", value: clarificationLabel(clarification) },
      {
        label: "Pending",
        value: item
          ? `${item.pending_suggestion_count} suggestion${item.pending_suggestion_count === 1 ? "" : "s"}, ${item.pending_clarification_count} clarification${item.pending_clarification_count === 1 ? "" : "s"}`
          : `${snapshot.loop_count} loop${snapshot.loop_count === 1 ? "" : "s"}`,
      },
    ],
    trust: {
      contextSources: [
        `Saved query: ${snapshot.session.query}`,
        `${snapshot.session.pending_kind} pending enrichment follow-up`,
        suggestion ? `Model: ${suggestion.model}` : "Stored session snapshot",
      ],
      assumptions: [
        "Structured suggestions should be reviewed before being applied to loop state.",
      ],
      confidenceLabel: clarification ? "Needs clarification before high-confidence apply" : "Structured suggestion ready for review",
      rollbackLabel: "Apply/reject choices happen inside the queue, not from this workspace card.",
      freshnessLabel: `Updated ${formatRelativeTime(snapshot.session.updated_at_utc)}`,
    },
    handoff: {
      changeSummary: "Opening this card launches the saved enrichment queue at the preserved cursor.",
      createdResources: [
        suggestion ? suggestionFieldSummary(suggestion) : "Saved enrichment session ready",
        clarification ? `Clarification: ${clarification.question}` : "No clarification preview surfaced",
      ],
      nextStep: "Apply or reject a suggestion, or answer the next clarification.",
      breadcrumbs: ["Home", "Decide", snapshot.session.name],
    },
    actions: [
      buildOpenAction("Open enrichment queue", location, `${snapshot.loop_count} enrichment follow-up items queued`),
      buildPinAction("Pin queue", location, `${snapshot.loop_count} enrichment follow-up items queued`, `Decide · ${snapshot.session.name}`),
    ],
  } satisfies OperatorActionCard;
}

function buildCohortDecisionCard(
  cohort: LoopReviewCohortResponse,
  index: number,
  generatedAtUtc: string,
): OperatorActionCard {
  const topLoop = cohort.items[0] ?? null;
  const location = createLocation({ state: "review", reviewFocus: "cohorts" });
  const cohortLabel = cohort.cohort.replaceAll("_", " ");

  return {
    id: `cohort-${cohort.cohort}-${index}`,
    kind: "decision",
    tone: index === 0 ? "attention" : "neutral",
    eyebrow: "Review cohort",
    title: cohortLabel,
    summary: `${cohort.count} item${cohort.count === 1 ? "" : "s"} need attention in this review cohort.`,
    rationale:
      "This cohort is the fastest way to clean up drift or stale work without scanning the entire system manually.",
    preview: [
      { label: "Cohort", value: cohortLabel },
      { label: "Count", value: `${cohort.count}` },
      { label: "Example", value: topLoop ? loopTitle(topLoop) : "No loop preview available" },
      { label: "Freshness", value: topLoop ? `Updated ${formatRelativeTime(topLoop.updated_at_utc)}` : "Session review" },
    ],
    trust: {
      contextSources: ["/loops/review cohort summary", "State-based hygiene review"],
      assumptions: ["The cohort remains a review signal, not a forced redirect."],
      confidenceLabel: "Cohort-level hygiene signal",
      rollbackLabel: "Opening review cohorts does not mutate data until you act inside Review.",
      freshnessLabel: `Generated ${formatRelativeTime(generatedAtUtc)}`,
    },
    handoff: {
      changeSummary: "Opening this card keeps you inside the broader Review workspace and focuses the cohort area.",
      createdResources: topLoop ? [`Top loop preview: ${loopTitle(topLoop)}`] : [],
      nextStep: "Inspect the cohort and decide which loops need cleanup first.",
      breadcrumbs: ["Home", "Review", cohortLabel],
    },
    actions: [
      buildOpenAction("Open review cohort", location, `${cohort.count} items in ${cohortLabel}`),
      buildPinAction("Pin cohort", location, `${cohort.count} items in ${cohortLabel}`, `Review · ${cohortLabel}`),
    ],
  } satisfies OperatorActionCard;
}

function buildDecisionCards(data: WorkspaceData): OperatorActionCard[] {
  const cards: OperatorActionCard[] = [];
  const relationshipCard = data.relationshipSnapshot ? buildRelationshipDecisionCard(data.relationshipSnapshot) : null;
  const enrichmentCard = data.enrichmentSnapshot ? buildEnrichmentDecisionCard(data.enrichmentSnapshot) : null;
  if (relationshipCard) {
    cards.push(relationshipCard);
  }
  if (enrichmentCard) {
    cards.push(enrichmentCard);
  }

  data.reviewData.daily
    .filter((cohort) => cohort.count > 0)
    .slice(0, 2)
    .forEach((cohort, index) => {
      cards.push(buildCohortDecisionCard(cohort, index, data.reviewData.generated_at_utc));
    });

  return cards;
}

function buildPlanningResumeCard(snapshot: PlanningSessionSnapshotResponse): OperatorActionCard {
  const location = createLocation({
    state: "plan",
    reviewFocus: "planning",
    sessionId: snapshot.session.id,
  });
  const currentCheckpoint = snapshot.current_checkpoint ?? null;
  const currentCheckpointTitle = currentCheckpoint?.title || `Checkpoint ${snapshot.session.current_checkpoint_index + 1}`;
  const targetLoops = snapshot.target_loops ?? [];
  const assumptions = snapshot.assumptions ?? [];
  const sources = snapshot.sources ?? [];
  const targetLoopPreview = targetLoops[0] ?? null;

  return {
    id: `plan-session-${snapshot.session.id}`,
    kind: snapshot.session.status === "completed" ? "refresh" : "handoff",
    tone: snapshot.session.status === "completed" ? "progress" : "attention",
    eyebrow: "Planning session",
    title: snapshot.session.name,
    summary: snapshot.plan_summary,
    rationale:
      "Planning stays durable so you can resume a checkpointed workflow without reconstructing the underlying context by hand.",
    preview: [
      { label: "Status", value: snapshot.session.status.replaceAll("_", " ") },
      { label: "Current checkpoint", value: currentCheckpointTitle },
      { label: "Progress", value: `${snapshot.session.executed_checkpoint_count}/${snapshot.session.checkpoint_count} executed` },
      { label: "Focus loop", value: targetLoopPreview ? loopTitle(targetLoopPreview) : "No focus loop preview available" },
    ],
    trust: {
      contextSources: [
        `${targetLoops.length} target loop${targetLoops.length === 1 ? "" : "s"}`,
        `${assumptions.length} recorded assumption${assumptions.length === 1 ? "" : "s"}`,
        `${sources.length} planning source${sources.length === 1 ? "" : "s"}`,
      ],
      assumptions: assumptions.slice(0, 2),
      confidenceLabel: currentCheckpoint ? `Ready to resume ${currentCheckpoint.title}` : "Planning session available",
      rollbackLabel: "Checkpoint execution records explicit rollback cues whenever supported.",
      freshnessLabel: `Updated ${formatRelativeTime(snapshot.session.updated_at_utc)}`,
    },
    handoff: {
      changeSummary: "Opening this card hands off into the checkpointed planning workspace with the current session selected.",
      createdResources: targetLoops.slice(0, 2).map((loop) => `Focus loop: ${loopTitle(loop)}`),
      nextStep: `Review ${currentCheckpointTitle} and decide whether to execute or refresh the plan.`,
      breadcrumbs: ["Home", "Plan", snapshot.session.name],
    },
    actions: [
      buildOpenAction("Resume plan", location, `Resume ${currentCheckpointTitle}`),
      buildPinAction("Pin plan", location, `Resume ${currentCheckpointTitle}`, `Plan · ${snapshot.session.name}`),
    ],
  } satisfies OperatorActionCard;
}

function buildPlanningExecutionCard(
  snapshot: PlanningSessionSnapshotResponse,
  latestExecution: PlanningExecutionHistoryItemResponse,
): OperatorActionCard {
  const primaryLocation =
    latestExecution.launch_surfaces?.map((surface) => launchSurfaceToLocation(surface)).find((location) => location != null)
    ?? createLocation({ state: "plan", reviewFocus: "planning", sessionId: snapshot.session.id });
  const followUpBits = summarizeFollowUpResources(latestExecution.follow_up_resources);

  return {
    id: `plan-execution-${snapshot.session.id}-${latestExecution.checkpoint_index}`,
    kind: "handoff",
    tone: latestExecution.launch_surfaces?.length ? "attention" : "progress",
    eyebrow: "Latest execution",
    title: latestExecution.checkpoint_title,
    summary: `${latestExecution.operation_count} deterministic result${latestExecution.operation_count === 1 ? "" : "s"} were executed ${formatRelativeTime(latestExecution.executed_at_utc)}.`,
    rationale:
      "Execution cards make downstream consequences explicit so you can move into the next queue without reverse-engineering what changed.",
    preview: [
      { label: "Executed", value: formatTimestamp(latestExecution.executed_at_utc) },
      { label: "Operations", value: `${latestExecution.operation_count}` },
      { label: "Follow-ups", value: followUpBits[0] ?? "No follow-up resources were emitted" },
      {
        label: "Next surface",
        value: latestExecution.launch_surfaces?.[0]?.label || "Resume the planning session",
      },
    ],
    trust: {
      contextSources: [
        "Stored checkpoint execution history",
        `${latestExecution.follow_up_resources?.length ?? 0} follow-up resource${(latestExecution.follow_up_resources?.length ?? 0) === 1 ? "" : "s"}`,
        `${latestExecution.launch_surfaces?.length ?? 0} launch surface${(latestExecution.launch_surfaces?.length ?? 0) === 1 ? "" : "s"}`,
      ],
      assumptions: ["Execution results reflect the latest stored checkpoint payload."],
      confidenceLabel: latestExecution.launch_surfaces?.length ? "A next surface was prepared for immediate launch" : "Execution completed without a downstream queue",
      rollbackLabel: summarizeRollbackCue(latestExecution.rollback_cues),
      freshnessLabel: `Executed ${formatRelativeTime(latestExecution.executed_at_utc)}`,
    },
    handoff: {
      changeSummary: latestExecution.launch_surfaces?.length
        ? "This checkpoint produced downstream work you can launch immediately."
        : "This checkpoint changed state but did not emit a dedicated downstream surface.",
      createdResources: followUpBits,
      nextStep: latestExecution.launch_surfaces?.[0]?.reason || "Inspect the execution history or continue in the plan workspace.",
      breadcrumbs: ["Home", "Plan", snapshot.session.name, latestExecution.checkpoint_title],
    },
    actions: [
      buildOpenAction(
        latestExecution.launch_surfaces?.length ? "Open next surface" : "Resume plan",
        primaryLocation,
        followUpBits[0] ?? latestExecution.checkpoint_title,
      ),
      buildPinAction("Pin handoff", primaryLocation, followUpBits[0] ?? latestExecution.checkpoint_title, latestExecution.launch_surfaces?.[0]?.label || latestExecution.checkpoint_title),
    ],
  } satisfies OperatorActionCard;
}

function buildLaunchSurfaceCard(
  surface: PlanningExecutionLaunchSurfaceResponse,
  latestExecution: PlanningExecutionHistoryItemResponse,
): OperatorActionCard | null {
  const location = launchSurfaceToLocation(surface);
  if (!location) {
    return null;
  }
  const resource = latestExecution.follow_up_resources?.find((item) => item.launch_surface?.resource_id === surface.resource_id) ?? null;
  const reason = surface.reason?.trim() || "Open the next operator surface prepared by the latest checkpoint.";

  return {
    id: `launch-surface-${surface.resource_type}-${surface.resource_id}`,
    kind: "handoff",
    tone: "attention",
    eyebrow: "Prepared handoff",
    title: surface.label,
    summary: reason,
    rationale:
      "Handoff cards exist so you can continue into the exact downstream workflow the checkpoint created, instead of searching for the result manually.",
    preview: [
      { label: "Surface", value: surface.surface },
      { label: "Resource", value: `${surface.resource_type} #${surface.resource_id}` },
      { label: "Operation", value: resource?.operation_summary || "Created by the latest checkpoint" },
      { label: "Role", value: resource?.role || "Next workflow" },
    ],
    trust: {
      contextSources: [
        "Planning launch surface metadata",
        resource ? `Follow-up resource: ${resource.operation_kind}` : "Stored launch surface",
      ],
      assumptions: ["The downstream saved session still exists and is ready to open."],
      confidenceLabel: "Primary next-step recommendation",
      rollbackLabel: summarizeRollbackCue(latestExecution.rollback_cues),
      freshnessLabel: `Prepared ${formatRelativeTime(latestExecution.executed_at_utc)}`,
    },
    handoff: {
      changeSummary: "This execution created a durable downstream surface you can open immediately.",
      createdResources: resource ? [resource.operation_summary] : [],
      nextStep: reason,
      breadcrumbs: ["Home", "Plan", surface.label],
    },
    actions: [
      buildOpenAction("Launch next queue", location, reason),
      buildPinAction("Pin handoff", location, reason, surface.label),
    ],
  } satisfies OperatorActionCard;
}

function buildPlanCards(data: WorkspaceData): OperatorActionCard[] {
  const snapshot = data.planningSnapshot;
  if (!snapshot?.session) {
    return [];
  }

  const cards: OperatorActionCard[] = [buildPlanningResumeCard(snapshot)];
  const latestExecution = snapshot.execution_history?.at(-1) ?? null;
  if (!latestExecution) {
    return cards;
  }

  cards.push(buildPlanningExecutionCard(snapshot, latestExecution));
  latestExecution.launch_surfaces?.forEach((surface) => {
    const launchCard = buildLaunchSurfaceCard(surface, latestExecution);
    if (launchCard) {
      cards.push(launchCard);
    }
  });
  return cards;
}

function buildRecallCards(data: WorkspaceData): OperatorActionCard[] {
  const blockedCount = data.allLoops.filter((loop) => loop.status === "blocked").length;
  const activeDecisionCount =
    (data.relationshipSnapshot?.loop_count ?? 0)
    + (data.enrichmentSnapshot?.loop_count ?? 0);
  const planAssumptions = data.planningSnapshot?.assumptions ?? [];
  const latestExecution = data.planningSnapshot?.execution_history?.at(-1) ?? null;

  const chatLocation = createLocation({ state: "recall", recallTool: "chat" });
  const memoryLocation = createLocation({ state: "recall", recallTool: "memory" });
  const ragLocation = createLocation({ state: "recall", recallTool: "rag" });

  return [
    {
      id: "recall-chat-suggestion",
      kind: "context",
      tone: blockedCount || activeDecisionCount ? "attention" : "neutral",
      eyebrow: "Grounded chat",
      title: "Ask what deserves attention next",
      summary: "Use grounded chat to synthesize real loops, review queues, and recent execution into one operator recommendation.",
      rationale:
        "This is the fastest recall surface when you want a narrative summary backed by the live operator state instead of scanning each queue yourself.",
      preview: [
        { label: "Blocked loops", value: `${blockedCount}` },
        { label: "Active decisions", value: `${activeDecisionCount}` },
        { label: "Planning session", value: data.planningSnapshot?.session?.name || "No active planning session" },
        { label: "Prompt idea", value: "What changed, what is blocked, and what should I do now?" },
      ],
      trust: {
        contextSources: ["Loop context", "Memory context", "Operator workspace state"],
        assumptions: ["Grounded chat stays most useful when loop and memory context remain enabled."],
        confidenceLabel: blockedCount || activeDecisionCount ? "High-value synthesis prompt available" : "General system recap prompt available",
        rollbackLabel: "Opening chat does not mutate anything by itself.",
        freshnessLabel: `Workspace refreshed ${formatRelativeTime(new Date())}`,
      },
      handoff: {
        changeSummary: "This launches the grounded chat thread from the same operator context.",
        createdResources: [],
        nextStep: "Ask for a prioritized summary or a recommended next move.",
        breadcrumbs: ["Home", "Recall", "Grounded chat"],
      },
      actions: [
        buildOpenAction("Open grounded chat", chatLocation, "Ask grounded chat what changed and what matters now"),
        buildPinAction("Pin chat", chatLocation, "Grounded chat for live operator-state synthesis", "Recall · Grounded chat"),
      ],
    },
    {
      id: "recall-memory-suggestion",
      kind: "context",
      tone: planAssumptions.length ? "progress" : "neutral",
      eyebrow: "Memory",
      title: "Review durable memory before the next move",
      summary: "Open Memory when a plan, decision, or conversation depends on durable facts, preferences, or commitments rather than only current loop state.",
      rationale:
        "Memory is the right recall surface when the system's next recommendation should be shaped by stable personal context, not just today’s task graph.",
      preview: [
        { label: "Recorded assumptions", value: planAssumptions[0] || "No active planning assumption preview" },
        { label: "Best use", value: "Preferences, commitments, and durable context" },
        { label: "Active plan", value: data.planningSnapshot?.session?.name || "No active plan" },
      ],
      trust: {
        contextSources: ["Direct memory store", "Planning assumptions", "Operator working context"],
        assumptions: ["Memory entries should capture durable truths, not one-off scratch notes."],
        confidenceLabel: planAssumptions.length ? "Memory can sharpen the next planning/review decision" : "Memory remains available for durable context review",
        rollbackLabel: "Opening Memory is read-first; edits stay explicit inside the Memory workspace.",
        freshnessLabel: null,
      },
      handoff: {
        changeSummary: "This launches the direct-memory workspace without leaving the operator shell model.",
        createdResources: planAssumptions.slice(0, 2),
        nextStep: "Inspect or update durable memory entries that should shape the next workflow.",
        breadcrumbs: ["Home", "Recall", "Memory"],
      },
      actions: [
        buildOpenAction("Open memory", memoryLocation, "Inspect durable memory before the next workflow"),
        buildPinAction("Pin memory", memoryLocation, "Return to durable memory context", "Recall · Memory"),
      ],
    },
    {
      id: "recall-documents-suggestion",
      kind: "context",
      tone: latestExecution?.follow_up_resources?.length ? "progress" : "neutral",
      eyebrow: "Documents",
      title: "Pull in local documents when evidence matters",
      summary: "Use Documents when the next decision depends on notes, playbooks, or other indexed local files that should ground the answer or plan refresh.",
      rationale:
        "Document recall is most useful when a planning step or review decision needs source-backed evidence instead of relying on memory alone.",
      preview: [
        { label: "Latest handoff", value: latestExecution?.launch_surfaces?.[0]?.label || "No active plan-created handoff" },
        { label: "Best use", value: "Policies, notes, manuals, and indexed local references" },
        { label: "Prompt idea", value: "What local docs should inform this next decision?" },
      ],
      trust: {
        contextSources: ["Indexed local documents", "RAG retrieval", "Operator handoff context"],
        assumptions: ["The needed reference material has already been indexed locally."],
        confidenceLabel: latestExecution?.follow_up_resources?.length ? "Useful before executing the next follow-up queue" : "Available whenever evidence-backed recall is needed",
        rollbackLabel: "Opening Documents is non-mutating until you ingest or ask.",
        freshnessLabel: null,
      },
      handoff: {
        changeSummary: "This launches the document-backed recall surface from the same shell.",
        createdResources: latestExecution?.follow_up_resources?.slice(0, 2).map((resource) => resource.label || `${resource.resource_type} #${resource.resource_id}`) ?? [],
        nextStep: "Ask a document-grounded question or index missing local material.",
        breadcrumbs: ["Home", "Recall", "Documents"],
      },
      actions: [
        buildOpenAction("Open documents", ragLocation, "Use document-backed recall for the next decision"),
        buildPinAction("Pin documents", ragLocation, "Return to document-backed recall", "Recall · Documents"),
      ],
    },
  ] satisfies OperatorActionCard[];
}

function buildCompletedSinceLastCard(data: WorkspaceData): PrioritizedCard | null {
  if (!visitBaseline) {
    return null;
  }

  const baselineTime = visitBaseline.getTime();
  const completed = data.allLoops
    .filter((loop) => loop.closed_at_utc && new Date(loop.closed_at_utc).getTime() > baselineTime)
    .sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc))
    .slice(0, 3);
  if (!completed.length) {
    return null;
  }

  const location = createLocation({ state: "do" });
  return {
    priority: 55,
    card: {
      id: "since-last-completed",
      kind: "context",
      tone: "progress",
      eyebrow: "Resume signal",
      title: "Recently completed work",
      summary: `${completed.length} loop${completed.length === 1 ? "" : "s"} completed since your last visit.`,
      rationale:
        "Completion deltas help you re-enter with momentum and understand what is already off the board before you pick the next task.",
      preview: completed.map((loop, index) => ({ label: `Completed ${index + 1}`, value: loopTitle(loop) })),
      trust: {
        contextSources: ["Loop close timestamps", "Last-visit browser baseline"],
        assumptions: ["Browser local storage baseline still reflects your prior visit."],
        confidenceLabel: "Recent completion delta",
        rollbackLabel: "This is informational only; opening Do does not replay completed work.",
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
      },
      handoff: {
        changeSummary: "This recap helps you resume from the updated system state instead of the state you last remember.",
        createdResources: [],
        nextStep: "Open ready work to decide what follows those completions.",
        breadcrumbs: ["Home", "Since last visit", "Completed"],
      },
      actions: [
        buildOpenAction("Open ready work", location, "Review what to do after recent completions"),
        buildPinAction("Pin recap", location, "Resume context after recent completions", "Resume · completed work"),
      ],
    },
  } satisfies PrioritizedCard;
}

function buildBlockedSinceLastCard(data: WorkspaceData): PrioritizedCard | null {
  if (!visitBaseline) {
    return null;
  }

  const baselineTime = visitBaseline.getTime();
  const blocked = data.allLoops
    .filter((loop) => loop.status === "blocked" && new Date(loop.updated_at_utc).getTime() > baselineTime)
    .sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc))
    .slice(0, 3);
  if (!blocked.length) {
    return null;
  }

  const location = createLocation({ state: "review", reviewFocus: "cohorts" });
  return {
    priority: 84,
    card: {
      id: "since-last-blocked",
      kind: "decision",
      tone: "attention",
      eyebrow: "Resume signal",
      title: "Newly blocked work",
      summary: `${blocked.length} loop${blocked.length === 1 ? "" : "s"} became blocked since your last visit.`,
      rationale:
        "Blocked-state drift is a strong review signal because it often changes what should happen next across the rest of the system.",
      preview: blocked.map((loop, index) => ({ label: `Blocked ${index + 1}`, value: loopTitle(loop) })),
      trust: {
        contextSources: ["Loop status changes", "Last-visit browser baseline"],
        assumptions: ["Blocked loops may require either review cleanup or recall/context gathering."],
        confidenceLabel: "High-priority resume risk",
        rollbackLabel: "Opening Review does not mutate loop state until you act.",
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
      },
      handoff: {
        changeSummary: "These loops changed state while you were away, so the Review surface is the safest place to inspect the drift.",
        createdResources: [],
        nextStep: "Open Review or grounded chat to resolve what blocked these loops.",
        breadcrumbs: ["Home", "Since last visit", "Blocked"],
      },
      actions: [
        buildOpenAction("Open review", location, "Inspect newly blocked loops"),
        buildPinAction("Pin blocker recap", location, "Return to newly blocked-loop recap", "Resume · blocked work"),
      ],
    },
  } satisfies PrioritizedCard;
}

function buildFollowUpSinceLastCard(data: WorkspaceData): PrioritizedCard | null {
  if (!visitBaseline) {
    return null;
  }

  const recentExecution = recentPlanningExecutions(data);
  const downstreamGroups = mergePlanningResourceChangeGroups(
    recentExecution.flatMap((item) => item.resource_change_summary?.downstream_groups ?? []),
  );
  const followUpResources = recentExecution
    .flatMap((item) => item.follow_up_resources ?? [])
    .slice(0, 3);

  if (!downstreamGroups.length && !followUpResources.length) {
    return null;
  }

  const launchLocation = recentExecution
    .flatMap((item) => item.launch_surfaces ?? [])
    .map((surface) => launchSurfaceToLocation(surface))
    .find((location) => location != null)
    ?? createLocation({ state: "plan", reviewFocus: "planning", sessionId: data.planningSnapshot?.session?.id ?? null });

  const latestDownstreamSummary = recentExecution.at(-1)?.resource_change_summary?.downstream_summary_label;

  return {
    priority: 80,
    card: {
      id: "since-last-handoffs",
      kind: "handoff",
      tone: "progress",
      eyebrow: "Resume signal",
      title: "Plan-created downstream handoffs",
      summary: latestDownstreamSummary
        ?? `${downstreamGroups.reduce((sum, group) => sum + group.count, 0)} downstream resources were created or updated after your last visit.`,
      rationale:
        "Downstream resources are the clearest sign that planning already prepared the next surface or durable artifact for the operator.",
      preview: followUpResources.length
        ? followUpResources.map((resource, index) => ({
            label: `Follow-up ${index + 1}`,
            value: resource.label || `${resource.resource_type} #${resource.resource_id}`,
          }))
        : buildPlanningResourcePreviewItems(downstreamGroups),
      trust: {
        contextSources: [
          "Planning execution history",
          "Typed downstream resource-change summaries",
          "Last-visit browser baseline",
        ],
        assumptions: ["The downstream resources still exist and remain valid resume targets."],
        confidenceLabel: "Prepared resume handoff",
        rollbackLabel: summarizeRollbackCue(recentExecution.at(-1)?.rollback_cues),
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
      },
      handoff: {
        changeSummary: "Planning execution produced durable follow-up work while you were away.",
        createdResources: downstreamGroups.length
          ? downstreamGroups.map((group) => group.display_label)
          : followUpResources.map((resource) => resource.operation_summary),
        nextStep: "Open the prepared handoff or resume the planning workspace to inspect the execution trail.",
        breadcrumbs: ["Home", "Since last visit", "Planning handoffs"],
      },
      actions: [
        buildOpenAction("Open handoff", launchLocation, "Open the newest downstream planning handoff"),
        buildPinAction("Pin handoff recap", launchLocation, "Return to the latest plan-created handoff recap", "Resume · plan handoffs"),
      ],
    },
  } satisfies PrioritizedCard;
}

type ContinuityCohortName = keyof ContinuityBaselineSnapshot["cohorts"];

function cohortByName(
  reviewData: LoopReviewResponse,
  cohortName: ContinuityCohortName,
): LoopReviewCohortResponse | null {
  return [...reviewData.daily, ...reviewData.weekly].find((item) => item.cohort === cohortName) ?? null;
}

function cohortCountDelta(data: WorkspaceData, cohortName: ContinuityCohortName): number {
  const previousCount = continuityBaseline?.cohorts[cohortName].count ?? 0;
  return (cohortByName(data.reviewData, cohortName)?.count ?? 0) - previousCount;
}

function previewLoopValue(loop: LoopReviewCohortItem | LoopResponse | null | undefined): string {
  return loop ? loopTitle(loop) : "No loop preview available";
}

function planningFreshness(snapshot: PlanningSessionSnapshotResponse | null): {
  isStale: boolean;
  label: string;
  staleTargetLoopCount: number;
  missingTargetLoopCount: number;
  changedTargets: PlanningContextFreshnessTargetChangeResponse[];
  summaryLabel: string;
} {
  const freshness = snapshot?.context_freshness;
  if (!freshness) {
    return {
      isStale: false,
      label: "No planning freshness metadata",
      staleTargetLoopCount: 0,
      missingTargetLoopCount: 0,
      changedTargets: [],
      summaryLabel: "No planning freshness metadata",
    };
  }

  return {
    isStale: freshness.is_stale,
    label: freshness.summary_label
      ?? `Generated ${formatRelativeTime(snapshot?.session.generated_at_utc ?? snapshot?.session.updated_at_utc ?? null)}`,
    staleTargetLoopCount: freshness.stale_target_loop_count,
    missingTargetLoopCount: freshness.missing_target_loop_count,
    changedTargets: freshness.changed_targets ?? [],
    summaryLabel: freshness.summary_label ?? "Planning freshness available",
  };
}

function buildNewlyStaleCard(data: WorkspaceData): PrioritizedCard | null {
  if (!continuityBaseline) {
    return null;
  }

  const staleCohort = cohortByName(data.reviewData, "stale");
  const previousIds = new Set(continuityBaseline.cohorts.stale.itemIds);
  const newlyStale = (staleCohort?.items ?? []).filter((item) => !previousIds.has(item.id));
  const delta = Math.max(0, cohortCountDelta(data, "stale"));
  if (!newlyStale.length && delta <= 0) {
    return null;
  }

  const location = createLocation({ state: "review", reviewFocus: "cohorts" });
  return {
    priority: 82,
    card: {
      id: "since-last-newly-stale",
      kind: "decision",
      tone: "attention",
      eyebrow: "Drift signal",
      title: "Loops aged into stale review",
      summary: `${delta || newlyStale.length} loop${(delta || newlyStale.length) === 1 ? "" : "s"} entered the stale cohort since your last visit.`,
      rationale:
        "Stale loops quietly lose trust. Surfacing newly stale items makes drift visible before it turns into backlog fog.",
      preview: (newlyStale.length ? newlyStale : staleCohort?.items ?? []).slice(0, 3).map((item, index) => ({
        label: `Stale ${index + 1}`,
        value: previewLoopValue(item),
      })),
      trust: {
        contextSources: ["Live review cohorts", "Stored continuity cohort baseline"],
        assumptions: ["Cohort counts stay deterministic across refreshes in the same browser."],
        confidenceLabel: "New stale-work drift detected",
        rollbackLabel: "Opening Review remains non-mutating until you edit or close a loop.",
        freshnessLabel: `Previous stale count ${continuityBaseline.cohorts.stale.count} → ${staleCohort?.count ?? 0}`,
      },
      handoff: {
        changeSummary: "More loops now require stale-work cleanup than when you last visited.",
        createdResources: newlyStale.slice(0, 3).map((item) => previewLoopValue(item)),
        nextStep: "Open Review and decide whether to revive, clarify, or close the newly stale work.",
        breadcrumbs: ["Home", "Since last visit", "Stale drift"],
      },
      actions: [
        buildOpenAction("Open stale review", location, "Review loops that aged into the stale cohort"),
        buildPinAction("Pin stale drift", location, "Return to the stale-drift recap", "Resume · stale drift"),
      ],
    },
  } satisfies PrioritizedCard;
}

function buildRiskCohortCard(data: WorkspaceData): PrioritizedCard | null {
  if (!continuityBaseline) {
    return null;
  }

  const blockedDelta = Math.max(0, data.metrics.blocked_too_long_count - continuityBaseline.metrics.blockedTooLongCount);
  const noNextDelta = Math.max(0, data.metrics.no_next_action_count - continuityBaseline.metrics.noNextActionCount);
  const dueSoonDelta = Math.max(0, cohortCountDelta(data, "due_soon_unplanned"));
  const staleDelta = Math.max(0, data.metrics.stale_open_count - continuityBaseline.metrics.staleOpenCount);
  const changes = [
    blockedDelta ? `${blockedDelta} more blocked-too-long` : null,
    noNextDelta ? `${noNextDelta} more missing next action` : null,
    dueSoonDelta ? `${dueSoonDelta} more due-soon under-planned` : null,
    staleDelta ? `${staleDelta} more stale open` : null,
  ].filter((value): value is string => value != null);
  if (!changes.length) {
    return null;
  }

  const location = createLocation({ state: "review", reviewFocus: "cohorts" });
  return {
    priority: 78,
    card: {
      id: "since-last-risk-cohorts",
      kind: "decision",
      tone: "attention",
      eyebrow: "Risk growth",
      title: "Higher-risk cohorts grew",
      summary: changes.join(" · "),
      rationale:
        "Growth in risk cohorts is a stronger continuity signal than raw backlog size because it changes where cleanup work should start.",
      preview: buildChangedCountPreviewItems([
        {
          label: "Blocked too long",
          previous: continuityBaseline.metrics.blockedTooLongCount,
          current: data.metrics.blocked_too_long_count,
        },
        {
          label: "Missing next action",
          previous: continuityBaseline.metrics.noNextActionCount,
          current: data.metrics.no_next_action_count,
        },
        {
          label: "Due soon under-planned",
          previous: continuityBaseline.cohorts.due_soon_unplanned.count,
          current: cohortByName(data.reviewData, "due_soon_unplanned")?.count ?? 0,
        },
        {
          label: "Stale open",
          previous: continuityBaseline.metrics.staleOpenCount,
          current: data.metrics.stale_open_count,
        },
      ]),
      trust: {
        contextSources: ["/loops/metrics", "/loops/review cohorts", "Stored continuity baseline"],
        assumptions: ["Metric deltas are compared only against the last successful browser-local visit baseline."],
        confidenceLabel: "Deterministic cohort growth",
        rollbackLabel: "This is diagnostic only until you act inside Review or Do.",
        freshnessLabel: `Compared to ${formatTimestamp(continuityBaseline.recordedAtUtc)}`,
      },
      handoff: {
        changeSummary: "The system has more hygiene risk than it did on your last visit.",
        createdResources: changes,
        nextStep: "Open Review and start with the fastest cohort that reduces trust drift.",
        breadcrumbs: ["Home", "Since last visit", "Risk growth"],
      },
      actions: [
        buildOpenAction("Open risk review", location, "Inspect the cohorts that grew since your last visit"),
        buildPinAction("Pin risk recap", location, "Return to the risk-growth recap", "Resume · risk growth"),
      ],
    },
  } satisfies PrioritizedCard;
}

function buildPlanningDriftCard(data: WorkspaceData): PrioritizedCard | null {
  if (!continuityBaseline?.planningSession || !data.planningSnapshot?.session) {
    return null;
  }

  const baseline = continuityBaseline.planningSession;
  const current = data.planningSnapshot;
  const freshness = planningFreshness(current);
  const sameSession = baseline.sessionId === current.session.id;
  const becameStale = freshness.isStale && (!baseline.contextIsStale || !sameSession);
  const movedPrimarySession = !sameSession;
  if (!becameStale && !movedPrimarySession) {
    return null;
  }

  const replacementCue = movedPrimarySession ? buildPlanningReplacementCue(baseline, current) : null;
  const changedTargetPreview = freshness.changedTargets.slice(0, 2).map((target, index) => ({
    label: `Changed target ${index + 1}`,
    value: `${target.label} · ${(target.changed_fields ?? []).map((field) => formatChangedFieldLabel(field)).join(", ")}`,
  }));

  const location = createLocation({
    state: "plan",
    reviewFocus: "planning",
    sessionId: current.session.id,
  });

  return {
    priority: 90,
    card: {
      id: "since-last-planning-drift",
      kind: "handoff",
      tone: freshness.isStale ? "attention" : "neutral",
      eyebrow: "Plan drift",
      title: movedPrimarySession ? "A different planning session became primary" : "Planning context drifted",
      summary: movedPrimarySession
        ? replacementCue?.summary ?? `${current.session.name} replaced the prior planning session.`
        : freshness.summaryLabel,
      rationale:
        "Saved plans are only trustworthy when their grounding still matches the real loop state and the operator still knows why this plan is the active one.",
      preview: [
        { label: "Plan", value: current.session.name },
        {
          label: movedPrimarySession ? "Replacement cue" : "Freshness",
          value: movedPrimarySession
            ? replacementCue?.detail ?? replacementCue?.overlapLabel ?? "Newer planning session"
            : freshness.label,
        },
        ...(changedTargetPreview.length
          ? changedTargetPreview
          : [
              {
                label: "Checkpoint",
                value: current.current_checkpoint?.title || `Checkpoint ${current.session.current_checkpoint_index + 1}`,
              },
            ]),
      ],
      trust: {
        contextSources: [
          "Planning session snapshot",
          "Typed planning context freshness",
          "Stored browser-local planning baseline",
        ],
        assumptions: [
          "Refreshing the plan is the safest next step when target-loop grounding no longer matches current loop state.",
        ],
        confidenceLabel: freshness.isStale ? freshness.summaryLabel : "Primary planning session shifted",
        rollbackLabel: "Opening Plan remains non-mutating until you refresh or execute a checkpoint.",
        freshnessLabel: sameSession
          ? `Previous plan freshness: ${baseline.contextIsStale ? "stale" : "fresh"}`
          : `Previous plan: ${baseline.sessionName || `Plan #${baseline.sessionId}`}`,
      },
      handoff: {
        changeSummary: freshness.isStale
          ? freshness.summaryLabel
          : replacementCue?.summary ?? "The operator-visible primary planning session changed.",
        createdResources: movedPrimarySession
          ? [
              `${baseline.sessionName || `Plan #${baseline.sessionId}`} → ${current.session.name}`,
              replacementCue?.overlapLabel ?? "Target overlap unavailable",
            ]
          : freshness.changedTargets.slice(0, 3).map((target) => {
              return `${target.label}: ${(target.changed_fields ?? []).map((field) => formatChangedFieldLabel(field)).join(", ")}`;
            }),
        nextStep: freshness.isStale
          ? "Open the plan and refresh its context before trusting the next checkpoint."
          : "Open the current plan and confirm it is the right workflow to resume.",
        breadcrumbs: ["Home", "Since last visit", "Planning drift"],
      },
      actions: [
        buildOpenAction(
          freshness.isStale ? "Refresh plan context" : "Open current plan",
          location,
          freshness.label,
        ),
        buildPinAction("Pin planning drift", location, freshness.label, `Plan · ${current.session.name}`),
      ],
    },
  } satisfies PrioritizedCard;
}

function buildPlanningResourceRollupCard(data: WorkspaceData): PrioritizedCard | null {
  if (!visitBaseline) {
    return null;
  }

  const recentExecution = recentPlanningExecutions(data);
  const groupedChanges = mergePlanningResourceChangeGroups(
    recentExecution.flatMap((item) => item.resource_change_summary?.groups ?? []),
  );
  if (!groupedChanges.length) {
    return null;
  }

  const latestSummary = recentExecution.at(-1)?.resource_change_summary?.summary_label;
  const location = createLocation({
    state: "plan",
    reviewFocus: "planning",
    sessionId: data.planningSnapshot?.session?.id ?? null,
  });

  return {
    priority: 81,
    card: {
      id: "since-last-planning-resource-rollup",
      kind: "handoff",
      tone: "progress",
      eyebrow: "Changed resources",
      title: "Planning execution changed durable resources",
      summary: latestSummary
        ?? `${groupedChanges.reduce((sum, group) => sum + group.count, 0)} planning-driven resource changes landed since your last visit.`,
      rationale:
        "Checkpoint execution can mutate loops and create durable objects. A grouped rollup shows the true post-execution state without forcing the operator to reconstruct it manually.",
      preview: buildPlanningResourcePreviewItems(groupedChanges),
      trust: {
        contextSources: [
          "Planning execution history",
          "Typed planning resource-change summaries",
          "Last-visit browser baseline",
        ],
        assumptions: [
          "Planning execution history still reflects the canonical durable mutations created after your last visit.",
        ],
        confidenceLabel: "Grouped planning change rollup",
        rollbackLabel: summarizeRollbackCue(recentExecution.at(-1)?.rollback_cues),
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
        impactSummary: groupedChanges.map((group) => group.display_label).join(" · "),
      },
      handoff: {
        changeSummary: "Planning checkpoints changed real loops and saved resources while you were away.",
        createdResources: groupedChanges.map((group) => group.display_label),
        nextStep: "Open the planning workspace to inspect the execution trail, then launch into the next updated queue or loop.",
        breadcrumbs: ["Home", "Since last visit", "Planning resource changes"],
      },
      actions: [
        buildOpenAction("Open planning activity", location, "Inspect grouped planning-driven resource changes"),
        buildPinAction("Pin resource rollup", location, "Return to the planning resource rollup", "Resume · planning changes"),
      ],
    },
  } satisfies PrioritizedCard;
}

interface GroupedChangeTheme {
  label: string;
  summary: string;
  tone: OperatorActionCard["tone"];
  location: ShellLocation;
}

function buildGroupedChangeRollupCard(data: WorkspaceData): PrioritizedCard | null {
  if (!visitBaseline) {
    return null;
  }

  const themes: GroupedChangeTheme[] = [];

  const planningDrift = buildPlanningDriftCard(data);
  if (planningDrift?.card.actions[0]) {
    themes.push({
      label: "Planning drift",
      summary: planningDrift.card.summary,
      tone: planningDrift.card.tone,
      location: planningDrift.card.actions[0].location,
    });
  }

  const planningResourceRollup = buildPlanningResourceRollupCard(data);
  if (planningResourceRollup?.card.actions[0]) {
    themes.push({
      label: "Planning activity",
      summary: planningResourceRollup.card.summary,
      tone: planningResourceRollup.card.tone,
      location: planningResourceRollup.card.actions[0].location,
    });
  }

  const queueChange = buildQueueChangeCard(data);
  if (queueChange?.card.actions[0]) {
    themes.push({
      label: "Review queues",
      summary: queueChange.card.summary,
      tone: queueChange.card.tone,
      location: queueChange.card.actions[0].location,
    });
  }

  const riskChange = buildRiskCohortCard(data) ?? buildNewlyStaleCard(data) ?? buildBlockedSinceLastCard(data);
  if (riskChange?.card.actions[0]) {
    themes.push({
      label: "Loop risk",
      summary: riskChange.card.summary,
      tone: riskChange.card.tone,
      location: riskChange.card.actions[0].location,
    });
  }

  const completed = buildCompletedSinceLastCard(data);
  if (completed?.card.actions[0]) {
    themes.push({
      label: "Progress",
      summary: completed.card.summary,
      tone: completed.card.tone,
      location: completed.card.actions[0].location,
    });
  }

  if (themes.length < 2) {
    return null;
  }

  const primary = themes.find((theme) => theme.tone === "attention") ?? themes[0] ?? null;
  if (!primary) {
    return null;
  }

  return {
    priority: 88,
    card: {
      id: "since-last-grouped-rollup",
      kind: "context",
      tone: themes.some((theme) => theme.tone === "attention") ? "attention" : "neutral",
      eyebrow: "Change rollup",
      title: "Several change themes landed while you were away",
      summary: `${themes.length} grouped change themes were detected since your last visit.`,
      rationale:
        "When multiple deterministic signals land at once, one grouped rollup helps the operator orient before drilling into specific continuity cards.",
      preview: buildGroupedChangePreviewItems(
        themes.map((theme) => ({ label: theme.label, summary: theme.summary })),
      ),
      trust: {
        contextSources: [
          "Planning continuity signals",
          "Review queue/session deltas",
          "Loop state and completion deltas",
          "Last-visit browser baseline",
        ],
        assumptions: ["A grouped summary is useful only when multiple continuity themes changed."],
        confidenceLabel: "Grouped deterministic continuity rollup",
        rollbackLabel: "This rollup is navigational only; mutations remain explicit in downstream surfaces.",
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
      },
      handoff: {
        changeSummary: "Planning activity, queue shifts, and/or loop-state drift all moved while you were away.",
        createdResources: themes.map((theme) => `${theme.label}: ${theme.summary}`),
        nextStep: "Open the highest-signal theme first, then work down the rest of the continuity deck.",
        breadcrumbs: ["Home", "Since last visit", "Grouped rollup"],
      },
      actions: [
        buildOpenAction(
          `Open ${primary.label.toLowerCase()}`,
          primary.location,
          primary.summary,
        ),
        buildPinAction("Pin grouped rollup", primary.location, "Return to the grouped continuity rollup", "Resume · grouped change rollup"),
      ],
    },
  } satisfies PrioritizedCard;
}

interface QueueShiftSummary {
  key: string;
  label: string;
  summary: string;
  detail: string;
  tone: OperatorActionCard["tone"];
  location: ShellLocation;
}

function summarizeQueueShift(
  label: string,
  reviewFocus: Extract<ReviewFocus, "relationship" | "enrichment">,
  snapshot: DecisionSessionSnapshot | null,
  baseline: ContinuityBaselineSnapshot["relationshipSession"] | ContinuityBaselineSnapshot["enrichmentSession"],
): QueueShiftSummary | null {
  const session = snapshot?.session ?? null;
  const currentLoopId = snapshot?.current_item?.loop.id ?? session?.current_loop_id ?? null;
  const location = createLocation({
    state: "decide",
    reviewFocus,
    sessionId: session?.id ?? baseline?.sessionId ?? null,
  });

  if (!session && !baseline) {
    return null;
  }
  if (session && !baseline) {
    const loopCount = snapshot?.loop_count ?? 0;
    return {
      key: reviewFocus,
      label,
      summary: `${session.name} is now active with ${loopCount} queued item${loopCount === 1 ? "" : "s"}.`,
      detail: "A saved queue appeared since your last visit.",
      tone: "attention",
      location,
    };
  }
  if (!session && baseline) {
    return {
      key: reviewFocus,
      label,
      summary: `The previously active ${label.toLowerCase()} queue is no longer active.`,
      detail: `Queue #${baseline.sessionId} was active on your last visit.`,
      tone: "progress",
      location,
    };
  }
  if (!session || !baseline) {
    return null;
  }
  if (session.id !== baseline.sessionId) {
    return {
      key: reviewFocus,
      label,
      summary: `${session.name} replaced queue #${baseline.sessionId} as the active ${label.toLowerCase()} workflow.`,
      detail: `${snapshot?.loop_count ?? 0} item${(snapshot?.loop_count ?? 0) === 1 ? "" : "s"} are queued now.`,
      tone: "attention",
      location,
    };
  }

  const loopDelta = (snapshot?.loop_count ?? 0) - baseline.loopCount;
  if (loopDelta !== 0) {
    return {
      key: reviewFocus,
      label,
      summary: `${label} queue ${loopDelta > 0 ? "grew" : "shrank"} by ${Math.abs(loopDelta)} item${Math.abs(loopDelta) === 1 ? "" : "s"}.`,
      detail: `${baseline.loopCount} → ${snapshot?.loop_count ?? 0}`,
      tone: loopDelta > 0 ? "attention" : "progress",
      location,
    };
  }
  if (baseline.currentLoopId !== currentLoopId && currentLoopId != null) {
    return {
      key: reviewFocus,
      label,
      summary: `${label} queue advanced to a different loop while keeping the same size.`,
      detail: `Current loop #${currentLoopId}`,
      tone: "neutral",
      location,
    };
  }
  return null;
}

function buildQueueChangeCard(data: WorkspaceData): PrioritizedCard | null {
  if (!continuityBaseline) {
    return null;
  }

  const shifts = [
    summarizeQueueShift("Relationship", "relationship", data.relationshipSnapshot, continuityBaseline.relationshipSession),
    summarizeQueueShift("Enrichment", "enrichment", data.enrichmentSnapshot, continuityBaseline.enrichmentSession),
  ].filter((item): item is QueueShiftSummary => item != null);
  if (!shifts.length) {
    return null;
  }

  const actions: OperatorActionCardAction[] = [];
  shifts.forEach((shift, index) => {
    pushUniqueAction(
      actions,
      buildOpenAction(
        `Open ${shift.label.toLowerCase()} queue`,
        shift.location,
        shift.summary,
        index === 0 ? "primary" : "secondary",
      ),
    );
  });

  return {
    priority: 77,
    card: {
      id: "since-last-queue-changes",
      kind: "decision",
      tone: shifts.some((shift) => shift.tone === "attention") ? "attention" : "neutral",
      eyebrow: "Queue change",
      title: "Saved review queues shifted",
      summary: shifts.map((shift) => shift.summary).join(" · "),
      rationale:
        "Saved queues are durable operator workflows, so changes to their size or active session are high-signal continuity events.",
      preview: shifts.map((shift) => ({ label: shift.label, value: shift.detail })),
      trust: {
        contextSources: ["Saved review session snapshots", "Stored continuity baseline"],
        assumptions: ["The newest relationship and enrichment sessions remain the operator-visible queues to resume."],
        confidenceLabel: `${shifts.length} queue change${shifts.length === 1 ? "" : "s"} detected`,
        rollbackLabel: "Opening a queue remains non-mutating until you confirm or reject work inside it.",
        freshnessLabel: `Compared to ${formatTimestamp(continuityBaseline.recordedAtUtc)}`,
      },
      handoff: {
        changeSummary: "The saved review queues no longer match the state you last saw.",
        createdResources: shifts.map((shift) => `${shift.label}: ${shift.detail}`),
        nextStep: "Open the queue that changed most and confirm whether it is still the right next workflow.",
        breadcrumbs: ["Home", "Since last visit", "Queue changes"],
      },
      actions,
    },
  } satisfies PrioritizedCard;
}

function buildRepeatedSnoozeCard(data: WorkspaceData): PrioritizedCard | null {
  if (!visitBaseline) {
    return null;
  }

  const baselineTime = visitBaseline.getTime();
  const snoozeActions = readRecentShellActions().filter((entry) => {
    return entry.kind === "snooze" && Date.parse(entry.occurredAt) > baselineTime;
  });
  const baselineSnoozedIds = new Set((continuityBaseline?.snoozedLoops ?? []).map((item) => item.id));
  const newlySnoozedLoops = sortLoopsByMostRecentUpdate(data.allLoops.filter((loop) => {
    return typeof loop.snooze_until_utc === "string"
      && loop.snooze_until_utc.trim().length > 0
      && !baselineSnoozedIds.has(loop.id);
  }));
  if (snoozeActions.length < 2 && newlySnoozedLoops.length < 2) {
    return null;
  }

  const snoozeSignal = buildRepeatedSnoozeSignal(snoozeActions, newlySnoozedLoops, loopTitle);
  const primaryLocation = snoozeActions.find((entry) => entry.location)?.location
    ?? (newlySnoozedLoops[0] ? createLocation({ state: "do", loopId: newlySnoozedLoops[0].id }) : createLocation({ state: "do" }));
  return {
    priority: 70,
    card: {
      id: "since-last-repeated-snooze",
      kind: "context",
      tone: "attention",
      eyebrow: "Deferral signal",
      title: "Repeated snoozes may be hiding drift",
      summary: snoozeActions.length
        ? `${snoozeActions.length} snooze action${snoozeActions.length === 1 ? "" : "s"} were recorded since your last visit.`
        : `${newlySnoozedLoops.length} additional loop${newlySnoozedLoops.length === 1 ? "" : "s"} are currently snoozed.`,
      rationale:
        "Repeated deferral is often a sign that a loop needs reframing, a stronger next action, or an explicit drop decision.",
      preview: snoozeSignal.preview,
      trust: {
        contextSources: snoozeSignal.contextSources,
        assumptions: snoozeSignal.assumptions,
        confidenceLabel: "Deterministic deferral pattern",
        rollbackLabel: "This card is diagnostic only; inspect the loops before changing anything.",
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
      },
      handoff: {
        changeSummary: "More work has been deferred since your last visit.",
        createdResources: newlySnoozedLoops.slice(0, 3).map((loop) => loopTitle(loop)),
        nextStep: "Open the most recent deferred loop and decide whether to resume, reframe, or drop it.",
        breadcrumbs: ["Home", "Since last visit", "Repeated snoozes"],
      },
      actions: [
        buildOpenAction("Inspect deferred work", createLocation(primaryLocation), "Review the most recent snoozed loop or queue"),
        buildPinAction("Pin deferral recap", createLocation(primaryLocation), "Return to the repeated-snooze recap", "Resume · deferred work"),
      ],
    },
  } satisfies PrioritizedCard;
}

function pushUniqueAction(actions: OperatorActionCardAction[], action: OperatorActionCardAction): void {
  const existing = actions.some((candidate) => {
    return candidate.type === action.type && locationsMatch(candidate.location, action.location);
  });
  if (!existing) {
    actions.push(action);
  }
}

function currentWorkingSetHandoffMetadata(): WorkingSetSessionMetadata | null {
  const activeSet = workingSetContext?.active_working_set ?? null;
  if (!activeSet) {
    return null;
  }
  return {
    workingSetId: activeSet.id,
    workingSetName: activeSet.name,
    itemCount: activeSet.item_count,
    missingItemCount: activeSet.missing_item_count,
  };
}

function withWorkingSetHandoff(cards: OperatorActionCard[]): OperatorActionCard[] {
  const workingSet = currentWorkingSetHandoffMetadata();
  if (!workingSet) {
    return cards;
  }
  return cards.map((card) => {
    if (!card.handoff) {
      return card;
    }
    return {
      ...card,
      handoff: {
        ...card.handoff,
        workingSet,
      },
    };
  });
}

function buildResumeAnchorsCard(_data: WorkspaceData): PrioritizedCard | null {
  const resumeAnchors = readResumeAnchors();
  const recentActions = readRecentShellActions();
  const actions: OperatorActionCardAction[] = [];
  const preview: Array<{ label: string; value: string }> = [];
  const createdResources: string[] = [];

  const workingSetId = workingSetContext?.active_working_set_id ?? continuityBaseline?.activeWorkingSetId ?? null;
  const anchoredWorkingSet = workingSetId != null
    ? latestWorkingSets.find((set) => set.id === workingSetId) ?? null
    : null;
  const workingSetLocation = anchoredWorkingSet ? workingSetSessionLocation(anchoredWorkingSet.id) : null;
  if (anchoredWorkingSet && workingSetLocation) {
    preview.push({ label: "Working set", value: anchoredWorkingSet.name });
    createdResources.push(`Working set: ${anchoredWorkingSet.name}`);
    pushUniqueAction(
      actions,
      buildOpenAction("Open active working set", workingSetLocation, anchoredWorkingSet.description ?? anchoredWorkingSet.name),
    );
  }

  if (resumeAnchors.lastPlanningSessionId != null) {
    const location = createLocation({
      state: "plan",
      reviewFocus: "planning",
      sessionId: resumeAnchors.lastPlanningSessionId,
    });
    preview.push({
      label: "Planning",
      value: `Session #${resumeAnchors.lastPlanningSessionId} · ${formatRelativeTime(resumeAnchors.lastPlanningVisitedAtUtc)}`,
    });
    createdResources.push(`Plan session #${resumeAnchors.lastPlanningSessionId}`);
    pushUniqueAction(actions, buildOpenAction("Resume plan", location, "Return to the last planning session you visited"));
  }

  if (resumeAnchors.lastReviewFocus && resumeAnchors.lastReviewSessionId != null) {
    const location = createLocation({
      state: "decide",
      reviewFocus: resumeAnchors.lastReviewFocus,
      sessionId: resumeAnchors.lastReviewSessionId,
    });
    preview.push({
      label: "Review",
      value: `${resumeAnchors.lastReviewFocus} #${resumeAnchors.lastReviewSessionId} · ${formatRelativeTime(resumeAnchors.lastReviewVisitedAtUtc)}`,
    });
    createdResources.push(`${resumeAnchors.lastReviewFocus} session #${resumeAnchors.lastReviewSessionId}`);
    pushUniqueAction(actions, buildOpenAction("Resume review", location, "Return to the last saved review queue you opened", actions.length ? "secondary" : "primary"));
  }

  recentActions
    .filter((entry) => entry.location)
    .slice(0, 3)
    .forEach((entry) => {
      preview.push({ label: "Recent action", value: entry.label });
      createdResources.push(entry.label);
      if (entry.location) {
        pushUniqueAction(
          actions,
          buildOpenAction(entry.label, createLocation(entry.location), entry.description, actions.length ? "secondary" : "primary"),
        );
      }
    });

  if (!preview.length || !actions.length) {
    return null;
  }

  return {
    priority: 95,
    card: {
      id: "since-last-resume-anchors",
      kind: "handoff",
      tone: "attention",
      eyebrow: "Resume anchors",
      title: "Pick up where you left off",
      summary: `${actions.length} explicit resume anchor${actions.length === 1 ? "" : "s"} are ready in this browser.`,
      rationale:
        "Resume anchors keep cross-session work lightweight by surfacing the exact planning, review, and shell locations you recently used.",
      preview: preview.slice(0, 4),
      trust: {
        contextSources: ["Browser-local resume anchors", "Recent shell action history", "Working-set context"],
        assumptions: ["Resume anchors are local to this browser and may not reflect work done elsewhere."],
        confidenceLabel: "Deterministic resume shortcuts",
        rollbackLabel: "Opening an anchor only restores context; downstream mutations remain explicit.",
        freshnessLabel: recentActions[0] ? `Latest action ${formatRelativeTime(recentActions[0].occurredAt)}` : "Browser-local continuity state",
      },
      handoff: {
        changeSummary: "You do not need to reconstruct your prior context manually.",
        createdResources,
        nextStep: "Open the strongest resume anchor or pivot into the newest risk/change signal below.",
        breadcrumbs: ["Home", "Since last visit", "Resume anchors"],
      },
      actions: actions.slice(0, 4),
    },
  } satisfies PrioritizedCard;
}

function buildSinceLastCards(data: WorkspaceData): OperatorActionCard[] {
  const prioritized: PrioritizedCard[] = [];
  const maybeCards = [
    buildResumeAnchorsCard(data),
    buildPlanningDriftCard(data),
    buildGroupedChangeRollupCard(data),
    buildBlockedSinceLastCard(data),
    buildNewlyStaleCard(data),
    buildPlanningResourceRollupCard(data),
    buildFollowUpSinceLastCard(data),
    buildRiskCohortCard(data),
    buildQueueChangeCard(data),
    buildRepeatedSnoozeCard(data),
    buildCompletedSinceLastCard(data),
  ];
  maybeCards.forEach((entry) => {
    if (entry) {
      prioritized.push(entry);
    }
  });
  return prioritized
    .sort((left, right) => right.priority - left.priority)
    .map((entry) => entry.card);
}

function renderNowZone(data: WorkspaceData): void {
  if (!elements) {
    return;
  }

  elements.operatorNow.innerHTML = renderActionCardDeck(
    withWorkingSetHandoff(filterCardsForFocus(buildNowCards(data))),
    `
      <p class="operator-empty">No ready work surfaced right now. Capture something new or use Recall to ask the system what changed.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="capture">Capture work</button>
        <button class="secondary" type="button" data-open-state="recall" data-open-recall-tool="chat">Ask grounded chat</button>
      </div>
    `,
  );
}

function renderDecisionsZone(data: WorkspaceData): void {
  if (!elements) {
    return;
  }

  elements.operatorDecisions.innerHTML = renderActionCardDeck(
    withWorkingSetHandoff(filterCardsForFocus(buildDecisionCards(data))),
    `
      <p class="operator-empty">No saved decision queues are active right now. Review remains available when you want a broader hygiene pass.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="review">Open review cohorts</button>
        <button class="secondary" type="button" data-open-state="plan">Start planning</button>
      </div>
    `,
  );
}

function renderPlanZone(data: WorkspaceData): void {
  if (!elements) {
    return;
  }

  elements.operatorPlan.innerHTML = renderActionCardDeck(
    withWorkingSetHandoff(filterCardsForFocus(buildPlanCards(data))),
    `
      <p class="operator-empty">No saved planning session is active yet. Start a checkpointed plan when you need a multi-step operational pass.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="plan">Open planning workspace</button>
      </div>
    `,
  );
}

function renderRecallZone(data: WorkspaceData): void {
  if (!elements) {
    return;
  }

  elements.operatorRecall.innerHTML = renderActionCardDeck(
    withWorkingSetHandoff(filterCardsForFocus(buildRecallCards(data))),
    `
      <p class="operator-empty">Recall suggestions will appear here when chat, memory, or documents are the clearest next support surface.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="recall" data-open-recall-tool="chat">Open grounded chat</button>
      </div>
    `,
  );
}

function renderSinceLastVisit(data: WorkspaceData): void {
  if (!elements) {
    return;
  }

  if (!visitBaseline) {
    elements.operatorSinceLast.innerHTML = `
      <p class="operator-empty">This is the first recorded visit in this browser, so the workspace is showing the current system state instead of a delta. After this session, Cloop will summarize what changed between visits.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="operator">Stay in workspace</button>
        <button class="secondary" type="button" data-open-state="recall" data-open-recall-tool="chat">Ask what matters now</button>
      </div>
    `;
    return;
  }

  elements.operatorSinceLast.innerHTML = renderActionCardDeck(
    withWorkingSetHandoff(filterCardsForFocus(buildSinceLastCards(data))),
    `
      <p class="operator-empty">No major changes were recorded since your last visit. This is a calm resume state.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="do">Open ready work</button>
        <button class="secondary" type="button" data-open-state="review">Run review</button>
      </div>
    `,
  );
}

async function safeRequest<T>(factory: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await factory();
  } catch {
    return fallback;
  }
}

function sortSessionsByUpdated<T extends { updated_at_utc: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc));
}

async function loadWorkspaceData(): Promise<WorkspaceData> {
  const [
    nextLoops,
    reviewData,
    metrics,
    planningSessionsRaw,
    relationshipSessionsRaw,
    enrichmentSessionsRaw,
    allLoops,
  ] = await Promise.all([
    safeRequest(
      () => requestJson<NextLoopsResponse>("/loops/next?limit=8", {}, "Failed to load next actions"),
      { due_soon: [], high_leverage: [], quick_wins: [], standard: [] },
    ),
    safeRequest(
      () =>
        requestJson<LoopReviewResponse>(
          "/loops/review?daily=true&weekly=true&limit=50",
          {},
          "Failed to load review data",
        ),
      { daily: [], generated_at_utc: new Date(0).toISOString(), weekly: [] },
    ),
    safeRequest(
      () => requestJson<LoopMetricsResponse>("/loops/metrics", {}, "Failed to load loop metrics"),
      {
        generated_at_utc: new Date(0).toISOString(),
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
      },
    ),
    safeRequest(
      () => requestJson<PlanningSessionResponse[]>("/loops/planning/sessions", {}, "Failed to load planning sessions"),
      [],
    ),
    safeRequest(
      () =>
        requestJson<RelationshipReviewSessionResponse[]>(
          "/loops/review/relationship/sessions",
          {},
          "Failed to load relationship review sessions",
        ),
      [],
    ),
    safeRequest(
      () =>
        requestJson<EnrichmentReviewSessionResponse[]>(
          "/loops/review/enrichment/sessions",
          {},
          "Failed to load enrichment review sessions",
        ),
      [],
    ),
    safeRequest(
      () => requestJson<LoopResponse[]>("/loops/?status=all", {}, "Failed to load loops"),
      [],
    ),
  ]);

  const planningSessions = sortSessionsByUpdated(planningSessionsRaw);
  const relationshipSessions = sortSessionsByUpdated(relationshipSessionsRaw);
  const enrichmentSessions = sortSessionsByUpdated(enrichmentSessionsRaw);
  const primaryPlanningSession = planningSessions[0] ?? null;
  const primaryRelationshipSession = relationshipSessions[0] ?? null;
  const primaryEnrichmentSession = enrichmentSessions[0] ?? null;

  const [planningSnapshot, relationshipSnapshot, enrichmentSnapshot] = await Promise.all([
    primaryPlanningSession
      ? safeRequest(
          () =>
            requestJson<PlanningSessionSnapshotResponse>(
              `/loops/planning/sessions/${primaryPlanningSession.id}`,
              {},
              "Failed to load planning snapshot",
            ),
          null,
        )
      : Promise.resolve(null),
    primaryRelationshipSession
      ? safeRequest(
          () =>
            requestJson<RelationshipReviewSessionSnapshotResponse>(
              `/loops/review/relationship/sessions/${primaryRelationshipSession.id}`,
              {},
              "Failed to load relationship review snapshot",
            ),
          null,
        )
      : Promise.resolve(null),
    primaryEnrichmentSession
      ? safeRequest(
          () =>
            requestJson<EnrichmentReviewSessionSnapshotResponse>(
              `/loops/review/enrichment/sessions/${primaryEnrichmentSession.id}`,
              {},
              "Failed to load enrichment review snapshot",
            ),
          null,
        )
      : Promise.resolve(null),
  ]);

  return {
    nextLoops,
    reviewData,
    metrics,
    planningSessions,
    planningSnapshot,
    relationshipSessions,
    relationshipSnapshot,
    enrichmentSessions,
    enrichmentSnapshot,
    allLoops,
  };
}

function persistVisitStateOnce(): void {
  if (visitStatePersisted || !latestWorkspaceData) {
    return;
  }
  writeContinuityBaseline(
    buildContinuityBaseline({
      metrics: latestWorkspaceData.metrics,
      reviewData: latestWorkspaceData.reviewData,
      planningSnapshot: latestWorkspaceData.planningSnapshot,
      relationshipSnapshot: latestWorkspaceData.relationshipSnapshot,
      enrichmentSnapshot: latestWorkspaceData.enrichmentSnapshot,
      allLoops: latestWorkspaceData.allLoops,
      workingSetContext,
    }),
  );
  continuityBaseline = readContinuityBaseline();
  writeLastVisitNow();
  visitStatePersisted = true;
}

async function renderOperatorWorkspace(): Promise<void> {
  if (!elements || workspaceLoading) {
    return;
  }
  workspaceLoading = true;
  elements.operatorNow.innerHTML = '<p class="operator-empty">Loading prioritized work…</p>';
  elements.operatorDecisions.innerHTML = '<p class="operator-empty">Loading decision surfaces…</p>';
  elements.operatorPlan.innerHTML = '<p class="operator-empty">Loading planning sessions…</p>';
  elements.operatorRecall.innerHTML = '<p class="operator-empty">Preparing recall suggestions…</p>';
  elements.operatorSinceLast.innerHTML = '<p class="operator-empty">Comparing recent activity…</p>';

  try {
    const [workspaceData] = await Promise.all([loadWorkspaceData(), loadWorkingSetState()]);
    latestWorkspaceData = workspaceData;
    renderNowZone(latestWorkspaceData);
    renderDecisionsZone(latestWorkspaceData);
    renderPlanZone(latestWorkspaceData);
    renderRecallZone(latestWorkspaceData);
    renderSinceLastVisit(latestWorkspaceData);
    renderWorkingSet(latestWorkspaceData);
    renderWorkingSetFocusBanner();
    syncFocusModeClass();
    if (currentLocation.state === "working_set") {
      renderWorkingSetSessionSurface();
    }
    persistVisitStateOnce();
  } finally {
    workspaceLoading = false;
  }
}

function parseOptionalInteger(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) ? parsed : null;
}

function workingSetIdFromButton(button: HTMLButtonElement, key: string): number | null {
  return parseOptionalInteger(button.dataset[key]);
}

async function setWorkingSetContext(
  activeWorkingSetId: number | null,
  focusModeEnabled: boolean,
  options: { recordHistory?: boolean } = {},
): Promise<void> {
  await requestJson<WorkingSetContextResponse, WorkingSetContextUpdateRequest>(
    "/loops/working-sets/context",
    {
      method: "PATCH",
      body: {
        active_working_set_id: activeWorkingSetId,
        focus_mode_enabled: focusModeEnabled,
      },
    },
    "Failed to update working-set focus state",
  );
  await refreshWorkingSetState();

  if (options.recordHistory === false) {
    return;
  }

  recordRecentShellAction({
    kind: activeWorkingSetId != null ? "working_set_session" : "working_set",
    label: workingSetContext?.active_working_set
      ? `${focusModeEnabled ? "Focused" : "Opened"} working set · ${workingSetContext.active_working_set.name}`
      : "Cleared active working set",
    description:
      workingSetContext?.active_working_set?.description
      ?? "Updated the active working-set session context.",
    location:
      activeWorkingSetId != null
        ? workingSetSessionLocation(activeWorkingSetId)
        : createLocation({ state: "operator" }),
    metadata: {
      focusModeEnabled,
      workingSetId: activeWorkingSetId,
    },
  });
}

async function createWorkingSetViaDialog(): Promise<WorkingSetResponse | null> {
  const details = await promptForWorkingSetDetails();
  if (!details) {
    return null;
  }
  const created = await requestJson<WorkingSetResponse, { name: string; description: string | null }>(
    "/loops/working-sets",
    {
      method: "POST",
      body: details,
    },
    "Failed to create working set",
  );
  await refreshWorkingSetState();
  return created;
}

async function ensureActiveWorkingSetId(): Promise<number | null> {
  let activeWorkingSetId = workingSetContext?.active_working_set_id ?? null;
  if (activeWorkingSetId != null) {
    return activeWorkingSetId;
  }
  const created = await createWorkingSetViaDialog();
  if (!created) {
    return null;
  }
  activeWorkingSetId = created.id;
  await setWorkingSetContext(created.id, false, { recordHistory: false });
  return activeWorkingSetId;
}

async function pinLocationToWorkingSet(
  location: ShellLocation,
  label: string,
  description: string | null,
): Promise<void> {
  const activeWorkingSetId = await ensureActiveWorkingSetId();
  if (activeWorkingSetId == null) {
    return;
  }

  const existingItems = workingSetContext?.active_working_set?.items ?? [];
  const alreadyPresent = existingItems.some((item) => {
    return locationsMatch(workingSetItemLocation(item), location);
  });
  if (alreadyPresent) {
    return;
  }

  const metadata: Record<string, unknown> = {};
  let itemType: WorkingSetItemCreateRequest["item_type"] = "state_anchor";
  let itemId: number | null = null;

  if (location.loopId != null) {
    itemType = "loop";
    itemId = location.loopId;
  } else if (location.state === "plan" && location.sessionId != null) {
    itemType = "planning_session";
    itemId = location.sessionId;
  } else if (location.reviewFocus === "relationship" && location.sessionId != null) {
    itemType = "relationship_review_session";
    itemId = location.sessionId;
  } else if (location.reviewFocus === "enrichment" && location.sessionId != null) {
    itemType = "enrichment_review_session";
    itemId = location.sessionId;
  } else if (location.viewId != null) {
    itemType = "view";
    itemId = location.viewId;
  } else if (location.memoryId != null) {
    itemType = "memory";
    itemId = location.memoryId;
  } else if (location.query) {
    itemType = "query_anchor";
    metadata["query"] = location.query;
    metadata["state"] = location.state;
    metadata["label"] = label;
    if (description) {
      metadata["description"] = description;
    }
  } else {
    itemType = "state_anchor";
    metadata["state"] = location.state;
    metadata["recall_tool"] = location.recallTool;
    metadata["review_focus"] = location.reviewFocus;
    metadata["session_id"] = location.sessionId;
    metadata["loop_id"] = location.loopId;
    metadata["view_id"] = location.viewId;
    metadata["memory_id"] = location.memoryId;
    metadata["working_set_id"] = location.workingSetId;
    metadata["query"] = location.query;
  }

  await requestJson<WorkingSetResponse, WorkingSetItemCreateRequest>(
    `/loops/working-sets/${activeWorkingSetId}/items`,
    {
      method: "POST",
      body: {
        item_type: itemType,
        item_id: itemId,
        label,
        description,
        metadata,
      },
    },
    "Failed to add item to working set",
  );
  await refreshWorkingSetState();

  recordRecentShellAction({
    kind: "working_set",
    label: `Pinned ${label}`,
    description: description ?? "Added a resume anchor to the active working set.",
    location,
  });
}

async function addLoopIdsToActiveWorkingSet(loopIds: readonly number[]): Promise<void> {
  const activeWorkingSetId = await ensureActiveWorkingSetId();
  if (activeWorkingSetId == null) {
    return;
  }
  const existingLoopIds = new Set(
    (workingSetContext?.active_working_set?.items ?? [])
      .map((item) => item.launch.loop_id)
      .filter((value): value is number => typeof value === "number"),
  );
  for (const loopId of loopIds) {
    if (existingLoopIds.has(loopId)) {
      continue;
    }
    const loop = latestWorkspaceData?.allLoops.find((candidate) => candidate.id === loopId) ?? null;
    const label = loop ? loopTitle(loop) : `Loop #${loopId}`;
    const description = loop ? loopPreview(loop) : null;
    await requestJson<WorkingSetResponse, WorkingSetItemCreateRequest>(
      `/loops/working-sets/${activeWorkingSetId}/items`,
      {
        method: "POST",
        body: {
          item_type: "loop",
          item_id: loopId,
          label,
          description,
          metadata: {},
        },
      },
      "Failed to add loops to working set",
    );
  }
  await refreshWorkingSetState();
}

async function pinFromButton(button: HTMLButtonElement): Promise<void> {
  const location = createLocation({
    state: button.dataset["pinState"] as ShellState | undefined,
    recallTool: button.dataset["pinRecallTool"] as RecallTool | undefined,
    reviewFocus: button.dataset["pinReviewFocus"] as ReviewFocus | undefined,
    sessionId: parseOptionalInteger(button.dataset["pinSessionId"]),
    loopId: parseOptionalInteger(button.dataset["pinLoopId"]),
    viewId: parseOptionalInteger(button.dataset["pinViewId"]),
    memoryId: parseOptionalInteger(button.dataset["pinMemoryId"]),
    workingSetId: parseOptionalInteger(button.dataset["pinWorkingSetId"]),
    query: button.dataset["pinQuery"]?.trim() || null,
  });
  const label = button.dataset["pinLabel"]?.trim();
  const description = button.dataset["pinDescription"]?.trim() || null;
  if (!label) {
    return;
  }

  await pinLocationToWorkingSet(location, label, description);
}

function locationFromButton(button: HTMLButtonElement): ShellLocation {
  return createLocation({
    state: button.dataset["openState"] as ShellState | undefined,
    recallTool: button.dataset["openRecallTool"] as RecallTool | undefined,
    reviewFocus: button.dataset["openReviewFocus"] as ReviewFocus | undefined,
    sessionId: parseOptionalInteger(button.dataset["openSessionId"]),
    loopId: parseOptionalInteger(button.dataset["openLoopId"]),
    viewId: parseOptionalInteger(button.dataset["openViewId"]),
    memoryId: parseOptionalInteger(button.dataset["openMemoryId"]),
    workingSetId: parseOptionalInteger(button.dataset["openWorkingSetId"]),
    query: button.dataset["openQuery"]?.trim() || null,
  });
}

async function applyLocation(
  input: Partial<ShellLocation>,
  options: { syncHash?: boolean; refreshWorkspace?: boolean; recordHistory?: boolean } = {},
): Promise<void> {
  currentLocation = normalizeLocation(input);

  if (currentLocation.state === "working_set" && currentLocation.workingSetId != null) {
    const activeId = workingSetContext?.active_working_set_id ?? null;
    const desiredFocus =
      activeId === currentLocation.workingSetId
        ? Boolean(workingSetContext?.focus_mode_enabled)
        : false;

    if (activeId !== currentLocation.workingSetId || !latestWorkingSets.length) {
      await setWorkingSetContext(currentLocation.workingSetId, desiredFocus, {
        recordHistory: false,
      });
    }
  }

  updateShellHeader(currentLocation);
  syncNavState(currentLocation);
  syncVisiblePanels(currentLocation);
  await activateOwnedSurface(currentLocation);
  persistLocation(currentLocation);

  if (options.recordHistory ?? true) {
    rememberLocationAnchor(currentLocation);
    recordRecentShellAction(buildLocationAction(currentLocation));
  }

  if (options.syncHash ?? true) {
    suppressHashChange = true;
    window.location.hash = locationToHash(currentLocation);
    window.setTimeout(() => {
      suppressHashChange = false;
    }, 0);
  }

  if (currentLocation.state === "working_set") {
    renderWorkingSetSessionSurface();
  }

  if (currentLocation.state === "operator" || options.refreshWorkspace) {
    void renderOperatorWorkspace();
  }

  if (currentLocation.state === "plan") {
    window.setTimeout(() => {
      focusReviewPanel(currentLocation);
      void selectReviewSession("planning", currentLocation.sessionId);
    }, 140);
  }

  if (currentLocation.state === "decide") {
    window.setTimeout(() => {
      focusReviewPanel(currentLocation);
      void selectReviewSession(currentLocation.reviewFocus, currentLocation.sessionId);
    }, 140);
  }

  if (currentLocation.state === "review") {
    window.setTimeout(() => {
      focusReviewPanel(createLocation({ state: "review", reviewFocus: "cohorts" }));
      void selectReviewSession("cohorts", null);
      void applyQueryAnchor("review", currentLocation.query ?? null);
    }, 140);
  }

  if (currentLocation.state === "capture") {
    window.setTimeout(() => {
      void selectViewFilter(currentLocation.viewId ?? null);
      void applyQueryAnchor("capture", currentLocation.query ?? null);
    }, 140);
  }

  if (currentLocation.state === "do") {
    if (currentLocation.loopId != null) {
      void focusLoopCard(currentLocation.loopId);
    }
    if (currentLocation.query) {
      window.setTimeout(() => {
        void applyQueryAnchor("do", currentLocation.query ?? null);
      }, 140);
    }
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "memory" && currentLocation.memoryId != null) {
    window.setTimeout(() => {
      void focusMemoryEntry(currentLocation.memoryId ?? null);
    }, 140);
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "memory" && currentLocation.query) {
    window.setTimeout(() => {
      void runMemorySearchSurface(currentLocation.query ?? null);
    }, 140);
  }

  if (currentLocation.state === "recall" && currentLocation.recallTool === "rag" && currentLocation.query) {
    window.setTimeout(() => {
      void runDocumentAskSurface(currentLocation.query ?? null);
    }, 140);
  }
}

async function openGroundedChatWithPrompt(query: string): Promise<void> {
  await applyLocation(createLocation({ state: "recall", recallTool: "chat" }));
  window.setTimeout(() => {
    void askGroundedChatSurface(query);
  }, 180);
}

async function openMemorySearchWithQuery(query: string): Promise<void> {
  await applyLocation(createLocation({ state: "recall", recallTool: "memory", query }));
}

async function openDocumentAskWithQuery(query: string): Promise<void> {
  await applyLocation(createLocation({ state: "recall", recallTool: "rag", query }));
}

async function handleShellClick(event: Event): Promise<void> {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const openButton = target.closest<HTMLButtonElement>("[data-open-state]");
  if (openButton) {
    await applyLocation(locationFromButton(openButton));
    return;
  }

  const pinButton = target.closest<HTMLButtonElement>("[data-pin-label]");
  if (pinButton) {
    await pinFromButton(pinButton);
    return;
  }

  const createButton = target.closest<HTMLButtonElement>("[data-working-set-create]");
  if (createButton) {
    const created = await createWorkingSetViaDialog();
    if (created) {
      await applyLocation(workingSetSessionLocation(created.id));
    }
    return;
  }

  const activateButton = target.closest<HTMLButtonElement>("[data-working-set-activate]");
  const activateId = activateButton ? workingSetIdFromButton(activateButton, "workingSetActivate") : null;
  if (activateButton && activateId != null) {
    await applyLocation(workingSetSessionLocation(activateId));
    return;
  }

  const focusButton = target.closest<HTMLButtonElement>("[data-working-set-focus]");
  const focusId = focusButton ? workingSetIdFromButton(focusButton, "workingSetFocus") : null;
  if (focusButton && focusId != null) {
    const shouldEnable = !(workingSetContext?.focus_mode_enabled && workingSetContext?.active_working_set_id === focusId);
    await setWorkingSetContext(focusId, shouldEnable, { recordHistory: false });
    await applyLocation(workingSetSessionLocation(focusId));
    return;
  }

  const editButton = target.closest<HTMLButtonElement>("[data-working-set-edit]");
  const editId = editButton ? workingSetIdFromButton(editButton, "workingSetEdit") : null;
  if (editButton && editId != null) {
    const existing = latestWorkingSets.find((set) => set.id === editId) ?? null;
    if (!existing) {
      return;
    }
    const details = await promptForWorkingSetDetails({
      name: existing.name,
      description: existing.description ?? "",
    });
    if (!details) {
      return;
    }
    await requestJson<WorkingSetResponse, { name: string; description: string | null }>(
      `/loops/working-sets/${editId}`,
      {
        method: "PATCH",
        body: details,
      },
      "Failed to update working set",
    );
    await refreshWorkingSetState();
    return;
  }

  const deleteButton = target.closest<HTMLButtonElement>("[data-working-set-delete]");
  const deleteId = deleteButton ? workingSetIdFromButton(deleteButton, "workingSetDelete") : null;
  if (deleteButton && deleteId != null) {
    const existing = latestWorkingSets.find((set) => set.id === deleteId) ?? null;
    if (!existing || !(await confirmWorkingSetDeletion(existing.name))) {
      return;
    }
    await requestJson<{ deleted: boolean }>(
      `/loops/working-sets/${deleteId}`,
      { method: "DELETE" },
      "Failed to delete working set",
    );
    if (workingSetContext?.active_working_set_id === deleteId) {
      await setWorkingSetContext(null, false);
    } else {
      await refreshWorkingSetState();
    }
    return;
  }

  const moveItemButton = target.closest<HTMLButtonElement>("[data-working-set-move]");
  const moveToken = moveItemButton?.dataset["workingSetMove"] ?? "";
  if (moveToken) {
    const [workingSetIdRaw = "", itemIdRaw = "", direction = ""] = moveToken.split(":");
    const workingSetId = Number.parseInt(workingSetIdRaw, 10);
    const itemId = Number.parseInt(itemIdRaw, 10);
    const workingSet = latestWorkingSets.find((set) => set.id === workingSetId) ?? null;
    if (!workingSet || !Number.isInteger(itemId)) {
      return;
    }
    const orderedIds = (workingSet.items ?? []).map((item) => item.id);
    const index = orderedIds.indexOf(itemId);
    if (index < 0) {
      return;
    }
    const swapIndex = direction === "up" ? index - 1 : index + 1;
    if (swapIndex < 0 || swapIndex >= orderedIds.length) {
      return;
    }
    const nextOrderedIds = [...orderedIds];
    const currentValue = nextOrderedIds[index];
    const swapValue = nextOrderedIds[swapIndex];
    if (currentValue == null || swapValue == null) {
      return;
    }
    nextOrderedIds[index] = swapValue;
    nextOrderedIds[swapIndex] = currentValue;
    await requestJson<WorkingSetResponse, { ordered_item_ids: number[] }>(
      `/loops/working-sets/${workingSetId}/reorder`,
      {
        method: "POST",
        body: { ordered_item_ids: nextOrderedIds },
      },
      "Failed to reorder working-set items",
    );
    await refreshWorkingSetState();
    return;
  }

  const removeItemButton = target.closest<HTMLButtonElement>("[data-remove-working-set-item]");
  const removeToken = removeItemButton?.dataset["removeWorkingSetItem"] ?? "";
  if (removeToken) {
    const [workingSetIdRaw = "", itemIdRaw = ""] = removeToken.split(":");
    const workingSetId = Number.parseInt(workingSetIdRaw, 10);
    const itemId = Number.parseInt(itemIdRaw, 10);
    if (!Number.isInteger(workingSetId) || !Number.isInteger(itemId)) {
      return;
    }
    await requestJson<WorkingSetResponse>(
      `/loops/working-sets/${workingSetId}/items/${itemId}`,
      { method: "DELETE" },
      "Failed to remove working-set item",
    );
    await refreshWorkingSetState();
  }
}

function handleStateButtonClick(button: HTMLButtonElement): void {
  const state = button.dataset["shellState"] as ShellState | undefined;
  if (!state) {
    return;
  }
  const nextLocation =
    state === "recall"
      ? createLocation({ state, recallTool: currentLocation.recallTool })
      : state === "plan"
        ? createLocation({ state, reviewFocus: "planning" })
        : state === "review"
          ? createLocation({ state, reviewFocus: "cohorts" })
          : createLocation({ state });
  void applyLocation(nextLocation);
}

function handlePrimaryActionClick(): void {
  if (!elements) {
    return;
  }
  const location = createLocation({
    state: elements.shellPrimaryAction.dataset["primaryState"] as ShellState | undefined,
    recallTool: elements.shellPrimaryAction.dataset["primaryRecallTool"] as RecallTool | undefined,
    reviewFocus: elements.shellPrimaryAction.dataset["primaryReviewFocus"] as ReviewFocus | undefined,
    sessionId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primarySessionId"]),
    loopId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryLoopId"]),
    viewId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryViewId"]),
    memoryId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryMemoryId"]),
    workingSetId: parseOptionalInteger(elements.shellPrimaryAction.dataset["primaryWorkingSetId"]),
    query: elements.shellPrimaryAction.dataset["primaryQuery"]?.trim() || null,
  });
  void applyLocation(location);
}

function handleHashChange(): void {
  if (suppressHashChange) {
    return;
  }
  const hashLocation = parseHash(window.location.hash) ?? readPersistedLocation();
  void applyLocation(hashLocation, { syncHash: false });
}

function shouldIgnoreHotkeys(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && (target.tagName === "INPUT"
      || target.tagName === "TEXTAREA"
      || target.tagName === "SELECT"
      || target.isContentEditable);
}

function handleShellHotkeys(event: KeyboardEvent): void {
  if (event.defaultPrevented) {
    return;
  }
  if (commandPaletteController?.handleGlobalHotkey(event)) {
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }
  if (commandPaletteController?.isOpen()) {
    return;
  }
  if (shouldIgnoreHotkeys(event.target)) {
    return;
  }

  const mapping: Record<string, ShellLocation> = {
    "1": DEFAULT_LOCATION,
    "2": createLocation({ state: "capture" }),
    "3": createLocation({ state: "do" }),
    "4": createLocation({ state: "decide", reviewFocus: currentLocation.reviewFocus ?? "relationship" }),
    "5": createLocation({ state: "plan", reviewFocus: "planning" }),
    "6": createLocation({ state: "review", reviewFocus: "cohorts" }),
    "7": createLocation({ state: "recall", recallTool: currentLocation.recallTool }),
  };

  const location = mapping[event.key];
  if (!location) {
    return;
  }

  event.preventDefault();
  event.stopImmediatePropagation();
  void applyLocation(location);
}

function initializeShell(): void {
  elements = buildShellElements();
  visitBaseline = readLastVisit();
  continuityBaseline = readContinuityBaseline();
  visitStatePersisted = false;
  updateLastVisitStatus();
  commandPaletteController = bootstrapCommandPalette({
    getContext: () => ({
      currentLocation,
      loops: latestWorkspaceData?.allLoops ?? [],
      workingSets: latestWorkingSets,
      workingSetContext,
      planningSessions: latestWorkspaceData?.planningSessions ?? [],
      relationshipSessions: latestWorkspaceData?.relationshipSessions ?? [],
      enrichmentSessions: latestWorkspaceData?.enrichmentSessions ?? [],
    }),
    openLocation: async (location) => applyLocation(location),
    refreshWorkspace: async () => renderOperatorWorkspace(),
    createWorkingSet: async () => createWorkingSetViaDialog(),
    setWorkingSetContext: async (workingSetId, focusModeEnabled) =>
      setWorkingSetContext(workingSetId, focusModeEnabled),
    pinLocation: async (location, label, description) =>
      pinLocationToWorkingSet(createLocation(location), label, description),
    addLoopIdsToActiveWorkingSet: async (loopIds) => addLoopIdsToActiveWorkingSet(loopIds),
    askGroundedChat: async (query) => openGroundedChatWithPrompt(query),
    runMemorySearch: async (query) => openMemorySearchWithQuery(query),
    runDocumentAsk: async (query) => openDocumentAskWithQuery(query),
  });

  elements.stateButtons.forEach((button) => {
    if (button.dataset["shellState"]) {
      button.addEventListener("click", () => handleStateButtonClick(button));
    }
  });
  elements.recallButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const recallTool = (button.dataset["recallTool"] as RecallTool | undefined) ?? currentLocation.recallTool;
      void applyLocation(createLocation({ state: "recall", recallTool }));
    });
  });
  elements.shellPrimaryAction.addEventListener("click", handlePrimaryActionClick);
  elements.refreshWorkspaceButton.addEventListener("click", () => {
    void renderOperatorWorkspace();
  });
  elements.commandPaletteButton.addEventListener("click", () => {
    commandPaletteController?.open();
  });
  elements.createWorkingSetButton.addEventListener("click", () => {
    void (async () => {
      const created = await createWorkingSetViaDialog();
      if (created) {
        await applyLocation(workingSetSessionLocation(created.id));
      }
    })();
  });
  elements.workingSetFocusToggleButton.addEventListener("click", () => {
    const activeId = workingSetContext?.active_working_set_id ?? null;
    if (activeId == null) {
      return;
    }
    void setWorkingSetContext(activeId, !Boolean(workingSetContext?.focus_mode_enabled));
  });
  elements.workingSetExitFocusButton.addEventListener("click", () => {
    void setWorkingSetContext(null, false);
  });
  elements.operatorMain.addEventListener("click", (event) => {
    void handleShellClick(event);
  });
  elements.operatorWorkingSet.addEventListener("click", (event) => {
    void handleShellClick(event);
  });
  elements.workingSetMain.addEventListener("click", (event) => {
    void handleShellClick(event);
  });
  elements.workingSetFocusItems.addEventListener("click", (event) => {
    void handleShellClick(event);
  });
  window.addEventListener("hashchange", handleHashChange);
  window.addEventListener("keydown", handleShellHotkeys, { capture: true });
  window.addEventListener(WORKSPACE_REFRESH_EVENT, () => {
    void renderOperatorWorkspace();
  });

  const initialLocation = parseHash(window.location.hash) ?? readPersistedLocation() ?? DEFAULT_LOCATION;

  window.setTimeout(() => {
    void applyLocation(initialLocation, {
      syncHash: !window.location.hash,
      refreshWorkspace: true,
      recordHistory: false,
    });
  }, 0);
}

export function bootstrapShell(dependencies: ShellRuntimeDependencies): void {
  runtimeDependencies = dependencies;

  if (typeof window === "undefined") {
    return;
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeShell, { once: true });
    return;
  }
  initializeShell();
}
