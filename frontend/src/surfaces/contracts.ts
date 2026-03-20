/**
 * contracts.ts - Shared TypeScript contracts for the surface runtime.
 *
 * Purpose:
 *   Centralize browser-side types used by the capture, do, and recall surface
 *   modules so the final Vite cutover does not rely on ad-hoc implicit types.
 *
 * Responsibilities:
 *   - Define shared loop, timer, comment, memory, and suggestion contracts.
 *   - Define common DOM element maps passed between surface modules.
 *   - Keep surface-local types close to the surface runtime implementation.
 *
 * Scope:
 *   - TypeScript contracts for frontend/src/surfaces/* only.
 *
 * Usage:
 *   - Import types from this module in surface modules instead of re-declaring
 *     inline Record/unknown shapes repeatedly.
 *
 * Invariants/Assumptions:
 *   - Backend-owned schema aliases should come from frontend/src/domain.ts.
 *   - SurfaceLoop extends LoopResponse with browser-only timer/search fields.
 */

import type { ChatMessage, ChatPreferences, ChatToolMode, ReviewMode } from "../contracts-ui";
import type {
  ApplySuggestionResponse,
  BulkCloseResponse,
  BulkEnrichResponse,
  BulkSnoozeResponse,
  BulkUpdateResponse,
  ClarificationListResponse,
  ClarificationRefinementResponse,
  ClarificationResponse,
  ClarificationSubmitBatchRequest,
  ClarificationSubmitResponse,
  DuplicateCandidateResponse,
  DuplicatesListResponse,
  EnrichmentReviewActionResponse,
  EnrichmentReviewSessionClarificationResponse,
  EnrichmentReviewSessionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  IngestResponse,
  LoopCommentCreateRequest,
  LoopCommentListResponse,
  LoopCommentResponse,
  LoopResponse,
  LoopReviewResponse,
  LoopSemanticSearchResponse,
  LoopTemplateResponse,
  LoopViewResponse,
  MemoryEntryResponse,
  MemoryListResponse,
  MemorySearchResponse,
  MergePreviewResponse,
  NextLoopsResponse,
  PlanningSessionExecuteResponse,
  PlanningSessionResponse,
  PlanningSessionSnapshotResponse,
  RejectSuggestionResponse,
  RelationshipReviewActionResponse,
  RelationshipReviewSessionActionResponse,
  RelationshipReviewSessionResponse,
  RelationshipReviewSessionSnapshotResponse,
  SuggestionResponse,
  TimeSessionResponse,
  TimerStatusResponse,
} from "../domain";

export type {
  ClarificationResponse,
  NextLoopsResponse,
  SuggestionResponse,
  TimeSessionResponse,
};

export type LegacySurfaceTab = "inbox" | "next" | "chat" | "memory" | "rag";
export type QueryMode = "dsl" | "semantic";
export type SurfaceStatusMessageTarget = HTMLElement | null;

export interface SurfaceLoop extends LoopResponse {
  timer_running?: boolean;
  timer_display?: string;
  total_tracked_minutes?: number;
  semantic_score?: number | null;
}

export interface SurfaceChatRequestMessage {
  role: string;
  content: string;
}

export interface SelectorResolutionStatus {
  requested_selector?: string | null;
  requested_selectors?: string[] | null;
  resolved_selector?: string | null;
  fallback_used?: boolean | null;
  selector_mode?: string | null;
  error?: string | null;
}

export interface HealthStatusResponse {
  tool_mode_default?: ChatToolMode | "manual" | string | null;
  chat_selector?: SelectorResolutionStatus | null;
  organizer_selector?: SelectorResolutionStatus | null;
  [key: string]: unknown;
}

export interface ActiveTimerRecord {
  session_id: number | null;
  started_at: Date;
  interval_id: number;
}

export interface LoopTemplateSummary extends LoopTemplateResponse {}
export interface LoopViewSummary extends LoopViewResponse {}
export interface CommentNode extends LoopCommentResponse {}
export interface CommentListResponse extends LoopCommentListResponse {}
export interface SurfaceNextBuckets extends NextLoopsResponse {}
export interface SurfaceDuplicateCandidate extends DuplicateCandidateResponse {}
export interface SurfaceDuplicatesListResponse extends DuplicatesListResponse {}
export interface SurfaceMergePreviewResponse extends MergePreviewResponse {}
export interface SurfaceClarificationListResponse extends ClarificationListResponse {}
export interface SurfaceClarificationSubmitResponse extends ClarificationSubmitResponse {}
export interface SurfaceClarificationRefinementResponse extends ClarificationRefinementResponse {}
export interface SurfaceTimerStatusResponse extends TimerStatusResponse {}
export interface SurfaceTimeSessionResponse extends TimeSessionResponse {}
export interface SurfaceLoopSemanticSearchResponse extends LoopSemanticSearchResponse {}

export interface RagSource {
  document_path?: string | null;
  chunk_index?: number | null;
  score?: number | null;
  id?: string | number | null;
}

