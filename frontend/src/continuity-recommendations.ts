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
 *   - When summary ranks are tied, warning-severity notifications outrank info-severity notifications.
 *   - Backend notification records are the canonical title/body/severity source.
 *   - Backend `whyNow`, `changedSinceLastSeen`, and `priorState` fields are canonical.
 *   - Display semantics on `summary.card` come from the backend display payload; this
 *     module only applies surface chrome via `continuitySurfaceCard`.
 */

import type {
  ContinuityNotificationRecord,
  ContinuityRecoveryPlan,
  OperatorActionCard,
} from "./contracts-ui";
import {
  continuitySurfaceCard,
  type RankedWorkflowSummary,
} from "./continuity-follow-through";
import { readActiveContinuityNotificationRecords } from "./continuity-intelligence";

export interface PrimaryRecommendation {
  summary: RankedWorkflowSummary;
  notification: ContinuityNotificationRecord;
  card: OperatorActionCard;
  whyNow: string[];
  changedSinceLastSeen: string[];
  priorState: RankedWorkflowSummary["priorState"];
  recovery: ContinuityRecoveryPlan | null;
}

export function notificationToneForSeverity(
  severity: ContinuityNotificationRecord["severity"],
): OperatorActionCard["tone"] {
  if (severity === "alert") {
    return "attention";
  }
  if (severity === "warning") {
    return "caution";
  }
  return "neutral";
}

const notificationSeverityRank: Record<ContinuityNotificationRecord["severity"], number> = {
  info: 0,
  warning: 1,
  alert: 2,
};

type PrimaryRecommendationCandidate = {
  summary: RankedWorkflowSummary;
  notification: ContinuityNotificationRecord;
  index: number;
};

function comparePrimaryRecommendationCandidates(
  left: PrimaryRecommendationCandidate,
  right: PrimaryRecommendationCandidate,
): number {
  if (left.summary.rank !== right.summary.rank) {
    return right.summary.rank - left.summary.rank;
  }

  const severityDelta = (
    notificationSeverityRank[right.notification.severity]
    - notificationSeverityRank[left.notification.severity]
  );
  if (severityDelta !== 0) {
    return severityDelta;
  }

  return left.index - right.index;
}

export function derivePrimaryRecommendation(
  summaries: readonly RankedWorkflowSummary[],
  notifications: readonly ContinuityNotificationRecord[] = readActiveContinuityNotificationRecords(),
): PrimaryRecommendation | null {
  const notificationById = new Map(notifications.map((notification) => [notification.id, notification]));
  const candidates: PrimaryRecommendationCandidate[] = [];

  summaries.forEach((summary, index) => {
    const notification = notificationById.get(summary.id);
    if (!notification) {
      return;
    }
    candidates.push({ summary, notification, index });
  });

  candidates.sort(comparePrimaryRecommendationCandidates);
  const candidate = candidates[0] ?? null;
  if (!candidate) {
    return null;
  }

  const { summary, notification } = candidate;
  const card = continuitySurfaceCard(summary, {
    id: `primary-next-move-${summary.id}`,
    emphasis: "primary",
    eyebrow: "Primary next move",
    rationale:
      "This card renders the top backend-authored continuity summary instead of re-ranking candidate workflows in the browser.",
  });

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
  const { notification, summary: s } = recommendation;
  const tone = notificationToneForSeverity(notification.severity);

  return continuitySurfaceCard(s, {
    id: `primary-next-move-digest-${s.id}`,
    kind: "context",
    tone,
    eyebrow: "Why this won",
    title: "Why this workflow became the top recommendation",
    summary: notification.body,
    rationale:
      "The operator should not need to infer the ranking from parallel cards. This digest reuses the backend-authored continuity explanation directly.",
    actions: [],
    recovery: recommendation.recovery,
  });
}
