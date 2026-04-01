/**
 * follow-through-adapters.ts - Shared API-to-receipt adapters for review and continuity flows.
 *
 * Purpose:
 *   Convert backend-authored follow-through and continuity payloads into the
 *   shared frontend card, undo, rerun, and recent-action contracts.
 *
 * Responsibilities:
 *   - Map backend location, workflow-thread, display-card, and undo payloads.
 *   - Build one receipt outcome path for backend-authored landed `follow_through` payloads.
 *   - Keep immediate review and recall receipts aligned with durable continuity hydration.
 *
 * Scope:
 *   - Frontend-only adapter helpers for landed outcomes and follow-through.
 *
 * Usage:
 *   - Imported by review workspace, continuity intelligence, and executable undo
 *     flows whenever backend follow-through or continuity outcomes need to land
 *     as shared operator cards.
 *
 * Invariants/Assumptions:
 *   - Backend follow-through and continuity payloads already describe landed work.
 *   - Undo handles remain exact and backend-authored; adapters never infer them.
 *   - Rerun handles stay backend-authored and reuse the shared rerun adapter.
 */

import { createReceiptCardFromDisplayCard, withReceiptOutcome } from "./action-receipts";
import type {
  ContinuityLocationResponse,
  ContinuityOutcomeRecordResponse,
  ContinuityWorkflowSummaryResponse,
  ReviewFollowThroughResponse,
} from "./domain";
import type {
  ContinuityCardDisplay,
  ExecutableUndoHandle,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardRerunAction,
  OperatorActionCardUndoAction,
  RecentShellActionEntry,
  RelationshipDecisionState,
  ShellLocationContract,
  WorkflowThreadRef,
} from "./contracts-ui";
import { mapApiRerunAction } from "./executable-rerun";
import { createLocation } from "./shell-routing";

type ApiLocation = ContinuityLocationResponse | ReviewFollowThroughResponse["resume_location"];
type ApiWorkflowThread =
  | ContinuityOutcomeRecordResponse["workflow_thread"]
  | ReviewFollowThroughResponse["workflow_thread"];
type ApiDisplayCard =
  | ContinuityOutcomeRecordResponse["display_card"]
  | ContinuityWorkflowSummaryResponse["display_card"]
  | ReviewFollowThroughResponse["display_card"];
type ApiUndoAction =
  | ContinuityOutcomeRecordResponse["undo_action"]
  | ContinuityWorkflowSummaryResponse["undo_action"]
  | ReviewFollowThroughResponse["undo_action"]
  | null
  | undefined;

export interface FollowThroughReceiptResult {
  card: OperatorActionCard;
  entry: Omit<RecentShellActionEntry, "occurredAt">;
  resumeLocation: ShellLocationContract | null;
  workflowThread: WorkflowThreadRef;
  undoAction: OperatorActionCardUndoAction | null;
  rerunAction: OperatorActionCardRerunAction | null;
}

export function mapApiLocation(location: ApiLocation | null | undefined): ShellLocationContract | null {
  if (!location) {
    return null;
  }
  return createLocation({
    state: location.state,
    recallTool: location.recall_tool,
    reviewFocus: location.review_focus ?? null,
    sessionId: location.session_id ?? null,
    loopId: location.loop_id ?? null,
    viewId: location.view_id ?? null,
    memoryId: location.memory_id ?? null,
    workingSetId: location.working_set_id ?? null,
    query: location.query ?? null,
    includeLoopContext: location.include_loop_context ?? null,
    includeMemoryContext: location.include_memory_context ?? null,
    includeRagContext: location.include_rag_context ?? null,
  });
}

export function mapApiWorkflowThread(thread: ApiWorkflowThread): WorkflowThreadRef {
  return {
    id: thread.id,
    kind: thread.kind,
    title: thread.title,
    summary: thread.summary ?? null,
    parentOutcomeId: thread.parent_outcome_id ?? null,
  };
}

