/**
 * duplicates.ts - Surface-runtime re-export for duplicate-merge helpers.
 *
 * Purpose:
 *   Expose the canonical TypeScript duplicate runtime to capture/do surfaces.
 *
 * Responsibilities:
 *   - Re-export duplicate badge and merge-modal helpers for surface modules.
 *
 * Scope:
 *   - Surface-runtime import surface only.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/*.ts modules.
 *
 * Invariants/Assumptions:
 *   - frontend/src/duplicates.ts remains the source of truth for merge-modal
 *     behavior.
 */

export {
  SURFACE_RUNTIME_REFRESH_EVENT,
  checkAndShowDuplicateBadges,
  closeMergeModal,
  confirmMerge,
  openMergeModal,
  setupMergeHandlers,
} from "../duplicates";
