/**
 * modals.ts - Surface-runtime re-export for the shared modal implementation.
 *
 * Purpose:
 *   Expose the canonical TypeScript modal runtime to the shared work-surface
 *   modules.
 *
 * Responsibilities:
 *   - Re-export the shared modal API for capture/do/recall modules.
 *
 * Scope:
 *   - Surface-runtime import surface only.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/*.ts modules.
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
