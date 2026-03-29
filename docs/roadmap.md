# Cloop Roadmap

Execution focus: settle clarification-answer reversibility with the smallest end-to-end slices, then bring the rest of review follow-through to parity.

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

### Slice 1 — Clarification-answer write-path inventory

1. Trace every row and payload written by clarification answers and the immediate rerun: clarification answers, superseded suggestions, replacement suggestions, session cursor changes, and continuity outcomes.
2. Capture the exact before/after state needed to restore one answer operation without guessing.
3. End with one explicit restore matrix that names what is reversible, what must be guarded, and what is already irreversible.

### Slice 2 — Clarification-answer restore viability probe

1. Prototype the minimum stale-state validation against the stored state from Slice 1.
2. Prove or disprove exact restore for one clarification-answer operation, including rerun side effects and saved-session cursor position.
3. End with one decision only: exact undo ships, or clarification answers are irreversible.

### Slice 3 — Clarification-answer contract hard cut

1. If exact undo is viable, add one backend-owned undo handle plus restore path and thread it through review follow-through, continuity, frontend undo, CLI, and MCP.
2. If exact undo is not viable, mark clarification-answer receipts and continuity outcomes explicitly irreversible and remove any implied undo affordances.
3. Regenerate contracts only after the chosen contract is consistent across backend and frontend surfaces.

### Slice 4 — Review outcome parity sweep

1. Audit the remaining review outcomes for mixed reversibility rules, stale-handle behavior, and advisory-only rollback copy.
2. Mark every non-restorable outcome explicitly irreversible and disable stale handles with specific reasons.
3. Land one shared review follow-through matrix across HTTP, web, CLI, and MCP.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
