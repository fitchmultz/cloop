/**
 * recall-action-cards.ts - Shared action-card support for recall surfaces.
 *
 * Purpose:
 *   Render canonical action cards inside recall surfaces and inline recall
 *   results so chat, memory, and document answers share the same structured
 *   next-step model as operator and review surfaces.
 *
 * Responsibilities:
 *   - Build recall-specific context cards for chat, memory, and documents.
 *   - Build in-thread answer cards for grounded chat and document results.
 *   - Preserve active working-set scope when opening or pinning recall flows.
 *   - Render card decks into recall containers and inline answer regions.
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

export interface RecallResultActionCardContext extends RecallActionCardContext {
  tool: Extract<RecallTool, "chat" | "rag">;
  answerSummary: string;
  sourceCount: number;
  sourceLabels: string[];
  loopContextApplied?: boolean | undefined;
  memoryContextApplied?: boolean | undefined;
  memoryEntriesUsed?: number | undefined;
  ragContextApplied?: boolean | undefined;
  ragChunksUsed?: number | undefined;
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

function truncateCopy(value: string, maxLength = 140): string {
  const normalized = value.trim().replaceAll(/\s+/g, " ");
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function recallResultGroundingLabel(context: RecallResultActionCardContext): string {
  const parts: string[] = [];
  if (context.loopContextApplied) {
    parts.push("loops");
  }
  if (context.memoryContextApplied) {
    parts.push(context.memoryEntriesUsed ? `memory (${context.memoryEntriesUsed})` : "memory");
  }
  if (context.ragContextApplied || context.sourceCount > 0) {
    parts.push(context.ragChunksUsed ? `documents (${context.ragChunksUsed})` : "documents");
  }
  if (!parts.length) {
    return context.tool === "rag" ? "document evidence" : "grounded recall";
  }
  return parts.join(" · ");
}

function recallResultTrustSources(context: RecallResultActionCardContext): string[] {
  const sources = context.sourceLabels.slice(0, 2).map((label) => `Source: ${label}`);
  if (context.tool === "chat") {
    return [
      ...(context.loopContextApplied ? ["Loop context"] : []),
      ...(context.memoryContextApplied ? ["Direct memory"] : []),
      ...(context.ragContextApplied || context.sourceCount > 0 ? ["Indexed local documents"] : []),
      ...sources,
    ];
  }
  return ["Indexed local documents", ...sources];
}

export function buildRecallResultActionCards(
  context: RecallResultActionCardContext,
): OperatorActionCard[] {
  const workingSetLabel = context.workingSetId != null ? `Working set #${context.workingSetId}` : "No bounded working set";
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
  const doLocation = createLocation({ state: "do", workingSetId: context.workingSetId });
  const evidenceSources = recallResultTrustSources(context);
  const groundingLabel = recallResultGroundingLabel(context);
  const summary = truncateCopy(context.answerSummary, 160);

  if (context.tool === "chat") {
    const cards: OperatorActionCard[] = [
      {
        id: "recall-chat-result-next-step",
        kind: "handoff",
        tone: context.sourceCount > 0 || context.loopContextApplied ? "attention" : "progress",
        eyebrow: "From this answer",
        title: "Open Do with this grounded brief",
        summary: "Carry the grounded answer directly into execution without leaving the recall flow behind.",
        rationale: "In-thread action cards keep a grounded answer executable so the operator can move from recall to action without translating prose into a separate navigation step.",
        preview: [
          { label: "Answer", value: summary },
          { label: "Grounding", value: groundingLabel },
          { label: "Evidence", value: context.sourceCount ? `${context.sourceCount} source${context.sourceCount === 1 ? "" : "s"}` : "Context-backed answer" },
          { label: "Context", value: workingSetLabel },
        ],
        trust: {
          generationLabel: "Grounded recall result",
          generationTone: "attention",
          contextSources: evidenceSources,
          assumptions: ["The next action still needs explicit operator confirmation once you leave recall."],
          confidenceLabel: context.sourceCount
            ? `${context.sourceCount} supporting source${context.sourceCount === 1 ? "" : "s"}`
            : `${groundingLabel} applied`,
          confidenceTone: context.sourceCount ? "attention" : "progress",
          freshnessLabel: null,
          freshnessTone: "neutral",
          rollbackLabel: "Opening Do is non-mutating; edits remain explicit in the destination surface.",
          rollbackTone: "progress",
          impactSummary: "Use this answer as the working brief for the next execution step.",
          impactTone: "attention",
        },
        handoff: {
          changeSummary: "This answer is ready to hand off into execution with the same working-set scope.",
          createdResources: context.sourceLabels.slice(0, 3),
          nextStep: "Open Do, keep this brief in mind, and act on the highest-signal next move.",
          breadcrumbs: ["Home", "Recall", "Grounded chat", "Answer result"],
        },
        actionContextLabel: "Next action",
        actions: [
          openAction("Open Do", doLocation, "Carry this grounded answer into execution"),
          pinAction("Pin answer context", chatLocation, "Return to this grounded answer context", "Recall · Grounded answer"),
        ],
      },
    ];

    if (context.sourceCount > 0 || context.ragContextApplied) {
      cards.push({
        id: "recall-chat-result-evidence",
        kind: "context",
        tone: "progress",
        eyebrow: "Supporting evidence",
        title: "Reopen the source-backed context",
        summary: "Inspect the supporting documents again if you want to verify or quote the evidence before acting.",
        rationale: "Evidence-backed answers should keep their source path one click away so trust never depends on memory alone.",
        preview: [
          { label: "Question", value: context.ragQuestion || "Inspect the supporting documents again" },
          { label: "Sources", value: context.sourceLabels.slice(0, 2).join(" · ") || `${context.sourceCount} retrieved source${context.sourceCount === 1 ? "" : "s"}` },
        ],
        trust: {
          generationLabel: "Document-backed handoff",
          generationTone: "progress",
          contextSources: ["Indexed local documents", ...context.sourceLabels.slice(0, 2).map((label) => `Source: ${label}`)],
          assumptions: ["The supporting source material is still the best evidence for this answer."],
          confidenceLabel: `${context.sourceCount || context.ragChunksUsed || 1} evidence item${(context.sourceCount || context.ragChunksUsed || 1) === 1 ? "" : "s"} available`,
          confidenceTone: "attention",
          freshnessLabel: null,
          freshnessTone: "neutral",
          rollbackLabel: "Opening Documents is read-first until you ingest new files or ask again.",
          rollbackTone: "progress",
          impactSummary: "Inspect the source-backed context before carrying this answer forward.",
          impactTone: "progress",
        },
        handoff: {
          changeSummary: "This keeps the evidence behind the answer available without leaving the recall workflow.",
          createdResources: context.sourceLabels.slice(0, 3),
          nextStep: "Open document recall if you need to verify or quote the source-backed evidence.",
          breadcrumbs: ["Home", "Recall", "Grounded chat", "Documents"],
        },
        actionContextLabel: "Evidence follow-up",
        actions: [
          openAction("Open documents", ragLocation, "Inspect the evidence behind this answer"),
          pinAction("Pin documents", ragLocation, "Return to document-backed recall", "Recall · Documents"),
        ],
      });
    } else if (context.memoryContextApplied) {
      cards.push({
        id: "recall-chat-result-memory",
        kind: "context",
        tone: "neutral",
        eyebrow: "Durable context",
        title: "Reopen the memory context behind this answer",
        summary: "Check the underlying durable context again before you commit to the next move.",
        rationale: "Grounded answers that depend on memory should keep that durable context one click away for verification.",
        preview: [
          { label: "Grounding", value: groundingLabel },
          { label: "Context", value: workingSetLabel },
        ],
        trust: {
          generationLabel: "Memory-backed handoff",
          generationTone: "progress",
          contextSources: ["Direct memory", ...(context.memoryEntriesUsed ? [`${context.memoryEntriesUsed} memory entr${context.memoryEntriesUsed === 1 ? "y" : "ies"}`] : [])],
          assumptions: ["Durable memory still reflects the long-lived context this answer relied on."],
          confidenceLabel: context.memoryEntriesUsed ? `${context.memoryEntriesUsed} memory entr${context.memoryEntriesUsed === 1 ? "y" : "ies"} applied` : "Memory grounding applied",
          confidenceTone: "progress",
          freshnessLabel: null,
          freshnessTone: "neutral",
          rollbackLabel: "Opening Memory is read-first; edits remain explicit.",
          rollbackTone: "progress",
          impactSummary: "Review the durable context behind this answer before acting.",
          impactTone: "neutral",
        },
        handoff: {
          changeSummary: "This keeps the durable context behind the answer available for a quick fact check.",
          createdResources: [],
          nextStep: "Open Memory if you need to reconfirm commitments, preferences, or long-lived facts.",
          breadcrumbs: ["Home", "Recall", "Grounded chat", "Memory"],
        },
        actionContextLabel: "Context follow-up",
        actions: [
          openAction("Open memory", memoryLocation, "Review the memory context behind this answer"),
          pinAction("Pin memory", memoryLocation, "Return to durable memory", "Recall · Memory"),
        ],
      });
    }

    return cards;
  }

  return [
    {
      id: "recall-rag-result-chat",
      kind: "handoff",
      tone: "attention",
      eyebrow: "From this answer",
      title: "Turn this evidence into the next move",
      summary: "Carry the retrieved evidence into grounded chat so the next recommendation stays tied to the documents you just reviewed.",
      rationale: "In-thread action cards make a document answer actionable by preserving the evidence and handing it straight into the next grounded conversation.",
      preview: [
        { label: "Answer", value: summary },
        { label: "Sources", value: context.sourceCount ? `${context.sourceCount} source${context.sourceCount === 1 ? "" : "s"}` : "Document-backed answer" },
        { label: "Question", value: context.ragQuestion || "What should I do based on this evidence?" },
        { label: "Context", value: workingSetLabel },
      ],
      trust: {
        generationLabel: "Document-backed recall result",
        generationTone: "attention",
        contextSources: evidenceSources,
        assumptions: ["Grounded chat should keep loop or memory context enabled if you want the document answer turned into a recommendation."],
        confidenceLabel: `${context.sourceCount || context.ragChunksUsed || 1} evidence item${(context.sourceCount || context.ragChunksUsed || 1) === 1 ? "" : "s"} available`,
        confidenceTone: "attention",
        freshnessLabel: null,
        freshnessTone: "neutral",
        rollbackLabel: "Opening grounded chat is non-mutating by itself.",
        rollbackTone: "progress",
        impactSummary: "Move from evidence collection into a grounded next-step recommendation.",
        impactTone: "attention",
      },
      handoff: {
        changeSummary: "This answer is ready to hand off into grounded chat without losing its source-backed context.",
        createdResources: context.sourceLabels.slice(0, 3),
        nextStep: "Open grounded chat and ask what the retrieved evidence changes about the next move.",
        breadcrumbs: ["Home", "Recall", "Documents", "Answer result"],
      },
      actionContextLabel: "Next action",
      actions: [
        openAction("Open grounded chat", chatLocation, "Turn this evidence into a grounded next-step brief"),
        pinAction("Pin documents", ragLocation, "Return to document-backed recall", "Recall · Documents"),
      ],
    },
    {
      id: "recall-rag-result-do",
      kind: "context",
      tone: "progress",
      eyebrow: "Act from evidence",
      title: "Open Do with the same evidence in mind",
      summary: "Jump straight into execution while the retrieved evidence is still fresh and easy to revisit.",
      rationale: "Evidence-backed answers are most useful when the operator can act immediately without losing the link back to the supporting documents.",
      preview: [
        { label: "Evidence", value: context.sourceLabels.slice(0, 2).join(" · ") || `${context.sourceCount} source${context.sourceCount === 1 ? "" : "s"}` },
        { label: "Context", value: workingSetLabel },
      ],
      trust: {
        generationLabel: "Evidence-backed execution handoff",
        generationTone: "progress",
        contextSources: evidenceSources,
        assumptions: ["The next change still happens explicitly in the destination surface."],
        confidenceLabel: "Ready to act with source-backed context",
        confidenceTone: "progress",
        freshnessLabel: null,
        freshnessTone: "neutral",
        rollbackLabel: "Opening Do is non-mutating; edits remain explicit once you act.",
        rollbackTone: "progress",
        impactSummary: "Carry the evidence-backed answer directly into the next execution step.",
        impactTone: "progress",
      },
      handoff: {
        changeSummary: "This keeps the document answer actionable instead of stranded in the recall panel.",
        createdResources: context.sourceLabels.slice(0, 3),
        nextStep: "Open Do if you are ready to act on the evidence-backed answer now.",
        breadcrumbs: ["Home", "Recall", "Documents", "Do"],
      },
      actionContextLabel: "Execution handoff",
      actions: [
        openAction("Open Do", doLocation, "Carry this evidence-backed answer into execution"),
        pinAction("Pin answer context", ragLocation, "Return to this document-backed answer context", "Recall · Document answer"),
      ],
    },
  ];
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

export function renderRecallResultActionCards(
  context: RecallResultActionCardContext,
): string {
  const cards = buildRecallResultActionCards(context);
  if (!cards.length) {
    return "";
  }
  return `
    <div class="recall-inline-action-card-deck" aria-label="${context.tool === "chat" ? "Grounded answer" : "Document answer"} action cards">
      ${renderActionCardDeck(cards, "")}
    </div>
  `;
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
