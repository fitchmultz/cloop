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

import { requestJson } from "./http";
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
  WorkingSetContextResponse,
  WorkingSetContextUpdateRequest,
  WorkingSetItemCreateRequest,
  WorkingSetItemResponse,
  WorkingSetResponse,
} from "./domain";
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
  pinLocationToWorkingSet(location: ShellLocation, label: string, description: string | null): Promise<void>;
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
        "Save a bounded cross-surface context so you can resume the exact loops, sessions, and anchors that matter later.",
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
            <h3>All anchors</h3>
            <p>Launch any member without losing the rest of the working set.</p>
          </div>
        </div>
        <div class="working-set-item-grid">
          ${
            (workingSet.items ?? []).length
              ? (workingSet.items ?? []).map((item) => renderWorkingSetItemCard(workingSet.id, item)).join("")
              : '<p class="operator-empty">This working set is empty. Pin loops, sessions, views, or anchors to make it resumable.</p>'
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
    elements.workingSetFocusToggleButton.textContent = focusEnabled ? "Pause focus mode" : "Enter focus mode";
    elements.workingSetFocusSummary.innerHTML = `
      <div>
        <p class="support-eyebrow">${focusEnabled ? "Focus mode" : "Active working set"}</p>
        <h2>${escapeHtml(activeSet.name)}</h2>
        <p>${escapeHtml(activeSet.description ?? "A saved bounded slice of loops, sessions, and anchors.")}</p>
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
      : '<p class="operator-empty">This working set is empty. Pin a loop, session, or anchor to make focus mode useful.</p>';
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
        <p class="operator-empty">Save a bounded slice of loops, sessions, and anchors so you can resume the exact operational context later.</p>
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
                <p>${escapeHtml(set.description ?? "Saved cross-surface operator context.")}</p>
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
                : '<p class="operator-empty">This set is empty. Add a loop, session, or anchor from the operator workspace.</p>'}
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
    await requestJson<WorkingSetContextResponse, WorkingSetContextUpdateRequest>(
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

    recordRecentShellAction({
      kind: activeWorkingSetId != null ? "working_set_session" : "working_set",
      label: workingSetContext?.active_working_set
        ? `${focusModeEnabled ? "Focused" : "Opened"} working set · ${workingSetContext.active_working_set.name}`
        : "Cleared active working set",
      description:
        workingSetContext?.active_working_set?.description
        ?? "Updated the active working-set session context.",
      location:
        activeWorkingSetId != null
          ? workingSetSessionLocation(activeWorkingSetId)
          : createLocation({ state: "operator" }),
      metadata: {
        focusModeEnabled,
        workingSetId: activeWorkingSetId,
      },
    });
  }

  async function createWorkingSetViaDialog(): Promise<WorkingSetResponse | null> {
    const details = await promptForWorkingSetDetails();
    if (!details) {
      return null;
    }
    const created = await requestJson<WorkingSetResponse, { name: string; description: string | null }>(
      "/loops/working-sets",
      {
        method: "POST",
        body: details,
      },
      "Failed to create working set",
    );
    await refreshWorkingSetState();
    return created;
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

  async function pinLocationToWorkingSet(
    location: ShellLocation,
    label: string,
    description: string | null,
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
    }

    await requestJson<WorkingSetResponse, WorkingSetItemCreateRequest>(
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

    recordRecentShellAction({
      kind: "working_set",
      label: `Pinned ${label}`,
      description: description ?? "Added a resume anchor to the active working set.",
      location: pinnedLocation,
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
    for (const loopId of loopIds) {
      if (existingLoopIds.has(loopId)) {
        continue;
      }
      const loop = options.getLatestWorkspaceData()?.allLoops.find((candidate) => candidate.id === loopId) ?? null;
      const label = loop ? loopTitle(loop) : `Loop #${loopId}`;
      const description = loop ? loopPreview(loop) : null;
      await requestJson<WorkingSetResponse, WorkingSetItemCreateRequest>(
        `/loops/working-sets/${activeWorkingSetId}/items`,
        {
          method: "POST",
          body: {
            item_type: "loop",
            item_id: loopId,
            label,
            description,
            metadata: {},
          },
        },
        "Failed to add loops to working set",
      );
    }
    await refreshWorkingSetState();
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
    pinLocationToWorkingSet,
    addLoopIdsToActiveWorkingSet,
  };
}
