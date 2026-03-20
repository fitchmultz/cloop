/**
 * contracts-ui.ts - Frontend-only UI and client-state contracts.
 *
 * Purpose:
 *   Define strict TypeScript shapes for browser-only state that does not come
 *   directly from backend schemas.
 *
 * Responsibilities:
 *   - Type shell navigation, review mode, and chat preference state.
 *   - Type normalized chat payloads persisted in local storage.
 *   - Provide reusable UI contracts for operator action cards and shell routing.
 *
 * Scope:
 *   - Frontend local-state contracts only.
 *
 * Usage:
 *   - Import these interfaces/types from frontend shell modules when browser-only
 *     state needs a stable shared definition.
 *
 * Invariants/Assumptions:
 *   - These contracts stay distinct from generated OpenAPI/backend schema types.
 *   - New TypeScript work should prefer these shared contracts over ad-hoc inline
 *     browser-state shapes.
 */

export type AppTab =
  | "inbox"
  | "next"
  | "chat"
  | "memory"
  | "rag"
  | "review"
  | "metrics";

export type ReviewMode = "daily" | "weekly";
export type ChatToolMode = "none" | "llm" | null;

export type ShellState =
  | "operator"
  | "capture"
  | "do"
  | "decide"
  | "plan"
  | "review"
  | "recall"
  | "working_set";

export type RecallTool = "chat" | "memory" | "rag";
export type ReviewFocus = "planning" | "relationship" | "enrichment" | "cohorts";

export interface ShellLocationContract {
  state: ShellState;
  recallTool: RecallTool;
  reviewFocus: ReviewFocus | null;
  sessionId: number | null;
  loopId: number | null;
  viewId?: number | null;
  memoryId?: number | null;
  workingSetId?: number | null;
  query?: string | null;
}

export interface ContinuityCohortBaseline {
  count: number;
  itemIds: number[];
}

export interface ContinuitySessionBaseline {
  sessionId: number;
  loopCount: number;
  currentLoopId: number | null;
  updatedAtUtc: string;
}

export interface ContinuityPlanningBaseline extends ContinuitySessionBaseline {
  sessionName: string;
  status: "draft" | "in_progress" | "completed";
  generatedAtUtc: string | null;
  contextIsStale: boolean;
  staleTargetLoopCount: number;
  missingTargetLoopCount: number;
  targetLoopIds: number[];
  lastExecutedAtUtc: string | null;
  resourceChangeCount: number;
  downstreamResourceChangeCount: number;
}

export interface ContinuityBaselineSnapshot {
  recordedAtUtc: string;
  metrics: {
    staleOpenCount: number;
    blockedTooLongCount: number;
    noNextActionCount: number;
  };
  cohorts: {
    stale: ContinuityCohortBaseline;
    blocked_too_long: ContinuityCohortBaseline;
    due_soon_unplanned: ContinuityCohortBaseline;
    no_next_action: ContinuityCohortBaseline;
  };
  planningSession: ContinuityPlanningBaseline | null;
  relationshipSession: ContinuitySessionBaseline | null;
  enrichmentSession: ContinuitySessionBaseline | null;
  activeWorkingSetId: number | null;
  snoozedLoops: Array<{
    id: number;
    snoozeUntilUtc: string;
  }>;
}

export type RecentShellActionKind =
  | "navigation"
  | "planning"
  | "review"
  | "recall"
  | "working_set"
  | "working_set_session"
  | "command"
  | "bulk"
  | "snooze";

export interface ResumeAnchorTarget {
  kind: "planning" | "review";
  reviewFocus: "planning" | "relationship" | "enrichment";
  sessionId: number;
  visitedAtUtc: string;
  launchLocation: ShellLocationContract | null;
  resumeLocation: ShellLocationContract | null;
  outcomeTitle: string | null;
  outcomeSummary: string | null;
  workingSetId: number | null;
}

export interface ResumeAnchorState {
  planning: ResumeAnchorTarget | null;
  review: ResumeAnchorTarget | null;
}

export interface RecentShellActionOutcome {
  card: OperatorActionCard;
  resumeLocation: ShellLocationContract | null;
  rollbackLabel: string | null;
}

export interface RecentShellActionEntry {
  kind: RecentShellActionKind;
  label: string;
  description: string;
  location: ShellLocationContract | null;
  metadata?: Record<string, unknown> | null;
  outcome?: RecentShellActionOutcome | null;
  occurredAt: string;
}

