# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to finish the delivery-status reason model now that notification-state lifecycle hygiene is in place.

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
- drift-aware since-last summaries and resume ranking driven by durable evidence instead of recency-first local history
- proactive operator guidance with one featured deterministic next move, a calm why-this-won digest, and a Recommended command-palette group
- explicit continuity recovery flows for superseded or unavailable workflows across operator cards, the receipt rail, and command-palette recommendations
- bounded read-only alternate generation strategies with surfaced provenance metadata
- shared rerun and refresh affordances across planning, saved review sessions, recall result cards, continuity, CLI, HTTP, and MCP

## Execution order

### Next — Delivery-status reason model

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)

Goal: define one backend-owned reason vocabulary for continuity notification delivery outcomes so cooldown, suppression, acknowledgement, send, and dedupe behavior can be inspected consistently.

Why this comes next:
- lifecycle cleanup should settle first so reason codes describe surviving state only
- explainability and tests will churn less if they build on one canonical status model

Planned sequence:

1. define canonical reason codes for sent, skipped, cooled-down, suppressed, acknowledged, missing-target, and deduped outcomes
2. attach the reason model to the scheduler/continuity delivery boundary without changing notification ranking
3. reuse the same reason vocabulary in tests before adding any inspection surface

### Later — Scheduler delivery history and explainability

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)

Goal: expose inspectable delivery history for continuity notifications by reusing scheduler delivery records, durable notification state, and the canonical delivery-status reason model.

Why this comes later:
- lifecycle cleanup and reason modeling should settle first so diagnostics describe stable behavior
- the write-side scheduler delivery record already exists, so the remaining work is a focused read/inspection contract

Planned sequence:

1. add a read path that joins scheduler delivery records with continuity notification state and delivery-status reasons
2. keep diagnostics debug-first and separate from notification ranking or operator recommendation logic
3. add focused inspection coverage for resend, suppression, acknowledgement, dedupe, and skipped-delivery cases

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
