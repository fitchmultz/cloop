/**
 * recall-receipts.ts - Shared continuity receipts for recall-surface mutations.
 *
 * Purpose:
 *   Build compact landed receipts for recall-side mutations so direct memory
 *   changes and document ingestion remain resumable after the status line clears.
 *
 * Responsibilities:
 *   - Shape memory create/update/delete receipts.
 *   - Shape document-ingestion receipts.
 *   - Preserve working-set-aware resume targets for recall mutations.
 *
 * Scope:
 *   - Recall mutation receipt shaping only.
 *
 * Usage:
 *   - Imported by recall surfaces after a mutation succeeds.
 *
 * Invariants/Assumptions:
 *   - Receipts describe completed mutations, not passive surface opens.
 *   - Resume locations must stay durable after the mutation lands.
 */

import { createReceiptCard, withReceiptOutcome } from "../action-receipts";
import type { RecentShellActionEntry, WorkflowThreadRef } from "../contracts-ui";
import type { IngestResponse, MemoryEntryResponse } from "../domain";
import { createLocation } from "../shell-routing";

function shortText(value: string, max = 56): string {
  const normalized = value.trim().replaceAll(/\s+/g, " ");
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1).trimEnd()}…`;
}

function thread(id: string, title: string, summary: string): WorkflowThreadRef {
  return { id, kind: "recall", title, summary, parentOutcomeId: null };
}

function receiptEntry(input: {
  title: string;
  summary: string;
  tone: "progress" | "attention";
  preview: Array<{ label: string; value: string }>;
  resumeLocation: ReturnType<typeof createLocation>;
  resumeLabel: string;
  pinLabel: string;
  rollbackLabel: string;
  nextStep: string;
  metadata: Record<string, unknown>;
  workflowThread: WorkflowThreadRef;
  workingSetId: number | null;
}): Omit<RecentShellActionEntry, "occurredAt"> {
  const card = createReceiptCard({
    id: `${input.workflowThread.id}-${Date.now()}`,
    eyebrow: "Recall receipt",
    title: input.title,
    summary: input.summary,
    rationale: "Recall receipts keep durable context mutations resumable instead of leaving them trapped in transient status text.",
    tone: input.tone,
    preview: input.preview,
    trust: {
      generationLabel: "Recall mutation",
      generationTone: "progress",
      contextSources: ["Recall surface contract"],
      assumptions: ["The destination surface remains the canonical place to inspect the landed result."],
      confidenceLabel: input.tone === "attention" ? "Mutation applied with follow-up required" : "Mutation applied",
      confidenceTone: input.tone,
      freshnessLabel: "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: input.rollbackLabel,
      rollbackTone: "caution",
      impactSummary: input.summary,
      impactTone: input.tone,
    },
    handoff: {
      changeSummary: input.summary,
      createdResources: input.preview.map((item) => item.value).slice(0, 2),
      nextStep: input.nextStep,
      breadcrumbs: ["Home", "Recall"],
      workingSet: null,
    },
    resumeLocation: input.resumeLocation,
    resumeLabel: input.resumeLabel,
    resumeDescription: input.summary,
    pinLabel: input.pinLabel,
  });

  return withReceiptOutcome(
    {
      kind: "recall",
      label: input.title,
      description: input.summary,
      location: input.resumeLocation,
      metadata: input.metadata,
    },
    card,
    input.resumeLocation,
    { workflowThread: input.workflowThread },
  );
}

function memoryLabel(entry: Pick<MemoryEntryResponse, "id" | "key" | "content">): string {
  return entry.key?.trim() || shortText(entry.content) || `Memory #${entry.id}`;
}

