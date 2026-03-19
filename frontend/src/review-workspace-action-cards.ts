/**
 * review-workspace-action-cards.ts - Shared action-card builders for review flows.
 *
 * Purpose:
 *   Convert planning, relationship, enrichment, and hygiene review state into
 *   the canonical operator action-card model used across the frontend.
 *
 * Responsibilities:
 *   - Build planning execution, launch-surface, and follow-up cards.
 *   - Build review decision cards for relationship, enrichment, and hygiene.
 *   - Keep review-local event actions declarative so existing handlers can own
 *     the actual mutations.
 *
 * Scope:
 *   - Pure card-shaping helpers only; no DOM access or network requests.
 *
 * Usage:
 *   - Imported by `frontend/src/review-workspace.ts`.
 *
 * Invariants/Assumptions:
 *   - Navigation remains encoded through shared shell locations.
 *   - Review mutations remain encoded through `data-review-action` attributes.
 *   - Working-set metadata is resolved from caller-provided context only.
 */

import type {
  OperatorActionCard,
  OperatorActionCardAction,
  ShellLocationContract,
  TrustSurfaceMetadata,
} from "./contracts-ui";
import type {
  EnrichmentReviewActionResponse,
  EnrichmentReviewQueueItemResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopReviewCohortResponse,
  PlanningExecutionFollowUpResourceResponse,
  PlanningExecutionHistoryItemResponse,
  PlanningExecutionLaunchSurfaceResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewActionResponse,
  RelationshipReviewCandidateResponse,
  RelationshipReviewSessionSnapshotResponse,
} from "./domain";
import {
  buildFollowUpResourceHandoff,
  buildLaunchSurfaceHandoff,
  launchSurfaceWorkingSetId,
  resolveWorkingSetSessionMetadata,
  type ReviewWorkspaceHandoffContext,
} from "./review-workspace-handoffs";
import { createLocation } from "./shell-routing";
import { loopTitle } from "./shell-core";

function openAction(
  label: string,
  location: ShellLocationContract,
  description: string,
  variant: OperatorActionCardAction["variant"] = "primary",
): OperatorActionCardAction {
  return {
    type: "open",
    label,
    variant,
    location,
    description,
  };
}

function pinAction(
  label: string,
  location: ShellLocationContract,
  description: string,
  pinLabel: string,
): OperatorActionCardAction {
  return {
    type: "pin",
    label,
    variant: "secondary",
    location,
    description,
    pinLabel,
  };
}

function eventAction(
  label: string,
  description: string,
  attributes: Record<string, string>,
  variant: OperatorActionCardAction["variant"] = "primary",
): OperatorActionCardAction {
  return {
    type: "event",
    label,
    variant,
    description,
    attributes,
  };
}

function eventActionWithIntegerAttributes(
  label: string,
  description: string,
  attributes: Record<string, string | number>,
  variant: OperatorActionCardAction["variant"] = "primary",
): OperatorActionCardAction {
  return eventAction(
    label,
    description,
    Object.fromEntries(Object.entries(attributes).map(([key, value]) => [key, String(value)])),
    variant,
  );
}

function workingSetHandoff(context: ReviewWorkspaceHandoffContext) {
  return resolveWorkingSetSessionMetadata(context.workingSets, context.fallbackWorkingSetId);
}

function launchSurfaceToLocation(
  surface: PlanningExecutionLaunchSurfaceResponse,
  fallbackWorkingSetId: number | null,
): ShellLocationContract | null {
  const web = surface.web && typeof surface.web === "object"
    ? surface.web as Record<string, unknown>
    : null;
  const reviewKind = typeof web?.["review_kind"] === "string" ? web["review_kind"] : null;
  const sessionId = typeof web?.["session_id"] === "number" ? web["session_id"] : null;
  const workingSetId = launchSurfaceWorkingSetId(surface, fallbackWorkingSetId);

  if (web?.["surface"] === "review_session" && reviewKind === "relationship") {
    return createLocation({ state: "decide", reviewFocus: "relationship", sessionId, workingSetId });
  }
  if (web?.["surface"] === "review_session" && reviewKind === "enrichment") {
    return createLocation({ state: "decide", reviewFocus: "enrichment", sessionId, workingSetId });
  }
  return null;
}

