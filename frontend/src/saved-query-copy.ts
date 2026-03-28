/**
 * saved-query-copy.ts - Shared saved-query wording helpers.
 *
 * Purpose:
 *   Keep saved-query context wording consistent across shell surfaces without
 *   repeating inline string formatting.
 *
 * Responsibilities:
 *   - Format one saved-query trust/context source label.
 *   - Fall back to the caller-provided label when no query is available.
 *
 * Scope:
 *   - Frontend copy helpers for saved-query labels only.
 *
 * Usage:
 *   - Import `savedQueryContextSource` where trust/context lists reference a
 *     saved query.
 *
 * Invariants/Assumptions:
 *   - Query text is plain text and may be blank.
 *   - Callers own any escaping/rendering after label construction.
 */

export function savedQueryContextSource(
  query: string | null | undefined,
  fallbackLabel: string,
): string {
  const normalizedQuery = query?.trim();
  return normalizedQuery ? `Saved query: ${normalizedQuery}` : fallbackLabel;
}
