# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to land one storage-backed diagnostics stabilization slice before exposing delivery diagnostics on more surfaces.

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

### Next — Storage-backed diagnostics stabilization

Goal: finish one durable diagnostics slice end to end by locking cursor semantics, moving page-window reads into storage, and calibrating scan bounds together.

Planned sequence:

1. replace the current outcome-id continuation cue with one stable cursor contract that preserves page boundaries across concurrent inserts
2. push diagnostics windowing and continuation lookup down to the storage query layer against that final cursor contract
3. tune or replace the fixed push scan floor and multiplier using real truncation and later-sendable evidence while keeping diagnostics explanations intact

### Later — CLI and MCP diagnostics rollout

Goal: reuse the stabilized diagnostics contract outside HTTP.

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
