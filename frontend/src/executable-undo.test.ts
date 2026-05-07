/**
 * executable-undo.test.ts - Regression tests for shared undo builders.
 *
 * Purpose:
 *   Verify the executable undo helpers preserve backend-authored confirmation and
 *   success-location contracts for planning rollback actions.
 *
 * Responsibilities:
 *   - Assert planning rollback actions honor the backend-authored shared undo contract.
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
 *   - Planning rollback actions include backend-authored confirmation copy and success-location handoff.
 */

import { requestJson } from "./http";
import type { PlanningExecutionHistoryItemResponse, PlanningSessionRollbackResponse } from "./domain";
import {
  buildClarificationUndoAction,
  buildPlanningRollbackAction,
  executeUndoAction,
  undoConfirmationDialog,
  undoHandleIdentity,
  undoUnavailableReason,
} from "./executable-undo";
import { createLocation } from "./shell-routing";
import { vi } from "vitest";

vi.mock("./http", () => ({
  requestJson: vi.fn(),
  HttpRequestError: class HttpRequestError extends Error {},
}));

describe("executable-undo", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("uses the backend-authored planning success location without frontend fallback", () => {
    const historyItem = {
      checkpoint_index: 3,
      checkpoint_title: "Create queue",
      executed_at_utc: "2026-03-29T12:00:00Z",
      operation_count: 2,
      run_id: 44,
      undo_action: {
        label: "Undo checkpoint",
        description: "Undo the checkpoint and resume planning.",
        undo: {
          kind: "planning_run",
          session_id: 19,
          run_id: 44,
          checkpoint_index: 3,
          checkpoint_title: "Create queue",
          action_count: 2,
          best_effort: false,
        },
        success_location: {
          state: "plan",
          review_focus: "planning",
          session_id: 19,
        },
      },
    } satisfies PlanningExecutionHistoryItemResponse;

    const action = buildPlanningRollbackAction(historyItem);

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
        actionCount: 2,
        bestEffort: false,
      },
      successLocation: createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: 19,
      }),
    });
  });

  it("requires backend-authored confirmation copy for undo dialogs", () => {
    expect(
      undoConfirmationDialog({
        type: "undo",
        label: "Rollback checkpoint",
        variant: "secondary",
        description: "Rollback Create queue.",
        undo: {
          kind: "planning_run",
          sessionId: 19,
          runId: 44,
          checkpointIndex: 3,
          checkpointTitle: "Create queue",
          actionCount: 2,
          bestEffort: true,
        },
        requiresConfirmation: true,
        confirmTitle: "Rollback checkpoint",
        confirmDescription: "Rollback will attempt 2 actions in reverse order.",
        successLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 19 }),
      }),
    ).toEqual({
      title: "Rollback checkpoint",
      description: "Rollback will attempt 2 actions in reverse order.",
    });

    expect(
      undoConfirmationDialog({
        type: "undo",
        label: "Undo checkpoint",
        variant: "secondary",
        description: "Undo the checkpoint and resume planning.",
        undo: {
          kind: "planning_run",
          sessionId: 19,
          runId: 44,
          checkpointIndex: 3,
          checkpointTitle: "Create queue",
          actionCount: 0,
          bestEffort: false,
        },
        requiresConfirmation: false,
        confirmTitle: null,
        confirmDescription: null,
        successLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 19 }),
      }),
    ).toBeNull();

    expect(() =>
      undoConfirmationDialog({
        type: "undo",
        label: "Rollback checkpoint",
        variant: "secondary",
        description: "Rollback Create queue.",
        undo: {
          kind: "planning_run",
          sessionId: 19,
          runId: 44,
          checkpointIndex: 3,
          checkpointTitle: "Create queue",
          actionCount: 2,
          bestEffort: true,
        },
        requiresConfirmation: true,
        confirmTitle: null,
        confirmDescription: null,
        successLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 19 }),
      }),
    ).toThrow("Undo action requires backend confirmation title and description.");
  });

  it("builds normalized clarification-answer undo handles", () => {
    const action = buildClarificationUndoAction(19, [11, 7, 11]);

    expect(action).toMatchObject({
      type: "undo",
      label: "Undo answers",
      description: "Restore these 2 clarifications to their unanswered state.",
      undo: {
        kind: "clarification_answer",
        loopId: 19,
        clarificationIds: [7, 11],
      },
      successLocation: createLocation({ state: "do", loopId: 19 }),
    });
    expect(action && undoHandleIdentity(action.undo)).toBe("clarification:19:7,11");
    expect(buildClarificationUndoAction(19, [])).toBeNull();
  });

  it("only marks unavailability for stale-or-malformed undo errors", () => {
    expect(undoUnavailableReason({
      name: "HttpRequestError",
      message: "Cannot undo: newer work landed",
      status: 400,
    })).toBe("Cannot undo: newer work landed");
    expect(undoUnavailableReason({
      name: "HttpRequestError",
      message: "Planning session not found",
      status: 404,
    })).toBe("Planning session not found");
    expect(undoUnavailableReason({
      name: "HttpRequestError",
      message: "Cannot undo: a newer clarification suggestion now depends on this answer",
      status: 400,
    })).toBe("Cannot undo: a newer clarification suggestion now depends on this answer");
    expect(undoUnavailableReason({
      name: "HttpRequestError",
      message: "Clarification undo is stale",
      status: 422,
    })).toBe("Clarification undo is stale");
    expect(undoUnavailableReason({
      name: "HttpRequestError",
      message: "Server exploded",
      status: 500,
    })).toBeNull();
    expect(undoUnavailableReason(new Error("Undo action requires backend confirmation title and description."))).toBe(
      "Undo action requires backend confirmation title and description.",
    );
    expect(undoUnavailableReason(new Error("Network down"))).toBeNull();
  });

  it("lands clarification undo receipts with restored clarification counts", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce({
      loop_id: 19,
      restored_count: 2,
      restored_clarification_ids: [7, 11],
      reopened_suggestion_ids: [44],
      message: "Clarification answers undone. Questions are now unanswered again.",
    });

    const result = await executeUndoAction({
      type: "undo",
      label: "Undo answers",
      variant: "secondary",
      description: "Restore these clarifications to their unanswered state.",
      undo: {
        kind: "clarification_answer",
        loopId: 19,
        clarificationIds: [7, 11],
      },
      successLocation: createLocation({ state: "do", loopId: 19 }),
    });

    expect(requestJson).toHaveBeenCalledWith(
      "/loops/19/clarifications/undo",
      expect.objectContaining({
        method: "POST",
        body: { clarification_ids: [7, 11] },
      }),
      "Failed to undo clarification answers",
    );
    expect(result.card.id).toBe("undo-clarification-19-7-11");
    expect(result.card.preview).toContainEqual({ label: "Restored clarifications", value: "2" });
    expect(result.card.preview).toContainEqual({ label: "Reopened suggestions", value: "1" });
    expect(result.resumeLocation).toEqual(createLocation({ state: "do", loopId: 19 }));
  });

  it("lands planning rollback receipts on the current checkpoint title", async () => {
    const rollbackResponse = {
      rollback: {
        run_id: 44,
        checkpoint_index: 3,
        checkpoint_title: "Create queue",
        attempted_action_count: 2,
        failed_action_count: 0,
        failed_actions: [],
        rollback_complete: true,
        rolled_back_at_utc: "2026-03-29T13:00:00Z",
        summary: "Rolled back checkpoint Create queue; 2 rollback actions completed",
      },
      snapshot: {
        plan_title: "Weekly plan",
        plan_summary: "Plan summary",
        session: {
          id: 19,
          name: "Weekly planning",
          prompt: "Plan the week",
          status: "in_progress",
          checkpoint_count: 4,
          current_checkpoint_index: 2,
          executed_checkpoint_count: 3,
          include_memory_context: false,
          include_rag_context: false,
          loop_limit: 10,
          rag_k: 5,
          created_at_utc: "2026-03-29T12:00:00Z",
          updated_at_utc: "2026-03-29T13:00:00Z",
        },
        current_checkpoint: {
          title: "Resume plan from prior checkpoint",
          summary: "Resume plan from prior checkpoint summary",
          success_criteria: "Ready to continue",
        },
      },
    } satisfies PlanningSessionRollbackResponse;

    vi.mocked(requestJson).mockResolvedValueOnce(rollbackResponse);

    const result = await executeUndoAction({
      type: "undo",
      label: "Undo checkpoint",
      variant: "secondary",
      description: "Undo the checkpoint and resume planning.",
      undo: {
        kind: "planning_run",
        sessionId: 19,
        runId: 44,
        checkpointIndex: 3,
        checkpointTitle: "Create queue",
        actionCount: 0,
        bestEffort: false,
      },
      requiresConfirmation: false,
      confirmTitle: null,
      confirmDescription: null,
      successLocation: createLocation({ state: "plan", reviewFocus: "planning", sessionId: 19 }),
    });

    expect(requestJson).toHaveBeenCalledWith(
      "/loops/planning/sessions/19/rollback",
      expect.objectContaining({
        method: "POST",
        body: { run_id: 44 },
      }),
      "Failed to undo checkpoint",
    );
    expect(result.card.id).toBe("undo-planning-19-2026-03-29T13:00:00Z");
    expect(result.card.summary).toBe("Rolled back checkpoint Create queue; 2 rollback actions completed");
    expect(result.card.preview).toContainEqual({ label: "Rolled back checkpoint", value: "Create queue" });
    expect(result.resumeLocation).toEqual(createLocation({ state: "plan", reviewFocus: "planning", sessionId: 19 }));
  });

});
