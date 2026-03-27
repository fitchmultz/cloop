/**
 * shell-operator-cards.ts - Operator workspace card assembly and zone rendering.
 *
 * Purpose:
 *   Extract the shell's action-card construction and operator-workspace zone
 *   rendering into one focused module.
 *
 * Responsibilities:
 *   - Build operator action cards for now, decide, plan, recall, and since-last.
 *   - Attach continuity and working-set metadata to rendered card decks.
 *   - Render the operator workspace zones into the shared shell DOM.
 *
 * Scope:
 *   - Operator card assembly and operator-zone rendering only.
 *
 * Usage:
 *   - Created by frontend/src/shell.ts and invoked whenever shell navigation
 *     or workspace refresh needs fresh action-card output.
 *
 * Invariants/Assumptions:
 *   - The shell coordinator remains the source of truth for mutable shell state.
 *   - Card actions remain declarative and launch through shared shell routing.
 *   - Behavior must remain identical to the pre-extraction shell implementation.
 */

import { renderActionCardDeck } from "./operator-action-cards";
import type {
  ClarificationResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopResponse,
  LoopReviewCohortItem,
  LoopReviewCohortResponse,
  LoopReviewResponse,
  PlanningContextFreshnessTargetChangeResponse,
  PlanningExecutionFollowUpResourceResponse,
  PlanningExecutionHistoryItemResponse,
  PlanningExecutionLaunchSurfaceResponse,
  PlanningExecutionRollbackCueResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewCandidateResponse,
  RelationshipReviewSessionSnapshotResponse,
  SuggestionResponse,
  WorkingSetContextResponse,
  WorkingSetItemResponse,
  WorkingSetResponse,
} from "./domain";
import type {
  ContinuityBaselineSnapshot,
  OperatorActionCard,
  OperatorActionCardAction,
  OperatorActionCardUndoAction,
  ReviewFocus,
  WorkingSetSessionMetadata,
} from "./contracts-ui";
import {
  buildCohortLastSeenMarker,
  buildPlanningLastSeenMarker,
  buildReviewLastSeenMarker,
  buildWorkflowSummaryLastSeenMarker,
  readActiveContinuityNotificationRecords,
  readContinuityLastSeenMarkers,
  readRecentShellActions,
  rememberContinuityObservation,
} from "./continuity-intelligence";
import { continuitySurfaceCard, readMergedRankedWorkflowSummaries } from "./continuity-follow-through";
import {
  buildPrimaryRecommendationDigestCard,
  derivePrimaryRecommendation,
} from "./continuity-recommendations";
import { requireApiRerunAction } from "./executable-rerun";
import { buildPlanningRollbackAction } from "./executable-undo";
import {
  buildChangedCountPreviewItems,
  buildGroupedChangePreviewItems,
  buildPlanningResourcePreviewItems,
  buildRepeatedSnoozeSignal,
  mergePlanningResourceChangeGroups,
  sortLoopsByMostRecentUpdate,
} from "./continuity-card-helpers";
import { summarizeCohortDrift } from "./continuity-drift";
import { formatRelativeTime, formatTimestamp, loopPreview, loopTitle } from "./shell-core";
import { createLocation, locationsMatch } from "./shell-routing";
import type { DecisionSessionSnapshot, PrioritizedCard, ShellElements, ShellLocation, WorkspaceData } from "./shell-types";

export interface ShellOperatorCardRenderer {
  renderNowZone(data: WorkspaceData): void;
  renderDecisionsZone(data: WorkspaceData): void;
  renderPlanZone(data: WorkspaceData): void;
  renderRecallZone(data: WorkspaceData): void;
  renderSinceLastVisit(data: WorkspaceData): void;
  renderOperatorZones(data: WorkspaceData): void;
}

interface CreateShellOperatorCardRendererOptions {
  getElements: () => ShellElements | null;
  getVisitBaseline: () => Date | null;
  getContinuityBaseline: () => ContinuityBaselineSnapshot | null;
  getLatestWorkingSets: () => WorkingSetResponse[];
  getWorkingSetContext: () => WorkingSetContextResponse | null;
  workingSetItemLocation: (item: WorkingSetItemResponse) => ShellLocation;
  focusModeActiveSet: () => WorkingSetResponse | null;
}

