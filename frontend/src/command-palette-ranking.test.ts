/**
 * command-palette-ranking.test.ts - Regression tests for deterministic palette ranking.
 *
 * Purpose:
 *   Verify that command-palette ranking keeps favoring exact query matches,
 *   current-context matches, and recent usage in a predictable order.
 *
 * Responsibilities:
 *   - Assert exact-title matches outrank weaker fuzzy matches.
 *   - Assert active-state/focus context boosts affect ordering.
 *   - Guard recent-usage weighting from accidental regressions.
 *
 * Scope:
 *   - Pure ranking helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests avoid DOM dependencies and operate on pure ranking inputs.
 *   - Ranking stays deterministic for identical inputs.
 */

import type { ShellLocationContract } from "./contracts-ui";
import {
  locationsMatch,
  rankPaletteItems,
  type PaletteRankItem,
  type PaletteRankingContext,
} from "./command-palette-ranking";

function location(overrides: Partial<ShellLocationContract> = {}): ShellLocationContract {
  return {
    state: overrides.state ?? "operator",
    recallTool: overrides.recallTool ?? "chat",
    reviewFocus: overrides.reviewFocus ?? null,
    sessionId: overrides.sessionId ?? null,
    loopId: overrides.loopId ?? null,
    viewId: overrides.viewId ?? null,
    memoryId: overrides.memoryId ?? null,
    workingSetId: overrides.workingSetId ?? null,
    query: overrides.query ?? null,
  };
}

function rankingContext(overrides: Partial<PaletteRankingContext> = {}): PaletteRankingContext {
  return {
    query: overrides.query ?? "",
    currentLocation: overrides.currentLocation ?? location({ state: "do", loopId: 18 }),
    focusLocations: overrides.focusLocations ?? [location({ state: "plan", reviewFocus: "planning", sessionId: 9 })],
    activeWorkingSetId: overrides.activeWorkingSetId ?? null,
    recentUsage: overrides.recentUsage ?? {},
    selectedLoopIds: overrides.selectedLoopIds ?? [],
    now: overrides.now ?? Date.parse("2026-03-17T12:00:00Z"),
  };
}

describe("locationsMatch", () => {
  it("matches identical shell locations", () => {
    expect(locationsMatch(location({ state: "recall", memoryId: 4 }), location({ state: "recall", memoryId: 4 }))).toBe(true);
  });

  it("treats differing query anchors as different locations", () => {
    expect(
      locationsMatch(
        location({ state: "review", query: "status:blocked" }),
        location({ state: "review", query: "status:open" }),
      ),
    ).toBe(false);
  });

  it("treats different working-set sessions as different locations", () => {
    expect(
      locationsMatch(
        location({ state: "working_set", workingSetId: 1 }),
        location({ state: "working_set", workingSetId: 2 }),
      ),
    ).toBe(false);
  });
});

