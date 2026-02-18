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
