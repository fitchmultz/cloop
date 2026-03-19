/**
 * recall-action-cards.ts - Shared action-card support for recall surfaces.
 *
 * Purpose:
 *   Render canonical action cards inside recall surfaces so chat, memory, and
 *   document recall share the same structured next-step model as operator and
 *   review surfaces.
 *
 * Responsibilities:
 *   - Build recall-specific context cards for chat, memory, and documents.
 *   - Preserve active working-set scope when opening or pinning recall flows.
 *   - Render card decks into the current recall surface container.
 *
 * Scope:
 *   - Frontend-only recall presentation helpers.
 *
 * Usage:
 *   - Imported by recall surface modules to refresh their support decks.
 *
 * Invariants/Assumptions:
 *   - Cards remain declarative and use shared shell locations for navigation.
 *   - Working-set scope is optional but should be carried when available.
 */

import type { OperatorActionCard, RecallTool, ShellLocationContract } from "../contracts-ui";
import { renderActionCardDeck } from "../operator-action-cards";
import { createLocation } from "../shell-routing";

export interface RecallActionCardContext {
  tool: RecallTool;
  workingSetId: number | null;
  chatGroundingSummary?: string | undefined;
  memoryQuery?: string | undefined;
  ragQuestion?: string | undefined;
  hasKnowledge?: boolean | undefined;
}

function openAction(label: string, location: ShellLocationContract, description: string) {
  return {
    type: "open" as const,
    label,
    variant: "primary" as const,
    location,
    description,
  };
}

function pinAction(label: string, location: ShellLocationContract, description: string, pinLabel: string) {
  return {
    type: "pin" as const,
    label,
    variant: "secondary" as const,
    location,
    description,
    pinLabel,
  };
}

function baseRecallLocation(tool: RecallTool, workingSetId: number | null): ShellLocationContract {
  return createLocation({ state: "recall", recallTool: tool, workingSetId });
}

