/**
 * capture.ts - Quick Capture form orchestration.
 *
 * Purpose:
 *   Own Quick Capture payload creation, submission state, feedback, and reset
 *   behavior for the shared capture surface.
 *
 * Responsibilities:
 *   - Validate required task text and user-entered capture metadata.
 *   - Build the canonical `/loops/capture` payload with client timestamp fields.
 *   - Submit captures with pending, success, offline-queued, and error states.
 *   - Reset form fields only after confirmed server-created loop responses.
 *
 * Scope:
 *   - Browser-side Quick Capture form behavior only.
 *
 * Usage:
 *   - Initialized by frontend/src/surfaces/bootstrap.ts with DOM elements.
 *
 * Invariants/Assumptions:
 *   - The backend requires raw_text, captured_at, and client_tz_offset_min.
 *   - Offline service-worker queue responses are not created loops and should not
 *     be inserted into the Inbox as if creation was confirmed.
 */

import type { LoopCaptureRequest } from "../domain";
import * as api from "./api";
import type { SurfaceLoop } from "./contracts";
import * as loop from "./loop";
import * as state from "./state";
import {
  formatDateInputValue,
  INVALID_DUE_DATE_MESSAGE,
  messageFromError,
  parseUserDateInput,
} from "./utils";

interface CaptureElements {
  status: HTMLElement;
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
  captureSaveButton: HTMLButtonElement;
  captureError: HTMLElement;
  statusFilter: HTMLSelectElement;
  tagFilter: HTMLSelectElement;
  queryFilter: HTMLInputElement;
}

interface CapturePayloadBuildResult {
  payload: LoopCaptureRequest;
}

interface OfflineQueuedCapture {
  queued: true;
  offline: true;
}

type CaptureFeedbackKind = "idle" | "pending" | "success" | "error";

type NotificationPermissionRequester = () => Promise<boolean> | boolean;

let elements!: CaptureElements;
let requestNotificationPermission: NotificationPermissionRequester = () => false;
let captureSubmitting = false;

function isInitialized(): boolean {
  return Boolean(elements);
}

export function init(
  nextElements: CaptureElements,
  options: { requestNotificationPermission?: NotificationPermissionRequester } = {},
): void {
  elements = nextElements;
  requestNotificationPermission = options.requestNotificationPermission ?? (() => false);
  captureSubmitting = false;
  setCaptureSubmitting(false);
  setCaptureFeedback("idle", "Ready.");
}

function requireInitialized(): void {
  if (!isInitialized()) {
    throw new Error("Capture surface has not been initialized.");
  }
}

function setCaptureSubmitting(isSubmitting: boolean): void {
  requireInitialized();
  elements.form.setAttribute("aria-busy", isSubmitting ? "true" : "false");
  elements.captureSaveButton.disabled = isSubmitting;
  elements.captureSaveButton.textContent = isSubmitting ? "Saving…" : "Save to Inbox";
}

function setCaptureFeedback(kind: CaptureFeedbackKind, message: string): void {
  requireInitialized();
  elements.status.textContent = message;
  elements.status.classList.toggle("is-error", kind === "error");
  elements.status.classList.toggle("is-success", kind === "success");
  elements.status.classList.toggle("is-pending", kind === "pending");
  elements.captureError.hidden = kind !== "error";
  elements.captureError.textContent = kind === "error" ? message : "";
}

function setRawTextInvalid(isInvalid: boolean): void {
  if (isInvalid) {
    elements.rawText.setAttribute("aria-invalid", "true");
    return;
  }
  elements.rawText.removeAttribute("aria-invalid");
}

export function formatDueDateInput(): void {
  requireInitialized();
  const formattedValue = formatDateInputValue(elements.dueDate.value);
  if (elements.dueDate.value !== formattedValue) {
    elements.dueDate.value = formattedValue;
  }
  elements.dueDate.removeAttribute("aria-invalid");
}

export function normalizeDueDateField(): { parsedDate: ReturnType<typeof parseUserDateInput>; isValid: boolean } {
  requireInitialized();
  const rawValue = elements.dueDate.value.trim();
  if (!rawValue) {
    elements.dueDate.value = "";
    elements.dueDate.removeAttribute("aria-invalid");
    return { parsedDate: null, isValid: true };
  }

  const parsedDate = parseUserDateInput(rawValue);
  if (!parsedDate) {
    elements.dueDate.setAttribute("aria-invalid", "true");
    return { parsedDate: null, isValid: false };
  }

  elements.dueDate.value = parsedDate.displayValue;
  elements.dueDate.removeAttribute("aria-invalid");
  return { parsedDate, isValid: true };
}

export function reportDueDateValidationResult(): void {
  const { isValid } = normalizeDueDateField();
  if (!isValid) {
    setCaptureFeedback("error", INVALID_DUE_DATE_MESSAGE);
    return;
  }
  if (elements.status.textContent === INVALID_DUE_DATE_MESSAGE) {
    setCaptureFeedback("idle", "Ready.");
  }
}

