# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn the shipped operator shell, trust surfaces, workflow handoffs, and first deterministic continuity slice into a world-class cross-session decision and execution workspace: sharper drift handling, tighter resume cues, and deeper operational memory.

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do now, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, and handoff.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, and reversibility anywhere the system proposes or executes meaningful work.

## UX Vision and Spec Set

- Experience vision: [`docs/ux/experience-vision.md`](ux/experience-vision.md)
- Shared UX principles: [`docs/ux/principles.md`](ux/principles.md)

## Execution Order

### Phase 1 — Recall result actions and responsive review-shell polish

Goal: finish turning the shipped operator shell, trust surfaces, shared action-card model, and redesigned review shell into a crisp decide-and-execute loop where recall results can launch work directly and review stays equally trustworthy on denser layouts.

1. **Recall in-thread action-card execution**
   - Extend the shared action-card model from recall support decks into grounded chat and document-answer results so evidence-backed recommendations can launch or stage the next action directly.
   - Reuse the same trust, preview, handoff, and rollback framing instead of leaving recall outputs prose-only.
2. **Responsive review-shell density + small-screen ergonomics**
   - Resolve the remaining queue-rail versus side-by-side-detail balance on smaller screens without losing why-this-is-here, decision-required, or impact visibility.
   - Keep relationship, enrichment, and hygiene review calm and fast on laptop splits, narrow windows, and mobile widths.

## Immediate Next Sessions

If work is being planned session-by-session, the best near-term sequence is:

1. **Recall in-thread action-card execution session**
   - extend chat and document-answer results from support/context cards into executable in-thread action cards with shared trust + handoff framing
2. **Responsive review-shell density session**
   - finish smaller-screen review ergonomics so queue health, decisions, and impact previews remain clear without wasting space or hiding context

## Delivery Model

- Keep `docs/roadmap.md` concise and ordered.
- Use linked UX specs for detailed workflows, interaction models, and contract implications.
- Remove completed roadmap items instead of marking them done.
- Update the relevant spec when implementation materially changes intended behavior.
- Land UX changes as end-to-end workflow slices once a spec is accepted, not as isolated visual polish.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; all operator-shell and work-surface runtime work belongs in the TypeScript/Vite frontend.
- Keep all AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration remains the source of truth.
- Treat `make ci` as the release gate for every milestone.
