/**
 * api.ts - Typed HTTP utilities for the shared work surfaces.
 *
 * Purpose:
 *   Provide strict TypeScript API client functions for all capture/do/recall
 *   surface interactions.
 *
 * Responsibilities:
 *   - Send typed JSON and streaming requests through shared HTTP helpers.
 *   - Keep endpoint URLs/query-parameter construction centralized.
 *   - Expose one frontend-facing API surface for work-surface modules.
 *
 * Scope:
 *   - Surface runtime transport helpers only.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/* modules.
 *
 * Invariants/Assumptions:
 *   - frontend/src/http.ts remains the source of truth for fetch/error handling.
 *   - Streaming chat/RAG endpoints return fetch Response objects.
 */

import type { ChatPreferences } from "../contracts-ui";
import type {
  ApplySuggestionResponse,
  BulkCloseRequest,
  BulkCloseResponse,
  BulkEnrichRequest,
  BulkEnrichResponse,
  BulkSnoozeRequest,
  BulkSnoozeResponse,
  BulkUpdateRequest,
  BulkUpdateResponse,
  ClarificationListResponse,
  ClarificationRefinementResponse,
  ClarificationSubmitBatchRequest,
  ClarificationSubmitResponse,
  DuplicatesListResponse,
  EnrichmentReviewActionResponse,
  EnrichmentReviewSessionClarificationRequest,
  EnrichmentReviewSessionClarificationResponse,
  EnrichmentReviewSessionResponse,
  EnrichmentReviewSessionSnapshotResponse,
  IngestResponse,
  LoopCaptureRequest,
  LoopCommentCreateRequest,
  LoopCommentListResponse,
  LoopCommentResponse,
  LoopResponse,
  LoopReviewResponse,
  LoopSearchResponse,
  LoopSemanticSearchResponse,
  LoopTemplateListResponse,
  LoopTemplateResponse,
  LoopViewResponse,
  MemoryEntryResponse,
  MemoryListResponse,
  MemorySearchResponse,
  MergePreviewResponse,
  NextLoopsResponse,
  PlanningSessionCreateRequest,
  PlanningSessionExecuteResponse,
  PlanningSessionResponse,
  PlanningSessionSnapshotResponse,
  RelationshipReviewActionCreateRequest,
  RelationshipReviewActionResponse,
  RelationshipReviewActionUpdateRequest,
  RelationshipReviewSessionActionRequest,
  RelationshipReviewSessionActionResponse,
  RelationshipReviewSessionCreateRequest,
  RelationshipReviewSessionResponse,
  RelationshipReviewSessionSnapshotResponse,
  RelationshipReviewSessionUpdateRequest,
  SuggestionResponse,
  TimeSessionResponse,
  TimerStatusResponse,
} from "../domain";
import { requestJson, requestStream } from "../http";
import type {
  HealthStatusResponse,
  LoopTemplateSummary,
  LoopViewSummary,
  SurfaceBulkCloseItem,
  SurfaceBulkEnrichItem,
  SurfaceBulkUpdateItem,
  SurfaceChatRequestMessage,
  SurfaceClarificationSubmitBatchRequest,
  SurfaceLoop,
  SurfaceMemoryQueryOptions,
  SurfaceSemanticSearchOptions,
  SurfaceSuggestion,
} from "./contracts";

interface SemanticSearchRequest {
  query: string;
  status: string;
  limit: number;
  offset: number;
  min_score: number | null;
}

interface SearchLoopBody {
  query: string;
  limit: number;
  offset: number;
}

interface EnrichLoopResponse {
  loop: SurfaceLoop;
  needs_clarification?: unknown[] | null;
}

interface ExportLoopsResponse {
  export_json: string;
}

interface ImportLoopsRequest {
  loops: unknown[];
}

interface ViewSaveRequest {
  name: string;
  query: string;
}

interface LoopStatusTransitionRequest {
  status: string;
  note?: string;
}

interface MemoryMutationRequest {
  key: string | null;
  content: string;
  category: string;
  priority: number;
  source: string;
  metadata: Record<string, unknown>;
}

