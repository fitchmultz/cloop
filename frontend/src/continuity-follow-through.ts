/**
 * continuity-follow-through.ts - Canonical ranked landed-outcome follow-through feed.
 *
 * Purpose:
 *   Build one shared ranked landed-outcome model for operator follow-through
 *   surfaces so home, receipt rail, and palette recents consume the same data.
 *
 * Responsibilities:
 *   - Read recent landed outcomes and outcome-aware resume anchors.
 *   - Validate and safely degrade resume targets against current workspace availability.
 *   - Deduplicate anchors versus recent landed outcomes.
 *   - Normalize resume, undo, and pin affordances into one consistent card shape.
 *   - Rank landed outcomes deterministically for all follow-through consumers.
 *
 * Scope:
 *   - Frontend-only continuity ranking and card normalization.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts, shell.ts, and command-palette.ts.
 *
 * Invariants/Assumptions:
 *   - `RecentShellActionEntry.outcome` remains the canonical landed-outcome payload.
 *   - `outcome.resumeLocation` is preferred over launch location.
 *   - Anchor-only items are fallback continuity, not stronger than recent receipts.
 *   - Rerun remains intentionally reserved as `null` until the next roadmap slice.
 */

import type {
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardPinAction,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  ResumeAnchorState,
  ResumeAnchorTarget,
  ShellLocationContract,
  WorkingSetSessionMetadata,
} from "./contracts-ui";
import { readRecentShellActions, readResumeAnchors } from "./continuity-intelligence";
import {
  continuityLocationIdentity,
  recentShellActionDedupKey,
  resolveContinuityEntry,
} from "./continuity-outcomes";
import { formatRelativeTime } from "./shell-core";
import { createLocation } from "./shell-routing";

export interface ContinuityAvailability {
  planningSessionIds: ReadonlySet<number>;
  relationshipSessionIds: ReadonlySet<number>;
  enrichmentSessionIds: ReadonlySet<number>;
  workingSets: ReadonlyMap<number, WorkingSetSessionMetadata>;
}

export interface RankedLandedOutcome {
  id: string;
  source: "receipt" | "recent" | "anchor";
  rank: number;
  occurredAt: string;
  resumeLocation: ShellLocationContract;
  displayTitle: string;
  displaySummary: string;
  workingSetId: number | null;
  workingSetName: string | null;
  degraded: boolean;
  degradedLabel: string | null;
  card: OperatorActionCard;
  undoAction: OperatorActionCardUndoAction | null;
  rerunAction: OperatorActionCardAction | null;
}

export interface ReadRankedLandedOutcomesInput {
  availability: ContinuityAvailability;
  activeWorkingSetId?: number | null;
  recentActions?: readonly RecentShellActionEntry[];
  resumeAnchors?: ResumeAnchorState;
  now?: number;
}

export interface BuildContinuityAvailabilityInput {
  planningSessionIds?: readonly number[];
  relationshipSessionIds?: readonly number[];
  enrichmentSessionIds?: readonly number[];
  workingSets?: readonly WorkingSetSessionMetadata[];
}

