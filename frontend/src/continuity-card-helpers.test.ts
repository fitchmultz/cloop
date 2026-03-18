/**
 * continuity-card-helpers.test.ts - Regression tests for operator continuity-card helpers.
 *
 * Purpose:
 *   Guard the operator shell's continuity-card preview shaping so high-signal
 *   deltas stay concise and repeated-snooze handoffs remain deterministic.
 *
 * Responsibilities:
 *   - Verify unchanged cohort rows are omitted from risk-growth previews.
 *   - Verify state-derived snooze previews use deterministic newest-first order.
 *   - Verify snooze-action history keeps the correct trust-surface context.
 *
 * Scope:
 *   - Pure helper coverage for frontend continuity-card shaping.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - These tests exercise pure helper functions without DOM dependencies.
 *   - Loop timestamps sort newest-first, with malformed timestamps sorting last.
 */

import {
  buildChangedCountPreviewItems,
  buildGroupedChangePreviewItems,
  buildPlanningResourcePreviewItems,
  buildRepeatedSnoozeSignal,
  mergePlanningResourceChangeGroups,
  sortLoopsByMostRecentUpdate,
} from "./continuity-card-helpers";
import type { RecentShellActionEntry } from "./contracts-ui";
import type { LoopResponse, PlanningResourceChangeGroupResponse } from "./domain";

function loop(overrides: Partial<LoopResponse>): LoopResponse {
  return {
    raw_text: overrides.raw_text ?? `Loop ${overrides.id ?? 1}`,
    summary: overrides.summary ?? null,
    definition_of_done: overrides.definition_of_done ?? null,
    next_action: overrides.next_action ?? null,
    captured_at_utc: overrides.captured_at_utc ?? "2026-03-17T22:00:00Z",
    captured_tz_offset_min: overrides.captured_tz_offset_min ?? 0,
    due_date: overrides.due_date ?? null,
    due_at_utc: overrides.due_at_utc ?? null,
    snooze_until_utc: overrides.snooze_until_utc ?? null,
    time_minutes: overrides.time_minutes ?? null,
    activation_energy: overrides.activation_energy ?? null,
    urgency: overrides.urgency ?? null,
    importance: overrides.importance ?? null,
    blocked_reason: overrides.blocked_reason ?? null,
    completion_note: overrides.completion_note ?? null,
    project: overrides.project ?? null,
    tags: overrides.tags ?? [],
    user_locks: overrides.user_locks ?? [],
    provenance: overrides.provenance ?? {},
    enrichment_state: overrides.enrichment_state ?? "pending",
    recurrence_rrule: overrides.recurrence_rrule ?? null,
    recurrence_tz: overrides.recurrence_tz ?? null,
    next_due_at_utc: overrides.next_due_at_utc ?? null,
    recurrence_enabled: overrides.recurrence_enabled ?? false,
    parent_loop_id: overrides.parent_loop_id ?? null,
    created_at_utc: overrides.created_at_utc ?? "2026-03-17T22:00:00Z",
    updated_at_utc: overrides.updated_at_utc ?? "2026-03-17T22:00:00Z",
    closed_at_utc: overrides.closed_at_utc ?? null,
    id: overrides.id ?? 1,
    title: overrides.title ?? null,
    status: overrides.status ?? "actionable",
    project_id: overrides.project_id ?? null,
  } satisfies LoopResponse;
}

function snoozeAction(overrides: Partial<RecentShellActionEntry> = {}): RecentShellActionEntry {
  return {
    kind: overrides.kind ?? "snooze",
    label: overrides.label ?? "Snoozed loop #7",
    description: overrides.description ?? "Deferred a loop from Do.",
    location: overrides.location ?? {
      state: "do",
      recallTool: "chat",
      reviewFocus: null,
      sessionId: null,
      loopId: 7,
      viewId: null,
      memoryId: null,
      query: null,
    },
    metadata: overrides.metadata ?? null,
    occurredAt: overrides.occurredAt ?? "2026-03-17T22:15:00Z",
  };
}

function loopTitle(loopValue: Pick<LoopResponse, "id" | "title" | "raw_text">): string {
  return loopValue.title?.trim() || loopValue.raw_text.trim() || `Loop #${loopValue.id}`;
}

