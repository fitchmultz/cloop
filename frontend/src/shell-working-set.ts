/**
 * shell-working-set.ts - Working-set session state, rendering, and mutations.
 *
 * Purpose:
 *   Own the operator shell's working-set session UI and the focused mutations
 *   that create, update, resume, and pin working-set context.
 *
 * Responsibilities:
 *   - Load and refresh working-set/session context from shared HTTP routes.
 *   - Render working-set session surfaces, banners, and operator cards.
 *   - Manage focus mode and active working-set context.
 *   - Create working sets and pin shell locations or loops into them.
 *
 * Scope:
 *   - Working-set-specific shell behavior only.
 *
 * Usage:
 *   - Created by frontend/src/shell.ts and consumed by shell workspace and
 *     event modules.
 *
 * Invariants/Assumptions:
 *   - Working sets remain the canonical durable bounded-context surface.
 *   - Operator-zone rerenders after working-set changes must preserve behavior.
 *   - Stored working-set state is refreshed from HTTP after every mutation.
 */

import { createReceiptCard, withReceiptOutcome } from "./action-receipts";
import { buildWorkingSetUndoAction } from "./executable-undo";
import { HttpRequestError, requestJson } from "./http";
import * as modals from "./modals";
import { recordRecentShellAction } from "./continuity-intelligence";
import { escapeHtml, formatRelativeTime, loopPreview, loopTitle } from "./shell-core";
import {
  createLocation,
  locationsMatch,
  openLocationAttributes,
  workingSetSessionLocation,
} from "./shell-routing";
import type {
  WorkingSetBulkItemCreateRequest,
  WorkingSetContextResponse,
  WorkingSetContextUpdateRequest,
  WorkingSetDeleteResponse,
  WorkingSetItemCreateRequest,
  WorkingSetItemResponse,
  WorkingSetResponse,
} from "./domain";
import type { WorkingSetSessionMetadata, OperatorActionCardAction } from "./contracts-ui";
import type { ShellElements, ShellLocation, WorkspaceData } from "./shell-types";

export interface ShellWorkingSetController {
  getLatestWorkingSets(): WorkingSetResponse[];
  getWorkingSetContext(): WorkingSetContextResponse | null;
  promptForWorkingSetDetails(
    defaults?: { name?: string; description?: string },
  ): Promise<{ name: string; description: string | null } | null>;
  confirmWorkingSetDeletion(name: string): Promise<boolean>;
  loadWorkingSetState(): Promise<void>;
  refreshWorkingSetState(): Promise<void>;
  workingSetItemLocation(item: WorkingSetItemResponse): ShellLocation;
  focusModeActiveSet(): WorkingSetResponse | null;
  workingSetFromLocation(location: ShellLocation): WorkingSetResponse | null;
  renderWorkingSet(data: WorkspaceData | null): void;
  renderWorkingSetFocusBanner(): void;
  syncFocusModeClass(): void;
  renderWorkingSetSessionSurface(): void;
  setWorkingSetContext(
    activeWorkingSetId: number | null,
    focusModeEnabled: boolean,
    options?: { recordHistory?: boolean },
  ): Promise<void>;
  createWorkingSetViaDialog(): Promise<WorkingSetResponse | null>;
  ensureActiveWorkingSetId(): Promise<number | null>;
  updateWorkingSet(workingSetId: number, details: { name: string; description: string | null }): Promise<void>;
  deleteWorkingSet(workingSetId: number): Promise<void>;
  reorderWorkingSetItems(workingSetId: number, orderedItemIds: number[]): Promise<void>;
  removeWorkingSetItem(workingSetId: number, itemId: number): Promise<void>;
  pinLocationToWorkingSet(
    location: ShellLocation,
    label: string,
    description: string | null,
    options?: { receiptVariant?: "pin" | "stage" | "defer" },
  ): Promise<void>;
  addLoopIdsToActiveWorkingSet(loopIds: readonly number[]): Promise<void>;
}

interface CreateShellWorkingSetControllerOptions {
  getElements: () => ShellElements | null;
  getCurrentLocation: () => ShellLocation;
  getLatestWorkspaceData: () => WorkspaceData | null;
  renderOperatorZones: (data: WorkspaceData) => void;
}