export interface RagChunk {
  content: string;
}

export interface SchedulerNotificationLoopDetail {
  id: number;
  title: string;
  is_overdue?: boolean;
}

export interface SchedulerNavigateAction {
  type: "navigate";
  tab: "review" | "capture" | "do" | "chat" | "memory" | "rag";
}

export interface SchedulerNotificationPayload {
  type: "due_soon" | "stale" | "blocked";
  title: string;
  body: string;
  severity: "info" | "warning" | "alert";
  details?: SchedulerNotificationLoopDetail[];
  action?: SchedulerNavigateAction | null;
}

export interface ReviewBannerPayload {
  type: "daily" | "weekly" | string;
  itemCount: number;
  cohorts?: unknown[] | null;
}

export interface SurfaceChatEventPayload {
  [key: string]: unknown;
  token?: string;
  output?: Record<string, unknown>;
  name?: string;
  arguments?: Record<string, unknown>;
  answer?: string;
  chunks?: RagChunk[];
  sources?: RagSource[];
  message?: string;
  model?: string | null;
  metadata?: Record<string, unknown> | null;
  options?: Record<string, unknown> | null;
  context?: Record<string, unknown> | null;
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }>;
  tool_results?: Record<string, unknown>[];
  tool_result?: Record<string, unknown> | null;
}

export interface SurfaceMemoryQueryOptions {
  category?: string | null;
  source?: string | null;
  minPriority?: number | string | null;
  limit?: number;
  cursor?: string | null;
}

export interface SurfaceSemanticSearchOptions {
  status?: string;
  limit?: number;
  offset?: number;
  minScore?: number | null;
}

export interface SurfaceBulkCloseItem {
  loop_id: number;
  status: "completed" | "dropped";
}

export interface SurfaceBulkSnoozeItem {
  loop_id: number;
  snooze_until_utc: string;
}

export interface SurfaceBulkUpdateItem {
  loop_id: number;
  fields: Record<string, unknown>;
}

export interface SurfaceBulkEnrichItem {
  loop_id: number;
}

export interface SurfaceSuggestionParsedFieldMap extends Record<string, unknown> {
  confidence?: Record<string, number | undefined>;
}

export type SurfaceSuggestion = SuggestionResponse;

export interface SurfaceReviewState {
  reviewMode: ReviewMode;
  reviewData: LoopReviewResponse | null;
  reviewPlanningSessions: PlanningSessionResponse[];
  reviewPlanningSessionSnapshot: PlanningSessionSnapshotResponse | null;
  reviewPlanningSessionId: number | null;
  reviewRelationshipActions: RelationshipReviewActionResponse[];
  reviewRelationshipSessions: RelationshipReviewSessionResponse[];
  reviewRelationshipSessionSnapshot: RelationshipReviewSessionSnapshotResponse | null;
  reviewRelationshipSessionId: number | null;
  reviewRelationshipActionId: number | null;
  reviewEnrichmentActions: EnrichmentReviewActionResponse[];
  reviewEnrichmentSessions: EnrichmentReviewSessionResponse[];
  reviewEnrichmentSessionSnapshot: EnrichmentReviewSessionSnapshotResponse | null;
  reviewEnrichmentSessionId: number | null;
  reviewEnrichmentActionId: number | null;
  reviewBulkEnrichmentPreview: unknown;
  reviewBulkEnrichmentResult: unknown;
}

export interface LegacySurfaceState extends SurfaceReviewState {
  loops: SurfaceLoop[];
  activeTab: LegacySurfaceTab;
  templatesCache: LoopTemplateSummary[] | null;
  relationshipReviewQueue: unknown;
  chatMessages: ChatMessage[];
  chatPreferences: ChatPreferences;
  lastClickedLoopId: number | null;
  focusedLoopId: number | null;
  notificationPermissionRequested: boolean;
}

export type SurfaceMemoryEntry = MemoryEntryResponse;
export type SurfaceMemoryListResponse = MemoryListResponse;
export type SurfaceMemorySearchResponse = MemorySearchResponse;
export type SurfaceBulkCloseResponse = BulkCloseResponse;
export type SurfaceBulkSnoozeResponse = BulkSnoozeResponse;
export type SurfaceBulkUpdateResponse = BulkUpdateResponse;
export type SurfaceBulkEnrichResponse = BulkEnrichResponse;
export type SurfaceCommentCreateRequest = LoopCommentCreateRequest;
export type SurfacePlanningExecuteResponse = PlanningSessionExecuteResponse;
export type SurfaceRelationshipSessionActionResponse = RelationshipReviewSessionActionResponse;
export type SurfaceEnrichmentClarificationResponse = EnrichmentReviewSessionClarificationResponse;
export type SurfaceApplySuggestionResponse = ApplySuggestionResponse;
export type SurfaceRejectSuggestionResponse = RejectSuggestionResponse;
export type SurfaceClarificationSubmitBatchRequest = ClarificationSubmitBatchRequest;
