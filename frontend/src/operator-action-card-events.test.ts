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
    const button = document.getElementById("stage");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing stage button");
    }

    const handled = await handleOperatorActionCardClick(new MouseEvent("click", { bubbles: true, composed: true }), {
      applyLocation,
      pinLocationToWorkingSet,
    });

    expect(handled).toBe(false);

    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });
    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
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
    const button = document.getElementById("edit");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing edit button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
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
    const button = document.getElementById("defer");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing defer button");
    }
    const event = new MouseEvent("click", { bubbles: true, composed: true });
    Object.defineProperty(event, "target", { value: button });

    const result = await handleOperatorActionCardClick(event, {
      applyLocation,
      pinLocationToWorkingSet,
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
  });
});
