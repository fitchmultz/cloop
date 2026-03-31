/**
 * shell-types.ts - Shared operator-shell TypeScript contracts.
 *
 * Purpose:
 *   Centralize the shell's shared interfaces and aliases so focused shell
 *   modules can collaborate without re-declaring inline contract types.
 *
 * Responsibilities:
 *   - Define shared shell location, workspace-data, and DOM element contracts.
 *   - Type the shell's runtime dependency boundary with the surface registry.
 *   - Keep extracted shell modules aligned on one source of truth.
 *
 * Scope:
 *   - Frontend operator-shell contracts only.
 *
 * Usage:
 *   - Import these types from extracted shell modules and the shell coordinator.
 *
 * Invariants/Assumptions:
 *   - Backend DTOs still come from frontend/src/domain.ts.
 *   - Browser-only shell state continues to use frontend/src/contracts-ui.ts.
 */

import type {
  ClarificationResponse,
  EnrichmentReviewSessionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  LoopMetricsResponse,
  LoopResponse,
  LoopReviewResponse,
  NowFeedResponse,
  PlanningSessionResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewSessionResponse,
  RelationshipReviewSessionSnapshotResponse,
} from "./domain";
import type { RecallTool, ReviewFocus, ShellLocationContract, ShellState } from "./contracts-ui";
import type { FrontendSurfaceRegistry } from "./surface-runtime";

export type ShellLocation = ShellLocationContract;

export interface ShellLocationInput {
  state?: ShellState | undefined;
  recallTool?: RecallTool | undefined;
  reviewFocus?: ReviewFocus | null | undefined;
  sessionId?: number | null | undefined;
  loopId?: number | null | undefined;
  viewId?: number | null | undefined;
  memoryId?: number | null | undefined;
  workingSetId?: number | null | undefined;
  query?: string | null | undefined;
}

export interface WorkspaceData {
  nowFeed: NowFeedResponse;
  reviewData: LoopReviewResponse;
  metrics: LoopMetricsResponse;
  planningSessions: PlanningSessionResponse[];
  planningSnapshot: PlanningSessionSnapshotResponse | null;
  relationshipSessions: RelationshipReviewSessionResponse[];
  relationshipSnapshot: RelationshipReviewSessionSnapshotResponse | null;
  enrichmentSessions: EnrichmentReviewSessionResponse[];
  enrichmentSnapshot: EnrichmentReviewSessionSnapshotResponse | null;
  allLoops: LoopResponse[];
}

export interface ShellElements {
  operatorMain: HTMLElement;
  inboxMain: HTMLElement;
  nextMain: HTMLElement;
  reviewMain: HTMLElement;
  chatMain: HTMLElement;
  memoryMain: HTMLElement;
  ragMain: HTMLElement;
  workingSetMain: HTMLElement;
  shellTitle: HTMLElement;
  shellDescription: HTMLElement;
  shellContext: HTMLElement;
  shellRoutePill: HTMLElement;
  shellLastVisit: HTMLElement;
  shellReceiptRail: HTMLElement;
  shellPrimaryAction: HTMLButtonElement;
  refreshWorkspaceButton: HTMLButtonElement;
  commandPaletteButton: HTMLButtonElement;
  createWorkingSetButton: HTMLButtonElement;
  stateButtons: HTMLButtonElement[];
  recallSubnav: HTMLElement;
  recallButtons: HTMLButtonElement[];
  operatorNow: HTMLElement;
  operatorDecisions: HTMLElement;
  operatorPlan: HTMLElement;
  operatorRecall: HTMLElement;
  operatorSinceLast: HTMLElement;
  operatorWorkingSet: HTMLElement;
  workingSetFocusBanner: HTMLElement;
  workingSetFocusSummary: HTMLElement;
  workingSetFocusItems: HTMLElement;
  workingSetFocusToggleButton: HTMLButtonElement;
  workingSetExitFocusButton: HTMLButtonElement;
}

export interface ShellRuntimeDependencies {
  surfaces: FrontendSurfaceRegistry;
}

export interface StateDescriptor {
  title: string;
  description: string;
  context: string;
  pill: string;
  primaryActionLabel: string;
  primaryActionLocation: ShellLocation;
}

export type DecisionSessionSnapshot =
  | RelationshipReviewSessionSnapshotResponse
  | EnrichmentReviewSessionSnapshotResponse;

export type ContinuityCohortName = "stale" | "blocked_too_long" | "due_soon_unplanned" | "no_next_action";

export interface PrioritizedCard {
  priority: number;
  card: import("./contracts-ui").OperatorActionCard;
}

export interface QueueShiftSummary {
  key: string;
  label: string;
  summary: string;
  detail: string;
  tone: import("./contracts-ui").OperatorActionCard["tone"];
  location: ShellLocation;
}

export type GroupedChangeTheme = {
  label: string;
  summary: string;
  tone: import("./contracts-ui").OperatorActionCard["tone"];
  location: ShellLocation;
};

export type PreviewClarification = ClarificationResponse;
