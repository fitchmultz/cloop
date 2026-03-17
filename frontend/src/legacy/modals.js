/**
 * modals.js - Legacy compatibility re-export for the shared modal runtime.
 *
 * Purpose:
 *   Preserve the legacy import path while the TypeScript-owned modal runtime is
 *   the canonical implementation.
 *
 * Responsibilities:
 *   - Re-export the shared modal API for untouched legacy modules.
 *
 * Scope:
 *   - Compatibility import surface only.
 *
 * Usage:
 *   - Imported by residual legacy JavaScript modules during the frontend
 *     cutover.
 *
 * Invariants/Assumptions:
 *   - frontend/src/modals.ts remains the source of truth for modal behavior.
 */

export {
  MERGE_MODAL_CLOSE_REQUEST_EVENT,
  alertDialog,
  closeActiveModal,
  confirmDialog,
  init,
  isModalOpen,
  promptDialog,
  showDialog,
  showHelpModal,
} from "../modals";