describe("rankPaletteItems", () => {
  it("prefers exact title matches over weaker partial matches", () => {
    const items: PaletteRankItem[] = [
      {
        id: "exact",
        group: "navigate",
        title: "Open planning workspace",
        subtitle: "Resume checkpointed planning",
        keywords: ["plan", "planning", "workspace"],
      },
      {
        id: "partial",
        group: "navigate",
        title: "Open planning queue",
        subtitle: "Jump to planning workspace",
        keywords: ["plan", "planning", "queue", "workspace"],
      },
    ];

    const ranked = rankPaletteItems(items, rankingContext({ query: "open planning workspace" }));
    expect(ranked.map((entry) => entry.item.id)).toEqual(["exact", "partial"]);
  });

  it("boosts commands that match the current location and active focus context", () => {
    const items: PaletteRankItem[] = [
      {
        id: "current-loop",
        group: "navigate",
        title: "Open current loop",
        subtitle: "Return to the selected do-surface loop",
        keywords: ["loop", "current"],
        location: location({ state: "do", loopId: 18 }),
      },
      {
        id: "focus-plan",
        group: "navigate",
        title: "Resume launch plan",
        subtitle: "Return to the focused planning session",
        keywords: ["plan", "launch"],
        location: location({ state: "plan", reviewFocus: "planning", sessionId: 9 }),
      },
      {
        id: "generic-review",
        group: "navigate",
        title: "Open review",
        subtitle: "Open hygiene review",
        keywords: ["review"],
        location: location({ state: "review", reviewFocus: "cohorts" }),
      },
    ];

    const ranked = rankPaletteItems(items, rankingContext({ query: "" }));
    expect(ranked[0]?.item.id).toBe("current-loop");
    expect(ranked[1]?.item.id).toBe("focus-plan");
  });

  it("uses recent history to lift commands with similar textual relevance", () => {
    const items: PaletteRankItem[] = [
      {
        id: "stale",
        group: "recent",
        title: "Open blocked loops",
        subtitle: "Review blocked drift",
        keywords: ["blocked", "review"],
      },
      {
        id: "recent",
        group: "recent",
        title: "Open blocked queue",
        subtitle: "Resume blocker triage",
        keywords: ["blocked", "queue"],
      },
    ];

    const ranked = rankPaletteItems(
      items,
      rankingContext({
        query: "blocked",
        recentUsage: {
          recent: { count: 3, usedAt: "2026-03-17T11:30:00Z" },
        },
      }),
    );

    expect(ranked[0]?.item.id).toBe("recent");
  });

  it("prefers working-set-scoped resumes over generic session resumes when a bounded context is active", () => {
    const items: PaletteRankItem[] = [
      {
        id: "generic-plan",
        group: "recent",
        title: "Resume plan · Launch prep",
        subtitle: "Recent generic reopen",
        keywords: ["plan", "planning", "launch"],
        location: location({ state: "plan", reviewFocus: "planning", sessionId: 12 }),
      },
      {
        id: "scoped-plan",
        group: "review",
        title: "Resume plan · Launch prep",
        subtitle: "2/4 checkpoints executed · Review Prep",
        keywords: ["plan", "planning", "launch", "Review Prep"],
        contextBoost: 86,
        location: location({ state: "plan", reviewFocus: "planning", sessionId: 12, workingSetId: 7 }),
      },
    ];

    const ranked = rankPaletteItems(
      items,
      rankingContext({
        activeWorkingSetId: 7,
        query: "resume plan",
        recentUsage: {
          "generic-plan": { count: 2, usedAt: "2026-03-17T11:30:00Z" },
        },
      }),
    );

    expect(ranked.map((entry) => entry.item.id)).toEqual(["scoped-plan", "generic-plan"]);
  });

  it("prefers higher continuity-ranked recent outcomes even when another item has heavier local usage", () => {
    const items: PaletteRankItem[] = [
      {
        id: "canonical-top",
        group: "recent",
        title: "Created launch review queue",
        subtitle: "The enrichment queue is ready to resume.",
        keywords: ["launch", "review", "queue"],
        continuityRank: 420,
      },
      {
        id: "usage-heavy",
        group: "recent",
        title: "Pinned working set",
        subtitle: "Saved the current context.",
        keywords: ["working", "set", "pin"],
        continuityRank: 120,
      },
    ];

    const ranked = rankPaletteItems(
      items,
      rankingContext({
        query: "",
        recentUsage: {
          "usage-heavy": { count: 6, usedAt: "2026-03-17T11:58:00Z" },
        },
      }),
    );

    expect(ranked[0]?.item.id).toBe("canonical-top");
  });

  it("prefers high-drift downstream-ready continuity items over fresher local usage alone", () => {
    const items: PaletteRankItem[] = [
      {
        id: "high-drift",
        group: "recent",
        title: "Resume enrichment queue",
        subtitle: "Major unseen drift",
        keywords: ["resume", "queue"],
        continuitySignals: {
          driftScore: 78,
          workingSetRelevant: true,
          downstreamReady: true,
          degraded: false,
          recencyTieBreaker: 4,
        },
      },
      {
        id: "fresh-usage",
        group: "recent",
        title: "Open chat",
        subtitle: "Recently used",
        keywords: ["chat"],
      },
    ];

    const ranked = rankPaletteItems(
      items,
      rankingContext({
        recentUsage: { "fresh-usage": { count: 8, usedAt: "2026-03-17T11:59:00Z" } },
      }),
    );

    expect(ranked[0]?.item.id).toBe("high-drift");
  });
});
