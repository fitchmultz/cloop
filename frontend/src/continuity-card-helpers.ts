/**
 * continuity-card-helpers.ts - Pure helper logic for operator-shell continuity cards.
 *
 * Purpose:
 *   Keep the operator shell's since-last-visit cards deterministic, concise, and
 *   easy to test by extracting pure preview/signal shaping helpers.
 *
 * Responsibilities:
 *   - Build preview rows for changed count deltas without noisy unchanged rows.
 *   - Normalize repeated-snooze signal content from browser history and live loop state.
 *   - Sort live loop previews deterministically by most recent update time.
 *
 * Scope:
 *   - Frontend-only pure helpers used by continuity cards in the shell.
 *
 * Usage:
 *   - Imported by frontend/src/shell.ts when shaping since-last-visit cards.
 *
 * Invariants/Assumptions:
 *   - Updated timestamps may be missing or malformed; malformed values sort last.
 *   - Preview rows should favor changed signals first and only fall back to full
 *     inputs when every row is unchanged.
 */

import type {
  LoopResponse,
  PlanningResourceChangeGroupResponse,
} from "./domain";
import type { OperatorActionPreviewItem, RecentShellActionEntry } from "./contracts-ui";
import { resolveContinuityEntry } from "./continuity-outcomes";

export interface CountDeltaPreviewInput {
  label: string;
  previous: number;
  current: number;
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) {
    return Number.NEGATIVE_INFINITY;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

export function buildChangedCountPreviewItems(
  inputs: CountDeltaPreviewInput[],
): OperatorActionPreviewItem[] {
  const changed = inputs.filter((input) => input.previous !== input.current);
  const previewSource = changed.length ? changed : inputs;
  return previewSource.map((input) => ({
    label: input.label,
    value: `${input.previous} → ${input.current}`,
  }));
}

export function sortLoopsByMostRecentUpdate<T extends Pick<LoopResponse, "updated_at_utc">>(
  loops: readonly T[],
): T[] {
  return [...loops].sort((left, right) => parseTimestamp(right.updated_at_utc) - parseTimestamp(left.updated_at_utc));
}

const RESOURCE_CHANGE_ORDER: Record<string, number> = {
  loop: 0,
  review_session: 1,
  view: 2,
  template: 3,
};

function resourceChangeDisplayLabel(
  count: number,
  resourceTypeLabel: string,
  roleLabel: string,
): string {
  return `${count} ${count === 1 ? resourceTypeLabel : `${resourceTypeLabel}s`} ${roleLabel}`;
}

export interface RepeatedSnoozeSignal {
  preview: OperatorActionPreviewItem[];
  contextSources: string[];
  assumptions: string[];
}

export interface GroupedChangeThemePreviewInput {
  label: string;
  summary: string;
}

export function mergePlanningResourceChangeGroups(
  groups: readonly PlanningResourceChangeGroupResponse[],
): PlanningResourceChangeGroupResponse[] {
  const buckets = new Map<string, PlanningResourceChangeGroupResponse>();

  groups.forEach((group) => {
    const key = `${group.resource_type}:${group.role}`;
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        ...group,
        resource_ids: [...(group.resource_ids ?? [])],
        preview_labels: [...(group.preview_labels ?? [])],
        operation_indexes: [...(group.operation_indexes ?? [])],
        operation_summaries: [...(group.operation_summaries ?? [])],
      });
      return;
    }

    const resourceIds = new Set([...(existing.resource_ids ?? []), ...(group.resource_ids ?? [])]);
    const previewLabels = new Set([...(existing.preview_labels ?? []), ...(group.preview_labels ?? [])]);
    const operationIndexes = new Set([...(existing.operation_indexes ?? []), ...(group.operation_indexes ?? [])]);
    const operationSummaries = new Set([...(existing.operation_summaries ?? []), ...(group.operation_summaries ?? [])]);

    const count = resourceIds.size;
    buckets.set(key, {
      ...existing,
      count,
      display_label: resourceChangeDisplayLabel(
        count,
        existing.resource_type_label,
        existing.role_label,
      ),
      resource_ids: [...resourceIds],
      preview_labels: [...previewLabels].slice(0, 3),
      operation_indexes: [...operationIndexes].sort((left, right) => left - right),
      operation_summaries: [...operationSummaries].slice(0, 3),
    });
  });

  return [...buckets.values()].sort((left, right) => {
    const typeDelta = (RESOURCE_CHANGE_ORDER[left.resource_type] ?? 99)
      - (RESOURCE_CHANGE_ORDER[right.resource_type] ?? 99);
    if (typeDelta !== 0) {
      return typeDelta;
    }
    return left.role.localeCompare(right.role);
  });
}

export function buildPlanningResourcePreviewItems(
  groups: readonly PlanningResourceChangeGroupResponse[],
): OperatorActionPreviewItem[] {
  return groups.slice(0, 3).map((group, index) => {
    const previewLabels = group.preview_labels ?? [];
    return {
      label: `Change ${index + 1}`,
      value: previewLabels.length
        ? `${group.display_label} · ${previewLabels.join(", ")}`
        : group.display_label,
    };
  });
}

export function buildGroupedChangePreviewItems(
  themes: readonly GroupedChangeThemePreviewInput[],
): OperatorActionPreviewItem[] {
  return themes.slice(0, 4).map((theme) => ({
    label: theme.label,
    value: theme.summary,
  }));
}

export function buildRepeatedSnoozeSignal(
  snoozeActions: RecentShellActionEntry[],
  newlySnoozedLoops: readonly Pick<LoopResponse, "id" | "title" | "raw_text" | "updated_at_utc">[],
  loopTitle: (loop: Pick<LoopResponse, "id" | "title" | "raw_text">) => string,
): RepeatedSnoozeSignal {
  const sortedLoops = sortLoopsByMostRecentUpdate(newlySnoozedLoops);

  if (snoozeActions.length) {
    return {
      preview: snoozeActions.slice(0, 3).map((entry, index) => ({
        label: `Snooze ${index + 1}`,
        value: resolveContinuityEntry(entry).displayTitle,
      })),
      contextSources: ["Browser-local recent shell action history", "Current snoozed loop state"],
      assumptions: ["Repeated snoozes indicate a review-worthy pattern rather than intentional batching alone."],
    };
  }

  return {
    preview: sortedLoops.slice(0, 3).map((loop, index) => ({
      label: `Deferred ${index + 1}`,
      value: loopTitle(loop),
    })),
    contextSources: ["Current snoozed loop state", "Stored continuity baseline"],
    assumptions: ["Newly snoozed loops can signal growing deferral even when no local snooze history was recorded."],
  };
}
