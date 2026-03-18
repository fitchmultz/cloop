/**
 * selection-state.ts - Shared loop-selection state for bulk actions.
 *
 * Purpose:
 *   Centralize loop-selection state so shell, review, and work surfaces observe
 *   the same selected-loop set.
 *
 * Responsibilities:
 *   - Hold the canonical selected-loop id set.
 *   - Provide selection helpers for single, range, visible-all, and clear flows.
 *   - Emit a browser event when selection changes so UI layers can react when
 *     needed.
 *
 * Scope:
 *   - Browser-only loop-card selection state.
 *
 * Usage:
 *   - Imported directly by TypeScript modules.
 *   - Re-exported by frontend/src/surfaces/state.ts for shared surface code.
 *
 * Invariants/Assumptions:
 *   - Loop cards expose integer ids through `data-loop-id`.
 *   - Selection order itself is not meaningful; the Set is the source of truth.
 */

export const LOOP_SELECTION_CHANGED_EVENT = "cloop:loop-selection-changed";
export const selectedLoopIds = new Set<number>();

function parseLoopId(raw: string | undefined): number | null {
  if (!raw) {
    return null;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isInteger(parsed) ? parsed : null;
}

function notifySelectionChanged(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(
    new CustomEvent(LOOP_SELECTION_CHANGED_EVENT, {
      detail: { selectedLoopIds: Array.from(selectedLoopIds) },
    }),
  );
}

export function toggleLoopSelection(loopId: number, isSelected: boolean): void {
  const hadLoop = selectedLoopIds.has(loopId);
  if (isSelected) {
    selectedLoopIds.add(loopId);
  } else {
    selectedLoopIds.delete(loopId);
  }
  if (selectedLoopIds.has(loopId) !== hadLoop) {
    notifySelectionChanged();
  }
}

export function clearLoopSelection(): void {
  if (!selectedLoopIds.size) {
    return;
  }
  selectedLoopIds.clear();
  notifySelectionChanged();
}

export function getVisibleLoopIds(): number[] {
  if (typeof document === "undefined") {
    return [];
  }
  return Array.from(document.querySelectorAll<HTMLElement>(".loop-card[data-loop-id]"))
    .map((card) => parseLoopId(card.dataset["loopId"] ?? undefined))
    .filter((loopId): loopId is number => loopId != null);
}

export function selectAllVisibleLoops(): void {
  let changed = false;
  getVisibleLoopIds().forEach((loopId) => {
    if (!selectedLoopIds.has(loopId)) {
      selectedLoopIds.add(loopId);
      changed = true;
    }
  });
  if (changed) {
    notifySelectionChanged();
  }
}

export function selectLoopRange(fromId: number, toId: number): void {
  const visibleIds = getVisibleLoopIds();
  const fromIndex = visibleIds.indexOf(fromId);
  const toIndex = visibleIds.indexOf(toId);
  if (fromIndex < 0 || toIndex < 0) {
    return;
  }

  const start = Math.min(fromIndex, toIndex);
  const end = Math.max(fromIndex, toIndex);
  let changed = false;
  for (let index = start; index <= end; index += 1) {
    const loopId = visibleIds[index];
    if (loopId != null && !selectedLoopIds.has(loopId)) {
      selectedLoopIds.add(loopId);
      changed = true;
    }
  }
  if (changed) {
    notifySelectionChanged();
  }
}
