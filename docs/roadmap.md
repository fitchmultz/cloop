# Cloop Roadmap

Execution focus: finish the remaining landed-outcome emitters before shell/runtime cleanup.

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do now, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, handoff, and rerun.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, reversibility, and rerun semantics anywhere the system proposes or re-executes meaningful work.

## UX Vision and Spec Set

- Experience vision: [`docs/ux/experience-vision.md`](ux/experience-vision.md)
- Shared UX principles: [`docs/ux/principles.md`](ux/principles.md)
- Continuity intelligence: [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- Undo actions: [`docs/ux/undo-actions.md`](ux/undo-actions.md)

## Execution order

### Next — Finish remaining landed-outcome emitters

Fill the real continuity gaps now that low-signal writes are gone.

1. Add outcome writes for recall-side follow-through and any remaining mutation paths that still only launch or pin state.
2. Ensure every continuity-worthy emitter supplies a durable resume target plus working-set context when present.
3. Add an explicit saved-anchor path only if planning/review still need durable resume without a landed outcome.

### Then — Frontend shell/runtime boundary cleanup

Clean up runtime boundaries only after continuity contracts stop moving.

1. Remove ineffective dynamic imports and dead split points in the shell and surface runtime.
2. Lazy-load surface code from the activation boundary so the operator bundle drops below the current warning path.
3. Keep the shell bootstrap thin and avoid reintroducing secondary entrypoints.

## Delivery model

- Keep this file short; link UX specs for acceptance detail.
- Remove finished work instead of marking it done.
- Update the relevant UX spec when behavior changes materially.
- Ship end-to-end slices (contract + storage + transport + UI), not isolated polish.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
