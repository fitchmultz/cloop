/**
 * coerce-json-integer.ts - Parse integer ids from JSON/web payloads.
 *
 * Accepts integer numbers and decimal integer strings (after trim). Used by
 * shell location normalization and planning launch-surface `web` objects so
 * numeric ids stay consistent whether the transport used numbers or strings.
 */

export function coerceJsonInteger(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseInt(value, 10);
    return Number.isInteger(parsed) ? parsed : null;
  }
  return null;
}
