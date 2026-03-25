/**
 * executable-rerun.ts - Shared rerun and refresh action contracts.
 *
 * Purpose:
 *   Centralize shared rerun and refresh affordances for planning, review, and
 *   recall flows so cards, continuity, and recents reuse one execution model.
 *
 * Responsibilities:
 *   - Map backend-authored rerun contracts into executable frontend actions.
 *   - Execute rerun actions through shared HTTP or shell recall hooks.
 *   - Shape landed receipt outcomes after reruns complete.
 *   - Classify stale rerun failures so disabled follow-through actions stay truthful.
 *
 * Scope:
 *   - Frontend-only rerun mapping and execution helpers.
 *
 * Usage:
 *   - Imported by action-card builders, shell event wiring, continuity, and the
 *     command palette whenever rerun or refresh follow-through is needed.
 *
 * Invariants/Assumptions:
 *   - Reruns preserve workflow identity and durable scope, not byte-identical AI output.
 *   - Every rerun contract must describe what stays strict and what may vary.
 *   - Recall reruns are delegated back into the shell so existing surface runtimes
 *     remain the source of truth for form submission and rendering.
 */

import { createReceiptCard, withReceiptOutcome } from "./action-receipts";
import type {
  AskResponse,
  ChatResponse,
  ContinuityOutcomeRecordResponse,
  ContinuityWorkflowSummaryResponse,
  EnrichmentReviewSessionSnapshotResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewSessionSnapshotResponse,
} from "./domain";
import { HttpRequestError, requestJson } from "./http";
import { createLocation } from "./shell-routing";
import type {
  OperatorActionCard,
  OperatorActionCardActionVariant,
  OperatorActionCardRerunAction,
  RecallQueryRerunHandle,
  RerunAttemptContract,
  ShellLocationContract,
  TrustSurfaceMetadata,
  ExecutableRerunHandle,
} from "./contracts-ui";

export interface ExecutedRerunResult {
  card: OperatorActionCard;
  entry: ReturnType<typeof withReceiptOutcome>;
  resumeLocation: ShellLocationContract | null;
}

export interface ExecuteRerunDependencies {
  rerunRecallQuery: (handle: RecallQueryRerunHandle) => Promise<void>;
}

function rerunTrust(
  contract: RerunAttemptContract,
  overrides: Partial<TrustSurfaceMetadata> = {},
): TrustSurfaceMetadata {
  return {
    generationLabel: overrides.generationLabel
      ?? (contract.mode === "refresh" ? "Shared refresh affordance" : "Shared rerun affordance"),
    generationTone: overrides.generationTone ?? "attention",
    contextSources: overrides.contextSources ?? [contract.provenanceLabel],
    assumptions: overrides.assumptions ?? [
      ...contract.strictInvariants.map((item) => `Strict: ${item}`),
      ...contract.mayVary.map((item) => `May vary: ${item}`),
    ],
    confidenceLabel: overrides.confidenceLabel ?? contract.strategySummary,
    confidenceTone: overrides.confidenceTone ?? "neutral",
    freshnessLabel: overrides.freshnessLabel ?? contract.freshnessLabel,
    freshnessTone: overrides.freshnessTone ?? "attention",
    rollbackLabel: overrides.rollbackLabel
      ?? "Rerunning preserves the workflow contract, not exact wording, ranking, or evidence order.",
    rollbackTone: overrides.rollbackTone ?? "neutral",
    impactSummary: overrides.impactSummary ?? contract.postRun.summary,
    impactTone: overrides.impactTone ?? "attention",
  };
}

type ApiRerunAction =
  | PlanningSessionSnapshotResponse["rerun_action"]
  | RelationshipReviewSessionSnapshotResponse["rerun_action"]
  | EnrichmentReviewSessionSnapshotResponse["rerun_action"]
  | ContinuityOutcomeRecordResponse["rerun_action"]
  | ContinuityWorkflowSummaryResponse["rerun_action"]
  | ChatResponse["rerun_action"]
  | AskResponse["rerun_action"]
  | null
  | undefined;

function withWorkingSetLocation(
  location: ShellLocationContract | null,
  workingSetId: number | null | undefined,
): ShellLocationContract | null {
  return location && workingSetId != null ? { ...location, workingSetId } : location;
}

