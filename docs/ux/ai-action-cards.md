# AI Action Cards

## Why

Cloop’s AI outputs are most valuable when they move work forward. The product should treat AI as a preparation and recommendation system that produces executable work objects, not just narrative responses.

## Outcome

Planning, chat, enrichment, and review-related AI output should render as structured action cards that explain:

- what is being proposed
- why it is being proposed
- what context it used
- what will happen if the user accepts it
- how the user can modify, defer, reject, or undo it

## User jobs

- Understand AI recommendations quickly.
- Compare options without reading long text first.
- Execute or edit suggested changes safely.
- See downstream consequences before committing.

## Non-goals

- Eliminating narrative explanation entirely.
- Auto-executing consequential actions by default.
- Replacing deterministic workflows with chat-only interaction.

## UX principles applied

- Action over narration.
- Trust at the point of action.
- Calm by default, deep on demand.
- Human authority, AI acceleration.

## Card anatomy

Every action card should have:

1. **Action title**
   - concise imperative summary
2. **Why this exists**
   - short rationale grounded in loops, memory, RAG, or workflow state
3. **Preview**
   - target objects, payload summary, or before/after diff
4. **Controls**
   - execute
   - edit before execute
   - defer
   - reject
5. **Trust metadata**
   - context sources used
   - assumptions
   - confidence or certainty language where applicable
   - rollback availability
6. **Next-step preview**
   - what surface or queue likely comes next

## Card types

- **Mutation card**: update/create/transition loop, create session, apply suggestion
- **Decision card**: choose between options or relationship outcomes
- **Handoff card**: open the next saved queue or workflow
- **Refresh card**: regenerate stale plan or session
- **Context card**: attach relevant memory/RAG context to the current working set

## Key workflows

### Chat-to-action flow

1. User asks grounded chat for help.
2. Response contains narrative plus one or more action cards.
3. User executes, edits, or defers a suggested action without leaving the conversation context blindly.

### Planning-to-action flow

1. Planning checkpoint completes.
2. Result renders summary plus action cards for created resources and next queues.
3. User launches directly into the next surface or inspects rollback cues.

### Review-to-action flow

1. Review session item is loaded.
2. System surfaces recommended next moves as action cards beside the decision UI.
3. User applies a saved action or edits the recommendation before execution.

## States and edge cases

- **Low-confidence suggestion**: card language should show recommendation, not certainty.
- **Non-reversible action**: card must emphasize irreversibility before execution.
- **Blocked by missing context**: card should expose the missing assumption or required clarification.
- **Already stale**: card should surface that underlying state changed since generation.

## Contract implications

- Shared backend execution outputs should expose enough structured fields to render cards without re-parsing natural language.
- Existing planning execution payloads, follow-up resources, launch surfaces, and rollback cues are the starting model.
- Chat and review surfaces may need shared “recommended actions” payloads that match the same card schema.

## Acceptance criteria

- Major AI-backed surfaces can render executable action cards instead of only text summaries.
- Users can inspect rationale, preview changes, and act without guessing side effects.
- Cards visibly distinguish reversible from non-reversible actions.
- Narrative text remains secondary support, not the only operational surface.

## Current implementation baseline

- Planning follow-up resources, launch surfaces, operator action cards, review impact cards, enrichment suggestion cards, recall support decks, and in-thread recall result cards now share the same structured card renderer.
- Grounded chat answers and document-answer results now surface trust-framed, executable handoff cards inline instead of leaving recall outputs prose-only.
- Shared action cards now support first-class stage, edit, defer, undo, and rerun/refresh follow-through alongside open, pin, and review-local event actions.
- Recall result cards now use those richer follow-through actions to save durable briefs, reopen editable source questions, rerun grounded answers, and defer evidence or execution handoffs without losing working-set scope.
- Planning and saved review-session cards now expose one shared rerun contract that makes provenance, freshness, strategy summary, strict invariants, variable attempt behavior, and landing semantics explicit before the operator refreshes a workflow.
- Card-triggered working-set changes, review decisions, planning execution, reruns, and command-palette actions now emit shared receipt cards with rollback cues and resume-from-landed-outcome affordances instead of disappearing into one-line status text.
- Shared receipt, continuity, and rollback behavior is specified in [`outcome-continuity.md`](outcome-continuity.md), [`continuity-intelligence.md`](continuity-intelligence.md), and [`undo-actions.md`](undo-actions.md).

## Dependencies

- [`docs/ux/principles.md`](principles.md)
- [`docs/ux/workflow-handoffs.md`](workflow-handoffs.md)
- [`docs/ux/trust-surfaces.md`](trust-surfaces.md)

## Open questions

- Should action cards share one canonical schema across planning, chat, and review, or one core schema with workflow-specific extensions?
- Which cards deserve batch execution versus individual operator confirmation?