function suggestionEntries(
  suggestion: EnrichmentReviewQueueItemResponse["pending_suggestions"][number],
): Array<[string, string]> {
  const parsed = typeof suggestion.parsed === "object" && suggestion.parsed ? suggestion.parsed : {};
  return Object.entries(parsed).flatMap(([key, value]) => {
    if (["confidence", "needs_clarification"].includes(key) || value == null || value === "") {
      return [];
    }
    return [[key.replaceAll("_", " "), Array.isArray(value) ? value.join(", ") : String(value)]];
  });
}

function suggestionTitle(
  suggestion: EnrichmentReviewQueueItemResponse["pending_suggestions"][number],
): string {
  const parsed = typeof suggestion.parsed === "object" && suggestion.parsed ? suggestion.parsed : {};
  return String((parsed["title"] as string | undefined) || (parsed["summary"] as string | undefined) || "Pending suggestion");
}

function describeQueueProgress(currentIndex: number | null | undefined, total: number): string {
  if (!Number.isInteger(total) || total <= 0) {
    return `0/${Math.max(0, total)}`;
  }
  if (currentIndex == null || !Number.isInteger(currentIndex)) {
    return `0/${total}`;
  }
  return `${Math.min(total, currentIndex + 1)}/${total}`;
}

export function buildPlanningExecutionSummaryCard(
  snapshot: PlanningSessionSnapshotResponse,
  latestExecution: PlanningExecutionHistoryItemResponse,
  trust: TrustSurfaceMetadata,
  context: ReviewWorkspaceHandoffContext & { sessionName: string },
): OperatorActionCard {
  const planLocation = createLocation({
    state: "plan",
    reviewFocus: "planning",
    sessionId: snapshot.session.id,
    workingSetId: context.fallbackWorkingSetId,
  });
  const primarySurface = (latestExecution.launch_surfaces ?? []).find((surface) => launchSurfaceToLocation(surface, context.fallbackWorkingSetId) != null) ?? null;
  const primaryLocation = primarySurface
    ? (launchSurfaceToLocation(primarySurface, context.fallbackWorkingSetId) ?? planLocation)
    : planLocation;

  return {
    id: `review-plan-impact-${snapshot.session.id}-${latestExecution.checkpoint_index}`,
    kind: latestExecution.launch_surfaces?.length ? "handoff" : "context",
    tone: latestExecution.launch_surfaces?.length ? "attention" : "progress",
    eyebrow: "Latest impact",
    title: latestExecution.checkpoint_title,
    summary: latestExecution.summary && typeof latestExecution.summary === "object" && typeof latestExecution.summary["summary"] === "string"
      ? String(latestExecution.summary["summary"])
      : `Checkpoint execution produced ${latestExecution.operation_count} result${latestExecution.operation_count === 1 ? "" : "s"}.`,
    rationale: "Execution cards keep checkpoint results actionable so the next queue, rollback cues, and downstream resources stay visible in one place.",
    preview: [
      { label: "Executed", value: latestExecution.executed_at_utc },
      { label: "Operations", value: `${latestExecution.operation_count}` },
      { label: "Launch surfaces", value: `${latestExecution.launch_surfaces?.length ?? 0}` },
      { label: "Follow-up resources", value: `${latestExecution.follow_up_resources?.length ?? 0}` },
    ],
    trust,
    handoff: {
      changeSummary: latestExecution.launch_surfaces?.length
        ? "This checkpoint produced downstream work you can launch immediately."
        : "This checkpoint changed state without creating a dedicated downstream queue.",
      createdResources: (latestExecution.follow_up_resources ?? []).map((resource) => resource.label || `${resource.resource_type} #${resource.resource_id}`),
      nextStep: primarySurface?.reason || "Inspect the plan or continue from the latest checkpoint.",
      breadcrumbs: [...context.breadcrumbPrefix, context.sessionName, latestExecution.checkpoint_title],
      workingSet: primarySurface
        ? resolveWorkingSetSessionMetadata(
            context.workingSets,
            launchSurfaceWorkingSetId(primarySurface, context.fallbackWorkingSetId),
          )
        : workingSetHandoff(context),
    },
    actions: [
      openAction(primarySurface ? "Open next surface" : "Resume plan", primaryLocation, latestExecution.checkpoint_title),
      pinAction("Pin handoff", primaryLocation, latestExecution.checkpoint_title, `${snapshot.session.name} · ${latestExecution.checkpoint_title}`),
    ],
  };
}

