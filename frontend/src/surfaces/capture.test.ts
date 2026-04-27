/**
 * capture.test.ts - Regression tests for Quick Capture orchestration.
 *
 * Purpose:
 *   Verify the first-run Quick Capture form submits the canonical payload and
 *   gives clear validation, pending, success, and failure feedback.
 *
 * Responsibilities:
 *   - Assert successful captures update the Inbox through the loop module.
 *   - Guard failed or invalid submissions against silent no-op regressions.
 *   - Verify Save disables while an online submission is in flight.
 *
 * Scope:
 *   - Focused browser-side Quick Capture form behavior with mocked transport.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend exec vitest run src/surfaces/capture.test.ts`.
 *
 * Invariants/Assumptions:
 *   - Tests run under jsdom and do not hit the real backend.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import type { SurfaceLoop } from "./contracts";
import { init, submitCaptureLoop } from "./capture";
import { INVALID_DUE_DATE_MESSAGE } from "./utils";

const mocks = vi.hoisted(() => ({
  captureLoop: vi.fn(),
  replaceLoop: vi.fn(),
  state: { notificationPermissionRequested: true },
  updateState: vi.fn((nextState: { notificationPermissionRequested?: boolean }) => {
    if (typeof nextState.notificationPermissionRequested === "boolean") {
      mocks.state.notificationPermissionRequested = nextState.notificationPermissionRequested;
    }
  }),
}));

vi.mock("./api", () => ({
  captureLoop: mocks.captureLoop,
}));

vi.mock("./loop", () => ({
  replaceLoop: mocks.replaceLoop,
}));

vi.mock("./state", () => ({
  state: mocks.state,
  updateState: mocks.updateState,
}));

interface CaptureDomFixture {
  form: HTMLFormElement;
  rawText: HTMLTextAreaElement;
  actionable: HTMLInputElement;
  scheduled: HTMLInputElement;
  blocked: HTMLInputElement;
  dueDate: HTMLInputElement;
  nextAction: HTMLInputElement;
  timeMinutes: HTMLInputElement;
  activationEnergy: HTMLSelectElement;
  project: HTMLInputElement;
  tags: HTMLInputElement;
  templateSelect: HTMLSelectElement;
  status: HTMLElement;
  captureError: HTMLElement;
  captureSaveButton: HTMLButtonElement;
  statusFilter: HTMLSelectElement;
  tagFilter: HTMLSelectElement;
  queryFilter: HTMLInputElement;
}

function requireElement<T extends HTMLElement>(id: string, type: { new (): T }): T {
  const element = document.getElementById(id);
  if (!(element instanceof type)) {
    throw new Error(`Missing test element #${id}`);
  }
  return element;
}

function createFixture(
  requestNotificationPermission: () => Promise<boolean> | boolean = () => false,
): CaptureDomFixture {
  document.body.innerHTML = `
    <form id="capture-form" aria-busy="false">
      <textarea id="raw-text" aria-describedby="status capture-error"></textarea>
      <input type="checkbox" id="actionable">
      <input type="checkbox" id="scheduled">
      <input type="checkbox" id="blocked">
      <input id="due-date">
      <input id="next-action">
      <input id="time-minutes" type="number">
      <select id="activation-energy"><option value=""></option><option value="2">2</option></select>
      <input id="project">
      <input id="tags">
      <select id="template-select"><option value=""></option><option value="4">Template</option></select>
      <span id="status" role="status">Ready.</span>
      <p id="capture-error" role="alert" hidden></p>
      <button id="capture-save-btn" type="submit">Save to Inbox</button>
      <select id="status-filter"><option value="open" selected>open</option><option value="completed">completed</option></select>
      <select id="tag-filter"><option value="" selected>all</option><option value="work">work</option></select>
      <input id="query-filter">
    </form>
  `;

  const fixture = {
    form: requireElement("capture-form", HTMLFormElement),
    rawText: requireElement("raw-text", HTMLTextAreaElement),
    actionable: requireElement("actionable", HTMLInputElement),
    scheduled: requireElement("scheduled", HTMLInputElement),
    blocked: requireElement("blocked", HTMLInputElement),
    dueDate: requireElement("due-date", HTMLInputElement),
    nextAction: requireElement("next-action", HTMLInputElement),
    timeMinutes: requireElement("time-minutes", HTMLInputElement),
    activationEnergy: requireElement("activation-energy", HTMLSelectElement),
    project: requireElement("project", HTMLInputElement),
    tags: requireElement("tags", HTMLInputElement),
    templateSelect: requireElement("template-select", HTMLSelectElement),
    status: requireElement("status", HTMLElement),
    captureError: requireElement("capture-error", HTMLElement),
    captureSaveButton: requireElement("capture-save-btn", HTMLButtonElement),
    statusFilter: requireElement("status-filter", HTMLSelectElement),
    tagFilter: requireElement("tag-filter", HTMLSelectElement),
    queryFilter: requireElement("query-filter", HTMLInputElement),
  };
  init(fixture, { requestNotificationPermission });
  return fixture;
}

function submitEvent(): SubmitEvent {
  return new SubmitEvent("submit", { cancelable: true });
}

function createdLoop(overrides: Partial<SurfaceLoop> = {}): SurfaceLoop {
  return {
    id: 42,
    raw_text: "Email Alex",
    title: "Email Alex",
    status: "inbox",
    tags: [],
    ...overrides,
  } as SurfaceLoop;
}

describe("surfaces/capture", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    mocks.state.notificationPermissionRequested = true;
    vi.clearAllMocks();
  });

  it("posts the required capture payload, updates the Inbox, resets the form, and shows success", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "  Email Alex  ";
    fixture.actionable.checked = true;
    fixture.nextAction.value = "Send checklist";
    fixture.tags.value = "work, launch";
    const response = createdLoop({ id: 77, tags: ["work", "launch"] });
    mocks.captureLoop.mockResolvedValueOnce(response);

    await submitCaptureLoop(submitEvent());

    expect(mocks.captureLoop).toHaveBeenCalledTimes(1);
    expect(mocks.captureLoop.mock.calls[0]?.[0]).toMatchObject({
      raw_text: "Email Alex",
      actionable: true,
      scheduled: false,
      blocked: false,
      next_action: "Send checklist",
      tags: ["work", "launch"],
    });
    expect(mocks.captureLoop.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      captured_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
      client_tz_offset_min: expect.any(Number),
    }));
    expect(mocks.replaceLoop).toHaveBeenCalledWith(response);
    expect(fixture.rawText.value).toBe("");
    expect(fixture.nextAction.value).toBe("");
    expect(fixture.status.textContent).toBe("Saved to Inbox as #77.");
    expect(fixture.captureError.hidden).toBe(true);
  });

  it("shows local validation and does not call the API for blank text", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "   ";

    await submitCaptureLoop(submitEvent());

    expect(mocks.captureLoop).not.toHaveBeenCalled();
    expect(fixture.rawText.getAttribute("aria-invalid")).toBe("true");
    expect(fixture.captureError.hidden).toBe(false);
    expect(fixture.captureError.textContent).toContain("Type a task");
  });

  it("clears the blank-text invalid state after a later successful save", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "   ";
    await submitCaptureLoop(submitEvent());

    fixture.rawText.value = "Email Alex";
    mocks.captureLoop.mockResolvedValueOnce(createdLoop());
    await submitCaptureLoop(submitEvent());

    expect(fixture.rawText.hasAttribute("aria-invalid")).toBe(false);
    expect(fixture.captureError.hidden).toBe(true);
    expect(mocks.replaceLoop).toHaveBeenCalledTimes(1);
  });

  it("blocks submission and announces an invalid due date", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "Email Alex";
    fixture.dueDate.value = "13/40/2026";

    await submitCaptureLoop(submitEvent());

    expect(mocks.captureLoop).not.toHaveBeenCalled();
    expect(fixture.rawText.value).toBe("Email Alex");
    expect(fixture.dueDate.getAttribute("aria-invalid")).toBe("true");
    expect(fixture.captureError.hidden).toBe(false);
    expect(fixture.captureError.textContent).toBe(INVALID_DUE_DATE_MESSAGE);
    expect(fixture.status.textContent).toBe(INVALID_DUE_DATE_MESSAGE);
  });

  it("preserves input and shows an inline error when the server rejects capture", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "Email Alex";
    fixture.project.value = "Launch";
    mocks.captureLoop.mockRejectedValueOnce(new Error("Backend said no"));

    await submitCaptureLoop(submitEvent());

    expect(fixture.rawText.value).toBe("Email Alex");
    expect(fixture.project.value).toBe("Launch");
    expect(fixture.captureSaveButton.disabled).toBe(false);
    expect(fixture.captureError.hidden).toBe(false);
    expect(fixture.captureError.textContent).toContain("Backend said no");
    expect(fixture.captureError.textContent).toContain("Your text is still here");
    expect(mocks.replaceLoop).not.toHaveBeenCalled();
  });

  it("disables Save and reports pending state while a capture is in flight", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "Email Alex";
    let resolveCapture!: (value: SurfaceLoop) => void;
    const pendingCapture = new Promise<SurfaceLoop>((resolve) => {
      resolveCapture = resolve;
    });
    mocks.captureLoop.mockReturnValueOnce(pendingCapture);

    const submission = submitCaptureLoop(submitEvent());

    expect(fixture.captureSaveButton.disabled).toBe(true);
    expect(fixture.captureSaveButton.textContent).toBe("Saving…");
    expect(fixture.form.getAttribute("aria-busy")).toBe("true");
    expect(fixture.status.textContent).toBe("Saving to Inbox…");

    resolveCapture(createdLoop());
    await submission;

    expect(fixture.captureSaveButton.disabled).toBe(false);
    expect(fixture.captureSaveButton.textContent).toBe("Save to Inbox");
    expect(fixture.form.getAttribute("aria-busy")).toBe("false");
  });

  it("does not reset or update the Inbox when the service worker only queued offline capture", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "Email Alex";
    mocks.captureLoop.mockResolvedValueOnce({ queued: true, offline: true });

    await submitCaptureLoop(submitEvent());

    expect(mocks.replaceLoop).not.toHaveBeenCalled();
    expect(fixture.rawText.value).toBe("Email Alex");
    expect(fixture.status.textContent).toContain("Queued offline");
  });

  it("explains when active filters may hide the saved loop", async () => {
    const fixture = createFixture();
    fixture.rawText.value = "Email Alex";
    fixture.queryFilter.value = "project:other";
    mocks.captureLoop.mockResolvedValueOnce(createdLoop({ id: 88 }));

    await submitCaptureLoop(submitEvent());

    expect(fixture.status.textContent).toBe("Saved to Inbox as #88. Clear the current Inbox filters to see it.");
  });

  it("does not mark notification permission as requested when the permission flow fails", async () => {
    mocks.state.notificationPermissionRequested = false;
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fixture = createFixture(() => Promise.reject(new Error("permission failed")));
    fixture.rawText.value = "Email Alex";
    mocks.captureLoop.mockResolvedValueOnce(createdLoop());

    await submitCaptureLoop(submitEvent());
    await Promise.resolve();

    expect(mocks.updateState).not.toHaveBeenCalledWith({ notificationPermissionRequested: true });
    expect(mocks.state.notificationPermissionRequested).toBe(false);
    expect(warning).toHaveBeenCalledWith(
      "Notification permission request failed; will retry after the next capture.",
      expect.any(Error),
    );
    warning.mockRestore();
  });
});
