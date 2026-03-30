/**
 * continuity-recommendations.test.ts - Primary continuity recommendation ranking regression coverage.
 *
 * Purpose:
 *   Verify the backend-authored continuity recommendation selector keeps warning
 *   notifications ahead of info notifications when ranks are otherwise tied.
 *
 * Responsibilities:
 *   - Exercise the narrow tie-break behavior for the primary recommendation picker.
 *   - Guard against future regressions that accidentally reintroduce array-order bias.
 *
 * Scope:
 *   - Frontend unit coverage for continuity-recommendations.ts only.
 *
 * Usage:
 *   - Run with the frontend Vitest suite.
 *
 * Invariants/Assumptions:
 *   - The helper only needs minimal summary and notification shapes for this regression.
 */

import { describe, expect, it } from "vitest";

import type { ContinuityNotificationRecord, OperatorActionCard } from "./contracts-ui";
import type { RankedWorkflowSummary } from "./continuity-follow-through";
import { derivePrimaryRecommendation } from "./continuity-recommendations";

function makeSummary(id: string, rank: number): RankedWorkflowSummary {
  return {
    id,
    rank,
    card: { id: `card-${id}` } as OperatorActionCard,
  } as RankedWorkflowSummary;
}

function makeNotification(
  id: string,
  severity: ContinuityNotificationRecord["severity"],
): ContinuityNotificationRecord {
  return {
    id,
    severity,
  } as ContinuityNotificationRecord;
}

describe("derivePrimaryRecommendation", () => {
  it("prefers warning notifications over info notifications when ranks are tied", () => {
    const summaries = [
      makeSummary("info-candidate", 20),
      makeSummary("warning-candidate", 20),
    ];
    const notifications = [
      makeNotification("info-candidate", "info"),
      makeNotification("warning-candidate", "warning"),
    ];

    const recommendation = derivePrimaryRecommendation(summaries, notifications);

    expect(recommendation).not.toBeNull();
    expect(recommendation?.summary.id).toBe("warning-candidate");
    expect(recommendation?.notification.id).toBe("warning-candidate");
    expect(recommendation?.notification.severity).toBe("warning");
  });
});