export function buildPlanningLaunchSurfaceCard(
  surface: PlanningExecutionLaunchSurfaceResponse,
  latestExecution: PlanningExecutionHistoryItemResponse,
  context: ReviewWorkspaceHandoffContext & { sessionName: string },
): OperatorActionCard | null {
  const location = launchSurfaceToLocation(surface, context.fallbackWorkingSetId);
  if (!location) {
    return null;
  }
  const resource = latestExecution.follow_up_resources?.find((item) => item.launch_surface?.resource_id === surface.resource_id) ?? null;
  const handoff = buildLaunchSurfaceHandoff(surface, {
    breadcrumbPrefix: [...context.breadcrumbPrefix, context.sessionName],
    fallbackWorkingSetId: context.fallbackWorkingSetId,
    workingSets: context.workingSets,
  });
  return {
    id: `review-plan-launch-${surface.resource_type}-${surface.resource_id}`,
    kind: "handoff",
    tone: "attention",
    eyebrow: "Next operator surface",
    title: surface.label,
    summary: surface.reason || "Open the next surface prepared by this checkpoint.",
    rationale: "Launch-surface cards keep saved downstream queues explicit so planning never depends on re-deriving where the next review session went.",
    preview: [
      { label: "Surface", value: surface.surface },
      { label: "Resource", value: `${surface.resource_type} #${surface.resource_id}` },
      { label: "Role", value: resource?.role || "Next workflow" },
      ...(handoff.workingSet ? [{ label: "Working set", value: handoff.workingSet.workingSetName }] : []),
    ],
    trust: {
      generationLabel: "Deterministic handoff",
      generationTone: "progress",
      contextSources: [
        `Surface: ${surface.surface}`,
        `Resource: ${surface.resource_type} #${surface.resource_id}`,
        resource ? `Operation: ${resource.operation_kind}` : "Stored launch surface",
      ],
      assumptions: ["The downstream surface still exists and is ready to open."],
      confidenceLabel: "Prepared next-step queue",
      confidenceTone: "attention",
      freshnessLabel: null,
      freshnessTone: "neutral",
      rollbackLabel: "Use the originating execution history for rollback cues",
      rollbackTone: "caution",
      impactSummary: surface.reason || "Open the next surface prepared by this checkpoint.",
      impactTone: "attention",
    },
    handoff,
    actions: [
      openAction("Open next queue", location, surface.reason || surface.label),
      pinAction("Pin handoff", location, surface.reason || surface.label, surface.label),
    ],
  };
}