interface QueryBulkEnrichRequest {
  query: string;
  dry_run?: boolean;
  limit?: number;
}

type JsonObject = Record<string, unknown>;

function buildUrl(path: string, params: Record<string, string | number | boolean | null | undefined>): string {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

function withJsonBody<TBody>(body?: TBody): { body?: TBody } {
  return body === undefined ? {} : { body };
}

export async function fetchMemoryEntries(
  options: SurfaceMemoryQueryOptions = {},
): Promise<MemoryListResponse> {
  return requestJson<MemoryListResponse>(
    buildUrl("/memory", {
      category: options.category,
      source: options.source,
      min_priority: options.minPriority,
      limit: options.limit ?? 50,
      cursor: options.cursor,
    }),
    {},
    "Failed to load memory entries",
  );
}

export async function searchMemoryEntries(
  query: string,
  options: SurfaceMemoryQueryOptions = {},
): Promise<MemorySearchResponse> {
  return requestJson<MemorySearchResponse>(
    buildUrl("/memory/search", {
      q: query,
      category: options.category,
      source: options.source,
      min_priority: options.minPriority,
      limit: options.limit ?? 50,
      cursor: options.cursor,
    }),
    {},
    "Failed to search memory entries",
  );
}

export async function fetchMemoryEntry(entryId: number | string): Promise<MemoryEntryResponse> {
  return requestJson<MemoryEntryResponse>(`/memory/${entryId}`, {}, "Failed to load memory entry");
}

export async function createMemoryEntry(payload: MemoryMutationRequest): Promise<MemoryEntryResponse> {
  return requestJson<MemoryEntryResponse, MemoryMutationRequest>(
    "/memory",
    { method: "POST", ...withJsonBody(payload) },
    "Failed to create memory entry",
  );
}

export async function updateMemoryEntry(
  entryId: number | string,
  payload: MemoryMutationRequest,
): Promise<MemoryEntryResponse> {
  return requestJson<MemoryEntryResponse, MemoryMutationRequest>(
    `/memory/${entryId}`,
    { method: "PUT", ...withJsonBody(payload) },
    "Failed to update memory entry",
  );
}

export async function deleteMemoryEntry(entryId: number | string): Promise<true> {
  await requestJson<null>(`/memory/${entryId}`, { method: "DELETE" }, "Failed to delete memory entry");
  return true;
}

export async function fetchLoops(status: string, tag: string | null = null): Promise<SurfaceLoop[]> {
  return requestJson<SurfaceLoop[]>(buildUrl("/loops", { status, tag }), {}, "Failed to load loops");
}

export async function searchLoops(query: string, limit = 50, offset = 0): Promise<SurfaceLoop[]> {
  const response = await requestJson<LoopSearchResponse, SearchLoopBody>(
    "/loops/search",
    { method: "POST", ...withJsonBody({ query, limit, offset }) },
    "Failed to search loops",
  );
  return response.items as SurfaceLoop[];
}

export async function searchLoopsSemantic(
  query: string,
  options: SurfaceSemanticSearchOptions = {},
): Promise<LoopSemanticSearchResponse> {
  return requestJson<LoopSemanticSearchResponse, SemanticSearchRequest>(
    "/loops/search/semantic",
    {
      method: "POST",
      ...withJsonBody({
        query,
        status: options.status ?? "open",
        limit: options.limit ?? 50,
        offset: options.offset ?? 0,
        min_score: options.minScore ?? null,
      }),
    },
    "Failed to search loops semantically",
  );
}

export async function fetchLoop(loopId: number | string): Promise<SurfaceLoop | null> {
  try {
    return await requestJson<SurfaceLoop>(`/loops/${loopId}`, {}, "Failed to load loop");
  } catch {
    return null;
  }
}

export async function captureLoop(payload: LoopCaptureRequest): Promise<SurfaceLoop> {
  return requestJson<SurfaceLoop, LoopCaptureRequest>(
    "/loops/capture",
    { method: "POST", ...withJsonBody(payload) },
    "Capture failed",
  );
}

export async function updateLoop(
  loopId: number | string,
  fields: Record<string, unknown>,
): Promise<SurfaceLoop | null> {
  try {
    return await requestJson<SurfaceLoop, Record<string, unknown>>(
      `/loops/${loopId}`,
      { method: "PATCH", ...withJsonBody(fields) },
      "Failed to update loop",
    );
  } catch {
    return null;
  }
}

export async function transitionLoopStatus(
  loopId: number | string,
  status: string,
  note: string | null = null,
): Promise<SurfaceLoop> {
  const payload: LoopStatusTransitionRequest = { status };
  if (note) {
    payload.note = note;
  }
  return requestJson<SurfaceLoop, LoopStatusTransitionRequest>(
    `/loops/${loopId}/status`,
    { method: "POST", ...withJsonBody(payload) },
    "Status transition failed",
  );
}

export async function enrichLoop(loopId: number | string): Promise<EnrichLoopResponse> {
  return requestJson<EnrichLoopResponse>(
    `/loops/${loopId}/enrich`,
    { method: "POST" },
    "Enrichment request failed",
  );
}

export async function fetchTimerStatus(loopId: number | string): Promise<TimerStatusResponse | null> {
  try {
    return await requestJson<TimerStatusResponse>(
      `/loops/${loopId}/timer/status`,
      {},
      "Failed to load timer status",
    );
  } catch {
    return null;
  }
}

export async function startTimer(loopId: number | string): Promise<TimeSessionResponse> {
  return requestJson<TimeSessionResponse>(
    `/loops/${loopId}/timer/start`,
    { method: "POST" },
    "Failed to start timer",
  );
}

export async function stopTimer(loopId: number | string): Promise<TimeSessionResponse> {
  return requestJson<TimeSessionResponse>(
    `/loops/${loopId}/timer/stop`,
    { method: "POST" },
    "Failed to stop timer",
  );
}

export async function fetchComments(loopId: number | string): Promise<LoopCommentListResponse> {
  return requestJson<LoopCommentListResponse>(`/loops/${loopId}/comments`, {}, "Failed to load comments");
}

export async function postComment(
  loopId: number | string,
  author: string,
  body: string,
  parentId?: number | null,
): Promise<LoopCommentResponse> {
  const payload: LoopCommentCreateRequest = { author, body_md: body };
  if (typeof parentId === "number") {
    payload.parent_id = parentId;
  }
  return requestJson<LoopCommentResponse, LoopCommentCreateRequest>(
    `/loops/${loopId}/comments`,
    { method: "POST", ...withJsonBody(payload) },
    "Failed to post comment",
  );
}

export async function deleteComment(loopId: number | string, commentId: number | string): Promise<LoopCommentResponse> {
  return requestJson<LoopCommentResponse>(
    `/loops/${loopId}/comments/${commentId}`,
    { method: "DELETE" },
    "Failed to delete comment",
  );
}

export async function fetchTemplates(): Promise<LoopTemplateSummary[]> {
  const response = await requestJson<LoopTemplateListResponse>(
    "/loops/templates",
    {},
    "Failed to load templates",
  );
  return response.templates as LoopTemplateSummary[];
}

export async function saveLoopAsTemplate(loopId: number | string, name: string): Promise<LoopTemplateResponse> {
  return requestJson<LoopTemplateResponse, { name: string }>(
    `/loops/${loopId}/save-as-template`,
    { method: "POST", ...withJsonBody({ name }) },
    "Failed to save template",
  );
}

export async function fetchTags(): Promise<string[]> {
  return requestJson<string[]>("/loops/tags", {}, "Failed to load tags");
}

export async function fetchViews(): Promise<LoopViewSummary[]> {
  return requestJson<LoopViewSummary[]>("/loops/views", {}, "Failed to load views");
}

export async function saveView(name: string, query: string): Promise<LoopViewResponse> {
  return requestJson<LoopViewResponse, ViewSaveRequest>(
    "/loops/views",
    { method: "POST", ...withJsonBody({ name, query }) },
    "Failed to save view",
  );
}

export async function bulkCloseLoops(
  items: SurfaceBulkCloseItem[],
  transactional = false,
): Promise<BulkCloseResponse> {
  return requestJson<BulkCloseResponse, BulkCloseRequest>(
    "/loops/bulk/close",
    { method: "POST", ...withJsonBody({ items, transactional }) },
    "Bulk close failed",
  );
}

export async function bulkSnoozeLoops(
  items: BulkSnoozeRequest["items"],
  transactional = false,
): Promise<BulkSnoozeResponse> {
  return requestJson<BulkSnoozeResponse, BulkSnoozeRequest>(
    "/loops/bulk/snooze",
    { method: "POST", ...withJsonBody({ items, transactional }) },
    "Bulk snooze failed",
  );
}

export async function bulkUpdateLoops(
  updates: SurfaceBulkUpdateItem[],
  transactional = false,
): Promise<BulkUpdateResponse> {
  return requestJson<BulkUpdateResponse, BulkUpdateRequest>(
    "/loops/bulk/update",
    { method: "POST", ...withJsonBody({ updates, transactional }) },
    "Bulk update failed",
  );
}

export async function bulkEnrichLoops(items: SurfaceBulkEnrichItem[]): Promise<BulkEnrichResponse> {
  return requestJson<BulkEnrichResponse, BulkEnrichRequest>(
    "/loops/bulk/enrich",
    { method: "POST", ...withJsonBody({ items }) },
    "Bulk enrich failed",
  );
}

export async function bulkEnrichQuery(
  query: string,
  options: { dryRun?: boolean; limit?: number } = {},
): Promise<JsonObject> {
  const body: QueryBulkEnrichRequest = { query };
  if (typeof options.dryRun === "boolean") {
    body.dry_run = options.dryRun;
  }
  if (typeof options.limit === "number") {
    body.limit = options.limit;
  }
  return requestJson<JsonObject, QueryBulkEnrichRequest>(
    "/loops/bulk/enrich/query",
    { method: "POST", ...withJsonBody(body) },
    "Query-based bulk enrich failed",
  );
}

export async function fetchNextLoops(limit = 10): Promise<NextLoopsResponse> {
  return requestJson<NextLoopsResponse>(buildUrl("/loops/next", { limit }), {}, "Failed to load next loops");
}

export async function fetchReviewData(): Promise<LoopReviewResponse> {
  return requestJson<LoopReviewResponse>("/loops/review?daily=true&weekly=true&limit=8", {}, "Failed to load review data");
}

export async function fetchRelationshipReviewQueue(
  options: { status?: string; relationshipKind?: string; limit?: number; candidateLimit?: number } = {},
): Promise<JsonObject> {
  return requestJson<JsonObject>(
    buildUrl("/loops/review/relationship", {
      status: options.status,
      relationship_kind: options.relationshipKind,
      limit: options.limit,
      candidate_limit: options.candidateLimit,
    }),
    {},
    "Failed to load relationship review queue",
  );
}

export async function fetchLoopRelationshipReview(
  loopId: number | string,
  options: { status?: string; duplicateLimit?: number; relatedLimit?: number } = {},
): Promise<JsonObject> {
  return requestJson<JsonObject>(
    buildUrl(`/loops/${loopId}/relationship-review`, {
      status: options.status,
      duplicate_limit: options.duplicateLimit,
      related_limit: options.relatedLimit,
    }),
    {},
    "Failed to load loop relationship review",
  );
}

export async function confirmLoopRelationship(
  loopId: number | string,
  candidateLoopId: number | string,
  relationshipType: string,
): Promise<JsonObject> {
  return requestJson<JsonObject, { candidate_loop_id: number | string; relationship_type: string }>(
    `/loops/${loopId}/relationship-review/confirm`,
    { method: "POST", ...withJsonBody({ candidate_loop_id: candidateLoopId, relationship_type: relationshipType }) },
    "Failed to confirm relationship",
  );
}

export async function dismissLoopRelationship(
  loopId: number | string,
  candidateLoopId: number | string,
  relationshipType: string,
): Promise<JsonObject> {
  return requestJson<JsonObject, { candidate_loop_id: number | string; relationship_type: string }>(
    `/loops/${loopId}/relationship-review/dismiss`,
    { method: "POST", ...withJsonBody({ candidate_loop_id: candidateLoopId, relationship_type: relationshipType }) },
    "Failed to dismiss relationship",
  );
}

function mergeInit(init: RequestInit, extra: RequestInit = {}): RequestInit {
  return {
    ...init,
    ...extra,
    headers: new Headers(extra.headers ?? init.headers),
  };
}

export async function fetchPlanningSessions(): Promise<PlanningSessionResponse[]> {
  return requestJson<PlanningSessionResponse[]>("/loops/planning/sessions", {}, "Failed to load planning sessions");
}

export async function createPlanningSession(payload: PlanningSessionCreateRequest): Promise<PlanningSessionResponse> {
  return requestJson<PlanningSessionResponse, PlanningSessionCreateRequest>(
    "/loops/planning/sessions",
    { method: "POST", ...withJsonBody(payload) },
    "Failed to create planning session",
  );
}

export async function fetchPlanningSession(sessionId: number | string): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse>(
    `/loops/planning/sessions/${sessionId}`,
    {},
    "Failed to load planning session",
  );
}

