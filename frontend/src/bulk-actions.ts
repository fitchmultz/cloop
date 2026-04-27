/**
 * bulk-actions.ts - Shared bulk-selection UI helpers.
 *
 * Purpose:
 *   Keep the visual bulk-action bar and loop-card selected state in sync with
 *   the canonical selection set shared across the frontend runtime.
 *
 * Responsibilities:
 *   - Show or hide the bulk action bar based on current selection.
 *   - Update the selected-loop count label.
 *   - Reflect selection state onto loop cards and checkboxes.
 *
 * Scope:
 *   - DOM synchronization for bulk-selection chrome only.
 *
 * Usage:
 *   - Imported by TypeScript surfaces that clear or mutate loop selections.
 *   - Re-exported by frontend/src/surfaces/bulk.ts for shared surface flows.
 *
 * Invariants/Assumptions:
 *   - The bulk action bar uses the `#bulk-action-bar` id.
 *   - Loop cards and checkboxes expose loop ids through `data-loop-id`.
 */

import { parseLoopId, selectedLoopIds } from "./selection-state";

export function updateBulkActionBar(): void {
  if (typeof document === "undefined") {
    return;
  }

  const bulkActionBar = document.getElementById("bulk-action-bar");
  const count = selectedLoopIds.size;

  if (bulkActionBar) {
    bulkActionBar.classList.toggle("visible", count > 0);
    const countElement = bulkActionBar.querySelector<HTMLElement>(".bulk-count");
    if (countElement) {
      countElement.textContent = `${count} loop${count === 1 ? "" : "s"} selected`;
    }
  }

  document.querySelectorAll<HTMLElement>(".loop-card[data-loop-id]").forEach((card) => {
    const loopId = parseLoopId(card.dataset["loopId"] ?? undefined);
    const isSelected = loopId != null && selectedLoopIds.has(loopId);
    card.classList.toggle("selected", isSelected);

    const checkbox = card.querySelector<HTMLInputElement>(".loop-checkbox");
    if (checkbox) {
      checkbox.checked = isSelected;
    }
  });
}
