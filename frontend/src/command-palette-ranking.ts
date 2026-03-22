/**
 * command-palette-ranking.ts - Deterministic ranking helpers for palette results.
 *
 * Purpose:
 *   Keep command-palette scoring predictable, testable, and independent from
 *   DOM rendering concerns.
 *
 * Responsibilities:
 *   - Normalize palette search text and query tokens.
 *   - Score palette items using query match, current context, focus context,
 *     and recent usage.
 *   - Provide a stable sort order for grouped palette results.
 *
 * Scope:
 *   - Pure ranking/model helpers only.
 *
 * Usage:
 *   - Imported by frontend/src/command-palette.ts to rank local commands,
 *     search results, and recent actions before rendering.
 *
 * Invariants/Assumptions:
 *   - Ranking must remain deterministic for the same inputs.
 *   - Query matching is intentionally transparent rather than probabilistic.
 *   - Location matches are treated as exact contract matches.
 */

import type { ShellLocationContract } from "./contracts-ui";

export type PaletteGroup =
  | "recommended"
  | "notifications"
  | "recent"
  | "navigate"
  | "capture"
  | "act"
  | "review"
  | "recall"
  | "search";

export interface PaletteRecentUsage {
  count: number;
  usedAt: string;
}

export interface PaletteContinuitySignals {
  driftScore: number;
  workingSetRelevant: boolean;
  downstreamReady: boolean;
  degraded: boolean;
  recencyTieBreaker: number;
}

export interface PaletteRankItem {
  id: string;
  group: PaletteGroup;
  title: string;
  subtitle: string;
  keywords: string[];
  location?: ShellLocationContract | null;
  searchText?: string | null;
  contextBoost?: number | undefined;
  continuityRank?: number | undefined;
  continuitySignals?: PaletteContinuitySignals | undefined;
  disabled?: boolean | undefined;
}

export interface PaletteRankingContext {
  query: string;
  currentLocation: ShellLocationContract;
  focusLocations: ShellLocationContract[];
  activeWorkingSetId: number | null;
  recentUsage: Record<string, PaletteRecentUsage>;
  selectedLoopIds: number[];
  now: number;
}

export interface RankedPaletteItem<T extends PaletteRankItem = PaletteRankItem> {
  item: T;
  matchedTokens: string[];
  score: number;
}

const GROUP_BASE_SCORES = {
  recommended: 320,
  notifications: 290,
  recent: 240,
  navigate: 210,
  act: 225,
  review: 190,
  capture: 185,
  recall: 170,
  search: 160,
} as const satisfies Record<PaletteGroup, number>;

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

