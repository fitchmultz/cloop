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
  | "recall";

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
  query?: string | null;
}

export type OperatorActionCardKind = "mutation" | "decision" | "handoff" | "refresh" | "context";
export type OperatorActionCardTone = "neutral" | "attention" | "progress" | "caution";
export type OperatorActionCardActionType = "open" | "pin";
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

export interface OperatorActionHandoff {
  changeSummary: string;
  createdResources: string[];
  nextStep: string | null;
  breadcrumbs: string[];
}

export interface OperatorActionCardAction {
  type: OperatorActionCardActionType;
  label: string;
  variant: OperatorActionCardActionVariant;
  location: ShellLocationContract;
  description: string;
  pinLabel?: string | undefined;
}

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
