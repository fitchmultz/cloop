# Cloop Roadmap

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do next, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, handoff, and rerun.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, reversibility, and rerun semantics anywhere the system proposes or re-executes meaningful work.

## UX Vision and Spec Set

- Experience vision: [`docs/ux/experience-vision.md`](ux/experience-vision.md)
- Shared UX principles: [`docs/ux/principles.md`](ux/principles.md)
- Working sets: [`docs/ux/working-sets.md`](ux/working-sets.md)
- Continuity intelligence: [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- Outcome-first continuity: [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- Undo actions: [`docs/ux/undo-actions.md`](ux/undo-actions.md)

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

## Next execution slices

1. **Command-palette explicit queue-target selection for saved review actions**
   - When a saved relationship or enrichment action needs more than the preserved current item, let the palette prompt for the exact candidate or suggestion target instead of forcing the operator to leave the keyboard and open the full review workspace.
   - Reuse the existing review session snapshots and saved action contracts so palette execution keeps the same cursor, confirmations, receipts, and working-set scope while adding explicit target choice only when needed.
   - Why: cross-session execution now works for the preserved current item, but the palette still has no graceful keyboard path when a queue has no current item or when the operator wants a different candidate or suggestion than the default top target.
   - Acceptance source: `docs/ux/command-palette.md`, `docs/ux/workflow-handoffs.md`.
