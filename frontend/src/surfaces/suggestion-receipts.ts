/**
 * suggestion-receipts.ts - Shared receipt builders for suggestion-surface outcomes.
 *
 * Purpose:
 *   Build deterministic recent-action receipts for clarification work initiated
 *   from the loop suggestion surface.
 *
 * Responsibilities:
 *   - Shape answer-only clarification submissions into shared receipt cards.
 *   - Attach the shared clarification-answer undo contract to those receipts.
 *   - Keep recent-history and command-palette follow-through grounded in the
 *     same operator card model used elsewhere.
 *
 * Scope:
 *   - Frontend-only receipt shaping for suggestion-surface clarification flows.
 *
 * Usage:
 *   - Imported by frontend/src/surfaces/suggestions.ts after direct
 *     clarification answers land.
 *
 * Invariants/Assumptions:
 *   - Answer-only clarification submissions remain reversible through the exact
 *     clarification IDs returned by the backend.
 *   - Receipt cards must keep a deterministic loop resume target.
 */

import { createReceiptCard, withReceiptOutcome } from "../action-receipts";
import type { RecentShellActionEntry, WorkflowThreadRef } from "../contracts-ui";
import type { ClarificationSubmitResponse } from "../domain";
import { buildClarificationUndoAction } from "../executable-undo";
import { createLocation } from "../shell-routing";
import type { SurfaceLoop } from "./contracts";

interface ClarificationAnswerReceiptInput {
  loop: Pick<SurfaceLoop, "id" | "title" | "raw_text">;
  result: ClarificationSubmitResponse;
}

function loopLabel(loop: Pick<SurfaceLoop, "id" | "title" | "raw_text">): string {
  const title = loop.title?.trim();
  if (title) {
    return title;
  }
  const rawText = loop.raw_text.trim();
  return rawText || `Loop #${loop.id}`;
}

function workflowThread(loopId: number, title: string, summary: string): WorkflowThreadRef {
  return {
    id: `clarification-answer:loop:${loopId}`,
    kind: "ad_hoc",
    title,
    summary,
    parentOutcomeId: null,
  };
}

export function buildClarificationAnswerReceiptEntry(
  input: ClarificationAnswerReceiptInput,
): Omit<RecentShellActionEntry, "occurredAt"> {
  const label = loopLabel(input.loop);
  const resumeLocation = createLocation({ state: "do", loopId: input.result.loop_id });
  const returnedClarificationIds = input.result.clarifications.map((clarification) => clarification.id);
  const undoAction = buildClarificationUndoAction(input.result.loop_id, returnedClarificationIds);
  const clarificationIds = undoAction?.undo.kind === "clarification_answer"
    ? undoAction.undo.clarificationIds
    : returnedClarificationIds;
  const answeredCount = input.result.answered_count;
  const supersededCount = input.result.superseded_suggestion_ids?.length ?? 0;
  const summary = input.result.message?.trim()
    || (answeredCount === 1
      ? `Recorded 1 clarification answer for ${label}.`
      : `Recorded ${answeredCount} clarification answers for ${label}.`);
  const cardTitle = answeredCount === 1
    ? `Saved clarification answer for ${label}`
    : `Saved ${answeredCount} clarification answers for ${label}`;
  const card = createReceiptCard({
    id: `clarification-answer-${input.result.loop_id}-${clarificationIds.join("-") || Date.now()}`,
    eyebrow: "Suggestion receipt",
    title: cardTitle,
    summary,
    rationale:
      "Suggestion-surface receipts keep answer-only clarification work reversible and discoverable from recent history without forcing an immediate rerun.",
    tone: "progress",
    preview: [
      { label: "Loop", value: label },
      { label: "Answered clarifications", value: String(answeredCount) },
      { label: "Superseded suggestions", value: String(supersededCount) },
      ...(input.result.clarifications[0]?.question
        ? [{
            label: input.result.clarifications.length === 1 ? "Question" : "First question",
            value: input.result.clarifications[0].question,
          }]
        : []),
    ],
    trust: {
      generationLabel: "Recorded clarification answers",
      generationTone: "progress",
      contextSources: ["Loop suggestion surface", `Loop #${input.result.loop_id}`],
      assumptions: ["Undo remains exact-handle safe until later suggestion drift makes the answer stale."],
      confidenceLabel: answeredCount === 1 ? "Answer saved" : "Answers saved",
      confidenceTone: "progress",
      freshnessLabel: "Saved just now",
      freshnessTone: "progress",
      rollbackLabel: undoAction
        ? (supersededCount > 0
          ? `Undo restores the unanswered clarifications and reopens ${supersededCount} superseded suggestion${supersededCount === 1 ? "" : "s"}.`
          : "Undo restores these clarifications to their unanswered state.")
        : "Undo is unavailable because no clarification IDs were returned.",
      rollbackTone: undoAction ? "caution" : "neutral",
      impactSummary: supersededCount > 0
        ? `The saved answers superseded ${supersededCount} older suggestion${supersededCount === 1 ? "" : "s"}.`
        : "The answers are saved without rerunning enrichment.",
      impactTone: supersededCount > 0 ? "attention" : "progress",
    },
    handoff: {
      changeSummary: summary,
      createdResources: [
        answeredCount === 1 ? "1 saved clarification answer" : `${answeredCount} saved clarification answers`,
        ...(supersededCount > 0
          ? [supersededCount === 1 ? "1 superseded suggestion" : `${supersededCount} superseded suggestions`]
          : []),
      ],
      nextStep: supersededCount > 0
        ? "Resume the loop to review the saved answers or undo them before you rerun enrichment."
        : "Resume the loop or rerun enrichment when you want a refreshed suggestion.",
      breadcrumbs: ["Home", "Do", label],
    },
    resumeLocation,
    resumeLabel: "Open loop",
    resumeDescription: summary,
    pinLabel: `Loop · ${label}`,
    actions: undoAction ? [undoAction] : [],
  });

  return withReceiptOutcome(
    {
      kind: "review",
      label: card.title,
      description: card.summary,
      location: resumeLocation,
      metadata: {
        source: "suggestion-surface",
        loopId: input.result.loop_id,
        clarificationIds,
        answeredCount,
        supersededSuggestionIds: input.result.superseded_suggestion_ids ?? [],
        reviewFocus: "enrichment",
      },
    },
    card,
    resumeLocation,
    { workflowThread: workflowThread(input.result.loop_id, card.title, card.summary) },
  );
}