export function createShellOperatorCardRenderer(
  options: CreateShellOperatorCardRendererOptions,
): ShellOperatorCardRenderer {
  let elements: ShellElements | null = null;
  let visitBaseline: Date | null = null;
  let continuityBaseline: ContinuityBaselineSnapshot | null = null;
  let latestWorkingSets: WorkingSetResponse[] = [];
  let workingSetContext: WorkingSetContextResponse | null = null;

  function syncContext(): void {
    elements = options.getElements();
    visitBaseline = options.getVisitBaseline();
    continuityBaseline = options.getContinuityBaseline();
    latestWorkingSets = options.getLatestWorkingSets();
    workingSetContext = options.getWorkingSetContext();
  }

  function workingSetItemLocation(item: WorkingSetItemResponse): ShellLocation {
    return options.workingSetItemLocation(item);
  }

  function focusModeActiveSet(): WorkingSetResponse | null {
    return options.focusModeActiveSet();
  }

  function integerValue(value: unknown): number | null {
    if (typeof value === "number" && Number.isInteger(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Number.parseInt(value, 10);
      return Number.isInteger(parsed) ? parsed : null;
    }
    return null;
  }

  function launchSurfaceWeb(
    surface: PlanningExecutionLaunchSurfaceResponse | null | undefined,
  ): Record<string, unknown> | null {
    const webValue = surface?.web;
    return webValue && typeof webValue === "object"
      ? (webValue as Record<string, unknown>)
      : null;
  }

  function launchSurfaceWorkingSetId(
    surface: PlanningExecutionLaunchSurfaceResponse | null | undefined,
  ): number | null {
    return integerValue(launchSurfaceWeb(surface)?.["working_set_id"]);
  }

  function locationWithFallbackWorkingSet(location: ShellLocation, workingSetId: number | null): ShellLocation {
    if (workingSetId == null || location.workingSetId != null) {
      return location;
    }
    return createLocation({ ...location, workingSetId });
  }

  function workingSetById(workingSetId: number | null | undefined): WorkingSetResponse | null {
    if (workingSetId == null) {
      return null;
    }
    return latestWorkingSets.find((set) => set.id === workingSetId)
      ?? (workingSetContext?.active_working_set_id === workingSetId ? workingSetContext.active_working_set : null)
      ?? null;
  }

  function workingSetHandoffMetadata(workingSetId: number | null | undefined): WorkingSetSessionMetadata | null {
    const workingSet = workingSetById(workingSetId);
    if (!workingSet) {
      return null;
    }
    return {
      workingSetId: workingSet.id,
      workingSetName: workingSet.name,
      itemCount: workingSet.item_count,
      missingItemCount: workingSet.missing_item_count,
    };
  }

  function workingSetLabel(workingSetId: number | null | undefined): string | null {
    const metadata = workingSetHandoffMetadata(workingSetId);
    if (metadata) {
      return metadata.workingSetName;
    }
    return workingSetId != null ? `Working set #${workingSetId}` : null;
  }

  function firstNavigableLaunchSurface(
    surfaces: readonly PlanningExecutionLaunchSurfaceResponse[] | null | undefined,
  ): PlanningExecutionLaunchSurfaceResponse | null {
    return (surfaces ?? []).find((surface) => launchSurfaceToLocation(surface) != null) ?? null;
  }

  function withResolvedWorkingSetHandoff(
    card: OperatorActionCard,
    workingSetId: number | null | undefined,
  ): OperatorActionCard {
    if (!card.handoff || card.handoff.workingSet != null) {
      return card;
    }
    const workingSet = workingSetHandoffMetadata(workingSetId);
    if (!workingSet) {
      return card;
    }
    return {
      ...card,
      handoff: {
        ...card.handoff,
        workingSet,
      },
    };
  }

  function launchSurfaceToLocation(surface: PlanningExecutionLaunchSurfaceResponse): ShellLocation | null {
    const web = launchSurfaceWeb(surface);
    const reviewKind = typeof web?.["review_kind"] === "string" ? web["review_kind"] : null;
    const sessionId = integerValue(web?.["session_id"]);
    const workingSetId = launchSurfaceWorkingSetId(surface);

    if (web?.["surface"] === "review_session" && reviewKind === "relationship") {
      return createLocation({ state: "decide", reviewFocus: "relationship", sessionId, workingSetId });
    }
    if (web?.["surface"] === "review_session" && reviewKind === "enrichment") {
      return createLocation({ state: "decide", reviewFocus: "enrichment", sessionId, workingSetId });
    }
    return null;
  }

  function filterCardsForFocus(cards: OperatorActionCard[]): OperatorActionCard[] {
    const activeSet = focusModeActiveSet();
    if (!workingSetContext?.focus_mode_enabled || !activeSet) {
      return cards;
    }
    const focusLocations = (activeSet.items ?? []).map((item) => {
      return locationWithFallbackWorkingSet(workingSetItemLocation(item), activeSet.id);
    });
    return cards.filter((card) => {
      return card.actions.some((action) => {
        if (!isLocationAction(action)) {
          return false;
        }
        const candidateLocation = locationWithFallbackWorkingSet(createLocation(action.location), activeSet.id);
        return focusLocations.some((location) => locationsMatch(candidateLocation, location));
      });
    });
  }

  function buildOpenAction(
    label: string,
    location: ShellLocation,
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

  function buildPinAction(
    label: string,
    location: ShellLocation,
    description: string,
    pinLabel?: string,
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

  function isUndoAction(value: OperatorActionCardUndoAction | null): value is OperatorActionCardUndoAction {
    return value != null;
  }

  function summarizeFollowUpResources(resources: PlanningExecutionFollowUpResourceResponse[] | undefined): string[] {
    return (resources ?? []).slice(0, 3).map((resource) => {
      return `${resource.label || `${resource.resource_type} #${resource.resource_id}`}: ${resource.operation_summary}`;
    });
  }

  function summarizeRollbackCue(cues: PlanningExecutionRollbackCueResponse | null | undefined): string {
    if (!cues) {
      return "Rollback information is not available.";
    }
    if (cues.undoable_operation_count > 0) {
      return `${cues.undoable_operation_count} operation${cues.undoable_operation_count === 1 ? "" : "s"} are directly undoable.`;
    }
    if (cues.rollback_supported_operation_count > 0) {
      return `${cues.rollback_supported_operation_count} operation${cues.rollback_supported_operation_count === 1 ? "" : "s"} include guided rollback cues.`;
    }
    return "No explicit rollback path was captured for this execution.";
  }

  function formatChangedFieldLabel(field: string): string {
    return field.replaceAll("_", " ");
  }

  function recentPlanningExecutions(data: WorkspaceData): PlanningExecutionHistoryItemResponse[] {
    if (!visitBaseline) {
      return [];
    }
    const baselineTime = visitBaseline.getTime();
    return (data.planningSnapshot?.execution_history ?? []).filter((item) => {
      return Date.parse(item.executed_at_utc) > baselineTime;
    });
  }

  function buildPlanningReplacementCue(
    baseline: NonNullable<ContinuityBaselineSnapshot["planningSession"]>,
    current: PlanningSessionSnapshotResponse,
  ): { summary: string; detail: string; overlapLabel: string } {
    const previousName = baseline.sessionName || `Plan #${baseline.sessionId}`;
    const baselineTargetIds = baseline.targetLoopIds ?? [];
    const currentTargetIds = new Set((current.target_loops ?? []).map((loop) => loop.id));
    const overlapCount = baselineTargetIds.filter((loopId) => currentTargetIds.has(loopId)).length;
    const overlapLabel = `${overlapCount}/${Math.max(baselineTargetIds.length, current.target_loops?.length ?? 0, 1)} overlapping targets`;

    if (baseline.status === "completed") {
      return {
        summary: `${current.session.name} replaced the completed plan you last saw.`,
        detail: overlapLabel,
        overlapLabel,
      };
    }
    if (overlapCount === 0) {
      return {
        summary: `${current.session.name} targets a different slice of work than ${previousName}.`,
        detail: "No prior target loops overlap",
        overlapLabel,
      };
    }
    if (overlapCount < baselineTargetIds.length) {
      return {
        summary: `${current.session.name} partially overlaps ${previousName} while refreshing the work mix.`,
        detail: overlapLabel,
        overlapLabel,
      };
    }
    return {
      summary: `${current.session.name} is a newer grounded version of ${previousName}.`,
      detail: overlapLabel,
      overlapLabel,
    };
  }

  function relationCandidateLabel(candidate: RelationshipReviewCandidateResponse | null): string {
    if (!candidate) {
      return "No candidate preview available";
    }
    return `${loopTitle(candidate)} · ${Math.round(candidate.score * 100)}% similarity`;
  }

  function suggestionFieldSummary(suggestion: SuggestionResponse | null): string {
    if (!suggestion || typeof suggestion.parsed !== "object" || suggestion.parsed === null) {
      return "No structured suggestion preview available";
    }
    const keys = Object.keys(suggestion.parsed);
    return keys.length ? `Suggests ${keys.join(", ")}` : "No parsed fields surfaced";
  }

  function clarificationLabel(clarification: ClarificationResponse | null): string {
    if (!clarification) {
      return "No clarification preview available";
    }
    return clarification.question;
  }

  function buildLoopNowCards(data: WorkspaceData): OperatorActionCard[] {
    const buckets: Array<{ label: string; tone: OperatorActionCard["tone"]; items: LoopResponse[] }> = [
      { label: "Due soon", tone: "attention", items: data.nextLoops.due_soon ?? [] },
      { label: "Quick wins", tone: "progress", items: data.nextLoops.quick_wins ?? [] },
      { label: "High leverage", tone: "progress", items: data.nextLoops.high_leverage ?? [] },
      { label: "Standard", tone: "neutral", items: data.nextLoops.standard ?? [] },
    ];

    return buckets.flatMap((bucket) => {
      return bucket.items.slice(0, 2).map((loop) => {
        const location = createLocation({ state: "do", loopId: loop.id });
        const dueMeta =
          loop.due_at_utc || loop.due_date
            ? `Due ${formatRelativeTime(loop.due_at_utc ?? loop.due_date ?? null)}`
            : "No due date";
        const nextStep = loop.next_action?.trim() || "Open the loop to choose the next concrete move.";
        return {
          id: `now-${bucket.label}-${loop.id}`,
          kind: "mutation",
          tone: bucket.tone,
          eyebrow: bucket.label,
          title: loopTitle(loop),
          summary: loopPreview(loop),
          rationale:
            bucket.label === "Due soon"
              ? "This loop is surfacing because timing pressure is higher than the rest of the queue."
              : bucket.label === "Quick wins"
                ? "This loop looks easy to move quickly, so it is a strong momentum candidate."
                : bucket.label === "High leverage"
                  ? "This loop appears to unlock outsized value relative to the rest of the queue."
                  : "This loop is ready enough to work without waiting on additional system preparation.",
          preview: [
            { label: "Loop", value: loopTitle(loop) },
            { label: "Status", value: loop.status },
            { label: "Timing", value: dueMeta },
            { label: "Next step", value: nextStep },
          ],
          trust: {
            contextSources: [
              "Live /loops/next prioritization",
              `Bucket: ${bucket.label}`,
              loop.project ? `Project: ${loop.project}` : "Loop-level prioritization only",
            ],
            assumptions: [
              loop.next_action ? "Existing next action remains valid." : "A new next action may still need operator clarification.",
            ],
            confidenceLabel: bucket.label === "Standard" ? "Ready-work signal" : `${bucket.label} priority signal`,
            rollbackLabel: "This card launches the loop; no mutation happens until you act inside Do.",
            freshnessLabel: `Updated ${formatRelativeTime(loop.updated_at_utc)}`,
          },
          handoff: {
            changeSummary: "Opening this card hands off into the exact loop detail inside the Do workspace.",
            createdResources: [],
            nextStep: "Review the loop, then execute or edit the next action in-context.",
            breadcrumbs: ["Home", "Do", `Loop #${loop.id}`],
          },
          actions: [
            buildOpenAction("Open in Do", location, loopPreview(loop)),
            buildPinAction("Pin for later", location, loopPreview(loop), loopTitle(loop)),
          ],
        } satisfies OperatorActionCard;
      });
    });
  }

  function buildNowCards(data: WorkspaceData): OperatorActionCard[] {
    const recommendation = followThroughModel(data).recommendation;
    return recommendation ? [recommendation.card, ...buildLoopNowCards(data)] : buildLoopNowCards(data);
  }

  function buildRelationshipDecisionCard(
    snapshot: RelationshipReviewSessionSnapshotResponse,
  ): OperatorActionCard | null {
    if (!snapshot.session || snapshot.loop_count <= 0) {
      return null;
    }

    const item = snapshot.current_item ?? snapshot.items[0] ?? null;
    const candidate = item?.duplicate_candidates[0] ?? item?.related_candidates[0] ?? null;
    const location = createLocation({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: snapshot.session.id,
    });

    return {
      id: `relationship-session-${snapshot.session.id}`,
      kind: "decision",
      tone: item?.top_score && item.top_score >= 0.9 ? "attention" : "neutral",
      eyebrow: "Relationship queue",
      title: snapshot.session.name,
      summary: `${snapshot.loop_count} duplicate/related-loop decision${snapshot.loop_count === 1 ? "" : "s"} are waiting in a saved queue.`,
      rationale:
        "This queue preserves your review cursor so you can keep making similarity judgments without rebuilding the candidate set.",
      preview: [
        { label: "Current loop", value: item ? loopTitle(item.loop) : "Queue ready" },
        { label: "Top candidate", value: relationCandidateLabel(candidate) },
        { label: "Queued", value: `${snapshot.loop_count} decision${snapshot.loop_count === 1 ? "" : "s"}` },
        { label: "Cursor", value: snapshot.current_index != null ? `${snapshot.current_index + 1} of ${snapshot.loop_count}` : "Start of queue" },
      ],
      trust: {
        contextSources: [
          `Saved query: ${snapshot.session.query}`,
          `${snapshot.session.relationship_kind} similarity review`,
          item ? `Top score ${Math.round(item.top_score * 100)}%` : "Session-level similarity scan",
        ],
        assumptions: [
          "Human review remains required before any relationship is confirmed or dismissed.",
        ],
        confidenceLabel: item ? `${Math.round(item.top_score * 100)}% top-similarity signal` : "Queue-level review signal",
        rollbackLabel: "No relationship mutation happens until you choose confirm or dismiss inside the queue.",
        freshnessLabel: `Updated ${formatRelativeTime(snapshot.session.updated_at_utc)}`,
      },
      handoff: {
        changeSummary: "Opening this card launches the saved relationship review session at the preserved cursor.",
        createdResources: candidate ? [`Candidate preview: ${relationCandidateLabel(candidate)}`] : [],
        nextStep: "Confirm or dismiss the current duplicate/related recommendation.",
        breadcrumbs: ["Home", "Decide", snapshot.session.name],
      },
      actions: [
        buildOpenAction("Open decision queue", location, `${snapshot.loop_count} relationship decisions queued`),
        requireApiRerunAction(snapshot.rerun_action, {
          sourceLabel: `Saved relationship review session ${snapshot.session.name}`,
        }),
        buildPinAction("Pin queue", location, `${snapshot.loop_count} relationship decisions queued`, `Decide · ${snapshot.session.name}`),
      ],
    } satisfies OperatorActionCard;
  }

  function buildEnrichmentDecisionCard(
    snapshot: EnrichmentReviewSessionSnapshotResponse,
  ): OperatorActionCard | null {
    if (!snapshot.session || snapshot.loop_count <= 0) {
      return null;
    }

    const item = snapshot.current_item ?? snapshot.items[0] ?? null;
    const suggestion = item?.pending_suggestions[0] ?? null;
    const clarification = item?.pending_clarifications[0] ?? null;
    const location = createLocation({
      state: "decide",
      reviewFocus: "enrichment",
      sessionId: snapshot.session.id,
    });

    return {
      id: `enrichment-session-${snapshot.session.id}`,
      kind: "decision",
      tone: item?.pending_clarification_count ? "attention" : "progress",
      eyebrow: "Enrichment queue",
      title: snapshot.session.name,
      summary: `${snapshot.loop_count} enrichment follow-up item${snapshot.loop_count === 1 ? "" : "s"} are ready for apply/reject or clarification answers.`,
      rationale:
        "This queue keeps pending suggestions and clarifications together so you can resolve AI-prepared follow-up work without losing place.",
      preview: [
        { label: "Current loop", value: item ? loopTitle(item.loop) : "Queue ready" },
        { label: "Suggestion", value: suggestionFieldSummary(suggestion) },
        { label: "Clarification", value: clarificationLabel(clarification) },
        {
          label: "Pending",
          value: item
            ? `${item.pending_suggestion_count} suggestion${item.pending_suggestion_count === 1 ? "" : "s"}, ${item.pending_clarification_count} clarification${item.pending_clarification_count === 1 ? "" : "s"}`
            : `${snapshot.loop_count} loop${snapshot.loop_count === 1 ? "" : "s"}`,
        },
      ],
      trust: {
        contextSources: [
          `Saved query: ${snapshot.session.query}`,
          `${snapshot.session.pending_kind} pending enrichment follow-up`,
          suggestion ? `Model: ${suggestion.model}` : "Stored session snapshot",
        ],
        assumptions: [
          "Structured suggestions should be reviewed before being applied to loop state.",
        ],
        confidenceLabel: clarification ? "Needs clarification before high-confidence apply" : "Structured suggestion ready for review",
        rollbackLabel: "Apply/reject choices happen inside the queue, not from this workspace card.",
        freshnessLabel: `Updated ${formatRelativeTime(snapshot.session.updated_at_utc)}`,
      },
      handoff: {
        changeSummary: "Opening this card launches the saved enrichment queue at the preserved cursor.",
        createdResources: [
          suggestion ? suggestionFieldSummary(suggestion) : "Saved enrichment session ready",
          clarification ? `Clarification: ${clarification.question}` : "No clarification preview surfaced",
        ],
        nextStep: "Apply or reject a suggestion, or answer the next clarification.",
        breadcrumbs: ["Home", "Decide", snapshot.session.name],
      },
      actions: [
        buildOpenAction("Open enrichment queue", location, `${snapshot.loop_count} enrichment follow-up items queued`),
        requireApiRerunAction(snapshot.rerun_action, {
          sourceLabel: `Saved enrichment review session ${snapshot.session.name}`,
        }),
        buildPinAction("Pin queue", location, `${snapshot.loop_count} enrichment follow-up items queued`, `Decide · ${snapshot.session.name}`),
      ],
    } satisfies OperatorActionCard;
  }

  function buildCohortDecisionCard(
    cohort: LoopReviewCohortResponse,
    index: number,
    generatedAtUtc: string,
  ): OperatorActionCard {
    const topLoop = cohort.items[0] ?? null;
    const location = createLocation({ state: "review", reviewFocus: "cohorts" });
    const cohortLabel = cohort.cohort.replaceAll("_", " ");

    return {
      id: `cohort-${cohort.cohort}-${index}`,
      kind: "decision",
      tone: index === 0 ? "attention" : "neutral",
      eyebrow: "Review cohort",
      title: cohortLabel,
      summary: `${cohort.count} item${cohort.count === 1 ? "" : "s"} need attention in this review cohort.`,
      rationale:
        "This cohort is the fastest way to clean up drift or stale work without scanning the entire system manually.",
      preview: [
        { label: "Cohort", value: cohortLabel },
        { label: "Count", value: `${cohort.count}` },
        { label: "Example", value: topLoop ? loopTitle(topLoop) : "No loop preview available" },
        { label: "Freshness", value: topLoop ? `Updated ${formatRelativeTime(topLoop.updated_at_utc)}` : "Session review" },
      ],
      trust: {
        contextSources: ["/loops/review cohort summary", "State-based hygiene review"],
        assumptions: ["The cohort remains a review signal, not a forced redirect."],
        confidenceLabel: "Cohort-level hygiene signal",
        rollbackLabel: "Opening review cohorts does not mutate data until you act inside Review.",
        freshnessLabel: `Generated ${formatRelativeTime(generatedAtUtc)}`,
      },
      handoff: {
        changeSummary: "Opening this card keeps you inside the broader Review workspace and focuses the cohort area.",
        createdResources: topLoop ? [`Top loop preview: ${loopTitle(topLoop)}`] : [],
        nextStep: "Inspect the cohort and decide which loops need cleanup first.",
        breadcrumbs: ["Home", "Review", cohortLabel],
      },
      actions: [
        buildOpenAction("Open review cohort", location, `${cohort.count} items in ${cohortLabel}`),
        buildPinAction("Pin cohort", location, `${cohort.count} items in ${cohortLabel}`, `Review · ${cohortLabel}`),
      ],
    } satisfies OperatorActionCard;
  }

  function buildDecisionCards(data: WorkspaceData): OperatorActionCard[] {
    const cards: OperatorActionCard[] = [];
    const relationshipCard = data.relationshipSnapshot ? buildRelationshipDecisionCard(data.relationshipSnapshot) : null;
    const enrichmentCard = data.enrichmentSnapshot ? buildEnrichmentDecisionCard(data.enrichmentSnapshot) : null;
    if (relationshipCard) {
      cards.push(relationshipCard);
    }
    if (enrichmentCard) {
      cards.push(enrichmentCard);
    }

    data.reviewData.daily
      .filter((cohort) => cohort.count > 0)
      .slice(0, 2)
      .forEach((cohort, index) => {
        cards.push(buildCohortDecisionCard(cohort, index, data.reviewData.generated_at_utc));
      });

    return cards;
  }

  function buildPlanningResumeCard(snapshot: PlanningSessionSnapshotResponse): OperatorActionCard {
    const location = createLocation({
      state: "plan",
      reviewFocus: "planning",
      sessionId: snapshot.session.id,
    });
    const currentCheckpoint = snapshot.current_checkpoint ?? null;
    const currentCheckpointTitle = currentCheckpoint?.title || `Checkpoint ${snapshot.session.current_checkpoint_index + 1}`;
    const targetLoops = snapshot.target_loops ?? [];
    const assumptions = snapshot.assumptions ?? [];
    const sources = snapshot.sources ?? [];
    const targetLoopPreview = targetLoops[0] ?? null;

    return {
      id: `plan-session-${snapshot.session.id}`,
      kind: snapshot.session.status === "completed" ? "refresh" : "handoff",
      tone: snapshot.session.status === "completed" ? "progress" : "attention",
      eyebrow: "Planning session",
      title: snapshot.session.name,
      summary: snapshot.plan_summary,
      rationale:
        "Planning stays durable so you can resume a checkpointed workflow without reconstructing the underlying context by hand.",
      preview: [
        { label: "Status", value: snapshot.session.status.replaceAll("_", " ") },
        { label: "Current checkpoint", value: currentCheckpointTitle },
        { label: "Progress", value: `${snapshot.session.executed_checkpoint_count}/${snapshot.session.checkpoint_count} executed` },
        { label: "Focus loop", value: targetLoopPreview ? loopTitle(targetLoopPreview) : "No focus loop preview available" },
      ],
      trust: {
        contextSources: [
          `${targetLoops.length} target loop${targetLoops.length === 1 ? "" : "s"}`,
          `${assumptions.length} recorded assumption${assumptions.length === 1 ? "" : "s"}`,
          `${sources.length} planning source${sources.length === 1 ? "" : "s"}`,
        ],
        assumptions: assumptions.slice(0, 2),
        confidenceLabel: currentCheckpoint ? `Ready to resume ${currentCheckpoint.title}` : "Planning session available",
        rollbackLabel: "Checkpoint execution records explicit rollback cues whenever supported.",
        freshnessLabel: `Updated ${formatRelativeTime(snapshot.session.updated_at_utc)}`,
      },
      handoff: {
        changeSummary: "Opening this card hands off into the checkpointed planning workspace with the current session selected.",
        createdResources: targetLoops.slice(0, 2).map((loop) => `Focus loop: ${loopTitle(loop)}`),
        nextStep: `Review ${currentCheckpointTitle} and decide whether to execute or refresh the plan.`,
        breadcrumbs: ["Home", "Plan", snapshot.session.name],
      },
      actions: [
        buildOpenAction("Resume plan", location, `Resume ${currentCheckpointTitle}`),
        requireApiRerunAction(snapshot.rerun_action, {
          sourceLabel: `Planning session ${snapshot.session.name}`,
        }),
        buildPinAction("Pin plan", location, `Resume ${currentCheckpointTitle}`, `Plan · ${snapshot.session.name}`),
      ],
    } satisfies OperatorActionCard;
  }

  function buildPlanningExecutionCard(
    snapshot: PlanningSessionSnapshotResponse,
    latestExecution: PlanningExecutionHistoryItemResponse,
  ): OperatorActionCard {
    const primarySurface = firstNavigableLaunchSurface(latestExecution.launch_surfaces);
    const primaryLocation = primarySurface
      ? (launchSurfaceToLocation(primarySurface)
        ?? createLocation({ state: "plan", reviewFocus: "planning", sessionId: snapshot.session.id }))
      : createLocation({ state: "plan", reviewFocus: "planning", sessionId: snapshot.session.id });
    const propagatedWorkingSetId = launchSurfaceWorkingSetId(primarySurface);
    const propagatedWorkingSetLabel = workingSetLabel(propagatedWorkingSetId);
    const followUpBits = summarizeFollowUpResources(latestExecution.follow_up_resources);
    const card = {
      id: `plan-execution-${snapshot.session.id}-${latestExecution.checkpoint_index}`,
      kind: "handoff",
      tone: latestExecution.launch_surfaces?.length ? "attention" : "progress",
      eyebrow: "Latest execution",
      title: latestExecution.checkpoint_title,
      summary: `${latestExecution.operation_count} deterministic result${latestExecution.operation_count === 1 ? "" : "s"} were executed ${formatRelativeTime(latestExecution.executed_at_utc)}.`,
      rationale:
        "Execution cards make downstream consequences explicit so you can move into the next queue without reverse-engineering what changed.",
      preview: [
        { label: "Executed", value: formatTimestamp(latestExecution.executed_at_utc) },
        { label: "Operations", value: `${latestExecution.operation_count}` },
        ...(propagatedWorkingSetLabel ? [{ label: "Working set", value: propagatedWorkingSetLabel }] : []),
        { label: "Follow-ups", value: followUpBits[0] ?? "No follow-up resources were emitted" },
        {
          label: "Next surface",
          value: primarySurface?.label || "Resume the planning session",
        },
      ],
      trust: {
        contextSources: [
          "Stored checkpoint execution history",
          `${latestExecution.follow_up_resources?.length ?? 0} follow-up resource${(latestExecution.follow_up_resources?.length ?? 0) === 1 ? "" : "s"}`,
          `${latestExecution.launch_surfaces?.length ?? 0} launch surface${(latestExecution.launch_surfaces?.length ?? 0) === 1 ? "" : "s"}`,
        ],
        assumptions: ["Execution results reflect the latest stored checkpoint payload."],
        confidenceLabel: latestExecution.launch_surfaces?.length ? "A next surface was prepared for immediate launch" : "Execution completed without a downstream queue",
        rollbackLabel: summarizeRollbackCue(latestExecution.rollback_cues),
        freshnessLabel: `Executed ${formatRelativeTime(latestExecution.executed_at_utc)}`,
      },
      handoff: {
        changeSummary: latestExecution.launch_surfaces?.length
          ? "This checkpoint produced downstream work you can launch immediately."
          : "This checkpoint changed state but did not emit a dedicated downstream surface.",
        createdResources: followUpBits,
        nextStep: primarySurface?.reason || "Inspect the execution history or continue in the plan workspace.",
        breadcrumbs: ["Home", "Plan", snapshot.session.name, latestExecution.checkpoint_title],
      },
      actions: [
        buildOpenAction(
          latestExecution.launch_surfaces?.length ? "Open next surface" : "Resume plan",
          primaryLocation,
          followUpBits[0] ?? latestExecution.checkpoint_title,
        ),
        requireApiRerunAction(snapshot.rerun_action, {
          sourceLabel: `Planning session ${snapshot.session.name}`,
        }),
        buildPinAction(
          "Pin handoff",
          primaryLocation,
          followUpBits[0] ?? latestExecution.checkpoint_title,
          primarySurface?.label || latestExecution.checkpoint_title,
        ),
        ...[
          buildPlanningRollbackAction(latestExecution),
        ].filter(isUndoAction),
      ],
    } satisfies OperatorActionCard;
    return withResolvedWorkingSetHandoff(card, propagatedWorkingSetId);
  }

  function buildLaunchSurfaceCard(
    surface: PlanningExecutionLaunchSurfaceResponse,
    latestExecution: PlanningExecutionHistoryItemResponse,
  ): OperatorActionCard | null {
    const location = launchSurfaceToLocation(surface);
    if (!location) {
      return null;
    }
    const resource = latestExecution.follow_up_resources?.find((item) => item.launch_surface?.resource_id === surface.resource_id) ?? null;
    const reason = surface.reason?.trim() || "Open the next operator surface prepared by the latest checkpoint.";
    const propagatedWorkingSetId = launchSurfaceWorkingSetId(surface);
    const propagatedWorkingSetLabel = workingSetLabel(propagatedWorkingSetId);
    const card = {
      id: `launch-surface-${surface.resource_type}-${surface.resource_id}`,
      kind: "handoff",
      tone: "attention",
      eyebrow: "Prepared handoff",
      title: surface.label,
      summary: reason,
      rationale:
        "Handoff cards exist so you can continue into the exact downstream workflow the checkpoint created, instead of searching for the result manually.",
      preview: [
        { label: "Surface", value: surface.surface },
        ...(propagatedWorkingSetLabel ? [{ label: "Working set", value: propagatedWorkingSetLabel }] : []),
        { label: "Resource", value: `${surface.resource_type} #${surface.resource_id}` },
        { label: "Operation", value: resource?.operation_summary || "Created by the latest checkpoint" },
        { label: "Role", value: resource?.role || "Next workflow" },
      ],
      trust: {
        contextSources: [
          "Planning launch surface metadata",
          resource ? `Follow-up resource: ${resource.operation_kind}` : "Stored launch surface",
        ],
        assumptions: ["The downstream saved session still exists and is ready to open."],
        confidenceLabel: "Primary next-step recommendation",
        rollbackLabel: summarizeRollbackCue(latestExecution.rollback_cues),
        freshnessLabel: `Prepared ${formatRelativeTime(latestExecution.executed_at_utc)}`,
      },
      handoff: {
        changeSummary: "This execution created a durable downstream surface you can open immediately.",
        createdResources: resource ? [resource.operation_summary] : [],
        nextStep: reason,
        breadcrumbs: ["Home", "Plan", surface.label],
      },
      actions: [
        buildOpenAction("Launch next queue", location, reason),
        buildPinAction("Pin handoff", location, reason, surface.label),
      ],
    } satisfies OperatorActionCard;
    return withResolvedWorkingSetHandoff(card, propagatedWorkingSetId);
  }

  function buildPlanCards(data: WorkspaceData): OperatorActionCard[] {
    const snapshot = data.planningSnapshot;
    if (!snapshot?.session) {
      return [];
    }

    const cards: OperatorActionCard[] = [buildPlanningResumeCard(snapshot)];
    const latestExecution = snapshot.execution_history?.at(-1) ?? null;
    if (!latestExecution) {
      return cards;
    }

    cards.push(buildPlanningExecutionCard(snapshot, latestExecution));
    latestExecution.launch_surfaces?.forEach((surface) => {
      const launchCard = buildLaunchSurfaceCard(surface, latestExecution);
      if (launchCard) {
        cards.push(launchCard);
      }
    });
    return cards;
  }

  function buildRecallCards(data: WorkspaceData): OperatorActionCard[] {
    const blockedCount = data.allLoops.filter((loop) => loop.status === "blocked").length;
    const activeDecisionCount =
      (data.relationshipSnapshot?.loop_count ?? 0)
      + (data.enrichmentSnapshot?.loop_count ?? 0);
    const planAssumptions = data.planningSnapshot?.assumptions ?? [];
    const latestExecution = data.planningSnapshot?.execution_history?.at(-1) ?? null;

    const chatLocation = createLocation({ state: "recall", recallTool: "chat" });
    const memoryLocation = createLocation({ state: "recall", recallTool: "memory" });
    const ragLocation = createLocation({ state: "recall", recallTool: "rag" });

    return [
      {
        id: "recall-chat-suggestion",
        kind: "context",
        tone: blockedCount || activeDecisionCount ? "attention" : "neutral",
        eyebrow: "Grounded chat",
        title: "Ask what deserves attention next",
        summary: "Use grounded chat to synthesize real loops, review queues, and recent execution into one operator recommendation.",
        rationale:
          "This is the fastest recall surface when you want a narrative summary backed by the live operator state instead of scanning each queue yourself.",
        preview: [
          { label: "Blocked loops", value: `${blockedCount}` },
          { label: "Active decisions", value: `${activeDecisionCount}` },
          { label: "Planning session", value: data.planningSnapshot?.session?.name || "No active planning session" },
          { label: "Prompt idea", value: "What changed, what is blocked, and what should I do now?" },
        ],
        trust: {
          contextSources: ["Loop context", "Memory context", "Operator workspace state"],
          assumptions: ["Grounded chat stays most useful when loop and memory context remain enabled."],
          confidenceLabel: blockedCount || activeDecisionCount ? "High-value synthesis prompt available" : "General system recap prompt available",
          rollbackLabel: "Opening chat does not mutate anything by itself.",
          freshnessLabel: `Workspace refreshed ${formatRelativeTime(new Date())}`,
        },
        handoff: {
          changeSummary: "This launches the grounded chat thread from the same operator context.",
          createdResources: [],
          nextStep: "Ask for a prioritized summary or a recommended next move.",
          breadcrumbs: ["Home", "Recall", "Grounded chat"],
        },
        actions: [
          buildOpenAction("Open grounded chat", chatLocation, "Ask grounded chat what changed and what matters now"),
          buildPinAction("Pin chat", chatLocation, "Grounded chat for live operator-state synthesis", "Recall · Grounded chat"),
        ],
      },
      {
        id: "recall-memory-suggestion",
        kind: "context",
        tone: planAssumptions.length ? "progress" : "neutral",
        eyebrow: "Memory",
        title: "Review durable memory before the next move",
        summary: "Open Memory when a plan, decision, or conversation depends on durable facts, preferences, or commitments rather than only current loop state.",
        rationale:
          "Memory is the right recall surface when the system's next recommendation should be shaped by stable personal context, not just today’s task graph.",
        preview: [
          { label: "Recorded assumptions", value: planAssumptions[0] || "No active planning assumption preview" },
          { label: "Best use", value: "Preferences, commitments, and durable context" },
          { label: "Active plan", value: data.planningSnapshot?.session?.name || "No active plan" },
        ],
        trust: {
          contextSources: ["Direct memory store", "Planning assumptions", "Operator working context"],
          assumptions: ["Memory entries should capture durable truths, not one-off scratch notes."],
          confidenceLabel: planAssumptions.length ? "Memory can sharpen the next planning/review decision" : "Memory remains available for durable context review",
          rollbackLabel: "Opening Memory is read-first; edits stay explicit inside the Memory workspace.",
          freshnessLabel: null,
        },
        handoff: {
          changeSummary: "This launches the direct-memory workspace without leaving the operator shell model.",
          createdResources: planAssumptions.slice(0, 2),
          nextStep: "Inspect or update durable memory entries that should shape the next workflow.",
          breadcrumbs: ["Home", "Recall", "Memory"],
        },
        actions: [
          buildOpenAction("Open memory", memoryLocation, "Inspect durable memory before the next workflow"),
          buildPinAction("Pin memory", memoryLocation, "Return to durable memory context", "Recall · Memory"),
        ],
      },
      {
        id: "recall-documents-suggestion",
        kind: "context",
        tone: latestExecution?.follow_up_resources?.length ? "progress" : "neutral",
        eyebrow: "Documents",
        title: "Pull in local documents when evidence matters",
        summary: "Use Documents when the next decision depends on notes, playbooks, or other indexed local files that should ground the answer or plan refresh.",
        rationale:
          "Document recall is most useful when a planning step or review decision needs source-backed evidence instead of relying on memory alone.",
        preview: [
          { label: "Latest handoff", value: latestExecution?.launch_surfaces?.[0]?.label || "No active plan-created handoff" },
          { label: "Best use", value: "Policies, notes, manuals, and indexed local references" },
          { label: "Prompt idea", value: "What local docs should inform this next decision?" },
        ],
        trust: {
          contextSources: ["Indexed local documents", "RAG retrieval", "Operator handoff context"],
          assumptions: ["The needed reference material has already been indexed locally."],
          confidenceLabel: latestExecution?.follow_up_resources?.length ? "Useful before executing the next follow-up queue" : "Available whenever evidence-backed recall is needed",
          rollbackLabel: "Opening Documents is non-mutating until you ingest or ask.",
          freshnessLabel: null,
        },
        handoff: {
          changeSummary: "This launches the document-backed recall surface from the same shell.",
          createdResources: latestExecution?.follow_up_resources?.slice(0, 2).map((resource) => resource.label || `${resource.resource_type} #${resource.resource_id}`) ?? [],
          nextStep: "Ask a document-grounded question or index missing local material.",
          breadcrumbs: ["Home", "Recall", "Documents"],
        },
        actions: [
          buildOpenAction("Open documents", ragLocation, "Use document-backed recall for the next decision"),
          buildPinAction("Pin documents", ragLocation, "Return to document-backed recall", "Recall · Documents"),
        ],
      },
    ] satisfies OperatorActionCard[];
  }

  function buildCompletedSinceLastCard(data: WorkspaceData): PrioritizedCard | null {
    if (!visitBaseline) {
      return null;
    }

    const baselineTime = visitBaseline.getTime();
    const completed = data.allLoops
      .filter((loop) => loop.closed_at_utc && new Date(loop.closed_at_utc).getTime() > baselineTime)
      .sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc))
      .slice(0, 3);
    if (!completed.length) {
      return null;
    }

    const location = createLocation({ state: "do" });
    return {
      priority: 55,
      card: {
        id: "since-last-completed",
        kind: "context",
        tone: "progress",
        eyebrow: "Resume signal",
        title: "Recently completed work",
        summary: `${completed.length} loop${completed.length === 1 ? "" : "s"} completed since your last visit.`,
        rationale:
          "Completion deltas help you re-enter with momentum and understand what is already off the board before you pick the next task.",
        preview: completed.map((loop, index) => ({ label: `Completed ${index + 1}`, value: loopTitle(loop) })),
        trust: {
          contextSources: ["Loop close timestamps", "Last-visit browser baseline"],
          assumptions: ["Browser local storage baseline still reflects your prior visit."],
          confidenceLabel: "Recent completion delta",
          rollbackLabel: "This is informational only; opening Do does not replay completed work.",
          freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
        },
        handoff: {
          changeSummary: "This recap helps you resume from the updated system state instead of the state you last remember.",
          createdResources: [],
          nextStep: "Open ready work to decide what follows those completions.",
          breadcrumbs: ["Home", "Since last visit", "Completed"],
        },
        actions: [
          buildOpenAction("Open ready work", location, "Review what to do after recent completions"),
          buildPinAction("Pin recap", location, "Resume context after recent completions", "Resume · completed work"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  function buildBlockedSinceLastCard(data: WorkspaceData): PrioritizedCard | null {
    if (!visitBaseline) {
      return null;
    }

    const baselineTime = visitBaseline.getTime();
    const blocked = data.allLoops
      .filter((loop) => loop.status === "blocked" && new Date(loop.updated_at_utc).getTime() > baselineTime)
      .sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc))
      .slice(0, 3);
    if (!blocked.length) {
      return null;
    }

    const location = createLocation({ state: "review", reviewFocus: "cohorts" });
    return {
      priority: 84,
      card: {
        id: "since-last-blocked",
        kind: "decision",
        tone: "attention",
        eyebrow: "Resume signal",
        title: "Newly blocked work",
        summary: `${blocked.length} loop${blocked.length === 1 ? "" : "s"} became blocked since your last visit.`,
        rationale:
          "Blocked-state drift is a strong review signal because it often changes what should happen next across the rest of the system.",
        preview: blocked.map((loop, index) => ({ label: `Blocked ${index + 1}`, value: loopTitle(loop) })),
        trust: {
          contextSources: ["Loop status changes", "Last-visit browser baseline"],
          assumptions: ["Blocked loops may require either review cleanup or recall/context gathering."],
          confidenceLabel: "High-priority resume risk",
          rollbackLabel: "Opening Review does not mutate loop state until you act.",
          freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
        },
        handoff: {
          changeSummary: "These loops changed state while you were away, so the Review surface is the safest place to inspect the drift.",
          createdResources: [],
          nextStep: "Open Review or grounded chat to resolve what blocked these loops.",
          breadcrumbs: ["Home", "Since last visit", "Blocked"],
        },
        actions: [
          buildOpenAction("Open review", location, "Inspect newly blocked loops"),
          buildPinAction("Pin blocker recap", location, "Return to newly blocked-loop recap", "Resume · blocked work"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  function buildFollowUpSinceLastCard(data: WorkspaceData): PrioritizedCard | null {
    if (!visitBaseline) {
      return null;
    }

    const recentExecution = recentPlanningExecutions(data);
    const downstreamGroups = mergePlanningResourceChangeGroups(
      recentExecution.flatMap((item) => item.resource_change_summary?.downstream_groups ?? []),
    );
    const followUpResources = recentExecution
      .flatMap((item) => item.follow_up_resources ?? [])
      .slice(0, 3);

    if (!downstreamGroups.length && !followUpResources.length) {
      return null;
    }

    const primarySurface = firstNavigableLaunchSurface(
      recentExecution.flatMap((item) => item.launch_surfaces ?? []),
    );
    const launchLocation = primarySurface
      ? (launchSurfaceToLocation(primarySurface)
        ?? createLocation({ state: "plan", reviewFocus: "planning", sessionId: data.planningSnapshot?.session?.id ?? null }))
      : createLocation({ state: "plan", reviewFocus: "planning", sessionId: data.planningSnapshot?.session?.id ?? null });
    const propagatedWorkingSetId = launchSurfaceWorkingSetId(primarySurface);
    const propagatedWorkingSetLabel = workingSetLabel(propagatedWorkingSetId);
    const latestDownstreamSummary = recentExecution.at(-1)?.resource_change_summary?.downstream_summary_label;
    const previewItems = followUpResources.length
      ? followUpResources.map((resource, index) => ({
        label: `Follow-up ${index + 1}`,
        value: resource.label || `${resource.resource_type} #${resource.resource_id}`,
      }))
      : buildPlanningResourcePreviewItems(downstreamGroups);
    const card = {
      id: "since-last-handoffs",
      kind: "handoff",
      tone: "progress",
      eyebrow: "Resume signal",
      title: "Plan-created downstream handoffs",
      summary: latestDownstreamSummary
        ?? `${downstreamGroups.reduce((sum, group) => sum + group.count, 0)} downstream resources were created or updated after your last visit.`,
      rationale:
        "Downstream resources are the clearest sign that planning already prepared the next surface or durable artifact for the operator.",
      preview: [
        ...(propagatedWorkingSetLabel ? [{ label: "Working set", value: propagatedWorkingSetLabel }] : []),
        ...previewItems,
      ].slice(0, 4),
      trust: {
        contextSources: [
          "Planning execution history",
          "Typed downstream resource-change summaries",
          "Last-visit browser baseline",
        ],
        assumptions: ["The downstream resources still exist and remain valid resume targets."],
        confidenceLabel: "Prepared resume handoff",
        rollbackLabel: summarizeRollbackCue(recentExecution.at(-1)?.rollback_cues),
        freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
      },
      handoff: {
        changeSummary: "Planning execution produced durable follow-up work while you were away.",
        createdResources: downstreamGroups.length
          ? downstreamGroups.map((group) => group.display_label)
          : followUpResources.map((resource) => resource.operation_summary),
        nextStep: primarySurface?.reason || "Open the prepared handoff or resume the planning workspace to inspect the execution trail.",
        breadcrumbs: ["Home", "Since last visit", "Planning handoffs"],
      },
      actions: [
        buildOpenAction("Open handoff", launchLocation, "Open the newest downstream planning handoff"),
        buildPinAction("Pin handoff recap", launchLocation, "Return to the latest plan-created handoff recap", "Resume · plan handoffs"),
        ...[
          recentExecution.at(-1)
            ? buildPlanningRollbackAction(recentExecution.at(-1)!)
            : null,
        ].filter(isUndoAction),
      ],
    } satisfies OperatorActionCard;
    return {
      priority: 80,
      card: withResolvedWorkingSetHandoff(card, propagatedWorkingSetId),
    } satisfies PrioritizedCard;
  }

  type ContinuityCohortName = keyof ContinuityBaselineSnapshot["cohorts"];

  function lastSeenMarker(entityKind: import("./contracts-ui").ContinuityEntityKind, entityKey: string) {
    return readContinuityLastSeenMarkers().find((marker) => marker.entityKind === entityKind && marker.entityKey === entityKey) ?? null;
  }

  function cohortByName(
    reviewData: LoopReviewResponse,
    cohortName: ContinuityCohortName,
  ): LoopReviewCohortResponse | null {
    return [...reviewData.daily, ...reviewData.weekly].find((item) => item.cohort === cohortName) ?? null;
  }

  function cohortCountDelta(data: WorkspaceData, cohortName: ContinuityCohortName): number {
    const previousCount = continuityBaseline?.cohorts[cohortName].count ?? 0;
    return (cohortByName(data.reviewData, cohortName)?.count ?? 0) - previousCount;
  }

  function previewLoopValue(loop: LoopReviewCohortItem | LoopResponse | null | undefined): string {
    return loop ? loopTitle(loop) : "No loop preview available";
  }

  function planningFreshness(snapshot: PlanningSessionSnapshotResponse | null): {
    isStale: boolean;
    label: string;
    staleTargetLoopCount: number;
    missingTargetLoopCount: number;
    changedTargets: PlanningContextFreshnessTargetChangeResponse[];
    summaryLabel: string;
  } {
    const freshness = snapshot?.context_freshness;
    if (!freshness) {
      return {
        isStale: false,
        label: "No planning freshness metadata",
        staleTargetLoopCount: 0,
        missingTargetLoopCount: 0,
        changedTargets: [],
        summaryLabel: "No planning freshness metadata",
      };
    }

    return {
      isStale: freshness.is_stale,
      label: freshness.summary_label
        ?? `Generated ${formatRelativeTime(snapshot?.session.generated_at_utc ?? snapshot?.session.updated_at_utc ?? null)}`,
      staleTargetLoopCount: freshness.stale_target_loop_count,
      missingTargetLoopCount: freshness.missing_target_loop_count,
      changedTargets: freshness.changed_targets ?? [],
      summaryLabel: freshness.summary_label ?? "Planning freshness available",
    };
  }

  function buildNewlyStaleCard(data: WorkspaceData): PrioritizedCard | null {
    const staleCohort = cohortByName(data.reviewData, "stale");
    const marker = lastSeenMarker("cohort_snapshot", "cohort:stale");
    const drift = summarizeCohortDrift(
      "Stale cohort",
      marker,
      staleCohort?.count ?? 0,
      (staleCohort?.items ?? []).map((item) => item.id),
    );
    if (drift.severity === "none") {
      return null;
    }

    const location = createLocation({ state: "review", reviewFocus: "cohorts" });
    return {
      priority: drift.severity === "major" ? 82 : 76,
      card: {
        id: "since-last-newly-stale",
        kind: "decision",
        tone: drift.severity === "major" ? "attention" : "neutral",
        eyebrow: "Durable drift",
        title: "Loops aged into stale review",
        summary: drift.summary,
        rationale:
          "Stale loops quietly lose trust. Durable cohort markers make that drift survive browser clears and device switches.",
        preview: drift.preview,
        trust: {
          contextSources: ["Live review cohorts", "Durable last-seen cohort marker"],
          assumptions: ["Durable markers reflect the last operator observation of the stale cohort."],
          confidenceLabel: `${drift.severity} stale-work drift`,
          rollbackLabel: "Opening Review remains non-mutating until you edit or close a loop.",
          freshnessLabel: marker ? `Last seen ${formatRelativeTime(marker.observedAtUtc)}` : "Never seen before",
        },
        handoff: {
          changeSummary: drift.summary,
          createdResources: drift.preview.map((item) => item.value),
          nextStep: "Open Review and decide whether to revive, clarify, or close the newly stale work.",
          breadcrumbs: ["Home", "Since last visit", "Stale drift"],
        },
        actions: [
          buildOpenAction("Open stale review", location, drift.summary),
          buildPinAction("Pin stale drift", location, drift.summary, "Resume · stale drift"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  function buildRiskCohortCard(data: WorkspaceData): PrioritizedCard | null {
    const cohortNames: Array<{ key: ContinuityCohortName; label: string }> = [
      { key: "blocked_too_long", label: "Blocked too long" },
      { key: "no_next_action", label: "Missing next action" },
      { key: "due_soon_unplanned", label: "Due soon under-planned" },
      { key: "stale", label: "Stale open" },
    ];
    const driftSignals = cohortNames.map((cohort) => {
      const current = cohortByName(data.reviewData, cohort.key);
      return {
        label: cohort.label,
        drift: summarizeCohortDrift(
          cohort.label,
          lastSeenMarker("cohort_snapshot", `cohort:${cohort.key}`),
          current?.count ?? 0,
          (current?.items ?? []).map((item) => item.id),
        ),
      };
    }).filter((entry) => entry.drift.severity !== "none");
    if (!driftSignals.length) {
      return null;
    }

    const strongest = driftSignals[0]!;
    const location = createLocation({ state: "review", reviewFocus: "cohorts" });
    return {
      priority: strongest.drift.severity === "major" ? 80 : 74,
      card: {
        id: "since-last-risk-cohorts",
        kind: "decision",
        tone: strongest.drift.severity === "major" ? "attention" : "neutral",
        eyebrow: "Risk growth",
        title: "Higher-risk cohorts drifted",
        summary: driftSignals.map((entry) => entry.drift.summary).join(" · "),
        rationale:
          "Growth in risk cohorts is a stronger continuity signal than raw backlog size because it changes where cleanup work should start.",
        preview: driftSignals.flatMap((entry) => entry.drift.preview.slice(0, 1)),
        trust: {
          contextSources: ["/loops/review cohorts", "Durable last-seen cohort markers"],
          assumptions: ["Durable markers reflect the last operator observation of each hygiene cohort."],
          confidenceLabel: `${strongest.drift.severity} deterministic cohort drift`,
          rollbackLabel: "This is diagnostic only until you act inside Review or Do.",
          freshnessLabel: "Compared against durable last-seen cohort markers",
        },
        handoff: {
          changeSummary: "The system has more hygiene risk than it did when these cohorts were last seen.",
          createdResources: driftSignals.map((entry) => entry.drift.summary),
          nextStep: "Open Review and start with the fastest cohort that reduces trust drift.",
          breadcrumbs: ["Home", "Since last visit", "Risk growth"],
        },
        actions: [
          buildOpenAction("Open risk review", location, "Inspect the cohorts that drifted since they were last seen"),
          buildPinAction("Pin risk recap", location, "Return to the risk-growth recap", "Resume · risk growth"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  function buildPlanningDriftCard(data: WorkspaceData): PrioritizedCard | null {
    const current = data.planningSnapshot;
    if (!current?.session) {
      return null;
    }

    const marker = lastSeenMarker("planning_session", `planning:${current.session.id}`);
    const freshness = planningFreshness(current);
    const previousState = (marker?.observedState ?? {}) as {
      contextIsStale?: boolean;
      updatedAtUtc?: string;
      status?: string;
    };
    const markerMissing = marker == null;
    const fingerprintChanged = marker?.observedFingerprint != null
      && marker.observedFingerprint !== buildPlanningLastSeenMarker(current, workingSetContext?.active_working_set_id ?? null)?.observedFingerprint;
    const becameStale = freshness.isStale && !previousState.contextIsStale;
    const severity = markerMissing
      ? "moderate"
      : freshness.isStale || fingerprintChanged
        ? "major"
        : "none";
    if (severity === "none") {
      return null;
    }

    const changedTargetPreview = freshness.changedTargets.slice(0, 2).map((target, index) => ({
      label: `Changed target ${index + 1}`,
      value: `${target.label} · ${(target.changed_fields ?? []).map((field) => formatChangedFieldLabel(field)).join(", ")}`,
    }));
    const location = createLocation({
      state: "plan",
      reviewFocus: "planning",
      sessionId: current.session.id,
    });

    return {
      priority: severity === "major" ? 90 : 76,
      card: {
        id: "since-last-planning-drift",
        kind: "handoff",
        tone: severity === "major" ? "attention" : "neutral",
        eyebrow: "Plan drift",
        title: markerMissing ? "Planning session has never been seen" : "Planning context drifted",
        summary: markerMissing
          ? `${current.session.name} is now active and has not been observed from this durable continuity history yet.`
          : freshness.summaryLabel,
        rationale:
          "Saved plans are only trustworthy when their grounding still matches the real loop state and the operator still knows why this plan is the active one.",
        preview: [
          { label: "Plan", value: current.session.name },
          {
            label: "Freshness",
            value: markerMissing
              ? "Never observed"
              : freshness.label,
          },
          ...(changedTargetPreview.length
            ? changedTargetPreview
            : [
              {
                label: "Checkpoint",
                value: current.current_checkpoint?.title || `Checkpoint ${current.session.current_checkpoint_index + 1}`,
              },
            ]),
        ],
        trust: {
          contextSources: [
            "Planning session snapshot",
            "Typed planning context freshness",
            "Durable last-seen planning marker",
          ],
          assumptions: [
            "Refreshing the plan is the safest next step when target-loop grounding no longer matches current loop state.",
          ],
          confidenceLabel: markerMissing ? "Unseen planning workflow" : freshness.summaryLabel,
          rollbackLabel: "Opening Plan remains non-mutating until you refresh or execute a checkpoint.",
          freshnessLabel: marker?.observedAtUtc
            ? `Last seen ${formatRelativeTime(marker.observedAtUtc)}`
            : "Never seen before",
        },
        handoff: {
          changeSummary: markerMissing
            ? `${current.session.name} is ready to inspect for the first durable observation.`
            : freshness.summaryLabel,
          createdResources: changedTargetPreview.map((item) => item.value),
          nextStep: becameStale || markerMissing
            ? "Open the plan and refresh its context before trusting the next checkpoint."
            : "Open the current plan and confirm it is still the right workflow to resume.",
          breadcrumbs: ["Home", "Since last visit", "Planning drift"],
        },
        actions: [
          requireApiRerunAction(current.rerun_action, {
            sourceLabel: `Planning session ${current.session.name}`,
            variant: "primary",
          }),
          buildOpenAction(
            markerMissing ? "Inspect plan" : "Open current plan",
            location,
            freshness.label,
            "secondary",
          ),
          buildPinAction("Pin planning drift", location, freshness.label, `Plan · ${current.session.name}`),
        ],
      },
    } satisfies PrioritizedCard;
  }

  function buildPlanningResourceRollupCard(data: WorkspaceData): PrioritizedCard | null {
    if (!visitBaseline) {
      return null;
    }

    const recentExecution = recentPlanningExecutions(data);
    const groupedChanges = mergePlanningResourceChangeGroups(
      recentExecution.flatMap((item) => item.resource_change_summary?.groups ?? []),
    );
    if (!groupedChanges.length) {
      return null;
    }

    const latestSummary = recentExecution.at(-1)?.resource_change_summary?.summary_label;
    const location = createLocation({
      state: "plan",
      reviewFocus: "planning",
      sessionId: data.planningSnapshot?.session?.id ?? null,
    });

    return {
      priority: 81,
      card: {
        id: "since-last-planning-resource-rollup",
        kind: "handoff",
        tone: "progress",
        eyebrow: "Changed resources",
        title: "Planning execution changed durable resources",
        summary: latestSummary
          ?? `${groupedChanges.reduce((sum, group) => sum + group.count, 0)} planning-driven resource changes landed since your last visit.`,
        rationale:
          "Checkpoint execution can mutate loops and create durable objects. A grouped rollup shows the true post-execution state without forcing the operator to reconstruct it manually.",
        preview: buildPlanningResourcePreviewItems(groupedChanges),
        trust: {
          contextSources: [
            "Planning execution history",
            "Typed planning resource-change summaries",
            "Last-visit browser baseline",
          ],
          assumptions: [
            "Planning execution history still reflects the canonical durable mutations created after your last visit.",
          ],
          confidenceLabel: "Grouped planning change rollup",
          rollbackLabel: summarizeRollbackCue(recentExecution.at(-1)?.rollback_cues),
          freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
          impactSummary: groupedChanges.map((group) => group.display_label).join(" · "),
        },
        handoff: {
          changeSummary: "Planning checkpoints changed real loops and saved resources while you were away.",
          createdResources: groupedChanges.map((group) => group.display_label),
          nextStep: "Open the planning workspace to inspect the execution trail, then launch into the next updated queue or loop.",
          breadcrumbs: ["Home", "Since last visit", "Planning resource changes"],
        },
        actions: [
          buildOpenAction("Open planning activity", location, "Inspect grouped planning-driven resource changes"),
          buildPinAction("Pin resource rollup", location, "Return to the planning resource rollup", "Resume · planning changes"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  interface GroupedChangeTheme {
    label: string;
    summary: string;
    tone: OperatorActionCard["tone"];
    location: ShellLocation;
  }

  function buildGroupedChangeRollupCard(data: WorkspaceData): PrioritizedCard | null {
    if (!visitBaseline) {
      return null;
    }

    const themes: GroupedChangeTheme[] = [];

    const planningDrift = buildPlanningDriftCard(data);
    const planningDriftAction = planningDrift ? firstLocationAction(planningDrift.card.actions) : null;
    if (planningDrift && planningDriftAction) {
      themes.push({
        label: "Planning drift",
        summary: planningDrift.card.summary,
        tone: planningDrift.card.tone,
        location: planningDriftAction.location,
      });
    }

    const planningResourceRollup = buildPlanningResourceRollupCard(data);
    const planningResourceAction = planningResourceRollup ? firstLocationAction(planningResourceRollup.card.actions) : null;
    if (planningResourceRollup && planningResourceAction) {
      themes.push({
        label: "Planning activity",
        summary: planningResourceRollup.card.summary,
        tone: planningResourceRollup.card.tone,
        location: planningResourceAction.location,
      });
    }

    const queueChange = buildQueueChangeCard(data);
    const queueChangeAction = queueChange ? firstLocationAction(queueChange.card.actions) : null;
    if (queueChange && queueChangeAction) {
      themes.push({
        label: "Review queues",
        summary: queueChange.card.summary,
        tone: queueChange.card.tone,
        location: queueChangeAction.location,
      });
    }

    const riskChange = buildRiskCohortCard(data) ?? buildNewlyStaleCard(data) ?? buildBlockedSinceLastCard(data);
    const riskChangeAction = riskChange ? firstLocationAction(riskChange.card.actions) : null;
    if (riskChange && riskChangeAction) {
      themes.push({
        label: "Loop risk",
        summary: riskChange.card.summary,
        tone: riskChange.card.tone,
        location: riskChangeAction.location,
      });
    }

    const completed = buildCompletedSinceLastCard(data);
    const completedAction = completed ? firstLocationAction(completed.card.actions) : null;
    if (completed && completedAction) {
      themes.push({
        label: "Progress",
        summary: completed.card.summary,
        tone: completed.card.tone,
        location: completedAction.location,
      });
    }

    if (themes.length < 2) {
      return null;
    }

    const primary = themes.find((theme) => theme.tone === "attention") ?? themes[0] ?? null;
    if (!primary) {
      return null;
    }

    return {
      priority: 88,
      card: {
        id: "since-last-grouped-rollup",
        kind: "context",
        tone: themes.some((theme) => theme.tone === "attention") ? "attention" : "neutral",
        eyebrow: "Change rollup",
        title: "Several change themes landed while you were away",
        summary: `${themes.length} grouped change themes were detected since your last visit.`,
        rationale:
          "When multiple deterministic signals land at once, one grouped rollup helps the operator orient before drilling into specific continuity cards.",
        preview: buildGroupedChangePreviewItems(
          themes.map((theme) => ({ label: theme.label, summary: theme.summary })),
        ),
        trust: {
          contextSources: [
            "Planning continuity signals",
            "Review queue/session deltas",
            "Loop state and completion deltas",
            "Last-visit browser baseline",
          ],
          assumptions: ["A grouped summary is useful only when multiple continuity themes changed."],
          confidenceLabel: "Grouped deterministic continuity rollup",
          rollbackLabel: "This rollup is navigational only; mutations remain explicit in downstream surfaces.",
          freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
        },
        handoff: {
          changeSummary: "Planning activity, queue shifts, and/or loop-state drift all moved while you were away.",
          createdResources: themes.map((theme) => `${theme.label}: ${theme.summary}`),
          nextStep: "Open the highest-signal theme first, then work down the rest of the continuity deck.",
          breadcrumbs: ["Home", "Since last visit", "Grouped rollup"],
        },
        actions: [
          buildOpenAction(
            `Open ${primary.label.toLowerCase()}`,
            primary.location,
            primary.summary,
          ),
          buildPinAction("Pin grouped rollup", primary.location, "Return to the grouped continuity rollup", "Resume · grouped change rollup"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  interface QueueShiftSummary {
    key: string;
    label: string;
    summary: string;
    detail: string;
    tone: OperatorActionCard["tone"];
    location: ShellLocation;
  }

  function summarizeQueueShift(
    label: string,
    reviewFocus: Extract<ReviewFocus, "relationship" | "enrichment">,
    snapshot: DecisionSessionSnapshot | null,
    baseline: ContinuityBaselineSnapshot["relationshipSession"] | ContinuityBaselineSnapshot["enrichmentSession"],
  ): QueueShiftSummary | null {
    const session = snapshot?.session ?? null;
    const currentLoopId = snapshot?.current_item?.loop.id ?? session?.current_loop_id ?? null;
    const location = createLocation({
      state: "decide",
      reviewFocus,
      sessionId: session?.id ?? baseline?.sessionId ?? null,
    });

    if (!session && !baseline) {
      return null;
    }
    if (session && !baseline) {
      const loopCount = snapshot?.loop_count ?? 0;
      return {
        key: reviewFocus,
        label,
        summary: `${session.name} is now active with ${loopCount} queued item${loopCount === 1 ? "" : "s"}.`,
        detail: "A saved queue appeared since your last visit.",
        tone: "attention",
        location,
      };
    }
    if (!session && baseline) {
      return {
        key: reviewFocus,
        label,
        summary: `The previously active ${label.toLowerCase()} queue is no longer active.`,
        detail: `Queue #${baseline.sessionId} was active on your last visit.`,
        tone: "progress",
        location,
      };
    }
    if (!session || !baseline) {
      return null;
    }
    if (session.id !== baseline.sessionId) {
      return {
        key: reviewFocus,
        label,
        summary: `${session.name} replaced queue #${baseline.sessionId} as the active ${label.toLowerCase()} workflow.`,
        detail: `${snapshot?.loop_count ?? 0} item${(snapshot?.loop_count ?? 0) === 1 ? "" : "s"} are queued now.`,
        tone: "attention",
        location,
      };
    }

    const loopDelta = (snapshot?.loop_count ?? 0) - baseline.loopCount;
    if (loopDelta !== 0) {
      return {
        key: reviewFocus,
        label,
        summary: `${label} queue ${loopDelta > 0 ? "grew" : "shrank"} by ${Math.abs(loopDelta)} item${Math.abs(loopDelta) === 1 ? "" : "s"}.`,
        detail: `${baseline.loopCount} → ${snapshot?.loop_count ?? 0}`,
        tone: loopDelta > 0 ? "attention" : "progress",
        location,
      };
    }
    if (baseline.currentLoopId !== currentLoopId && currentLoopId != null) {
      return {
        key: reviewFocus,
        label,
        summary: `${label} queue advanced to a different loop while keeping the same size.`,
        detail: `Current loop #${currentLoopId}`,
        tone: "neutral",
        location,
      };
    }
    return null;
  }

  function buildQueueChangeCard(data: WorkspaceData): PrioritizedCard | null {
    const relationshipMarker = data.relationshipSnapshot?.session
      ? lastSeenMarker("review_session", `review:relationship:${data.relationshipSnapshot.session.id}`)
      : null;
    const enrichmentMarker = data.enrichmentSnapshot?.session
      ? lastSeenMarker("review_session", `review:enrichment:${data.enrichmentSnapshot.session.id}`)
      : null;
    const relationshipBaseline = relationshipMarker
      ? {
        sessionId: Number((relationshipMarker.observedState as { sessionId?: number }).sessionId ?? data.relationshipSnapshot?.session?.id ?? 0),
        loopCount: Number((relationshipMarker.observedState as { loopCount?: number }).loopCount ?? 0),
        currentLoopId: Number((relationshipMarker.observedState as { currentLoopId?: number }).currentLoopId ?? 0) || null,
        updatedAtUtc: String((relationshipMarker.observedState as { updatedAtUtc?: string }).updatedAtUtc ?? relationshipMarker.observedAtUtc),
      }
      : null;
    const enrichmentBaseline = enrichmentMarker
      ? {
        sessionId: Number((enrichmentMarker.observedState as { sessionId?: number }).sessionId ?? data.enrichmentSnapshot?.session?.id ?? 0),
        loopCount: Number((enrichmentMarker.observedState as { loopCount?: number }).loopCount ?? 0),
        currentLoopId: Number((enrichmentMarker.observedState as { currentLoopId?: number }).currentLoopId ?? 0) || null,
        updatedAtUtc: String((enrichmentMarker.observedState as { updatedAtUtc?: string }).updatedAtUtc ?? enrichmentMarker.observedAtUtc),
      }
      : null;

    const shifts = [
      summarizeQueueShift("Relationship", "relationship", data.relationshipSnapshot, relationshipBaseline),
      summarizeQueueShift("Enrichment", "enrichment", data.enrichmentSnapshot, enrichmentBaseline),
    ].filter((item): item is QueueShiftSummary => item != null);
    if (!shifts.length) {
      return null;
    }

    const actions: OperatorActionCardAction[] = [];
    shifts.forEach((shift, index) => {
      pushUniqueAction(
        actions,
        buildOpenAction(
          `Open ${shift.label.toLowerCase()} queue`,
          shift.location,
          shift.summary,
          index === 0 ? "primary" : "secondary",
        ),
      );
    });

    return {
      priority: 77,
      card: {
        id: "since-last-queue-changes",
        kind: "decision",
        tone: shifts.some((shift) => shift.tone === "attention") ? "attention" : "neutral",
        eyebrow: "Queue change",
        title: "Saved review queues shifted",
        summary: shifts.map((shift) => shift.summary).join(" · "),
        rationale:
          "Saved queues are durable operator workflows, so changes to their size or active session are high-signal continuity events.",
        preview: shifts.map((shift) => ({ label: shift.label, value: shift.detail })),
        trust: {
          contextSources: ["Saved review session snapshots", "Durable last-seen review markers"],
          assumptions: ["The newest relationship and enrichment sessions remain the operator-visible queues to resume."],
          confidenceLabel: `${shifts.length} queue change${shifts.length === 1 ? "" : "s"} detected`,
          rollbackLabel: "Opening a queue remains non-mutating until you confirm or reject work inside it.",
          freshnessLabel: "Compared against durable last-seen review markers",
        },
        handoff: {
          changeSummary: "The saved review queues no longer match the state you last saw.",
          createdResources: shifts.map((shift) => `${shift.label}: ${shift.detail}`),
          nextStep: "Open the queue that changed most and confirm whether it is still the right next workflow.",
          breadcrumbs: ["Home", "Since last visit", "Queue changes"],
        },
        actions,
      },
    } satisfies PrioritizedCard;
  }

  function buildRepeatedSnoozeCard(data: WorkspaceData): PrioritizedCard | null {
    if (!visitBaseline) {
      return null;
    }

    const baselineTime = visitBaseline.getTime();
    const snoozeActions = readRecentShellActions().filter((entry) => {
      return entry.kind === "snooze" && Date.parse(entry.occurredAt) > baselineTime;
    });
    const baselineSnoozedIds = new Set((continuityBaseline?.snoozedLoops ?? []).map((item) => item.id));
    const newlySnoozedLoops = sortLoopsByMostRecentUpdate(data.allLoops.filter((loop) => {
      return typeof loop.snooze_until_utc === "string"
        && loop.snooze_until_utc.trim().length > 0
        && !baselineSnoozedIds.has(loop.id);
    }));
    if (snoozeActions.length < 2 && newlySnoozedLoops.length < 2) {
      return null;
    }

    const snoozeSignal = buildRepeatedSnoozeSignal(snoozeActions, newlySnoozedLoops, loopTitle);
    const primaryLocation = snoozeActions.find((entry) => entry.location)?.location
      ?? (newlySnoozedLoops[0] ? createLocation({ state: "do", loopId: newlySnoozedLoops[0].id }) : createLocation({ state: "do" }));
    return {
      priority: 70,
      card: {
        id: "since-last-repeated-snooze",
        kind: "context",
        tone: "attention",
        eyebrow: "Deferral signal",
        title: "Repeated snoozes may be hiding drift",
        summary: snoozeActions.length
          ? `${snoozeActions.length} snooze action${snoozeActions.length === 1 ? "" : "s"} were recorded since your last visit.`
          : `${newlySnoozedLoops.length} additional loop${newlySnoozedLoops.length === 1 ? "" : "s"} are currently snoozed.`,
        rationale:
          "Repeated deferral is often a sign that a loop needs reframing, a stronger next action, or an explicit drop decision.",
        preview: snoozeSignal.preview,
        trust: {
          contextSources: snoozeSignal.contextSources,
          assumptions: snoozeSignal.assumptions,
          confidenceLabel: "Deterministic deferral pattern",
          rollbackLabel: "This card is diagnostic only; inspect the loops before changing anything.",
          freshnessLabel: `Compared to ${formatTimestamp(visitBaseline.toISOString())}`,
        },
        handoff: {
          changeSummary: "More work has been deferred since your last visit.",
          createdResources: newlySnoozedLoops.slice(0, 3).map((loop) => loopTitle(loop)),
          nextStep: "Open the most recent deferred loop and decide whether to resume, reframe, or drop it.",
          breadcrumbs: ["Home", "Since last visit", "Repeated snoozes"],
        },
        actions: [
          buildOpenAction("Inspect deferred work", createLocation(primaryLocation), "Review the most recent snoozed loop or queue"),
          buildPinAction("Pin deferral recap", createLocation(primaryLocation), "Return to the repeated-snooze recap", "Resume · deferred work"),
        ],
      },
    } satisfies PrioritizedCard;
  }

  function isLocationAction(
    action: OperatorActionCardAction,
  ): action is Extract<OperatorActionCardAction, { location: unknown }> {
    return action.type === "open"
      || action.type === "pin"
      || action.type === "stage"
      || action.type === "edit"
      || action.type === "defer"
      || action.type === "recover";
  }

  function firstLocationAction(
    actions: readonly OperatorActionCardAction[],
  ): Extract<OperatorActionCardAction, { location: unknown }> | null {
    return actions.find((action): action is Extract<OperatorActionCardAction, { location: unknown }> => isLocationAction(action)) ?? null;
  }

  function pushUniqueAction(actions: OperatorActionCardAction[], action: OperatorActionCardAction): void {
    const existing = actions.some((candidate) => {
      if (!isLocationAction(candidate) || !isLocationAction(action)) {
        return false;
      }
      return candidate.type === action.type && locationsMatch(candidate.location, action.location);
    });
    if (!existing) {
      actions.push(action);
    }
  }

  function currentWorkingSetHandoffMetadata(): WorkingSetSessionMetadata | null {
    return workingSetHandoffMetadata(workingSetContext?.active_working_set_id ?? null);
  }

  function withWorkingSetHandoff(cards: OperatorActionCard[]): OperatorActionCard[] {
    const workingSet = currentWorkingSetHandoffMetadata();
    if (!workingSet) {
      return cards;
    }
    return cards.map((card) => {
      if (!card.handoff || card.handoff.workingSet != null) {
        return card;
      }
      return {
        ...card,
        handoff: {
          ...card.handoff,
          workingSet,
        },
      };
    });
  }

  interface FollowThroughModel {
    summaries: ReturnType<typeof readMergedRankedWorkflowSummaries>;
    recommendation: ReturnType<typeof derivePrimaryRecommendation>;
  }

  function followThroughModel(_data: WorkspaceData): FollowThroughModel {
    const summaries = readMergedRankedWorkflowSummaries();
    const recommendation = derivePrimaryRecommendation(summaries);

    return {
      summaries,
      recommendation,
    };
  }

  function followThroughFeed(data: WorkspaceData) {
    return followThroughModel(data).summaries;
  }

  function buildFollowThroughCards(
    summaries: readonly ReturnType<typeof readMergedRankedWorkflowSummaries>[number][],
    excludedSummaryId: string | null,
  ): PrioritizedCard[] {
    return summaries
      .filter((item) => item.id !== excludedSummaryId && (item.recovery == null || item.recovery.acknowledged))
      .slice(0, 3)
      .map((item, index) => ({
        priority: 120 - index * 5,
        card: item.card,
      }));
  }

  function buildRecoveryCards(
    summaries: readonly ReturnType<typeof readMergedRankedWorkflowSummaries>[number][],
    excludedSummaryId: string | null,
  ): PrioritizedCard[] {
    return summaries
      .filter((item) => item.id !== excludedSummaryId && item.recovery != null && !item.recovery.acknowledged)
      .slice(0, 2)
      .map((item, index) => ({
        priority: 129 - index * 3,
        card: index === 0
          ? {
            ...item.card,
            emphasis: "primary",
          }
          : item.card,
      }));
  }

  function buildNotificationInboxCards(
    summaries: readonly ReturnType<typeof readMergedRankedWorkflowSummaries>[number][],
  ): PrioritizedCard[] {
    const summaryById = new Map(summaries.map((summary) => [summary.id, summary]));
    return readActiveContinuityNotificationRecords()
      .flatMap((notification, index) => {
        const summary = summaryById.get(notification.id);
        if (!summary) {
          return [];
        }
        const unseen = notification.state.seenAtUtc == null;
        const actions: OperatorActionCardAction[] = [
          {
            type: "open",
            label: unseen ? "Open workflow" : "Open again",
            variant: "primary",
            description: notification.body,
            location: notification.resolvedLocation,
          },
          {
            type: "acknowledge",
            label: "Acknowledge",
            variant: "secondary",
            description: "Remove this notification from operator surfaces.",
            acknowledgementKey: `notification:${notification.id}`,
          },
          {
            type: "event",
            label: "Hide for 1 day",
            variant: "secondary",
            description: "Suppress this notification across operator surfaces for one day.",
            attributes: {
              "data-notification-suppress-id": notification.id,
              "data-notification-suppress-hours": "24",
            },
          },
        ];
        const tone = notification.severity === "alert"
          ? "attention"
          : notification.severity === "warning"
            ? "caution"
            : "neutral";
        return [{
          priority: 127 - index * 2,
          card: continuitySurfaceCard(summary, {
            id: `notification-${notification.id}`,
            kind: "context",
            tone,
            eyebrow: unseen ? "New notification" : "Notification inbox",
            title: notification.title,
            summary: notification.body,
            rationale:
              "This card exposes the durable continuity notification in operator home instead of relying on banner-only delivery.",
            actions,
            actionContextLabel: "Inbox controls",
            recovery: null,
          }),
        } satisfies PrioritizedCard];
      })
      .slice(0, 3);
  }

  function buildWorkflowThreadRollupCards(
    summaries: readonly ReturnType<typeof readMergedRankedWorkflowSummaries>[number][],
    excludedSummaryId: string | null,
  ): PrioritizedCard[] {
    return summaries
      .filter((summary) => summary.id !== excludedSummaryId && summary.outcomeCount > 1)
      .slice(0, 3)
      .map((summary, index) => ({
        priority: 118 - index * 4,
        card: continuitySurfaceCard(summary, {
          id: `workflow-thread-${summary.id}`,
          eyebrow: "Workflow thread",
          title: summary.workflowThread.title,
          summary: summary.workflowThread.summary ?? `${summary.outcomeCount} related outcomes landed in this workflow thread.`,
          rationale:
            "Related receipts, reruns, and downstream handoffs should read as one workflow thread instead of disconnected event fragments.",
          preview: [
            { label: "Latest", value: summary.displayTitle },
            { label: "Outcomes", value: `${summary.outcomeCount}` },
            ...summary.outcomePreviewTitles.slice(0, 2).map((value, itemIndex) => ({
              label: `Step ${itemIndex + 1}`,
              value,
            })),
          ],
        }),
      }));
  }

  function buildSinceLastCards(data: WorkspaceData): OperatorActionCard[] {
    const model = followThroughModel(data);
    const excludedSummaryId = model.recommendation?.summary.id ?? null;
    const prioritized: PrioritizedCard[] = [
      ...(model.recommendation
        ? [{ priority: 132, card: buildPrimaryRecommendationDigestCard(model.recommendation) }]
        : []),
      ...buildRecoveryCards(model.summaries, excludedSummaryId),
      ...buildNotificationInboxCards(model.summaries),
      ...buildWorkflowThreadRollupCards(model.summaries, excludedSummaryId),
      ...buildFollowThroughCards(model.summaries, excludedSummaryId),
    ];
    const maybeCards = [
      buildPlanningDriftCard(data),
      buildGroupedChangeRollupCard(data),
      buildBlockedSinceLastCard(data),
      buildNewlyStaleCard(data),
      buildPlanningResourceRollupCard(data),
      buildFollowUpSinceLastCard(data),
      buildRiskCohortCard(data),
      buildQueueChangeCard(data),
      buildRepeatedSnoozeCard(data),
      buildCompletedSinceLastCard(data),
    ];
    maybeCards.forEach((entry) => {
      if (entry) {
        prioritized.push(entry);
      }
    });
    return prioritized
      .sort((left, right) => right.priority - left.priority)
      .map((entry) => entry.card);
  }

  function renderNowZone(data: WorkspaceData): void {
    if (!elements) {
      return;
    }

    elements.operatorNow.innerHTML = renderActionCardDeck(
      withWorkingSetHandoff(filterCardsForFocus(buildNowCards(data))),
      `
      <p class="operator-empty">No ready work surfaced right now. Capture something new or use Recall to ask the system what changed.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="capture">Capture work</button>
        <button class="secondary" type="button" data-open-state="recall" data-open-recall-tool="chat">Ask grounded chat</button>
      </div>
    `,
    );
  }

  function renderDecisionsZone(data: WorkspaceData): void {
    if (!elements) {
      return;
    }

    elements.operatorDecisions.innerHTML = renderActionCardDeck(
      withWorkingSetHandoff(filterCardsForFocus(buildDecisionCards(data))),
      `
      <p class="operator-empty">No saved decision queues are active right now. Review remains available when you want a broader hygiene pass.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="review">Open review cohorts</button>
        <button class="secondary" type="button" data-open-state="plan">Start planning</button>
      </div>
    `,
    );
  }

  function renderPlanZone(data: WorkspaceData): void {
    if (!elements) {
      return;
    }

    elements.operatorPlan.innerHTML = renderActionCardDeck(
      withWorkingSetHandoff(filterCardsForFocus(buildPlanCards(data))),
      `
      <p class="operator-empty">No saved planning session is active yet. Start a checkpointed plan when you need a multi-step operational pass.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="plan">Open planning workspace</button>
      </div>
    `,
    );
  }

  function renderRecallZone(data: WorkspaceData): void {
    if (!elements) {
      return;
    }

    elements.operatorRecall.innerHTML = renderActionCardDeck(
      withWorkingSetHandoff(filterCardsForFocus(buildRecallCards(data))),
      `
      <p class="operator-empty">Recall suggestions will appear here when chat, memory, or documents are the clearest next support surface.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="recall" data-open-recall-tool="chat">Open grounded chat</button>
      </div>
    `,
    );
  }

  function renderSinceLastVisit(data: WorkspaceData): void {
    if (!elements) {
      return;
    }

    const sinceLastCards = withWorkingSetHandoff(filterCardsForFocus(buildSinceLastCards(data)));

    if (!visitBaseline && sinceLastCards.length === 0) {
      const durableWarmStartCards = withWorkingSetHandoff(
        filterCardsForFocus(
          followThroughFeed(data)
            .slice(0, 1)
            .map((item) => item.card),
        ),
      );
      if (durableWarmStartCards.length) {
        elements.operatorSinceLast.innerHTML = renderActionCardDeck(
          durableWarmStartCards,
          `
          <p class="operator-empty">No major changes were recorded since your last visit. This is a calm resume state.</p>
          <div class="operator-inline-actions">
            <button type="button" data-open-state="do">Open ready work</button>
            <button class="secondary" type="button" data-open-state="review">Run review</button>
          </div>
        `,
        );
        return;
      }

      elements.operatorSinceLast.innerHTML = `
      <p class="operator-empty">This is the first recorded visit in this browser and there is no durable continuity history yet, so the workspace is showing the current system state instead of a delta.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="operator">Stay in workspace</button>
        <button class="secondary" type="button" data-open-state="recall" data-open-recall-tool="chat">Ask what matters now</button>
      </div>
    `;
      return;
    }

    elements.operatorSinceLast.innerHTML = renderActionCardDeck(
      sinceLastCards,
      `
      <p class="operator-empty">No major changes were recorded since your last visit. This is a calm resume state.</p>
      <div class="operator-inline-actions">
        <button type="button" data-open-state="do">Open ready work</button>
        <button class="secondary" type="button" data-open-state="review">Run review</button>
      </div>
    `,
    );

    queueMicrotask(() => {
      const workingSetId = workingSetContext?.active_working_set_id ?? null;
      const markers = [
        buildPlanningLastSeenMarker(data.planningSnapshot, workingSetId),
        buildReviewLastSeenMarker({
          reviewFocus: "relationship",
          snapshot: data.relationshipSnapshot,
          workingSetId,
        }),
        buildReviewLastSeenMarker({
          reviewFocus: "enrichment",
          snapshot: data.enrichmentSnapshot,
          workingSetId,
        }),
        buildCohortLastSeenMarker({ cohort: "stale", reviewData: data.reviewData, workingSetId }),
        buildCohortLastSeenMarker({ cohort: "blocked_too_long", reviewData: data.reviewData, workingSetId }),
        buildCohortLastSeenMarker({ cohort: "due_soon_unplanned", reviewData: data.reviewData, workingSetId }),
        buildCohortLastSeenMarker({ cohort: "no_next_action", reviewData: data.reviewData, workingSetId }),
        ...followThroughFeed(data)
          .slice(0, 4)
          .map((item) => buildWorkflowSummaryLastSeenMarker({
            summaryId: item.id,
            workflowThreadId: item.workflowThread.id,
            workingSetId: item.workingSetId,
            latestOutcomeId: item.latestOutcomeId,
            title: item.workflowThread.title,
            summary: item.workflowThread.summary,
          })),
      ].filter((value): value is NonNullable<typeof value> => value != null);

      rememberContinuityObservation(markers);
    });
  }



  return {
    renderNowZone(data): void {
      syncContext();
      renderNowZone(data);
    },
    renderDecisionsZone(data): void {
      syncContext();
      renderDecisionsZone(data);
    },
    renderPlanZone(data): void {
      syncContext();
      renderPlanZone(data);
    },
    renderRecallZone(data): void {
      syncContext();
      renderRecallZone(data);
    },
    renderSinceLastVisit(data): void {
      syncContext();
      renderSinceLastVisit(data);
    },
    renderOperatorZones(data): void {
      syncContext();
      renderNowZone(data);
      renderDecisionsZone(data);
      renderPlanZone(data);
      renderRecallZone(data);
      renderSinceLastVisit(data);
    },
  };
}
