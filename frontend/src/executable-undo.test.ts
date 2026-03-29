/**
 * executable-undo.test.ts - Regression tests for shared undo builders.
 *
 * Purpose:
 *   Verify the executable undo helpers preserve deterministic resume locations and
 *   tolerate backend payloads that omit optional planning rollback fields.
 *
 * Responsibilities:
 *   - Assert planning rollback actions still render with stable defaults.
 *   - Guard against accidental regressions in the shared undo builder contract.
 *
 * Scope:
 *   - Pure frontend undo builder logic only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Backend rollback handles remain the source of truth.
 *   - Optional planning undo fields may be omitted by the API and should fall back deterministically.
 */

import type { PlanningExecutionHistoryItemResponse } from "./domain";
import { buildPlanningRollbackAction } from "./executable-undo";
import { createLocation } from "./shell-routing";

describe("executable-undo", () => {
  it("defaults missing planning rollback fields without breaking the resume location", () => {
    const action = buildPlanningRollbackAction({
      undo_action: {
        label: "Undo checkpoint",
        description: "Undo the checkpoint and resume planning.",
        undo: {
          kind: "planning_run",
          session_id: 19,
          run_id: 44,
          checkpoint_index: 3,
          checkpoint_title: "Create queue",
        },
      },
    } as unknown as PlanningExecutionHistoryItemResponse);

    expect(action).not.toBeNull();
    expect(action).toMatchObject({
      type: "undo",
      label: "Undo checkpoint",
      variant: "secondary",
      description: "Undo the checkpoint and resume planning.",
      requiresConfirmation: false,
      undo: {
        kind: "planning_run",
        sessionId: 19,
        runId: 44,
        checkpointIndex: 3,
        checkpointTitle: "Create queue",
        actionCount: 0,
        bestEffort: false,
      },
      successLocation: createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: 19,
      }),
    });
  });
});
