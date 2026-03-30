# Cloop Roadmap

Execution focus: ship the review undo parity matrix and land a consistent reversibility reference across all surfaces.

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

## Execution order

### Slice 1 — Review undo parity matrix

Review undo is nearly at parity. Relationship decisions, enrichment apply, working-set mutations, planning rollback, and loop-event undo all have real backend undo with exact-handle freshness guards. Enrichment reject is trivially irreversible (sets one column, no side effects). This slice closes the remaining labeling gaps and lands a shared reference matrix.

1. Verify enrichment reject follow-through already uses correct `undo_action: None` + explicit `rollback_label`. If the label is vague, tighten it to say "Reject is irreversible."
2. Verify stale undo handles across relationship, enrichment, and working-set surfaces return specific reasons (not generic failures). Close any gaps.
3. Write one shared review follow-through matrix documenting the reversibility tier (reversible / irreversible / best-effort) for every review outcome, covering HTTP, web, CLI, and MCP. Land it in `docs/ux/undo-actions.md` as a reference table.

Outcome: every review receipt is honest about reversibility; one reference matrix documents the current state.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
