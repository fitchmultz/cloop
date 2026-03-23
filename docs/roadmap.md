# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to bound delivery-diagnostics reads, then remove payload-only scheduler reason parsing, before exposing the contract on more surfaces.

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

### Next — Diagnostics scan metadata

Goal: make diagnostics reads bounded, explicit, and resumable.

Planned sequence:

1. add effective limit, inspected count, returned count, truncation flag, and stable continuation cue
2. keep the metadata on the shared diagnostics contract instead of introducing a side response shape
3. cover empty scans and truncated mixes of sendable and non-sendable records

### Then — Persist scheduler delivery reasons

Goal: move scheduler terminal delivery reasons out of `payload_json` before more consumers depend on them.

Planned sequence:

1. add first-class durable fields for the scheduler delivery reasons the diagnostics contract actually reads
2. keep the shared diagnostics contract stable while writers and readers cut over
3. delete the payload fallback after the durable fields become authoritative

### Then — Lock scheduler delivery reason vocabulary

Goal: stop exposing free-form scheduler reason strings once durable fields exist.

Planned sequence:

1. define the canonical scheduler terminal reason set used by push sending and diagnostics
2. validate and serialize that vocabulary consistently in storage and transport
3. keep pre-cutover rows readable until the storage migration is complete

### Then — Scan policy calibration

Goal: tune or replace the fixed push scan policy before the diagnostics contract spreads to more surfaces.

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
