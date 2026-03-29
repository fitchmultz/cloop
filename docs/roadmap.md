# Cloop Roadmap

Execution focus: finish the review follow-through rollout across durable continuity and shared undo adapters.

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

### Next — Persist review follow-through outcomes into durable continuity

1. Write relationship and enrichment `follow_through` payloads into the continuity store at mutation time so operator home, the receipt rail, and the command palette survive reloads without local-only receipt state.
2. Reuse backend-authored display, rerun, and undo fields directly when hydrating durable continuity outcomes.
3. Remove local-only review receipt fallback paths once durable writes land.

### Then — Unify frontend follow-through adapters and extend safe review undo

1. Collapse duplicated frontend API-to-card and API-to-undo mapping helpers around review `follow_through` and continuity display contracts.
2. Evaluate safe undo contracts for enrichment apply and clarification-answer flows only after the shared adapter path is in place.
3. Leave irreversible review outcomes explicit when no safe inverse exists.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