export function buildPlanningFollowUpResourceCard(
  resource: PlanningExecutionFollowUpResourceResponse,
  context: ReviewWorkspaceHandoffContext & { sessionName: string },
): OperatorActionCard {
  const location = resource.launch_surface
    ? launchSurfaceToLocation(resource.launch_surface, context.fallbackWorkingSetId)
    : null;
  const handoff = buildFollowUpResourceHandoff(resource, {
    breadcrumbPrefix: [...context.breadcrumbPrefix, context.sessionName],
    fallbackWorkingSetId: context.fallbackWorkingSetId,
    workingSets: context.workingSets,
  });

  return {
    id: `review-plan-resource-${resource.resource_type}-${resource.resource_id}`,
    kind: handoff ? "handoff" : "context",
    tone: handoff ? "attention" : "progress",
    eyebrow: "Created resource",
    title: resource.label || `${resource.resource_type} #${resource.resource_id}`,
    summary: resource.operation_summary,
    rationale: "Follow-up resource cards keep plan-created durable objects visible so the operator can continue immediately or pin the result for later.",
    preview: [
      { label: "Role", value: resource.role },
      { label: "Operation", value: resource.operation_kind },
      { label: "Resource", value: `${resource.resource_type} #${resource.resource_id}` },
      ...(handoff?.workingSet ? [{ label: "Working set", value: handoff.workingSet.workingSetName }] : []),
    ],
    trust: {
      generationLabel: "Deterministic follow-up resource",
      generationTone: "progress",
      contextSources: [
        `Role: ${resource.role}`,
        `Operation: ${resource.operation_kind}`,
        `Resource: ${resource.resource_type} #${resource.resource_id}`,
      ],
      assumptions: [],
      confidenceLabel: handoff ? "Created by the latest checkpoint and ready to continue" : "Created by the latest checkpoint",
      confidenceTone: handoff ? "attention" : "progress",
      freshnessLabel: null,
      freshnessTone: "neutral",
      rollbackLabel: "Inspect execution history for rollback support",
      rollbackTone: "caution",
      impactSummary: resource.operation_summary,
      impactTone: handoff ? "attention" : "progress",
    },
    handoff,
    actions: location
      ? [
          openAction("Open next queue", location, resource.operation_summary),
          pinAction("Pin resource", location, resource.operation_summary, resource.label || `${resource.resource_type} #${resource.resource_id}`),
        ]
      : [],
  };
}

