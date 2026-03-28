/**
 * utils.ts - Shared utility helpers for the work-surface runtime.
 *
 * Purpose:
 *   Provide strict TypeScript helpers for date formatting, DOM target guards,
 *   status messaging, and user-input normalization across capture/do/recall.
 *
 * Responsibilities:
 *   - Safely escape HTML and normalize freeform user input.
 *   - Convert loop due dates and local date/time inputs.
 *   - Surface consistent error messages from unknown exceptions.
 *   - Provide DOM-target helpers for strict event handling.
 *
 * Scope:
 *   - Surface-runtime utility functions only.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/* modules.
 *
 * Invariants/Assumptions:
 *   - Browser locale formatting is acceptable for human-facing timestamps.
 *   - SurfaceLoop due-date fields follow backend LoopResponse semantics.
 */

import type { SurfaceLoop } from "./contracts";

export const INVALID_DUE_DATE_MESSAGE = "Enter a valid due date as MM/DD/YYYY.";

interface ParsedUserDateInput {
  year: number;
  month: number;
  day: number;
  isoDate: string;
  displayValue: string;
}

export function messageFromError(error: unknown, fallback = "Unexpected error"): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

export function parseInteger(value: string | null | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) ? parsed : null;
}

export function closestFromEventTarget<T extends Element = Element>(
  target: EventTarget | null,
  selector: string,
): T | null {
  if (!(target instanceof Element)) {
    return null;
  }
  return target.closest(selector) as T | null;
}

