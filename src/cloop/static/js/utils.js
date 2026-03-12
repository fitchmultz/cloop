/**
 * utils.js - Shared utility functions
 *
 * Purpose:
 *   Provide common helper functions used across modules.
 *
 * Responsibilities:
 *   - HTML escaping for security
 *   - Date/time formatting
 *   - Tag normalization
 *   - Input value conversion
 *
 * Non-scope:
 *   - API calls (see api.js)
 *   - DOM rendering (see render.js)
 *   - State management (see state.js)
 */

/**
 * Escape HTML to prevent XSS
 */
export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Format ISO timestamp to local string
 */
export function formatTime(value) {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

/**
 * Convert ISO timestamp to datetime-local input value
 */
export function toLocalInputValue(isoValue) {
  if (!isoValue) return "";
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "";
  const offsetMs = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

/**
 * Convert datetime-local input value to ISO string
 */
export function isoFromLocalInput(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

/**
 * Format freeform date input as MM/DD/YYYY while the user types.
 */
export function formatDateInputValue(value) {
  const digits = String(value ?? "")
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

/**
 * Parse user-entered due date values.
 * Accepts MM/DD/YYYY, M/D/YYYY, and YYYY-MM-DD.
 */
export function parseUserDateInput(value) {
  const rawValue = String(value ?? "").trim();
  if (!rawValue) {
    return null;
  }

  let month;
  let day;
  let year;

  const usMatch = rawValue.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (usMatch) {
    month = Number.parseInt(usMatch[1], 10);
    day = Number.parseInt(usMatch[2], 10);
    year = Number.parseInt(usMatch[3], 10);
  } else {
    const isoMatch = rawValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!isoMatch) {
      return null;
    }
    year = Number.parseInt(isoMatch[1], 10);
    month = Number.parseInt(isoMatch[2], 10);
    day = Number.parseInt(isoMatch[3], 10);
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

/**
 * Normalize tags from comma-separated string to array
 */
export function normalizeTags(value) {
  if (!value) return [];
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/**
 * Convert snooze duration string to UTC timestamp
 */
export function snoozeDurationToUtc(duration) {
  const now = new Date();
  let ms = 0;

  if (duration.endsWith('h')) {
    ms = parseInt(duration) * 60 * 60 * 1000;
  } else if (duration.endsWith('d')) {
    ms = parseInt(duration) * 24 * 60 * 60 * 1000;
  } else if (duration.endsWith('w')) {
    ms = parseInt(duration) * 7 * 24 * 60 * 60 * 1000;
  } else {
    return null;
  }

  return new Date(now.getTime() + ms).toISOString();
}