function tokenize(value: string): string[] {
  return normalizeText(value)
    .split(/\s+/)
    .filter(Boolean);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function locationsMatch(
  left: ShellLocationContract | null | undefined,
  right: ShellLocationContract | null | undefined,
): boolean {
  if (!left || !right) {
    return false;
  }
  return left.state === right.state
    && left.recallTool === right.recallTool
    && left.reviewFocus === right.reviewFocus
    && left.sessionId === right.sessionId
    && left.loopId === right.loopId
    && (left.viewId ?? null) === (right.viewId ?? null)
    && (left.memoryId ?? null) === (right.memoryId ?? null)
    && (left.workingSetId ?? null) === (right.workingSetId ?? null)
    && (left.query ?? null) === (right.query ?? null);
}

export function buildPaletteSearchText(item: PaletteRankItem): string {
  return [item.title, item.subtitle, item.searchText ?? "", ...item.keywords]
    .map((value) => normalizeText(value))
    .filter(Boolean)
    .join(" ");
}

function titleMatchScore(title: string, query: string): number {
  if (!query) {
    return 0;
  }
  if (title === query) {
    return 220;
  }
  if (title.startsWith(query)) {
    return 160;
  }
  if (title.includes(` ${query}`)) {
    return 120;
  }
  if (title.includes(query)) {
    return 80;
  }
  return 0;
}

function tokenMatchScore(item: PaletteRankItem, queryTokens: string[]): { matched: string[]; score: number } {
  if (!queryTokens.length) {
    return { matched: [], score: 0 };
  }

  const title = normalizeText(item.title);
  const subtitle = normalizeText(item.subtitle);
  const keywords = item.keywords.map((keyword) => normalizeText(keyword));
  const searchText = buildPaletteSearchText(item);
  const matched: string[] = [];
  let score = 0;

  for (const token of queryTokens) {
    if (title === token) {
      matched.push(token);
      score += 140;
      continue;
    }
    if (title.startsWith(token)) {
      matched.push(token);
      score += 90;
      continue;
    }
    if (keywords.some((keyword) => keyword === token)) {
      matched.push(token);
      score += 70;
      continue;
    }
    if (keywords.some((keyword) => keyword.includes(token))) {
      matched.push(token);
      score += 48;
      continue;
    }
    if (subtitle.includes(token)) {
      matched.push(token);
      score += 32;
      continue;
    }
    if (searchText.includes(token)) {
      matched.push(token);
      score += 22;
    }
  }

  if (matched.length !== queryTokens.length) {
    return { matched: [], score: -1 };
  }

  return { matched, score };
}

function recentUsageScore(usage: PaletteRecentUsage | undefined, now: number): number {
  if (!usage) {
    return 0;
  }
  const usedAt = new Date(usage.usedAt);
  if (Number.isNaN(usedAt.getTime())) {
    return clamp(usage.count * 14, 0, 70);
  }
  const ageMs = Math.max(0, now - usedAt.getTime());
  const ageHours = ageMs / (60 * 60 * 1000);
  const freshness = clamp(60 - ageHours * 4, 0, 60);
  return clamp(usage.count * 16, 0, 96) + freshness;
}

function continuityScore(item: PaletteRankItem): number {
  const signals = item.continuitySignals;
  if (!signals) {
    return item.continuityRank ?? 0;
  }
  return (
    signals.driftScore * 6
    + (signals.workingSetRelevant ? 140 : 0)
    + (signals.downstreamReady ? 110 : -140)
    - (signals.degraded ? 80 : 0)
    + signals.recencyTieBreaker
  );
}

function locationContextScore(
  itemLocation: ShellLocationContract | null | undefined,
  context: PaletteRankingContext,
): number {
  if (!itemLocation) {
    return 0;
  }

  let score = 0;
  if (itemLocation.state === context.currentLocation.state) {
    score += 38;
  }
  if (itemLocation.loopId != null && context.selectedLoopIds.includes(itemLocation.loopId)) {
    score += 95;
  }
  if (locationsMatch(itemLocation, context.currentLocation)) {
    score += 74;
  }
  if (context.focusLocations.some((focusLocation) => locationsMatch(focusLocation, itemLocation))) {
    score += 64;
  }
  if (context.activeWorkingSetId != null && itemLocation.workingSetId === context.activeWorkingSetId) {
    score += itemLocation.state === "working_set" ? 120 : 90;
  }
  return score;
}

export function rankPaletteItems<T extends PaletteRankItem>(
  items: readonly T[],
  context: PaletteRankingContext,
): RankedPaletteItem<T>[] {
  const normalizedQuery = normalizeText(context.query);
  const queryTokens = tokenize(normalizedQuery);

  return items
    .map((item) => {
      const normalizedTitle = normalizeText(item.title);
      const titleScore = titleMatchScore(normalizedTitle, normalizedQuery);
      const tokenMatch = tokenMatchScore(item, queryTokens);
      if (queryTokens.length > 0 && tokenMatch.score < 0 && titleScore <= 0) {
        return null;
      }

      const score = GROUP_BASE_SCORES[item.group]
        + titleScore
        + Math.max(0, tokenMatch.score)
        + continuityScore(item)
        + Math.floor(recentUsageScore(context.recentUsage[item.id], context.now) / 4)
        + locationContextScore(item.location, context)
        + (item.contextBoost ?? 0)
        - (item.disabled ? 160 : 0);

      return {
        item,
        matchedTokens: tokenMatch.matched,
        score,
      } satisfies RankedPaletteItem<T>;
    })
    .filter((item): item is RankedPaletteItem<T> => item !== null)
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      if (left.item.group !== right.item.group) {
        return GROUP_BASE_SCORES[right.item.group] - GROUP_BASE_SCORES[left.item.group];
      }
      return left.item.title.localeCompare(right.item.title);
    });
}