export async function movePlanningSession(sessionId: number | string, direction: string): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse, { direction: string }>(
    `/loops/planning/sessions/${sessionId}/move`,
    { method: "POST", ...withJsonBody({ direction }) },
    "Failed to move planning session",
  );
}

export async function refreshPlanningSession(sessionId: number | string): Promise<PlanningSessionSnapshotResponse> {
  return requestJson<PlanningSessionSnapshotResponse>(
    `/loops/planning/sessions/${sessionId}/refresh`,
    { method: "POST" },
    "Failed to refresh planning session",
  );
}

export async function executePlanningSession(sessionId: number | string): Promise<PlanningSessionExecuteResponse> {
  return requestJson<PlanningSessionExecuteResponse>(
    `/loops/planning/sessions/${sessionId}/execute`,
    { method: "POST" },
    "Failed to execute planning session",
  );
}

export async function deletePlanningSession(sessionId: number | string): Promise<null> {
  return requestJson<null>(`/loops/planning/sessions/${sessionId}`, { method: "DELETE" }, "Failed to delete planning session");
}

export async function fetchRelationshipReviewActions(): Promise<RelationshipReviewActionResponse[]> {
  return requestJson<RelationshipReviewActionResponse[]>(
    "/loops/review/relationship/actions",
    {},
    "Failed to load relationship review actions",
  );
}

