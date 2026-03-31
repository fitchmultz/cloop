/**
 * shell-routing.ts - Operator-shell location construction, persistence, and hash routing.
 *
 * Purpose:
 *   Own the shell's canonical location model so deep links, stored navigation,
 *   and button launch attributes stay aligned across the frontend.
 *
 * Responsibilities:
 *   - Define default shell locations and state descriptors.
 *   - Normalize partial location input into canonical shell locations.
 *   - Parse and serialize shell hash routes.
 *   - Persist and restore shell location state from local storage.
 *   - Compare locations and encode open-location button attributes.
 *
 * Scope:
 *   - Shell routing and location helpers only.
 *
 * Usage:
 *   - Imported by shell.ts, shell-working-set.ts, shell-events.ts, and other
 *     shell-adjacent modules that need canonical location handling.
 *
 * Invariants/Assumptions:
 *   - Hash routes remain the canonical shareable shell URLs.
 *   - Persisted locations are normalized before use.
 *   - Supported states, recall tools, and review foci are hard-cutover lists.
 */

import type { RecallTool, ReviewFocus, ShellLocationContract, ShellState } from "./contracts-ui";
import { escapeHtml, safeJsonParse, SHELL_LOCATION_STORAGE_KEY } from "./shell-core";
import type { ShellLocation, ShellLocationInput, StateDescriptor } from "./shell-types";

const SHELL_STATES: ShellState[] = ["operator", "capture", "do", "decide", "plan", "review", "recall", "working_set"];
const RECALL_TOOLS: RecallTool[] = ["chat", "memory", "rag"];
const REVIEW_FOCI: ReviewFocus[] = ["planning", "relationship", "enrichment", "cohorts"];
const DECISION_REVIEW_FOCI: Array<Extract<ReviewFocus, "relationship" | "enrichment" | "cohorts">> = [
  "relationship",
  "enrichment",
  "cohorts",
];
export const WORK_STATES = ["do", "decide", "plan", "review"] as const satisfies readonly ShellState[];
export type WorkState = (typeof WORK_STATES)[number];

export const DEFAULT_LOCATION: ShellLocation = {
  state: "operator",
  recallTool: "chat",
  reviewFocus: null,
  sessionId: null,
  loopId: null,
  workingSetId: null,
  includeLoopContext: null,
  includeMemoryContext: null,
  includeRagContext: null,
};

export const STATE_DESCRIPTORS: Record<ShellState, StateDescriptor> = {
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

export function createLocation(overrides: ShellLocationInput = {}): ShellLocation {
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
    includeLoopContext: overrides.includeLoopContext ?? null,
    includeMemoryContext: overrides.includeMemoryContext ?? null,
    includeRagContext: overrides.includeRagContext ?? null,
  };
}

export function workingSetSessionLocation(workingSetId: number | null): ShellLocation {
  return createLocation({
    state: "working_set",
    workingSetId,
  });
}

export function isWorkState(state: ShellState | null | undefined): state is WorkState {
  return state != null && WORK_STATES.includes(state as WorkState);
}

export function defaultLocationForState(
  state: ShellState,
  currentLocation: Partial<ShellLocationInput> = {},
): ShellLocation {
  const workingSetId = currentLocation.workingSetId ?? null;

  switch (state) {
    case "operator":
      return createLocation({ state, workingSetId });
    case "capture":
      return createLocation({
        state,
        viewId: currentLocation.state === "capture" ? (currentLocation.viewId ?? null) : null,
        query: currentLocation.state === "capture" ? (currentLocation.query ?? null) : null,
        workingSetId,
      });
    case "do":
      return createLocation({
        state,
        loopId: currentLocation.state === "do" ? (currentLocation.loopId ?? null) : null,
        query: currentLocation.state === "do" ? (currentLocation.query ?? null) : null,
        workingSetId,
      });
    case "decide":
      return createLocation({
        state,
        reviewFocus:
          currentLocation.state === "decide"
            ? (currentLocation.reviewFocus ?? "relationship")
            : "relationship",
        sessionId: currentLocation.state === "decide" ? (currentLocation.sessionId ?? null) : null,
        workingSetId,
      });
    case "plan":
      return createLocation({
        state,
        reviewFocus: "planning",
        sessionId: currentLocation.state === "plan" ? (currentLocation.sessionId ?? null) : null,
        workingSetId,
      });
    case "review":
      return createLocation({
        state,
        reviewFocus: "cohorts",
        query: currentLocation.state === "review" ? (currentLocation.query ?? null) : null,
        workingSetId,
      });
    case "recall":
      return createLocation({
        state,
        recallTool: currentLocation.recallTool ?? DEFAULT_LOCATION.recallTool,
        memoryId: currentLocation.state === "recall" && currentLocation.recallTool === "memory"
          ? (currentLocation.memoryId ?? null)
          : null,
        query: currentLocation.state === "recall" ? (currentLocation.query ?? null) : null,
        workingSetId,
        includeLoopContext: currentLocation.state === "recall" ? (currentLocation.includeLoopContext ?? null) : null,
        includeMemoryContext: currentLocation.state === "recall" ? (currentLocation.includeMemoryContext ?? null) : null,
        includeRagContext: currentLocation.state === "recall" ? (currentLocation.includeRagContext ?? null) : null,
      });
    case "working_set":
      return createLocation({
        state,
        workingSetId: currentLocation.workingSetId ?? null,
      });
  }
}

