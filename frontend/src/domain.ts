/**
 * domain.ts - Curated aliases for generated backend contract types.
 *
 * Purpose:
 *   Provide a stable frontend-facing layer over generated OpenAPI schema types so
 *   new TypeScript code does not import raw generated schema names everywhere.
 *
 * Responsibilities:
 *   - Re-export selected backend schema aliases used by the frontend shell.
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
 *   - frontend/src/generated/openapi.ts is generated and never hand-edited.
 *   - New TypeScript work should import aliases from here instead of the generated file directly.
 */

import type { components } from "./generated/openapi";

export type ApiSchemas = components["schemas"];
export type ApiSchemaName = keyof ApiSchemas;
export type ApiSchema<K extends ApiSchemaName> = ApiSchemas[K];

export type LoopResponse = ApiSchema<"LoopResponse">;
export type LoopCaptureRequest = ApiSchema<"LoopCaptureRequest">;
export type LoopUpdateRequest = ApiSchema<"LoopUpdateRequest">;
export type LoopSearchRequest = ApiSchema<"LoopSearchRequest">;
export type LoopSearchResponse = ApiSchema<"LoopSearchResponse">;
export type LoopSemanticSearchRequest = ApiSchema<"LoopSemanticSearchRequest">;
export type LoopSemanticSearchResponse = ApiSchema<"LoopSemanticSearchResponse">;
export type LoopMetricsResponse = ApiSchema<"LoopMetricsResponse">;
export type LoopReviewResponse = ApiSchema<"LoopReviewResponse">;
export type LoopReviewCohortResponse = ApiSchema<"LoopReviewCohortResponse">;
export type LoopReviewCohortItem = ApiSchema<"LoopReviewCohortItem">;
export type LoopUndoResponse = ApiSchema<"LoopUndoResponse">;
export type LoopViewResponse = ApiSchema<"LoopViewResponse">;
export type NextLoopsResponse = ApiSchema<"LoopNextResponse">;
export type ChatRequest = ApiSchema<"ChatRequest">;
export type ChatResponse = ApiSchema<"ChatResponse">;
export type AskResponse = ApiSchema<"AskResponse">;
export type MemoryEntryResponse = ApiSchema<"MemoryResponse">;
export type MemoryListResponse = ApiSchema<"MemoryListResponse">;
export type MemorySearchResponse = ApiSchema<"MemorySearchResponse">;
export type WorkingSetLaunchLocationResponse = ApiSchema<"WorkingSetLaunchLocationResponse">;
export type WorkingSetItemResponse = ApiSchema<"WorkingSetItemResponse">;
export type WorkingSetResponse = ApiSchema<"WorkingSetResponse">;
export type WorkingSetContextResponse = ApiSchema<"WorkingSetContextResponse">;
export type WorkingSetCreateRequest = ApiSchema<"WorkingSetCreateRequest">;
export type WorkingSetUpdateRequest = ApiSchema<"WorkingSetUpdateRequest">;
export type WorkingSetItemCreateRequest = ApiSchema<"WorkingSetItemCreateRequest">;
export type WorkingSetBulkItemCreateRequest = ApiSchema<"WorkingSetBulkItemCreateRequest">;
export type WorkingSetReorderRequest = ApiSchema<"WorkingSetReorderRequest">;
export type WorkingSetContextUpdateRequest = ApiSchema<"WorkingSetContextUpdateRequest">;
export type WorkingSetDeleteResponse = ApiSchema<"WorkingSetDeleteResponse">;
export type WorkingSetUndoRequest = ApiSchema<"WorkingSetUndoRequest">;
export type WorkingSetUndoResponse = ApiSchema<"WorkingSetUndoResponse">;
export type BulkCloseRequest = ApiSchema<"BulkCloseRequest">;
export type BulkCloseResponse = ApiSchema<"BulkCloseResponse">;
export type BulkEnrichRequest = ApiSchema<"BulkEnrichRequest">;
export type BulkEnrichResponse = ApiSchema<"BulkEnrichResponse">;
export type ContinuityLastSeenBatchUpsertRequest = ApiSchema<"ContinuityLastSeenBatchUpsertRequest">;
export type ContinuityLastSeenMarkerResponse = ApiSchema<"ContinuityLastSeenMarkerResponse">;
export type ContinuityLastSeenMarkerUpsertRequest = ApiSchema<"ContinuityLastSeenMarkerUpsertRequest">;
export type ContinuityLocationResponse = ApiSchema<"ContinuityLocationResponse">;
export type ContinuityNotificationRecordResponse = ApiSchema<"ContinuityNotificationRecordResponse">;
export type ContinuityNotificationStateResponse = ApiSchema<"ContinuityNotificationStateResponse">;
export type ContinuityNotificationStateUpsertRequest = ApiSchema<"ContinuityNotificationStateUpsertRequest">;
export type ContinuityOutcomeRecordResponse = ApiSchema<"ContinuityOutcomeRecordResponse">;
export type ContinuityOutcomeWriteRequest = ApiSchema<"ContinuityOutcomeWriteRequest">;
export type ContinuityRecoveryAcknowledgementResponse = ApiSchema<"ContinuityRecoveryAcknowledgementResponse">;
export type ContinuityRecoveryAcknowledgementUpsertRequest = ApiSchema<"ContinuityRecoveryAcknowledgementUpsertRequest">;
export type ContinuitySnapshotResponse = ApiSchema<"ContinuitySnapshotResponse">;
export type ContinuitySuccessorTargetResponse = ApiSchema<"ContinuitySuccessorTargetResponse">;
export type BulkSnoozeRequest = ApiSchema<"BulkSnoozeRequest">;
export type BulkSnoozeResponse = ApiSchema<"BulkSnoozeResponse">;
export type BulkUpdateRequest = ApiSchema<"BulkUpdateRequest">;
export type BulkUpdateResponse = ApiSchema<"BulkUpdateResponse">;
export type PlanningCheckpointResponse = ApiSchema<"PlanningCheckpointResponse">;
export type PlanningTargetLoopResponse = ApiSchema<"PlanningTargetLoopResponse">;
export type PlanningExecutionHistoryItemResponse = ApiSchema<"PlanningExecutionHistoryItemResponse">;
export type PlanningExecutionLaunchSurfaceResponse = ApiSchema<"PlanningExecutionLaunchSurfaceResponse">;
export type PlanningExecutionFollowUpResourceResponse = ApiSchema<"PlanningExecutionFollowUpResourceResponse">;
export type PlanningExecutionRollbackCueOperationResponse = ApiSchema<"PlanningExecutionRollbackCueOperationResponse">;
export type ResolvedContinuityTargetResponse = ApiSchema<"ResolvedContinuityTargetResponse">;
export type PlanningExecutionRollbackCueResponse = ApiSchema<"PlanningExecutionRollbackCueResponse">;
export type PlanningContextFreshnessTargetChangeResponse = ApiSchema<"PlanningContextFreshnessTargetChangeResponse">;
export type PlanningContextFreshnessResponse = ApiSchema<"PlanningContextFreshnessResponse">;
export type PlanningResourceChangeGroupResponse = ApiSchema<"PlanningResourceChangeGroupResponse">;
export type PlanningResourceChangeSummaryResponse = ApiSchema<"PlanningResourceChangeSummaryResponse">;
export type PlanningSessionCreateRequest = ApiSchema<"PlanningSessionCreateRequest">;
export type PlanningSessionResponse = ApiSchema<"PlanningSessionResponse">;
export type PlanningSessionSnapshotResponse = ApiSchema<"PlanningSessionSnapshotResponse">;
export type PlanningSessionExecuteResponse = ApiSchema<"PlanningSessionExecuteResponse">;
export type PlanningSessionRollbackResponse = ApiSchema<"PlanningSessionRollbackResponse">;
export type RelationshipReviewActionCreateRequest = ApiSchema<"RelationshipReviewActionCreateRequest">;
export type RelationshipReviewActionUpdateRequest = ApiSchema<"RelationshipReviewActionUpdateRequest">;
export type RelationshipReviewActionResponse = ApiSchema<"RelationshipReviewActionResponse">;
export type RelationshipReviewCandidateResponse = ApiSchema<"RelationshipReviewCandidateResponse">;
export type RelationshipReviewSessionCreateRequest = ApiSchema<"RelationshipReviewSessionCreateRequest">;
export type RelationshipReviewSessionUpdateRequest = ApiSchema<"RelationshipReviewSessionUpdateRequest">;
export type RelationshipReviewSessionActionRequest = ApiSchema<"RelationshipReviewSessionActionRequest">;
export type RelationshipReviewSessionActionResponse = ApiSchema<"RelationshipReviewSessionActionResponse">;
export type LoopRelationshipReviewQueueItemResponse = ApiSchema<"LoopRelationshipReviewQueueItemResponse">;
export type RelationshipReviewSessionResponse = ApiSchema<"RelationshipReviewSessionResponse">;
export type RelationshipReviewSessionSnapshotResponse = ApiSchema<"RelationshipReviewSessionSnapshotResponse">;
export type ClarificationResponse = ApiSchema<"ClarificationResponse">;
export type ClarificationSubmitRequest = ApiSchema<"ClarificationSubmitRequest">;
export type SuggestionResponse = ApiSchema<"SuggestionResponse">;
export type EnrichmentReviewActionCreateRequest = ApiSchema<"EnrichmentReviewActionCreateRequest">;
export type EnrichmentReviewActionUpdateRequest = ApiSchema<"EnrichmentReviewActionUpdateRequest">;
export type EnrichmentReviewActionResponse = ApiSchema<"EnrichmentReviewActionResponse">;
export type EnrichmentReviewQueueItemResponse = ApiSchema<"EnrichmentReviewQueueItemResponse">;
export type EnrichmentReviewSessionCreateRequest = ApiSchema<"EnrichmentReviewSessionCreateRequest">;
export type EnrichmentReviewSessionUpdateRequest = ApiSchema<"EnrichmentReviewSessionUpdateRequest">;
export type EnrichmentReviewSessionActionRequest = ApiSchema<"EnrichmentReviewSessionActionRequest">;
export type EnrichmentReviewSessionActionResponse = ApiSchema<"EnrichmentReviewSessionActionResponse">;
export type EnrichmentReviewSessionClarificationRequest = ApiSchema<"EnrichmentReviewSessionClarificationRequest">;
export type EnrichmentReviewSessionClarificationResponse = ApiSchema<"EnrichmentReviewSessionClarificationResponse">;
export type EnrichmentReviewSessionResponse = ApiSchema<"EnrichmentReviewSessionResponse">;
export type EnrichmentReviewSessionSnapshotResponse = ApiSchema<"EnrichmentReviewSessionSnapshotResponse">;
export type ApplySuggestionRequest = ApiSchema<"ApplySuggestionRequest">;
export type ApplySuggestionResponse = ApiSchema<"ApplySuggestionResponse">;
export type RejectSuggestionResponse = ApiSchema<"RejectSuggestionResponse">;
export type ClarificationListResponse = ApiSchema<"ClarificationListResponse">;
export type ClarificationRefinementResponse = ApiSchema<"ClarificationRefinementResponse">;
export type ClarificationSubmitBatchRequest = ApiSchema<"ClarificationSubmitBatchRequest">;
export type ClarificationSubmitResponse = ApiSchema<"ClarificationSubmitResponse">;
export type DuplicateCandidateResponse = ApiSchema<"DuplicateCandidateResponse">;
export type DuplicatesListResponse = ApiSchema<"DuplicatesListResponse">;
export type IngestResponse = ApiSchema<"IngestResponse">;
export type LoopCommentCreateRequest = ApiSchema<"LoopCommentCreateRequest">;
export type LoopCommentListResponse = ApiSchema<"LoopCommentListResponse">;
export type LoopCommentResponse = ApiSchema<"LoopCommentResponse">;
export type LoopTemplateListResponse = ApiSchema<"LoopTemplateListResponse">;
export type LoopTemplateResponse = ApiSchema<"LoopTemplateResponse">;
export type MergePreviewResponse = ApiSchema<"MergePreviewResponse">;
export type TimeSessionResponse = ApiSchema<"TimeSessionResponse">;
export type TimerStatusResponse = ApiSchema<"TimerStatusResponse">;
export type ContinuityWorkflowSummaryPriorStateResponse = ApiSchema<"ContinuityWorkflowSummaryPriorStateResponse">;
export type ContinuityWorkflowSummaryResponse = ApiSchema<"ContinuityWorkflowSummaryResponse">;
export type ContinuityWorkflowSummarySignalsResponse = ApiSchema<"ContinuityWorkflowSummarySignalsResponse">;
export type WorkflowThreadRefResponse = ApiSchema<"WorkflowThreadRefResponse">;
