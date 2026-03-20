/**
 * operator-action-card-events.test.ts - Regression tests for shared action-card dispatch.
 *
 * Purpose:
 *   Verify shared operator action-card events execute deterministic open, pin,
 *   stage, edit, and defer flows outside review-local handlers.
 *
 * Responsibilities:
 *   - Assert stage pins a durable anchor and optionally opens the destination.
 *   - Assert edit replays the encoded query through shell navigation.
 *   - Assert defer only saves the anchor without forcing navigation.
 *
 * Scope:
 *   - Shared click-dispatch behavior only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Buttons are rendered with the shared operator-action-card data attributes.
 *   - Review-local `data-review-action` flows remain outside this dispatcher.
 */

import { describe, expect, it, vi } from "vitest";

import { handleOperatorActionCardClick } from "./operator-action-card-events";

describe("handleOperatorActionCardClick", () => {
  it("stages a durable anchor and opens the destination when requested", async () => {
    document.body.innerHTML = `
      <button
        id="stage"
        type="button"
        data-card-action="stage"
        data-stage-label="Recall · Evidence"
        data-stage-description="Evidence review: verify the source-backed follow-up."
        data-stage-open-after="true"
        data-stage-state="recall"
        data-stage-recall-tool="rag"
        data-stage-working-set-id="12"
        data-stage-query="What evidence should I verify?"
      >Stage</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("stage");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing stage button");
    }

    const handled = await handleOperatorActionCardClick(new MouseEvent("click", { bubbles: true, composed: true }), {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
    });

    expect(handled).toBe(false);

    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });
    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
    });

    expect(result).toBe(true);
    expect(pinLocationToWorkingSet).toHaveBeenCalledTimes(1);
    expect(pinLocationToWorkingSet.mock.calls[0]?.[0]).toMatchObject({
      state: "recall",
      recallTool: "rag",
      workingSetId: 12,
      query: "What evidence should I verify?",
    });
    expect(pinLocationToWorkingSet.mock.calls[0]?.[1]).toBe("Recall · Evidence");
    expect(pinLocationToWorkingSet.mock.calls[0]?.[3]).toEqual({ receiptVariant: "stage" });
    expect(applyLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "recall",
      recallTool: "rag",
      workingSetId: 12,
      query: "What evidence should I verify?",
    }));
  });

  it("replays edit queries through shell navigation", async () => {
    document.body.innerHTML = `
      <button
        id="edit"
        type="button"
        data-card-action="edit"
        data-edit-query="What should I do next?"
        data-edit-state="recall"
        data-edit-recall-tool="chat"
        data-edit-working-set-id="7"
      >Edit</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("edit");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing edit button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
    });

    expect(result).toBe(true);
    expect(pinLocationToWorkingSet).not.toHaveBeenCalled();
    expect(applyLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "recall",
      recallTool: "chat",
      workingSetId: 7,
      query: "What should I do next?",
    }));
  });

  it("defers a durable anchor without opening the destination", async () => {
    document.body.innerHTML = `
      <button
        id="defer"
        type="button"
        data-card-action="defer"
        data-defer-label="Do · Review the duplicate queue first"
        data-defer-description="Execution brief: Review the duplicate queue first."
        data-defer-state="do"
        data-defer-recall-tool="chat"
        data-defer-working-set-id="5"
      >Defer</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("defer");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing defer button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
    });

    expect(result).toBe(true);
    expect(pinLocationToWorkingSet).toHaveBeenCalledTimes(1);
    expect(pinLocationToWorkingSet.mock.calls[0]?.[0]).toMatchObject({
      state: "do",
      recallTool: "chat",
      workingSetId: 5,
    });
    expect(pinLocationToWorkingSet.mock.calls[0]?.[1]).toBe("Do · Review the duplicate queue first");
    expect(pinLocationToWorkingSet.mock.calls[0]?.[3]).toEqual({ receiptVariant: "defer" });
    expect(applyLocation).not.toHaveBeenCalled();
    expect(executeUndoAction).not.toHaveBeenCalled();
  });

  it("dispatches executable undo actions", async () => {
    document.body.innerHTML = `
      <button
        id="undo"
        type="button"
        data-card-action="undo"
        data-undo-kind="planning_run"
        data-undo-session-id="12"
        data-undo-run-id="44"
        data-undo-checkpoint-index="1"
        data-undo-checkpoint-title="Create review queue"
        data-undo-action-count="2"
        data-undo-best-effort="true"
        data-undo-confirm-title="Rollback checkpoint"
        data-undo-confirm-description="Rollback may be partial."
        data-undo-success-state="plan"
        data-undo-success-recall-tool="chat"
        data-undo-success-review-focus="planning"
        data-undo-success-session-id="12"
      >Rollback checkpoint</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("undo");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing undo button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
    });

    expect(result).toBe(true);
    expect(executeUndoAction).toHaveBeenCalledTimes(1);
    expect(executeUndoAction.mock.calls[0]?.[0]).toMatchObject({
      type: "undo",
      undo: {
        kind: "planning_run",
        sessionId: 12,
        runId: 44,
        checkpointIndex: 1,
        checkpointTitle: "Create review queue",
        actionCount: 2,
        bestEffort: true,
      },
      successLocation: expect.objectContaining({
        state: "plan",
        reviewFocus: "planning",
        sessionId: 12,
      }),
    });
    expect(applyLocation).not.toHaveBeenCalled();
    expect(pinLocationToWorkingSet).not.toHaveBeenCalled();
  });

  it("dispatches working-set undo actions", async () => {
    document.body.innerHTML = `
      <button
        id="working-set-undo"
        type="button"
        data-card-action="undo"
        data-undo-kind="working_set_event"
        data-undo-expected-event-id="91"
        data-undo-event-type="reorder"
        data-undo-working-set-id="7"
        data-undo-working-set-name="Launch reset"
        data-undo-success-state="working_set"
        data-undo-success-recall-tool="chat"
        data-undo-success-working-set-id="7"
      >Undo working-set change</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("working-set-undo");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing working-set undo button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
    });

    expect(result).toBe(true);
    expect(executeUndoAction).toHaveBeenCalledTimes(1);
    expect(executeUndoAction.mock.calls[0]?.[0]).toMatchObject({
      type: "undo",
      undo: {
        kind: "working_set_event",
        expectedEventId: 91,
        eventType: "reorder",
        workingSetId: 7,
        workingSetName: "Launch reset",
      },
      successLocation: expect.objectContaining({
        state: "working_set",
        workingSetId: 7,
      }),
    });
    expect(applyLocation).not.toHaveBeenCalled();
    expect(pinLocationToWorkingSet).not.toHaveBeenCalled();
  });
});