describe("continuity-card-helpers", () => {
  it("omits unchanged rows from risk-growth previews", () => {
    expect(buildChangedCountPreviewItems([
      { label: "Blocked too long", previous: 0, current: 0 },
      { label: "Missing next action", previous: 3, current: 4 },
      { label: "Stale open", previous: 0, current: 0 },
    ])).toEqual([
      { label: "Missing next action", value: "3 → 4" },
    ]);
  });

  it("sorts state-derived snoozed loops newest-first and cites state-based context", () => {
    const loops = [
      loop({ id: 4, title: "Older deferred loop", updated_at_utc: "2026-03-17T22:15:53Z" }),
      loop({ id: 7, title: "Newest deferred loop", updated_at_utc: "2026-03-17T22:16:53Z" }),
    ];

    expect(sortLoopsByMostRecentUpdate(loops).map((item) => item.id)).toEqual([7, 4]);
    expect(buildRepeatedSnoozeSignal([], loops, loopTitle)).toEqual({
      preview: [
        { label: "Deferred 1", value: "Newest deferred loop" },
        { label: "Deferred 2", value: "Older deferred loop" },
      ],
      contextSources: ["Current snoozed loop state", "Stored continuity baseline"],
      assumptions: ["Newly snoozed loops can signal growing deferral even when no local snooze history was recorded."],
    });
  });

  it("prefers snooze-action history when present", () => {
    const actions = [
      snoozeAction({ label: "Snoozed 2 selected loops" }),
      snoozeAction({ label: "Snoozed loop #7", occurredAt: "2026-03-17T22:14:00Z" }),
    ];

    expect(buildRepeatedSnoozeSignal(actions, [loop({ id: 7 })], loopTitle)).toEqual({
      preview: [
        { label: "Snooze 1", value: "Snoozed 2 selected loops" },
        { label: "Snooze 2", value: "Snoozed loop #7" },
      ],
      contextSources: ["Browser-local recent shell action history", "Current snoozed loop state"],
      assumptions: ["Repeated snoozes indicate a review-worthy pattern rather than intentional batching alone."],
    });
  });

  it("merges planning resource change groups deterministically", () => {
    const groups: PlanningResourceChangeGroupResponse[] = [
      {
        resource_type: "loop",
        resource_type_label: "loop",
        role: "updated",
        role_label: "updated",
        display_label: "1 loop updated",
        count: 1,
        resource_ids: [7],
        preview_labels: ["Prepare launch checklist"],
        operation_indexes: [0],
        operation_summaries: ["Clarify the first loop"],
      },
      {
        resource_type: "loop",
        resource_type_label: "loop",
        role: "updated",
        role_label: "updated",
        display_label: "1 loop updated",
        count: 1,
        resource_ids: [9],
        preview_labels: ["Confirm launch owner"],
        operation_indexes: [1],
        operation_summaries: ["Update the second loop"],
      },
      {
        resource_type: "review_session",
        resource_type_label: "review session",
        role: "created",
        role_label: "created",
        display_label: "1 review session created",
        count: 1,
        resource_ids: [3],
        preview_labels: ["launch-follow-up"],
        operation_indexes: [2],
        operation_summaries: ["Create a follow-up review queue"],
      },
    ];

    expect(mergePlanningResourceChangeGroups(groups)).toEqual([
      expect.objectContaining({
        resource_type: "loop",
        role: "updated",
        count: 2,
        resource_ids: [7, 9],
        preview_labels: ["Prepare launch checklist", "Confirm launch owner"],
      }),
      expect.objectContaining({
        resource_type: "review_session",
        role: "created",
        count: 1,
        resource_ids: [3],
      }),
    ]);
    expect(buildPlanningResourcePreviewItems(mergePlanningResourceChangeGroups(groups))).toEqual([
      {
        label: "Change 1",
        value: "2 loops updated · Prepare launch checklist, Confirm launch owner",
      },
      {
        label: "Change 2",
        value: "1 review session created · launch-follow-up",
      },
    ]);
  });

  it("builds grouped change preview items in input order", () => {
    expect(buildGroupedChangePreviewItems([
      { label: "Planning drift", summary: "2 target loops changed" },
      { label: "Planning activity", summary: "3 downstream resources created" },
    ])).toEqual([
      { label: "Planning drift", value: "2 target loops changed" },
      { label: "Planning activity", value: "3 downstream resources created" },
    ]);
  });
});
