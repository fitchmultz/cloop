# Cloop Roadmap

Execution focus: prove clarification-answer undo safety in the backend before widening shared review undo contracts.

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

### Next — Prove clarification-answer undo safety in the backend

1. Define the exact persisted state that clarification-answer undo must restore: answered clarification rows, superseded suggestions, rerun outputs, saved-session cursor state, and continuity outcomes.
2. Prototype exact-handle stale-state validation against that state before changing any shared transport or frontend contract.
3. Stop at an explicit irreversible contract if full restoration cannot be guaranteed.

### Then — Ship clarification-answer undo end to end only if proof holds

1. Add one backend-owned undo handle and restore path for clarification answers after the exact-handle proof succeeds.
2. Reuse the shared review follow-through, continuity, frontend undo, CLI, and MCP adapters instead of inventing clarification-specific transport logic.
3. Keep rerun state, continuity hydration, and stale-handle disablement aligned with the new undo path.

### Later — Make irreversible review outcomes explicit and finish schema/runtime parity cleanup

1. Codify no-undo behavior for review outcomes that still cannot prove exact restoration.
2. Keep receipts and trust surfaces explicit about rerun-without-undo cases.
3. Audit other route-built runtime payloads for schema drift before frontend contract regeneration.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
