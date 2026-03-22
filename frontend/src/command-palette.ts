/**
 * command-palette.ts - Global command palette and unified quick-action surface.
 *
 * Purpose:
 *   Deliver one keyboard-first palette for navigation, capture, quick actions,
 *   resume flows, and object search across the operator shell.
 *
 * Responsibilities:
 *   - Render and manage the palette dialog.
 *   - Build deterministic commands from shell context, continuity recovery,
 *     working sets, sessions, saved views, and current selection state.
 *   - Execute navigation, capture, mutation, and recall actions through shared
 *     HTTP contracts and shell callbacks.
 *   - Persist recent command usage for fast resume behavior.
 *
 * Scope:
 *   - Web-only command palette behavior for the TypeScript frontend.
 *
 * Usage:
 *   - Bootstrapped from frontend/src/shell.ts with live shell bindings.
 *
 * Invariants/Assumptions:
 *   - The shell remains the source of truth for navigation and working-set
 *     context mutations.
 *   - Shared HTTP routes stay canonical for loop, memory, planning, and review
 *     actions.
 *   - Recent usage is advisory and stored locally in the browser.
 */

import { createReceiptCard, withReceiptOutcome } from "./action-receipts";
import { requestJson } from "./http";
import type {
  AskResponse,
  BulkCloseRequest,
  BulkCloseResponse,
  BulkEnrichRequest,
  BulkEnrichResponse,
  BulkSnoozeRequest,
  BulkSnoozeResponse,
  LoopCaptureRequest,
  LoopResponse,
  LoopViewResponse,
  MemoryEntryResponse,
  MemorySearchResponse,
  PlanningSessionCreateRequest,
  PlanningSessionSnapshotResponse,
  PlanningSessionResponse,
  RelationshipReviewSessionResponse,
  EnrichmentReviewSessionResponse,
  WorkingSetContextResponse,
  WorkingSetResponse,
} from "./domain";
import type {
  ContinuityRecoveryPlan,
  RecallTool,
  RecentShellActionKind,
  ReviewFocus,
  ShellLocationContract,
  ShellState,
  TrustSurfaceMetadata,
  TrustTone,
} from "./contracts-ui";
import {
  markContinuityRecoveryAcknowledged,
  markRerunActionUnavailable,
  markUndoActionUnavailable,
  readContinuityLastSeenMarkers,
  readResumeAnchors,
  recordRecentShellAction,
} from "./continuity-intelligence";
import {
  buildContinuityAvailability,
  groupRankedWorkflowThreads,
  readRankedLandedOutcomes,
  type RankedLandedOutcome,
} from "./continuity-follow-through";
import { derivePrimaryRecommendation } from "./continuity-recommendations";
import { continuityLocationIdentity } from "./continuity-outcomes";
import { renderTrustSurface } from "./trust-surface";
import {
  rankPaletteItems,
  type PaletteGroup,
  type PaletteRankItem,
  type PaletteRankingContext,
} from "./command-palette-ranking";
import {
  executeRerunAction as runExecutableRerunAction,
  staleRerunReason,
} from "./executable-rerun";
import { executeUndoAction as runExecutableUndoAction, staleUndoReason } from "./executable-undo";
import * as modals from "./modals";
import { createLocation, workingSetSessionLocation } from "./shell-routing";
import { updateBulkActionBar } from "./bulk-actions";
import { clearLoopSelection, selectedLoopIds } from "./selection-state";

interface CommandPaletteElements {
  root: HTMLElement;
  overlay: HTMLElement;
  panel: HTMLElement;
  input: HTMLInputElement;
  results: HTMLElement;
  detail: HTMLElement;
  status: HTMLElement;
  closeButtons: HTMLButtonElement[];
}

export interface CommandPaletteContext {
  currentLocation: ShellLocationContract;
  loops: LoopResponse[];
  workingSets: WorkingSetResponse[];
  workingSetContext: WorkingSetContextResponse | null;
  planningSessions: PlanningSessionResponse[];
  relationshipSessions: RelationshipReviewSessionResponse[];
  enrichmentSessions: EnrichmentReviewSessionResponse[];
}

interface CommandPaletteBindings {
  getContext: () => CommandPaletteContext;
  openLocation: (location: ShellLocationContract) => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  createWorkingSet: () => Promise<WorkingSetResponse | null>;
  setWorkingSetContext: (workingSetId: number | null, focusModeEnabled: boolean) => Promise<void>;
  pinLocation: (
    location: ShellLocationContract,
    label: string,
    description: string | null,
  ) => Promise<void>;
  addLoopIdsToActiveWorkingSet: (loopIds: number[]) => Promise<void>;
  askGroundedChat: (query: string) => Promise<void>;
  runMemorySearch: (query: string) => Promise<void>;
  runDocumentAsk: (query: string) => Promise<void>;
}

type RecentAction =
  | {
      kind: "open-location";
      location: ShellLocationContract;
    }
  | {
      kind: "working-set-context";
      workingSetId: number | null;
      focusModeEnabled: boolean;
    }
  | {
      kind: "ask-chat";
      query: string;
    }
  | {
      kind: "memory-search";
      query: string;
    }
  | {
      kind: "document-ask";
      query: string;
    }
  | {
      kind: "bulk-close";
      status: "completed" | "dropped";
    }
  | {
      kind: "bulk-status";
      status: "actionable" | "blocked" | "scheduled" | "inbox";
    }
  | {
      kind: "bulk-snooze";
    }
  | {
      kind: "bulk-enrich";
    }
  | {
      kind: "capture-loop";
    }
  | {
      kind: "create-memory";
    }
  | {
      kind: "create-planning-session";
    }
  | {
      kind: "pin-current-location";
    }
  | {
      kind: "pin-selected-loops";
    };

interface StoredRecentCommand {
  id: string;
  title: string;
  subtitle: string;
  group: PaletteGroup;
  usedAt: string;
  count: number;
  action: RecentAction;
}

interface CommandPaletteCommand extends PaletteRankItem {
  badge: string;
  detail: {
    eyebrow: string;
    description: string;
    meta: string[];
    trust?: Partial<TrustSurfaceMetadata> | undefined;
    recovery?: ContinuityRecoveryPlan | undefined;
  };
  execute: () => Promise<void>;
  recentAction?: RecentAction | undefined;
  skipAutomaticReceipt?: boolean | undefined;
}

interface CommandPaletteController {
  handleGlobalHotkey: (event: KeyboardEvent) => boolean;
  isOpen: () => boolean;
  open: (initialQuery?: string) => void;
}

const RECENT_COMMANDS_STORAGE_KEY = "cloop.command-palette.recent.v1";
const VIEW_CACHE_TTL_MS = 60 * 1000;
const GROUP_LABELS = {
  recommended: "Recommended",
  recent: "Recent",
  navigate: "Navigate",
  capture: "Capture",
  act: "Act",
  review: "Review",
  recall: "Recall",
  search: "Search",
} as const satisfies Record<PaletteGroup, string>;

function requireElement<T extends HTMLElement>(id: string, ctor: { new (): T }): T {
  const element = document.getElementById(id);
  if (!(element instanceof ctor)) {
    throw new Error(`Missing required command-palette element: ${id}`);
  }
  return element;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

function selectedLoopIdList(): number[] {
  return Array.from(selectedLoopIds.values()).filter((value): value is number => {
    return typeof value === "number" && Number.isInteger(value);
  });
}

function buildElements(): CommandPaletteElements {
  const root = requireElement("command-palette", HTMLElement);
  return {
    root,
    overlay: requireElement("command-palette-overlay", HTMLElement),
    panel: requireElement("command-palette-panel", HTMLElement),
    input: requireElement("command-palette-input", HTMLInputElement),
    results: requireElement("command-palette-results", HTMLElement),
    detail: requireElement("command-palette-detail", HTMLElement),
    status: requireElement("command-palette-status", HTMLElement),
    closeButtons: Array.from(root.querySelectorAll<HTMLButtonElement>("[data-command-palette-close]")),
  };
}

function loopTitle(loop: LoopResponse): string {
  return loop.title?.trim() || loop.raw_text.trim() || `Loop #${loop.id}`;
}

function loopSummary(loop: LoopResponse): string {
  return loop.summary?.trim() || loop.next_action?.trim() || loop.raw_text.trim();
}

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) {
    return "unknown time";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const diffMs = Date.now() - date.getTime();
  const absMs = Math.abs(diffMs);
  const hour = 60 * 60 * 1000;
  const day = 24 * hour;
  if (absMs < day) {
    const hours = Math.max(1, Math.round(absMs / hour));
    return `${hours} hour${hours === 1 ? "" : "s"} ${diffMs >= 0 ? "ago" : "from now"}`;
  }
  const days = Math.max(1, Math.round(absMs / day));
  return `${days} day${days === 1 ? "" : "s"} ${diffMs >= 0 ? "ago" : "from now"}`;
}

function readStoredRecentCommands(): StoredRecentCommand[] {
  try {
    const raw = window.localStorage.getItem(RECENT_COMMANDS_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as StoredRecentCommand[]) : [];
  } catch {
    return [];
  }
}

function writeStoredRecentCommands(commands: StoredRecentCommand[]): void {
  window.localStorage.setItem(RECENT_COMMANDS_STORAGE_KEY, JSON.stringify(commands.slice(0, 18)));
}

function usageIndex(records: readonly StoredRecentCommand[]): PaletteRankingContext["recentUsage"] {
  return Object.fromEntries(
    records.map((record) => [record.id, { count: record.count, usedAt: record.usedAt }]),
  );
}

function storeRecentCommand(command: CommandPaletteCommand): void {
  if (!command.recentAction) {
    return;
  }
  const stored = readStoredRecentCommands();
  const existing = stored.find((record) => record.id === command.id) ?? null;
  const updated: StoredRecentCommand = {
    id: command.id,
    title: command.title,
    subtitle: command.subtitle,
    group: command.group,
    usedAt: new Date().toISOString(),
    count: existing ? existing.count + 1 : 1,
    action: command.recentAction,
  };
  writeStoredRecentCommands([updated, ...stored.filter((record) => record.id !== command.id)]);
}

function commandHistoryKind(command: CommandPaletteCommand): RecentShellActionKind {
  const action = command.recentAction;
  if (action?.kind === "bulk-snooze") {
    return "snooze";
  }
  if (action?.kind === "bulk-close" || action?.kind === "bulk-status" || action?.kind === "bulk-enrich") {
    return "bulk";
  }
  if (action?.kind === "working-set-context") {
    return action.workingSetId != null ? "working_set_session" : "working_set";
  }
  if (action?.kind === "pin-current-location" || action?.kind === "pin-selected-loops") {
    return "working_set";
  }
  if (action?.kind === "create-planning-session") {
    return "planning";
  }
  if (action?.kind === "ask-chat" || action?.kind === "memory-search" || action?.kind === "document-ask") {
    return "recall";
  }
  if (action?.kind === "open-location") {
    if (action.location.state === "plan") {
      return "planning";
    }
    if (action.location.state === "decide") {
      return "review";
    }
    if (action.location.state === "recall") {
      return "recall";
    }
    if (action.location.state === "working_set") {
      return "working_set_session";
    }
    return "navigation";
  }
  return "command";
}

