/**
 * window.d.ts - Global browser type extensions for legacy-compatible handlers.
 *
 * Purpose:
 *   Extend the global Window shape so strict TypeScript can model browser hooks
 *   used by preserved modal and notification integrations.
 *
 * Responsibilities:
 *   - Declare global merge-modal callbacks used by inline HTML handlers.
 *   - Provide a typed home for additional window-level shell hooks as needed.
 *
 * Scope:
 *   - Global browser typing only.
 *
 * Usage:
 *   - Imported automatically by TypeScript through the frontend tsconfig include set.
 *
 * Invariants/Assumptions:
 *   - Inline HTML hooks remain during the Phase 0 behavior-preserving cutover.
 */

export {};

declare global {
  interface Window {
    closeMergeModal: () => void;
    confirmMerge: () => void;
  }
}
