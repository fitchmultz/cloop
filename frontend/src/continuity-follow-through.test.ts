/**
 * continuity-follow-through.test.ts - Regression tests for canonical landed-outcome follow-through ranking.
 *
 * Purpose:
 *   Verify the shared follow-through feed ranks landed outcomes consistently
 *   across recent receipts, anchors, fallback targets, and action affordances.
 *
 * Responsibilities:
 *   - Assert recent receipts outrank anchor-only fallbacks.
 *   - Assert anchors do not duplicate recent landed targets.
 *   - Assert degraded working-set scope falls back safely.
 *   - Assert resume, rerun, and undo affordances normalize consistently.
 *
 * Scope:
 *   - Pure follow-through feed helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - The canonical feed is the only ranking truth for landed follow-through.
 *   - Landed rerun actions should survive normalization when present on the card.
 */

import type {
  RecentShellActionEntry,
  ResumeAnchorState,
  ShellLocationContract,
  WorkingSetSessionMetadata,
} from "./contracts-ui";
import {
  buildContinuityAvailability,
  groupRankedWorkflowThreads,
  readRankedLandedOutcomes,
} from "./continuity-follow-through";

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

function workingSet(id: number, name: string): WorkingSetSessionMetadata {
  return {
    workingSetId: id,
    workingSetName: name,
    itemCount: 5,
    missingItemCount: 0,
  };
}

function receiptEntry(overrides: Partial<RecentShellActionEntry> = {}): RecentShellActionEntry {
  return {
    kind: overrides.kind ?? "planning",
    label: overrides.label ?? "Executed checkpoint",
    description: overrides.description ?? "Created the downstream review queue.",
    location: overrides.location ?? location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
    occurredAt: overrides.occurredAt ?? "2026-03-20T12:00:00Z",
    metadata: overrides.metadata ?? null,
    outcome: overrides.outcome ?? {
      card: {
        id: "receipt-1",
        kind: "receipt",
        tone: "progress",
        eyebrow: "Planning receipt",
        title: "Created launch review queue",
        summary: "The enrichment queue is ready to resume.",
        rationale: "Receipt",
        preview: [],
        trust: {
          contextSources: ["Planning session"],
          assumptions: [],
          confidenceLabel: "Recorded",
          freshnessLabel: "Saved just now",
          rollbackLabel: "Undo remains available from the landed outcome.",
        },
        handoff: {
          changeSummary: "Queue created.",
          createdResources: ["Launch enrichment queue"],
          nextStep: "Open the created queue.",
          breadcrumbs: ["Home", "Plan"],
          workingSet: workingSet(7, "Launch Prep"),
        },
        actions: [
          {
            type: "undo",
            label: "Undo checkpoint",
            variant: "secondary",
            description: "Undo the checkpoint execution.",
            undo: {
              kind: "planning_run",
              sessionId: 41,
              runId: 8,
              checkpointIndex: 1,
              checkpointTitle: "Create queue",
              actionCount: 2,
              bestEffort: false,
            },
          },
          {
            type: "rerun",
            label: "Refresh plan",
            variant: "secondary",
            description: "Land back in the saved planning session with refreshed checkpoints.",
            rerun: {
              kind: "planning_session",
              sessionId: 41,
              sessionName: "Weekly reset",
            },
            contract: {
              mode: "refresh",
              provenanceLabel: "Planning session: Weekly reset",
              freshnessLabel: "1 target changed",
              strategySummary: "Reuse the saved planning session and refresh it against current loop state.",
              strictInvariants: ["Same planning session identity"],
              mayVary: ["Checkpoint wording"],
              postRun: {
                summary: "Land back in the saved planning session with refreshed checkpoints.",
                location: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 7 }),
              },
            },
          },
        ],
      },
      resumeLocation: location({
        state: "decide",
        reviewFocus: "enrichment",
        sessionId: 52,
        workingSetId: 7,
      }),
      rollbackLabel: "Undo remains available from the landed outcome.",
      workflowThread: {
        id: "planning:41:checkpoint:0",
        kind: "planning_checkpoint",
        title: "Weekly reset",
        summary: "Planning checkpoint thread",
        parentOutcomeId: null,
      },
      resolvedResume: {
        requestedLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
        resolvedLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
        status: "ok",
        message: null,
      },
      undoAction: {
        type: "undo",
        label: "Undo checkpoint",
        variant: "secondary",
        description: "Undo the checkpoint execution.",
        undo: {
          kind: "planning_run",
          sessionId: 41,
          runId: 8,
          checkpointIndex: 1,
          checkpointTitle: "Create queue",
          actionCount: 2,
          bestEffort: false,
        },
      },
    },
  };
}

