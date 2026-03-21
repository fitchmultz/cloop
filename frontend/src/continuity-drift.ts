/**
 * continuity-drift.ts - Deterministic drift assessment and continuity ranking signals.
 *
 * Purpose:
 *   Convert durable last-seen markers plus live continuity state into stable drift
 *   severity and ranking signals shared by since-last cards and resume ranking.
 *
 * Responsibilities:
 *   - Compare live planning/review/cohort/thread state to durable last-seen markers.
 *   - Produce deterministic drift severity, summaries, and preview evidence.
 *   - Score resume candidates using drift, working-set relevance, readiness, and recency.
 *
 * Scope:
 *   - Frontend-only deterministic continuity intelligence helpers.
 *
 * Usage:
 *   - Imported by continuity-follow-through.ts and shell-operator-cards.ts.
 *
 * Invariants/Assumptions:
 *   - Durable last-seen markers are the comparison baseline.
 *   - Fingerprint mismatch alone does not imply severe drift; structure matters too.
 */

import type {
  ContinuityDriftSeverity,
  ContinuityLastSeenMarker,
  ContinuityRankingSignals,
  OperatorActionPreviewItem,
} from "./contracts-ui";

const DRIFT_SCORE: Record<ContinuityDriftSeverity, number> = {
  none: 0,
  minor: 24,
  moderate: 52,
  major: 78,
  replaced: 92,
  gone: 100,
};

function diffIds(previous: readonly number[], current: readonly number[]) {
  const previousSet = new Set(previous);
  const currentSet = new Set(current);
  return {
    added: current.filter((id) => !previousSet.has(id)),
    removed: previous.filter((id) => !currentSet.has(id)),
  };
}

export function scoreRankingSignals(input: {
  severity: ContinuityDriftSeverity;
  workingSetRelevant: boolean;
  downstreamReady: boolean;
  degraded: boolean;
  ageMinutes: number;
}): ContinuityRankingSignals {
  const recencyTieBreaker = Math.max(0, 18 - Math.floor(input.ageMinutes / 90));
  return {
    driftSeverity: input.severity,
    driftScore: DRIFT_SCORE[input.severity],
    workingSetRelevant: input.workingSetRelevant,
    downstreamReady: input.downstreamReady && !input.degraded,
    degraded: input.degraded,
    recencyTieBreaker,
  };
}

export function totalRankingScore(signals: ContinuityRankingSignals, source: "receipt" | "recent" | "anchor"): number {
  const sourceScore = source === "receipt" ? 18 : source === "recent" ? 10 : 4;
  return (
    signals.driftScore * 100
    + (signals.workingSetRelevant ? 240 : 0)
    + (signals.downstreamReady ? 180 : -220)
    - (signals.degraded ? 120 : 0)
    + sourceScore
    + signals.recencyTieBreaker
  );
}

export function summarizeCohortDrift(
  label: string,
  marker: ContinuityLastSeenMarker | null,
  currentCount: number,
  currentIds: readonly number[],
): { severity: ContinuityDriftSeverity; summary: string; preview: OperatorActionPreviewItem[] } {
  if (!marker) {
    return {
      severity: currentCount > 0 ? "moderate" : "none",
      summary: currentCount > 0 ? `${label} is populated and has never been seen.` : `${label} is unchanged.`,
      preview: [{ label: "Current", value: `${currentCount}` }],
    };
  }

  const previousState = marker.observedState as { count?: number; itemIds?: number[] };
  const previousCount = previousState.count ?? 0;
  const changes = diffIds(previousState.itemIds ?? [], currentIds);
  const delta = currentCount - previousCount;

  let severity: ContinuityDriftSeverity = "none";
  if (currentCount === 0 && previousCount > 0) {
    severity = "minor";
  } else if (Math.abs(delta) >= 5 || changes.added.length >= 5 || changes.removed.length >= 5) {
    severity = "major";
  } else if (Math.abs(delta) >= 2 || changes.added.length > 0 || changes.removed.length > 0) {
    severity = "moderate";
  } else if (delta !== 0) {
    severity = "minor";
  }

  return {
    severity,
    summary: `${label}: ${previousCount} → ${currentCount}`,
    preview: [
      { label: "Count", value: `${previousCount} → ${currentCount}` },
      ...changes.added.slice(0, 2).map((id, index) => ({
        label: `New ${index + 1}`,
        value: `Loop #${id}`,
      })),
    ],
  };
}
