# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to ship one canonical delivery-diagnostics read model, then bounded scan metadata, then cross-surface access.

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

### Next — Canonical delivery diagnostics read model

Goal: expose one joined read path for current continuity decisions and prior scheduler push attempts.

Planned sequence:

1. join ranked notification decisions to `scheduler_push_deliveries` through canonical persisted provenance
2. return slot identity, claim/send timestamps, terminal status, push counts, resend-readiness context, and current reason codes in one contract
3. cover reserved-only crashes, vanished preselection, zero-recipient sends, acknowledgement, suppression expiry, cooldown, dedupe, missing-target, and skipped-delivery transitions

### Then — Bounded diagnostics metadata

Goal: make diagnostics responses explain their own scan boundaries.

Planned sequence:

1. add effective limit, inspected count, returned count, truncation flag, and stable continuation cue
2. keep the metadata on the joined diagnostics contract instead of adding an intermediate shape
3. cover empty scans and truncated mixes of sendable and non-sendable records

### Later — CLI and MCP diagnostics surfaces

Goal: reuse the canonical diagnostics read model outside HTTP.

Planned sequence:

1. add CLI and MCP entrypoints backed by the shared store read path
2. keep HTTP, CLI, and MCP fields aligned on one schema contract
3. keep surface-specific formatting minimal and downstream of the shared contract

### Later — Scan policy calibration

Goal: tune or replace the fixed push scan policy only after joined diagnostics show real misses or over-scan.

Planned sequence:

1. compare truncation and later-sendable records against actual scheduler attempt history
2. decide whether to raise, parameterize, or replace the fixed floor and multiplier
3. keep the cutover inside the shared delivery store contract with explainable diagnostics

### Later — Runtime cleanup ownership hints

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
