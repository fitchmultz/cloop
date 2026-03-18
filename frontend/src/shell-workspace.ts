/**
 * shell-workspace.ts - Operator workspace data loading and refresh orchestration.
 *
 * Purpose:
 *   Centralize the shell's workspace fetch and render pipeline so operator-zone
 *   refreshes stay separate from routing and event wiring concerns.
 *
 * Responsibilities:
 *   - Load operator workspace API data and primary session snapshots.
 *   - Manage the shell's latest workspace cache and loading guard.
 *   - Render operator zones together with working-set state refresh.
 *   - Persist continuity baselines after a successful workspace render.
 *
 * Scope:
 *   - Operator workspace loading/render orchestration only.
 *
 * Usage:
 *   - Created by frontend/src/shell.ts and used by routing and event modules.
 *
 * Invariants/Assumptions:
 *   - Shared HTTP routes remain the canonical workspace data sources.
 *   - Operator rendering remains idempotent across repeated refresh requests.
 *   - Continuity baselines are browser-local and only persist after success.
 */

import { requestJson } from "./http";
import {
  buildContinuityBaseline,
  readContinuityBaseline,
  writeContinuityBaseline,
} from "./continuity-intelligence";
import type {
  ContinuityBaselineSnapshot,
} from "./contracts-ui";
import type {
  EnrichmentReviewSessionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewResponse,
  NextLoopsResponse,
  PlanningSessionResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewSessionResponse,
  RelationshipReviewSessionSnapshotResponse,
} from "./domain";
import type { ShellElements, ShellLocation, WorkspaceData } from "./shell-types";

export interface ShellWorkspaceController {
  getLatestWorkspaceData(): WorkspaceData | null;
  loadWorkspaceData(): Promise<WorkspaceData>;
  renderOperatorWorkspace(): Promise<void>;
}

interface CreateShellWorkspaceControllerOptions {
  getElements: () => ShellElements | null;
  getCurrentLocation: () => ShellLocation;
  getVisitStatePersisted: () => boolean;
  setVisitStatePersisted: (value: boolean) => void;
  setContinuityBaseline: (value: ContinuityBaselineSnapshot | null) => void;
  writeLastVisitNow: () => void;
  getWorkingSetContext: () => import("./domain").WorkingSetContextResponse | null;
  loadWorkingSetState: () => Promise<void>;
  renderOperatorZones: (data: WorkspaceData) => void;
  renderWorkingSet: (data: WorkspaceData | null) => void;
  renderWorkingSetFocusBanner: () => void;
  syncFocusModeClass: () => void;
  renderWorkingSetSessionSurface: () => void;
}

