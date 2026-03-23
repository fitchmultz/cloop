# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to add a delivery-decision inspection read path so each continuity notification exposes its current backend decision and reason.

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

## Shipped foundation

The next roadmap slice starts from work that is already live:

- TypeScript/Vite operator-shell cutover with state-driven shell routing
- operator workspace foundation and state-oriented navigation model
- working-set sessions, focus mode, and working-set-aware handoffs
- shared trust surfaces and shared AI/action-card rendering across planning, review, recall, and follow-through flows
- post-action receipt cards with resume targets and rollback cues
- review workspace redesign across relationship, enrichment, and hygiene review
- durable backend-backed continuity outcomes and resume anchors with browser-local visit baselines still preserved for local drift comparison
- durable last-seen continuity markers for planning sessions, review sessions, workflow threads, and review cohorts
- backend-authored workflow-summary continuity across operator home, the receipt rail, command-palette recents, and calm notification/push delivery
- durable notification delivery state for canonical continuity records across push sends, in-app banners, and continuity hydration
- deterministic notification-state compaction for expired suppressions, retired workflow ids, and orphaned workflow ids
- drift-aware since-last summaries and resume ranking driven by durable evidence instead of recency-first local history
- proactive operator guidance with one featured deterministic next move, a calm why-this-won digest, and a Recommended command-palette group
- explicit continuity recovery flows for superseded or unavailable workflows across operator cards, the receipt rail, and command-palette recommendations
- bounded read-only alternate generation strategies with surfaced provenance metadata
- shared rerun and refresh affordances across planning, saved review sessions, recall result cards, continuity, CLI, HTTP, and MCP

## Execution order

### Next — Delivery-decision inspection read path

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)

Goal: expose the current backend delivery decision for each continuity notification without coupling it to scheduler history yet.

Planned sequence:

1. add a debug-first read path that returns notification state plus canonical decision reason
2. keep the inspection contract separate from operator ranking and rendering
3. cover sent, cooled_down, suppressed, acknowledged, missing_target, deduped, and skipped outcomes

### Then — Delivery history and explainability

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)

Goal: join current continuity delivery decisions with scheduler delivery records for resend and send-history inspection.

Planned sequence:

1. add a read path that joins scheduler delivery records with the current decision snapshot
2. keep diagnostics debug-first and separate from notification ranking or operator recommendation logic
3. add focused inspection coverage for resend windows, suppression expiry, acknowledgement, dedupe, missing-target, and skipped-delivery transitions

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
