/**
 * follow-through-adapters.test.ts - Regression tests for shared follow-through adapters.
 *
 * Purpose:
 *   Verify backend-authored review follow-through payloads and durable continuity
 *   payloads land on the same frontend receipt and undo contracts.
 *
 * Responsibilities:
 *   - Assert review follow-through recording reuses one shared receipt path.
 *   - Assert relationship-decision undo handles map consistently for continuity hydration.
 *
 * Scope:
 *   - Pure frontend adapter helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests operate on typed payload fragments only.
 *   - Backend follow-through payloads remain the source of truth for landed review receipts.
 */

import type { ContinuityOutcomeRecordResponse, ReviewFollowThroughResponse } from "./domain";
import { buildFollowThroughReceipt, mapApiDisplayCard, mapApiUndoAction } from "./follow-through-adapters";
import { createLocation } from "./shell-routing";

describe("follow-through-adapters", () => {
  it("builds one shared review receipt entry from backend follow-through payloads", () => {
    const resumeLocation = createLocation({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 17,
      workingSetId: 9,
    });
    const followThrough = {
      display_card: {
        kind: "receipt",
        tone: "progress",
        eyebrow: "Relationship receipt",
        title: "Recorded duplicate decision",
        summary: "Marked loop #11 as a duplicate of loop #8.",
        rationale: "The backend follow-through contract should drive the same receipt card everywhere.",
        preview: [{ label: "Pair", value: "#8 ↔ #11" }],
        trust: {
          generation_label: "Recorded relationship decision",
          generation_tone: "progress",
          context_sources: ["Saved relationship session"],
          assumptions: ["The queue remains resumable after the decision lands."],
          confidence_label: "Recorded exactly once",
          confidence_tone: "progress",
          freshness_label: "Saved just now",
          freshness_tone: "progress",
          rollback_label: "Undo remains available for this relationship decision.",
          rollback_tone: "caution",
          impact_summary: "Removed the pair from the active queue.",
          impact_tone: "progress",
        },
        handoff: null,
        action_context_label: "Continue from here",
        action_warning: null,
      },
      undo_action: {
        label: "Undo decision",
        description: "Restore the relationship pair to the queue.",
        undo: {
          kind: "relationship_decision",
          session_id: 17,
          loop_id: 8,
          candidate_loop_id: 11,
          expected_pair_state: {
            duplicate: { state: "resolved", confidence: 1, source: "human_review" },
            related: null,
          },
          restore_pair_state: {
            duplicate: { state: "active", confidence: 0.82, source: "similarity" },
            related: null,
          },
        },
        requires_confirmation: false,
        confirm_title: null,
        confirm_description: null,
        success_location: null,
      },
      rerun_action: {
        label: "Refresh queue",
        description: "Rebuild the saved relationship queue from live state.",
        rerun: {
          kind: "review_session",
          review_focus: "relationship",
          session_id: 17,
          session_name: "Duplicate review",
        },
        contract: {
          mode: "refresh",
          provenance_label: "Duplicate review · status:open",
          freshness_label: "Updated 2026-03-28T18:30:00Z",
          strategy_summary: "Reuse the saved review session and refresh its queue.",
          strict_invariants: ["Same saved review session identity"],
          may_vary: ["Queue membership and cursor target"],
          post_run: {
            summary: "Land back in the saved relationship queue with refreshed items.",
            location: {
              state: "decide",
              recall_tool: "chat",
              review_focus: "relationship",
              session_id: 17,
              loop_id: null,
              view_id: null,
              memory_id: null,
              working_set_id: 9,
              query: null,
            },
          },
        },
      },
      resume_location: {
        state: "decide",
        recall_tool: "chat",
        review_focus: "relationship",
        session_id: 17,
        loop_id: null,
        view_id: null,
        memory_id: null,
        working_set_id: 9,
        query: null,
      },
      grounded_chat_location: {
        state: "recall",
        recall_tool: "chat",
        review_focus: null,
        session_id: null,
        loop_id: null,
        view_id: null,
        memory_id: null,
        working_set_id: 9,
        query: "What changed after this review outcome?",
        include_loop_context: true,
        include_memory_context: true,
        include_rag_context: false,
      },
      workflow_thread: {
        id: "review:relationship:17",
        kind: "review_session",
        title: "Duplicate review",
        summary: "Relationship review queue",
        parent_outcome_id: null,
      },
    } as unknown as ReviewFollowThroughResponse;

    const receipt = buildFollowThroughReceipt({
      followThrough,
      id: "review-follow-through-17",
      metadata: { source: "review-workspace", sessionId: 17 },
    });

    expect(receipt.card.title).toBe("Recorded duplicate decision");
    expect(receipt.resumeLocation).toEqual(resumeLocation);
    expect(receipt.entry.location).toEqual(resumeLocation);
    expect(receipt.entry.metadata).toEqual({ source: "review-workspace", sessionId: 17 });
    expect(receipt.entry.outcome?.workflowThread).toEqual({
      id: "review:relationship:17",
      kind: "review_session",
      title: "Duplicate review",
      summary: "Relationship review queue",
      parentOutcomeId: null,
    });
    expect(receipt.entry.outcome?.rerunAction?.rerun.kind).toBe("review_session");
    expect(receipt.entry.outcome?.undoAction?.undo.kind).toBe("relationship_decision");
    expect(receipt.entry.outcome?.card.actions.map((action) => action.type)).toEqual([
      "open",
      "pin",
      "open",
      "rerun",
      "undo",
    ]);
    expect(receipt.entry.outcome?.card.actions[2]).toMatchObject({
      type: "open",
      label: "Ask grounded chat",
      location: createLocation({
        state: "recall",
        recallTool: "chat",
        workingSetId: 9,
        query: "What changed after this review outcome?",
        includeLoopContext: true,
        includeMemoryContext: true,
        includeRagContext: false,
      }),
    });
  });

  it("overlays browser-owned working-set scope onto recall follow-through receipts", () => {
    const receipt = buildFollowThroughReceipt({
      followThrough: {
        display_card: {
          kind: "receipt",
          tone: "attention",
          eyebrow: "Recall receipt",
          title: "Evidence answer · launch checklist",
          summary: "The launch checklist lives in docs/launch.md.",
          rationale: "Document answers should reopen the landed result.",
          preview: [{ label: "Question", value: "Where is the launch checklist?" }],
          trust: {
            generation_label: "Recall receipt",
            generation_tone: "attention",
            context_sources: ["Indexed local documents"],
            assumptions: [],
            confidence_label: "1 retrieved source",
            confidence_tone: "attention",
            freshness_label: "Saved just now",
            freshness_tone: "progress",
            rollback_label: "Rerun the same document question to refresh this answer.",
            rollback_tone: "progress",
            impact_summary: "The launch checklist lives in docs/launch.md.",
            impact_tone: "attention",
          },
          handoff: null,
          action_context_label: "Continue from here",
          action_warning: null,
        },
        undo_action: null,
        rerun_action: {
          label: "Refresh evidence",
          description: "Land back in Recall with a fresh evidence-backed result.",
          rerun: {
            kind: "recall_query",
            recall_tool: "rag",
            query: "Where is the launch checklist?",
            working_set_id: null,
            include_loop_context: null,
            include_memory_context: null,
            include_rag_context: true,
          },
          contract: {
            mode: "rerun",
            provenance_label: "Document-backed recall result",
            freshness_label: "1 retrieved source in the prior answer",
            strategy_summary: "Reuse the same document question against the current indexed evidence.",
            strict_invariants: ["Same document recall surface"],
            may_vary: ["Retrieved source set"],
            post_run: {
              summary: "Land back in Recall with a fresh evidence-backed result.",
              location: {
                state: "recall",
                recall_tool: "rag",
                review_focus: null,
                session_id: null,
                loop_id: null,
                view_id: null,
                memory_id: null,
                working_set_id: null,
                query: "Where is the launch checklist?",
              },
            },
          },
        },
        resume_location: {
          state: "recall",
          recall_tool: "rag",
          review_focus: null,
          session_id: null,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: "Where is the launch checklist?",
        },
        grounded_chat_location: null,
        workflow_thread: {
          id: "recall:rag:where is the launch checklist?",
          kind: "recall",
          title: "Evidence answer · launch checklist",
          summary: "The launch checklist lives in docs/launch.md.",
          parent_outcome_id: null,
        },
        working_set_id: null,
      } as unknown as ReviewFollowThroughResponse,
      id: "recall-follow-through-1",
      kind: "recall",
      workingSetIdOverride: 7,
      metadata: { source: "recall-rag" },
    });

    expect(receipt.resumeLocation).toEqual(createLocation({
      state: "recall",
      recallTool: "rag",
      workingSetId: 7,
      query: "Where is the launch checklist?",
    }));
    expect(receipt.entry.outcome?.rerunAction?.rerun).toMatchObject({
      kind: "recall_query",
      recallTool: "rag",
      workingSetId: 7,
      query: "Where is the launch checklist?",
    });
    expect(receipt.entry.metadata).toEqual({ source: "recall-rag" });
  });

  it("records direct-memory follow-through through the shared receipt adapter", () => {
    const receipt = buildFollowThroughReceipt({
      followThrough: {
        display_card: {
          kind: "receipt",
          tone: "progress",
          eyebrow: "Recall receipt",
          title: "Created memory · launch-preference",
          summary: "launch-preference is now available as durable memory.",
          rationale: "Direct-memory mutations should use the backend follow-through contract.",
          preview: [
            { label: "Memory", value: "launch-preference" },
            { label: "Category", value: "preference" },
          ],
          trust: {
            generation_label: "Recall receipt",
            generation_tone: "progress",
            context_sources: ["Direct memory"],
            assumptions: [],
            confidence_label: "Mutation applied",
            confidence_tone: "progress",
            freshness_label: "Saved just now",
            freshness_tone: "progress",
            rollback_label: "Edit or delete the memory entry if this durable context is no longer correct.",
            rollback_tone: "progress",
            impact_summary: "launch-preference is now available as durable memory.",
            impact_tone: "progress",
          },
          handoff: null,
          action_context_label: "Continue from here",
          action_warning: null,
        },
        undo_action: null,
        rerun_action: null,
        resume_location: {
          state: "recall",
          recall_tool: "memory",
          review_focus: null,
          session_id: null,
          loop_id: null,
          view_id: null,
          memory_id: 41,
          working_set_id: 7,
          query: null,
        },
        grounded_chat_location: null,
        workflow_thread: {
          id: "recall:memory:created:41",
          kind: "recall",
          title: "Created memory · launch-preference",
          summary: "launch-preference is now available as durable memory.",
          parent_outcome_id: null,
        },
        working_set_id: 7,
      } as unknown as ReviewFollowThroughResponse,
      id: "memory-follow-through-41",
      kind: "recall",
      metadata: { source: "recall-memory", action: "created" },
    });

    expect(receipt.resumeLocation).toEqual(createLocation({
      state: "recall",
      recallTool: "memory",
      memoryId: 41,
      workingSetId: 7,
    }));
    expect(receipt.entry.outcome?.card.title).toBe("Created memory · launch-preference");
    expect(receipt.entry.metadata).toEqual({ source: "recall-memory", action: "created" });
  });

  it("records ingest follow-through through the shared receipt adapter", () => {
    const receipt = buildFollowThroughReceipt({
      followThrough: {
        display_card: {
          kind: "receipt",
          tone: "attention",
          eyebrow: "Recall receipt",
          title: "Indexed knowledge · launch-notes",
          summary: "Indexed 3 files into 18 chunks with 1 failures.",
          rationale: "Knowledge ingestion should use the backend follow-through contract.",
          preview: [
            { label: "Path", value: "launch-notes" },
            { label: "Files", value: "3" },
            { label: "Chunks", value: "18" },
          ],
          trust: {
            generation_label: "Recall receipt",
            generation_tone: "attention",
            context_sources: ["Indexed local documents"],
            assumptions: [],
            confidence_label: "Mutation applied with follow-up required",
            confidence_tone: "attention",
            freshness_label: "Saved just now",
            freshness_tone: "progress",
            rollback_label: "Reindex with a corrected path or ingestion mode if this document set is not the one you intended.",
            rollback_tone: "progress",
            impact_summary: "Indexed 3 files into 18 chunks with 1 failures.",
            impact_tone: "attention",
          },
          handoff: null,
          action_context_label: "Continue from here",
          action_warning: null,
        },
        undo_action: null,
        rerun_action: null,
        resume_location: {
          state: "recall",
          recall_tool: "rag",
          review_focus: null,
          session_id: null,
          loop_id: null,
          view_id: null,
          memory_id: null,
          working_set_id: null,
          query: "what changed",
        },
        grounded_chat_location: null,
        workflow_thread: {
          id: "recall:rag:ingest:/tmp/launch-notes",
          kind: "recall",
          title: "Indexed knowledge · launch-notes",
          summary: "Indexed 3 files into 18 chunks with 1 failures.",
          parent_outcome_id: null,
        },
        working_set_id: null,
      } as unknown as ReviewFollowThroughResponse,
      id: "rag-ingest-follow-through-1",
      kind: "recall",
      metadata: { source: "recall-rag", action: "ingest" },
      workingSetIdOverride: 5,
    });

    expect(receipt.resumeLocation).toEqual(createLocation({
      state: "recall",
      recallTool: "rag",
      workingSetId: 5,
      query: "what changed",
    }));
    expect(receipt.entry.metadata).toEqual({ source: "recall-rag", action: "ingest" });
  });

  it("fails fast when backend review follow-through omits resume_location", () => {
    expect(() =>
      buildFollowThroughReceipt({
        followThrough: {
          display_card: {
            kind: "receipt",
            tone: "progress",
            eyebrow: "Relationship receipt",
            title: "Recorded duplicate decision",
            summary: "Marked loop #11 as a duplicate of loop #8.",
            rationale: "Receipt",
            preview: [],
            trust: {
              generation_label: null,
              generation_tone: null,
              context_sources: [],
              assumptions: [],
              confidence_label: null,
              confidence_tone: null,
              freshness_label: null,
              freshness_tone: null,
              rollback_label: null,
              rollback_tone: null,
              impact_summary: null,
              impact_tone: null,
            },
            handoff: null,
            action_context_label: null,
            action_warning: null,
          },
          undo_action: null,
          rerun_action: null,
          resume_location: null,
          grounded_chat_location: null,
          workflow_thread: {
            id: "review:relationship:17",
            kind: "review_session",
            title: "Duplicate review",
            summary: null,
            parent_outcome_id: null,
          },
        } as unknown as ReviewFollowThroughResponse,
        id: "review-follow-through-missing-resume-location",
      }),
    ).toThrow("resume_location");
  });

  it("defaults optional planning undo fields through the shared continuity adapter", () => {
    const action = mapApiUndoAction({
      label: "Undo checkpoint",
      description: "Undo the checkpoint and resume planning.",
      undo: {
        kind: "planning_run",
        session_id: 19,
        run_id: 44,
        checkpoint_index: 3,
        checkpoint_title: "Create queue",
      },
      success_location: {
        state: "plan",
        recall_tool: "chat",
        review_focus: "planning",
        session_id: 19,
        loop_id: null,
        view_id: null,
        memory_id: null,
        working_set_id: null,
        query: null,
      },
    } as unknown as ContinuityOutcomeRecordResponse["undo_action"]);

    expect(action).not.toBeNull();
    expect(action).toMatchObject({
      type: "undo",
      label: "Undo checkpoint",
      description: "Undo the checkpoint and resume planning.",
      requiresConfirmation: false,
      undo: {
        kind: "planning_run",
        sessionId: 19,
        runId: 44,
        checkpointIndex: 3,
        checkpointTitle: "Create queue",
        actionCount: 0,
        bestEffort: false,
      },
      successLocation: createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: 19,
      }),
    });
  });

  it("defaults missing working-set handoff counts in display cards", () => {
    const card = mapApiDisplayCard({
      kind: "receipt",
      tone: "progress",
      eyebrow: "Review receipt",
      title: "Created working set",
      summary: "A new working set is ready.",
      rationale: "Receipt",
      preview: [],
      trust: {
        generation_label: null,
        generation_tone: null,
        context_sources: [],
        assumptions: [],
        confidence_label: null,
        confidence_tone: null,
        freshness_label: null,
        freshness_tone: null,
        rollback_label: null,
        rollback_tone: null,
        impact_summary: null,
        impact_tone: null,
      },
      handoff: {
        change_summary: "Created a working set.",
        created_resources: ["Working set"],
        next_step: "Open it.",
        breadcrumbs: ["Home", "Operator"],
        working_set: {
          working_set_id: 7,
          working_set_name: "Hiring loop",
        },
      },
      action_context_label: null,
      action_warning: null,
    } as unknown as ContinuityOutcomeRecordResponse["display_card"]);

    expect(card.handoff?.workingSet).toEqual({
      workingSetId: 7,
      workingSetName: "Hiring loop",
      itemCount: 0,
      missingItemCount: 0,
    });
  });

  it("maps clarification undo handles through the shared continuity adapter", () => {
    const action = mapApiUndoAction({
      label: "Undo answers",
      description: "Restore the saved clarification answers.",
      undo: {
        kind: "clarification_answer",
        loop_id: 19,
        clarification_ids: [11, 7],
      },
      success_location: {
        state: "do",
        recall_tool: "chat",
        review_focus: null,
        session_id: null,
        loop_id: 19,
        view_id: null,
        memory_id: null,
        working_set_id: null,
        query: null,
      },
    } as unknown as ContinuityOutcomeRecordResponse["undo_action"]);

    expect(action).toMatchObject({
      type: "undo",
      label: "Undo answers",
      description: "Restore the saved clarification answers.",
      undo: {
        kind: "clarification_answer",
        loopId: 19,
        clarificationIds: [7, 11],
      },
      successLocation: createLocation({
        state: "do",
        loopId: 19,
      }),
    });
  });

  it("drops malformed clarification undo handles through the shared continuity adapter", () => {
    const action = mapApiUndoAction({
      label: "Undo answers",
      description: "Restore the saved clarification answers.",
      undo: {
        kind: "clarification_answer",
        loop_id: 19,
        clarification_ids: [],
      },
      success_location: {
        state: "do",
        recall_tool: "chat",
        review_focus: null,
        session_id: null,
        loop_id: 19,
        view_id: null,
        memory_id: null,
        working_set_id: null,
        query: null,
      },
    } as unknown as ContinuityOutcomeRecordResponse["undo_action"]);

    expect(action).toBeNull();
  });

  it("drops relationship undo handles with invalid pair-state values", () => {
    const action = mapApiUndoAction({
      label: "Undo decision",
      description: "Restore the relationship pair.",
      undo: {
        kind: "relationship_decision",
        session_id: 17,
        loop_id: 8,
        candidate_loop_id: 11,
        expected_pair_state: {
          duplicate: { state: "bogus", confidence: 1, source: "human_review" },
          related: null,
        },
        restore_pair_state: {
          duplicate: { state: "active", confidence: 0.82, source: "similarity" },
          related: null,
        },
      },
      success_location: {
        state: "decide",
        recall_tool: "chat",
        review_focus: "relationship",
        session_id: 17,
        loop_id: null,
        view_id: null,
        memory_id: null,
        working_set_id: 9,
        query: null,
      },
    } as unknown as ContinuityOutcomeRecordResponse["undo_action"]);

    expect(action).toBeNull();
  });

  it("maps durable relationship undo handles through the shared continuity adapter", () => {
    const action = mapApiUndoAction({
      label: "Undo decision",
      description: "Restore the relationship pair.",
      undo: {
        kind: "relationship_decision",
        session_id: 17,
        loop_id: 8,
        candidate_loop_id: 11,
        expected_pair_state: {
          duplicate: { state: "resolved", confidence: 1, source: "human_review" },
          related: null,
        },
        restore_pair_state: {
          duplicate: { state: "active", confidence: 0.82, source: "similarity" },
          related: null,
        },
      },
      requires_confirmation: true,
      confirm_title: "Undo relationship decision",
      confirm_description: "Restore the pair to the saved queue.",
      success_location: {
        state: "decide",
        recall_tool: "chat",
        review_focus: "relationship",
        session_id: 17,
        loop_id: null,
        view_id: null,
        memory_id: null,
        working_set_id: 9,
        query: null,
      },
    } as unknown as ContinuityOutcomeRecordResponse["undo_action"]);

    expect(action).not.toBeNull();
    expect(action?.undo).toEqual({
      kind: "relationship_decision",
      sessionId: 17,
      loopId: 8,
      candidateLoopId: 11,
      expectedPairState: {
        duplicate: { state: "resolved", confidence: 1, source: "human_review" },
        related: null,
      },
      restorePairState: {
        duplicate: { state: "active", confidence: 0.82, source: "similarity" },
        related: null,
      },
    });
    expect(action?.requiresConfirmation).toBe(true);
    expect(action?.successLocation).toEqual(createLocation({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 17,
      workingSetId: 9,
    }));
  });
});
