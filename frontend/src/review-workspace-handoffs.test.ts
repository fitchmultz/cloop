/**
 * review-workspace-handoffs.test.ts - Regression tests for review-workspace handoff helpers.
 *
 * Purpose:
 *   Verify planning-impact handoff helpers preserve propagated working-set
 *   metadata, breadcrumbs, and next-step cues before review-workspace rendering.
 *
 * Responsibilities:
 *   - Assert launch-surface handoffs keep named working-set metadata.
 *   - Assert follow-up-resource handoffs reuse launch-surface context.
 *   - Guard breadcrumb shaping for downstream review queues.
 *
 * Scope:
 *   - Pure helper coverage for review-workspace handoff shaping.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests operate on typed payload fragments only.
 *   - Working-set lookup remains deterministic for the same input arrays.
 */

import type {
  PlanningExecutionFollowUpResourceResponse,
  PlanningExecutionLaunchSurfaceResponse,
  WorkingSetResponse,
} from "./domain";
import {
  buildFollowUpResourceHandoff,
  buildLaunchSurfaceHandoff,
  resolveWorkingSetSessionMetadata,
} from "./review-workspace-handoffs";

const workingSets: WorkingSetResponse[] = [
  {
    id: 2,
    name: "Review Prep",
    description: "Cross-surface review prep",
    item_count: 3,
    missing_item_count: 1,
    last_activated_at_utc: "2026-03-18T18:10:00Z",
    created_at_utc: "2026-03-18T18:00:00Z",
    updated_at_utc: "2026-03-18T18:10:00Z",
    items: [],
  } as unknown as WorkingSetResponse,
];

function launchSurface(overrides: Partial<PlanningExecutionLaunchSurfaceResponse> = {}): PlanningExecutionLaunchSurfaceResponse {
  return {
    label: overrides.label ?? "Enrichment review queue",
    reason: overrides.reason ?? "Continue with the created enrichment queue.",
    resource_id: overrides.resource_id ?? 27,
    resource_type: overrides.resource_type ?? "review_session",
    surface: overrides.surface ?? "review_session",
    web: overrides.web ?? {
      surface: "review_session",
      review_kind: "enrichment",
      session_id: 27,
      working_set_id: 2,
    },
  } as PlanningExecutionLaunchSurfaceResponse;
}

describe("review-workspace-handoffs", () => {
  it("resolves named working-set metadata", () => {
    expect(resolveWorkingSetSessionMetadata(workingSets, 2)).toEqual({
      workingSetId: 2,
      workingSetName: "Review Prep",
      itemCount: 3,
      missingItemCount: 1,
    });
  });

  it("builds launch-surface handoffs with working-set metadata and breadcrumbs", () => {
    const handoff = buildLaunchSurfaceHandoff(launchSurface(), {
      breadcrumbPrefix: ["Home", "Plan", "Weekly reset"],
      fallbackWorkingSetId: null,
      workingSets,
    });

    expect(handoff.workingSet?.workingSetName).toBe("Review Prep");
    expect(handoff.breadcrumbs).toEqual(["Home", "Plan", "Weekly reset", "Enrichment review queue"]);
    expect(handoff.nextStep).toContain("Enrichment review queue");
  });

  it("reuses launch-surface context for follow-up-resource handoffs", () => {
    const resource: PlanningExecutionFollowUpResourceResponse = {
      label: "Enrichment review queue",
      launch_surface: launchSurface(),
      operation_index: 0,
      operation_kind: "create_enrichment_review_session",
      operation_summary: "Created enrichment review queue",
      resource_id: 27,
      resource_type: "review_session",
      role: "Next workflow",
    } as PlanningExecutionFollowUpResourceResponse;

    const handoff = buildFollowUpResourceHandoff(resource, {
      breadcrumbPrefix: ["Home", "Plan", "Weekly reset"],
      fallbackWorkingSetId: null,
      workingSets,
    });

    expect(handoff).not.toBeNull();
    expect(handoff?.changeSummary).toBe("Created enrichment review queue");
    expect(handoff?.workingSet?.workingSetName).toBe("Review Prep");
    expect(handoff?.breadcrumbs.at(-1)).toBe("Enrichment review queue");
  });
});