export function createShellWorkspaceController(
  options: CreateShellWorkspaceControllerOptions,
): ShellWorkspaceController {
  let latestWorkspaceData: WorkspaceData | null = null;
  let workspaceLoading = false;

  async function safeRequest<T>(factory: () => Promise<T>, fallback: T): Promise<T> {
    try {
      return await factory();
    } catch {
      return fallback;
    }
  }

  function sortSessionsByUpdated<T extends { updated_at_utc: string }>(items: T[]): T[] {
    return [...items].sort((left, right) => right.updated_at_utc.localeCompare(left.updated_at_utc));
  }

  async function loadWorkspaceData(): Promise<WorkspaceData> {
    const [
      nextLoops,
      reviewData,
      metrics,
      planningSessionsRaw,
      relationshipSessionsRaw,
      enrichmentSessionsRaw,
      allLoops,
    ] = await Promise.all([
      safeRequest(
        () => requestJson<NextLoopsResponse>("/loops/next?limit=8", {}, "Failed to load next actions"),
        { due_soon: [], high_leverage: [], quick_wins: [], standard: [] },
      ),
      safeRequest(
        () =>
          requestJson<LoopReviewResponse>(
            "/loops/review?daily=true&weekly=true&limit=50",
            {},
            "Failed to load review data",
          ),
        { daily: [], generated_at_utc: new Date(0).toISOString(), weekly: [] },
      ),
      safeRequest(
        () => requestJson<LoopMetricsResponse>("/loops/metrics", {}, "Failed to load loop metrics"),
        {
          generated_at_utc: new Date(0).toISOString(),
          total_loops: 0,
          status_counts: {
            inbox: 0,
            actionable: 0,
            blocked: 0,
            scheduled: 0,
            completed: 0,
            dropped: 0,
          },
          stale_open_count: 0,
          blocked_too_long_count: 0,
          no_next_action_count: 0,
          enrichment_pending_count: 0,
          enrichment_failed_count: 0,
          capture_count_24h: 0,
          completion_count_24h: 0,
          avg_age_open_hours: null,
          project_breakdown: null,
          trend_metrics: null,
        },
      ),
      safeRequest(
        () => requestJson<PlanningSessionResponse[]>("/loops/planning/sessions", {}, "Failed to load planning sessions"),
        [],
      ),
      safeRequest(
        () =>
          requestJson<RelationshipReviewSessionResponse[]>(
            "/loops/review/relationship/sessions",
            {},
            "Failed to load relationship review sessions",
          ),
        [],
      ),
      safeRequest(
        () =>
          requestJson<EnrichmentReviewSessionResponse[]>(
            "/loops/review/enrichment/sessions",
            {},
            "Failed to load enrichment review sessions",
          ),
        [],
      ),
      safeRequest(
        () => requestJson<LoopResponse[]>("/loops/?status=all", {}, "Failed to load loops"),
        [],
      ),
    ]);

    const planningSessions = sortSessionsByUpdated(planningSessionsRaw);
    const relationshipSessions = sortSessionsByUpdated(relationshipSessionsRaw);
    const enrichmentSessions = sortSessionsByUpdated(enrichmentSessionsRaw);
    const primaryPlanningSession = planningSessions[0] ?? null;
    const primaryRelationshipSession = relationshipSessions[0] ?? null;
    const primaryEnrichmentSession = enrichmentSessions[0] ?? null;

    const [planningSnapshot, relationshipSnapshot, enrichmentSnapshot] = await Promise.all([
      primaryPlanningSession
        ? safeRequest(
            () =>
              requestJson<PlanningSessionSnapshotResponse>(
                `/loops/planning/sessions/${primaryPlanningSession.id}`,
                {},
                "Failed to load planning snapshot",
              ),
            null,
          )
        : Promise.resolve(null),
      primaryRelationshipSession
        ? safeRequest(
            () =>
              requestJson<RelationshipReviewSessionSnapshotResponse>(
                `/loops/review/relationship/sessions/${primaryRelationshipSession.id}`,
                {},
                "Failed to load relationship review snapshot",
              ),
            null,
          )
        : Promise.resolve(null),
      primaryEnrichmentSession
        ? safeRequest(
            () =>
              requestJson<EnrichmentReviewSessionSnapshotResponse>(
                `/loops/review/enrichment/sessions/${primaryEnrichmentSession.id}`,
                {},
                "Failed to load enrichment review snapshot",
              ),
            null,
          )
        : Promise.resolve(null),
    ]);

    return {
      nextLoops,
      reviewData,
      metrics,
      planningSessions,
      planningSnapshot,
      relationshipSessions,
      relationshipSnapshot,
      enrichmentSessions,
      enrichmentSnapshot,
      allLoops,
    };
  }

  function persistVisitStateOnce(): void {
    if (options.getVisitStatePersisted() || !latestWorkspaceData) {
      return;
    }
    writeContinuityBaseline(
      buildContinuityBaseline({
        metrics: latestWorkspaceData.metrics,
        reviewData: latestWorkspaceData.reviewData,
        planningSnapshot: latestWorkspaceData.planningSnapshot,
        relationshipSnapshot: latestWorkspaceData.relationshipSnapshot,
        enrichmentSnapshot: latestWorkspaceData.enrichmentSnapshot,
        allLoops: latestWorkspaceData.allLoops,
        workingSetContext: options.getWorkingSetContext(),
      }),
    );
    options.setContinuityBaseline(readContinuityBaseline());
    options.writeLastVisitNow();
    options.setVisitStatePersisted(true);
  }

  async function renderOperatorWorkspace(): Promise<void> {
    const elements = options.getElements();
    if (!elements || workspaceLoading) {
      return;
    }
    workspaceLoading = true;
    elements.operatorNow.innerHTML = '<p class="operator-empty">Loading prioritized work…</p>';
    elements.operatorDecisions.innerHTML = '<p class="operator-empty">Loading decision surfaces…</p>';
    elements.operatorPlan.innerHTML = '<p class="operator-empty">Loading planning sessions…</p>';
    elements.operatorRecall.innerHTML = '<p class="operator-empty">Preparing recall suggestions…</p>';
    elements.operatorSinceLast.innerHTML = '<p class="operator-empty">Comparing recent activity…</p>';

    try {
      const [workspaceData] = await Promise.all([loadWorkspaceData(), options.loadWorkingSetState()]);
      latestWorkspaceData = workspaceData;
      options.renderOperatorZones(latestWorkspaceData);
      options.renderWorkingSet(latestWorkspaceData);
      options.renderWorkingSetFocusBanner();
      options.syncFocusModeClass();
      if (options.getCurrentLocation().state === "working_set") {
        options.renderWorkingSetSessionSurface();
      }
      persistVisitStateOnce();
    } finally {
      workspaceLoading = false;
    }
  }

  return {
    getLatestWorkspaceData: (): WorkspaceData | null => latestWorkspaceData,
    loadWorkspaceData,
    renderOperatorWorkspace,
  };
}
