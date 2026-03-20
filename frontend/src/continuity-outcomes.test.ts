/**
 * continuity-outcomes.test.ts - Regression tests for outcome-first continuity resolution.
 *
 * Purpose:
 *   Verify landed-outcome continuity precedence, dedupe keys, and low-signal
 *   navigation classification stay deterministic.
 *
 * Responsibilities:
 *   - Assert outcome display and resume targets win over launch metadata.
 *   - Guard dedupe identity against launch-label churn.
 *   - Confirm low-signal navigation remains classified as secondary history.
 *
 * Scope:
 *   - Pure outcome-resolution helper behavior only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Continuity helpers remain pure and frontend-only.
 *   - Outcome cards are the canonical landed display payload when present.
 */

import type { RecentShellActionEntry, ShellLocationContract } from "./contracts-ui";
import {
  isLowSignalNavigationEntry,
  recentShellActionDedupKey,
  resolveContinuityEntry,
  resolveContinuityResumeLocation,
  resolveContinuityWorkingSetId,
} from "./continuity-outcomes";

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

function receiptEntry(overrides: Partial<RecentShellActionEntry> = {}): RecentShellActionEntry {
  return {
    kind: overrides.kind ?? "review",
    label: overrides.label ?? "Opened enrichment queue",
    description: overrides.description ?? "Launch description",
    location: overrides.location ?? location({ state: "review", reviewFocus: "cohorts" }),
    occurredAt: overrides.occurredAt ?? "2026-03-20T12:00:00Z",
    metadata: overrides.metadata ?? null,
    outcome: overrides.outcome ?? {
      card: {
        id: "receipt-1",
        kind: "receipt",
        tone: "progress",
        eyebrow: "Enrichment receipt",
        title: "Applied enrichment suggestion",
        summary: "Applied the top suggestion and advanced the queue.",
        rationale: "Receipt",
        preview: [],
        trust: {
          contextSources: ["Saved enrichment queue"],
          assumptions: [],
          confidenceLabel: "Recorded",
          freshnessLabel: "Saved just now",
          rollbackLabel: "Rejecting is no longer available after apply.",
        },
        handoff: {
          changeSummary: "Queue advanced.",
          createdResources: [],
          nextStep: "Resume the queue.",
          breadcrumbs: ["Home", "Decide"],
          workingSet: {
            workingSetId: 7,
            workingSetName: "Review Prep",
            itemCount: 4,
            missingItemCount: 0,
          },
        },
        actions: [],
      },
      resumeLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 7 }),
      rollbackLabel: "Rejecting is no longer available after apply.",
      undoAction: null,
    },
  };
}

describe("continuity-outcomes", () => {
  it("prefers landed outcome display and resume data over launch metadata", () => {
    const resolved = resolveContinuityEntry(receiptEntry());

    expect(resolved.displayTitle).toBe("Applied enrichment suggestion");
    expect(resolved.displaySummary).toBe("Applied the top suggestion and advanced the queue.");
    expect(resolved.resumeLocation).toEqual(location({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 7 }));
    expect(resolveContinuityResumeLocation(receiptEntry())).toEqual(
      location({ state: "decide", reviewFocus: "enrichment", sessionId: 27, workingSetId: 7 }),
    );
    expect(resolveContinuityWorkingSetId(receiptEntry())).toBe(7);
  });

  it("dedupes the same landed outcome even when the launch label changes", () => {
    const first = receiptEntry({
      label: "Opened queue from planning",
      location: location({ state: "plan", reviewFocus: "planning", sessionId: 14 }),
    });
    const second = receiptEntry({
      label: "Opened queue from operator home",
      location: location({ state: "operator" }),
    });

    expect(recentShellActionDedupKey(first)).toBe(recentShellActionDedupKey(second));
  });

  it("keeps distinct landed targets separate even when the launch point matches", () => {
    const first = receiptEntry();
    const second = receiptEntry({
      outcome: {
        ...receiptEntry().outcome!,
        resumeLocation: location({ state: "decide", reviewFocus: "relationship", sessionId: 91, workingSetId: 7 }),
      },
    });

    expect(recentShellActionDedupKey(first)).not.toBe(recentShellActionDedupKey(second));
  });

  it("marks plain navigation-only entries as low signal", () => {
    expect(isLowSignalNavigationEntry({
      kind: "navigation",
      label: "Opened do",
      description: "Moved into the do workspace.",
      location: location({ state: "do" }),
      occurredAt: "2026-03-20T12:00:00Z",
    })).toBe(true);

    expect(isLowSignalNavigationEntry(receiptEntry())).toBe(false);
  });
});
