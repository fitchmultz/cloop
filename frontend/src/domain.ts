/**
 * domain.ts - Curated aliases for generated backend contract types.
 *
 * Purpose:
 *   Provide a stable frontend-facing layer over generated OpenAPI contract types so
 *   new TypeScript code does not import raw generated contract names everywhere.
 *
 * Responsibilities:
 *   - Re-export selected backend contract aliases used by the frontend shell.
 *   - Keep generated contract imports centralized in one small file.
 *   - Provide a typed foothold for upcoming Operator workspace/state-navigation work.
 *
 * Scope:
 *   - Backend-derived contract aliases only.
 *
 * Usage:
 *   - Import backend response/request aliases from this module in new TypeScript code.
 *
 * Invariants/Assumptions:
 *   - frontend/src/generated/types.gen.ts is generated and never hand-edited.
 *   - New TypeScript work should import aliases from here instead of the generated file directly.
 */

import type * as ApiTypes from "./generated/types.gen";

export type LoopResponse = ApiTypes.LoopResponse;
export type LoopCaptureRequest = ApiTypes.LoopCaptureRequest;
export type LoopUpdateRequest = ApiTypes.LoopUpdateRequest;
export type LoopSearchRequest = ApiTypes.LoopSearchRequest;
export type LoopSearchResponse = ApiTypes.LoopSearchResponse;
export type LoopSemanticSearchRequest = ApiTypes.LoopSemanticSearchRequest;
export type LoopSemanticSearchResponse = ApiTypes.LoopSemanticSearchResponse;
export type LoopMetricsResponse = ApiTypes.LoopMetricsResponse;
export type LoopReviewResponse = ApiTypes.LoopReviewResponse;
export type LoopReviewCohortResponse = ApiTypes.LoopReviewCohortResponse;
export type LoopReviewCohortItem = ApiTypes.LoopReviewCohortItem;
export type LoopUndoResponse = ApiTypes.LoopUndoResponse;
export type LoopViewResponse = ApiTypes.LoopViewResponse;
export type NextLoopsResponse = ApiTypes.LoopNextResponse;
export type NowFeedItemResponse = ApiTypes.NowFeedItemResponse;
export type NowFeedResponse = ApiTypes.NowFeedResponse;
export type ChatRequest = ApiTypes.ChatRequest;
export type ChatResponse = ApiTypes.ChatResponse;
export type AskResponse = ApiTypes.AskResponse;
export type MemoryEntryResponse = ApiTypes.MemoryResponse;
export type MemoryListResponse = ApiTypes.MemoryListResponse;
export type MemorySearchResponse = ApiTypes.MemorySearchResponse;
export type WorkingSetLaunchLocationResponse = ApiTypes.WorkingSetLaunchLocationResponse;
export type WorkingSetItemResponse = ApiTypes.WorkingSetItemResponse;
export type WorkingSetResponse = ApiTypes.WorkingSetResponse;
export type WorkingSetContextResponse = ApiTypes.WorkingSetContextResponse;
export type WorkingSetCreateRequest = ApiTypes.WorkingSetCreateRequest;
export type WorkingSetUpdateRequest = ApiTypes.WorkingSetUpdateRequest;
export type WorkingSetItemCreateRequest = ApiTypes.WorkingSetItemCreateRequest;
export type WorkingSetBulkItemCreateRequest = ApiTypes.WorkingSetBulkItemCreateRequest;
export type WorkingSetReorderRequest = ApiTypes.WorkingSetReorderRequest;
export type WorkingSetContextUpdateRequest = ApiTypes.WorkingSetContextUpdateRequest;
export type WorkingSetDeleteResponse = ApiTypes.WorkingSetDeleteResponse;
export type WorkingSetUndoRequest = ApiTypes.WorkingSetUndoRequest;
export type WorkingSetUndoResponse = ApiTypes.WorkingSetUndoResponse;
export type BulkCloseRequest = ApiTypes.BulkCloseRequest;
export type BulkCloseResponse = ApiTypes.BulkCloseResponse;
export type BulkEnrichRequest = ApiTypes.BulkEnrichRequest;
export type BulkEnrichResponse = ApiTypes.BulkEnrichResponse;
export type ContinuityLastSeenBatchUpsertRequest = ApiTypes.ContinuityLastSeenBatchUpsertRequest;
export type ContinuityLastSeenMarkerResponse = ApiTypes.ContinuityLastSeenMarkerResponse;
export type ContinuityLastSeenMarkerUpsertRequest = ApiTypes.ContinuityLastSeenMarkerUpsertRequest;
export type ContinuityLocationResponse = ApiTypes.ContinuityLocationResponse;
export type ContinuityNotificationRecordResponse = ApiTypes.ContinuityNotificationRecordResponse;
export type ContinuityNotificationStateResponse = ApiTypes.ContinuityNotificationStateResponse;
export type ContinuityNotificationStateUpsertRequest = ApiTypes.ContinuityNotificationStateUpsertRequest;
export type ContinuityOutcomeRecordResponse = ApiTypes.ContinuityOutcomeRecordResponse;
export type ContinuityOutcomeWriteRequest = ApiTypes.ContinuityOutcomeWriteRequest;
export type ReviewFollowThroughResponse = ApiTypes.ReviewFollowThroughResponse;
export type ContinuityRecoveryAcknowledgementResponse = ApiTypes.ContinuityRecoveryAcknowledgementResponse;
export type ContinuityRecoveryAcknowledgementUpsertRequest = ApiTypes.ContinuityRecoveryAcknowledgementUpsertRequest;
export type ContinuitySnapshotResponse = ApiTypes.ContinuitySnapshotResponse;
export type ContinuitySuccessorTargetResponse = ApiTypes.ContinuitySuccessorTargetResponse;
export type BulkSnoozeRequest = ApiTypes.BulkSnoozeRequest;
export type BulkSnoozeResponse = ApiTypes.BulkSnoozeResponse;
export type BulkUpdateRequest = ApiTypes.BulkUpdateRequest;
export type BulkUpdateResponse = ApiTypes.BulkUpdateResponse;
export type PlanningCheckpointResponse = ApiTypes.PlanningCheckpointResponse;
export type PlanningTargetLoopResponse = ApiTypes.PlanningTargetLoopResponse;
export type PlanningExecutionHistoryItemResponse = ApiTypes.PlanningExecutionHistoryItemResponse;
export type PlanningExecutionLaunchSurfaceResponse = ApiTypes.PlanningExecutionLaunchSurfaceResponse;
export type PlanningExecutionFollowUpResourceResponse = ApiTypes.PlanningExecutionFollowUpResourceResponse;
export type PlanningExecutionRollbackCueOperationResponse = ApiTypes.PlanningExecutionRollbackCueOperationResponse;
export type ResolvedContinuityTargetResponse = ApiTypes.ResolvedContinuityTargetResponse;
export type PlanningExecutionRollbackCueResponse = ApiTypes.PlanningExecutionRollbackCueResponse;
export type PlanningContextFreshnessTargetChangeResponse = ApiTypes.PlanningContextFreshnessTargetChangeResponse;
export type PlanningContextFreshnessResponse = ApiTypes.PlanningContextFreshnessResponse;
export type PlanningResourceChangeGroupResponse = ApiTypes.PlanningResourceChangeGroupResponse;
export type PlanningResourceChangeSummaryResponse = ApiTypes.PlanningResourceChangeSummaryResponse;
export type PlanningSessionCreateRequest = ApiTypes.PlanningSessionCreateRequest;
export type PlanningSessionResponse = ApiTypes.PlanningSessionResponse;
export type PlanningSessionSnapshotResponse = ApiTypes.PlanningSessionSnapshotResponse;
export type PlanningSessionExecuteResponse = ApiTypes.PlanningSessionExecuteResponse;
export type PlanningSessionRollbackResponse = ApiTypes.PlanningSessionRollbackResponse;
export type RelationshipReviewActionCreateRequest = ApiTypes.RelationshipReviewActionCreateRequest;
export type RelationshipReviewActionUpdateRequest = ApiTypes.RelationshipReviewActionUpdateRequest;
export type RelationshipReviewActionResponse = ApiTypes.RelationshipReviewActionResponse;
export type RelationshipReviewCandidateResponse = ApiTypes.RelationshipReviewCandidateResponse;
export type RelationshipReviewSessionCreateRequest = ApiTypes.RelationshipReviewSessionCreateRequest;
export type RelationshipReviewSessionUpdateRequest = ApiTypes.RelationshipReviewSessionUpdateRequest;
export type RelationshipReviewSessionActionRequest = ApiTypes.RelationshipReviewSessionActionRequest;
export type RelationshipReviewSessionActionResponse = ApiTypes.RelationshipReviewSessionActionResponse;
export type RelationshipReviewSessionUndoRequest = ApiTypes.RelationshipReviewSessionUndoRequest;
export type RelationshipReviewSessionUndoResponse = ApiTypes.RelationshipReviewSessionUndoResponse;
export type LoopRelationshipReviewQueueItemResponse = ApiTypes.LoopRelationshipReviewQueueItemResponse;
export type RelationshipReviewSessionResponse = ApiTypes.RelationshipReviewSessionResponse;
export type RelationshipReviewSessionSnapshotResponse = ApiTypes.RelationshipReviewSessionSnapshotResponse;
export type ClarificationResponse = ApiTypes.ClarificationResponse;
export type ClarificationSubmitRequest = ApiTypes.ClarificationSubmitRequest;
export type SuggestionResponse = ApiTypes.SuggestionResponse;
export type EnrichmentReviewActionCreateRequest = ApiTypes.EnrichmentReviewActionCreateRequest;
export type EnrichmentReviewActionUpdateRequest = ApiTypes.EnrichmentReviewActionUpdateRequest;
export type EnrichmentReviewActionResponse = ApiTypes.EnrichmentReviewActionResponse;
export type EnrichmentReviewQueueItemResponse = ApiTypes.EnrichmentReviewQueueItemResponse;
export type EnrichmentReviewSessionCreateRequest = ApiTypes.EnrichmentReviewSessionCreateRequest;
export type EnrichmentReviewSessionUpdateRequest = ApiTypes.EnrichmentReviewSessionUpdateRequest;
export type EnrichmentReviewSessionActionRequest = ApiTypes.EnrichmentReviewSessionActionRequest;
export type EnrichmentReviewSessionActionResponse = ApiTypes.EnrichmentReviewSessionActionResponse;
export type EnrichmentReviewSessionClarificationRequest = ApiTypes.EnrichmentReviewSessionClarificationRequest;
export type EnrichmentReviewSessionClarificationResponse = ApiTypes.EnrichmentReviewSessionClarificationResponse;
export type EnrichmentReviewSessionResponse = ApiTypes.EnrichmentReviewSessionResponse;
export type EnrichmentReviewSessionSnapshotResponse = ApiTypes.EnrichmentReviewSessionSnapshotResponse;
export type ApplySuggestionRequest = ApiTypes.ApplySuggestionRequest;
export type ApplySuggestionResponse = ApiTypes.ApplySuggestionResponse;
export type RejectSuggestionResponse = ApiTypes.RejectSuggestionResponse;
export type ClarificationListResponse = ApiTypes.ClarificationListResponse;
export type ClarificationRefinementResponse = ApiTypes.ClarificationRefinementResponse;
export type ClarificationSubmitBatchRequest = ApiTypes.ClarificationSubmitBatchRequest;
export type ClarificationSubmitResponse = ApiTypes.ClarificationSubmitResponse;
export type ClarificationUndoResponse = ApiTypes.ClarificationUndoResponse;
export type DuplicateCandidateResponse = ApiTypes.DuplicateCandidateResponse;
export type SuggestionListResponse = ApiTypes.SuggestionListResponse;
export type DuplicatesListResponse = ApiTypes.DuplicatesListResponse;
export type IngestResponse = ApiTypes.IngestResponse;
export type LoopCommentCreateRequest = ApiTypes.LoopCommentCreateRequest;
export type LoopCommentListResponse = ApiTypes.LoopCommentListResponse;
export type LoopCommentResponse = ApiTypes.LoopCommentResponse;
export type LoopTemplateListResponse = ApiTypes.LoopTemplateListResponse;
export type LoopTemplateResponse = ApiTypes.LoopTemplateResponse;
export type MergePreviewResponse = ApiTypes.MergePreviewResponse;
export type TimeSessionResponse = ApiTypes.TimeSessionResponse;
export type TimerStatusResponse = ApiTypes.TimerStatusResponse;
export type ContinuityWorkflowSummaryPriorStateResponse = ApiTypes.ContinuityWorkflowSummaryPriorStateResponse;
export type ContinuityWorkflowSummaryResponse = ApiTypes.ContinuityWorkflowSummaryResponse;
export type ContinuityWorkflowSummarySignalsResponse = ApiTypes.ContinuityWorkflowSummarySignalsResponse;
export type WorkflowThreadRefResponse = ApiTypes.WorkflowThreadRefResponse;
