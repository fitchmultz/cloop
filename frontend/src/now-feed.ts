/**
 * now-feed.ts - Shared frontend adapters for backend-ranked operator Now-feed items.
 *
 * Purpose:
 *   Convert backend-ranked Now-feed entries into shared shell locations,
 *   action cards, and display labels for operator surfaces.
 *
 * Responsibilities:
 *   - Map backend launch locations into shell navigation contracts.
 *   - Build canonical operator action cards from Now-feed items.
 *   - Keep workspace and command-palette wording aligned on one feed contract.
 *
 * Scope:
 *   - Frontend adapters for `NowFeedItemResponse` only.
 *
 * Usage:
 *   - Imported by shell-operator-cards.ts and command-palette.ts.
 *
 * Invariants/Assumptions:
 *   - Backend ranking is canonical; this module does not re-rank items.
 *   - Every Now-feed item includes an explicit launch location.
 *   - Action-card rendering should stay lightweight and deterministic.
 */

import type { NowFeedItemResponse } from "./domain";
import type { OperatorActionCard } from "./contracts-ui";
import { mapApiLocation } from "./follow-through-adapters";
import { formatRelativeTime } from "./shell-core";

export function nowFeedLocation(item: NowFeedItemResponse) {
  return mapApiLocation(item.launch_location)!;
}

export function nowFeedFreshnessLabel(item: NowFeedItemResponse): string | null {
  if (!item.freshness_at_utc) {
    return null;
  }
  const prefix = item.freshness_prefix?.trim() || "Updated";
  return `${prefix} ${formatRelativeTime(item.freshness_at_utc)}`;
}

export function buildNowFeedActionCard(item: NowFeedItemResponse): OperatorActionCard {
  const location = nowFeedLocation(item);
  const reasons = item.reason_labels ?? [];
  return {
    id: `now-feed-${item.id}`,
    kind: item.display_kind ?? "context",
    tone: item.display_tone ?? "neutral",
    eyebrow: item.eyebrow,
    title: item.title,
    summary: item.summary,
    rationale: item.rationale,
    preview: reasons.slice(0, 4).map((reason, index) => ({
      label: index === 0 ? "Why now" : `Signal ${index + 1}`,
      value: reason,
    })),
    trust: {
      contextSources: [`Backend-ranked ${(item.source ?? "workflow").replaceAll("_", " ")} signal`],
      assumptions: [],
      confidenceLabel: reasons[0] ?? "Backend-ranked next move",
      freshnessLabel: nowFeedFreshnessLabel(item),
      rollbackLabel: "Opening this card does not mutate data until you act in the destination surface.",
    },
    handoff: {
      changeSummary: item.summary,
      createdResources: [],
      nextStep: reasons[0] ?? item.summary,
      breadcrumbs: ["Home", "Now", item.title],
    },
    actions: [
      {
        type: "open",
        label: item.action_label,
        variant: "primary",
        location,
        description: item.summary,
      },
      {
        type: "pin",
        label: "Pin for later",
        variant: "secondary",
        location,
        description: item.summary,
        pinLabel: item.title,
      },
    ],
  } satisfies OperatorActionCard;
}
