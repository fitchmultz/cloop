# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to roll backend-authored rerun contracts across workflow surfaces without regressing the landed-outcome continuity model.

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

### Next — Workflow rerun contract rollout

Goal: make planning, saved review, and recall reruns share one backend-authored contract instead of frontend-only handle builders.

Planned sequence:

1. define one transport-safe rerun handle + attempt contract for planning, review, and recall refresh flows
2. expose that contract from shared orchestration payloads and continuity follow-through surfaces
3. keep stale-target handling and post-rerun landing semantics consistent across operator, HTTP, CLI, and MCP

### Later — Outcome payload slimming

Goal: shrink durable continuity payloads after typed follow-through contracts land so storage and hydration stop depending on full UI-card action blobs.

Planned sequence:

1. keep only backend-owned trust, handoff, and action fields needed for continuity rendering
2. remove redundant action data from persisted `outcome_card` payloads where typed fields already exist
3. delete transitional card-action parsing once all first-party readers use the typed contract

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