export async function createRelationshipReviewAction(
  payload: RelationshipReviewActionCreateRequest,
): Promise<RelationshipReviewActionResponse> {
  return requestJson<RelationshipReviewActionResponse, RelationshipReviewActionCreateRequest>(
    "/loops/review/relationship/actions",
    { method: "POST", ...withJsonBody(payload) },
    "Failed to create relationship review action",
  );
}

export async function updateRelationshipReviewAction(
  actionId: number | string,
  payload: RelationshipReviewActionUpdateRequest,
): Promise<RelationshipReviewActionResponse> {
  return requestJson<RelationshipReviewActionResponse, RelationshipReviewActionUpdateRequest>(
    `/loops/review/relationship/actions/${actionId}`,
    { method: "PUT", ...withJsonBody(payload) },
    "Failed to update relationship review action",
  );
}

export async function deleteRelationshipReviewAction(actionId: number | string): Promise<null> {
  return requestJson<null>(
    `/loops/review/relationship/actions/${actionId}`,
    { method: "DELETE" },
    "Failed to delete relationship review action",
  );
}

export async function fetchRelationshipReviewSessions(): Promise<RelationshipReviewSessionResponse[]> {
  return requestJson<RelationshipReviewSessionResponse[]>(
    "/loops/review/relationship/sessions",
    {},
    "Failed to load relationship review sessions",
  );
}

