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
import { markContinuityRecoveryAcknowledged } from "./continuity-intelligence";
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
    persistence: overrides.persistence ?? null,
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

function createMemoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length(): number {
      return values.size;
    },
    clear(): void {
      values.clear();
    },
    getItem(key: string): string | null {
      return values.get(key) ?? null;
    },
    key(index: number): string | null {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      values.delete(key);
    },
    setItem(key: string, value: string): void {
      values.set(key, value);
    },
  } satisfies Storage;
}

let originalLocalStorage: Storage;

describe("readRankedLandedOutcomes", () => {
  beforeEach(() => {
    originalLocalStorage = window.localStorage as Storage;
    Object.defineProperty(window, "localStorage", {
      value: createMemoryStorage(),
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
  });
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
    expect(outcomes[0]?.recovery).toMatchObject({
      kind: "working_set_scope_removed",
      ctaLabel: "Open durable target",
    });
    expect(outcomes[0]?.card.actions[0]).toMatchObject({
      type: "recover",
      label: "Open durable target",
    });
    expect(outcomes[0]?.card.actions[1]?.type).toBe("acknowledge");
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

  it("adds replacement recovery when an older anchor was superseded", () => {
    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        planningSessionIds: [41, 99],
      }),
      recentActions: [receiptEntry({
        occurredAt: "2026-03-20T12:03:00Z",
        outcome: {
          ...receiptEntry().outcome!,
          card: {
            ...receiptEntry().outcome!.card,
            title: "Replacement plan is ready",
            summary: "Open the refreshed planning session.",
          },
          resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
          workflowThread: {
            id: "planning:99",
            kind: "planning_checkpoint",
            title: "Replacement plan",
            summary: "New planning thread",
            parentOutcomeId: null,
          },
          resolvedResume: {
            requestedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
            resolvedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
            status: "ok",
            message: null,
          },
        },
      })],
      resumeAnchors: {
        planning: {
          kind: "planning",
          reviewFocus: "planning",
          sessionId: 41,
          visitedAtUtc: "2026-03-20T12:00:00Z",
          launchLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          outcomeTitle: "Old plan",
          outcomeSummary: "Prior planning path",
          workingSetId: null,
          workflowThreadId: "planning:41",
        },
        review: null,
      },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    const anchorOutcome = outcomes.find((item) => item.source === "anchor");
    expect(anchorOutcome?.recovery).toMatchObject({
      kind: "replacement",
      ctaLabel: "Open replacement workflow",
    });
    expect(anchorOutcome?.card.actions[0]).toMatchObject({
      type: "recover",
      label: "Open replacement workflow",
    });
  });

  it("removes the acknowledgement action once recovery is acknowledged", () => {
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

    const recoveryKey = outcomes[0]?.recovery?.key;
    expect(recoveryKey).toBeTruthy();
    markContinuityRecoveryAcknowledged(recoveryKey!);

    const acknowledged = readRankedLandedOutcomes({
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

    expect(acknowledged[0]?.recovery?.acknowledged).toBe(true);
    expect(acknowledged[0]?.card.actions.some((action) => action.type === "acknowledge")).toBe(false);
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

  it("marks an unseen higher outcome id in the same workflow thread as major drift", () => {
    window.localStorage.setItem("cloop.continuity.last-seen.cache.v1", JSON.stringify([
      {
        entityKind: "workflow_thread",
        entityKey: "planning:41",
        observedAtUtc: "2026-03-20T11:59:00Z",
        observedFingerprint: "{\"latestOutcomeId\":2}",
        workingSetId: null,
        workflowThreadId: "planning:41",
        observedState: { latestOutcomeId: 2 },
        metadata: {},
      },
    ]));

    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        planningSessionIds: [41],
        workingSets: [workingSet(7, "Launch Prep")],
      }),
      recentActions: [
        receiptEntry({
          occurredAt: "2026-03-20T10:00:00Z",
          persistence: { status: "synced", persistedOutcomeId: 12, syncedAtUtc: "2026-03-20T10:00:00Z" },
          outcome: {
            ...receiptEntry().outcome!,
            workflowThread: {
              id: "planning:41",
              kind: "planning_checkpoint",
              title: "Weekly reset",
              summary: "Thread",
              parentOutcomeId: null,
            },
            resolvedResume: receiptEntry().outcome!.resolvedResume ?? null,
          },
        }),
      ],
      resumeAnchors: { planning: null, review: null },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    expect(outcomes[0]?.persistedOutcomeId).toBe(12);
    expect(outcomes[0]?.rankingSignals.driftSeverity).toBe("major");
  });

  it("marks a newer workflow as replaced when it supersedes the durable anchor in the same family", () => {
    const outcomes = readRankedLandedOutcomes({
      availability: buildContinuityAvailability({
        planningSessionIds: [41, 99],
      }),
      recentActions: [
        receiptEntry({
          occurredAt: "2026-03-20T12:03:00Z",
          outcome: {
            ...receiptEntry().outcome!,
            workflowThread: {
              id: "planning:99",
              kind: "planning_checkpoint",
              title: "Replacement plan",
              summary: "New planning thread",
              parentOutcomeId: null,
            },
            resolvedResume: {
              requestedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
              resolvedLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 99 }),
              status: "ok",
              message: null,
            },
          },
        }),
      ],
      resumeAnchors: {
        planning: {
          kind: "planning",
          reviewFocus: "planning",
          sessionId: 41,
          visitedAtUtc: "2026-03-20T12:00:00Z",
          launchLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          resumeLocation: location({ state: "plan", reviewFocus: "planning", sessionId: 41 }),
          outcomeTitle: "Old plan",
          outcomeSummary: "Prior planning path",
          workingSetId: null,
          workflowThreadId: "planning:41",
        },
        review: null,
      },
      now: Date.parse("2026-03-20T12:05:00Z"),
    });

    expect(outcomes[0]?.rankingSignals.driftSeverity).toBe("replaced");
  });
});
