/**
 * operator-action-cards.test.ts - Regression tests for shared action-card rendering.
 *
 * Purpose:
 *   Verify the canonical action-card renderer supports open, pin, shared
 *   follow-through, and custom event actions without losing the trust and
 *   handoff anatomy.
 *
 * Responsibilities:
 *   - Assert event-style action buttons keep their custom data attributes.
 *   - Assert stage/edit/defer actions render deterministic follow-through datasets.
 *   - Assert recovery actions render dedicated recovery UI and datasets.
 *   - Guard shared card rendering from dropping trust or handoff sections.
 *
 * Scope:
 *   - Pure HTML-string rendering only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Button attributes remain declarative so shell/review handlers can attach
 *     behavior outside the renderer.
 *   - Rendered HTML stays deterministic for the same card payload.
 */

import type { OperatorActionCard } from "./contracts-ui";
import { renderActionCardDeck } from "./operator-action-cards";

describe("renderActionCardDeck", () => {
  it("renders event actions alongside trust and handoff content", () => {
    const cards: OperatorActionCard[] = [
      {
        id: "decision-1",
        kind: "decision",
        tone: "attention",
        eyebrow: "Review",
        title: "Apply the top suggestion",
        summary: "A structured suggestion is ready for review.",
        rationale: "Action cards keep the next mutation explicit and local to the queue.",
        preview: [{ label: "Loop", value: "Weekly reset" }],
        trust: {
          contextSources: ["Saved enrichment session", "Model: test-model"],
          assumptions: ["Human review remains required before mutating the loop."],
          confidenceLabel: "Structured suggestion ready",
          freshnessLabel: "Generated 2 minutes ago",
          rollbackLabel: "Apply or reject remains explicit",
        },
        handoff: {
          changeSummary: "Applying this suggestion updates the loop inside the current queue.",
          createdResources: [],
          nextStep: "Apply, reject, or inspect the loop in Do.",
          breadcrumbs: ["Home", "Review", "Enrichment queue"],
        },
        actionContextLabel: "Decision required",
        actionWarning: "Applying this suggestion mutates loop fields immediately.",
        actions: [
          {
            type: "event",
            label: "Apply",
            variant: "primary",
            description: "Apply the top suggestion",
            attributes: {
              "data-review-action": "enrichment-apply",
              "data-suggestion-id": "42",
            },
          },
        ],
      },
    ];

    const html = renderActionCardDeck(cards, "<p>Empty</p>");

    expect(html).toContain('data-review-action="enrichment-apply"');
    expect(html).toContain('data-suggestion-id="42"');
    expect(html).toContain("Decision required");
    expect(html).toContain("mutates loop fields immediately");
    expect(html).toContain("Trust surface");
    expect(html).toContain("Workflow handoff");
  });

  it("renders recovery blocks and recovery actions", () => {
    const cards: OperatorActionCard[] = [
      {
        id: "recovery-1",
        kind: "receipt",
        tone: "attention",
        eyebrow: "Continuity recovery",
        title: "Launch review queue is ready",
        summary: "The original queue is unavailable.",
        rationale: "Recovery keeps continuity actionable when the original path disappears.",
        preview: [],
        trust: {
          contextSources: ["Durable continuity"],
          assumptions: [],
          confidenceLabel: "Explicit recovery path",
          freshnessLabel: "Detected just now",
          rollbackLabel: "Navigation only until you act downstream.",
        },
        handoff: null,
        actionContextLabel: "Recovery path",
        recovery: {
          key: "replacement::planning:41",
          kind: "replacement",
          title: "Old launch plan was replaced",
          summary: "Old launch plan was superseded by Launch review queue is ready.",
          nextStep: "Open the replacement workflow and continue from the newer path.",
          ctaLabel: "Open replacement workflow",
          ctaDescription: "Continue from the workflow that replaced the prior path.",
          location: {
            state: "decide",
            recallTool: "chat",
            reviewFocus: "enrichment",
            sessionId: 52,
            loopId: null,
            workingSetId: null,
          },
          acknowledged: false,
        },
        actions: [
          {
            type: "recover",
            label: "Open replacement workflow",
            variant: "primary",
            description: "Continue from the replacement workflow.",
            recoveryKey: "replacement::planning:41",
            recoveryKind: "replacement",
            location: {
              state: "decide",
              recallTool: "chat",
              reviewFocus: "enrichment",
              sessionId: 52,
              loopId: null,
              workingSetId: null,
            },
          },
          {
            type: "acknowledge",
            label: "Acknowledge change",
            variant: "secondary",
            description: "Old launch plan was superseded by Launch review queue is ready.",
            acknowledgementKey: "replacement::planning:41",
          },
        ],
      },
    ];

    const html = renderActionCardDeck(cards, "<p>Empty</p>");

    expect(html).toContain("Old launch plan was replaced");
    expect(html).toContain("Open replacement workflow");
    expect(html).toContain('data-card-action="recover"');
    expect(html).toContain('data-card-action="acknowledge"');
    expect(html).toContain('data-recovery-kind="replacement"');
  });

  it("renders stage, edit, and defer datasets for shared follow-through actions", () => {
    const cards: OperatorActionCard[] = [
      {
        id: "handoff-1",
        kind: "handoff",
        tone: "progress",
        eyebrow: "Recall",
        title: "Stage the next move",
        summary: "Turn a grounded answer into a durable next action.",
        rationale: "Shared follow-through actions keep deterministic work executable across shell-owned surfaces.",
        preview: [{ label: "Answer", value: "Review the duplicate queue first." }],
        trust: {
          contextSources: ["Grounded recall", "Working set"],
          assumptions: ["Execution still remains explicit once the destination surface opens."],
          confidenceLabel: "Follow-through ready",
          freshnessLabel: null,
          rollbackLabel: "Stage and defer only save durable follow-through items.",
        },
        handoff: {
          changeSummary: "This answer can become a durable follow-through item.",
          createdResources: [],
          nextStep: "Stage it now, refine the query, or defer it for later.",
          breadcrumbs: ["Home", "Recall", "Answer result"],
        },
        actions: [
          {
            type: "stage",
            label: "Stage next step",
            variant: "primary",
            description: "Execution brief: Review the duplicate queue first.",
            stageLabel: "Do · Review the duplicate queue first",
            location: {
              state: "do",
              recallTool: "chat",
              reviewFocus: null,
              sessionId: null,
              loopId: null,
              workingSetId: 7,
            },
          },
          {
            type: "edit",
            label: "Edit question",
            variant: "secondary",
            description: "Refine the grounded question behind this answer.",
            query: "What should I do next?",
            location: {
              state: "recall",
              recallTool: "chat",
              reviewFocus: null,
              sessionId: null,
              loopId: null,
              workingSetId: 7,
              query: "What should I do next?",
            },
          },
          {
            type: "defer",
            label: "Defer for later",
            variant: "secondary",
            description: "Execution brief: Review the duplicate queue first.",
            deferLabel: "Do · Review the duplicate queue first",
            location: {
              state: "do",
              recallTool: "chat",
              reviewFocus: null,
              sessionId: null,
              loopId: null,
              workingSetId: 7,
            },
          },
          {
            type: "undo",
            label: "Undo checkpoint",
            variant: "secondary",
            description: "Undo this planning checkpoint.",
            undo: {
              kind: "planning_run",
              sessionId: 12,
              runId: 44,
              checkpointIndex: 1,
              checkpointTitle: "Create queue",
              actionCount: 2,
              bestEffort: false,
            },
            successLocation: {
              state: "plan",
              recallTool: "chat",
              reviewFocus: "planning",
              sessionId: 12,
              loopId: null,
              workingSetId: 7,
            },
          },
          {
            type: "undo",
            label: "Undo working-set change",
            variant: "secondary",
            description: "Restore the previous working-set state.",
            undo: {
              kind: "working_set_event",
              expectedEventId: 91,
              eventType: "reorder",
              workingSetId: 7,
              workingSetName: "Launch reset",
            },
            successLocation: {
              state: "working_set",
              recallTool: "chat",
              reviewFocus: null,
              sessionId: null,
              loopId: null,
              workingSetId: 7,
            },
          },
          {
            type: "rerun",
            label: "Refresh plan",
            variant: "secondary",
            description: "Land back in the saved planning session.",
            rerun: {
              kind: "planning_session",
              sessionId: 12,
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
                summary: "Land back in the saved planning session.",
                location: {
                  state: "plan",
                  recallTool: "chat",
                  reviewFocus: "planning",
                  sessionId: 12,
                  loopId: null,
                  workingSetId: 7,
                },
              },
            },
          },
        ],
      },
    ];

    const html = renderActionCardDeck(cards, "<p>Empty</p>");

    expect(html).toContain('data-card-action="stage"');
    expect(html).toContain('data-stage-label="Do · Review the duplicate queue first"');
    expect(html).toContain('data-card-action="edit"');
    expect(html).toContain('data-edit-query="What should I do next?"');
    expect(html).toContain('data-card-action="defer"');
    expect(html).toContain('data-defer-label="Do · Review the duplicate queue first"');
    expect(html).toContain('data-card-action="undo"');
    expect(html).toContain('data-undo-run-id="44"');
    expect(html).toContain('data-undo-working-set-id="7"');
    expect(html).toContain('data-undo-working-set-name="Launch reset"');
    expect(html).toContain('data-undo-success-state="plan"');
    expect(html).toContain('data-undo-success-state="working_set"');
    expect(html).toContain('data-card-action="rerun"');
    expect(html).toContain('data-rerun-handle="{&quot;kind&quot;:&quot;planning_session&quot;');
    expect(html).toContain("Refresh contract");
    expect(html).toContain("Strict:");
    expect(html).toContain("May vary:");
  });
});
