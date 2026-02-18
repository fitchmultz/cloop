/**
 * modals.js - Modal handling
 *
 * Purpose:
 *   Manage modal dialogs and overlays.
 *
 * Responsibilities:
 *   - Help modal show/hide
 *   - Modal backdrop clicks
 *   - Modal state tracking
 *
 * Non-scope:
 *   - Merge modal (see duplicates.js)
 *   - Bulk confirmation (see bulk.js)
 *   - Keyboard shortcuts (see keyboard.js)
 */

let helpModal;
let isHelpModalOpen = false;

/**
 * Initialize modals module
 */
export function init(elements) {
  helpModal = elements.helpModal;

  // Close modal on overlay click
  helpModal.addEventListener("click", (event) => {
    if (event.target === helpModal) {
      showHelpModal(false);
    }
  });

  // Close modal button handler
  const closeBtn = helpModal.querySelector("[data-action=close-help]");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => showHelpModal(false));
  }
}

/**
 * Show or hide help modal
 */
export function showHelpModal(show) {
  if (show) {
    helpModal.classList.add("visible");
    helpModal.querySelector(".help-modal").focus();
    isHelpModalOpen = true;
  } else {
    helpModal.classList.remove("visible");
    isHelpModalOpen = false;
  }
}

/**
 * Check if any modal is open
 */
export function isModalOpen() {
  return isHelpModalOpen ||
    document.getElementById("bulk-confirm-modal")?.classList.contains("visible") ||
    document.getElementById("mergeModal")?.classList.contains("visible");
}