export function mapApiDisplayCard(response: ApiDisplayCard): ContinuityCardDisplay {
  return {
    kind: response.kind,
    tone: response.tone,
    eyebrow: response.eyebrow,
    title: response.title,
    summary: response.summary,
    rationale: response.rationale,
    preview: (response.preview ?? []).map((item) => ({
      label: item.label,
      value: item.value,
    })),
    trust: {
      generationLabel: response.trust.generation_label ?? null,
      generationTone: response.trust.generation_tone ?? null,
      contextSources: response.trust.context_sources ?? [],
      assumptions: response.trust.assumptions ?? [],
      confidenceLabel: response.trust.confidence_label ?? null,
      confidenceTone: response.trust.confidence_tone ?? null,
      freshnessLabel: response.trust.freshness_label ?? null,
      freshnessTone: response.trust.freshness_tone ?? null,
      rollbackLabel: response.trust.rollback_label ?? null,
      rollbackTone: response.trust.rollback_tone ?? null,
      impactSummary: response.trust.impact_summary ?? null,
      impactTone: response.trust.impact_tone ?? null,
    },
    handoff: response.handoff
      ? {
          changeSummary: response.handoff.change_summary,
          createdResources: response.handoff.created_resources ?? [],
          nextStep: response.handoff.next_step ?? null,
          breadcrumbs: response.handoff.breadcrumbs ?? [],
          workingSet: response.handoff.working_set
            ? {
                workingSetId: response.handoff.working_set.working_set_id,
                workingSetName: response.handoff.working_set.working_set_name,
                itemCount: response.handoff.working_set.item_count ?? 0,
                missingItemCount: response.handoff.working_set.missing_item_count ?? 0,
              }
            : null,
        }
      : null,
    actionContextLabel: response.action_context_label ?? null,
    actionWarning: response.action_warning ?? null,
  };
}

function normalizePositiveIntegerIds(values: readonly number[]): number[] {
  return Array.from(new Set(values.filter((value) => Number.isInteger(value) && value > 0))).sort((left, right) => left - right);
}

function isRelationshipDecisionState(
  value: unknown,
): value is RelationshipDecisionState["state"] {
  return value === "active" || value === "dismissed" || value === "resolved";
}

function mapPairState(
  response:
    | { state: RelationshipDecisionState["state"]; confidence?: number | null; source?: string | null }
    | null
    | undefined,
): RelationshipDecisionState | null {
  if (!response) {
    return null;
  }
  if (!isRelationshipDecisionState(response.state)) {
    return null;
  }
  return {
    state: response.state,
    confidence: response.confidence ?? null,
    source: response.source ?? null,
  };
}

function pairStatePayloadIsValid(
  payload:
    | { duplicate?: { state: unknown } | null; related?: { state: unknown } | null }
    | null
    | undefined,
): boolean {
  if (!payload) {
    return true;
  }
  for (const candidate of [payload.duplicate, payload.related]) {
    if (candidate == null) {
      continue;
    }
    if (!isRelationshipDecisionState(candidate.state)) {
      return false;
    }
  }
  return true;
}

export function mapApiUndoAction(action: ApiUndoAction): OperatorActionCardUndoAction | null {
  if (!action) {
    return null;
  }
  let undo: ExecutableUndoHandle | null = null;
  if (action.undo.kind === "loop_event") {
    undo = {
      kind: "loop_event",
      loopId: action.undo.loop_id,
      expectedEventId: action.undo.expected_event_id,
      eventType: action.undo.event_type ?? null,
      claimToken: action.undo.claim_token ?? null,
    };
  } else if (action.undo.kind === "planning_run") {
    undo = {
      kind: "planning_run",
      sessionId: action.undo.session_id,
      runId: action.undo.run_id,
      checkpointIndex: action.undo.checkpoint_index,
      checkpointTitle: action.undo.checkpoint_title,
      actionCount: action.undo.action_count ?? 0,
      bestEffort: action.undo.best_effort === true,
    };
  } else if (action.undo.kind === "working_set_event") {
    undo = {
      kind: "working_set_event",
      expectedEventId: action.undo.expected_event_id,
      eventType: action.undo.event_type ?? null,
      workingSetId: action.undo.working_set_id ?? null,
      workingSetName: action.undo.working_set_name ?? null,
    };
  } else if (action.undo.kind === "clarification_answer") {
    const clarificationIds = normalizePositiveIntegerIds(
      Array.isArray(action.undo.clarification_ids)
        ? action.undo.clarification_ids.filter(
            (clarificationId): clarificationId is number => Number.isInteger(clarificationId) && clarificationId > 0,
          )
        : [],
    );
    if (clarificationIds.length > 0) {
      undo = {
        kind: "clarification_answer",
        loopId: action.undo.loop_id,
        clarificationIds,
      };
    }
  } else if (action.undo.kind === "relationship_decision") {
    const expectedPairState = action.undo.expected_pair_state ?? { duplicate: null, related: null };
    const restorePairState = action.undo.restore_pair_state ?? { duplicate: null, related: null };
    if (pairStatePayloadIsValid(expectedPairState) && pairStatePayloadIsValid(restorePairState)) {
      undo = {
        kind: "relationship_decision",
        sessionId: action.undo.session_id,
        loopId: action.undo.loop_id,
        candidateLoopId: action.undo.candidate_loop_id,
        expectedPairState: {
          duplicate: mapPairState(expectedPairState.duplicate),
          related: mapPairState(expectedPairState.related),
        },
        restorePairState: {
          duplicate: mapPairState(restorePairState.duplicate),
          related: mapPairState(restorePairState.related),
        },
      };
    }
  }
  if (!undo) {
    return null;
  }
  return {
    type: "undo",
    label: action.label,
    variant: "secondary",
    description: action.description,
    undo,
    requiresConfirmation: action.requires_confirmation === true,
    confirmTitle: action.confirm_title ?? null,
    confirmDescription: action.confirm_description ?? null,
    successLocation: mapApiLocation(action.success_location),
  };
}

