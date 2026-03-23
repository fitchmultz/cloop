# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to finish one canonical delivery-diagnostics contract end to end before tuning scan policy or cleanup tooling.

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

### Next — Canonical delivery diagnostics contract

Goal: return one shared backend contract for ranked continuity decisions and scheduler push attempts.

Planned sequence:

1. build one read path that joins ranked notification decisions to `scheduler_push_deliveries` through persisted provenance
2. emit slot identity, claim/send timestamps, terminal status, push counts, resend-readiness context, and current reason codes from that contract
3. distinguish reserved-only crashes, vanished preselection, zero-recipient sends, acknowledgement, suppression expiry, cooldown, dedupe, missing-target, and skipped-delivery transitions without per-surface logic

### Then — Diagnostics pagination metadata

Goal: make diagnostics responses bounded, explicit, and resumable.

Planned sequence:

1. add effective limit, inspected count, returned count, truncation flag, and stable continuation cue
2. keep the metadata on the shared diagnostics contract instead of adding a temporary response shape
3. cover empty scans and truncated mixes of sendable and non-sendable records

### Then — CLI and MCP diagnostics rollout

Goal: reuse the shared diagnostics contract outside HTTP.

Planned sequence:

1. add CLI and MCP entrypoints backed by the same read path
2. keep HTTP, CLI, and MCP fields aligned on one contract
3. keep surface-specific formatting minimal and downstream of the shared data model

### Later — Scheduler delivery provenance normalization

Goal: stop depending on ad hoc payload fields for terminal delivery nuances once the shared diagnostics contract proves which fields need to be durable.

Planned sequence:

1. identify which scheduler terminal reasons need first-class persisted fields instead of payload-only provenance
2. normalize the durable shape only after the shared diagnostics contract is stable
3. preserve diagnostics behavior across the storage cutover

### Later — Scan policy calibration

Goal: tune or replace the fixed push scan policy only after shared diagnostics show real misses or over-scan.

Planned sequence:

1. compare truncation and later-sendable records against actual scheduler attempt history
2. decide whether to raise, parameterize, or replace the fixed floor and multiplier
3. keep the cutover inside the shared delivery contract with explainable diagnostics

### Later — Runtime cleanup ambiguity attribution

Goal: reduce false-positive ambiguous runtime warnings without broadening automatic cleanup.

Planned sequence:

1. label why a detected process is ambiguous, such as cwd mismatch, command-only match, or missing cwd
2. surface enough attribution in runtime-clean verification output to distinguish repo-owned helpers from external tools
3. keep automatic termination conservative and limited to clearly repo-owned resources

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
