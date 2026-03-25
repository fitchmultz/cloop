# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to finish continuity presentation convergence, then slim durable continuity payloads.

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

### Next — Continuity presentation convergence

Goal: stop rewriting backend-authored continuity cards in frontend consumers.

1. cut notification, recommendation, and recovery consumers to one shared continuity card adapter
2. remove per-surface trust, handoff, and warning overrides that still patch `summary.card`
3. keep backend-authored ranking and display fields as the only rendering input for continuity summaries

### Then — Outcome payload slimming

Goal: remove transitional continuity payload duplication from storage and transport.

1. keep only backend-owned display, typed action, resume, and workflow-thread fields needed for rendering and execution
2. remove redundant `outcome_card` display copies and other duplicated presentation blobs from persisted outcomes
3. trim snapshot/OpenAPI/frontend hydration to the slimmer contract in one cutover

### Later — Continuity cache cleanup

Goal: delete browser-side compatibility glue left by the display cutover.

1. remove parser fallbacks and cache-version support kept only for pre-`display_card` shapes
2. delete `outcome.card`-is-canonical assumptions in frontend continuity helpers
3. drop unused representative/display-only wiring once payload slimming lands

## Delivery model

- Keep `docs/roadmap.md` concise and ordered.
- Use linked UX specs for workflow detail and acceptance criteria.
- Remove completed roadmap items instead of marking them done.
- Update the relevant spec when implementation materially changes intended behavior.
- Land UX changes as end-to-end workflow slices, not isolated visual polish.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; all operator-shell and work-surface runtime work belongs in the TypeScript/Vite frontend.
- Keep all AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration remains the source of truth.
- Treat `make ci` as the release gate for every milestone.