describe("readRankedLandedOutcomes", () => {
  it("ranks a recent receipt above an anchor-only fallback and suppresses a duplicate anchor target", () => {
    const anchors: ResumeAnchorState = {
      planning: null,
      review: {
        kind: "review",
        reviewFocus: "enrichment",
        sessionId: 52,
        visitedAtUtc: "2026-03-20T11:50:00Z",
        launchLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
        resumeLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
        outcomeTitle: "Created launch review queue",
        outcomeSummary: "The enrichment queue is ready to resume.",
        workingSetId: 7,
      },
    };

    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        planningSessionIds: [41],
        enrichmentSessionIds: [52],
        workingSets: [workingSet(7, "Launch Prep")],
      }),
      activeWorkingSetId: 7,
      recentActions: [receiptEntry()],
      resumeAnchors: anchors,
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    expect(outcomes).toHaveLength(1);
    expect(outcomes[0]?.source).toBe("receipt");
    expect(outcomes[0]?.displayTitle).toBe("Created launch review queue");
  });

  it("falls back to the durable target when the working-set scope is gone", () => {
    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        enrichmentSessionIds: [52],
      }),
      recentActions: [receiptEntry({
        outcome: {
          ...receiptEntry().outcome!,
          resolvedResume: null,
        },
      })],
      resumeAnchors: { planning: null, review: null },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    expect(outcomes[0]?.resumeLocation.workingSetId).toBeNull();
    expect(outcomes[0]?.degraded).toBe(true);
    expect(outcomes[0]?.degradedLabel).toMatch(/Working-set scope was removed/i);
  });

  it("normalizes resume first, rerun second, then undo", () => {
    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        enrichmentSessionIds: [52],
        workingSets: [workingSet(7, "Launch Prep")],
      }),
      recentActions: [receiptEntry()],
      resumeAnchors: { planning: null, review: null },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    expect(outcomes[0]?.card.actions[0]?.type).toBe("open");
    expect(outcomes[0]?.card.actions[1]?.type).toBe("rerun");
    expect(outcomes[0]?.card.actions[2]?.type).toBe("undo");
    expect(outcomes[0]?.card.actions[3]?.type).toBe("pin");
    expect(outcomes[0]?.rerunAction?.type).toBe("rerun");
  });

  it("uses working-set metadata from availability when anchors need a fallback name", () => {
    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        planningSessionIds: [41],
        workingSets: [workingSet(7, "Launch Prep")],
      }),
      recentActions: [],
      resumeAnchors: {
        planning: {
          kind: "planning",
          reviewFocus: "planning",
          sessionId: 41,
          visitedAtUtc: "2026-03-20T12:00:00Z",
          launchLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 7 }),
          resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41, workingSetId: 7 }),
          outcomeTitle: "Resume launch plan",
          outcomeSummary: "Continue the saved plan.",
          workingSetId: 7,
          workflowThreadId: "planning:41",
        },
        review: null,
      },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    expect(outcomes[0]?.workingSetName).toBe("Launch Prep");
    expect(outcomes[0]?.card.handoff?.workingSet?.workingSetName).toBe("Launch Prep");
  });

  it("groups related outcomes into one ranked workflow thread", () => {
    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        enrichmentSessionIds: [52],
        workingSets: [workingSet(7, "Launch Prep")],
      }),
      recentActions: [
        receiptEntry(),
        receiptEntry({
          occurredAt: "2026-03-20T12:03:00Z",
          label: "Refreshed launch queue",
          description: "The enrichment queue was refreshed.",
          outcome: {
            ...receiptEntry().outcome!,
            card: {
              ...receiptEntry().outcome!.card,
              id: "receipt-2",
              title: "Refreshed launch queue",
              summary: "The enrichment queue was refreshed.",
            },
            workflowThread: {
              id: "planning:41:checkpoint:0",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Planning checkpoint thread",
              parentOutcomeId: null,
            },
            resolvedResume: {
              requestedLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
              resolvedLocation: location({ state: "decide", reviewFocus: "enrichment", sessionId: 52, workingSetId: 7 }),
              status: "ok",
              message: null,
            },
          },
        }),
      ],
      resumeAnchors: { planning: null, review: null },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    const threads = groupRankedWorkflowThreads(outcomes);
    expect(threads).toHaveLength(1);
    expect(threads[0]?.thread.id).toBe("planning:41:checkpoint:0");
    expect(threads[0]?.outcomeCount).toBe(2);
  });
});
