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

import type { OperatorActionCard, OperatorActionCardAction, RecallTool, ShellLocationContract } from "../contracts-ui";
import { buildRecallRerunAction } from "../executable-rerun";
import { renderActionCardDeck } from "../operator-action-cards";
import { createLocation } from "../shell-routing";

export interface RecallActionCardContext {
  tool: RecallTool;
  workingSetId: number | null;
  chatGroundingSummary?: string | undefined;
  chatPrompt?: string | undefined;
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

function stageAction(
  label: string,
  location: ShellLocationContract,
  description: string,
  stageLabel: string,
  openAfterStage = true,
  variant: OperatorActionCardAction["variant"] = "primary",
): OperatorActionCardAction {
  return {
    type: "stage",
    label,
    variant,
    location,
    description,
    stageLabel,
    stageDescription: description,
    openAfterStage,
  };
}

function editAction(
  label: string,
  location: ShellLocationContract,
  description: string,
  query: string,
  variant: OperatorActionCardAction["variant"] = "secondary",
): OperatorActionCardAction {
  return {
    type: "edit",
    label,
    variant,
    location,
    description,
    query,
  };
}

function deferAction(
  label: string,
  location: ShellLocationContract,
  description: string,
  deferLabel: string,
  variant: OperatorActionCardAction["variant"] = "secondary",
): OperatorActionCardAction {
  return {
    type: "defer",
    label,
    variant,
    location,
    description,
    deferLabel,
    deferDescription: description,
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
  const doLocation = createLocation({ state: "do", workingSetId: context.workingSetId });
  const evidenceSources = recallResultTrustSources(context);
  const groundingLabel = recallResultGroundingLabel(context);
  const summary = truncateCopy(context.answerSummary, 160);
  const chatPrompt = context.chatPrompt?.trim() || "";
  const evidenceQuestion = context.ragQuestion?.trim()
    || (chatPrompt ? `What evidence should I verify for "${chatPrompt}"?` : "What evidence should I verify before acting?");
  const documentQuestion = context.ragQuestion?.trim() || evidenceQuestion;
  const memoryFollowUpQuery = context.memoryQuery?.trim()
    || (chatPrompt ? `What durable commitments or facts matter for "${chatPrompt}"?` : "Which durable commitments or facts should I reconfirm before acting?");
  const groundedBriefLabel = `Do · ${truncateCopy(summary, 56)}`;
  const groundedBriefDescription = `Execution brief: ${summary}`;
  const evidenceReviewLabel = `Recall · Evidence · ${truncateCopy(evidenceQuestion, 48)}`;
  const evidenceReviewDescription = `Evidence review: ${truncateCopy(evidenceQuestion, 140)}`;
  const memoryReviewLabel = `Recall · Memory · ${truncateCopy(memoryFollowUpQuery, 48)}`;
  const memoryReviewDescription = `Memory follow-up: ${truncateCopy(memoryFollowUpQuery, 140)}`;
  const chatQuestionLocation = createLocation({
    state: "recall",
    recallTool: "chat",
    workingSetId: context.workingSetId,
    query: chatPrompt || null,
  });
  const documentLocation = createLocation({
    state: "recall",
    recallTool: "rag",
    workingSetId: context.workingSetId,
    query: documentQuestion,
  });
  const memoryFollowUpLocation = createLocation({
    state: "recall",
    recallTool: "memory",
    workingSetId: context.workingSetId,
    query: memoryFollowUpQuery,
  });
  const stagedGroundedChatQuery = truncateCopy(
    context.ragQuestion?.trim()
      ? `Based on the evidence answering "${context.ragQuestion.trim()}", what should I do next?`
      : `Using this evidence, recommend the next move. ${summary}`,
    220,
  );
  const stagedGroundedChatLocation = createLocation({
    state: "recall",
    recallTool: "chat",
    workingSetId: context.workingSetId,
    query: stagedGroundedChatQuery,
  });
  const chatRerun = context.tool === "chat" && chatPrompt
    ? buildRecallRerunAction({
        recallTool: "chat",
        query: chatPrompt,
        workingSetId: context.workingSetId,
        provenanceLabel: "Grounded chat result",
        freshnessLabel: context.sourceCount
          ? `${context.sourceCount} supporting source${context.sourceCount === 1 ? "" : "s"} in the prior answer`
          : `${groundingLabel} applied in the prior answer`,
        strategySummary: "Reuse the same grounded question against current loop, memory, and document context.",
        includeLoopContext: context.loopContextApplied,
        includeMemoryContext: context.memoryContextApplied,
        includeRagContext: context.ragContextApplied,
      })
    : null;
  const ragRerun = context.tool === "rag" && documentQuestion
    ? buildRecallRerunAction({
        recallTool: "rag",
        query: documentQuestion,
        workingSetId: context.workingSetId,
        provenanceLabel: "Document-backed recall result",
        freshnessLabel: context.sourceCount
          ? `${context.sourceCount} retrieved source${context.sourceCount === 1 ? "" : "s"} in the prior answer`
          : "Document-backed recall result",
        strategySummary: "Reuse the same document question against the current indexed evidence.",
        includeRagContext: true,
      })
    : null;

  if (context.tool === "chat") {
    const cards: OperatorActionCard[] = [
      {
        id: "recall-chat-result-next-step",
        kind: "handoff",
        tone: context.sourceCount > 0 || context.loopContextApplied ? "attention" : "progress",
        eyebrow: "From this answer",
        title: "Stage this grounded brief for execution",
        summary: "Make the answer durable immediately, refine the question, or defer the handoff without losing the brief.",
        rationale: "In-thread action cards should carry a grounded answer into a durable next step instead of forcing the operator to reconstruct the follow-through by hand.",
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
          rollbackLabel: "Staging or deferring only saves a durable handoff; execution still stays explicit in Do.",
          rollbackTone: "progress",
          impactSummary: "Carry this answer forward as the working brief for the next execution step.",
          impactTone: "attention",
        },
        handoff: {
          changeSummary: "This answer can become a durable execution handoff with the same working-set scope.",
          createdResources: context.sourceLabels.slice(0, 3),
          nextStep: "Stage the next step to open Do now, or defer the brief if you want to preserve it without switching surfaces.",
          breadcrumbs: ["Home", "Recall", "Grounded chat", "Answer result"],
        },
        actionContextLabel: "Follow-through",
        actions: [
          stageAction(
            "Stage next step",
            doLocation,
            groundedBriefDescription,
            groundedBriefLabel,
          ),
          ...(chatRerun ? [chatRerun] : []),
          ...(chatPrompt
            ? [editAction(
                "Edit question",
                chatQuestionLocation,
                "Refine the grounded chat question behind this answer.",
                chatPrompt,
              )]
            : []),
          deferAction(
            "Defer for later",
            doLocation,
            groundedBriefDescription,
            groundedBriefLabel,
          ),
        ],
      },
    ];

    if (context.sourceCount > 0 || context.ragContextApplied) {
      cards.push({
        id: "recall-chat-result-evidence",
        kind: "context",
        tone: "progress",
        eyebrow: "Supporting evidence",
        title: "Stage or refine the source-backed follow-up",
        summary: "Keep the evidence path durable, reopen Documents with the question ready, or defer the follow-up without losing the supporting trail.",
        rationale: "Evidence-backed answers should keep their source path executable so trust never depends on memory alone.",
        preview: [
          { label: "Question", value: evidenceQuestion },
          { label: "Sources", value: context.sourceLabels.slice(0, 2).join(" · ") || `${context.sourceCount} retrieved source${context.sourceCount === 1 ? "" : "s"}` },
        ],
        trust: {
          generationLabel: "Document-backed follow-up",
          generationTone: "progress",
          contextSources: ["Indexed local documents", ...context.sourceLabels.slice(0, 2).map((label) => `Source: ${label}`)],
          assumptions: ["The supporting source material is still the best evidence for this answer."],
          confidenceLabel: `${context.sourceCount || context.ragChunksUsed || 1} evidence item${(context.sourceCount || context.ragChunksUsed || 1) === 1 ? "" : "s"} available`,
          confidenceTone: "attention",
          freshnessLabel: null,
          freshnessTone: "neutral",
          rollbackLabel: "Staging or deferring only saves the document follow-up; document recall stays read-first until you ask again.",
          rollbackTone: "progress",
          impactSummary: "Keep the source-backed verification step one action away before you act.",
          impactTone: "progress",
        },
        handoff: {
          changeSummary: "This keeps the evidence behind the answer available without forcing an immediate surface switch.",
          createdResources: context.sourceLabels.slice(0, 3),
          nextStep: "Stage the document review to reopen Documents now, refine the question, or defer it for later.",
          breadcrumbs: ["Home", "Recall", "Grounded chat", "Documents"],
        },
        actionContextLabel: "Evidence follow-up",
        actions: [
          stageAction(
            "Stage evidence review",
            documentLocation,
            evidenceReviewDescription,
            evidenceReviewLabel,
          ),
          editAction(
            "Edit document question",
            documentLocation,
            "Refine the document question that produced this answer.",
            evidenceQuestion,
          ),
          deferAction(
            "Defer evidence review",
            documentLocation,
            evidenceReviewDescription,
            evidenceReviewLabel,
          ),
        ],
      });
    } else if (context.memoryContextApplied) {
      cards.push({
        id: "recall-chat-result-memory",
        kind: "context",
        tone: "neutral",
        eyebrow: "Durable context",
        title: "Stage or refine the memory follow-up",
        summary: "Keep the memory check durable, reopen Memory with the query ready, or defer the follow-up without losing the context.",
        rationale: "Grounded answers that depend on memory should keep that durable context executable for a quick fact check.",
        preview: [
          { label: "Grounding", value: groundingLabel },
          { label: "Memory query", value: memoryFollowUpQuery },
        ],
        trust: {
          generationLabel: "Memory-backed follow-up",
          generationTone: "progress",
          contextSources: ["Direct memory", ...(context.memoryEntriesUsed ? [`${context.memoryEntriesUsed} memory entr${context.memoryEntriesUsed === 1 ? "y" : "ies"}`] : [])],
          assumptions: ["Durable memory still reflects the long-lived context this answer relied on."],
          confidenceLabel: context.memoryEntriesUsed ? `${context.memoryEntriesUsed} memory entr${context.memoryEntriesUsed === 1 ? "y" : "ies"} applied` : "Memory grounding applied",
          confidenceTone: "progress",
          freshnessLabel: null,
          freshnessTone: "neutral",
          rollbackLabel: "Staging or deferring only saves the memory follow-up; memory edits remain explicit.",
          rollbackTone: "progress",
          impactSummary: "Keep the durable-context check available before you act on the answer.",
          impactTone: "neutral",
        },
        handoff: {
          changeSummary: "This keeps the durable context behind the answer available for a quick fact check.",
          createdResources: [],
          nextStep: "Stage the memory review to reopen Memory now, refine the search, or defer it for later.",
          breadcrumbs: ["Home", "Recall", "Grounded chat", "Memory"],
        },
        actionContextLabel: "Context follow-up",
        actions: [
          stageAction(
            "Stage memory check",
            memoryFollowUpLocation,
            memoryReviewDescription,
            memoryReviewLabel,
          ),
          editAction(
            "Edit memory search",
            memoryFollowUpLocation,
            "Refine the durable-memory query behind this answer.",
            memoryFollowUpQuery,
          ),
          deferAction(
            "Defer memory review",
            memoryFollowUpLocation,
            memoryReviewDescription,
            memoryReviewLabel,
          ),
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
      title: "Stage a grounded follow-up from this evidence",
      summary: "Turn the retrieved evidence into a durable next-step conversation, refine the document question, or defer the evidence for later.",
      rationale: "Document answers are most valuable when the operator can preserve the evidence, refine the question, and reopen the next grounded conversation without rebuilding context by hand.",
      preview: [
        { label: "Answer", value: summary },
        { label: "Sources", value: context.sourceCount ? `${context.sourceCount} source${context.sourceCount === 1 ? "" : "s"}` : "Document-backed answer" },
        { label: "Question", value: documentQuestion },
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
        rollbackLabel: "Staging grounded chat only saves and reopens the follow-up question; the next answer still remains explicit.",
        rollbackTone: "progress",
        impactSummary: "Move from evidence collection into a durable grounded next-step recommendation.",
        impactTone: "attention",
      },
      handoff: {
        changeSummary: "This answer can become a durable grounded follow-up without losing its source-backed context.",
        createdResources: context.sourceLabels.slice(0, 3),
        nextStep: "Stage the grounded follow-up to reopen chat now, edit the document question, or defer the evidence for later.",
        breadcrumbs: ["Home", "Recall", "Documents", "Answer result"],
      },
      actionContextLabel: "Follow-through",
      actions: [
        stageAction(
          "Stage grounded follow-up",
          stagedGroundedChatLocation,
          `Grounded follow-up: ${truncateCopy(stagedGroundedChatQuery, 140)}`,
          "Recall · Grounded follow-up",
        ),
        ...(ragRerun ? [ragRerun] : []),
        editAction(
          "Edit document question",
          documentLocation,
          "Refine the document question behind this answer.",
          documentQuestion,
        ),
        deferAction(
          "Defer evidence",
          documentLocation,
          evidenceReviewDescription,
          "Recall · Documents",
        ),
      ],
    },
    {
      id: "recall-rag-result-do",
      kind: "context",
      tone: "progress",
      eyebrow: "Act from evidence",
      title: "Stage this evidence-backed handoff in Do",
      summary: "Carry the answer into execution now or save the brief for later without losing the source trail.",
      rationale: "Evidence-backed answers are most useful when the operator can keep the brief durable and still move into execution immediately.",
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
        rollbackLabel: "Staging or deferring only saves the execution brief; Do remains explicit once you act.",
        rollbackTone: "progress",
        impactSummary: "Carry the evidence-backed answer directly into the next execution step.",
        impactTone: "progress",
      },
      handoff: {
        changeSummary: "This keeps the document answer actionable instead of stranded in the recall panel.",
        createdResources: context.sourceLabels.slice(0, 3),
        nextStep: "Stage the Do handoff to open execution now, or defer it if you just need a durable brief.",
        breadcrumbs: ["Home", "Recall", "Documents", "Do"],
      },
      actionContextLabel: "Execution handoff",
      actions: [
        stageAction(
          "Stage Do handoff",
          doLocation,
          groundedBriefDescription,
          groundedBriefLabel,
        ),
        deferAction(
          "Defer Do handoff",
          doLocation,
          groundedBriefDescription,
          groundedBriefLabel,
        ),
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