export function openLocationAttributes(location: ShellLocationContract): string {
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
    ["include-loop-context", location.includeLoopContext == null ? "" : String(location.includeLoopContext)],
    ["include-memory-context", location.includeMemoryContext == null ? "" : String(location.includeMemoryContext)],
    ["include-rag-context", location.includeRagContext == null ? "" : String(location.includeRagContext)],
  ] as const;

  return attributes
    .map(([name, value]) => `data-open-${name}="${escapeHtml(value)}"`)
    .join(" ");
}

export function normalizeLocation(value: Partial<ShellLocationInput>): ShellLocation {
  const state = value.state && SHELL_STATES.includes(value.state) ? value.state : DEFAULT_LOCATION.state;
  const recallTool =
    value.recallTool && RECALL_TOOLS.includes(value.recallTool)
      ? value.recallTool
      : DEFAULT_LOCATION.recallTool;
  const reviewFocus = value.reviewFocus && REVIEW_FOCI.includes(value.reviewFocus) ? value.reviewFocus : null;

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
    includeLoopContext: typeof value.includeLoopContext === "boolean" ? value.includeLoopContext : null,
    includeMemoryContext: typeof value.includeMemoryContext === "boolean" ? value.includeMemoryContext : null,
    includeRagContext: typeof value.includeRagContext === "boolean" ? value.includeRagContext : null,
  };
}

export function readPersistedLocation(): ShellLocation {
  const stored = safeJsonParse<Partial<ShellLocation>>(window.localStorage.getItem(SHELL_LOCATION_STORAGE_KEY), {});
  return normalizeLocation(stored);
}

export function persistLocation(location: ShellLocation): void {
  window.localStorage.setItem(SHELL_LOCATION_STORAGE_KEY, JSON.stringify(location));
}

function parseBooleanQueryParam(value: string | null): boolean | null {
  if (value === "1" || value === "true") {
    return true;
  }
  if (value === "0" || value === "false") {
    return false;
  }
  return null;
}

