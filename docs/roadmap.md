# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn the shipped operator shell, action cards, and workflow handoffs into a world-class decision and execution workspace: sharper review, stronger focus context, faster navigation, and deeper trust/continuity.

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

### Phase 1 — Trust and continuity

Goal: make the system feel credible, explainable, and alive over time now that the shell, review workspace, durable working sets, and command palette are in place.

1. **Trust surfaces at every meaningful recommendation or mutation**
   - Spec: [`docs/ux/trust-surfaces.md`](ux/trust-surfaces.md)
   - Depends on: shipped action cards, workflow handoffs, the redesigned review workspace, focus-mode working sets, and the command palette.

### Phase 2 — Cross-session intelligence

Goal: make the system feel alive and resumable over time instead of merely fast in-session.

2. **Continuity and intelligence across sessions**
   - Spec: [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
   - Depends on: operator workspace, durable working sets, trust surfaces, and the command palette's recent/resume model.

## Immediate Next Sessions

If work is being planned session-by-session, the best near-term sequence is:

1. **Trust-surface session**
   - layer richer provenance, drift indicators, reversibility language, and mutation confidence into the shipped action-card, command-palette, working-set, and review-workspace model
2. **Continuity-intelligence session**
   - deepen since-last-visit summaries, resume suggestions, and cross-session intelligence on top of the richer operator workspace, command-palette recents, and durable working-set foundation

That sequence minimizes churn by using the now-stable shell, review-workspace, working-set, and command-palette architecture as the base before layering deeper trust and continuity on top.

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
- Do not land major new operator shell work in the legacy plain-JS frontend once Phase 0 starts.
- Keep all AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration remains the source of truth.
- Treat `make ci` as the release gate for every milestone.