function safeTimestamp(value: string): number {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function workingSetMetadata(
  availability: ContinuityAvailability,
  workingSetId: number | null | undefined,
): WorkingSetSessionMetadata | null {
  if (workingSetId == null) {
    return null;
  }
  return availability.workingSets.get(workingSetId) ?? null;
}

function workingSetName(
  availability: ContinuityAvailability,
  workingSetId: number | null | undefined,
): string | null {
  const metadata = workingSetMetadata(availability, workingSetId);
  if (metadata) {
    return metadata.workingSetName;
  }
  return workingSetId != null ? `Working set #${workingSetId}` : null;
}

function cloneLocation(location: ShellLocationContract): ShellLocationContract {
  return { ...location };
}

export function buildContinuityAvailability(input: BuildContinuityAvailabilityInput): ContinuityAvailability {
  return {
    planningSessionIds: new Set(input.planningSessionIds ?? []),
    relationshipSessionIds: new Set(input.relationshipSessionIds ?? []),
    enrichmentSessionIds: new Set(input.enrichmentSessionIds ?? []),
    workingSets: new Map((input.workingSets ?? []).map((metadata) => [metadata.workingSetId, metadata])),
  };
}

function locationExists(location: ShellLocationContract, availability: ContinuityAvailability): boolean {
  if (location.state === "working_set") {
    return location.workingSetId != null && availability.workingSets.has(location.workingSetId);
  }
  if (location.state === "plan" && location.sessionId != null) {
    return availability.planningSessionIds.size === 0 || availability.planningSessionIds.has(location.sessionId);
  }
  if (location.state === "decide" && location.reviewFocus === "relationship" && location.sessionId != null) {
    return availability.relationshipSessionIds.size === 0 || availability.relationshipSessionIds.has(location.sessionId);
  }
  if (location.state === "decide" && location.reviewFocus === "enrichment" && location.sessionId != null) {
    return availability.enrichmentSessionIds.size === 0 || availability.enrichmentSessionIds.has(location.sessionId);
  }
  return true;
}

export function fallbackFollowThroughLocation(
  location: ShellLocationContract | null,
  availability: ContinuityAvailability,
): { location: ShellLocationContract; degraded: boolean; degradedLabel: string | null } {
  if (!location) {
    return {
      location: createLocation({ state: "operator" }),
      degraded: true,
      degradedLabel: "Original outcome is no longer available, so this follow-through falls back to home.",
    };
  }

  if (location.workingSetId != null && !availability.workingSets.has(location.workingSetId)) {
    if (location.state === "working_set") {
      return {
        location: createLocation({ state: "operator" }),
        degraded: true,
        degradedLabel: "Working-set session is no longer available, so this follow-through falls back to home.",
      };
    }
    const unscopedLocation = createLocation({ ...location, workingSetId: null });
    if (locationExists(unscopedLocation, availability)) {
      return {
        location: unscopedLocation,
        degraded: true,
        degradedLabel: "Working-set scope was removed, so this follow-through falls back to the durable session or object.",
      };
    }
  }

  if (locationExists(location, availability)) {
    return {
      location: cloneLocation(location),
      degraded: false,
      degradedLabel: null,
    };
  }

  return {
    location: createLocation({ state: "operator" }),
    degraded: true,
    degradedLabel: "Original outcome is no longer available, so this follow-through falls back to home.",
  };
}

function buildResumeAction(location: ShellLocationContract, description: string): OperatorActionCardAction {
  return {
    type: "open",
    label: "Resume outcome",
    variant: "primary",
    description,
    location,
  };
}

function buildPinAction(
  location: ShellLocationContract,
  title: string,
  description: string,
  pinLabel: string,
): OperatorActionCardAction {
  return {
    type: "pin",
    label: "Pin outcome",
    variant: "secondary",
    description,
    location,
    pinLabel,
  };
}

function preferredPinLabel(card: OperatorActionCard): string {
  const pinAction = card.actions.find((action): action is OperatorActionCardPinAction => action.type === "pin") ?? null;
  return pinAction?.pinLabel ?? `Outcome · ${card.title}`;
}

function normalizeOutcomeCard(
  base: OperatorActionCard,
  resumeLocation: ShellLocationContract,
  summary: string,
  degradedLabel: string | null,
  undoAction: OperatorActionCardUndoAction | null,
  workingSet: WorkingSetSessionMetadata | null,
): OperatorActionCard {
  const carryForward = base.actions.filter((action) => {
    return action.type !== "open" && action.type !== "pin" && action.type !== "undo";
  });
  const actions: OperatorActionCardAction[] = [buildResumeAction(resumeLocation, degradedLabel ?? summary)];

  if (undoAction) {
    actions.push({
      ...undoAction,
      variant: "secondary",
    });
  }

  actions.push(buildPinAction(resumeLocation, base.title, degradedLabel ?? summary, preferredPinLabel(base)));
  actions.push(...carryForward);

  return {
    ...base,
    handoff: base.handoff
      ? {
          ...base.handoff,
          workingSet: base.handoff.workingSet ?? workingSet,
        }
      : base.handoff,
    actionContextLabel: actions.length ? "Continue from here" : (base.actionContextLabel ?? null),
    actionWarning: degradedLabel ?? base.actionWarning ?? null,
    actions,
  };
}

function anchorLabel(anchor: ResumeAnchorTarget): string {
  if (anchor.kind === "planning") {
    return `Planning session #${anchor.sessionId}`;
  }
  return `${anchor.reviewFocus} queue #${anchor.sessionId}`;
}

function anchorEyebrow(anchor: ResumeAnchorTarget): string {
  if (anchor.kind === "planning") {
    return "Resume plan";
  }
  return `Resume ${anchor.reviewFocus}`;
}

function anchorBreadcrumb(anchor: ResumeAnchorTarget): string {
  if (anchor.kind === "planning") {
    return "Plan";
  }
  return "Decide";
}

function buildAnchorCard(
  anchor: ResumeAnchorTarget,
  resumeLocation: ShellLocationContract,
  degradedLabel: string | null,
  workingSet: WorkingSetSessionMetadata | null,
): OperatorActionCard {
  const title = anchor.outcomeTitle ?? anchorLabel(anchor);
  const summary = anchor.outcomeSummary ?? "Resume the most recent landed workflow state from this browser.";
  const preview = [
    { label: "Last visited", value: formatRelativeTime(anchor.visitedAtUtc) },
    ...(workingSet ? [{ label: "Working set", value: workingSet.workingSetName }] : []),
  ];

  return {
    id: `follow-through-anchor-${anchor.kind}-${anchor.reviewFocus}-${anchor.sessionId}`,
    kind: "handoff",
    tone: "attention",
    eyebrow: anchorEyebrow(anchor),
    title,
    summary,
    rationale:
      "Outcome-aware resume anchors preserve the best durable handoff when there is no newer landed receipt to supersede it.",
    preview,
    trust: {
      generationLabel: "Browser-local resume anchor",
      generationTone: "attention",
      contextSources: ["Browser-local outcome continuity anchors"],
      assumptions: ["Resume anchors are local to this browser."],
      confidenceLabel: "Deterministic resume shortcut",
      confidenceTone: "progress",
      freshnessLabel: `Visited ${formatRelativeTime(anchor.visitedAtUtc)}`,
      freshnessTone: "neutral",
      rollbackLabel: "Opening an anchor restores context only; later mutations remain explicit.",
      rollbackTone: "neutral",
      impactSummary: summary,
      impactTone: "neutral",
    },
    handoff: {
      changeSummary: degradedLabel ?? "Resume the landed workflow state directly.",
      createdResources: [title],
      nextStep: "Reopen the saved workflow context and continue from the landed state.",
      breadcrumbs: ["Home", "Since last visit", anchorBreadcrumb(anchor)],
      workingSet,
    },
    actionContextLabel: "Continue from here",
    actionWarning: degradedLabel,
    actions: [
      buildResumeAction(resumeLocation, degradedLabel ?? summary),
      buildPinAction(resumeLocation, title, degradedLabel ?? summary, `Outcome · ${title}`),
    ],
  };
}

function scoreOutcome(input: {
  source: RankedLandedOutcome["source"];
  occurredAt: string;
  activeWorkingSetId: number | null;
  workingSetId: number | null;
  degraded: boolean;
  undoAction: OperatorActionCardUndoAction | null;
  now: number;
}): number {
  const ageMs = Math.max(0, input.now - safeTimestamp(input.occurredAt));
  const ageMinutes = ageMs / 60_000;
  const recencyScore = Math.max(0, 240 - Math.floor(ageMinutes / 15) * 8);
  const sourceScore = input.source === "receipt"
    ? 180
    : input.source === "recent"
      ? 140
      : 115;
  const activeWorkingSetBoost = input.activeWorkingSetId != null && input.workingSetId === input.activeWorkingSetId
    ? 42
    : 0;
  const undoBoost = input.undoAction && !input.undoAction.disabledReason ? 16 : 0;
  const degradedPenalty = input.degraded ? 36 : 0;

  return sourceScore + recencyScore + activeWorkingSetBoost + undoBoost - degradedPenalty;
}

function buildRecentOutcome(
  entry: RecentShellActionEntry,
  availability: ContinuityAvailability,
  activeWorkingSetId: number | null,
  now: number,
): RankedLandedOutcome | null {
  if (!entry.outcome?.card) {
    return null;
  }

  const resolved = resolveContinuityEntry(entry);
  const fallback = fallbackFollowThroughLocation(resolved.resumeLocation, availability);
  const workingSet = resolved.workingSet ?? workingSetMetadata(availability, resolved.workingSetId);
  const undoAction = entry.outcome.undoAction ?? null;
  const source: RankedLandedOutcome["source"] = entry.outcome.card.kind === "receipt" ? "receipt" : "recent";
  const card = normalizeOutcomeCard(
    entry.outcome.card,
    fallback.location,
    resolved.displaySummary,
    fallback.degraded ? fallback.degradedLabel : null,
    undoAction,
    workingSet,
  );

  return {
    id: `${source}-${recentShellActionDedupKey(entry)}`,
    source,
    rank: scoreOutcome({
      source,
      occurredAt: entry.occurredAt,
      activeWorkingSetId,
      workingSetId: resolved.workingSetId,
      degraded: fallback.degraded,
      undoAction,
      now,
    }),
    occurredAt: entry.occurredAt,
    resumeLocation: fallback.location,
    displayTitle: resolved.displayTitle,
    displaySummary: resolved.displaySummary,
    workingSetId: resolved.workingSetId,
    workingSetName: workingSet?.workingSetName ?? workingSetName(availability, resolved.workingSetId),
    degraded: fallback.degraded,
    degradedLabel: fallback.degraded ? fallback.degradedLabel : null,
    card,
    undoAction,
    rerunAction: null,
  };
}

function buildAnchorOutcome(
  anchor: ResumeAnchorTarget,
  availability: ContinuityAvailability,
  activeWorkingSetId: number | null,
  now: number,
): RankedLandedOutcome {
  const fallback = fallbackFollowThroughLocation(anchor.resumeLocation ?? anchor.launchLocation, availability);
  const workingSet = workingSetMetadata(availability, anchor.workingSetId);
  const card = buildAnchorCard(
    anchor,
    fallback.location,
    fallback.degraded ? fallback.degradedLabel : null,
    workingSet,
  );
  const displayTitle = anchor.outcomeTitle ?? anchorLabel(anchor);
  const displaySummary = anchor.outcomeSummary ?? "Resume the last saved landed workflow state.";

  return {
    id: `anchor-${anchor.kind}-${anchor.reviewFocus}-${anchor.sessionId}`,
    source: "anchor",
    rank: scoreOutcome({
      source: "anchor",
      occurredAt: anchor.visitedAtUtc,
      activeWorkingSetId,
      workingSetId: anchor.workingSetId,
      degraded: fallback.degraded,
      undoAction: null,
      now,
    }),
    occurredAt: anchor.visitedAtUtc,
    resumeLocation: fallback.location,
    displayTitle,
    displaySummary,
    workingSetId: anchor.workingSetId,
    workingSetName: workingSet?.workingSetName ?? workingSetName(availability, anchor.workingSetId),
    degraded: fallback.degraded,
    degradedLabel: fallback.degraded ? fallback.degradedLabel : null,
    card,
    undoAction: null,
    rerunAction: null,
  };
}

function dedupeRecentOutcomes(items: readonly RankedLandedOutcome[]): RankedLandedOutcome[] {
  const deduped = new Map<string, RankedLandedOutcome>();

  items.forEach((item) => {
    const key = [
      continuityLocationIdentity(item.resumeLocation),
      item.displayTitle.trim().toLowerCase(),
      item.displaySummary.trim().toLowerCase(),
    ].join("::");
    const existing = deduped.get(key) ?? null;
    if (!existing) {
      deduped.set(key, item);
      return;
    }
    if (item.rank > existing.rank || safeTimestamp(item.occurredAt) > safeTimestamp(existing.occurredAt)) {
      deduped.set(key, item);
    }
  });

  return [...deduped.values()];
}

export function readRankedLandedOutcomes(input: ReadRankedLandedOutcomesInput): RankedLandedOutcome[] {
  const recentActions = input.recentActions ?? readRecentShellActions();
  const resumeAnchors = input.resumeAnchors ?? readResumeAnchors();
  const activeWorkingSetId = input.activeWorkingSetId ?? null;
  const now = input.now ?? Date.now();

  const recent = dedupeRecentOutcomes(
    recentActions
      .map((entry) => buildRecentOutcome(entry, input.availability, activeWorkingSetId, now))
      .filter((item): item is RankedLandedOutcome => item !== null),
  );

  const recentLocationKeys = new Set(recent.map((item) => continuityLocationIdentity(item.resumeLocation)));
  const anchors = [resumeAnchors.planning, resumeAnchors.review]
    .filter((anchor): anchor is ResumeAnchorTarget => anchor != null)
    .map((anchor) => buildAnchorOutcome(anchor, input.availability, activeWorkingSetId, now))
    .filter((item) => !recentLocationKeys.has(continuityLocationIdentity(item.resumeLocation)));

  return [...recent, ...anchors].sort((left, right) => {
    if (right.rank !== left.rank) {
      return right.rank - left.rank;
    }
    return safeTimestamp(right.occurredAt) - safeTimestamp(left.occurredAt);
  });
}