export type OperatorActionCardKind = "mutation" | "decision" | "handoff" | "refresh" | "context" | "receipt";
export type OperatorActionCardTone = "neutral" | "attention" | "progress" | "caution";
export type OperatorActionCardActionType = "open" | "pin" | "event" | "stage" | "edit" | "defer";
export type OperatorActionCardActionVariant = "primary" | "secondary";
export type TrustTone = "neutral" | "attention" | "progress" | "caution";

export interface OperatorActionPreviewItem {
  label: string;
  value: string;
}

export interface TrustSurfaceMetadata {
  generationLabel?: string | null;
  generationTone?: TrustTone | null;
  contextSources: string[];
  assumptions: string[];
  confidenceLabel: string | null;
  confidenceTone?: TrustTone | null;
  freshnessLabel: string | null;
  freshnessTone?: TrustTone | null;
  rollbackLabel: string | null;
  rollbackTone?: TrustTone | null;
  impactSummary?: string | null;
  impactTone?: TrustTone | null;
}

export type OperatorActionTrustMetadata = TrustSurfaceMetadata;

export interface WorkingSetSessionMetadata {
  workingSetId: number;
  workingSetName: string;
  itemCount: number;
  missingItemCount: number;
}

export interface OperatorActionHandoff {
  changeSummary: string;
  createdResources: string[];
  nextStep: string | null;
  breadcrumbs: string[];
  workingSet?: WorkingSetSessionMetadata | null;
}

interface OperatorActionCardActionBase {
  type: OperatorActionCardActionType;
  label: string;
  variant: OperatorActionCardActionVariant;
  description: string;
}

export interface OperatorActionCardOpenAction extends OperatorActionCardActionBase {
  type: "open";
  location: ShellLocationContract;
}

export interface OperatorActionCardPinAction extends OperatorActionCardActionBase {
  type: "pin";
  location: ShellLocationContract;
  pinLabel?: string | undefined;
}

export interface OperatorActionCardEventAction extends OperatorActionCardActionBase {
  type: "event";
  attributes: Record<string, string>;
}

export interface OperatorActionCardStageAction extends OperatorActionCardActionBase {
  type: "stage";
  location: ShellLocationContract;
  stageLabel: string;
  stageDescription?: string | null;
  openAfterStage?: boolean | undefined;
}

export interface OperatorActionCardEditAction extends OperatorActionCardActionBase {
  type: "edit";
  location: ShellLocationContract;
  query: string;
}

export interface OperatorActionCardDeferAction extends OperatorActionCardActionBase {
  type: "defer";
  location: ShellLocationContract;
  deferLabel: string;
  deferDescription?: string | null;
}

export type OperatorActionCardAction =
  | OperatorActionCardOpenAction
  | OperatorActionCardPinAction
  | OperatorActionCardEventAction
  | OperatorActionCardStageAction
  | OperatorActionCardEditAction
  | OperatorActionCardDeferAction;

export interface OperatorActionCard {
  id: string;
  kind: OperatorActionCardKind;
  tone: OperatorActionCardTone;
  eyebrow: string;
  title: string;
  summary: string;
  rationale: string;
  preview: OperatorActionPreviewItem[];
  trust: OperatorActionTrustMetadata;
  handoff: OperatorActionHandoff | null;
  actionContextLabel?: string | null;
  actionWarning?: string | null;
  actions: OperatorActionCardAction[];
}

export interface ChatPreferences {
  toolMode: ChatToolMode;
  includeLoopContext: boolean;
  includeMemoryContext: boolean;
  includeRagContext: boolean;
  memoryLimit: number;
  ragK: number;
  ragScope: string;
}

export interface ChatToolCall {
  name: string;
  arguments: Record<string, unknown>;
}

export interface ChatMetadata {
  model: string | null;
  provider: string | null;
  api: string | null;
  latency_ms: number | null;
  stop_reason: string | null;
  usage: Record<string, unknown>;
}

export interface ChatContext {
  loop_context_applied: boolean;
  memory_context_applied: boolean;
  memory_entries_used: number;
  rag_context_applied: boolean;
  rag_chunks_used: number;
}

export interface ChatSource {
  id: string | number | null;
  document_path: string | null;
  chunk_index: number | null;
  score: number | null;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  createdAt: string;
  status: string;
  model: string | null;
  metadata: ChatMetadata | null;
  options: Record<string, unknown> | null;
  context: ChatContext | null;
  toolCalls: ChatToolCall[];
  toolResult: Record<string, unknown> | null;
  sources: ChatSource[];
  error: string | null;
}