export async function createRelationshipReviewSession(
  payload: RelationshipReviewSessionCreateRequest,
): Promise<RelationshipReviewSessionResponse> {
  return requestJson<RelationshipReviewSessionResponse, RelationshipReviewSessionCreateRequest>(
    "/loops/review/relationship/sessions",
    { method: "POST", ...withJsonBody(payload) },
    "Failed to create relationship review session",
  );
}

export async function fetchRelationshipReviewSession(
  sessionId: number | string,
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse>(
    `/loops/review/relationship/sessions/${sessionId}`,
    {},
    "Failed to load relationship review session",
  );
}

export async function updateRelationshipReviewSession(
  sessionId: number | string,
  payload: RelationshipReviewSessionUpdateRequest,
): Promise<RelationshipReviewSessionResponse> {
  return requestJson<RelationshipReviewSessionResponse, RelationshipReviewSessionUpdateRequest>(
    `/loops/review/relationship/sessions/${sessionId}`,
    { method: "PUT", ...withJsonBody(payload) },
    "Failed to update relationship review session",
  );
}

export async function deleteRelationshipReviewSession(sessionId: number | string): Promise<null> {
  return requestJson<null>(
    `/loops/review/relationship/sessions/${sessionId}`,
    { method: "DELETE" },
    "Failed to delete relationship review session",
  );
}

