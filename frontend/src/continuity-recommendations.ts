/**
 * continuity-recommendations.ts - Deterministic primary-next-move synthesis.
 *
 * Purpose:
 *   Turn ranked continuity outcomes into one explicit operator recommendation
 *   with calm supporting evidence and superseded-path state.
 *
 * Responsibilities:
 *   - Derive one primary next move from ranked workflow threads.
 *   - Explain why it won and what changed since the operator last saw it.
 *   - Surface replaced or gone prior-path state using durable anchors.
 *   - Build operator-card-ready recommendation artifacts for shell surfaces.
 *
 * Scope:
 *   - Frontend-only recommendation synthesis on top of continuity ranking.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts and command-palette.ts.
 *
 * Invariants/Assumptions:
 *   - Ranking remains deterministic and feed-driven.
 *   - Durable anchors and last-seen markers remain the evidence substrate.
 *   - This module explains and packages the ranked result; it does not replace ranking.
 */

import type {
  ContinuityLastSeenMarker,
  OperatorActionCard,
  ResumeAnchorState,
  ResumeAnchorTarget,
} from "./contracts-ui";
import type {
  ContinuityAvailability,
  RankedLandedOutcome,
  RankedWorkflowThread,
} from "./continuity-follow-through";
import {
  fallbackFollowThroughLocation,
  groupRankedWorkflowThreads,
} from "./continuity-follow-through";
import { continuityLocationIdentity } from "./continuity-outcomes";

export interface PrimaryRecommendationPriorState {
  kind: "replaced" | "gone";
  title: string;
  summary: string;
}

export interface PrimaryRecommendation {
  workflow: RankedWorkflowThread;
  representative: RankedLandedOutcome;
  card: OperatorActionCard;
  whyNow: string[];
  changedSinceLastSeen: string[];
  priorState: PrimaryRecommendationPriorState | null;
}

function uniqueLines(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)))];
}

function workflowMarker(
  markers: readonly ContinuityLastSeenMarker[],
  workflowThreadId: string | null,
): ContinuityLastSeenMarker | null {
  if (!workflowThreadId) {
    return null;
  }
  return markers.find((marker) => marker.entityKind === "workflow_thread" && marker.entityKey === workflowThreadId) ?? null;
}

function familyForOutcome(outcome: RankedLandedOutcome): "planning" | "review" | null {
  if (outcome.workflowThread?.kind === "planning_checkpoint" || outcome.resumeLocation.state === "plan") {
    return "planning";
  }
  if (
    outcome.workflowThread?.kind === "review_session"
    || (outcome.resumeLocation.state === "decide"
      && (outcome.resumeLocation.reviewFocus === "relationship" || outcome.resumeLocation.reviewFocus === "enrichment"))
  ) {
    return "review";
  }
  return null;
}

function priorAnchorForOutcome(
  outcome: RankedLandedOutcome,
  anchors: ResumeAnchorState,
): ResumeAnchorTarget | null {
  const family = familyForOutcome(outcome);
  return family === "planning"
    ? anchors.planning
    : family === "review"
      ? anchors.review
      : null;
}

function buildWhyNow(
  workflow: RankedWorkflowThread,
  representative: RankedLandedOutcome,
): string[] {
  const lines: string[] = [];

  switch (representative.rankingSignals.driftSeverity) {
    case "replaced":
      lines.push("A newer workflow superseded the prior path you last saved.");
      break;
    case "gone":
      lines.push("The prior landing target disappeared, so this is the safest surviving path.");
      break;
    case "major":
      lines.push("This workflow changed materially since you last saw it.");
      break;
    case "moderate":
      lines.push("This workflow has fresh unseen movement.");
      break;
    case "minor":
      lines.push("This workflow drifted slightly and is still ready to resume.");
      break;
    default:
      lines.push("This is the highest deterministic ready-to-resume workflow.");
      break;
  }

  if (representative.rankingSignals.workingSetRelevant) {
    lines.push("It stays inside the active working set.");
  }
  if (representative.rankingSignals.downstreamReady) {
    lines.push("A downstream surface is ready to open immediately.");
  }
  if (workflow.outcomeCount > 1) {
    lines.push(`${workflow.outcomeCount} related landed outcomes were grouped into one thread.`);
  }

  return lines;
}

function buildChangedSinceLastSeen(
  workflow: RankedWorkflowThread,
  representative: RankedLandedOutcome,
  markers: readonly ContinuityLastSeenMarker[],
): string[] {
  const lines: string[] = [];
  const marker = workflowMarker(markers, representative.workflowThread?.id ?? workflow.id);

  if (!marker) {
    lines.push("This workflow has never been seen from durable continuity.");
  }

  const previousOutcomeId = Number(
    (marker?.observedState as { latestOutcomeId?: number } | undefined)?.latestOutcomeId ?? 0,
  );

  if (representative.persistedOutcomeId != null && representative.persistedOutcomeId > previousOutcomeId) {
    const delta = representative.persistedOutcomeId - previousOutcomeId;
    lines.push(`${delta} newer landed outcome${delta === 1 ? "" : "s"} appeared since you last saw it.`);
  }

  if (workflow.outcomeCount > 1) {
    lines.push(`${workflow.outcomeCount} outcomes are grouped under this workflow thread.`);
  }

  if (representative.degradedLabel) {
    lines.push(representative.degradedLabel);
  }

  if (!lines.length) {
    lines.push("No opaque heuristic changed this ranking; it still wins on deterministic readiness.");
  }

  return lines;
}

