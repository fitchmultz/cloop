# Cloop Roadmap

Execution focus: lock the working-set launch-helper contract, then align docs and tests to it.

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
- Outcome-first continuity: [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- Undo actions: [`docs/ux/undo-actions.md`](ux/undo-actions.md)

## Execution order

### Next — Lock the working-set launch-helper contract

1. Decide whether `query_anchor` and `state_anchor` remain the canonical public `item_type` values.
2. If they change, rename schema, storage, frontend, docs, and tests in one cutover without compatibility shims.
3. If they stay, document them as working-set launch helpers only and stop treating them as deleted continuity leftovers.

### Then — Align working-set docs and HTTP fixtures to the locked contract

1. Update `docs/ux/working-sets.md` and working-set HTTP fixture/test descriptions to match the locked term.
2. Keep docs and fixture wording neutral even if public `item_type` values retain `*_anchor` names.
3. Remove wording that implies deleted continuity-anchor behavior.

### Then — Align pure frontend test terminology

1. Update frontend routing and ranking test descriptions to the locked term.
2. Preserve behavior assertions and avoid broad regression churn.
3. Keep the discarded-browser-cache reopen regression narrowly focused on ignored legacy cache behavior.

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
