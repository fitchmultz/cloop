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

1. **Recall working-set provenance + transport handoff parity**
   - Thread optional working-set context through chat and document-recall HTTP, CLI, and MCP requests so backend-authored recall follow-through and rerun contracts stop depending on browser-only working-set overlays.
   - Surface the landed recall `follow_through` summary, resume target, and rerun affordances directly in CLI and MCP-facing recall outputs so non-web transports stop lagging the web continuity contract.
   - Acceptance source: `docs/ux/outcome-continuity.md`, `docs/ux/command-palette.md`.

2. **Durable recall-outcome hydration verification**
   - Add cross-device-style verification for recall outcomes so operator home, the receipt rail, and command-palette Recent keep preferring synced durable recall receipts after hydration instead of relying on fresh local-only entries.
   - Acceptance source: `docs/ux/outcome-continuity.md`, `docs/ux/command-palette.md`.

3. **Recall mutation follow-through cutover**
   - Move direct memory and document-ingest recall mutations onto the same backend-authored landed `follow_through` contract already used by review outcomes and recall answers so transport behavior stops splitting between frontend-shaped and backend-shaped receipts.
   - Acceptance source: `docs/ux/outcome-continuity.md`, `docs/ux/ai-action-cards.md`.