export function mapApiRerunAction(
  action: ApiRerunAction,
  options: { workingSetId?: number | null; variant?: OperatorActionCardActionVariant } = {},
): OperatorActionCardRerunAction | null {
  if (!action) {
    return null;
  }

  let rerun: ExecutableRerunHandle | null = null;
  if (action.rerun.kind === "planning_session") {
    rerun = {
      kind: "planning_session",
      sessionId: action.rerun.session_id,
      sessionName: action.rerun.session_name,
    };
  } else if (action.rerun.kind === "review_session") {
    rerun = {
      kind: "review_session",
      reviewFocus: action.rerun.review_focus,
      sessionId: action.rerun.session_id,
      sessionName: action.rerun.session_name,
    };
  } else if (action.rerun.kind === "recall_query") {
    rerun = {
      kind: "recall_query",
      recallTool: action.rerun.recall_tool,
      query: action.rerun.query,
      workingSetId: action.rerun.working_set_id ?? options.workingSetId ?? null,
      includeLoopContext: action.rerun.include_loop_context ?? undefined,
      includeMemoryContext: action.rerun.include_memory_context ?? undefined,
      includeRagContext: action.rerun.include_rag_context ?? undefined,
    };
  }
  if (!rerun) {
    return null;
  }

  return {
    type: "rerun",
    label: action.label,
    variant: options.variant ?? "secondary",
    description: action.description,
    rerun,
    contract: {
      mode: action.contract.mode,
      provenanceLabel: action.contract.provenance_label,
      freshnessLabel: action.contract.freshness_label ?? null,
      strategySummary: action.contract.strategy_summary,
      strictInvariants: action.contract.strict_invariants ?? [],
      mayVary: action.contract.may_vary ?? [],
      postRun: {
        summary: action.contract.post_run.summary,
        location: withWorkingSetLocation(
          action.contract.post_run.location
            ? createLocation({
                state: action.contract.post_run.location.state,
                recallTool: action.contract.post_run.location.recall_tool,
                reviewFocus: action.contract.post_run.location.review_focus,
                sessionId: action.contract.post_run.location.session_id,
                loopId: action.contract.post_run.location.loop_id,
                viewId: action.contract.post_run.location.view_id,
                memoryId: action.contract.post_run.location.memory_id,
                workingSetId: action.contract.post_run.location.working_set_id,
                query: action.contract.post_run.location.query,
              })
            : null,
          options.workingSetId,
        ),
      },
    },
  };
}

export function requireApiRerunAction(
  action: ApiRerunAction,
  options: {
    sourceLabel: string;
    workingSetId?: number | null;
    variant?: OperatorActionCardActionVariant;
  },
): OperatorActionCardRerunAction {
  const rerunAction = mapApiRerunAction(action, options);
  if (!rerunAction) {
    throw new Error(`${options.sourceLabel} is missing rerun_action.`);
  }
  return rerunAction;
}

export function rerunHandleIdentity(handle: ExecutableRerunHandle): string {
  switch (handle.kind) {
    case "planning_session":
      return `planning:${handle.sessionId}`;
    case "review_session":
      return `review:${handle.reviewFocus}:${handle.sessionId}`;
    case "recall_query":
      return `recall:${handle.recallTool}:${handle.workingSetId ?? "none"}:${handle.query.trim().toLowerCase()}`;
  }
}