export function buildRecallActionCards(context: RecallActionCardContext): OperatorActionCard[] {
  const chatLocation = baseRecallLocation("chat", context.workingSetId);
  const memoryLocation = createLocation({
    state: "recall",
    recallTool: "memory",
    workingSetId: context.workingSetId,
    query: context.memoryQuery ?? null,
  });
  const ragLocation = createLocation({
    state: "recall",
    recallTool: "rag",
    workingSetId: context.workingSetId,
    query: context.ragQuestion ?? null,
  });

  const workingSetLabel = context.workingSetId != null ? `Working set #${context.workingSetId}` : "No bounded working set";

  if (context.tool === "chat") {
    return [
      {
        id: "recall-chat-brief",
        kind: "context",
        tone: "attention",
        eyebrow: "Grounded chat",
        title: "Ask for a grounded next-step brief",
        summary: "Start with one high-signal question that synthesizes real loops, memory, and optional document grounding into a concrete next move.",
        rationale: "Structured recall cards keep grounded chat from feeling like a blank box and preserve the same action-first framing used elsewhere in the shell.",
        preview: [
          { label: "Best prompt", value: "What changed, what is blocked, and what should I do now?" },
          { label: "Grounding", value: context.chatGroundingSummary || "Loops and memory are usually the best default." },
          { label: "Context", value: workingSetLabel },
        ],
        trust: {
          contextSources: ["Loop context", "Memory context", "Current shell state"],
          assumptions: ["Grounded chat is strongest when its context toggles reflect the real question you are asking."],
          confidenceLabel: "High-signal recall prompt ready",
          rollbackLabel: "Opening chat does not mutate anything by itself.",
          freshnessLabel: null,
          impactSummary: "Use one prompt to turn current system state into an explicit recommendation.",
        },
        handoff: {
          changeSummary: "This keeps recall aligned with the current operational context instead of starting from a blank assistant thread.",
          createdResources: [],
          nextStep: "Ask for a prioritized brief or a recommended next move.",
          breadcrumbs: ["Home", "Recall", "Grounded chat"],
        },
        actions: [
          openAction("Stay in grounded chat", chatLocation, "Ask for a grounded next-step brief"),
          pinAction("Pin chat", chatLocation, "Return to grounded chat", "Recall · Grounded chat"),
        ],
      },
      {
        id: "recall-chat-memory",
        kind: "context",
        tone: "progress",
        eyebrow: "Durable context",
        title: "Check durable memory before acting",
        summary: "Open Memory when the next move depends on commitments, preferences, or durable facts that should shape the answer.",
        rationale: "Memory is the right recall companion when the problem is stable context, not just today’s loop graph.",
        preview: [
          { label: "Best use", value: "Preferences, commitments, and durable context" },
          { label: "Context", value: workingSetLabel },
        ],
        trust: {
          contextSources: ["Direct memory store", "Current shell state"],
          assumptions: ["Memory entries should capture durable truths, not scratch notes."],
          confidenceLabel: "Useful before the next recommendation",
          rollbackLabel: "Opening Memory is read-first; edits remain explicit.",
          freshnessLabel: null,
          impactSummary: "Review durable memory before relying on a chat answer alone.",
        },
        handoff: {
          changeSummary: "This keeps durable memory one move away from grounded chat.",
          createdResources: [],
          nextStep: "Open Memory if preferences, commitments, or facts should shape the next answer.",
          breadcrumbs: ["Home", "Recall", "Memory"],
        },
        actions: [
          openAction("Open memory", memoryLocation, "Inspect durable memory before the next recommendation"),
          pinAction("Pin memory", memoryLocation, "Return to durable memory", "Recall · Memory"),
        ],
      },
      {
        id: "recall-chat-documents",
        kind: "context",
        tone: context.hasKnowledge === false ? "caution" : "neutral",
        eyebrow: "Document evidence",
        title: context.hasKnowledge === false ? "Index local documents before asking for evidence" : "Bring document evidence into the same recall loop",
        summary: context.hasKnowledge === false
          ? "The document recall surface is the next step when you need local evidence but have not indexed the relevant files yet."
          : "Open Documents when the next answer should be grounded in indexed local notes, playbooks, or reference material.",
        rationale: "Document recall works best when the operator can move into evidence-backed recall without losing the current work-state context.",
        preview: [
          { label: "Best use", value: "Policies, notes, manuals, and other local references" },
          { label: "Prompt idea", value: context.ragQuestion || "What local docs should shape this decision?" },
        ],
        trust: {
          contextSources: ["Indexed local documents", "RAG retrieval"],
          assumptions: [context.hasKnowledge === false ? "The needed material still needs to be indexed locally." : "The relevant material has already been indexed locally."],
          confidenceLabel: context.hasKnowledge === false ? "Index first, then ask" : "Evidence-backed recall available",
          rollbackLabel: "Opening Documents is non-mutating until you ingest or ask.",
          freshnessLabel: null,
          impactSummary: "Move from narrative recall into source-backed evidence when the next action needs proof.",
        },
        handoff: {
          changeSummary: "This preserves the same recall context while switching from chat synthesis to document-backed evidence.",
          createdResources: [],
          nextStep: context.hasKnowledge === false ? "Index the right files or folders, then ask a grounded question." : "Ask a document-grounded question without rebuilding context.",
          breadcrumbs: ["Home", "Recall", "Documents"],
        },
        actions: [
          openAction(context.hasKnowledge === false ? "Open documents" : "Open document recall", ragLocation, "Use document-backed recall for the next question"),
          pinAction("Pin documents", ragLocation, "Return to document-backed recall", "Recall · Documents"),
        ],
      },
    ];
  }

  if (context.tool === "memory") {
    return [
      {
        id: "recall-memory-search",
        kind: "context",
        tone: "attention",
        eyebrow: "Memory search",
        title: "Search durable context before reopening workflow state",
        summary: "Use Memory to confirm facts, preferences, or commitments before you jump back into plan, review, or chat.",
        rationale: "This keeps durable context review explicit instead of forcing the operator to remember what should already be stored.",
        preview: [
          { label: "Search", value: context.memoryQuery || "Try a person, project, preference, or commitment" },
          { label: "Context", value: workingSetLabel },
        ],
        trust: {
          contextSources: ["Direct memory store", "Current shell state"],
          assumptions: ["Memory should hold durable context worth reusing across sessions."],
          confidenceLabel: "High-value durable context search ready",
          rollbackLabel: "Editing memory remains explicit and local to this surface.",
          freshnessLabel: null,
          impactSummary: "Search memory before acting on stale assumptions.",
        },
        handoff: {
          changeSummary: "This makes durable context a first-class step in the operator loop.",
          createdResources: [],
          nextStep: "Search memory, then reopen the next workflow with the right context in mind.",
          breadcrumbs: ["Home", "Recall", "Memory"],
        },
        actions: [
          openAction("Stay in memory", memoryLocation, "Search or review durable memory"),
          pinAction("Pin memory", memoryLocation, "Return to durable memory", "Recall · Memory"),
        ],
      },
      {
        id: "recall-memory-chat",
        kind: "context",
        tone: "progress",
        eyebrow: "Grounded synthesis",
        title: "Carry memory back into grounded chat",
        summary: "After checking durable context, reopen grounded chat to turn those facts into a recommendation or summary.",
        rationale: "Memory becomes more useful when the operator can immediately put it back into a grounded decision conversation.",
        preview: [
          { label: "Best prompt", value: "Use the current memory context to recommend the next move." },
        ],
        trust: {
          contextSources: ["Direct memory store", "Loop context", "Current shell state"],
          assumptions: ["Loop and memory grounding should both stay enabled for this handoff."],
          confidenceLabel: "Ready to turn durable context into a recommendation",
          rollbackLabel: "Opening chat is non-mutating by itself.",
          freshnessLabel: null,
          impactSummary: "Move from stored facts back into a grounded recommendation.",
        },
        handoff: {
          changeSummary: "This keeps memory review connected to the broader operator loop.",
          createdResources: [],
          nextStep: "Reopen grounded chat and ask for the next move using the durable context you just checked.",
          breadcrumbs: ["Home", "Recall", "Grounded chat"],
        },
        actions: [
          openAction("Open grounded chat", chatLocation, "Turn memory context into a grounded recommendation"),
          pinAction("Pin chat", chatLocation, "Return to grounded chat", "Recall · Grounded chat"),
        ],
      },
    ];
  }

  return [
    {
      id: "recall-rag-evidence",
      kind: "context",
      tone: context.hasKnowledge === false ? "caution" : "attention",
      eyebrow: "Document recall",
      title: context.hasKnowledge === false ? "Index evidence before asking for an answer" : "Ask a document-grounded decision question",
      summary: context.hasKnowledge === false
        ? "Document recall is empty until the relevant local files are indexed."
        : "Use Documents when the next move should be grounded in retrieved local sources instead of memory or narrative alone.",
      rationale: "This keeps document recall aligned with the same action-first shell contract used by operator and review surfaces.",
      preview: [
        { label: "Question", value: context.ragQuestion || "What local docs should shape this decision?" },
        { label: "Context", value: workingSetLabel },
      ],
      trust: {
        contextSources: ["Indexed local documents", "RAG retrieval"],
        assumptions: [context.hasKnowledge === false ? "The right files still need to be indexed." : "The relevant references have already been indexed locally."],
        confidenceLabel: context.hasKnowledge === false ? "Index first" : "Evidence-backed answer path ready",
        rollbackLabel: "Opening document recall is non-mutating until you ingest or ask.",
        freshnessLabel: null,
        impactSummary: "Use local source material when the next answer needs evidence.",
      },
      handoff: {
        changeSummary: "This keeps evidence-backed recall in the same shell flow as planning, review, and chat.",
        createdResources: [],
        nextStep: context.hasKnowledge === false ? "Index files or folders, then ask again." : "Ask a source-backed question and inspect the retrieved evidence.",
        breadcrumbs: ["Home", "Recall", "Documents"],
      },
      actions: [
        openAction("Stay in documents", ragLocation, "Use document-backed recall"),
        pinAction("Pin documents", ragLocation, "Return to document-backed recall", "Recall · Documents"),
      ],
    },
    {
      id: "recall-rag-memory",
      kind: "context",
      tone: "neutral",
      eyebrow: "Cross-check memory",
      title: "Compare retrieved evidence against durable memory",
      summary: "Switch to Memory when a document answer should be reconciled with durable facts, commitments, or preferences.",
      rationale: "Evidence and durable memory solve different problems; good recall flows make it trivial to compare both before acting.",
      preview: [
        { label: "Best use", value: "Cross-check source-backed evidence against durable context" },
      ],
      trust: {
        contextSources: ["Indexed local documents", "Direct memory store"],
        assumptions: ["Durable memory and local documents can complement each other rather than compete."],
        confidenceLabel: "Useful when evidence and durable context must agree",
        rollbackLabel: "Opening Memory is read-first.",
        freshnessLabel: null,
        impactSummary: "Cross-check evidence with durable context before committing to the next move.",
      },
      handoff: {
        changeSummary: "This keeps evidence-backed recall connected to durable context review.",
        createdResources: [],
        nextStep: "Open Memory if the document answer should be reconciled with durable commitments or preferences.",
        breadcrumbs: ["Home", "Recall", "Memory"],
      },
      actions: [
        openAction("Open memory", memoryLocation, "Compare documents against durable memory"),
        pinAction("Pin memory", memoryLocation, "Return to durable memory", "Recall · Memory"),
      ],
    },
    {
      id: "recall-rag-chat",
      kind: "context",
      tone: "progress",
      eyebrow: "Synthesis",
      title: "Carry retrieved evidence back into grounded chat",
      summary: "After reading the sources, reopen grounded chat to synthesize what the evidence means for the next action.",
      rationale: "Document recall is most useful when the operator can immediately turn evidence into a concrete recommendation.",
      preview: [
        { label: "Best prompt", value: "Use these documents to recommend the next move." },
      ],
      trust: {
        contextSources: ["Indexed local documents", "Loop context", "Memory context"],
        assumptions: ["Document-grounded evidence should shape the next chat answer when context is enabled."],
        confidenceLabel: "Ready to turn evidence into a recommendation",
        rollbackLabel: "Opening chat is non-mutating by itself.",
        freshnessLabel: null,
        impactSummary: "Move from evidence collection into a grounded next-step recommendation.",
      },
      handoff: {
        changeSummary: "This keeps document recall connected to the operator’s grounded decision loop.",
        createdResources: [],
        nextStep: "Reopen grounded chat and ask what the retrieved evidence changes.",
        breadcrumbs: ["Home", "Recall", "Grounded chat"],
      },
      actions: [
        openAction("Open grounded chat", chatLocation, "Turn retrieved evidence into a grounded recommendation"),
        pinAction("Pin chat", chatLocation, "Return to grounded chat", "Recall · Grounded chat"),
      ],
    },
  ];
}

export function renderRecallActionCards(
  container: HTMLElement | null,
  context: RecallActionCardContext,
): void {
  if (!container) {
    return;
  }
  container.innerHTML = renderActionCardDeck(
    buildRecallActionCards(context),
    "",
  );
}