export function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatTime(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString([], {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function toLocalInputValue(isoValue: string | null | undefined): string {
  if (!isoValue) {
    return "";
  }
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export function isoFromLocalInput(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

function localDateFromIsoDate(value: string | null | undefined): Date | null {
  const match = String(value ?? "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return null;
  }

  const yearText = match[1] ?? "0";
  const monthText = match[2] ?? "0";
  const dayText = match[3] ?? "0";
  const year = Number.parseInt(yearText, 10);
  const month = Number.parseInt(monthText, 10);
  const day = Number.parseInt(dayText, 10);
  return new Date(year, month - 1, day);
}

export function formatIsoDate(value: string | null | undefined): string {
  const date = localDateFromIsoDate(value);
  if (!date) {
    return "";
  }
  return date.toLocaleDateString([], {
    year: "numeric",
    month: "numeric",
    day: "numeric",
  });
}

export function formatDueValue(loop: Pick<SurfaceLoop, "due_date" | "due_at_utc">): string {
  if (loop.due_date) {
    return formatIsoDate(loop.due_date);
  }
  if (loop.due_at_utc) {
    return formatTime(loop.due_at_utc);
  }
  return "";
}

export function formatDueLabel(loop: Pick<SurfaceLoop, "due_date" | "due_at_utc">): string {
  const formattedValue = formatDueValue(loop);
  return formattedValue ? `Due ${formattedValue}` : "Set due date";
}

export function dueDateInputValueFromLoop(
  loop: Pick<SurfaceLoop, "due_date" | "due_at_utc">,
): string {
  let date: Date | null = null;
  if (loop.due_date) {
    date = localDateFromIsoDate(loop.due_date);
  } else if (loop.due_at_utc) {
    date = new Date(loop.due_at_utc);
  }

  if (!date || Number.isNaN(date.getTime())) {
    return "";
  }

  return [
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
    String(date.getFullYear()).padStart(4, "0"),
  ].join("/");
}

export function localTimeInputValueFromIso(isoValue: string | null | undefined): string {
  if (!isoValue) {
    return "";
  }
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function isoFromLocalDateAndTime(
  isoDate: string | null | undefined,
  timeValue: string | null | undefined,
): string | null {
  if (!isoDate || !timeValue) {
    return null;
  }

  const dateParts = String(isoDate).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const timeParts = String(timeValue).match(/^(\d{2}):(\d{2})$/);
  if (!dateParts || !timeParts) {
    return null;
  }

  const yearText = dateParts[1] ?? "0";
  const monthText = dateParts[2] ?? "0";
  const dayText = dateParts[3] ?? "0";
  const hourText = timeParts[1] ?? "0";
  const minuteText = timeParts[2] ?? "0";
  const year = Number.parseInt(yearText, 10);
  const month = Number.parseInt(monthText, 10);
  const day = Number.parseInt(dayText, 10);
  const hours = Number.parseInt(hourText, 10);
  const minutes = Number.parseInt(minuteText, 10);
  const date = new Date(year, month - 1, day, hours, minutes, 0, 0);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

export function formatDateInputValue(value: string | null | undefined): string {
  const rawValue = String(value ?? "").trim();
  if (!rawValue) {
    return "";
  }

  if (/^[\d/\-]+$/.test(rawValue) && /[\/-]/.test(rawValue)) {
    return rawValue.slice(0, 10);
  }

  const digits = rawValue
    .replace(/\D/g, "")
    .slice(0, 8);

  if (digits.length <= 2) {
    return digits;
  }
  if (digits.length <= 4) {
    return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  }
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

export function parseUserDateInput(value: string | null | undefined): ParsedUserDateInput | null {
  const rawValue = String(value ?? "").trim();
  if (!rawValue) {
    return null;
  }

  let month: number;
  let day: number;
  let year: number;

  const usMatch = rawValue.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (usMatch) {
    const monthText = usMatch[1] ?? "0";
    const dayText = usMatch[2] ?? "0";
    const yearText = usMatch[3] ?? "0";
    month = Number.parseInt(monthText, 10);
    day = Number.parseInt(dayText, 10);
    year = Number.parseInt(yearText, 10);
  } else {
    const isoMatch = rawValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!isoMatch) {
      return null;
    }
    const yearText = isoMatch[1] ?? "0";
    const monthText = isoMatch[2] ?? "0";
    const dayText = isoMatch[3] ?? "0";
    year = Number.parseInt(yearText, 10);
    month = Number.parseInt(monthText, 10);
    day = Number.parseInt(dayText, 10);
  }

  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    Number.isNaN(parsed.getTime())
    || parsed.getUTCFullYear() !== year
    || parsed.getUTCMonth() !== month - 1
    || parsed.getUTCDate() !== day
  ) {
    return null;
  }

  const isoDate = [
    String(year).padStart(4, "0"),
    String(month).padStart(2, "0"),
    String(day).padStart(2, "0"),
  ].join("-");

  return {
    year,
    month,
    day,
    isoDate,
    displayValue: `${String(month).padStart(2, "0")}/${String(day).padStart(2, "0")}/${String(year).padStart(4, "0")}`,
  };
}

export function describeKnowledgeIngestError(
  error: unknown,
  health: Record<string, unknown> | null,
): string {
  const directMessage = messageFromError(error, "Knowledge ingestion failed.");
  if (directMessage !== "Knowledge ingestion failed." && directMessage !== "Unexpected server error") {
    return directMessage;
  }

  const embedModelValue = health?.["embed_model"];
  const embedModel = typeof embedModelValue === "string" ? embedModelValue.trim() : "";
  if (!embedModel) {
    return "Knowledge ingestion needs a working embedding provider. Check the local embedding configuration, then try again.";
  }

  if (embedModel.startsWith("ollama/")) {
    return `Knowledge ingestion needs a running Ollama embedding server for ${embedModel}. Start Ollama or point CLOOP_OLLAMA_API_BASE at a running instance, then try again.`;
  }
  if (embedModel.startsWith("openai/")) {
    return `Knowledge ingestion needs a valid OpenAI embedding configuration for ${embedModel}. Set CLOOP_OPENAI_API_KEY, restart the app, then try again.`;
  }
  if (embedModel.startsWith("gemini/")) {
    return `Knowledge ingestion needs a valid Google embedding configuration for ${embedModel}. Set CLOOP_GOOGLE_API_KEY, restart the app, then try again.`;
  }

  return `Knowledge ingestion needs a working embedding provider for ${embedModel}. Check the local provider configuration, restart the app if needed, then try again.`;
}

export function normalizeTags(value: string | null | undefined): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((tag) => tag.trim().toLowerCase())
    .filter(Boolean);
}

export function snoozeDurationToUtc(duration: string): string | null {
  const now = Date.now();
  let ms = 0;

  if (duration.endsWith("h")) {
    ms = Number.parseInt(duration, 10) * 60 * 60 * 1000;
  } else if (duration.endsWith("d")) {
    ms = Number.parseInt(duration, 10) * 24 * 60 * 60 * 1000;
  } else if (duration.endsWith("w")) {
    ms = Number.parseInt(duration, 10) * 7 * 24 * 60 * 60 * 1000;
  } else {
    return null;
  }

  if (!Number.isFinite(ms) || ms <= 0) {
    return null;
  }
  return new Date(now + ms).toISOString();
}