function commandHistoryLocation(command: CommandPaletteCommand, currentLocation: ShellLocationContract): ShellLocationContract | null {
  const action = command.recentAction;
  if (command.location) {
    return command.location;
  }
  if (action?.kind === "open-location") {
    return action.location;
  }
  if (action?.kind === "working-set-context") {
    return action.workingSetId != null
      ? workingSetSessionLocation(action.workingSetId)
      : createLocation({ state: "operator" });
  }
  if (action?.kind === "ask-chat") {
    return createLocation({ state: "recall", recallTool: "chat" });
  }
  if (action?.kind === "memory-search") {
    return createLocation({ state: "recall", recallTool: "memory", query: action.query });
  }
  if (action?.kind === "document-ask") {
    return createLocation({ state: "recall", recallTool: "rag", query: action.query });
  }
  return currentLocation;
}

function commandHistoryLabel(command: CommandPaletteCommand, location: ShellLocationContract | null): string {
  const action = command.recentAction;
  const usesLocationLabel = action?.kind === "open-location"
    || action?.kind === "ask-chat"
    || action?.kind === "memory-search"
    || action?.kind === "document-ask"
    || action?.kind === "create-planning-session"
    || action?.kind === "working-set-context";
  if (!usesLocationLabel || !location) {
    return command.title;
  }
  if (location.state === "working_set" && location.workingSetId != null) {
    return `Opened working set #${location.workingSetId}`;
  }
  if (location.state === "plan" && location.sessionId != null) {
    return `Resumed plan #${location.sessionId}`;
  }
  if (location.state === "decide" && location.sessionId != null) {
    return `Opened ${location.reviewFocus ?? "review"} queue #${location.sessionId}`;
  }
  if (location.state === "recall") {
    return `Opened recall · ${location.recallTool}`;
  }
  return `Opened ${location.state}`;
}

function requestSubmit(form: HTMLFormElement): void {
  if (typeof form.requestSubmit === "function") {
    form.requestSubmit();
    return;
  }
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

function defaultCommandGenerationLabel(command: CommandPaletteCommand): string {
  if (command.detail.recovery) {
    return "Deterministic continuity recovery path";
  }
  if (command.group === "act" || command.group === "capture") {
    return "Explicit mutation contract";
  }
  if (command.group === "recommended") {
    return "Deterministic continuity recommendation";
  }
  if (command.group === "review") {
    return "Saved-session or review handoff";
  }
  if (command.group === "recent") {
    return "Browser-local recent command";
  }
  if (command.group === "recall") {
    return "Recall launch surface";
  }
  if (command.group === "search") {
    return "Deterministic object lookup";
  }
  return "Deterministic navigation";
}

function defaultCommandContextSources(command: CommandPaletteCommand, selectedCount: number): string[] {
  const sources: string[] = [command.detail.eyebrow];
  if (command.detail.recovery) {
    sources.push("Recovery evidence from continuity outcomes and durable anchors");
  }
  if (command.location?.sessionId != null) {
    sources.push(`Saved session #${command.location.sessionId}`);
  }
  if (command.location?.loopId != null) {
    sources.push(`Loop #${command.location.loopId}`);
  }
  if (command.location?.viewId != null) {
    sources.push(`Saved view #${command.location.viewId}`);
  }
  if (command.location?.memoryId != null) {
    sources.push(`Memory entry #${command.location.memoryId}`);
  }
  if (command.location?.workingSetId != null) {
    sources.push(`Working set #${command.location.workingSetId}`);
  }
  if (command.location?.query) {
    sources.push(`Query anchor: ${command.location.query}`);
  }
  if (selectedCount > 0 && command.group === "act") {
    sources.push(`${selectedCount} selected loop${selectedCount === 1 ? "" : "s"}`);
  }
  if (command.group === "recommended") {
    sources.push("Durable continuity outcomes and last-seen evidence");
  }
  if (command.group === "recent") {
    sources.push("Browser-local recent usage history");
  }
  return sources;
}

function defaultCommandAssumptions(command: CommandPaletteCommand, selectedCount: number): string[] {
  if (command.detail.recovery) {
    return ["Recovery commands stay deterministic and only open the surviving destination."];
  }
  if (command.disabled && command.group === "act") {
    return ["Select one or more loops before this command can run."];
  }
  if (command.group === "act") {
    return ["The shared loop mutation contract remains the source of truth for the selected targets."];
  }
  if (command.group === "capture") {
    return ["A confirmation dialog or follow-up form will collect any missing required fields."];
  }
  if (command.group === "recommended") {
    return ["Recommendation ranking uses only visible continuity evidence, drift, readiness, and working-set relevance."];
  }
  if (command.group === "recent") {
    return ["Recent commands are stored locally in this browser and may not reflect work done elsewhere."];
  }
  if (selectedCount > 0) {
    return ["The current shell selection and focus context may influence ranking."];
  }
  return [];
}

function defaultCommandConfidence(command: CommandPaletteCommand): { label: string | null; tone: TrustTone } {
  if (command.detail.recovery) {
    return { label: "Explicit recovery path", tone: "attention" };
  }
  if (command.disabled) {
    return { label: "Unavailable until prerequisites are met", tone: "caution" };
  }
  if (command.location?.loopId != null || command.location?.memoryId != null || command.location?.viewId != null) {
    return { label: "Exact object target", tone: "progress" };
  }
  if (command.group === "recommended") {
    return { label: "Deterministic next move", tone: "attention" };
  }
  if (command.group === "recent") {
    return { label: "Recent repeat candidate", tone: "progress" };
  }
  if (command.group === "review") {
    return { label: "Context-ranked review handoff", tone: "attention" };
  }
  if (command.group === "act" || command.group === "capture") {
    return { label: "Ready to run shared mutation flow", tone: "attention" };
  }
  return { label: "Context-ranked navigation target", tone: "neutral" };
}

function defaultCommandFreshness(command: CommandPaletteCommand): { label: string | null; tone: TrustTone } {
  if (command.group === "recent") {
    const recentLine = command.detail.meta.find((item) => item.startsWith("Last used ")) ?? null;
    return { label: recentLine ? recentLine.replace(/^Last used /, "") : "Browser-local recent history", tone: "neutral" };
  }
  if (command.group === "recommended") {
    return { label: "Resolved from durable continuity and live shell state", tone: "neutral" };
  }
  if (command.group === "act") {
    return { label: "Uses current shell selection and focus context", tone: command.disabled ? "caution" : "neutral" };
  }
  if (command.group === "review") {
    return { label: "Depends on the latest saved session snapshot", tone: "neutral" };
  }
  return { label: "Resolved from the live shell context", tone: "neutral" };
}

function defaultCommandRollback(command: CommandPaletteCommand): { label: string | null; tone: TrustTone } {
  if (
    command.group === "recommended"
    || command.group === "navigate"
    || command.group === "review"
    || command.group === "recall"
    || command.group === "search"
    || command.group === "recent"
  ) {
    return { label: "Navigation only until you act downstream", tone: "progress" };
  }
  if (command.group === "capture") {
    return { label: "Creates a new resource after confirmation", tone: "caution" };
  }
  return { label: "Runs the shared mutation contract immediately", tone: "caution" };
}

function detailTrustMetadata(command: CommandPaletteCommand, selectedCount: number): TrustSurfaceMetadata {
  const overrides = command.detail.trust ?? {};
  const confidence = defaultCommandConfidence(command);
  const freshness = defaultCommandFreshness(command);
  const rollback = defaultCommandRollback(command);

  return {
    generationLabel: overrides.generationLabel ?? defaultCommandGenerationLabel(command),
    generationTone: overrides.generationTone ?? (command.group === "act" || command.group === "capture" ? "attention" : "neutral"),
    contextSources: overrides.contextSources ?? defaultCommandContextSources(command, selectedCount),
    assumptions: overrides.assumptions ?? defaultCommandAssumptions(command, selectedCount),
    confidenceLabel: overrides.confidenceLabel ?? confidence.label,
    confidenceTone: overrides.confidenceTone ?? confidence.tone,
    freshnessLabel: overrides.freshnessLabel ?? freshness.label,
    freshnessTone: overrides.freshnessTone ?? freshness.tone,
    rollbackLabel: overrides.rollbackLabel ?? rollback.label,
    rollbackTone: overrides.rollbackTone ?? rollback.tone,
    impactSummary: overrides.impactSummary ?? command.subtitle,
    impactTone: overrides.impactTone ?? (command.group === "act" || command.group === "capture" ? "attention" : "neutral"),
  };
}

function buildDetailHtml(command: CommandPaletteCommand, selectedCount: number): string {
  const recoveryBlock = command.detail.recovery
    ? `
      <div class="command-palette-detail-recovery command-palette-detail-recovery--${escapeHtml(command.detail.recovery.kind)}">
        <p class="support-eyebrow">${escapeHtml(command.detail.recovery.title)}</p>
        <p>${escapeHtml(command.detail.recovery.summary)}</p>
        <p><strong>Do this now:</strong> ${escapeHtml(command.detail.recovery.nextStep)}</p>
      </div>
    `
    : "";

  return `
    <div class="command-palette-detail-header">
      <p class="support-eyebrow">${escapeHtml(command.detail.eyebrow)}</p>
      <h3>${escapeHtml(command.title)}</h3>
      <p>${escapeHtml(command.subtitle)}</p>
    </div>
    <p class="command-palette-detail-body">${escapeHtml(command.detail.description)}</p>
    ${recoveryBlock}
    ${renderTrustSurface(detailTrustMetadata(command, selectedCount), {
      variant: "detail",
      title: "Trust surface",
      showContextLists: true,
    })}
    <ul class="command-palette-detail-meta">
      ${command.detail.meta.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      <li>${selectedCount} selected loop${selectedCount === 1 ? "" : "s"} in scope</li>
    </ul>
  `;
}

function workingSetMetadataFromContext(context: CommandPaletteContext) {
  const active = context.workingSetContext?.active_working_set ?? null;
  if (!active) {
    return null;
  }
  return {
    workingSetId: active.id,
    workingSetName: active.name,
    itemCount: active.item_count,
    missingItemCount: active.missing_item_count,
  };
}

function buildCommandReceipt(
  command: CommandPaletteCommand,
  currentContext: CommandPaletteContext,
  historyLocation: ShellLocationContract | null,
) {
  const rollback = defaultCommandRollback(command);
  const selectedCount = selectedLoopIdList().length;
  const workingSet = workingSetMetadataFromContext(currentContext);
  return createReceiptCard({
    id: `command-receipt-${command.id}-${Date.now()}`,
    eyebrow: "Command complete",
    title: command.title,
    summary: command.subtitle,
    rationale:
      "Command receipts preserve what just ran, where it landed, and how to resume after the palette closes.",
    tone: command.group === "act" || command.group === "capture" ? "attention" : "progress",
    preview: [
      { label: "Group", value: GROUP_LABELS[command.group] },
      { label: "Badge", value: command.badge },
      ...(historyLocation ? [{ label: "Landed in", value: historyLocation.state.replaceAll("_", " ") }] : []),
    ],
    trust: {
      ...detailTrustMetadata(command, selectedCount),
      generationLabel: "Executed palette command",
      generationTone: "progress",
      rollbackLabel: rollback.label,
      rollbackTone: rollback.tone,
    },
    handoff: {
      changeSummary: `${command.title} completed and the landing context is ready.`,
      createdResources: [],
      nextStep: historyLocation
        ? "Resume from the landed outcome or continue from the current shell context."
        : "Continue from the updated shell context.",
      breadcrumbs: ["Command palette", GROUP_LABELS[command.group], command.title],
      workingSet,
    },
    resumeLocation: historyLocation,
    resumeDescription: command.subtitle,
    ...(historyLocation ? { resumeLabel: "Resume outcome", pinLabel: `Command · ${command.title}` } : {}),
  });
}

async function captureLoopDialog(): Promise<LoopCaptureRequest | null> {
  const result = await modals.promptDialog({
    eyebrow: "Quick capture",
    title: "Capture from the palette",
    description: "Create a loop without leaving the keyboard, then jump straight into the right surface.",
    confirmLabel: "Capture loop",
    fields: [
      { name: "raw_text", label: "Loop text", required: true, type: "textarea", rows: 4, placeholder: "Follow up with launch vendor" },
      {
        name: "status",
        label: "Initial status",
        type: "select",
        value: "inbox",
        options: [
          { value: "inbox", label: "Inbox" },
          { value: "actionable", label: "Actionable" },
          { value: "blocked", label: "Blocked" },
          { value: "scheduled", label: "Scheduled" },
        ],
      },
      { name: "next_action", label: "Next action (optional)", value: "", placeholder: "Draft vendor follow-up email" },
      { name: "due_date", label: "Due date (optional)", value: "", placeholder: "YYYY-MM-DD" },
    ],
    validate(values: Record<string, string>): string | null {
      return values["raw_text"]?.trim() ? null : "Loop text is required.";
    },
  });
  if (!result) {
    return null;
  }
  return {
    raw_text: result["raw_text"]?.trim() ?? "",
    captured_at: new Date().toISOString(),
    client_tz_offset_min: new Date().getTimezoneOffset(),
    actionable: result["status"] === "actionable",
    blocked: result["status"] === "blocked",
    scheduled: result["status"] === "scheduled",
    next_action: result["next_action"]?.trim() || null,
    due_date: result["due_date"]?.trim() || null,
  } satisfies LoopCaptureRequest;
}

async function memoryEntryDialog(): Promise<Record<string, unknown> | null> {
  const result = await modals.promptDialog({
    eyebrow: "Direct memory",
    title: "Create memory from the palette",
    description: "Store a durable fact, preference, commitment, or context note without leaving the keyboard.",
    confirmLabel: "Create memory",
    fields: [
      { name: "content", label: "Content", required: true, type: "textarea", rows: 4, placeholder: "The launch review prefers concise decision summaries." },
      {
        name: "category",
        label: "Category",
        type: "select",
        value: "context",
        options: [
          { value: "fact", label: "Fact" },
          { value: "preference", label: "Preference" },
          { value: "commitment", label: "Commitment" },
          { value: "context", label: "Context" },
        ],
      },
      { name: "key", label: "Key (optional)", value: "", placeholder: "launch-review-style" },
      { name: "priority", label: "Priority", type: "number", value: "40", inputMode: "numeric" },
      {
        name: "source",
        label: "Source",
        type: "select",
        value: "user_stated",
        options: [
          { value: "user_stated", label: "User stated" },
          { value: "inferred", label: "Inferred" },
          { value: "imported", label: "Imported" },
          { value: "system", label: "System" },
        ],
      },
    ],
    validate(values: Record<string, string>): string | null {
      if (!values["content"]?.trim()) {
        return "Memory content is required.";
      }
      const priority = Number.parseInt(values["priority"] ?? "", 10);
      if (!Number.isInteger(priority) || priority < 0 || priority > 100) {
        return "Priority must be between 0 and 100.";
      }
      return null;
    },
  });
  if (!result) {
    return null;
  }
  return {
    content: result["content"]?.trim() ?? "",
    category: result["category"] ?? "context",
    key: result["key"]?.trim() || null,
    priority: Number.parseInt(result["priority"] ?? "0", 10),
    source: result["source"] ?? "user_stated",
  };
}

async function planningSessionDialog(): Promise<PlanningSessionCreateRequest | null> {
  const result = await modals.promptDialog({
    eyebrow: "Planning workflows",
    title: "Create planning session",
    description: "Generate a checkpointed plan without leaving the palette.",
    confirmLabel: "Create session",
    fields: [
      { name: "name", label: "Session name", required: true, value: "" },
      {
        name: "prompt",
        label: "Planning prompt",
        type: "textarea",
        rows: 5,
        required: true,
        placeholder: "Create a checkpointed plan for the launch cleanup and decision follow-up.",
      },
      { name: "query", label: "DSL query (optional)", value: "status:open" },
      { name: "loop_limit", label: "Loop limit", type: "number", value: "10", inputMode: "numeric" },
      {
        name: "include_memory_context",
        label: "Include memory context",
        type: "select",
        value: "true",
        options: [
          { value: "true", label: "Yes" },
          { value: "false", label: "No" },
        ],
      },
      {
        name: "include_rag_context",
        label: "Include documents",
        type: "select",
        value: "false",
        options: [
          { value: "false", label: "No" },
          { value: "true", label: "Yes" },
        ],
      },
      { name: "rag_k", label: "Document chunks", type: "number", value: "5", inputMode: "numeric" },
      { name: "rag_scope", label: "Document scope (optional)", value: "" },
    ],
    validate(values: Record<string, string>): string | null {
      if (!values["name"]?.trim()) {
        return "Session name is required.";
      }
      if (!values["prompt"]?.trim()) {
        return "Planning prompt is required.";
      }
      const loopLimit = Number.parseInt(values["loop_limit"] ?? "", 10);
      const ragK = Number.parseInt(values["rag_k"] ?? "", 10);
      if (!Number.isInteger(loopLimit) || loopLimit < 1) {
        return "Loop limit must be a positive integer.";
      }
      if (!Number.isInteger(ragK) || ragK < 1) {
        return "Document chunk count must be a positive integer.";
      }
      return null;
    },
  });
  if (!result) {
    return null;
  }
  return {
    name: result["name"]?.trim() ?? "",
    prompt: result["prompt"]?.trim() ?? "",
    query: result["query"]?.trim() || null,
    loop_limit: Number.parseInt(result["loop_limit"] ?? "10", 10),
    include_memory_context: result["include_memory_context"] === "true",
    include_rag_context: result["include_rag_context"] === "true",
    rag_k: Number.parseInt(result["rag_k"] ?? "5", 10),
    rag_scope: result["rag_scope"]?.trim() || null,
  } satisfies PlanningSessionCreateRequest;
}

async function snoozeDialog(count: number): Promise<string | null> {
  const result = await modals.promptDialog({
    eyebrow: "Bulk action",
    title: "Snooze selected loops",
    description: `Hide ${count} selected loop${count === 1 ? "" : "s"} until a specific date and time.`,
    confirmLabel: "Snooze loops",
    fields: [
      {
        name: "snooze_until",
        label: "Snooze until",
        type: "datetime-local",
        required: true,
      },
    ],
    validate(values: Record<string, string>): string | null {
      const value = values["snooze_until"] ?? "";
      if (!value.trim()) {
        return "Choose a snooze date and time.";
      }
      return Number.isNaN(new Date(value).getTime()) ? "Enter a valid snooze date and time." : null;
    },
  });
  if (!result) {
    return null;
  }
  const snoozeUntil = result["snooze_until"] ?? "";
  return new Date(snoozeUntil).toISOString();
}

function countLabel(count: number): string {
  return `${count} loop${count === 1 ? "" : "s"}`;
}

function loopSearchText(loop: LoopResponse): string {
  return [
    loopTitle(loop),
    loopSummary(loop),
    loop.project ?? "",
    (loop.tags ?? []).join(" "),
    loop.raw_text,
    loop.next_action ?? "",
  ].join(" ");
}

function localLoopMatches(query: string, loops: readonly LoopResponse[]): LoopResponse[] {
  const normalized = normalizeText(query);
  if (!normalized || normalized.includes(":")) {
    return [];
  }
  return [...loops]
    .filter((loop) => normalizeText(loopSearchText(loop)).includes(normalized))
    .sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc))
    .slice(0, 8);
}

