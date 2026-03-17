/**
 * duplicates.js - Legacy compatibility re-export for duplicate-merge runtime.
 *
 * Purpose:
 *   Preserve the legacy duplicate-module import path while the TypeScript-owned
 *   duplicate runtime is the canonical implementation.
 *
 * Responsibilities:
 *   - Re-export duplicate badge and merge-modal helpers for untouched legacy
 *     surfaces.
 *
 * Scope:
 *   - Compatibility import surface only.
 *
 * Usage:
 *   - Imported by residual legacy JavaScript modules during the frontend
 *     cutover.
 *
 * Invariants/Assumptions:
 *   - frontend/src/duplicates.ts remains the source of truth for merge-modal
 *     behavior.
 */

export {
  LEGACY_RUNTIME_REFRESH_EVENT,
  checkAndShowDuplicateBadges,
  closeMergeModal,
  confirmMerge,
  openMergeModal,
  setupMergeHandlers,
} from "../duplicates";