function planningRefreshReceipt(snapshot: PlanningSessionSnapshotResponse, action: OperatorActionCardRerunAction): ExecutedRerunResult {
  const resumeLocation = action.contract.postRun.location;
  const refreshAction = requireApiRerunAction(snapshot.rerun_action, {
    sourceLabel: `Planning session ${snapshot.session.name}`,
    workingSetId: resumeLocation?.workingSetId ?? null,
  });
  const title = action.contract.mode === "refresh"
    ? `Refreshed ${snapshot.session.name}`
    : `Regenerated ${snapshot.session.name}`;
  const summary = snapshot.plan_summary?.trim()
    || action.contract.postRun.summary;
  const card = createReceiptCard({
    id: `planning-rerun-${snapshot.session.id}-${Date.now()}`,
    eyebrow: action.contract.mode === "refresh" ? "Planning refresh" : "Planning rerun",
    title,
    summary,
    rationale:
      "Shared planning rerun receipts keep refreshed plan state resumable without re-deriving what stayed strict versus what may change.",
    tone: "progress",
    preview: [
      { label: "Session", value: snapshot.session.name },
      { label: "Status", value: snapshot.session.status.replaceAll("_", " ") },
      { label: "Checkpoints", value: `${snapshot.session.checkpoint_count}` },
      { label: "Targets", value: `${snapshot.target_loops?.length ?? 0}` },
    ],
    trust: rerunTrust(action.contract, {
      contextSources: [
        action.contract.provenanceLabel,
        `${snapshot.target_loops?.length ?? 0} target loop${(snapshot.target_loops?.length ?? 0) === 1 ? "" : "s"}`,
      ],
      confidenceLabel: title,
      freshnessLabel: snapshot.context_freshness?.summary_label ?? `Updated ${snapshot.session.updated_at_utc}`,
      impactSummary: summary,
    }),
    handoff: {
      changeSummary: summary,
      createdResources: [],
      nextStep: "Inspect the refreshed checkpoints before executing the next step.",
      breadcrumbs: ["Home", "Plan", snapshot.session.name],
    },
    resumeLocation,
    resumeLabel: "Open refreshed plan",
    resumeDescription: summary,
    pinLabel: `Plan · ${snapshot.session.name}`,
    actions: [refreshAction],
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: "planning",
        label: title,
        description: summary,
        location: resumeLocation,
      },
      card,
      resumeLocation,
      {
        workflowThread: {
          id: `planning:${snapshot.session.id}`,
          kind: "planning_checkpoint",
          title: snapshot.session.name,
          summary,
          parentOutcomeId: null,
        },
      },
    ),
  };
}

function reviewRefreshReceipt(
  snapshot: RelationshipReviewSessionSnapshotResponse | EnrichmentReviewSessionSnapshotResponse,
  action: OperatorActionCardRerunAction,
): ExecutedRerunResult {
  if (action.rerun.kind !== "review_session") {
    throw new Error("Expected a saved review-session rerun handle.");
  }
  const resumeLocation = action.contract.postRun.location;
  const refreshAction = requireApiRerunAction(snapshot.rerun_action, {
    sourceLabel: `Saved ${action.rerun.reviewFocus} review session ${snapshot.session.name}`,
    workingSetId: resumeLocation?.workingSetId ?? null,
  });
  const title = `Refreshed ${snapshot.session.name}`;
  const summary = action.rerun.reviewFocus === "relationship"
    ? `Relationship queue rebuilt with ${snapshot.loop_count} queued item${snapshot.loop_count === 1 ? "" : "s"}.`
    : `Enrichment queue rebuilt with ${snapshot.loop_count} queued item${snapshot.loop_count === 1 ? "" : "s"}.`;
  const card = createReceiptCard({
    id: `review-rerun-${action.rerun.reviewFocus}-${snapshot.session.id}-${Date.now()}`,
    eyebrow: "Review refresh",
    title,
    summary,
    rationale:
      "Shared review-session refresh receipts keep queue regeneration resumable without hiding what may change between AI attempts.",
    tone: "progress",
    preview: [
      { label: "Session", value: snapshot.session.name },
      { label: "Kind", value: action.rerun.reviewFocus },
      { label: "Queue size", value: `${snapshot.loop_count}` },
      { label: "Updated", value: snapshot.session.updated_at_utc },
    ],
    trust: rerunTrust(action.contract, {
      contextSources: [
        action.contract.provenanceLabel,
        `Saved ${action.rerun.reviewFocus} review session`,
      ],
      confidenceLabel: title,
      freshnessLabel: `Updated ${snapshot.session.updated_at_utc}`,
      impactSummary: summary,
    }),
    handoff: {
      changeSummary: summary,
      createdResources: [],
      nextStep: action.rerun.reviewFocus === "relationship"
        ? "Resume the queue and confirm or dismiss the new top candidate."
        : "Resume the queue and review the refreshed suggestion or clarification state.",
      breadcrumbs: ["Home", "Decide", snapshot.session.name],
    },
    resumeLocation,
    resumeLabel: "Open refreshed queue",
    resumeDescription: summary,
    pinLabel: `Decide · ${snapshot.session.name}`,
    actions: [refreshAction],
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: "review",
        label: title,
        description: summary,
        location: resumeLocation,
      },
      card,
      resumeLocation,
      {
        workflowThread: {
          id: `review:${action.rerun.reviewFocus}:${snapshot.session.id}`,
          kind: "review_session",
          title: snapshot.session.name,
          summary,
          parentOutcomeId: null,
        },
      },
    ),
  };
}