export function buildRelationshipImpactCard(options: {
  snapshot: RelationshipReviewSessionSnapshotResponse;
  candidate: RelationshipReviewCandidateResponse;
  recommendedDecision: string;
  recommendationTitle: string;
  trust: TrustSurfaceMetadata;
  selectedAction: RelationshipReviewActionResponse | null;
  context: ReviewWorkspaceHandoffContext & { sessionName: string; loopId: number };
}): OperatorActionCard {
  const { snapshot, candidate, recommendedDecision, recommendationTitle, trust, selectedAction, context } = options;
  const canUseSelectedPreset = Boolean(
    selectedAction
      && (selectedAction.relationship_type === "suggested" || selectedAction.relationship_type === candidate.relationship_type),
  );
  const doLocation = createLocation({ state: "do", loopId: context.loopId, workingSetId: context.fallbackWorkingSetId });

  return {
    id: `review-relationship-impact-${snapshot.session.id}-${context.loopId}-${candidate.id}`,
    kind: "decision",
    tone: candidate.relationship_type === "duplicate" ? "attention" : "neutral",
    eyebrow: "Impact preview",
    title: recommendationTitle,
    summary: recommendedDecision,
    rationale: "Decision cards keep the recommended relationship action, confidence, and downstream consequences visible before you commit the queue mutation.",
    preview: [
      { label: "Queue progress", value: describeQueueProgress(snapshot.current_index, snapshot.loop_count) },
      { label: "Queue remaining", value: `${Math.max(snapshot.loop_count - ((snapshot.current_index ?? -1) + 1), 0)}` },
      { label: "Candidate", value: loopTitle(candidate) },
      { label: "Similarity", value: `${Math.round(candidate.score * 100)}%` },
    ],
    trust,
    handoff: {
      changeSummary: recommendedDecision,
      createdResources: [],
      nextStep: "Confirm, merge, dismiss, or inspect the loop in Do before advancing the queue.",
      breadcrumbs: [...context.breadcrumbPrefix, "Relationship review", context.sessionName, loopTitle(candidate)],
      workingSet: workingSetHandoff(context),
    },
    actionContextLabel: "Decision required",
    actionWarning: candidate.relationship_type === "duplicate"
      ? "Duplicate confirmation or merge is not reversible in-place. Verify both loops represent the same work before committing."
      : "Confirm as duplicate is not reversible in-place. Use that path only if both loops should collapse together.",
    actions: [
      ...(selectedAction && canUseSelectedPreset
        ? [eventActionWithIntegerAttributes(
            `Use “${selectedAction.name}”`,
            `Use the saved relationship-review action ${selectedAction.name}`,
            {
              "data-review-action": "relationship-use-preset",
              "data-loop-id": context.loopId,
              "data-candidate-id": candidate.id,
              "data-candidate-type": candidate.relationship_type,
            },
            "secondary",
          )]
        : []),
      eventActionWithIntegerAttributes(
        `Confirm ${candidate.relationship_type}`,
        `Confirm ${candidate.relationship_type} for the current review item`,
        {
          "data-review-action": "relationship-confirm",
          "data-loop-id": context.loopId,
          "data-candidate-id": candidate.id,
          "data-candidate-type": candidate.relationship_type,
          "data-relationship-type": candidate.relationship_type,
        },
      ),
      ...(candidate.relationship_type === "related"
        ? [eventActionWithIntegerAttributes(
            "Confirm as duplicate",
            "Confirm this related candidate as a duplicate instead",
            {
              "data-review-action": "relationship-confirm",
              "data-loop-id": context.loopId,
              "data-candidate-id": candidate.id,
              "data-candidate-type": "related",
              "data-relationship-type": "duplicate",
            },
            "secondary",
          )]
        : [eventActionWithIntegerAttributes(
            "Merge",
            "Open the merge flow for this duplicate candidate",
            {
              "data-review-action": "relationship-merge",
              "data-loop-id": context.loopId,
              "data-candidate-id": candidate.id,
            },
            "secondary",
          )]),
      eventActionWithIntegerAttributes(
        "Dismiss",
        "Dismiss this relationship candidate",
        {
          "data-review-action": "relationship-dismiss",
          "data-loop-id": context.loopId,
          "data-candidate-id": candidate.id,
          "data-candidate-type": candidate.relationship_type,
        },
        "secondary",
      ),
      openAction("Open loop in Do", doLocation, `Inspect ${loopTitle(candidate)} in Do`, "secondary"),
    ],
  };
}