async function searchMemories(query: string): Promise<MemoryEntryResponse[]> {
  if (query.trim().length < 2) {
    return [];
  }
  const result = await requestJson<MemorySearchResponse>(
    `/memory/search?q=${encodeURIComponent(query)}&limit=6`,
    {},
    "Failed to search memory",
  );
  return result.items ?? [];
}

function rankingContext(
  query: string,
  context: CommandPaletteContext,
  recentCommands: readonly StoredRecentCommand[],
): PaletteRankingContext {
  const focusLocations = (context.workingSetContext?.active_working_set?.items ?? []).map((item) => {
    return createLocation({
      state: item.launch.state,
      recallTool: item.launch.recall_tool,
      reviewFocus: item.launch.review_focus ?? null,
      sessionId: item.launch.session_id ?? null,
      loopId: item.launch.loop_id ?? null,
      viewId: item.launch.view_id ?? null,
      memoryId: item.launch.memory_id ?? null,
      workingSetId: item.launch.working_set_id ?? null,
      query: item.launch.query ?? null,
    });
  });
  return {
    query,
    currentLocation: context.currentLocation,
    focusLocations,
    activeWorkingSetId: context.workingSetContext?.active_working_set_id ?? null,
    recentUsage: usageIndex(recentCommands),
    selectedLoopIds: selectedLoopIdList(),
    now: Date.now(),
  };
}

function continuityAvailabilityFromContext(context: CommandPaletteContext) {
  return buildContinuityAvailability({
    planningSessionIds: context.planningSessions.map((session) => session.id),
    relationshipSessionIds: context.relationshipSessions.map((session) => session.id),
    enrichmentSessionIds: context.enrichmentSessions.map((session) => session.id),
    workingSets: context.workingSets.map((workingSet) => ({
      workingSetId: workingSet.id,
      workingSetName: workingSet.name,
      itemCount: workingSet.item_count,
      missingItemCount: workingSet.missing_item_count,
    })),
  });
}

function rankedFollowThrough(context: CommandPaletteContext): RankedLandedOutcome[] {
  const resumeAnchors = readResumeAnchors();
  const lastSeenMarkers = readContinuityLastSeenMarkers();
  return readRankedLandedOutcomes({
    availability: continuityAvailabilityFromContext(context),
    activeWorkingSetId: context.workingSetContext?.active_working_set_id ?? null,
    resumeAnchors,
    lastSeenMarkers,
  });
}

function primaryRecommendationForContext(
  context: CommandPaletteContext,
  outcomes: readonly RankedLandedOutcome[],
) {
  return derivePrimaryRecommendation({
    outcomes,
    resumeAnchors: readResumeAnchors(),
    lastSeenMarkers: readContinuityLastSeenMarkers(),
  });
}

function commandItemHtml(command: CommandPaletteCommand, active: boolean): string {
  const disabledLabel = command.disabled ? '<span class="command-palette-result-note">Unavailable</span>' : "";
  return `
    <button
      type="button"
      class="command-palette-result${active ? " is-active" : ""}${command.disabled ? " is-disabled" : ""}${command.group === "recommended" ? " is-recommended" : ""}${command.detail.recovery ? " is-recovery" : ""}"
      data-command-id="${escapeHtml(command.id)}"
      role="option"
      aria-selected="${active ? "true" : "false"}"
      ${command.disabled ? 'aria-disabled="true"' : ""}
    >
      <span class="command-palette-result-copy">
        <span class="command-palette-result-title-row">
          <span class="command-palette-result-title">${escapeHtml(command.title)}</span>
          <span class="command-palette-result-badge">${escapeHtml(command.badge)}</span>
        </span>
        <span class="command-palette-result-subtitle">${escapeHtml(command.subtitle)}</span>
      </span>
      ${disabledLabel}
    </button>
  `;
}