function recallRerunReceipt(action: OperatorActionCardRerunAction): ExecutedRerunResult {
  const resumeLocation = action.contract.postRun.location;
  const title = action.rerun.kind === "recall_query" && action.rerun.recallTool === "chat"
    ? "Reran grounded answer"
    : "Refreshed evidence answer";
  const summary = action.contract.postRun.summary;
  const card = createReceiptCard({
    id: `recall-rerun-${Date.now()}`,
    eyebrow: action.contract.mode === "refresh" ? "Recall refresh" : "Recall rerun",
    title,
    summary,
    rationale:
      "Shared recall rerun receipts keep grounded answer refreshes resumable from cards, continuity, and palette recents.",
    tone: "progress",
    preview: action.rerun.kind === "recall_query"
      ? [
          { label: "Tool", value: action.rerun.recallTool },
          { label: "Query", value: action.rerun.query },
        ]
      : [],
    trust: rerunTrust(action.contract, {
      contextSources: [action.contract.provenanceLabel],
      confidenceLabel: title,
      impactSummary: summary,
    }),
    handoff: {
      changeSummary: summary,
      createdResources: [],
      nextStep: "Inspect the fresh recall result and decide whether to act, edit, or defer it.",
      breadcrumbs: ["Home", "Recall", action.rerun.kind === "recall_query" ? action.rerun.recallTool : "chat"],
    },
    resumeLocation,
    resumeLabel: "Open rerun result",
    resumeDescription: summary,
    pinLabel: action.rerun.kind === "recall_query"
      ? `Recall · ${action.rerun.recallTool} · ${action.rerun.query.slice(0, 32)}`
      : "Recall rerun",
    actions: [action],
  });

  return {
    card,
    resumeLocation,
    entry: withReceiptOutcome(
      {
        kind: "recall",
        label: title,
        description: summary,
        location: resumeLocation,
      },
      card,
      resumeLocation,
      {
        workflowThread: action.rerun.kind === "recall_query"
          ? {
              id: `recall:${action.rerun.recallTool}:${action.rerun.query.trim().toLowerCase()}`,
              kind: "recall",
              title,
              summary,
              parentOutcomeId: null,
            }
          : null,
      },
    ),
  };
}

export async function executeRerunAction(
  action: OperatorActionCardRerunAction,
  deps: ExecuteRerunDependencies,
): Promise<ExecutedRerunResult> {
  switch (action.rerun.kind) {
    case "planning_session": {
      const snapshot = await requestJson<PlanningSessionSnapshotResponse>(
        `/loops/planning/sessions/${action.rerun.sessionId}/refresh`,
        { method: "POST" },
        "Failed to refresh planning session",
      );
      return planningRefreshReceipt(snapshot, action);
    }
    case "review_session": {
      const path = action.rerun.reviewFocus === "relationship" ? "relationship" : "enrichment";
      const snapshot = await requestJson<
        RelationshipReviewSessionSnapshotResponse | EnrichmentReviewSessionSnapshotResponse
      >(
        `/loops/review/${path}/sessions/${action.rerun.sessionId}/refresh`,
        { method: "POST" },
        `Failed to refresh ${path} review session`,
      );
      return reviewRefreshReceipt(snapshot, action);
    }
    case "recall_query": {
      await deps.rerunRecallQuery(action.rerun);
      return recallRerunReceipt(action);
    }
  }
}

export function staleRerunReason(error: unknown): string | null {
  if (error instanceof HttpRequestError) {
    if (error.status === 404) {
      return "This rerun target is no longer available.";
    }
    if (error.status === 400 && /not found|missing|no longer available/i.test(error.message)) {
      return error.message;
    }
  }
  return error instanceof Error && /not found|no longer available/i.test(error.message)
    ? error.message
    : null;
}
