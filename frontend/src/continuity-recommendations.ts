/**
 * continuity-recommendations.ts - Backend-authored primary continuity recommendation helpers.
 *
 * Purpose:
 *   Turn the canonical backend continuity summary feed into one explicit primary
 *   operator recommendation and one supporting digest card.
 *
 * Responsibilities:
 *   - Select the top backend-authored notification-backed workflow summary.
 *   - Package the backend explanation lines for shell and command-palette consumers.
 *   - Build a calm digest card without re-ranking or rewriting the notification logic.
 *
 * Scope:
 *   - Frontend packaging of backend-authored continuity summaries only.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts and command-palette.ts.
 *
 * Invariants/Assumptions:
 *   - Backend workflow summaries are already ranked.
 *   - Backend notification records are the canonical title/body/severity source.
 *   - Backend `whyNow`, `changedSinceLastSeen`, and `priorState` fields are canonical.
 */

import type {
  ContinuityNotificationRecord,
  ContinuityRecoveryPlan,
  OperatorActionCard,
} from "./contracts-ui";
import { readActiveContinuityNotificationRecords } from "./continuity-intelligence";
import type { RankedWorkflowSummary } from "./continuity-follow-through";

export type ContinuityNotificationDigest = ContinuityNotificationRecord;

export interface PrimaryRecommendation {
  summary: RankedWorkflowSummary;
  notification: ContinuityNotificationRecord;
  card: OperatorActionCard;
  whyNow: string[];
  changedSinceLastSeen: string[];
  priorState: RankedWorkflowSummary["priorState"];
  recovery: ContinuityRecoveryPlan | null;
}

function uniqueLines(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)))];
}

export function buildPrimaryRecommendationNotification(
  recommendation: PrimaryRecommendation,
): ContinuityNotificationDigest {
  return recommendation.notification;
}

export function derivePrimaryRecommendation(
  summaries: readonly RankedWorkflowSummary[],
  notifications: readonly ContinuityNotificationRecord[] = readActiveContinuityNotificationRecords(),
): PrimaryRecommendation | null {
  const notification = notifications[0] ?? null;
  if (!notification) {
    return null;
  }

  const summary = summaries.find((item) => item.id === notification.id) ?? null;
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
    notification,
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
      contextSources: ["Durable continuity notification record"],
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
