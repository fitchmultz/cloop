/**
 * continuity-recommendations.ts - Backend-authored primary continuity recommendation helpers.
 *
 * Purpose:
 *   Turn the canonical backend continuity summary feed into one explicit primary
 *   operator recommendation and one supporting digest card.
 *
 * Responsibilities:
 *   - Select the top backend-authored workflow summary.
 *   - Package the backend explanation lines for shell and command-palette consumers.
 *   - Build a calm digest card without re-ranking or rewriting the summary logic.
 *
 * Scope:
 *   - Frontend packaging of backend-authored continuity summaries only.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts and command-palette.ts.
 *
 * Invariants/Assumptions:
 *   - Backend workflow summaries are already ranked.
 *   - Backend `whyNow`, `changedSinceLastSeen`, and `priorState` fields are canonical.
 */

import type {
  ContinuityRecoveryPlan,
  OperatorActionCard,
} from "./contracts-ui";
import type { RankedWorkflowSummary } from "./continuity-follow-through";

export interface ContinuityNotificationDigest {
  title: string;
  body: string;
  severity: "info" | "warning" | "alert";
  tab: "operator";
}

export interface PrimaryRecommendation {
  summary: RankedWorkflowSummary;
  card: OperatorActionCard;
  whyNow: string[];
  changedSinceLastSeen: string[];
  priorState: RankedWorkflowSummary["priorState"];
  recovery: ContinuityRecoveryPlan | null;
}

function uniqueLines(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)))];
}

function notificationSeverity(recommendation: PrimaryRecommendation): "info" | "warning" | "alert" {
  const severity = recommendation.summary.rankingSignals.driftSeverity;
  if (severity === "gone") {
    return "alert";
  }
  if (recommendation.summary.degraded || severity === "replaced" || severity === "major") {
    return "warning";
  }
  return "info";
}

export function buildPrimaryRecommendationNotification(
  recommendation: PrimaryRecommendation,
): ContinuityNotificationDigest {
  const severity = notificationSeverity(recommendation);
  const summary = recommendation.summary;
  const title = summary.rankingSignals.driftSeverity === "gone"
    ? `${summary.displayTitle} needs a recovery decision`
    : summary.rankingSignals.driftSeverity === "replaced"
      ? `${summary.displayTitle} has a newer path`
      : summary.rankingSignals.workingSetRelevant
        ? `${summary.displayTitle} is ready in your working set`
        : summary.rankingSignals.downstreamReady
          ? `${summary.displayTitle} is ready to resume`
          : summary.displayTitle;
  const body = uniqueLines([
    ...recommendation.whyNow.slice(0, 2),
    ...recommendation.changedSinceLastSeen.slice(0, 2),
    recommendation.priorState?.summary,
    summary.displaySummary,
  ]).slice(0, 2).join(" · ") || summary.displaySummary;

  return {
    title,
    body,
    severity,
    tab: "operator",
  };
}

export function derivePrimaryRecommendation(
  summaries: readonly RankedWorkflowSummary[],
): PrimaryRecommendation | null {
  const summary = summaries[0] ?? null;
  if (!summary) {
    return null;
  }

  const impactSummary = uniqueLines([
    ...summary.whyNow.slice(1),
    ...summary.changedSinceLastSeen,
    summary.priorState?.summary,
  ]).join(" · ");

  const card: OperatorActionCard = {
    ...summary.card,
    id: `primary-next-move-${summary.id}`,
    emphasis: "primary",
    eyebrow: "Primary next move",
    rationale:
      "This card renders the top backend-authored continuity summary instead of re-ranking candidate workflows in the browser.",
    preview: [
      { label: "Workflow", value: summary.workflowThread.title },
      { label: "Why now", value: summary.whyNow[0] ?? "Highest deterministic rank" },
      { label: "Changed", value: summary.changedSinceLastSeen[0] ?? "No unseen drift" },
      ...(summary.priorState
        ? [{
            label: summary.priorState.kind === "gone" ? "Prior path gone" : "Prior path replaced",
            value: summary.priorState.summary,
          }]
        : []),
    ],
    trust: {
      ...summary.card.trust,
      confidenceLabel: "Deterministic next move",
      impactSummary: impactSummary || summary.card.trust.impactSummary || summary.displaySummary,
    },
    handoff: summary.card.handoff
      ? {
          ...summary.card.handoff,
          changeSummary: summary.changedSinceLastSeen.join(" · "),
          createdResources: uniqueLines([
            ...summary.card.handoff.createdResources,
            summary.priorState?.summary,
          ]).slice(0, 4),
        }
      : {
          changeSummary: summary.changedSinceLastSeen.join(" · "),
          createdResources: uniqueLines([summary.priorState?.summary]).slice(0, 4),
          nextStep: "Open the prepared workflow and continue from the landed state.",
          breadcrumbs: ["Home", "Now", summary.workflowThread.title],
        },
    actionContextLabel: "Do this next",
    actionWarning: summary.priorState?.kind === "gone" ? summary.priorState.summary : (summary.card.actionWarning ?? null),
    recovery: summary.recovery,
  };

  return {
    summary,
    card,
    whyNow: summary.whyNow,
    changedSinceLastSeen: summary.changedSinceLastSeen,
    priorState: summary.priorState,
    recovery: summary.recovery,
  };
}

export function buildPrimaryRecommendationDigestCard(
  recommendation: PrimaryRecommendation,
): OperatorActionCard {
  const notification = buildPrimaryRecommendationNotification(recommendation);
  return {
    id: `primary-next-move-digest-${recommendation.summary.id}`,
    kind: "context",
    tone: notification.severity === "alert" ? "attention" : "neutral",
    eyebrow: "Why this won",
    title: "Why this workflow became the top recommendation",
    summary: notification.body,
    rationale:
      "The operator should not need to infer the ranking from parallel cards. This digest reuses the backend-authored continuity explanation directly.",
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
      generationLabel: "Backend continuity summary",
      generationTone: "neutral",
      contextSources: ["Durable workflow-summary feed"],
      assumptions: [],
      confidenceLabel: "Deterministic recommendation explanation",
      confidenceTone: "progress",
      freshnessLabel: recommendation.summary.card.trust.freshnessLabel,
      freshnessTone: recommendation.summary.card.trust.freshnessTone ?? null,
      rollbackLabel: null,
      rollbackTone: "neutral",
      impactSummary: recommendation.changedSinceLastSeen.join(" · "),
      impactTone: "neutral",
    },
    handoff: {
      changeSummary: recommendation.changedSinceLastSeen.join(" · "),
      createdResources: uniqueLines([
        recommendation.summary.workflowThread.title,
        recommendation.priorState?.summary,
      ]).slice(0, 3),
      nextStep: "Open the ranked workflow and continue from the canonical landed state.",
      breadcrumbs: ["Home", "Since last visit", "Why this won"],
      workingSet: recommendation.summary.card.handoff?.workingSet ?? null,
    },
    actionContextLabel: null,
    actionWarning: null,
    recovery: recommendation.recovery,
    actions: [],
  };
}