export async function runRelationshipReviewSessionAction(
  sessionId: number | string,
  payload: RelationshipReviewSessionActionRequest,
): Promise<RelationshipReviewSessionActionResponse> {
  return requestJson<RelationshipReviewSessionActionResponse, RelationshipReviewSessionActionRequest>(
    `/loops/review/relationship/sessions/${sessionId}/act`,
    { method: "POST", ...withJsonBody(payload) },
    "Failed to run relationship review action",
  );
}

export async function moveRelationshipReviewSession(
  sessionId: number | string,
  direction: string,
): Promise<RelationshipReviewSessionSnapshotResponse> {
  return requestJson<RelationshipReviewSessionSnapshotResponse, { direction: string }>(
    `/loops/review/relationship/sessions/${sessionId}/move`,
    { method: "POST", ...withJsonBody({ direction }) },
    "Failed to move relationship review session",
  );
}

export async function fetchEnrichmentReviewActions(): Promise<EnrichmentReviewActionResponse[]> {
  return requestJson<EnrichmentReviewActionResponse[]>(
    "/loops/review/enrichment/actions",
    {},
    "Failed to load enrichment review actions",
  );
}

export async function createEnrichmentReviewAction(payload: JsonObject): Promise<EnrichmentReviewActionResponse> {
  return requestJson<EnrichmentReviewActionResponse, JsonObject>(
    "/loops/review/enrichment/actions",
    { method: "POST", ...withJsonBody(payload) },
    "Failed to create enrichment review action",
  );
}

export async function updateEnrichmentReviewAction(
  actionId: number | string,
  payload: JsonObject,
): Promise<EnrichmentReviewActionResponse> {
  return requestJson<EnrichmentReviewActionResponse, JsonObject>(
    `/loops/review/enrichment/actions/${actionId}`,
    { method: "PUT", ...withJsonBody(payload) },
    "Failed to update enrichment review action",
  );
}

export async function deleteEnrichmentReviewAction(actionId: number | string): Promise<null> {
  return requestJson<null>(
    `/loops/review/enrichment/actions/${actionId}`,
    { method: "DELETE" },
    "Failed to delete enrichment review action",
  );
}

export async function fetchEnrichmentReviewSessions(): Promise<EnrichmentReviewSessionResponse[]> {
  return requestJson<EnrichmentReviewSessionResponse[]>(
    "/loops/review/enrichment/sessions",
    {},
    "Failed to load enrichment review sessions",
  );
}

export async function createEnrichmentReviewSession(payload: JsonObject): Promise<EnrichmentReviewSessionResponse> {
  return requestJson<EnrichmentReviewSessionResponse, JsonObject>(
    "/loops/review/enrichment/sessions",
    { method: "POST", ...withJsonBody(payload) },
    "Failed to create enrichment review session",
  );
}

export async function fetchEnrichmentReviewSession(
  sessionId: number | string,
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse>(
    `/loops/review/enrichment/sessions/${sessionId}`,
    {},
    "Failed to load enrichment review session",
  );
}

