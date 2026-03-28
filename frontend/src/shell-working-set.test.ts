/**
 * shell-working-set.test.ts - Focused regressions for working-set shell rendering.
 *
 * Purpose:
 *   Verify the working-set shell keeps user-facing launch-helper copy neutral
 *   even when backend item types retain legacy `*_anchor` names.
 *
 * Responsibilities:
 *   - Assert query/state launch helpers render neutral labels in the session view.
 *
 * Scope:
 *   - Working-set shell rendering only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend exec vitest run src/shell-working-set.test.ts`.
 *
 * Invariants/Assumptions:
 *   - HTTP loading remains the source of truth for working-set session data.
 *   - User-facing labels should not mirror internal `*_anchor` item_type values.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestJsonMock } = vi.hoisted(() => ({
  requestJsonMock: vi.fn(),
}));

vi.mock("./http", () => ({
  requestJson: requestJsonMock,
}));

import { createShellWorkingSetController } from "./shell-working-set";
import type { ShellElements, ShellLocation } from "./shell-types";
import type { WorkingSetContextResponse, WorkingSetItemResponse, WorkingSetResponse } from "./domain";

function location(overrides: Partial<ShellLocation> = {}): ShellLocation {
  return {
    state: overrides.state ?? "working_set",
    recallTool: overrides.recallTool ?? "chat",
    reviewFocus: overrides.reviewFocus ?? null,
    sessionId: overrides.sessionId ?? null,
    loopId: overrides.loopId ?? null,
    viewId: overrides.viewId ?? null,
    memoryId: overrides.memoryId ?? null,
    workingSetId: overrides.workingSetId ?? 7,
    query: overrides.query ?? null,
  };
}

function item(overrides: Partial<WorkingSetItemResponse> = {}): WorkingSetItemResponse {
  return {
    id: overrides.id ?? 1,
    item_type: overrides.item_type ?? "query_anchor",
    item_id: overrides.item_id ?? null,
    kind_label: overrides.kind_label ?? "Query anchor",
    label: overrides.label ?? "Blocked launch work",
    description: overrides.description ?? "Return to blocked launch cleanup if drift appears.",
    status_label: overrides.status_label ?? "Query anchor",
    missing: overrides.missing ?? false,
    position: overrides.position ?? 0,
    created_at_utc: overrides.created_at_utc ?? "2026-03-27T12:00:00Z",
    metadata: overrides.metadata ?? {},
    launch: overrides.launch ?? {
      state: "review",
      recall_tool: "chat",
      review_focus: "cohorts",
      session_id: null,
      loop_id: null,
      view_id: null,
      memory_id: null,
      working_set_id: 7,
      query: "status:blocked project:launch",
    },
  };
}

function workingSet(items: WorkingSetItemResponse[]): WorkingSetResponse {
  return {
    id: 7,
    name: "Launch reset",
    description: "Keep the launch cleanup context together.",
    item_count: items.length,
    missing_item_count: 0,
    last_activated_at_utc: "2026-03-27T12:05:00Z",
    created_at_utc: "2026-03-27T12:00:00Z",
    updated_at_utc: "2026-03-27T12:05:00Z",
    latest_reversible_event_id: 11,
    latest_reversible_event_type: "add_item",
    items,
    launch: {
      state: "working_set",
      recall_tool: "chat",
      review_focus: null,
      session_id: null,
      loop_id: null,
      view_id: null,
      memory_id: null,
      working_set_id: 7,
      query: null,
    },
  };
}

function workingSetContext(activeWorkingSet: WorkingSetResponse): WorkingSetContextResponse {
  return {
    active_working_set_id: activeWorkingSet.id,
    focus_mode_enabled: false,
    updated_at_utc: "2026-03-27T12:05:00Z",
    latest_reversible_event_id: 21,
    latest_reversible_event_type: "context_update",
    active_working_set: activeWorkingSet,
  };
}

describe("shell-working-set", () => {
  beforeEach(() => {
    requestJsonMock.mockReset();
    document.body.innerHTML = "";
  });

  it("renders neutral labels for query/state launch helpers", async () => {
    const items = [
      item(),
      item({
        id: 2,
        item_type: "state_anchor",
        kind_label: "Surface anchor",
        label: "Resume this working set",
        description: "Open the dedicated working-set session.",
        status_label: "Surface anchor",
        launch: {
          state: "working_set",
          recall_tool: "chat",
          review_focus: null,
          session_id: null,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: 7,
          query: null,
        },
      }),
    ];
    const set = workingSet(items);
    requestJsonMock.mockImplementation(async (path: string) => {
      if (path === "/loops/working-sets") {
        return [set];
      }
      if (path === "/loops/working-sets/context") {
        return workingSetContext(set);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    const workingSetMain = document.createElement("main");
    const elements = { workingSetMain } as ShellElements;
    const controller = createShellWorkingSetController({
      getElements: () => elements,
      getCurrentLocation: () => location(),
      getLatestWorkspaceData: () => null,
      renderOperatorZones: () => {},
    });

    await controller.loadWorkingSetState();
    controller.renderWorkingSetSessionSurface();

    expect(workingSetMain.textContent).toContain("Saved filter");
    expect(workingSetMain.textContent).toContain("Saved location");
    expect(workingSetMain.textContent).not.toContain("Query anchor");
    expect(workingSetMain.textContent).not.toContain("Surface anchor");
  });
});