export function buildEnrichmentImpactCard(options: {
  snapshot: EnrichmentReviewSessionSnapshotResponse;
  item: EnrichmentReviewQueueItemResponse;
  recommendationTitle: string;
  recommendedDecision: string;
  trust: TrustSurfaceMetadata;
  selectedAction: EnrichmentReviewActionResponse | null;
  context: ReviewWorkspaceHandoffContext & { sessionName: string };
}): OperatorActionCard {
  const { snapshot, item, recommendationTitle, recommendedDecision, trust, selectedAction, context } = options;
  const suggestion = item.pending_suggestions[0] ?? null;
  const doLocation = createLocation({ state: "do", loopId: item.loop.id, workingSetId: context.fallbackWorkingSetId });

  return {
    id: `review-enrichment-impact-${snapshot.session.id}-${item.loop.id}`,
    kind: "decision",
    tone: item.pending_clarification_count > 0 ? "attention" : "progress",
    eyebrow: "Impact preview",
    title: recommendationTitle,
    summary: recommendedDecision,
    rationale: "Enrichment impact cards keep the top suggestion, clarification pressure, and next queue action visible before you mutate loop fields.",
    preview: [
      { label: "Queue progress", value: describeQueueProgress(snapshot.current_index, snapshot.loop_count) },
      { label: "Loop", value: loopTitle(item.loop) },
      { label: "Suggestions", value: `${item.pending_suggestion_count}` },
      { label: "Clarifications", value: `${item.pending_clarification_count}` },
    ],
    trust,
    handoff: {
      changeSummary: recommendedDecision,
      createdResources: suggestion ? [suggestionTitle(suggestion)] : [],
      nextStep: item.pending_clarification_count > 0
        ? "Answer clarifications or inspect the loop before applying older suggestions."
        : "Apply, reject, or inspect the loop in Do without losing your place in the queue.",
      breadcrumbs: [...context.breadcrumbPrefix, "Enrichment review", context.sessionName, loopTitle(item.loop)],
      workingSet: workingSetHandoff(context),
    },
    actionContextLabel: "Decision required",
    actionWarning: item.pending_clarification_count > 0
      ? "Clarification answers rerun enrichment and may supersede older suggestions in this queue."
      : "Applying a suggestion mutates loop fields immediately and may supersede current loop context.",
    actions: [
      ...(selectedAction && suggestion
        ? [eventActionWithIntegerAttributes(
            `Use “${selectedAction.name}”`,
            `Use the saved enrichment-review action ${selectedAction.name}`,
            {
              "data-review-action": "enrichment-use-preset",
              "data-suggestion-id": suggestion.id,
            },
            "secondary",
          )]
        : []),
      ...(suggestion
        ? [
            eventActionWithIntegerAttributes(
              "Apply",
              "Apply the top structured suggestion",
              {
                "data-review-action": "enrichment-apply",
                "data-suggestion-id": suggestion.id,
              },
            ),
            eventActionWithIntegerAttributes(
              "Reject",
              "Reject the top structured suggestion",
              {
                "data-review-action": "enrichment-reject",
                "data-suggestion-id": suggestion.id,
              },
              "secondary",
            ),
          ]
        : []),
      openAction("Open loop in Do", doLocation, `Inspect ${loopTitle(item.loop)} in Do`, "secondary"),
    ],
  };
}

export function buildEnrichmentSuggestionCard(options: {
  suggestion: EnrichmentReviewQueueItemResponse["pending_suggestions"][number];
  selectedAction: EnrichmentReviewActionResponse | null;
  context: ReviewWorkspaceHandoffContext & { sessionName: string };
}): OperatorActionCard {
  const { suggestion, selectedAction, context } = options;
  const entries = suggestionEntries(suggestion);

  return {
    id: `review-enrichment-suggestion-${suggestion.id}`,
    kind: "decision",
    tone: "progress",
    eyebrow: `Suggestion #${suggestion.id}`,
    title: suggestionTitle(suggestion),
    summary: entries.length
      ? `Structured suggestion preview: ${entries.slice(0, 2).map(([label]) => label).join(", ")}.`
      : "No structured field preview was emitted for this suggestion.",
    rationale: "Suggestion cards keep apply/reject actions next to the structured preview so review decisions stay explicit instead of hiding inside generic buttons.",
    preview: entries.length
      ? entries.slice(0, 4).map(([label, value]) => ({ label, value }))
      : [{ label: "Preview", value: "No structured field preview available" }],
    trust: {
      generationLabel: "AI-assisted suggestion",
      generationTone: "attention",
      contextSources: [`Model: ${suggestion.model}`],
      assumptions: ["Review the structured fields before mutating loop state."],
      confidenceLabel: entries.length ? `${entries.length} structured field${entries.length === 1 ? "" : "s"} suggested` : "Structured suggestion ready for manual review",
      confidenceTone: "progress",
      freshnessLabel: null,
      freshnessTone: "neutral",
      rollbackLabel: "Apply or reject remains explicit inside this queue",
      rollbackTone: "caution",
      impactSummary: entries.length
        ? `Applying this suggestion may update ${entries.slice(0, 3).map(([label]) => label).join(", ")}.`
        : "Applying this suggestion may update loop fields with model-proposed structure.",
      impactTone: "attention",
    },
    handoff: {
      changeSummary: entries.length
        ? `Applying this suggestion may update ${entries.slice(0, 3).map(([label]) => label).join(", ")}.`
        : "Applying this suggestion updates loop fields inside the current enrichment queue.",
      createdResources: [],
      nextStep: "Apply the suggestion, reject it, or pin this review context for later.",
      breadcrumbs: [...context.breadcrumbPrefix, "Enrichment review", context.sessionName, suggestionTitle(suggestion)],
      workingSet: workingSetHandoff(context),
    },
    actionContextLabel: "Decision required",
    actionWarning: entries.length
      ? `Applying this suggestion mutates ${entries.slice(0, 3).map(([label]) => label).join(", ")} immediately.`
      : "Applying this suggestion mutates loop fields immediately.",
    actions: [
      ...(selectedAction
        ? [eventActionWithIntegerAttributes(
            `Use “${selectedAction.name}”`,
            `Use the saved enrichment-review action ${selectedAction.name}`,
            {
              "data-review-action": "enrichment-use-preset",
              "data-suggestion-id": suggestion.id,
            },
            "secondary",
          )]
        : []),
      eventActionWithIntegerAttributes(
        "Apply",
        "Apply this structured suggestion",
        {
          "data-review-action": "enrichment-apply",
          "data-suggestion-id": suggestion.id,
        },
      ),
      eventActionWithIntegerAttributes(
        "Reject",
        "Reject this structured suggestion",
        {
          "data-review-action": "enrichment-reject",
          "data-suggestion-id": suggestion.id,
        },
        "secondary",
      ),
    ],
  };
}

