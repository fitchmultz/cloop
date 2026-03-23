# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to make continuity delivery diagnostics explicit, historically accurate, and joinable before tuning push-scan policy.

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

### Next — Delivery inspection scan metadata

Goal: make bounded delivery inspection say exactly what it scanned, what it omitted, and how to continue.

Planned sequence:

1. add explicit scan metadata for the effective scan limit, inspected decision count, truncation state, and stable continuation cue
2. preserve current push selection and snapshot hydration behavior while exposing the bounded-read contract directly
3. thread the metadata through shared schemas/OpenAPI and cover cooled_down, deduped, missing-target, skipped, and empty-scan cases

### Then — Joined continuity delivery diagnostics

Goal: inspect current continuity delivery decisions and prior scheduler push attempts in one canonical contract.

Planned sequence:

1. join delivery-inspection decisions to scheduler push rows through persisted canonical notification provenance
2. expose claim/send timestamps, terminal delivery status, slot identity, push counts, and resend-readiness context alongside current reason codes
3. distinguish reserved-only crash rows, zero-recipient sends, acknowledgement, suppression expiry, cooldown, dedupe, missing-target, and skipped-delivery transitions

### Later — Cross-surface delivery diagnostics access

Goal: make the canonical delivery diagnostics usable outside the HTTP debug endpoint.

Planned sequence:

1. expose the shared delivery-diagnostics read contract through CLI and MCP entrypoints
2. keep HTTP, CLI, and MCP output backed by the same store and schema contract
3. add only minimal surface-specific formatting after the shared contract is stable

### Later — Delivery scan policy calibration

Goal: tune or replace the fixed push scan policy only after inspection metadata and joined history show where it hides sendable work or over-scans cold records.

Planned sequence:

1. compare truncation and later-sendable records against actual scheduler attempt history
2. decide whether to raise, parameterize, or replace the fixed floor and multiplier with a clearer contract
3. keep the cutover inside the shared delivery store contract and preserve explainable diagnostics

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
