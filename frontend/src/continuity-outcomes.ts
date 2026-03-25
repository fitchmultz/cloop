/**
 * continuity-outcomes.ts - Shared outcome-first continuity resolution helpers.
 *
 * Purpose:
 *   Centralize how browser-local continuity history prefers landed outcomes,
 *   fallback launch locations, and propagated working-set context.
 *
 * Responsibilities:
 *   - Resolve recent shell actions into outcome-first display and resume models.
 *   - Provide stable landed-location identity and deduplication keys.
 *   - Classify low-signal navigation entries that should stay secondary.
 *
 * Scope:
 *   - Frontend-only continuity precedence and identity helpers.
 *
 * Usage:
 *   - Imported by continuity persistence, operator summaries, and palette recents.
 *
 * Invariants/Assumptions:
 *   - `outcome.resumeLocation` is the canonical landed resume target when present.
 *   - `outcome.card` is the canonical local display payload hydrated from landed outcomes when present.
 *   - Launch locations remain useful only as degraded fallback context.
 */

import type {
  OperatorActionCard,
  OperatorActionHandoff,
  RecentShellActionEntry,
  ShellLocationContract,
  WorkingSetSessionMetadata,
} from "./contracts-ui";

export interface ResolvedContinuityEntry {
  entry: RecentShellActionEntry;
  hasOutcome: boolean;
  card: OperatorActionCard | null;
  displayTitle: string;
  displaySummary: string;
  resumeLocation: ShellLocationContract | null;
  launchLocation: ShellLocationContract | null;
  handoff: OperatorActionHandoff | null;
  workingSet: WorkingSetSessionMetadata | null;
  workingSetId: number | null;
  degradedReason: "none" | "no_outcome" | "missing_resume_location";
}

export function continuityLocationIdentity(location: ShellLocationContract | null | undefined): string {
  if (!location) {
    return "location:null";
  }
  return [
    location.state,
    location.recallTool,
    location.reviewFocus ?? "-",
    location.sessionId ?? "-",
    location.loopId ?? "-",
    location.viewId ?? "-",
    location.memoryId ?? "-",
    location.workingSetId ?? "-",
    location.query ?? "-",
  ].join("|");
}

export function resolveContinuityResumeLocation(entry: RecentShellActionEntry): ShellLocationContract | null {
  return entry.outcome?.resumeLocation ?? entry.location ?? null;
}

export function resolveContinuityWorkingSetId(entry: RecentShellActionEntry): number | null {
  return entry.outcome?.card.handoff?.workingSet?.workingSetId
    ?? entry.outcome?.resumeLocation?.workingSetId
    ?? entry.location?.workingSetId
    ?? null;
}

export function resolveContinuityEntry(entry: RecentShellActionEntry): ResolvedContinuityEntry {
  const card = entry.outcome?.card ?? null;
  const resumeLocation = resolveContinuityResumeLocation(entry);
  const handoff = card?.handoff ?? null;
  const workingSet = handoff?.workingSet ?? null;
  const hasOutcome = Boolean(entry.outcome);

  return {
    entry,
    hasOutcome,
    card,
    displayTitle: card?.title ?? entry.label,
    displaySummary: card?.summary ?? entry.description,
    resumeLocation,
    launchLocation: entry.location ?? null,
    handoff,
    workingSet,
    workingSetId: resolveContinuityWorkingSetId(entry),
    degradedReason: entry.outcome
      ? (entry.outcome.resumeLocation ? "none" : "missing_resume_location")
      : "no_outcome",
  };
}

export function recentShellActionDedupKey(entry: RecentShellActionEntry): string {
  const resolved = resolveContinuityEntry(entry);
  return [
    entry.kind,
    continuityLocationIdentity(resolved.resumeLocation),
    resolved.displayTitle.trim().toLowerCase(),
    resolved.displaySummary.trim().toLowerCase(),
  ].join("::");
}

export function isLowSignalNavigationEntry(
  entry: RecentShellActionEntry | Omit<RecentShellActionEntry, "occurredAt">,
): boolean {
  if (entry.outcome) {
    return false;
  }
  return entry.kind === "navigation"
    || entry.kind === "planning"
    || entry.kind === "review"
    || entry.kind === "recall"
    || entry.kind === "working_set_session";
}
