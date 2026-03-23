# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to push diagnostics windowing into storage and harden continuation semantics before tuning scan policy or exposing delivery diagnostics on more surfaces.

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

## Execution order

### Next — Storage-level diagnostics windowing

Goal: stop loading the full high-signal continuity set before slicing one diagnostics page.

Planned sequence:

1. push the diagnostics outcome window and continuation lookup down to the storage query layer
2. keep anchor resolution and snapshot hydration behavior unchanged
3. preserve the existing diagnostics contract while reducing per-page scan work

### Then — Stable diagnostics continuation semantics

Goal: make multi-page diagnostics reads predictable while new outcomes continue to arrive.

Planned sequence:

1. replace the current outcome-id continuation cue if needed with a cursor that survives concurrent inserts
2. keep duplicate and skipped-decision behavior stable across page boundaries
3. preserve the existing diagnostics fields or replace them in one cutover before CLI and MCP reuse them

### Then — Scan policy calibration

Goal: tune or replace the fixed push scan policy after bounded reads and stable continuation semantics are in place.

Planned sequence:

1. compare truncation and later-sendable records against actual scheduler attempt history
2. decide whether to raise, parameterize, or replace the fixed floor and multiplier
3. keep the cutover inside the shared delivery contract with explainable diagnostics

### Later — CLI and MCP diagnostics rollout

Goal: reuse the stable diagnostics contract outside HTTP.

Planned sequence:

1. add CLI and MCP entrypoints backed by the same read path
2. keep HTTP, CLI, and MCP fields aligned on one contract
3. keep surface-specific formatting minimal and downstream of the shared data model

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
