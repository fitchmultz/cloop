# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to stop conflating vanished preselected notifications with real zero-recipient sends, then ship one canonical continuity delivery-diagnostics contract before tuning push-scan policy.

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

### Next — Preselected notification disappearance outcome

Goal: stop conflating a vanished preselected notification with a real zero-recipient send.

Planned sequence:

1. record an explicit terminal scheduler-push outcome when a claimed `notification_id` no longer resolves at send time
2. keep slot-level at-most-once behavior and current selection flow unchanged
3. thread the outcome through scheduler persistence and the future diagnostics read model

### Then — Canonical joined delivery diagnostics

Goal: read current continuity decisions and prior scheduler push attempts from one shared contract.

Planned sequence:

1. build one store read path that joins ranked notification decisions to `scheduler_push_deliveries` through persisted canonical provenance
2. expose slot identity, claim/send timestamps, terminal delivery status, push counts, and resend-readiness context alongside current reason codes
3. distinguish reserved-only crashes, vanished-preselection rows, zero-recipient sends, acknowledgement, suppression expiry, cooldown, dedupe, missing-target, and skipped-delivery transitions

### Then — Delivery diagnostics scan metadata

Goal: make bounded diagnostics self-describing and resumable without changing selection behavior.

Planned sequence:

1. add explicit metadata for effective scan limit, inspected count, returned count, truncation state, and stable continuation cue
2. attach the metadata to the joined diagnostics contract instead of growing a temporary pre-join shape
3. cover empty scans and truncated mixes of sendable and non-sendable decisions

### Later — Cross-surface delivery diagnostics access

Goal: expose the canonical delivery diagnostics contract outside the HTTP debug endpoint.

Planned sequence:

1. add CLI and MCP entrypoints backed by the shared store read path
2. keep HTTP, CLI, and MCP output aligned on one schema contract
3. add only minimal surface-specific formatting after the shared contract is stable

### Later — Delivery scan policy calibration

Goal: tune or replace the fixed push scan policy only after joined diagnostics show where the current bounded scan hides sendable work or over-scans cold records.

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
