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

### Phase 1 — Continuity signal refinement and workflow handoff polish

Goal: turn the first continuity slice into a sharper operator decision surface once the deterministic baseline is stable.

1. **Planning / review / working-set handoff tightening**
   - Deepen explicit launch surfaces between review queues, planning sessions, working-set sessions, and recall tools.
   - Prefer typed shared contracts over client-side re-derivation for any new handoff UI.

## Immediate Next Sessions

If work is being planned session-by-session, the best near-term sequence is:

1. **Workflow-handoff rendering completion session**
   - audit operator cards and downstream workspace surfaces so propagated working-set badges, breadcrumbs, and next-surface cues render anywhere `handoff.workingSet` is available

The command/resume prioritization slice is now complete, so the next session can focus entirely on finishing the explicit working-set handoff rendering pass across every downstream surface.

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
