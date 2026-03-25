# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to remove continuity fallback debt, then slim stored outcome payloads after typed follow-through is the only execution path.

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

### Next — Continuity follow-through hard cutover

Goal: delete continuity fallbacks that still infer undo or rerun from stored card-action blobs.

Planned sequence:

1. identify persisted outcomes that still rely on card-action fallbacks
2. backfill typed follow-through from canonical workflow data where a safe contract exists
3. cut continuity readers to typed follow-through fields only and make irrecoverable history explicit

### Later — Outcome payload slimming

Goal: shrink durable continuity payloads after typed follow-through is the only execution path.

Planned sequence:

1. keep only backend-owned trust, handoff, display, and typed follow-through fields needed for continuity rendering
2. remove redundant action blobs from persisted `outcome_card` payloads
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