export function buildRecallMemoryReceiptEntry(input: {
  action: "created" | "updated" | "deleted";
  entry: Pick<MemoryEntryResponse, "id" | "key" | "content" | "category" | "source">;
  workingSetId: number | null;
  query: string | null;
}): Omit<RecentShellActionEntry, "occurredAt"> {
  const label = memoryLabel(input.entry);
  const resumeLocation = input.action === "deleted"
    ? createLocation({ state: "recall", recallTool: "memory", workingSetId: input.workingSetId, query: input.query })
    : createLocation({ state: "recall", recallTool: "memory", memoryId: input.entry.id, workingSetId: input.workingSetId });
  const title = `${input.action === "deleted" ? "Deleted" : input.action === "updated" ? "Updated" : "Created"} memory · ${label}`;
  const summary = input.action === "deleted"
    ? `${label} was removed from durable memory.`
    : input.action === "updated"
      ? `${label} now reflects the latest durable context.`
      : `${label} is now available as durable memory.`;

  return receiptEntry({
    title,
    summary,
    tone: input.action === "deleted" ? "attention" : "progress",
    preview: [
      { label: "Memory", value: label },
      { label: "Category", value: input.entry.category },
      ...(input.workingSetId != null ? [{ label: "Context", value: `Working set #${input.workingSetId}` }] : []),
    ],
    resumeLocation,
    resumeLabel: input.action === "deleted" ? "Return to Memory" : "Open memory entry",
    pinLabel: input.action === "deleted" ? "Recall · Memory" : `Memory · ${label}`,
    rollbackLabel: input.action === "deleted"
      ? "Create a replacement memory entry if this durable context still matters."
      : "Edit or delete the memory entry if this durable context is no longer correct.",
    nextStep: input.action === "deleted"
      ? "Continue from Memory search or create a replacement entry if needed."
      : "Open the landed memory entry or keep working from Memory.",
    metadata: {
      source: "recall-memory",
      action: input.action,
      memoryId: input.entry.id,
      workingSetId: input.workingSetId,
      query: input.query,
    },
    workflowThread: thread(`recall:memory:${input.action}:${input.entry.id}`, title, summary),
    workingSetId: input.workingSetId,
  });
}

function pathLabel(path: string): string {
  return path.trim().split(/[\\/]/).filter(Boolean).at(-1) || "Knowledge path";
}

export function buildRecallIngestReceiptEntry(input: {
  path: string;
  mode: string;
  recursive: boolean;
  result: IngestResponse;
  workingSetId: number | null;
  query: string | null;
}): Omit<RecentShellActionEntry, "occurredAt"> {
  const failedCount = input.result.failed_files?.length ?? 0;
  const summary = failedCount > 0
    ? `Indexed ${input.result.files} files into ${input.result.chunks} chunks with ${failedCount} failures.`
    : `Indexed ${input.result.files} files into ${input.result.chunks} chunks.`;
  const title = `${input.mode === "replace" ? "Rebuilt" : "Indexed"} knowledge · ${pathLabel(input.path)}`;
  const resumeLocation = createLocation({
    state: "recall",
    recallTool: "rag",
    workingSetId: input.workingSetId,
    query: input.query,
  });

  return receiptEntry({
    title,
    summary,
    tone: failedCount > 0 ? "attention" : "progress",
    preview: [
      { label: "Path", value: pathLabel(input.path) },
      { label: "Files", value: `${input.result.files}` },
      { label: "Chunks", value: `${input.result.chunks}` },
      ...(input.workingSetId != null ? [{ label: "Context", value: `Working set #${input.workingSetId}` }] : []),
    ],
    resumeLocation,
    resumeLabel: "Open documents",
    pinLabel: `Recall · Documents · ${pathLabel(input.path)}`,
    rollbackLabel: "Reindex with a corrected path or ingestion mode if this document set is not the one you intended.",
    nextStep: "Ask a document-backed question or refine the ingest path if the indexed set is incomplete.",
    metadata: {
      source: "recall-rag",
      action: "ingest",
      path: input.path,
      mode: input.mode,
      recursive: input.recursive,
      workingSetId: input.workingSetId,
      query: input.query,
    },
    workflowThread: thread(`recall:rag:ingest:${input.path.trim().toLowerCase()}`, title, summary),
    workingSetId: input.workingSetId,
  });
}