function buildPriorState(
  representative: RankedLandedOutcome,
  anchors: ResumeAnchorState,
  availability: ContinuityAvailability,
): PrimaryRecommendationPriorState | null {
  const anchor = priorAnchorForOutcome(representative, anchors);
  if (!anchor) {
    return null;
  }

  const anchorIdentity = continuityLocationIdentity(anchor.resumeLocation ?? anchor.launchLocation);
  const currentIdentity = continuityLocationIdentity(representative.resumeLocation);
  const sameThread = anchor.workflowThreadId != null
    && representative.workflowThread?.id != null
    && anchor.workflowThreadId === representative.workflowThread.id;
  if (sameThread || anchorIdentity === currentIdentity) {
    return null;
  }

  const fallback = fallbackFollowThroughLocation(anchor.resumeLocation ?? anchor.launchLocation, availability);
  if (fallback.degraded) {
    return {
      kind: "gone",
      title: anchor.outcomeTitle ?? "Prior path",
      summary: fallback.degradedLabel ?? "The prior primary path is no longer available.",
    };
  }

  return {
    kind: "replaced",
    title: anchor.outcomeTitle ?? "Prior path",
    summary: `${anchor.outcomeTitle ?? "The prior path"} was superseded by ${representative.displayTitle}.`,
  };
}

export function derivePrimaryRecommendation(input: {
  outcomes: readonly RankedLandedOutcome[];
  availability: ContinuityAvailability;
  resumeAnchors: ResumeAnchorState;
  lastSeenMarkers: readonly ContinuityLastSeenMarker[];
}): PrimaryRecommendation | null {
  const workflows = groupRankedWorkflowThreads(input.outcomes);
  const workflow = workflows.find((item) => !item.representative.degraded) ?? workflows[0] ?? null;
  if (!workflow) {
    return null;
  }

  const representative = workflow.representative;
  const whyNow = buildWhyNow(workflow, representative);
  const changedSinceLastSeen = buildChangedSinceLastSeen(workflow, representative, input.lastSeenMarkers);
  const priorState = buildPriorState(representative, input.resumeAnchors, input.availability);
  const impactSummary = uniqueLines([
    ...whyNow.slice(1),
    ...changedSinceLastSeen,
    priorState?.summary,
  ]).join(" · ");

  const card: OperatorActionCard = {
    ...representative.card,
    id: `primary-next-move-${representative.id}`,
    emphasis: "primary",
    eyebrow: "Primary next move",
    summary: representative.card.summary,
    rationale:
      "This is the deterministic top recommendation. It combines visible drift, working-set relevance, downstream readiness, and durable continuity evidence to show one obvious next move.",
    preview: [
      { label: "Workflow", value: workflow.thread.title },
      { label: "Why now", value: whyNow[0] ?? "Highest deterministic rank" },
      { label: "Changed", value: changedSinceLastSeen[0] ?? "No unseen drift" },
      ...(priorState
        ? [{
            label: priorState.kind === "gone" ? "Prior path gone" : "Prior path replaced",
            value: priorState.summary,
          }]
        : []),
    ],
    trust: {
      ...representative.card.trust,
      confidenceLabel: "Deterministic next move",
      impactSummary: impactSummary || representative.card.trust.impactSummary || representative.displaySummary,
    },
    handoff: representative.card.handoff
      ? {
          ...representative.card.handoff,
          changeSummary: changedSinceLastSeen.join(" · "),
          createdResources: uniqueLines([
            ...representative.card.handoff.createdResources,
            priorState?.summary,
          ]).slice(0, 4),
        }
      : {
          changeSummary: changedSinceLastSeen.join(" · "),
          createdResources: uniqueLines([priorState?.summary]).slice(0, 4),
          nextStep: "Open the prepared workflow and continue from the landed state.",
          breadcrumbs: ["Home", "Now", workflow.thread.title],
        },
    actionContextLabel: "Do this next",
    actionWarning: priorState?.kind === "gone" ? priorState.summary : (representative.card.actionWarning ?? null),
  };

  return {
    workflow,
    representative,
    card,
    whyNow,
    changedSinceLastSeen,
    priorState,
  };
}

export function buildPrimaryRecommendationDigestCard(
  recommendation: PrimaryRecommendation,
): OperatorActionCard {
  return {
    id: `primary-next-move-digest-${recommendation.representative.id}`,
    kind: "context",
    tone: recommendation.priorState?.kind === "gone" ? "attention" : "neutral",
    eyebrow: "Why this won",
    title: "Why this workflow became the top recommendation",
    summary: recommendation.whyNow.join(" · "),
    rationale:
      "The operator should not need to infer the ranking from parallel cards. This digest calmly explains why the workflow moved to the top and what changed since it was last seen.",
    preview: [
      ...recommendation.whyNow.slice(0, 2).map((value, index) => ({
        label: `Why ${index + 1}`,
        value,
      })),
      ...recommendation.changedSinceLastSeen.slice(0, 2).map((value, index) => ({
        label: `Changed ${index + 1}`,
        value,
      })),
      ...(recommendation.priorState
        ? [{
            label: recommendation.priorState.kind === "gone" ? "Prior path gone" : "Prior path replaced",
            value: recommendation.priorState.summary,
          }]
        : []),
    ],
    trust: {
      contextSources: [
        "Ranked landed outcomes",
        "Durable resume anchors",
        "Durable workflow-thread last-seen markers",
      ],
      assumptions: ["Recommendation ranking remains deterministic and feed-driven."],
      confidenceLabel: "Visible evidence only",
      freshnessLabel: recommendation.representative.card.trust.freshnessLabel ?? null,
      rollbackLabel: "This digest does not mutate state; it explains the next move.",
      impactSummary: recommendation.changedSinceLastSeen.join(" · "),
    },
    handoff: recommendation.card.handoff,
    actionContextLabel: "Open the same next move",
    actions: recommendation.card.actions.slice(0, 2),
  };
}