function splitHashQuery(hash: string): {
  path: string;
  workingSetId: number | null;
  includeLoopContext: boolean | null;
  includeMemoryContext: boolean | null;
  includeRagContext: boolean | null;
} {
  const cleaned = hash.replace(/^#/, "").trim();
  if (!cleaned) {
    return {
      path: "",
      workingSetId: null,
      includeLoopContext: null,
      includeMemoryContext: null,
      includeRagContext: null,
    };
  }
  const [rawPath, query = ""] = cleaned.split("?", 2);
  const path = rawPath ?? "";
  const params = new URLSearchParams(query);
  const rawWorkingSetId = params.get("ws") ?? params.get("working_set_id");
  const parsedWorkingSetId = rawWorkingSetId ? Number.parseInt(rawWorkingSetId, 10) : Number.NaN;
  return {
    path,
    workingSetId: Number.isInteger(parsedWorkingSetId) && parsedWorkingSetId > 0
      ? parsedWorkingSetId
      : null,
    includeLoopContext: parseBooleanQueryParam(params.get("lc")),
    includeMemoryContext: parseBooleanQueryParam(params.get("mc")),
    includeRagContext: parseBooleanQueryParam(params.get("rc")),
  };
}

function appendLocationHash(baseHash: string, location: ShellLocation): string {
  const params = new URLSearchParams();
  if (location.workingSetId != null && !baseHash.startsWith("#working-set")) {
    params.set("ws", String(location.workingSetId));
  }
  if (location.includeLoopContext != null) {
    params.set("lc", location.includeLoopContext ? "1" : "0");
  }
  if (location.includeMemoryContext != null) {
    params.set("mc", location.includeMemoryContext ? "1" : "0");
  }
  if (location.includeRagContext != null) {
    params.set("rc", location.includeRagContext ? "1" : "0");
  }
  const suffix = params.toString();
  return suffix ? `${baseHash}?${suffix}` : baseHash;
}

export function locationToHash(location: ShellLocation): string {
  const baseHash = (() => {
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
  })();

  return appendLocationHash(baseHash, location);
}

export function parseHash(hash: string): ShellLocation | null {
  const { path, workingSetId, includeLoopContext, includeMemoryContext, includeRagContext } = splitHashQuery(hash);
  if (!path) {
    return null;
  }

  const parts = path.split("/").filter(Boolean);
  const [first, second, third] = parts;

  switch (first) {
    case "operator":
      return createLocation({
        ...DEFAULT_LOCATION,
        workingSetId,
      });
    case "capture":
      if (second === "view" && third) {
        return createLocation({
          state: "capture",
          viewId: Number.parseInt(third, 10) || null,
          workingSetId,
        });
      }
      if (second === "query" && third) {
        return createLocation({
          state: "capture",
          query: decodeURIComponent(third),
          workingSetId,
        });
      }
      return createLocation({ state: "capture", workingSetId });
    case "do":
      if (second === "loop" && third) {
        return createLocation({
          state: "do",
          loopId: Number.parseInt(third, 10) || null,
          workingSetId,
        });
      }
      if (second === "query" && third) {
        return createLocation({
          state: "do",
          query: decodeURIComponent(third),
          workingSetId,
        });
      }
      return createLocation({ state: "do", workingSetId });
    case "decide": {
      const focus = second && DECISION_REVIEW_FOCI.includes(second as Extract<ReviewFocus, "relationship" | "enrichment" | "cohorts">)
        ? (second as ReviewFocus)
        : null;
      return createLocation({
        state: "decide",
        reviewFocus: focus,
        sessionId: focus && third ? Number.parseInt(third, 10) || null : null,
        workingSetId,
      });
    }
    case "plan":
      return createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: second === "session" && third ? Number.parseInt(third, 10) || null : null,
        workingSetId,
      });
    case "review":
      if (second === "query" && third) {
        return createLocation({
          state: "review",
          reviewFocus: "cohorts",
          query: decodeURIComponent(third),
          workingSetId,
        });
      }
      return createLocation({ state: "review", reviewFocus: "cohorts", workingSetId });
    case "recall": {
      const recallTool = second && RECALL_TOOLS.includes(second as RecallTool)
        ? (second as RecallTool)
        : DEFAULT_LOCATION.recallTool;
      return createLocation({
        state: "recall",
        recallTool,
        memoryId: second === "memory" && third && parts[3] !== "query" ? Number.parseInt(third, 10) || null : null,
        query: parts[2] === "query" && parts[3] ? decodeURIComponent(parts[3]) : null,
        workingSetId,
        includeLoopContext,
        includeMemoryContext,
        includeRagContext,
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

export function locationsMatch(
  left: ShellLocationContract | null | undefined,
  right: ShellLocationContract | null | undefined,
): boolean {
  if (!left || !right) {
    return false;
  }
  return left.state === right.state
    && left.recallTool === right.recallTool
    && left.reviewFocus === right.reviewFocus
    && left.sessionId === right.sessionId
    && left.loopId === right.loopId
    && (left.viewId ?? null) === (right.viewId ?? null)
    && (left.memoryId ?? null) === (right.memoryId ?? null)
    && (left.workingSetId ?? null) === (right.workingSetId ?? null)
    && (left.query ?? null) === (right.query ?? null)
    && (left.includeLoopContext ?? null) === (right.includeLoopContext ?? null)
    && (left.includeMemoryContext ?? null) === (right.includeMemoryContext ?? null)
    && (left.includeRagContext ?? null) === (right.includeRagContext ?? null);
}
