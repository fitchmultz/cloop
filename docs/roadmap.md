# Cloop Roadmap

Execution focus: eliminate remaining client-side follow-through reconstruction first, then close the highest-value transport parity gaps.

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

### Next — Backend-author shared review follow-through payloads

1. Emit one shared follow-through payload for relationship and enrichment mutations instead of forcing web/MCP/CLI clients to reconstruct receipts from `result` + `snapshot`.
2. Reuse the existing planning vocabulary where it fits: explicit summary, next surface, `rerun_action`, and `undo_action` when the backend has a safe inverse.
3. Keep irreversibility explicit when no exact-handle undo exists.

### Then — Add safe relationship undo handles

1. Expose exact reversible handles for relationship decisions when the backend can identify the landed loop event safely.
2. Reuse the continuity undo contract instead of inferring reversibility from stale review snapshots.
3. Keep duplicate/merge paths explicit when they remain irreversible.

### Later — Close working-set CLI parity gaps

1. Expose durable working-set list/get/context/mutation flows to the CLI with the same launch and exact-handle semantics already used by HTTP, web, and MCP.
2. Reuse `loops/working_sets.py` plus the shared CLI runtime helpers instead of forking transport-local logic.
3. Keep `#working-set/:id` and the returned `launch` payload as the shared resume contract across surfaces.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