function groupedResultsHtml(commands: readonly CommandPaletteCommand[], activeId: string | null): string {
  const grouped = new Map<PaletteGroup, CommandPaletteCommand[]>();
  for (const command of commands) {
    const existing = grouped.get(command.group) ?? [];
    existing.push(command);
    grouped.set(command.group, existing);
  }

  return Array.from(grouped.entries())
    .map(([group, items]) => {
      return `
        <section class="command-palette-group command-palette-group--${escapeHtml(group)}" aria-label="${escapeHtml(GROUP_LABELS[group])}">
          <p class="command-palette-group-label">${escapeHtml(GROUP_LABELS[group])}</p>
          <div class="command-palette-group-list">
            ${items.map((item) => commandItemHtml(item, item.id === activeId)).join("")}
          </div>
        </section>
      `;
    })
    .join("");
}

export function bootstrapCommandPalette(bindings: CommandPaletteBindings): CommandPaletteController {
  const elements = buildElements();
  let open = false;
  let activeCommandId: string | null = null;
  let visibleCommands: CommandPaletteCommand[] = [];
  let searchNonce = 0;
  let cachedViews: LoopViewResponse[] = [];
  let viewsLoadedAt = 0;

  function activeCommand(): CommandPaletteCommand | null {
    if (!visibleCommands.length) {
      return null;
    }
    return visibleCommands.find((command) => command.id === activeCommandId) ?? visibleCommands[0] ?? null;
  }

  async function ensureViewsLoaded(force = false): Promise<LoopViewResponse[]> {
    const isFresh = Date.now() - viewsLoadedAt < VIEW_CACHE_TTL_MS;
    if (!force && cachedViews.length && isFresh) {
      return cachedViews;
    }
    cachedViews = await requestJson<LoopViewResponse[]>(
      "/loops/views",
      {},
      "Failed to load saved views",
    );
    viewsLoadedAt = Date.now();
    return cachedViews;
  }

  async function executeRecentAction(action: RecentAction): Promise<void> {
    const context = bindings.getContext();
    const selection = selectedLoopIdList();

    switch (action.kind) {
      case "open-location":
        await bindings.openLocation(action.location);
        return;
      case "working-set-context":
        await bindings.setWorkingSetContext(action.workingSetId, action.focusModeEnabled);
        if (action.workingSetId != null) {
          await bindings.openLocation(workingSetSessionLocation(action.workingSetId));
        }
        return;
      case "ask-chat":
        await bindings.askGroundedChat(action.query);
        return;
      case "memory-search":
        await bindings.runMemorySearch(action.query);
        return;
      case "document-ask":
        await bindings.runDocumentAsk(action.query);
        return;
      case "capture-loop": {
        const payload = await captureLoopDialog();
        if (!payload) {
          return;
        }
        const created = await requestJson<LoopResponse, LoopCaptureRequest>(
          "/loops/capture",
          { method: "POST", body: payload },
          "Failed to capture loop",
        );
        await bindings.refreshWorkspace();
        await bindings.openLocation(createLocation({ state: "do", loopId: created.id }));
        return;
      }
      case "create-memory": {
        const payload = await memoryEntryDialog();
        if (!payload) {
          return;
        }
        const created = await requestJson<MemoryEntryResponse, Record<string, unknown>>(
          "/memory",
          { method: "POST", body: payload },
          "Failed to create memory",
        );
        await bindings.openLocation(createLocation({ state: "recall", recallTool: "memory", memoryId: created.id }));
        return;
      }
      case "create-planning-session": {
        const payload = await planningSessionDialog();
        if (!payload) {
          return;
        }
        const created = await requestJson<PlanningSessionSnapshotResponse, PlanningSessionCreateRequest>(
          "/loops/planning/sessions",
          { method: "POST", body: payload },
          "Failed to create planning session",
        );
        await bindings.refreshWorkspace();
        await bindings.openLocation(
          createLocation({
            state: "plan",
            reviewFocus: "planning",
            sessionId: created.session.id,
          }),
        );
        return;
      }
      case "bulk-close": {
        if (!selection.length) {
          throw new Error("Select one or more loops before running this action.");
        }
        const result = await requestJson<BulkCloseResponse, BulkCloseRequest>(
          "/loops/bulk/close",
          {
            method: "POST",
            body: {
              transactional: false,
              items: selection.map((loopId) => ({ loop_id: loopId, status: action.status })),
            },
          },
          "Failed to update selected loops",
        );
        clearLoopSelection();
        updateBulkActionBar();
        await bindings.refreshWorkspace();
        if (!result.ok) {
          throw new Error(`Only ${result.succeeded} of ${selection.length} selected loops updated.`);
        }
        return;
      }
      case "bulk-status": {
        if (!selection.length) {
          throw new Error("Select one or more loops before running this action.");
        }
        await Promise.all(
          selection.map((loopId) => {
            return requestJson<LoopResponse, { status: typeof action.status }>(
              `/loops/${loopId}/status`,
              {
                method: "POST",
                body: { status: action.status },
              },
              "Failed to update selected loops",
            );
          }),
        );
        clearLoopSelection();
        updateBulkActionBar();
        await bindings.refreshWorkspace();
        return;
      }
      case "bulk-snooze": {
        if (!selection.length) {
          throw new Error("Select one or more loops before running this action.");
        }
        const snoozeUntilUtc = await snoozeDialog(selection.length);
        if (!snoozeUntilUtc) {
          return;
        }
        const result = await requestJson<BulkSnoozeResponse, BulkSnoozeRequest>(
          "/loops/bulk/snooze",
          {
            method: "POST",
            body: {
              transactional: false,
              items: selection.map((loopId) => ({ loop_id: loopId, snooze_until_utc: snoozeUntilUtc })),
            },
          },
          "Failed to snooze selected loops",
        );
        clearLoopSelection();
        updateBulkActionBar();
        await bindings.refreshWorkspace();
        if (!result.ok) {
          throw new Error(`Only ${result.succeeded} of ${selection.length} selected loops snoozed.`);
        }
        return;
      }
      case "bulk-enrich": {
        if (!selection.length) {
          throw new Error("Select one or more loops before running this action.");
        }
        const result = await requestJson<BulkEnrichResponse, BulkEnrichRequest>(
          "/loops/bulk/enrich",
          {
            method: "POST",
            body: {
              items: selection.map((loopId) => ({ loop_id: loopId })),
            },
          },
          "Failed to enrich selected loops",
        );
        clearLoopSelection();
        updateBulkActionBar();
        await bindings.refreshWorkspace();
        if (!result.ok) {
          throw new Error(`Only ${result.succeeded} of ${selection.length} selected loops enriched.`);
        }
        return;
      }
      case "pin-current-location":
        await bindings.pinLocation(context.currentLocation, `Resume ${context.currentLocation.state}`, "Pinned from the command palette.");
        return;
      case "pin-selected-loops":
        if (!selection.length) {
          throw new Error("Select one or more loops before adding them to a working set.");
        }
        await bindings.addLoopIdsToActiveWorkingSet(selection);
        return;
    }
  }

  function baseNavigationCommands(context: CommandPaletteContext): CommandPaletteCommand[] {
    const commands: CommandPaletteCommand[] = [
      {
        id: "nav-home",
        group: "navigate",
        title: "Open home workspace",
        subtitle: "Return to the operator workspace overview",
        keywords: ["home", "operator", "workspace"],
        badge: "Home",
        location: createLocation({ state: "operator" }),
        detail: {
          eyebrow: "Navigate",
          description: "Return to the operator workspace and resume from the highest-signal home surface.",
          meta: ["Best for: broad orientation", "Scope: whole system"],
        },
        recentAction: { kind: "open-location", location: createLocation({ state: "operator" }) },
        execute: () => bindings.openLocation(createLocation({ state: "operator" })),
      },
      {
        id: "nav-capture",
        group: "navigate",
        title: "Open capture",
        subtitle: "Jump to quick capture and inbox triage",
        keywords: ["capture", "inbox", "collect"],
        badge: "Capture",
        location: createLocation({ state: "capture" }),
        detail: {
          eyebrow: "Navigate",
          description: "Jump straight into capture when new work or raw context needs to be recorded quickly.",
          meta: ["Best for: ingesting new work", "Keyboard hint: 2"],
        },
        recentAction: { kind: "open-location", location: createLocation({ state: "capture" }) },
        execute: () => bindings.openLocation(createLocation({ state: "capture" })),
      },
      {
        id: "nav-do",
        group: "navigate",
        title: "Open ready work",
        subtitle: "Jump to the Do surface for actionable loops",
        keywords: ["do", "next", "ready", "work"],
        badge: "Do",
        location: createLocation({ state: "do" }),
        detail: {
          eyebrow: "Navigate",
          description: "Open the Do surface when you want the shortest path to ready execution.",
          meta: ["Best for: focused execution", "Keyboard hint: 3"],
        },
        recentAction: { kind: "open-location", location: createLocation({ state: "do" }) },
        execute: () => bindings.openLocation(createLocation({ state: "do" })),
      },
      {
        id: "nav-relationship-review",
        group: "review",
        title: "Open relationship review",
        subtitle: "Jump to duplicate and related-loop decisions",
        keywords: ["decide", "relationship", "duplicates", "review"],
        badge: "Decide",
        location: createLocation({ state: "decide", reviewFocus: "relationship" }),
        detail: {
          eyebrow: "Review",
          description: "Enter the relationship queue when duplicate or related-loop judgment is the next operator task.",
          meta: ["Best for: ambiguity and cleanup", "Keyboard hint: 4"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "decide", reviewFocus: "relationship" }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "decide", reviewFocus: "relationship" })),
      },
      {
        id: "nav-plan",
        group: "review",
        title: "Open planning workspace",
        subtitle: "Resume checkpointed planning sessions",
        keywords: ["plan", "planning", "checkpoint"],
        badge: "Plan",
        location: createLocation({ state: "plan", reviewFocus: "planning" }),
        detail: {
          eyebrow: "Review",
          description: "Resume planning when you need a structured, checkpointed execution pass.",
          meta: ["Best for: multi-step work", "Keyboard hint: 5"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "plan", reviewFocus: "planning" }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "plan", reviewFocus: "planning" })),
      },
      {
        id: "nav-review",
        group: "review",
        title: "Open hygiene review",
        subtitle: "Run cohort-based review and drift cleanup",
        keywords: ["review", "hygiene", "cohort", "drift"],
        badge: "Review",
        location: createLocation({ state: "review", reviewFocus: "cohorts" }),
        detail: {
          eyebrow: "Review",
          description: "Open broader review when you want cohort-level cleanup instead of one saved queue.",
          meta: ["Best for: stale/blocked drift", "Keyboard hint: 6"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "review", reviewFocus: "cohorts" }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "review", reviewFocus: "cohorts" })),
      },
      {
        id: "nav-chat",
        group: "recall",
        title: "Open grounded chat",
        subtitle: "Ask grounded chat from the current operator context",
        keywords: ["chat", "assistant", "recall"],
        badge: "Recall",
        location: createLocation({ state: "recall", recallTool: "chat" }),
        detail: {
          eyebrow: "Recall",
          description: "Use grounded chat when you want a narrative synthesis across loops, memory, and live state.",
          meta: ["Best for: summarization", "Keyboard hint: 7"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "recall", recallTool: "chat" }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "recall", recallTool: "chat" })),
      },
      {
        id: "nav-memory",
        group: "recall",
        title: "Open memory",
        subtitle: "Jump to direct-memory management",
        keywords: ["memory", "facts", "preferences", "recall"],
        badge: "Recall",
        location: createLocation({ state: "recall", recallTool: "memory" }),
        detail: {
          eyebrow: "Recall",
          description: "Use Memory when durable facts or preferences should shape the next decision.",
          meta: ["Best for: durable context", "Surface: Recall → Memory"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "recall", recallTool: "memory" }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "recall", recallTool: "memory" })),
      },
      {
        id: "nav-documents",
        group: "recall",
        title: "Open documents",
        subtitle: "Jump to document-backed recall",
        keywords: ["documents", "rag", "knowledge", "recall"],
        badge: "Recall",
        location: createLocation({ state: "recall", recallTool: "rag" }),
        detail: {
          eyebrow: "Recall",
          description: "Open document-backed recall when local files should ground the next decision.",
          meta: ["Best for: evidence-backed recall", "Surface: Recall → Documents"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "recall", recallTool: "rag" }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "recall", recallTool: "rag" })),
      },
    ];

    const activeSet = context.workingSetContext?.active_working_set ?? null;
    if (activeSet) {
      const location = workingSetSessionLocation(activeSet.id);
      commands.push({
        id: `working-set-active-${activeSet.id}`,
        group: "navigate",
        title: `Resume working set · ${activeSet.name}`,
        subtitle: "Open the dedicated working-set session surface",
        keywords: ["working set", "resume", "session", activeSet.name],
        badge: "Set",
        location,
        contextBoost: 88,
        detail: {
          eyebrow: "Navigate",
          description: "Restore the full working-set context as a dedicated shell session, not as a single anchor item.",
          meta: [
            `${activeSet.item_count} item${activeSet.item_count === 1 ? "" : "s"}`,
            context.workingSetContext?.focus_mode_enabled ? "Focus mode already enabled" : "Focus mode currently paused",
          ],
        },
        recentAction: {
          kind: "working-set-context",
          workingSetId: activeSet.id,
          focusModeEnabled: Boolean(context.workingSetContext?.focus_mode_enabled),
        },
        execute: () => bindings.openLocation(location),
      });
    }

    context.workingSets.forEach((workingSet) => {
      const location = workingSetSessionLocation(workingSet.id);

      commands.push({
        id: `working-set-open-${workingSet.id}`,
        group: "navigate",
        title: `Open working set · ${workingSet.name}`,
        subtitle: workingSet.description ?? "Saved cross-surface resume context",
        keywords: ["working set", "focus", "resume", "session", workingSet.name],
        badge: "Set",
        location,
        contextBoost:
          context.workingSetContext?.active_working_set_id === workingSet.id ? 60 : 0,
        detail: {
          eyebrow: "Navigate",
          description: "Open this working set as its own session surface and restore the full bounded context.",
          meta: [
            `${workingSet.item_count} item${workingSet.item_count === 1 ? "" : "s"}`,
            workingSet.missing_item_count ? `${workingSet.missing_item_count} missing anchor${workingSet.missing_item_count === 1 ? "" : "s"}` : "No missing anchors",
          ],
        },
        recentAction: {
          kind: "working-set-context",
          workingSetId: workingSet.id,
          focusModeEnabled: false,
        },
        execute: () => bindings.openLocation(location),
      });
      commands.push({
        id: `working-set-focus-${workingSet.id}`,
        group: "navigate",
        title: `Focus working set · ${workingSet.name}`,
        subtitle: "Open the working-set session and turn on focus mode",
        keywords: ["working set", "focus", "session", workingSet.name],
        badge: "Set",
        location,
        contextBoost:
          context.workingSetContext?.active_working_set_id === workingSet.id
          && context.workingSetContext?.focus_mode_enabled
            ? 75
            : 0,
        detail: {
          eyebrow: "Navigate",
          description: "Restore the session surface and explicitly enter focus mode for this bounded context.",
          meta: [
            `${workingSet.item_count} item${workingSet.item_count === 1 ? "" : "s"}`,
            workingSet.last_activated_at_utc ? `Last resumed ${formatRelativeTime(workingSet.last_activated_at_utc)}` : "Not resumed yet",
          ],
        },
        recentAction: {
          kind: "working-set-context",
          workingSetId: workingSet.id,
          focusModeEnabled: true,
        },
        execute: async () => {
          await bindings.setWorkingSetContext(workingSet.id, true);
          await bindings.openLocation(location);
        },
      });
    });

    return commands;
  }

  function baseCaptureCommands(): CommandPaletteCommand[] {
    return [
      {
        id: "capture-loop-prompt",
        group: "capture",
        title: "Capture loop from palette",
        subtitle: "Create a loop without leaving the keyboard",
        keywords: ["capture", "loop", "new task"],
        badge: "Capture",
        detail: {
          eyebrow: "Capture",
          description: "Open a quick prompt, capture a loop, and jump directly to the resulting work surface.",
          meta: ["Uses: /loops/capture", "Outcome: new loop"],
        },
        recentAction: { kind: "capture-loop" },
        execute: () => executeRecentAction({ kind: "capture-loop" }),
      },
      {
        id: "capture-memory-prompt",
        group: "capture",
        title: "Create memory entry",
        subtitle: "Store durable context directly from the palette",
        keywords: ["memory", "context", "fact", "preference"],
        badge: "Capture",
        detail: {
          eyebrow: "Capture",
          description: "Create a memory entry when context should persist beyond the current session or loop.",
          meta: ["Uses: /memory", "Outcome: durable memory entry"],
        },
        recentAction: { kind: "create-memory" },
        execute: () => executeRecentAction({ kind: "create-memory" }),
      },
      {
        id: "capture-planning-session",
        group: "capture",
        title: "Create planning session",
        subtitle: "Seed a checkpointed plan from the palette",
        keywords: ["planning", "plan", "seed", "checkpoint"],
        badge: "Capture",
        detail: {
          eyebrow: "Capture",
          description: "Create a new checkpointed planning session without manually navigating into the review workspace first.",
          meta: ["Uses: /loops/planning/sessions", "Outcome: saved planning session"],
        },
        recentAction: { kind: "create-planning-session" },
        execute: () => executeRecentAction({ kind: "create-planning-session" }),
      },
    ];
  }

  function baseActCommands(context: CommandPaletteContext): CommandPaletteCommand[] {
    const selectedIds = selectedLoopIdList();
    const selectionLabel = selectedIds.length ? countLabel(selectedIds.length) : "Select loops first";

    const commands: CommandPaletteCommand[] = [
      {
        id: "act-pin-current-location",
        group: "act",
        title: "Pin current surface to working set",
        subtitle: "Save the current location as a durable resume anchor",
        keywords: ["pin", "working set", "anchor", "resume"],
        badge: "Act",
        detail: {
          eyebrow: "Act",
          description: "Add the current shell location to the active working set so you can resume it later from one command.",
          meta: ["Uses: working-set items", `Current state: ${context.currentLocation.state}`],
        },
        recentAction: { kind: "pin-current-location" },
        execute: () => executeRecentAction({ kind: "pin-current-location" }),
      },
      {
        id: "act-pin-selected-loops",
        group: "act",
        title: "Add selected loops to working set",
        subtitle: selectedIds.length ? `Save ${selectionLabel} into the active working set` : "Select loops in Do or Capture first",
        keywords: ["pin", "working set", "selected", "loops"],
        badge: "Act",
        contextBoost: selectedIds.length ? 70 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Push the current loop selection into the active working set so the same bundle can be resumed later.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Best for: bounded execution context"],
        },
        recentAction: { kind: "pin-selected-loops" },
        execute: () => executeRecentAction({ kind: "pin-selected-loops" }),
      },
      {
        id: "act-complete-selection",
        group: "act",
        title: "Complete selected loops",
        subtitle: selectedIds.length ? `Mark ${selectionLabel} completed` : "Select loops before completing them",
        keywords: ["complete", "selected", "done", "close"],
        badge: "Act",
        contextBoost: selectedIds.length ? 82 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Complete the selected loops in one keyboard-first action using the shared bulk close contract.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Confirmation: explicit"],
        },
        recentAction: { kind: "bulk-close", status: "completed" },
        execute: () => executeRecentAction({ kind: "bulk-close", status: "completed" }),
      },
      {
        id: "act-drop-selection",
        group: "act",
        title: "Drop selected loops",
        subtitle: selectedIds.length ? `Mark ${selectionLabel} dropped` : "Select loops before dropping them",
        keywords: ["drop", "selected", "discard"],
        badge: "Act",
        contextBoost: selectedIds.length ? 74 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Drop the selected loops using the shared bulk close contract when the work should be intentionally removed.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Confirmation: explicit"],
        },
        recentAction: { kind: "bulk-close", status: "dropped" },
        execute: () => executeRecentAction({ kind: "bulk-close", status: "dropped" }),
      },
      {
        id: "act-set-actionable",
        group: "act",
        title: "Mark selected loops actionable",
        subtitle: selectedIds.length ? `Move ${selectionLabel} into actionable` : "Select loops before updating status",
        keywords: ["actionable", "status", "selected"],
        badge: "Act",
        contextBoost: selectedIds.length ? 72 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Move the selected loops into actionable status without leaving the palette.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Uses: /loops/bulk/update"],
        },
        recentAction: { kind: "bulk-status", status: "actionable" },
        execute: () => executeRecentAction({ kind: "bulk-status", status: "actionable" }),
      },
      {
        id: "act-set-blocked",
        group: "act",
        title: "Mark selected loops blocked",
        subtitle: selectedIds.length ? `Move ${selectionLabel} into blocked` : "Select loops before updating status",
        keywords: ["blocked", "status", "selected"],
        badge: "Act",
        contextBoost: selectedIds.length ? 70 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Move the selected loops into blocked status without leaving the palette.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Uses: /loops/bulk/update"],
        },
        recentAction: { kind: "bulk-status", status: "blocked" },
        execute: () => executeRecentAction({ kind: "bulk-status", status: "blocked" }),
      },
      {
        id: "act-set-scheduled",
        group: "act",
        title: "Mark selected loops scheduled",
        subtitle: selectedIds.length ? `Move ${selectionLabel} into scheduled` : "Select loops before updating status",
        keywords: ["scheduled", "status", "selected"],
        badge: "Act",
        contextBoost: selectedIds.length ? 68 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Move the selected loops into scheduled status without leaving the palette.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Uses: /loops/bulk/update"],
        },
        recentAction: { kind: "bulk-status", status: "scheduled" },
        execute: () => executeRecentAction({ kind: "bulk-status", status: "scheduled" }),
      },
      {
        id: "act-set-inbox",
        group: "act",
        title: "Return selected loops to inbox",
        subtitle: selectedIds.length ? `Move ${selectionLabel} back to inbox` : "Select loops before updating status",
        keywords: ["inbox", "status", "selected"],
        badge: "Act",
        contextBoost: selectedIds.length ? 66 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Return the selected loops to inbox when they should be re-triaged rather than acted immediately.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Uses: /loops/bulk/update"],
        },
        recentAction: { kind: "bulk-status", status: "inbox" },
        execute: () => executeRecentAction({ kind: "bulk-status", status: "inbox" }),
      },
      {
        id: "act-snooze-selection",
        group: "act",
        title: "Snooze selected loops",
        subtitle: selectedIds.length ? `Hide ${selectionLabel} until a later date` : "Select loops before snoozing them",
        keywords: ["snooze", "selected", "later", "defer"],
        badge: "Act",
        contextBoost: selectedIds.length ? 78 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Prompt for a future date/time and snooze the selected loops through the shared bulk snooze contract.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Prompt: snooze timestamp"],
        },
        recentAction: { kind: "bulk-snooze" },
        execute: () => executeRecentAction({ kind: "bulk-snooze" }),
      },
      {
        id: "act-enrich-selection",
        group: "act",
        title: "Enrich selected loops",
        subtitle: selectedIds.length ? `Run enrichment for ${selectionLabel}` : "Select loops before enriching them",
        keywords: ["enrich", "selected", "ai"],
        badge: "Act",
        contextBoost: selectedIds.length ? 76 : 0,
        disabled: !selectedIds.length,
        detail: {
          eyebrow: "Act",
          description: "Run explicit enrichment for the selected loops using the shared bulk enrich contract.",
          meta: [selectedIds.length ? `${selectionLabel} ready` : "Needs: loop selection", "Uses: /loops/bulk/enrich"],
        },
        recentAction: { kind: "bulk-enrich" },
        execute: () => executeRecentAction({ kind: "bulk-enrich" }),
      },
    ];

    return commands;
  }

  function sessionCommands(
    context: CommandPaletteContext,
    outcomes: readonly RankedLandedOutcome[],
  ): CommandPaletteCommand[] {
    const commands: CommandPaletteCommand[] = [];
    const activeWorkingSet = context.workingSetContext?.active_working_set ?? null;
    const activeWorkingSetId = context.workingSetContext?.active_working_set_id ?? null;
    const activeWorkingSetName = activeWorkingSet?.name ?? null;
    const followThroughLocations = new Set(
      outcomes.map((item) => continuityLocationIdentity(item.resumeLocation)),
    );
    const scopedSubtitle = (base: string): string => {
      return activeWorkingSetName ? `${base} · ${activeWorkingSetName}` : base;
    };

    context.planningSessions.slice(0, 6).forEach((session) => {
      const scopedLocation = createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: session.id,
        workingSetId: activeWorkingSetId,
      });
      const scopedToActiveWorkingSet = activeWorkingSetId != null
        && followThroughLocations.has(continuityLocationIdentity(scopedLocation));
      const location = scopedToActiveWorkingSet
        ? scopedLocation
        : createLocation({
            state: "plan",
            reviewFocus: "planning",
            sessionId: session.id,
            workingSetId: null,
          });
      commands.push({
        id: `planning-session-${session.id}`,
        group: "review",
        title: `Resume plan · ${session.name}`,
        subtitle: scopedToActiveWorkingSet
          ? scopedSubtitle(`${session.executed_checkpoint_count}/${session.checkpoint_count} checkpoints executed`)
          : `${session.executed_checkpoint_count}/${session.checkpoint_count} checkpoints executed`,
        keywords: ["plan", "planning", session.name, session.prompt, activeWorkingSetName ?? ""],
        badge: "Plan",
        location,
        contextBoost: scopedToActiveWorkingSet ? 86 : 0,
        detail: {
          eyebrow: "Review",
          description: scopedToActiveWorkingSet
            ? "Resume this saved planning session with the active working-set scope restored."
            : "Resume this saved planning session at its current checkpointed state.",
          meta: [
            `Status: ${session.status.replaceAll("_", " ")}`,
            session.updated_at_utc ? `Updated ${formatRelativeTime(session.updated_at_utc)}` : "No update timestamp",
            scopedToActiveWorkingSet && activeWorkingSetName ? `Working set: ${activeWorkingSetName}` : null,
          ].filter((value): value is string => Boolean(value)),
        },
        recentAction: { kind: "open-location", location },
        execute: () => bindings.openLocation(location),
      });
    });
    context.relationshipSessions.slice(0, 6).forEach((session) => {
      const scopedLocation = createLocation({
        state: "decide",
        reviewFocus: "relationship",
        sessionId: session.id,
        workingSetId: activeWorkingSetId,
      });
      const scopedToActiveWorkingSet = activeWorkingSetId != null
        && followThroughLocations.has(continuityLocationIdentity(scopedLocation));
      const location = scopedToActiveWorkingSet
        ? scopedLocation
        : createLocation({
            state: "decide",
            reviewFocus: "relationship",
            sessionId: session.id,
            workingSetId: null,
          });
      commands.push({
        id: `relationship-session-${session.id}`,
        group: "review",
        title: `Open relationship queue · ${session.name}`,
        subtitle: scopedToActiveWorkingSet ? scopedSubtitle(session.query) : session.query,
        keywords: ["relationship", "duplicates", "review", session.name, session.query, activeWorkingSetName ?? ""],
        badge: "Decide",
        location,
        contextBoost: scopedToActiveWorkingSet ? 84 : 0,
        detail: {
          eyebrow: "Review",
          description: scopedToActiveWorkingSet
            ? "Open this saved relationship-review queue with the active working-set scope restored."
            : "Open this saved relationship-review queue at its preserved cursor.",
          meta: [
            `Relationship kind: ${session.relationship_kind}`,
            session.updated_at_utc ? `Updated ${formatRelativeTime(session.updated_at_utc)}` : "No update timestamp",
            scopedToActiveWorkingSet && activeWorkingSetName ? `Working set: ${activeWorkingSetName}` : null,
          ].filter((value): value is string => Boolean(value)),
        },
        recentAction: { kind: "open-location", location },
        execute: () => bindings.openLocation(location),
      });
    });
    context.enrichmentSessions.slice(0, 6).forEach((session) => {
      const scopedLocation = createLocation({
        state: "decide",
        reviewFocus: "enrichment",
        sessionId: session.id,
        workingSetId: activeWorkingSetId,
      });
      const scopedToActiveWorkingSet = activeWorkingSetId != null
        && followThroughLocations.has(continuityLocationIdentity(scopedLocation));
      const location = scopedToActiveWorkingSet
        ? scopedLocation
        : createLocation({
            state: "decide",
            reviewFocus: "enrichment",
            sessionId: session.id,
            workingSetId: null,
          });
      commands.push({
        id: `enrichment-session-${session.id}`,
        group: "review",
        title: `Open enrichment queue · ${session.name}`,
        subtitle: scopedToActiveWorkingSet ? scopedSubtitle(session.query) : session.query,
        keywords: ["enrichment", "clarifications", "review", session.name, session.query, activeWorkingSetName ?? ""],
        badge: "Decide",
        location,
        contextBoost: scopedToActiveWorkingSet ? 84 : 0,
        detail: {
          eyebrow: "Review",
          description: scopedToActiveWorkingSet
            ? "Open this saved enrichment queue with the active working-set scope restored."
            : "Open this saved enrichment queue at its preserved cursor.",
          meta: [
            `Pending kind: ${session.pending_kind}`,
            session.updated_at_utc ? `Updated ${formatRelativeTime(session.updated_at_utc)}` : "No update timestamp",
            scopedToActiveWorkingSet && activeWorkingSetName ? `Working set: ${activeWorkingSetName}` : null,
          ].filter((value): value is string => Boolean(value)),
        },
        recentAction: { kind: "open-location", location },
        execute: () => bindings.openLocation(location),
      });
    });
    return commands;
  }

  function savedViewCommands(views: readonly LoopViewResponse[]): CommandPaletteCommand[] {
    return views.slice(0, 8).map((view) => {
      const location = createLocation({ state: "capture", viewId: view.id });
      return {
        id: `view-${view.id}`,
        group: "navigate",
        title: `Open saved view · ${view.name}`,
        subtitle: view.description ?? view.query,
        keywords: ["view", view.name, view.query],
        badge: "View",
        location,
        detail: {
          eyebrow: "Navigate",
          description: "Open this saved view as a typed query anchor inside the capture/inbox surface.",
          meta: [`Query: ${view.query}`, `Updated ${formatRelativeTime(view.updated_at_utc)}`],
        },
        recentAction: { kind: "open-location", location },
        execute: () => bindings.openLocation(location),
      } satisfies CommandPaletteCommand;
    });
  }

  function recallQueryCommands(query: string): CommandPaletteCommand[] {
    if (query.trim().length < 2) {
      return [];
    }
    return [
      {
        id: `query-chat:${query}`,
        group: "recall",
        title: `Ask grounded chat · “${query}”`,
        subtitle: "Send this question straight into grounded chat",
        keywords: ["chat", "question", query],
        badge: "Recall",
        detail: {
          eyebrow: "Recall",
          description: "Open grounded chat and send this question immediately.",
          meta: ["Action: sends a chat message", "Grounding: loops + memory by default"],
        },
        recentAction: { kind: "ask-chat", query },
        execute: () => executeRecentAction({ kind: "ask-chat", query }),
      },
      {
        id: `query-memory:${query}`,
        group: "recall",
        title: `Search memory · “${query}”`,
        subtitle: "Open Memory with this query already applied",
        keywords: ["memory", "search", query],
        badge: "Recall",
        location: createLocation({ state: "recall", recallTool: "memory", query }),
        detail: {
          eyebrow: "Recall",
          description: "Jump into Memory with the search query already applied so you can scan durable context quickly.",
          meta: ["Action: opens Memory and applies query", "Best for: durable facts and preferences"],
        },
        recentAction: { kind: "memory-search", query },
        execute: () => executeRecentAction({ kind: "memory-search", query }),
      },
      {
        id: `query-docs:${query}`,
        group: "recall",
        title: `Ask documents · “${query}”`,
        subtitle: "Open Documents and run the question against indexed local files",
        keywords: ["documents", "rag", "search", query],
        badge: "Recall",
        location: createLocation({ state: "recall", recallTool: "rag", query }),
        detail: {
          eyebrow: "Recall",
          description: "Open document-backed recall and run this question against indexed local documents.",
          meta: ["Action: opens Documents and submits query", "Best for: evidence-backed recall"],
        },
        recentAction: { kind: "document-ask", query },
        execute: () => executeRecentAction({ kind: "document-ask", query }),
      },
      {
        id: `query-do:${query}`,
        group: "navigate",
        title: `Open Do filtered by · “${query}”`,
        subtitle: "Use this query as a launch anchor in the Do surface",
        keywords: ["query", "filter", "do", query],
        badge: "Search",
        location: createLocation({ state: "do", query }),
        detail: {
          eyebrow: "Search",
          description: "Open the Do surface with this query anchor applied so execution stays scoped.",
          meta: ["Action: opens Do with query anchor", "Best for: bounded execution slices"],
        },
        recentAction: { kind: "open-location", location: createLocation({ state: "do", query }) },
        execute: () => bindings.openLocation(createLocation({ state: "do", query })),
      },
      {
        id: `query-review:${query}`,
        group: "navigate",
        title: `Open Review filtered by · “${query}”`,
        subtitle: "Use this query as a hygiene/review anchor",
        keywords: ["query", "filter", "review", query],
        badge: "Search",
        location: createLocation({ state: "review", reviewFocus: "cohorts", query }),
        detail: {
          eyebrow: "Search",
          description: "Open the Review surface with this query anchor applied so the hygiene pass starts from the right slice.",
          meta: ["Action: opens Review with query anchor", "Best for: targeted cleanup"],
        },
        recentAction: {
          kind: "open-location",
          location: createLocation({ state: "review", reviewFocus: "cohorts", query }),
        },
        execute: () => bindings.openLocation(createLocation({ state: "review", reviewFocus: "cohorts", query })),
      },
    ];
  }

  function loopResultCommands(query: string, loops: readonly LoopResponse[]): CommandPaletteCommand[] {
    return loops.map((loop) => {
      const location = createLocation({ state: "do", loopId: loop.id });
      return {
        id: `loop-${loop.id}`,
        group: "search",
        title: loopTitle(loop),
        subtitle: loopSummary(loop),
        keywords: ["loop", loop.status, ...(loop.tags ?? []), loop.project ?? ""],
        badge: "Loop",
        location,
        contextBoost: normalizeText(loopTitle(loop)).startsWith(normalizeText(query)) ? 26 : 0,
        detail: {
          eyebrow: "Search",
          description: "Open this exact loop inside the Do surface.",
          meta: [
            `Status: ${loop.status}`,
            loop.project ? `Project: ${loop.project}` : "No project",
          ],
        },
        recentAction: { kind: "open-location", location },
        execute: () => bindings.openLocation(location),
      } satisfies CommandPaletteCommand;
    });
  }

  function memoryResultCommands(items: readonly MemoryEntryResponse[]): CommandPaletteCommand[] {
    return items.map((item) => {
      const location = createLocation({ state: "recall", recallTool: "memory", memoryId: item.id });
      return {
        id: `memory-${item.id}`,
        group: "search",
        title: item.key?.trim() || `Memory #${item.id}`,
        subtitle: item.content,
        keywords: ["memory", item.category, item.source, item.key ?? ""],
        badge: "Memory",
        location,
        detail: {
          eyebrow: "Search",
          description: "Open this exact memory entry inside the Memory workspace.",
          meta: [
            `Category: ${item.category}`,
            `Priority: ${item.priority}`,
          ],
        },
        recentAction: { kind: "open-location", location },
        execute: () => bindings.openLocation(location),
      } satisfies CommandPaletteCommand;
    });
  }

  function continuityLocationLabel(location: ShellLocationContract): string {
    switch (location.state) {
      case "plan":
        return location.sessionId != null ? `Plan #${location.sessionId}` : "Planning workspace";
      case "decide":
        return location.sessionId != null
          ? `${location.reviewFocus ?? "review"} queue #${location.sessionId}`
          : "Decision workspace";
      case "working_set":
        return location.workingSetId != null ? `Working set #${location.workingSetId}` : "Working-set workspace";
      case "do":
        return location.loopId != null ? `Loop #${location.loopId}` : "Do workspace";
      case "recall":
        return location.recallTool === "chat"
          ? "Grounded chat"
          : location.recallTool === "memory"
            ? "Memory"
            : "Documents";
      default:
        return "Operator workspace";
    }
  }

  function buildRecoveryPaletteCommand(input: {
    id: string;
    group: "recommended" | "recent";
    title: string;
    recovery: ContinuityRecoveryPlan;
    keywords: string[];
    continuityRank: number;
    continuitySignals: RankedLandedOutcome["rankingSignals"];
  }): CommandPaletteCommand {
    return {
      id: input.id,
      group: input.group,
      title: `${input.recovery.ctaLabel} · ${input.title}`,
      subtitle: input.recovery.summary,
      keywords: [
        ...input.keywords,
        input.recovery.title,
        input.recovery.summary,
        input.recovery.nextStep,
        "recover",
        "replacement",
        "fallback",
      ],
      badge: input.recovery.kind === "replacement" ? "Replacement" : "Recover",
      location: input.recovery.location,
      continuityRank: input.continuityRank + 48,
      continuitySignals: {
        driftScore: input.continuitySignals.driftScore,
        workingSetRelevant: input.continuitySignals.workingSetRelevant,
        downstreamReady: true,
        degraded: false,
        recencyTieBreaker: input.continuitySignals.recencyTieBreaker,
      },
      detail: {
        eyebrow: "Continuity recovery",
        description: input.recovery.nextStep,
        meta: [
          input.recovery.title,
          input.recovery.summary,
          `Destination: ${continuityLocationLabel(input.recovery.location)}`,
        ],
        recovery: input.recovery,
      },
      recentAction: { kind: "open-location", location: input.recovery.location },
      execute: async () => {
        markContinuityRecoveryAcknowledged(input.recovery.key);
        await bindings.openLocation(input.recovery.location);
      },
    } satisfies CommandPaletteCommand;
  }

  function recommendedCommands(
    context: CommandPaletteContext,
    outcomes: readonly RankedLandedOutcome[],
    recommendation = primaryRecommendationForContext(context, outcomes),
  ): CommandPaletteCommand[] {
    if (!recommendation) {
      return [];
    }

    const item = recommendation.representative;
    if (recommendation.recovery && !recommendation.recovery.acknowledged) {
      return [buildRecoveryPaletteCommand({
        id: `recommended-recovery-${item.id}`,
        group: "recommended",
        title: recommendation.workflow.thread.title,
        recovery: recommendation.recovery,
        keywords: [
          recommendation.workflow.thread.title,
          recommendation.card.summary,
          item.displayTitle,
          item.displaySummary,
          ...recommendation.whyNow,
          ...recommendation.changedSinceLastSeen,
        ],
        continuityRank: item.rank + 400,
        continuitySignals: item.rankingSignals,
      })];
    }

    return [{
      id: `recommended-${item.id}`,
      group: "recommended",
      title: `Next move · ${recommendation.workflow.thread.title}`,
      subtitle: recommendation.card.summary,
      keywords: [
        recommendation.workflow.thread.title,
        recommendation.card.summary,
        item.displayTitle,
        item.displaySummary,
        ...recommendation.whyNow,
        ...recommendation.changedSinceLastSeen,
      ],
      badge: "Next move",
      location: item.resumeLocation,
      continuityRank: item.rank + 400,
      continuitySignals: {
        driftScore: item.rankingSignals.driftScore,
        workingSetRelevant: item.rankingSignals.workingSetRelevant,
        downstreamReady: item.rankingSignals.downstreamReady,
        degraded: item.rankingSignals.degraded,
        recencyTieBreaker: item.rankingSignals.recencyTieBreaker,
      },
      detail: {
        eyebrow: "Recommended next move",
        description: recommendation.card.rationale,
        meta: [
          ...recommendation.whyNow,
          ...recommendation.changedSinceLastSeen,
          recommendation.priorState
            ? `${recommendation.priorState.kind === "gone" ? "Prior path gone" : "Prior path replaced"}: ${recommendation.priorState.summary}`
            : null,
        ].filter((value): value is string => Boolean(value)),
        trust: recommendation.card.trust,
        recovery: recommendation.recovery ?? undefined,
      },
      recentAction: { kind: "open-location", location: item.resumeLocation },
      execute: async () => {
        await bindings.openLocation(item.resumeLocation);
      },
    } satisfies CommandPaletteCommand];
  }

  function recentCommands(
    context: CommandPaletteContext,
    outcomes: readonly RankedLandedOutcome[],
    excludedThreadId: string | null,
  ): CommandPaletteCommand[] {
    const activeWorkingSetName = context.workingSetContext?.active_working_set?.name ?? null;
    const grouped = groupRankedWorkflowThreads(outcomes)
      .filter((thread) => thread.id !== excludedThreadId)
      .slice(0, 8);

    return grouped.flatMap((thread) => {
      const item = thread.representative;
      const commands: CommandPaletteCommand[] = [];
      const rerunAction = item.rerunAction;
      const undoAction = item.undoAction;

      if (item.recovery && !item.recovery.acknowledged) {
        commands.push(buildRecoveryPaletteCommand({
          id: `recent-recovery-${item.id}`,
          group: "recent",
          title: thread.thread.title,
          recovery: item.recovery,
          keywords: [
            item.displayTitle,
            item.displaySummary,
            thread.thread.title,
            thread.thread.summary ?? "",
            item.workingSetName ?? "",
            activeWorkingSetName ?? "",
          ],
          continuityRank: item.rank + 32,
          continuitySignals: item.rankingSignals,
        }));
        return commands;
      }

      if (rerunAction && !rerunAction.disabledReason) {
        commands.push({
          id: `recent-rerun-${item.id}`,
          group: "recent",
          title: `${rerunAction.label}: ${thread.thread.title}`,
          subtitle: rerunAction.description,
          keywords: [
            rerunAction.label,
            "rerun",
            "refresh",
            item.displayTitle,
            item.displaySummary,
            thread.thread.title,
            thread.thread.summary ?? "",
            item.workingSetName ?? "",
            activeWorkingSetName ?? "",
          ],
          badge: rerunAction.contract.mode === "refresh" ? "Refresh" : "Rerun",
          location: item.resumeLocation,
          continuityRank: item.rank + 28,
          continuitySignals: {
            driftScore: item.rankingSignals.driftScore,
            workingSetRelevant: item.rankingSignals.workingSetRelevant,
            downstreamReady: item.rankingSignals.downstreamReady,
            degraded: item.rankingSignals.degraded,
            recencyTieBreaker: item.rankingSignals.recencyTieBreaker,
          },
          detail: {
            eyebrow: rerunAction.contract.mode === "refresh" ? "Recent refresh" : "Recent rerun",
            description: rerunAction.description,
            meta: [
              `Thread: ${thread.thread.title}`,
              `Strict: ${rerunAction.contract.strictInvariants.join(" · ")}`,
              `May vary: ${rerunAction.contract.mayVary.join(" · ")}`,
              rerunAction.contract.freshnessLabel,
              item.degradedLabel,
            ].filter((value): value is string => Boolean(value)),
          },
          skipAutomaticReceipt: true,
          execute: async () => {
            try {
              const result = await runExecutableRerunAction(rerunAction, {
                rerunRecallQuery: async (handle) => {
                  const location = createLocation({
                    state: "recall",
                    recallTool: handle.recallTool,
                    workingSetId: handle.workingSetId,
                    query: handle.query,
                  });
                  await bindings.openLocation(location);
                },
              });
              recordRecentShellAction(result.entry);
              await bindings.refreshWorkspace();
              if (result.resumeLocation && rerunAction.rerun.kind !== "recall_query") {
                await bindings.openLocation(result.resumeLocation);
              }
            } catch (error: unknown) {
              const reason = staleRerunReason(error);
              if (reason) {
                markRerunActionUnavailable(rerunAction.rerun, reason);
              }
              throw error;
            }
          },
        } satisfies CommandPaletteCommand);
      }

      if (undoAction && !undoAction.disabledReason) {
        commands.push({
          id: `recent-undo-${item.id}`,
          group: "recent",
          title: `${undoAction.label}: ${thread.thread.title}`,
          subtitle: undoAction.description,
          keywords: [
            "undo",
            "rollback",
            item.displayTitle,
            item.displaySummary,
            thread.thread.title,
            thread.thread.summary ?? "",
            item.workingSetName ?? "",
            activeWorkingSetName ?? "",
          ],
          badge: "Undo",
          location: item.resumeLocation,
          continuityRank: item.rank + 24,
          continuitySignals: {
            driftScore: item.rankingSignals.driftScore,
            workingSetRelevant: item.rankingSignals.workingSetRelevant,
            downstreamReady: item.rankingSignals.downstreamReady,
            degraded: item.rankingSignals.degraded,
            recencyTieBreaker: item.rankingSignals.recencyTieBreaker,
          },
          detail: {
            eyebrow: undoAction.undo.kind === "planning_run" ? "Recent rollback" : "Recent undo",
            description: undoAction.description,
            meta: [
              `Thread: ${thread.thread.title}`,
              item.workingSetName ? `Working set: ${item.workingSetName}` : null,
              `Recorded ${formatRelativeTime(item.occurredAt)}`,
              item.degradedLabel,
            ].filter((value): value is string => Boolean(value)),
          },
          skipAutomaticReceipt: true,
          execute: async () => {
            if (undoAction.requiresConfirmation && undoAction.confirmDescription?.trim()) {
              const confirmed = await modals.confirmDialog({
                eyebrow: undoAction.undo.kind === "planning_run" ? "Planning rollback" : "Undo",
                title: undoAction.confirmTitle?.trim() || undoAction.label,
                description: undoAction.confirmDescription.trim(),
                confirmLabel: undoAction.label,
                confirmVariant: "danger",
              });
              if (!confirmed) {
                return;
              }
            }
            try {
              const result = await runExecutableUndoAction(undoAction);
              recordRecentShellAction(result.entry);
              await bindings.refreshWorkspace();
              if (result.resumeLocation) {
                await bindings.openLocation(result.resumeLocation);
              }
            } catch (error: unknown) {
              const reason = staleUndoReason(error) ?? "Undo is no longer available.";
              markUndoActionUnavailable(undoAction.undo, reason);
              throw error;
            }
          },
        } satisfies CommandPaletteCommand);
      }

      commands.push({
        id: `recent-${item.id}`,
        group: "recent",
        title: thread.thread.title,
        subtitle: thread.thread.summary ?? item.displaySummary,
        keywords: [
          item.displayTitle,
          item.displaySummary,
          thread.thread.title,
          thread.thread.summary ?? "",
          item.resumeLocation.state,
          item.workingSetName ?? "",
          activeWorkingSetName ?? "",
        ],
        badge: item.workflowThread ? "Thread" : (item.source === "anchor" ? "Resume" : "Outcome"),
        location: item.resumeLocation,
        continuityRank: item.rank,
        continuitySignals: {
          driftScore: item.rankingSignals.driftScore,
          workingSetRelevant: item.rankingSignals.workingSetRelevant,
          downstreamReady: item.rankingSignals.downstreamReady,
          degraded: item.rankingSignals.degraded,
          recencyTieBreaker: item.rankingSignals.recencyTieBreaker,
        },
        detail: {
          eyebrow: item.workflowThread ? "Workflow thread" : (item.source === "anchor" ? "Resume anchor" : "Recent outcome"),
          description: item.degradedLabel
            ? item.degradedLabel
            : "Reopen the landed outcome using the same receipt and handoff contract shown in operator follow-through surfaces.",
          meta: [
            item.workflowThread ? `Thread: ${item.workflowThread.title}` : null,
            item.workingSetName ? `Working set: ${item.workingSetName}` : null,
            `Recorded ${formatRelativeTime(item.occurredAt)}`,
            item.rerunAction && !item.rerunAction.disabledReason
              ? `${item.rerunAction.contract.mode === "refresh" ? "Refresh" : "Rerun"} available`
              : item.undoAction && !item.undoAction.disabledReason
                ? "Undo available"
                : "Resume only",
          ].filter((value): value is string => Boolean(value)),
          recovery: item.recovery ?? undefined,
        },
        execute: async () => {
          await bindings.openLocation(item.resumeLocation);
        },
      } satisfies CommandPaletteCommand);

      return commands;
    });
  }

  async function buildCommands(query: string): Promise<CommandPaletteCommand[]> {
    const context = bindings.getContext();
    const normalizedQuery = query.trim();
    const views = await ensureViewsLoaded().catch(() => [] as LoopViewResponse[]);
    const outcomes = rankedFollowThrough(context);
    const recommendation = primaryRecommendationForContext(context, outcomes);
    const commands: CommandPaletteCommand[] = [
      ...recommendedCommands(context, outcomes, recommendation),
      ...recentCommands(context, outcomes, recommendation?.workflow.id ?? null),
      ...baseNavigationCommands(context),
      ...baseCaptureCommands(),
      ...baseActCommands(context),
      ...sessionCommands(context, outcomes),
      ...savedViewCommands(views),
      ...recallQueryCommands(normalizedQuery),
      ...loopResultCommands(normalizedQuery, localLoopMatches(normalizedQuery, context.loops)),
    ];

    if (normalizedQuery.length >= 2) {
      try {
        const memories = await searchMemories(normalizedQuery);
        commands.push(...memoryResultCommands(memories));
      } catch {
        // Ignore search-provider failures so deterministic/local commands still work.
      }
    }

    const ranking = rankPaletteItems(commands, rankingContext(query, context, readStoredRecentCommands()));
    return ranking.slice(0, normalizedQuery ? 24 : 18).map((entry) => entry.item);
  }

  function setOpen(nextOpen: boolean): void {
    open = nextOpen;
    elements.root.hidden = !nextOpen;
    document.body.classList.toggle("command-palette-open", nextOpen);
    if (!nextOpen) {
      elements.input.value = "";
      activeCommandId = null;
      visibleCommands = [];
      elements.results.innerHTML = "";
      elements.detail.innerHTML = '<p class="command-palette-empty-detail">Choose a command to see why it belongs here and what it will do.</p>';
      elements.status.textContent = "Closed.";
    }
  }

  async function renderCommands(): Promise<void> {
    const currentNonce = ++searchNonce;
    elements.status.textContent = "Ranking commands…";
    const query = elements.input.value;
    let commands: CommandPaletteCommand[] = [];
    try {
      commands = await buildCommands(query);
    } catch (error) {
      if (currentNonce !== searchNonce) {
        return;
      }
      visibleCommands = [];
      activeCommandId = null;
      elements.results.innerHTML = '<div class="command-palette-empty-state"><p>Commands are temporarily unavailable.</p><p>Try again in a moment or refresh the workspace.</p></div>';
      elements.detail.innerHTML = '<p class="command-palette-empty-detail">The palette could not load its current context. Deterministic shell navigation should return after a refresh.</p>';
      elements.status.textContent = error instanceof Error ? error.message : "Failed to load commands.";
      return;
    }
    if (currentNonce !== searchNonce) {
      return;
    }
    visibleCommands = commands;
    activeCommandId = commands[0]?.id ?? null;
    if (!commands.length) {
      elements.results.innerHTML = `
        <div class="command-palette-empty-state">
          <p>No commands matched “${escapeHtml(query.trim())}”.</p>
          <p>Try a loop title, a working-set name, a saved session, or a query like <code>status:blocked</code>.</p>
        </div>
      `;
      elements.detail.innerHTML = '<p class="command-palette-empty-detail">No result matched the current query. Try a broader search or clear the input to see recent and high-signal commands.</p>';
      elements.status.textContent = "No matching commands.";
      return;
    }
    elements.results.innerHTML = groupedResultsHtml(commands, activeCommandId);
    const current = activeCommand();
    elements.detail.innerHTML = current
      ? buildDetailHtml(current, selectedLoopIdList().length)
      : '<p class="command-palette-empty-detail">Choose a command to see detail.</p>';
    elements.status.textContent = `${commands.length} command${commands.length === 1 ? "" : "s"} ranked by current state, focus context, and recent usage.`;
  }

  function syncActiveCommand(nextId: string): void {
    activeCommandId = nextId;
    elements.results.querySelectorAll<HTMLElement>("[data-command-id]").forEach((element) => {
      const isActive = element.dataset["commandId"] === nextId;
      element.classList.toggle("is-active", isActive);
      element.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    const current = activeCommand();
    elements.detail.innerHTML = current
      ? buildDetailHtml(current, selectedLoopIdList().length)
      : '<p class="command-palette-empty-detail">Choose a command to see detail.</p>';
  }

  function moveSelection(step: 1 | -1): void {
    if (!visibleCommands.length) {
      return;
    }
    const index = visibleCommands.findIndex((command) => command.id === activeCommandId);
    const nextIndex = index < 0
      ? 0
      : (index + step + visibleCommands.length) % visibleCommands.length;
    const nextCommand = visibleCommands[nextIndex] ?? null;
    if (!nextCommand) {
      return;
    }
    syncActiveCommand(nextCommand.id);
    const activeButton = elements.results.querySelector<HTMLElement>(`[data-command-id="${CSS.escape(nextCommand.id)}"]`);
    activeButton?.scrollIntoView({ block: "nearest" });
  }

  async function runCommand(command: CommandPaletteCommand | null): Promise<void> {
    if (!command || command.disabled) {
      return;
    }
    elements.status.textContent = `Running ${command.title}…`;
    try {
      await command.execute();
      storeRecentCommand(command);
      if (!command.skipAutomaticReceipt) {
        const currentContext = bindings.getContext();
        const historyLocation = commandHistoryLocation(command, currentContext.currentLocation);
        const receiptCard = buildCommandReceipt(command, currentContext, historyLocation);
        recordRecentShellAction(
          withReceiptOutcome(
            {
              kind: commandHistoryKind(command),
              label: commandHistoryLabel(command, historyLocation),
              description: command.subtitle,
              location: historyLocation,
              metadata: {
                source: "command-palette",
                commandId: command.id,
                group: command.group,
                badge: command.badge,
              },
            },
            receiptCard,
            historyLocation,
          ),
        );
      }
      setOpen(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Command failed";
      elements.status.textContent = message;
    }
  }

  function openPalette(initialQuery = ""): void {
    setOpen(true);
    elements.input.value = initialQuery;
    void renderCommands();
    window.setTimeout(() => {
      elements.input.focus();
      elements.input.select();
    }, 0);
  }

  function closePalette(): void {
    setOpen(false);
  }

  elements.input.addEventListener("input", () => {
    void renderCommands();
  });
  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSelection(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSelection(-1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      void runCommand(activeCommand());
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closePalette();
    }
  });
  elements.results.addEventListener("mousemove", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLElement>("[data-command-id]");
    if (!button?.dataset["commandId"] || button.dataset["commandId"] === activeCommandId) {
      return;
    }
    syncActiveCommand(button.dataset["commandId"]);
  });
  elements.results.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLElement>("[data-command-id]");
    const commandId = button?.dataset["commandId"];
    if (!commandId) {
      return;
    }
    const command = visibleCommands.find((item) => item.id === commandId) ?? null;
    void runCommand(command);
  });
  elements.closeButtons.forEach((button) => {
    button.addEventListener("click", closePalette);
  });
  elements.overlay.addEventListener("click", closePalette);

  return {
    isOpen(): boolean {
      return open;
    },
    open(initialQuery?: string): void {
      openPalette(initialQuery);
    },
    handleGlobalHotkey(event: KeyboardEvent): boolean {
      const key = event.key.toLowerCase();
      const target = event.target;
      const targetIsEditable = target instanceof HTMLElement
        && (target.tagName === "INPUT"
          || target.tagName === "TEXTAREA"
          || target.tagName === "SELECT"
          || target.isContentEditable);
      const shouldOpen = (event.metaKey || event.ctrlKey) && key === "k";
      const shouldQuickOpen = !targetIsEditable && !event.metaKey && !event.ctrlKey && !event.altKey && key === "/";

      if (shouldOpen || shouldQuickOpen) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (open) {
          closePalette();
        } else {
          openPalette();
        }
        return true;
      }

      if (open && event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closePalette();
        return true;
      }

      return open;
    },
  } satisfies CommandPaletteController;
}
