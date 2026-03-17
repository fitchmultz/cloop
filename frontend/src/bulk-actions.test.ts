/**
 * bulk-actions.test.ts - Regression tests for shared selection and bulk-bar sync.
 *
 * Purpose:
 *   Verify the TypeScript-owned selection and bulk-action helpers stay aligned
 *   with loop-card DOM state during the frontend cutover.
 *
 * Responsibilities:
 *   - Assert range selection follows visible loop ordering.
 *   - Assert bulk-action bar visibility and checkbox/card selection stay in sync.
 *
 * Scope:
 *   - DOM-backed unit tests for selection-state.ts and bulk-actions.ts.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests run under Vitest's jsdom environment.
 *   - Loop cards expose ids through `data-loop-id` and use `.loop-checkbox`.
 */

import { updateBulkActionBar } from "./bulk-actions";
import {
  clearLoopSelection,
  selectedLoopIds,
  selectLoopRange,
  toggleLoopSelection,
} from "./selection-state";

function renderLoopCard(loopId: number): string {
  return `
    <article class="loop-card" data-loop-id="${loopId}">
      <div class="badges"></div>
      <input class="loop-checkbox" data-loop-id="${loopId}" type="checkbox">
    </article>
  `;
}

describe("selection-state + bulk-actions", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="bulk-action-bar" class="bulk-action-bar">
        <span class="bulk-count"></span>
      </div>
      ${renderLoopCard(11)}
      ${renderLoopCard(12)}
      ${renderLoopCard(13)}
    `;
    clearLoopSelection();
  });

  afterEach(() => {
    clearLoopSelection();
    document.body.innerHTML = "";
  });

  it("selects an inclusive visible range in DOM order", () => {
    selectLoopRange(11, 13);

    expect(Array.from(selectedLoopIds)).toEqual([11, 12, 13]);
  });

  it("syncs the bulk bar, loop-card class, and checkbox state", () => {
    toggleLoopSelection(12, true);
    toggleLoopSelection(13, true);

    updateBulkActionBar();

    const bulkBar = document.getElementById("bulk-action-bar");
    const count = bulkBar?.querySelector(".bulk-count");
    const selectedCard = document.querySelector<HTMLElement>('.loop-card[data-loop-id="12"]');
    const selectedCheckbox = document.querySelector<HTMLInputElement>('.loop-checkbox[data-loop-id="12"]');
    const unselectedCard = document.querySelector<HTMLElement>('.loop-card[data-loop-id="11"]');

    expect(bulkBar?.classList.contains("visible")).toBe(true);
    expect(count?.textContent).toBe("2 loops selected");
    expect(selectedCard?.classList.contains("selected")).toBe(true);
    expect(selectedCheckbox?.checked).toBe(true);
    expect(unselectedCard?.classList.contains("selected")).toBe(false);

    clearLoopSelection();
    updateBulkActionBar();

    expect(bulkBar?.classList.contains("visible")).toBe(false);
    expect(selectedCheckbox?.checked).toBe(false);
  });
});
