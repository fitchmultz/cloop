# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to finish recall rerun contracts, then complete continuity normalization and payload cleanup without re-cutting the same surfaces twice.

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

### Next — Recall rerun contract rollout

Goal: give recall follow-through one backend-owned rerun contract instead of shell-only reconstruction.

Planned sequence:

1. define a transport-safe rerun contract for recall queries and grounded-answer refreshes
2. persist and expose that contract through receipt outcomes and continuity summaries
3. reuse one execution/staleness path across cards, continuity, and command palette

### Then — Legacy continuity follow-through normalization

Goal: rewrite or normalize older persisted continuity outcomes so typed follow-through stays available after the final payload cleanup.

Planned sequence:

1. identify legacy outcomes that still depend on `outcome_card.actions` for undo or rerun
2. backfill typed follow-through fields from canonical workflow data where a safe contract still exists
3. leave irrecoverable legacy outcomes explicit instead of silently inventing actions

### Later — Outcome payload slimming

Goal: shrink durable continuity payloads after first-party readers stop depending on full UI-card action blobs.

Planned sequence:

1. keep only backend-owned trust, handoff, and display fields needed for continuity rendering
2. remove redundant action data from persisted `outcome_card` payloads once typed fields are complete
3. delete parser fallbacks and metadata shims kept only for the cutover

## Delivery model

- Keep `docs/roadmap.md` concise and ordered.
- Use linked UX specs for detailed workflows, interaction models, contract implications, and acceptance criteria.
- Remove completed roadmap items instead of marking them done.
- Update the relevant spec when implementation materially changes intended behavior.
- Land UX changes as end-to-end workflow slices once a spec is accepted, not as isolated visual polish.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; all operator-shell and work-surface runtime work belongs in the TypeScript/Vite frontend.
- Keep all AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration remains the source of truth.
- Treat `make ci` as the release gate for every milestone.