function buildCapturePayload(): CapturePayloadBuildResult | null {
  const { parsedDate, isValid: isDueDateValid } = normalizeDueDateField();
  if (!isDueDateValid) {
    setCaptureFeedback("error", INVALID_DUE_DATE_MESSAGE);
    elements.dueDate.focus();
    elements.dueDate.select();
    return null;
  }

  const rawText = elements.rawText.value.trim();
  if (!rawText) {
    setRawTextInvalid(true);
    elements.rawText.focus();
    setCaptureFeedback("error", "Type a task, idea, or reminder before saving.");
    return null;
  }
  setRawTextInvalid(false);

  const now = new Date();
  const templateId = elements.templateSelect.value;
  const payload: LoopCaptureRequest = {
    raw_text: rawText,
    captured_at: now.toISOString(),
    client_tz_offset_min: -now.getTimezoneOffset(),
    actionable: elements.actionable.checked,
    scheduled: elements.scheduled.checked,
    blocked: elements.blocked.checked,
  };

  if (templateId) {
    payload.template_id = Number.parseInt(templateId, 10);
  }
  if (parsedDate) {
    payload.due_date = parsedDate.isoDate;
  }
  if (elements.nextAction.value.trim()) {
    payload.next_action = elements.nextAction.value.trim();
  }
  if (elements.timeMinutes.value) {
    payload.time_minutes = Number.parseInt(elements.timeMinutes.value, 10);
  }
  if (elements.activationEnergy.value) {
    payload.activation_energy = Number.parseInt(elements.activationEnergy.value, 10);
  }
  if (elements.project.value.trim()) {
    payload.project = elements.project.value.trim();
  }
  if (elements.tags.value.trim()) {
    payload.tags = elements.tags.value.split(",")
      .map((tag) => tag.trim())
      .filter((tag) => tag.length > 0);
  }

  return { payload };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isCreatedSurfaceLoop(value: unknown): value is SurfaceLoop {
  return isRecord(value)
    && typeof value["id"] === "number"
    && typeof value["raw_text"] === "string"
    && typeof value["status"] === "string";
}

function isOfflineQueuedCapture(value: unknown): value is OfflineQueuedCapture {
  return isRecord(value) && value["queued"] === true && value["offline"] === true;
}

function resetCaptureForm(): void {
  elements.rawText.value = "";
  elements.actionable.checked = false;
  elements.scheduled.checked = false;
  elements.blocked.checked = false;
  elements.templateSelect.value = "";
  elements.dueDate.value = "";
  elements.nextAction.value = "";
  elements.timeMinutes.value = "";
  elements.activationEnergy.value = "";
  elements.project.value = "";
  elements.tags.value = "";
  setRawTextInvalid(false);
  elements.dueDate.removeAttribute("aria-invalid");
}

function captureResultMayBeHidden(loopValue: Pick<SurfaceLoop, "status" | "tags">): boolean {
  const statusValue = elements.statusFilter.value || "open";
  const tagValue = elements.tagFilter.value || "";
  const queryValue = elements.queryFilter.value.trim();
  if (queryValue) {
    return true;
  }
  if (statusValue === "open") {
    return !new Set(["inbox", "actionable", "blocked", "scheduled"]).has(loopValue.status);
  }
  if (statusValue !== "all" && statusValue !== loopValue.status) {
    return true;
  }
  const tags = Array.isArray(loopValue.tags) ? loopValue.tags : [];
  return Boolean(tagValue && tagValue !== "all" && !tags.includes(tagValue));
}

function successMessageFor(loopValue: SurfaceLoop): string {
  if (captureResultMayBeHidden(loopValue)) {
    return `Saved to Inbox as #${loopValue.id}. Clear the current Inbox filters to see it.`;
  }
  return `Saved to Inbox as #${loopValue.id}.`;
}

async function requestNotificationsOnce(): Promise<void> {
  if (state.state.notificationPermissionRequested) {
    return;
  }

  try {
    await requestNotificationPermission();
    state.updateState({ notificationPermissionRequested: true });
  } catch (error: unknown) {
    console.warn("Notification permission request failed; will retry after the next capture.", error);
  }
}

export async function submitCaptureLoop(event: SubmitEvent): Promise<void> {
  requireInitialized();
  event.preventDefault();
  if (captureSubmitting) {
    return;
  }

  const built = buildCapturePayload();
  if (!built) {
    return;
  }

  captureSubmitting = true;
  setCaptureSubmitting(true);
  setCaptureFeedback("pending", navigator.onLine ? "Saving to Inbox…" : "Trying to save…");
  void requestNotificationsOnce();

  try {
    const result: unknown = await api.captureLoop(built.payload);

    if (isOfflineQueuedCapture(result)) {
      setCaptureFeedback(
        "success",
        "Queued offline. Your text is still here until it appears in Inbox after sync.",
      );
      return;
    }

    if (!isCreatedSurfaceLoop(result)) {
      throw new Error("Capture returned an unexpected response. Your text is still here.");
    }

    loop.replaceLoop(result);
    resetCaptureForm();
    setCaptureFeedback("success", successMessageFor(result));
  } catch (error: unknown) {
    setCaptureFeedback("error", `${messageFromError(error, "Capture failed.")} Your text is still here.`);
  } finally {
    captureSubmitting = false;
    setCaptureSubmitting(false);
  }
}