export async function updateEnrichmentReviewSession(
  sessionId: number | string,
  payload: JsonObject,
): Promise<EnrichmentReviewSessionResponse> {
  return requestJson<EnrichmentReviewSessionResponse, JsonObject>(
    `/loops/review/enrichment/sessions/${sessionId}`,
    { method: "PUT", ...withJsonBody(payload) },
    "Failed to update enrichment review session",
  );
}

export async function deleteEnrichmentReviewSession(sessionId: number | string): Promise<null> {
  return requestJson<null>(
    `/loops/review/enrichment/sessions/${sessionId}`,
    { method: "DELETE" },
    "Failed to delete enrichment review session",
  );
}

export async function runEnrichmentReviewSessionAction(
  sessionId: number | string,
  payload: JsonObject,
): Promise<JsonObject> {
  return requestJson<JsonObject, JsonObject>(
    `/loops/review/enrichment/sessions/${sessionId}/act`,
    { method: "POST", ...withJsonBody(payload) },
    "Failed to run enrichment review action",
  );
}

export async function moveEnrichmentReviewSession(
  sessionId: number | string,
  direction: string,
): Promise<EnrichmentReviewSessionSnapshotResponse> {
  return requestJson<EnrichmentReviewSessionSnapshotResponse, { direction: string }>(
    `/loops/review/enrichment/sessions/${sessionId}/move`,
    { method: "POST", ...withJsonBody({ direction }) },
    "Failed to move enrichment review session",
  );
}

export async function answerEnrichmentReviewSessionClarifications(
  sessionId: number | string,
  payload: EnrichmentReviewSessionClarificationRequest,
): Promise<EnrichmentReviewSessionClarificationResponse> {
  return requestJson<EnrichmentReviewSessionClarificationResponse, EnrichmentReviewSessionClarificationRequest>(
    `/loops/review/enrichment/sessions/${sessionId}/clarifications/answer`,
    { method: "POST", ...withJsonBody(payload) },
    "Failed to answer enrichment clarifications",
  );
}

export async function exportLoops(): Promise<ExportLoopsResponse> {
  return requestJson<ExportLoopsResponse>("/loops/export", {}, "Failed to export loops");
}

export async function importLoops(loops: unknown[]): Promise<JsonObject> {
  return requestJson<JsonObject, ImportLoopsRequest>(
    "/loops/import",
    { method: "POST", ...withJsonBody({ loops }) },
    "Failed to import loops",
  );
}

export async function fetchDuplicateCandidates(loopId: number | string): Promise<DuplicatesListResponse | null> {
  try {
    return await requestJson<DuplicatesListResponse>(`/loops/${loopId}/duplicates`, {}, "Failed to load duplicate candidates");
  } catch {
    return null;
  }
}

export async function fetchMergePreview(
  duplicateLoopId: number | string,
  survivingLoopId: number | string,
): Promise<MergePreviewResponse> {
  return requestJson<MergePreviewResponse>(
    `/loops/${duplicateLoopId}/merge-preview/${survivingLoopId}`,
    {},
    "Failed to load merge preview",
  );
}

export async function mergeLoops(
  duplicateLoopId: number | string,
  survivingLoopId: number | string,
  fieldOverrides: Record<string, unknown> = {},
): Promise<JsonObject> {
  return requestJson<JsonObject, { target_loop_id: number | string; field_overrides: Record<string, unknown> }>(
    `/loops/${duplicateLoopId}/merge`,
    { method: "POST", ...withJsonBody({ target_loop_id: survivingLoopId, field_overrides: fieldOverrides }) },
    "Merge failed",
  );
}

export async function fetchSuggestions(loopId: number | string, pendingOnly = true): Promise<SurfaceSuggestion[]> {
  return requestJson<SurfaceSuggestion[]>(
    buildUrl(`/loops/${loopId}/suggestions`, { pending_only: pendingOnly }),
    {},
    "Failed to load suggestions",
  );
}

export async function applySuggestion(
  suggestionId: number | string,
  fields?: string[] | null,
): Promise<ApplySuggestionResponse> {
  return requestJson<ApplySuggestionResponse, { fields?: string[] }>(
    `/suggestions/${suggestionId}/apply`,
    { method: "POST", ...withJsonBody(fields && fields.length > 0 ? { fields } : {}) },
    "Failed to apply suggestion",
  );
}

