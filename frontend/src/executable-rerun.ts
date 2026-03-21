/**
 * executable-rerun.ts - Shared rerun and refresh action contracts.
 *
 * Purpose:
 *   Centralize shared rerun and refresh affordances for planning, review, and
 *   recall flows so cards, continuity, and recents reuse one execution model.
 *
 * Responsibilities:
 *   - Build typed rerun actions for planning sessions, saved review sessions,
 *     and recall queries.
 *   - Execute rerun actions through shared HTTP or shell recall hooks.
 *   - Shape landed receipt outcomes after reruns complete.
 *   - Classify stale rerun failures so disabled follow-through actions stay truthful.
 *
 * Scope:
 *   - Frontend-only rerun contract building and execution helpers.
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

function planningRerunContract(
  snapshot: PlanningSessionSnapshotResponse,
  workingSetId: number | null,
): RerunAttemptContract {
  const freshness = snapshot.context_freshness;
  return {
    mode: freshness?.is_stale ? "refresh" : "rerun",
    provenanceLabel: `Planning session: ${snapshot.session.name}`,
    freshnessLabel: freshness?.summary_label ?? `Updated ${snapshot.session.updated_at_utc}`,
    strategySummary: freshness?.is_stale
      ? "Reuse the saved planning session and refresh it against current loop state."
      : "Reuse the saved planning session contract and regenerate the current plan from live state.",
    strictInvariants: [
      "Same planning session identity",
      "Same saved prompt, query, and grounded planning contract",
      "Same planning-session landing surface after the rerun",
    ],
    mayVary: [
      "Checkpoint wording and emphasis",
      "Target ordering when loop state changed",
      "Generation strategy path or alternate selector choice",
    ],
    postRun: {
      summary: "Land back in the saved planning session with refreshed checkpoints, trust metadata, and handoff cues.",
      location: createLocation({
        state: "plan",
        reviewFocus: "planning",
        sessionId: snapshot.session.id,
        workingSetId,
      }),
    },
  };
}

function reviewRerunContract(
  snapshot: RelationshipReviewSessionSnapshotResponse | EnrichmentReviewSessionSnapshotResponse,
  reviewFocus: "relationship" | "enrichment",
  workingSetId: number | null,
): RerunAttemptContract {
  return {
    mode: "refresh",
    provenanceLabel: `${snapshot.session.name} · ${snapshot.session.query}`,
    freshnessLabel: `Updated ${snapshot.session.updated_at_utc}`,
    strategySummary: reviewFocus === "relationship"
      ? "Reuse the saved review query and rebuild the current relationship queue from live similarity state."
      : "Reuse the saved review query and rebuild the current enrichment queue from live suggestions and clarifications.",
    strictInvariants: [
      "Same saved review session identity",
      `Same ${reviewFocus} review kind and saved query`,
      "Same saved-session landing surface after refresh",
    ],
    mayVary: reviewFocus === "relationship"
      ? [
          "Queue size and cursor target",
          "Candidate ordering and similarity scores",
          "Strategy path or alternate selector choice behind refreshed AI metadata",
        ]
      : [
          "Queue size and cursor target",
          "Suggestion ranking or clarification pressure",
          "Strategy path or alternate selector choice behind refreshed AI metadata",
        ],
    postRun: {
      summary: `Land back in the saved ${reviewFocus} queue with refreshed items and trust copy.`,
      location: createLocation({
        state: "decide",
        reviewFocus,
        sessionId: snapshot.session.id,
        workingSetId,
      }),
    },
  };
}

export function buildPlanningRefreshAction(
  snapshot: PlanningSessionSnapshotResponse,
  options: { workingSetId?: number | null; variant?: OperatorActionCardActionVariant } = {},
): OperatorActionCardRerunAction {
  const contract = planningRerunContract(snapshot, options.workingSetId ?? null);
  return {
    type: "rerun",
    label: contract.mode === "refresh" ? "Refresh plan" : "Regenerate plan",
    variant: options.variant ?? "secondary",
    description: contract.postRun.summary,
    rerun: {
      kind: "planning_session",
      sessionId: snapshot.session.id,
      sessionName: snapshot.session.name,
    },
    contract,
  };
}

export function buildReviewSessionRefreshAction(
  input:
    | {
        reviewFocus: "relationship";
        snapshot: RelationshipReviewSessionSnapshotResponse;
        workingSetId?: number | null;
        variant?: OperatorActionCardActionVariant;
      }
    | {
        reviewFocus: "enrichment";
        snapshot: EnrichmentReviewSessionSnapshotResponse;
        workingSetId?: number | null;
        variant?: OperatorActionCardActionVariant;
      },
): OperatorActionCardRerunAction {
  const contract = reviewRerunContract(input.snapshot, input.reviewFocus, input.workingSetId ?? null);
  return {
    type: "rerun",
    label: input.reviewFocus === "relationship" ? "Refresh queue" : "Refresh enrichment",
    variant: input.variant ?? "secondary",
    description: contract.postRun.summary,
    rerun: {
      kind: "review_session",
      reviewFocus: input.reviewFocus,
      sessionId: input.snapshot.session.id,
      sessionName: input.snapshot.session.name,
    },
    contract,
  };
}

export function buildRecallRerunAction(input: {
  recallTool: "chat" | "rag";
  query: string;
  workingSetId: number | null;
  provenanceLabel: string;
  freshnessLabel: string | null;
  strategySummary: string;
  includeLoopContext?: boolean | undefined;
  includeMemoryContext?: boolean | undefined;
  includeRagContext?: boolean | undefined;
  variant?: OperatorActionCardActionVariant;
}): OperatorActionCardRerunAction {
  const contract: RerunAttemptContract = {
    mode: "rerun",
    provenanceLabel: input.provenanceLabel,
    freshnessLabel: input.freshnessLabel,
    strategySummary: input.strategySummary,
    strictInvariants: [
      `Same ${input.recallTool} recall surface`,
      "Same query text",
      "Same working-set scope when it still exists",
    ],
    mayVary: [
      "Retrieved evidence or grounded context mix",
      "Answer wording and emphasis",
      "Generation strategy path or alternate selector choice",
    ],
    postRun: {
      summary: `Land back in Recall with a fresh ${input.recallTool === "chat" ? "grounded answer" : "evidence-backed result"}.`,
      location: createLocation({
        state: "recall",
        recallTool: input.recallTool,
        workingSetId: input.workingSetId,
        query: input.query,
      }),
    },
  };

  return {
    type: "rerun",
    label: input.recallTool === "chat" ? "Rerun answer" : "Refresh evidence",
    variant: input.variant ?? "secondary",
    description: contract.postRun.summary,
    rerun: {
      kind: "recall_query",
      recallTool: input.recallTool,
      query: input.query,
      workingSetId: input.workingSetId,
      includeLoopContext: input.includeLoopContext,
      includeMemoryContext: input.includeMemoryContext,
      includeRagContext: input.includeRagContext,
    },
    contract,
  };
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
  const refreshAction = buildPlanningRefreshAction(snapshot, {
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
  const refreshAction = buildReviewSessionRefreshAction({
    reviewFocus: action.rerun.reviewFocus,
    snapshot: snapshot as RelationshipReviewSessionSnapshotResponse & EnrichmentReviewSessionSnapshotResponse,
    workingSetId: resumeLocation?.workingSetId ?? null,
  } as never);
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