export function createShellWorkingSetController(
  options: CreateShellWorkingSetControllerOptions,
): ShellWorkingSetController {
  let latestWorkingSets: WorkingSetResponse[] = [];
  let workingSetContext: WorkingSetContextResponse | null = null;

  async function promptForWorkingSetDetails(
    defaults: { name?: string; description?: string } = {},
  ): Promise<{ name: string; description: string | null } | null> {
    const result = await modals.promptDialog({
      eyebrow: "Working set",
      title: defaults.name ? "Update working set" : "Create a working set",
      description:
        "Save a bounded cross-surface context so you can resume the exact loops, sessions, and saved items that matter later.",
      confirmLabel: defaults.name ? "Save changes" : "Create set",
      fields: [
        {
          name: "name",
          label: "Name",
          value: defaults.name ?? "",
          required: true,
          maxLength: 120,
          placeholder: "Launch cleanup, hiring pass, weekly reset…",
        },
        {
          name: "description",
          label: "Description",
          type: "textarea",
          rows: 4,
          value: defaults.description ?? "",
          maxLength: 280,
          placeholder: "What bounded slice of the system does this set hold together?",
        },
      ],
      validate(values: Record<string, string>): string | null {
        const name = values["name"]?.trim() ?? "";
        if (!name) {
          return "Name is required.";
        }
        return null;
      },
    });
    if (!result) {
      return null;
    }
    const name = typeof result["name"] === "string" ? result["name"].trim() : "";
    if (!name) {
      return null;
    }
    const descriptionValue = typeof result["description"] === "string" ? result["description"].trim() : "";
    return {
      name,
      description: descriptionValue || null,
    };
  }

  async function confirmWorkingSetDeletion(name: string): Promise<boolean> {
    return modals.confirmDialog({
      eyebrow: "Working set",
      title: "Delete working set",
      description: `Delete “${name}”? The saved context, ordering, and focus history will be removed.`,
      confirmLabel: "Delete set",
    });
  }

  async function loadWorkingSetState(): Promise<void> {
    try {
      const [sets, context] = await Promise.all([
        requestJson<WorkingSetResponse[]>("/loops/working-sets", {}, "Failed to load working sets"),
        requestJson<WorkingSetContextResponse>(
          "/loops/working-sets/context",
          {},
          "Failed to load working-set focus state",
        ),
      ]);
      latestWorkingSets = sets;
      workingSetContext = context;
    } catch {
      latestWorkingSets = [];
      workingSetContext = null;
    }
  }

  function workingSetItemLocation(item: WorkingSetItemResponse): ShellLocation {
    const launch = item.launch;
    return createLocation({
      state: launch.state,
      recallTool: launch.recall_tool,
      reviewFocus: launch.review_focus,
      sessionId: launch.session_id,
      loopId: launch.loop_id,
      viewId: launch.view_id,
      memoryId: launch.memory_id,
      workingSetId: launch.working_set_id,
      query: launch.query,
      includeLoopContext: launch.include_loop_context ?? null,
      includeMemoryContext: launch.include_memory_context ?? null,
      includeRagContext: launch.include_rag_context ?? null,
    });
  }

  function isGenericStateAnchorLocation(location: ShellLocation): boolean {
    return location.loopId == null
      && location.sessionId == null
      && (location.viewId ?? null) == null
      && (location.memoryId ?? null) == null
      && !location.query;
  }

  function focusModeActiveSet(): WorkingSetResponse | null {
    return workingSetContext?.active_working_set ?? null;
  }

  function workingSetFromLocation(location: ShellLocation): WorkingSetResponse | null {
    const requestedId =
      location.state === "working_set"
        ? (location.workingSetId ?? workingSetContext?.active_working_set_id ?? null)
        : null;
    if (requestedId == null) {
      return null;
    }
    return latestWorkingSets.find((set) => set.id === requestedId)
      ?? (workingSetContext?.active_working_set_id === requestedId ? workingSetContext.active_working_set : null)
      ?? null;
  }

  function workingSetMetadata(workingSet: WorkingSetResponse | null): WorkingSetSessionMetadata | null {
    if (!workingSet) {
      return null;
    }
    return {
      workingSetId: workingSet.id,
      workingSetName: workingSet.name,
      itemCount: workingSet.item_count,
      missingItemCount: workingSet.missing_item_count,
    };
  }

  function appendUndoAction(
    actions: OperatorActionCardAction[] | undefined,
    undoAction: OperatorActionCardAction | null,
  ): OperatorActionCardAction[] {
    return [...(actions ?? []), ...(undoAction ? [undoAction] : [])];
  }

  function contextUndoAction(context: WorkingSetContextResponse): OperatorActionCardAction | null {
    const activeSet = context.active_working_set ?? null;
    return buildWorkingSetUndoAction(context, {
      description: activeSet != null
        ? `Restore the prior working-set context before switching into ${activeSet.name}.`
        : "Restore the prior working-set context and focus mode.",
      workingSetId: activeSet?.id ?? null,
      workingSetName: activeSet?.name ?? null,
      successLocation: activeSet != null
        ? workingSetSessionLocation(activeSet.id)
        : createLocation({ state: "operator" }),
    });
  }

  function workingSetUndoAction(
    workingSet: WorkingSetResponse | null,
    description: string,
  ): OperatorActionCardAction | null {
    if (!workingSet) {
      return null;
    }
    return buildWorkingSetUndoAction(workingSet, {
      description,
      workingSetId: workingSet.id,
      workingSetName: workingSet.name,
      successLocation: workingSetSessionLocation(workingSet.id),
    });
  }

  function recordWorkingSetReceipt(params: {
    kind: "working_set" | "working_set_session";
    historyLabel: string;
    historyDescription: string;
    title: string;
    summary: string;
    tone: "neutral" | "attention" | "progress" | "caution";
    location: ShellLocation;
    workingSet: WorkingSetResponse | null;
    rollbackLabel: string;
    nextStep: string;
    preview?: Array<{ label: string; value: string }>;
    actions?: OperatorActionCardAction[];
  }): void {
    const handoffWorkingSet = workingSetMetadata(params.workingSet);
    const resumeLocation = params.workingSet
      ? workingSetSessionLocation(params.workingSet.id)
      : params.location;
    const receiptCard = createReceiptCard({
      id: `working-set-receipt-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      eyebrow: "Working-set receipt",
      title: params.title,
      summary: params.summary,
      rationale:
        "Working-set receipts preserve what changed, where the bounded context now lives, and how to reopen it without rebuilding state.",
      tone: params.tone,
      preview: params.preview ?? [],
      trust: {
        generationLabel: "Durable continuity mutation",
        generationTone: "progress",
        contextSources: handoffWorkingSet
          ? [`Working set: ${handoffWorkingSet.workingSetName}`]
          : ["Working-set controller"],
        assumptions: ["The working set remains the canonical bounded context for this handoff."],
        confidenceLabel: handoffWorkingSet
          ? `Saved in ${handoffWorkingSet.workingSetName}`
          : "Working-set change recorded",
        confidenceTone: "progress",
        freshnessLabel: "Saved just now",
        freshnessTone: "progress",
        rollbackLabel: params.rollbackLabel,
        rollbackTone: "caution",
        impactSummary: params.summary,
        impactTone: params.tone,
      },
      handoff: {
        changeSummary: params.summary,
        createdResources: handoffWorkingSet ? [handoffWorkingSet.workingSetName] : [],
        nextStep: params.nextStep,
        breadcrumbs: ["Home", "Working set", handoffWorkingSet?.workingSetName ?? "Session"],
        workingSet: handoffWorkingSet,
      },
      resumeLocation,
      resumeLabel: handoffWorkingSet ? "Open working set" : "Resume outcome",
      resumeDescription: params.summary,
      pinLabel: handoffWorkingSet ? `Working set · ${handoffWorkingSet.workingSetName}` : null,
      actions: params.actions ?? [],
    });

    recordRecentShellAction(
      withReceiptOutcome(
        {
          kind: params.kind,
          label: params.historyLabel,
          description: params.historyDescription,
          location: params.location,
        },
        receiptCard,
        resumeLocation,
      ),
    );
  }

  function renderWorkingSetItemCard(workingSetId: number, item: WorkingSetItemResponse): string {
    const location = workingSetItemLocation(item);
    return `
      <article class="working-set-item-card${item.missing ? " working-set-item-card--missing" : ""}">
        <div class="working-set-card-header">
          <div>
            <p class="support-eyebrow">${escapeHtml(item.kind_label)}</p>
            <h4>${escapeHtml(item.label)}</h4>
            <p>${escapeHtml(item.description)}</p>
          </div>
          <span class="operator-chip">${escapeHtml(item.missing ? "Missing" : item.status_label ?? "Ready")}</span>
        </div>
        <div class="operator-card-actions">
          <button type="button" ${openLocationAttributes(location)}>Open</button>
          <button class="secondary" type="button" data-working-set-move="${workingSetId}:${item.id}:up">Earlier</button>
          <button class="secondary" type="button" data-working-set-move="${workingSetId}:${item.id}:down">Later</button>
          <button class="secondary" type="button" data-remove-working-set-item="${workingSetId}:${item.id}">Remove</button>
        </div>
      </article>
    `;
  }

  function renderWorkingSetSessionSurface(): void {
    const elements = options.getElements();
    if (!elements) {
      return;
    }

    const workingSet = workingSetFromLocation(options.getCurrentLocation());
    if (!workingSet) {
      elements.workingSetMain.innerHTML = `
        <section class="working-set-session-hero">
          <p class="operator-empty">This working-set session is no longer available. Return home and choose another working set.</p>
          <div class="operator-inline-actions">
            <button type="button" data-open-state="operator">Return home</button>
          </div>
        </section>
      `;
      return;
    }

    const focusEnabled =
      Boolean(workingSetContext?.focus_mode_enabled)
      && workingSetContext?.active_working_set_id === workingSet.id;
    const firstLaunchable = (workingSet.items ?? []).find((item) => !item.missing)
      ?? workingSet.items?.[0]
      ?? null;

    elements.workingSetMain.innerHTML = `
      <section class="working-set-session-hero panel">
        <div class="working-set-card-header">
          <div>
            <p class="support-eyebrow">Working-set session</p>
            <h2>${escapeHtml(workingSet.name)}</h2>
            <p>${escapeHtml(workingSet.description ?? "Saved bounded cross-surface context.")}</p>
          </div>
          <div class="operator-chip-row">
            <span class="operator-chip">${workingSet.item_count} item${workingSet.item_count === 1 ? "" : "s"}</span>
            ${workingSet.missing_item_count ? `<span class="operator-chip">${workingSet.missing_item_count} missing</span>` : ""}
            ${focusEnabled ? '<span class="operator-chip">Focus mode</span>' : '<span class="operator-chip">Session</span>'}
          </div>
        </div>
        <div class="operator-card-actions">
          <button type="button" data-working-set-focus="${workingSet.id}">${focusEnabled ? "Pause focus mode" : "Enter focus mode"}</button>
          ${
            firstLaunchable
              ? `<button class="secondary" type="button" ${openLocationAttributes(workingSetItemLocation(firstLaunchable))}>Open first item</button>`
              : ""
          }
          <button class="secondary" type="button" data-open-state="operator">Return home</button>
        </div>
      </section>

      <section class="working-set-session-list panel">
        <div class="working-set-card-header">
          <div>
            <p class="support-eyebrow">Ordered context</p>
            <h3>All saved items</h3>
            <p>Launch any member without losing the rest of the working set.</p>
          </div>
        </div>
        <div class="working-set-item-grid">
          ${
            (workingSet.items ?? []).length
              ? (workingSet.items ?? []).map((item) => renderWorkingSetItemCard(workingSet.id, item)).join("")
              : '<p class="operator-empty">This working set is empty. Pin loops, sessions, views, or locations to make it resumable.</p>'
          }
        </div>
      </section>
    `;
  }

  function renderWorkingSetFocusBanner(): void {
    const elements = options.getElements();
    if (!elements) {
      return;
    }
    const activeSet = focusModeActiveSet();
    const focusEnabled = Boolean(workingSetContext?.focus_mode_enabled && activeSet);
    elements.workingSetFocusBanner.hidden = !activeSet;
    if (!activeSet) {
      elements.workingSetFocusSummary.innerHTML = "";
      elements.workingSetFocusItems.innerHTML = "";
      return;
    }
    elements.workingSetFocusToggleButton.textContent = focusEnabled ? "Pause focus" : "Focus";
    elements.workingSetFocusSummary.innerHTML = `
      <div>
        <p class="support-eyebrow">${focusEnabled ? "Focused" : "Saved focus"}</p>
        <h2>${escapeHtml(activeSet.name)}</h2>
        <p>${escapeHtml(activeSet.description ?? "A saved bounded slice of loops, sessions, and saved items.")}</p>
      </div>
      <div class="working-set-focus-meta">
        <span class="operator-chip">${activeSet.item_count} item${activeSet.item_count === 1 ? "" : "s"}</span>
        ${activeSet.missing_item_count ? `<span class="operator-chip">${activeSet.missing_item_count} missing</span>` : ""}
        ${activeSet.last_activated_at_utc ? `<span class="support-status">Resumed ${escapeHtml(formatRelativeTime(activeSet.last_activated_at_utc))}</span>` : ""}
      </div>
    `;
    const activeItems = activeSet.items ?? [];
    elements.workingSetFocusItems.innerHTML = activeItems.length
      ? activeItems.slice(0, 4).map((item) => renderWorkingSetItemCard(activeSet.id, item)).join("")
      : '<p class="operator-empty">This working set is empty. Pin a loop, session, or location to make focus mode useful.</p>';
  }

  function syncFocusModeClass(): void {
    const enabled = Boolean(workingSetContext?.focus_mode_enabled && workingSetContext.active_working_set);
    document.body.classList.toggle("shell-focus-mode", enabled);
  }

  function renderWorkingSet(_data: WorkspaceData | null): void {
    const elements = options.getElements();
    if (!elements) {
      return;
    }

    if (!latestWorkingSets.length) {
      elements.operatorWorkingSet.innerHTML = `
        <p class="operator-empty">Save a bounded slice of loops, sessions, and saved items so you can resume the exact context later.</p>
        <div class="operator-inline-actions">
          <button type="button" id="operator-working-set-empty-create" data-working-set-create>Build your first working set</button>
        </div>
      `;
      return;
    }

    const activeId = workingSetContext?.active_working_set_id ?? null;
    elements.operatorWorkingSet.innerHTML = latestWorkingSets
      .map((set) => {
        const isActive = activeId === set.id;
        const isFocused = isActive && Boolean(workingSetContext?.focus_mode_enabled);
        const setItems = set.items ?? [];
        return `
          <article class="working-set-card${isActive ? " working-set-card--active" : ""}">
            <div class="working-set-card-header">
              <div>
                <h3>${escapeHtml(set.name)}</h3>
                <p>${escapeHtml(set.description ?? "Saved focus context.")}</p>
              </div>
              <div class="operator-chip-row">
                <span class="operator-chip">${set.item_count} item${set.item_count === 1 ? "" : "s"}</span>
                ${set.missing_item_count ? `<span class="operator-chip">${set.missing_item_count} missing</span>` : ""}
                ${isFocused ? '<span class="operator-chip">Focus</span>' : isActive ? '<span class="operator-chip">Active</span>' : ""}
              </div>
            </div>
            <div class="working-set-item-grid">
              ${setItems.length
                ? setItems.slice(0, 3).map((item) => renderWorkingSetItemCard(set.id, item)).join("")
                : '<p class="operator-empty">This set is empty. Add a loop, session, or location from Life home.</p>'}
            </div>
            <div class="operator-card-actions">
              <button type="button" ${openLocationAttributes(workingSetSessionLocation(set.id))}>${isActive ? "Resume set" : "Open session"}</button>
              <button class="secondary" type="button" data-working-set-focus="${set.id}">${isFocused ? "Pause focus" : "Focus"}</button>
              <button class="secondary" type="button" data-working-set-edit="${set.id}">Rename</button>
              <button class="secondary" type="button" data-working-set-delete="${set.id}">Delete</button>
            </div>
          </article>
        `;
      })
      .join("");
  }

  async function refreshWorkingSetState(): Promise<void> {
    await loadWorkingSetState();
    const latestWorkspaceData = options.getLatestWorkspaceData();
    if (latestWorkspaceData) {
      options.renderOperatorZones(latestWorkspaceData);
    }
    renderWorkingSet(latestWorkspaceData);
    renderWorkingSetFocusBanner();
    syncFocusModeClass();
    if (options.getCurrentLocation().state === "working_set") {
      renderWorkingSetSessionSurface();
    }
  }

  async function setWorkingSetContext(
    activeWorkingSetId: number | null,
    focusModeEnabled: boolean,
    requestOptions: { recordHistory?: boolean } = {},
  ): Promise<void> {
    const updatedContext = await requestJson<WorkingSetContextResponse, WorkingSetContextUpdateRequest>(
      "/loops/working-sets/context",
      {
        method: "PATCH",
        body: {
          active_working_set_id: activeWorkingSetId,
          focus_mode_enabled: focusModeEnabled,
        },
      },
      "Failed to update working-set focus state",
    );
    await refreshWorkingSetState();

    if (requestOptions.recordHistory === false) {
      return;
    }

    const activeSet = workingSetContext?.active_working_set ?? null;
    const location =
      activeWorkingSetId != null
        ? workingSetSessionLocation(activeWorkingSetId)
        : createLocation({ state: "operator" });

    recordWorkingSetReceipt({
      kind: activeWorkingSetId != null ? "working_set_session" : "working_set",
      historyLabel:
        activeSet != null
          ? `${focusModeEnabled ? "Focused" : "Opened"} working set · ${activeSet.name}`
          : "Cleared active working set",
      historyDescription:
        activeSet?.description ?? "Updated the active working-set session context.",
      title:
        activeSet != null
          ? `${focusModeEnabled ? "Focus mode updated" : "Working set activated"} · ${activeSet.name}`
          : "Returned to Life home",
      summary:
        activeSet != null
          ? `${activeSet.name} is now the live bounded context for the shell.`
          : "No working set is currently scoping the shell.",
      tone: activeSet != null ? "attention" : "neutral",
      location,
      workingSet: activeSet,
      rollbackLabel:
        activeSet != null
          ? "Pause focus mode or clear the active working set to undo this context switch."
          : "Open any saved working set to restore bounded context.",
      nextStep:
        activeSet != null
          ? "Resume the session or open a pinned item from the working set."
          : "Choose another working set if you want to restore a bounded slice of context.",
      preview: activeSet != null
        ? [
            { label: "Working set", value: activeSet.name },
            { label: "Items", value: `${activeSet.item_count}` },
            { label: "Mode", value: focusModeEnabled ? "Focus mode" : "Session" },
          ]
        : [],
      actions: appendUndoAction(undefined, contextUndoAction(updatedContext)),
    });
  }

  async function showWorkingSetRequestError(title: string, error: unknown): Promise<void> {
    const description = error instanceof HttpRequestError || error instanceof Error
      ? error.message
      : "Unexpected working-set error.";
    await modals.alertDialog({ eyebrow: "Working set", title, description });
  }

  async function createWorkingSetViaDialog(): Promise<WorkingSetResponse | null> {
    const details = await promptForWorkingSetDetails();
    if (!details) {
      return null;
    }
    let created: WorkingSetResponse;
    try {
      created = await requestJson<WorkingSetResponse, { name: string; description: string | null }>(
        "/loops/working-sets",
        {
          method: "POST",
          body: details,
        },
        "Failed to create working set",
      );
    } catch (error) {
      await showWorkingSetRequestError("Could not create working set", error);
      return null;
    }
    await refreshWorkingSetState();
    const hydrated = latestWorkingSets.find((set) => set.id === created.id) ?? created;
    recordWorkingSetReceipt({
      kind: "working_set_session",
      historyLabel: `Created working set · ${hydrated.name}`,
      historyDescription: hydrated.description ?? "Created a new bounded context.",
      title: `Created working set · ${hydrated.name}`,
      summary: "A new resumable bounded context is ready.",
      tone: "progress",
      location: workingSetSessionLocation(hydrated.id),
      workingSet: hydrated,
      rollbackLabel: "Delete the working set if you do not want to keep this bounded context.",
      nextStep: "Add loops or locations, then reopen the session from the landed outcome.",
      preview: [
        { label: "Working set", value: hydrated.name },
        { label: "Description", value: hydrated.description ?? "No description" },
      ],
      actions: appendUndoAction(
        undefined,
        workingSetUndoAction(
          hydrated,
          `Delete ${hydrated.name} and restore the prior unscoped working-set state.`,
        ),
      ),
    });
    return hydrated;
  }

  async function ensureActiveWorkingSetId(): Promise<number | null> {
    let activeWorkingSetId = workingSetContext?.active_working_set_id ?? null;
    if (activeWorkingSetId != null) {
      return activeWorkingSetId;
    }
    const created = await createWorkingSetViaDialog();
    if (!created) {
      return null;
    }
    activeWorkingSetId = created.id;
    await setWorkingSetContext(created.id, false, { recordHistory: false });
    return activeWorkingSetId;
  }

  async function updateWorkingSet(
    workingSetId: number,
    details: { name: string; description: string | null },
  ): Promise<void> {
    const previous = latestWorkingSets.find((set) => set.id === workingSetId) ?? null;
    try {
      await requestJson<WorkingSetResponse, { name: string; description: string | null }>(
        `/loops/working-sets/${workingSetId}`,
        {
          method: "PATCH",
          body: details,
        },
        "Failed to update working set",
      );
    } catch (error) {
      await showWorkingSetRequestError("Could not update working set", error);
      return;
    }
    await refreshWorkingSetState();
    const updated = latestWorkingSets.find((set) => set.id === workingSetId) ?? null;
    if (!updated) {
      return;
    }
    recordWorkingSetReceipt({
      kind: "working_set_session",
      historyLabel: `Updated working set · ${updated.name}`,
      historyDescription: updated.description ?? "Updated working-set details.",
      title: `Updated working set · ${updated.name}`,
      summary: previous && previous.name !== updated.name
        ? `Renamed ${previous.name} to ${updated.name} and saved the bounded context.`
        : `${updated.name} now has refreshed session details.`,
      tone: "progress",
      location: workingSetSessionLocation(updated.id),
      workingSet: updated,
      rollbackLabel: "Edit the working set again to restore the previous name or description.",
      nextStep: "Resume the session to continue from the updated bounded context.",
      preview: [
        { label: "Working set", value: updated.name },
        { label: "Description", value: updated.description ?? "No description" },
      ],
      actions: appendUndoAction(
        undefined,
        workingSetUndoAction(
          updated,
          `Restore the previous saved details for ${updated.name}.`,
        ),
      ),
    });
  }

  async function deleteWorkingSet(workingSetId: number): Promise<void> {
    const existing = latestWorkingSets.find((set) => set.id === workingSetId) ?? null;
    const deleted = await requestJson<WorkingSetDeleteResponse>(
      `/loops/working-sets/${workingSetId}`,
      { method: "DELETE" },
      "Failed to delete working set",
    );
    if (workingSetContext?.active_working_set_id === workingSetId) {
      await setWorkingSetContext(null, false, { recordHistory: false });
    } else {
      await refreshWorkingSetState();
    }
    recordWorkingSetReceipt({
      kind: "working_set",
      historyLabel: existing ? `Deleted working set · ${existing.name}` : `Deleted working set #${workingSetId}`,
      historyDescription: existing?.description ?? "Removed a saved bounded context.",
      title: existing ? `Deleted working set · ${existing.name}` : "Deleted working set",
      summary: existing
        ? `${existing.name} and its saved items were removed.`
        : `Working set #${workingSetId} and its saved items were removed.`, 
      tone: "caution",
      location: createLocation({ state: "operator" }),
      workingSet: null,
      rollbackLabel: "Recreate the working set manually if you still need this bounded context.",
      nextStep: "Open another working set or continue from Life home.",
      preview: existing
        ? [
            { label: "Removed set", value: existing.name },
            { label: "Removed items", value: `${existing.item_count}` },
          ]
        : [],
      actions: appendUndoAction(
        undefined,
        buildWorkingSetUndoAction(deleted, {
          description: existing != null
            ? `Restore ${existing.name} and its saved items.`
            : `Restore deleted working set #${workingSetId}.`,
          workingSetId: deleted.deleted_working_set_id,
          workingSetName: deleted.deleted_working_set_name ?? existing?.name ?? null,
          successLocation: workingSetSessionLocation(deleted.deleted_working_set_id),
        }),
      ),
    });
  }

  async function reorderWorkingSetItems(workingSetId: number, orderedItemIds: number[]): Promise<void> {
    const workingSet = latestWorkingSets.find((set) => set.id === workingSetId) ?? null;
    await requestJson<WorkingSetResponse, { ordered_item_ids: number[] }>(
      `/loops/working-sets/${workingSetId}/reorder`,
      {
        method: "POST",
        body: { ordered_item_ids: orderedItemIds },
      },
      "Failed to reorder working-set items",
    );
    await refreshWorkingSetState();
    const refreshed = latestWorkingSets.find((set) => set.id === workingSetId) ?? workingSet;
    recordWorkingSetReceipt({
      kind: "working_set",
      historyLabel: refreshed ? `Reordered items · ${refreshed.name}` : `Reordered working set #${workingSetId}`,
      historyDescription: "Updated the saved item order.",
      title: refreshed ? `Reordered items · ${refreshed.name}` : "Reordered working-set items",
      summary: refreshed
        ? `${refreshed.name} now reflects the new priority order.`
        : "The saved item order was updated.",
      tone: "progress",
      location: refreshed ? workingSetSessionLocation(refreshed.id) : createLocation({ state: "operator" }),
      workingSet: refreshed,
      rollbackLabel: "Reorder the saved items again if you want a different sequence.",
      nextStep: "Open the working set to continue from the new top-of-stack order.",
      preview: refreshed
        ? [
            { label: "Working set", value: refreshed.name },
            { label: "Items", value: `${orderedItemIds.length}` },
          ]
        : [{ label: "Items", value: `${orderedItemIds.length}` }],
      actions: appendUndoAction(
        undefined,
        workingSetUndoAction(
          refreshed,
          refreshed != null
            ? `Restore the previous item order for ${refreshed.name}.`
            : "Restore the previous working-set item order.",
        ),
      ),
    });
  }

  async function removeWorkingSetItem(workingSetId: number, itemId: number): Promise<void> {
    const workingSet = latestWorkingSets.find((set) => set.id === workingSetId) ?? null;
    const removedItem = workingSet?.items?.find((item) => item.id === itemId) ?? null;
    await requestJson<WorkingSetResponse>(
      `/loops/working-sets/${workingSetId}/items/${itemId}`,
      { method: "DELETE" },
      "Failed to remove working-set item",
    );
    await refreshWorkingSetState();
    const refreshed = latestWorkingSets.find((set) => set.id === workingSetId) ?? workingSet;
    recordWorkingSetReceipt({
      kind: "working_set",
      historyLabel: removedItem ? `Removed item · ${removedItem.label}` : `Removed working-set item #${itemId}`,
      historyDescription: removedItem?.description ?? "Removed a saved item from the working set.",
      title: removedItem ? `Removed item · ${removedItem.label}` : "Removed working-set item",
      summary: removedItem
        ? `${removedItem.label} is no longer pinned in this working set.`
        : `Removed item #${itemId} from the working set.`,
      tone: "caution",
      location: refreshed ? workingSetSessionLocation(refreshed.id) : createLocation({ state: "operator" }),
      workingSet: refreshed,
      rollbackLabel: "Pin the same location or loop again if you want to restore this item.",
      nextStep: "Resume the working set to continue with the remaining items.",
      preview: [
        ...(removedItem ? [{ label: "Removed item", value: removedItem.label }] : []),
        ...(refreshed ? [{ label: "Working set", value: refreshed.name }] : []),
      ],
      actions: appendUndoAction(
        undefined,
        workingSetUndoAction(
          refreshed,
          removedItem != null
            ? `Restore ${removedItem.label} to this working set.`
            : "Restore the removed working-set item.",
        ),
      ),
    });
  }

  async function pinLocationToWorkingSet(
    location: ShellLocation,
    label: string,
    description: string | null,
    receiptOptions: { receiptVariant?: "pin" | "stage" | "defer" } = {},
  ): Promise<void> {
    const activeWorkingSetId = await ensureActiveWorkingSetId();
    if (activeWorkingSetId == null) {
      return;
    }

    const pinnedLocation = createLocation({
      ...location,
      workingSetId: location.workingSetId ?? activeWorkingSetId,
    });

    const existingItems = workingSetContext?.active_working_set?.items ?? [];
    const genericStateAnchor = isGenericStateAnchorLocation(pinnedLocation);
    const alreadyPresent = existingItems.some((item) => {
      if (!locationsMatch(workingSetItemLocation(item), pinnedLocation)) {
        return false;
      }
      if (!genericStateAnchor) {
        return true;
      }
      return item.label.trim() === label.trim();
    });
    if (alreadyPresent) {
      return;
    }

    const metadata: Record<string, unknown> = {};
    let itemType: WorkingSetItemCreateRequest["item_type"] = "state_anchor";
    let itemId: number | null = null;

    if (pinnedLocation.loopId != null) {
      itemType = "loop";
      itemId = pinnedLocation.loopId;
    } else if (pinnedLocation.state === "plan" && pinnedLocation.sessionId != null) {
      itemType = "planning_session";
      itemId = pinnedLocation.sessionId;
    } else if (pinnedLocation.reviewFocus === "relationship" && pinnedLocation.sessionId != null) {
      itemType = "relationship_review_session";
      itemId = pinnedLocation.sessionId;
    } else if (pinnedLocation.reviewFocus === "enrichment" && pinnedLocation.sessionId != null) {
      itemType = "enrichment_review_session";
      itemId = pinnedLocation.sessionId;
    } else if (pinnedLocation.viewId != null) {
      itemType = "view";
      itemId = pinnedLocation.viewId;
    } else if (pinnedLocation.memoryId != null) {
      itemType = "memory";
      itemId = pinnedLocation.memoryId;
    } else if (pinnedLocation.query) {
      itemType = "query_anchor";
      metadata["query"] = pinnedLocation.query;
      metadata["state"] = pinnedLocation.state;
      if (pinnedLocation.state === "recall") {
        metadata["recall_tool"] = pinnedLocation.recallTool;
        metadata["include_loop_context"] = pinnedLocation.includeLoopContext;
        metadata["include_memory_context"] = pinnedLocation.includeMemoryContext;
        metadata["include_rag_context"] = pinnedLocation.includeRagContext;
      }
      metadata["label"] = label;
      if (description) {
        metadata["description"] = description;
      }
    } else {
      itemType = "state_anchor";
      metadata["state"] = pinnedLocation.state;
      metadata["recall_tool"] = pinnedLocation.recallTool;
      metadata["review_focus"] = pinnedLocation.reviewFocus;
      metadata["session_id"] = pinnedLocation.sessionId;
      metadata["loop_id"] = pinnedLocation.loopId;
      metadata["view_id"] = pinnedLocation.viewId;
      metadata["memory_id"] = pinnedLocation.memoryId;
      metadata["working_set_id"] = pinnedLocation.workingSetId;
      metadata["query"] = pinnedLocation.query;
      metadata["include_loop_context"] = pinnedLocation.includeLoopContext;
      metadata["include_memory_context"] = pinnedLocation.includeMemoryContext;
      metadata["include_rag_context"] = pinnedLocation.includeRagContext;
    }

    const updatedWorkingSet = await requestJson<WorkingSetResponse, WorkingSetItemCreateRequest>(
      `/loops/working-sets/${activeWorkingSetId}/items`,
      {
        method: "POST",
        body: {
          item_type: itemType,
          item_id: itemId,
          label,
          description,
          metadata,
        },
      },
      "Failed to add item to working set",
    );
    await refreshWorkingSetState();

    const activeSet = latestWorkingSets.find((set) => set.id === activeWorkingSetId)
      ?? workingSetContext?.active_working_set
      ?? updatedWorkingSet
      ?? null;
    const variant = receiptOptions.receiptVariant ?? "pin";
    const pastTense = variant === "stage"
      ? "Staged"
      : variant === "defer"
        ? "Deferred"
        : "Pinned";

    recordWorkingSetReceipt({
      kind: "working_set",
      historyLabel: `${pastTense} ${label}`,
      historyDescription: description ?? "Added a saved item to the active working set.",
      title: `${pastTense} in working set${activeSet ? ` · ${activeSet.name}` : ""}`,
      summary: variant === "stage"
        ? `${label} is now staged as a resumable handoff.`
        : variant === "defer"
          ? `${label} is now saved for later without losing the landing context.`
          : `${label} is now saved in the working set.`,
      tone: "progress",
      location: pinnedLocation,
      workingSet: activeSet,
      rollbackLabel: variant === "pin"
        ? "Remove this item from the working set to undo the saved item."
        : "Remove this item from the working set to cancel the staged handoff.",
      nextStep: activeSet != null
        ? "Open the working set to continue from the landed outcome."
        : "Resume from the landed outcome or reopen the active working set.",
      preview: [
        { label: "Saved item", value: label },
        { label: "Surface", value: pinnedLocation.state.replaceAll("_", " ") },
        ...(activeSet ? [{ label: "Working set", value: activeSet.name }] : []),
      ],
      actions: appendUndoAction(
        [
          {
            type: "open",
            label: "Open landed item",
            variant: "secondary",
            description: description ?? label,
            location: pinnedLocation,
          },
        ],
        workingSetUndoAction(
          activeSet,
          variant === "stage"
            ? `Remove ${label} from the working set and cancel the staged handoff.`
            : variant === "defer"
              ? `Remove ${label} from the working set and cancel the saved defer.`
              : `Remove ${label} from the working set.`,
        ),
      ),
    });
  }

  async function addLoopIdsToActiveWorkingSet(loopIds: readonly number[]): Promise<void> {
    const activeWorkingSetId = await ensureActiveWorkingSetId();
    if (activeWorkingSetId == null) {
      return;
    }
    const existingLoopIds = new Set(
      (workingSetContext?.active_working_set?.items ?? [])
        .map((item) => item.launch.loop_id)
        .filter((value): value is number => typeof value === "number"),
    );
    const items: WorkingSetBulkItemCreateRequest["items"] = [];
    const addedLabels: string[] = [];
    for (const loopId of loopIds) {
      if (existingLoopIds.has(loopId)) {
        continue;
      }
      const loop = options.getLatestWorkspaceData()?.allLoops.find((candidate) => candidate.id === loopId) ?? null;
      const label = loop ? loopTitle(loop) : `Loop #${loopId}`;
      const description = loop ? loopPreview(loop) : null;
      items.push({
        item_type: "loop",
        item_id: loopId,
        label,
        description,
        metadata: {},
      });
      addedLabels.push(label);
    }
    if (!items.length) {
      return;
    }
    const updatedWorkingSet = await requestJson<WorkingSetResponse, WorkingSetBulkItemCreateRequest>(
      `/loops/working-sets/${activeWorkingSetId}/items/bulk`,
      {
        method: "POST",
        body: { items },
      },
      "Failed to add loops to working set",
    );
    await refreshWorkingSetState();
    const activeSet = latestWorkingSets.find((set) => set.id === activeWorkingSetId)
      ?? workingSetContext?.active_working_set
      ?? updatedWorkingSet
      ?? null;
    recordWorkingSetReceipt({
      kind: "working_set",
      historyLabel: `Added ${addedLabels.length} loop${addedLabels.length === 1 ? "" : "s"} to working set`,
      historyDescription: `Saved ${addedLabels.join(", ")} for later resume.`,
      title: activeSet ? `Expanded working set · ${activeSet.name}` : "Expanded working set",
      summary: `${addedLabels.length} loop${addedLabels.length === 1 ? "" : "s"} were added to the working set.`,
      tone: "progress",
      location: activeSet ? workingSetSessionLocation(activeSet.id) : createLocation({ state: "operator" }),
      workingSet: activeSet,
      rollbackLabel: "Remove the added loops if you do not want to keep them in this working set.",
      nextStep: "Open the working set to continue from the expanded bounded context.",
      preview: [
        ...(activeSet ? [{ label: "Working set", value: activeSet.name }] : []),
        { label: "Added", value: `${addedLabels.length}` },
        { label: "Examples", value: addedLabels.slice(0, 2).join(" · ") },
      ],
      actions: appendUndoAction(
        undefined,
        workingSetUndoAction(
          activeSet,
          `Remove the ${addedLabels.length} loop item${addedLabels.length === 1 ? "" : "s"} added in this step.`,
        ),
      ),
    });
  }

  return {
    getLatestWorkingSets: (): WorkingSetResponse[] => latestWorkingSets,
    getWorkingSetContext: (): WorkingSetContextResponse | null => workingSetContext,
    promptForWorkingSetDetails,
    confirmWorkingSetDeletion,
    loadWorkingSetState,
    refreshWorkingSetState,
    workingSetItemLocation,
    focusModeActiveSet,
    workingSetFromLocation,
    renderWorkingSet,
    renderWorkingSetFocusBanner,
    syncFocusModeClass,
    renderWorkingSetSessionSurface,
    setWorkingSetContext,
    createWorkingSetViaDialog,
    ensureActiveWorkingSetId,
    updateWorkingSet,
    deleteWorkingSet,
    reorderWorkingSetItems,
    removeWorkingSetItem,
    pinLocationToWorkingSet,
    addLoopIdsToActiveWorkingSet,
  };
}