export async function rejectSuggestion(suggestionId: number | string): Promise<JsonObject> {
  return requestJson<JsonObject>(`/suggestions/${suggestionId}/reject`, { method: "POST" }, "Failed to reject suggestion");
}

export async function submitClarification(
  loopId: number | string,
  answers: ClarificationSubmitBatchRequest["answers"],
): Promise<ClarificationSubmitResponse> {
  return requestJson<ClarificationSubmitResponse, SurfaceClarificationSubmitBatchRequest>(
    `/loops/${loopId}/clarifications/answer`,
    { method: "POST", ...withJsonBody({ answers }) },
    "Failed to submit clarifications",
  );
}

export async function refineClarification(
  loopId: number | string,
  answers: ClarificationSubmitBatchRequest["answers"],
): Promise<ClarificationRefinementResponse> {
  return requestJson<ClarificationRefinementResponse, SurfaceClarificationSubmitBatchRequest>(
    `/loops/${loopId}/clarifications/refine`,
    { method: "POST", ...withJsonBody({ answers }) },
    "Failed to refine clarifications",
  );
}

export async function fetchClarifications(loopId: number | string): Promise<ClarificationListResponse> {
  return requestJson<ClarificationListResponse>(
    `/loops/${loopId}/clarifications`,
    {},
    "Failed to load clarifications",
  );
}

export async function submitChatMessage(
  messages: ReadonlyArray<SurfaceChatRequestMessage>,
  stream = true,
  options: Partial<ChatPreferences> = {},
): Promise<Response> {
  const body: Record<string, unknown> = {
    messages,
    include_loop_context: options.includeLoopContext ?? true,
    include_memory_context: options.includeMemoryContext ?? true,
    memory_limit: options.memoryLimit ?? 10,
    include_rag_context: options.includeRagContext ?? false,
    rag_k: options.ragK ?? 5,
  };

  if (options.toolMode != null) {
    body["tool_mode"] = options.toolMode;
  }
  if (options.ragScope?.trim()) {
    body["rag_scope"] = options.ragScope.trim();
  }

  return requestStream(
    `/chat?stream=${stream}`,
    { method: "POST", ...withJsonBody(body) },
    "Chat request failed",
  );
}

export async function submitRagQuestion(question: string, stream = true): Promise<Response> {
  return requestStream(`/ask?q=${encodeURIComponent(question)}&stream=${stream}`, {}, "RAG request failed");
}

export async function fetchHealth(): Promise<HealthStatusResponse> {
  return requestJson<HealthStatusResponse>("/health", {}, "Failed to load health");
}

export async function ingestKnowledge(
  paths: string[],
  mode = "add",
  recursive = true,
): Promise<IngestResponse> {
  return requestJson<IngestResponse, { paths: string[]; mode: string; recursive: boolean }>(
    "/ingest",
    { method: "POST", ...withJsonBody({ paths, mode, recursive }) },
    "Knowledge ingestion failed",
  );
}

export async function updateRecurrence(
  loopId: number | string,
  rrule: string,
  timezone: string,
  enabled: boolean,
): Promise<SurfaceLoop> {
  return requestJson<SurfaceLoop, { recurrence_rrule: string; recurrence_tz: string; recurrence_enabled: boolean }>(
    `/loops/${loopId}/recurrence`,
    {
      method: "PUT",
      ...withJsonBody({
        recurrence_rrule: rrule,
        recurrence_tz: timezone,
        recurrence_enabled: enabled,
      }),
    },
    "Failed to update recurrence",
  );
}

export async function snoozeLoop(
  loopId: number | string,
  snoozeUntilUtc: string | null = null,
): Promise<SurfaceLoop> {
  return requestJson<SurfaceLoop, { snooze_until_utc: string | null }>(
    `/loops/${loopId}/snooze`,
    { method: "POST", ...withJsonBody({ snooze_until_utc: snoozeUntilUtc }) },
    "Failed to update snooze",
  );
}