export function buildFollowThroughActions(input: {
  groundedChatLocation: ShellLocationContract | null;
  undoAction: OperatorActionCardUndoAction | null | undefined;
  rerunAction: OperatorActionCardRerunAction | null | undefined;
}): OperatorActionCardAction[] {
  const actions: OperatorActionCardAction[] = [];
  if (input.groundedChatLocation) {
    actions.push({
      type: "open",
      label: "Ask grounded chat",
      variant: "secondary",
      description: "Open grounded chat with the landed review context preserved.",
      location: input.groundedChatLocation,
    });
  }
  if (input.rerunAction) {
    actions.push(input.rerunAction);
  }
  if (input.undoAction) {
    actions.push(input.undoAction);
  }
  return actions;
}

function withWorkingSetLocation(
  location: ShellLocationContract | null,
  workingSetId: number | null | undefined,
): ShellLocationContract | null {
  return location && workingSetId != null ? { ...location, workingSetId } : location;
}

function requireFollowThroughResumeLocation(
  location: ReviewFollowThroughResponse["resume_location"] | null | undefined,
  workingSetId: number | null | undefined,
): ShellLocationContract {
  const mapped = withWorkingSetLocation(mapApiLocation(location), workingSetId);
  if (!mapped) {
    throw new Error("follow_through.resume_location is required");
  }
  return mapped;
}

export function buildFollowThroughReceipt(input: {
  followThrough: ReviewFollowThroughResponse;
  id: string;
  label?: string;
  description?: string;
  kind?: RecentShellActionEntry["kind"];
  metadata?: Record<string, unknown> | null;
  workingSetIdOverride?: number | null;
}): FollowThroughReceiptResult {
  const workingSetId = input.workingSetIdOverride ?? input.followThrough.working_set_id ?? null;
  const displayCard = mapApiDisplayCard(input.followThrough.display_card);
  const resumeLocation = requireFollowThroughResumeLocation(
    input.followThrough.resume_location,
    workingSetId,
  );
  const workflowThread = mapApiWorkflowThread(input.followThrough.workflow_thread);
  const groundedChatLocation = withWorkingSetLocation(
    mapApiLocation(input.followThrough.grounded_chat_location),
    workingSetId,
  );
  const undoAction = mapApiUndoAction(input.followThrough.undo_action);
  const rerunAction = mapApiRerunAction(input.followThrough.rerun_action, { workingSetId });
  const description = input.description ?? displayCard.summary;
  const label = input.label ?? displayCard.title;
  const card = createReceiptCardFromDisplayCard({
    id: input.id,
    displayCard,
    resumeLocation,
    resumeDescription: description,
    pinLabel: displayCard.title,
    actions: buildFollowThroughActions({ groundedChatLocation, undoAction, rerunAction }),
  });
  return {
    card,
    entry: withReceiptOutcome(
      {
        kind: input.kind ?? "review",
        label,
        description,
        location: resumeLocation,
        metadata: input.metadata ?? null,
      },
      card,
      resumeLocation,
      { workflowThread },
    ),
    resumeLocation,
    workflowThread,
    undoAction,
    rerunAction,
  };
}