export function buildCohortImpactCard(options: {
  cohort: LoopReviewCohortResponse;
  decisionLabel: string;
  why: string;
  trust: TrustSurfaceMetadata;
  reviewMode: "daily" | "weekly";
  context: ReviewWorkspaceHandoffContext;
}): OperatorActionCard {
  const { cohort, decisionLabel, why, trust, reviewMode, context } = options;
  const topLoop = cohort.items[0] ?? null;
  const doLocation = topLoop
    ? createLocation({ state: "do", loopId: topLoop.id, workingSetId: context.fallbackWorkingSetId })
    : null;
  const reviewLocation = createLocation({ state: "review", workingSetId: context.fallbackWorkingSetId });

  return {
    id: `review-cohort-impact-${cohort.cohort}`,
    kind: "refresh",
    tone: cohort.count > 0 ? "attention" : "neutral",
    eyebrow: "Impact preview",
    title: decisionLabel,
    summary: why,
    rationale: "Cohort cards keep hygiene review focused on the smallest next cleanup move instead of forcing the operator to infer why this bucket matters.",
    preview: [
      { label: "Cohort", value: cohort.cohort.replaceAll("_", " ") },
      { label: "Items", value: `${cohort.count}` },
      { label: "Cadence", value: reviewMode === "daily" ? "Fast cleanup cadence" : "Structural cleanup cadence" },
      ...(topLoop ? [{ label: "Top loop", value: loopTitle(topLoop) }] : []),
    ],
    trust,
    handoff: {
      changeSummary: why,
      createdResources: [],
      nextStep: topLoop ? "Open the top loop in Do or stay in Review and clear the cohort from the top down." : "Choose another cohort or refresh the current review pass.",
      breadcrumbs: ["Home", "Review", "Hygiene review", cohort.cohort.replaceAll("_", " ")],
      workingSet: workingSetHandoff(context),
    },
    actionContextLabel: "Decision required",
    actions: [
      ...(doLocation ? [openAction("Open top loop in Do", doLocation, `Inspect ${loopTitle(topLoop!)} in Do`)] : []),
      pinAction("Pin review", reviewLocation, `Return to ${cohort.cohort.replaceAll("_", " ")} review`, `Review · ${cohort.cohort.replaceAll("_", " ")}`),
    ],
  };
}
