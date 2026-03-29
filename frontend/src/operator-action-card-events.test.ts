/**
 * operator-action-card-events.test.ts - Regression tests for shared action-card dispatch.
 *
 * Purpose:
 *   Verify shared operator action-card events execute deterministic open, pin,
 *   stage, edit, and defer flows outside review-local handlers.
 *
 * Responsibilities:
 *   - Assert stage saves a durable working-set item and optionally opens the destination.
 *   - Assert edit replays the encoded query through shell navigation.
 *   - Assert defer only saves the item without forcing navigation.
 *   - Assert recovery actions acknowledge drift and launch the surviving path.
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
  it("stages a durable working-set item and opens the destination when requested", async () => {
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
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("stage");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing stage button");
    }

    const handled = await handleOperatorActionCardClick(new MouseEvent("click", { bubbles: true, composed: true }), {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
    });

    expect(handled).toBe(false);

    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });
    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
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
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
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
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
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

  it("defers a durable working-set item without opening the destination", async () => {
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
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
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
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
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
        data-undo-description="Undo this planning checkpoint."
        data-undo-best-effort="true"
        data-undo-requires-confirmation="true"
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
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
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
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
    });

    expect(result).toBe(true);
    expect(executeUndoAction).toHaveBeenCalledTimes(1);
    expect(executeUndoAction.mock.calls[0]?.[0]).toMatchObject({
      type: "undo",
      description: "Undo this planning checkpoint.",
      undo: {
        kind: "planning_run",
        sessionId: 12,
        runId: 44,
        checkpointIndex: 1,
        checkpointTitle: "Create review queue",
        actionCount: 2,
        bestEffort: true,
      },
      requiresConfirmation: true,
      successLocation: expect.objectContaining({
        state: "plan",
        reviewFocus: "planning",
        sessionId: 12,
      }),
    });
    expect(applyLocation).not.toHaveBeenCalled();
    expect(pinLocationToWorkingSet).not.toHaveBeenCalled();
  });

  it("preserves explicit undo confirmation flags instead of inferring from description text", async () => {
    document.body.innerHTML = `
      <button
        id="undo-no-confirm"
        type="button"
        data-card-action="undo"
        data-undo-kind="planning_run"
        data-undo-session-id="12"
        data-undo-run-id="44"
        data-undo-checkpoint-index="1"
        data-undo-checkpoint-title="Create review queue"
        data-undo-action-count="2"
        data-undo-best-effort="false"
        data-undo-description="Undo this planning checkpoint."
        data-undo-requires-confirmation="false"
        data-undo-confirm-title="Checkpoint info"
        data-undo-confirm-description="Informational text only."
      >Undo checkpoint</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("undo-no-confirm");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing undo button without confirmation");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
    });

    expect(result).toBe(true);
    expect(executeUndoAction).toHaveBeenCalledTimes(1);
    expect(executeUndoAction.mock.calls[0]?.[0]).toMatchObject({
      type: "undo",
      requiresConfirmation: false,
      confirmTitle: "Checkpoint info",
      confirmDescription: "Informational text only.",
    });
  });

  it("ignores malformed undo buttons that omit the backend-authored description", async () => {
    document.body.innerHTML = `
      <button
        id="undo-missing-description"
        type="button"
        data-card-action="undo"
        data-undo-kind="planning_run"
        data-undo-session-id="12"
        data-undo-run-id="44"
        data-undo-checkpoint-index="1"
        data-undo-checkpoint-title="Create review queue"
        data-undo-action-count="2"
      >Undo checkpoint</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("undo-missing-description");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing malformed undo button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
    });

    expect(result).toBe(true);
    expect(executeUndoAction).not.toHaveBeenCalled();
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
        data-undo-description="Undo the working-set reorder."
        data-undo-success-state="working_set"
        data-undo-success-recall-tool="chat"
        data-undo-success-working-set-id="7"
      >Undo working-set change</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
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
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
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

  it("dispatches relationship-decision undo actions from encoded handles", async () => {
    document.body.innerHTML = `
      <button
        id="relationship-undo"
        type="button"
        data-card-action="undo"
        data-undo-kind="relationship_decision"
        data-undo-handle='{"kind":"relationship_decision","sessionId":12,"loopId":5,"candidateLoopId":9,"expectedPairState":{"duplicate":{"state":"dismissed","confidence":null,"source":"user"},"related":null},"restorePairState":{"duplicate":null,"related":null}}'
        data-undo-description="Restore the relationship pair to the queue."
        data-undo-success-state="decide"
        data-undo-success-recall-tool="chat"
        data-undo-success-review-focus="relationship"
        data-undo-success-session-id="12"
      >Undo decision</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("relationship-undo");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing relationship undo button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
    });

    expect(result).toBe(true);
    expect(executeUndoAction).toHaveBeenCalledTimes(1);
    expect(executeUndoAction.mock.calls[0]?.[0]).toMatchObject({
      type: "undo",
      description: "Restore the relationship pair to the queue.",
      undo: {
        kind: "relationship_decision",
        sessionId: 12,
        loopId: 5,
        candidateLoopId: 9,
        expectedPairState: {
          duplicate: { state: "dismissed", confidence: null, source: "user" },
          related: null,
        },
      },
      successLocation: expect.objectContaining({
        state: "decide",
        reviewFocus: "relationship",
        sessionId: 12,
      }),
    });
    expect(applyLocation).not.toHaveBeenCalled();
    expect(pinLocationToWorkingSet).not.toHaveBeenCalled();
  });

  it("acknowledges and opens recovery actions", async () => {
    document.body.innerHTML = `
      <button
        id="recover"
        type="button"
        data-card-action="recover"
        data-recovery-key="replacement::planning:41"
        data-recovery-kind="replacement"
        data-recover-state="decide"
        data-recover-recall-tool="chat"
        data-recover-review-focus="enrichment"
        data-recover-session-id="52"
      >Open replacement workflow</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const acknowledgeContinuityRecovery = vi.fn();
    const acknowledgeContinuityNotification = vi.fn();
    const suppressContinuityNotification = vi.fn();
    const button = document.getElementById("recover");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing recover button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery,
      acknowledgeContinuityNotification,
      suppressContinuityNotification,
    });

    expect(result).toBe(true);
    expect(acknowledgeContinuityRecovery).toHaveBeenCalledWith("replacement::planning:41");
    expect(applyLocation).toHaveBeenCalledWith(expect.objectContaining({
      state: "decide",
      reviewFocus: "enrichment",
      sessionId: 52,
    }));
  });

  it("acknowledges recovery changes without navigating", async () => {
    document.body.innerHTML = `
      <button
        id="acknowledge"
        type="button"
        data-card-action="acknowledge"
        data-acknowledgement-key="replacement::planning:41"
      >Acknowledge change</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const acknowledgeContinuityRecovery = vi.fn();
    const acknowledgeContinuityNotification = vi.fn();
    const suppressContinuityNotification = vi.fn();
    const button = document.getElementById("acknowledge");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing acknowledge button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery,
      acknowledgeContinuityNotification,
      suppressContinuityNotification,
    });

    expect(result).toBe(true);
    expect(acknowledgeContinuityRecovery).toHaveBeenCalledWith("replacement::planning:41");
    expect(applyLocation).not.toHaveBeenCalled();
  });

  it("acknowledges notifications without routing through recovery state", async () => {
    document.body.innerHTML = `
      <button
        id="notification-acknowledge"
        type="button"
        data-card-action="acknowledge"
        data-acknowledgement-key="notification:planning:41"
      >Acknowledge notification</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const acknowledgeContinuityRecovery = vi.fn();
    const acknowledgeContinuityNotification = vi.fn();
    const suppressContinuityNotification = vi.fn();
    const button = document.getElementById("notification-acknowledge");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing notification acknowledge button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery,
      acknowledgeContinuityNotification,
      suppressContinuityNotification,
    });

    expect(result).toBe(true);
    expect(acknowledgeContinuityNotification).toHaveBeenCalledWith("planning:41");
    expect(acknowledgeContinuityRecovery).not.toHaveBeenCalled();
  });

  it("suppresses notifications from shared event actions", async () => {
    document.body.innerHTML = `
      <button
        id="notification-suppress"
        type="button"
        data-card-action="event"
        data-notification-suppress-id="planning:41"
        data-notification-suppress-hours="24"
      >Hide for 1 day</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const acknowledgeContinuityRecovery = vi.fn();
    const acknowledgeContinuityNotification = vi.fn();
    const suppressContinuityNotification = vi.fn();
    const button = document.getElementById("notification-suppress");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing notification suppress button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery,
      acknowledgeContinuityNotification,
      suppressContinuityNotification,
    });

    expect(result).toBe(true);
    expect(suppressContinuityNotification).toHaveBeenCalledWith("planning:41", 24);
    expect(acknowledgeContinuityNotification).not.toHaveBeenCalled();
  });

  it("dispatches shared rerun actions", async () => {
    document.body.innerHTML = `
      <button
        id="rerun"
        type="button"
        data-card-action="rerun"
        data-rerun-handle='{"kind":"planning_session","sessionId":12,"sessionName":"Weekly reset"}'
        data-rerun-contract='{"mode":"refresh","provenanceLabel":"Planning session: Weekly reset","freshnessLabel":"1 target changed","strategySummary":"Reuse the saved planning session and refresh it against current loop state.","strictInvariants":["Same planning session identity"],"mayVary":["Checkpoint wording"],"postRun":{"summary":"Land back in the saved planning session.","location":{"state":"plan","recallTool":"chat","reviewFocus":"planning","sessionId":12,"loopId":null,"viewId":null,"memoryId":null,"workingSetId":7,"query":null}}}'
      >Refresh plan</button>
    `;

    const applyLocation = vi.fn().mockResolvedValue(undefined);
    const pinLocationToWorkingSet = vi.fn().mockResolvedValue(undefined);
    const executeUndoAction = vi.fn().mockResolvedValue(undefined);
    const executeRerunAction = vi.fn().mockResolvedValue(undefined);
    const button = document.getElementById("rerun");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing rerun button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
      executeUndoAction,
      executeRerunAction,
      acknowledgeContinuityRecovery: vi.fn(),
      acknowledgeContinuityNotification: vi.fn(),
      suppressContinuityNotification: vi.fn(),
    });

    expect(result).toBe(true);
    expect(executeRerunAction).toHaveBeenCalledTimes(1);
    expect(executeRerunAction.mock.calls[0]?.[0]).toMatchObject({
      type: "rerun",
      rerun: {
        kind: "planning_session",
        sessionId: 12,
        sessionName: "Weekly reset",
      },
      contract: {
        mode: "refresh",
        provenanceLabel: "Planning session: Weekly reset",
      },
    });
    expect(applyLocation).not.toHaveBeenCalled();
    expect(pinLocationToWorkingSet).not.toHaveBeenCalled();
    expect(executeUndoAction).not.toHaveBeenCalled();
  });
});
