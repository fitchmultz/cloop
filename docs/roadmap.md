# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to cut operator surfaces over to the durable continuity notification state so inbox controls, seen state, acknowledgement, and suppression no longer depend on browser-only behavior.

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

### Next — Operator inbox and delivery-control UX

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)

Goal: cut operator surfaces over to durable notification state so the shell can show inboxed items, mark notifications seen, and apply suppression without local-only behavior.

Why this comes after durable state:
- the shell should read and write the final state model, not a temporary browser contract
- UI churn stays lower once the backend identity and mutation rules are fixed

Planned sequence:

1. add operator-home or command-surface reads for inboxed notifications and delivery controls
2. wire open, seen, acknowledge, and suppress actions to continuity-owned writes
3. remove remaining browser-only notification state and transport-specific dismissal behavior

### Then — Scheduler delivery selection and timing

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)

Goal: make scheduler delivery select only deliverable notifications and respect durable state, suppression, and timing windows without re-ranking workflows outside continuity.

Why this comes later:
- timing policy depends on stable delivery state and UI write paths first
- scheduling before state and surface semantics settle would create avoidable churn in storage, transport, and UX

Planned sequence:

1. add scheduler-facing reads that select deliverable notifications from durable continuity state
2. respect suppression, inbox, seen, acknowledgement, and timing windows during push or digest sends
3. keep scheduler delivery as a transport over continuity-owned notification records instead of task-specific reminder copy

### Later — Notification-state hygiene for retired workflow ids

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)

Goal: prune or compact notification-state rows whose canonical workflow ids no longer resolve so continuity state stays small and explainable.

Why this comes later:
- delivery behavior and operator controls matter first
- cleanup policy is easier once state writes and scheduler reads have settled

Planned sequence:

1. define when a notification-state row becomes retired or orphaned
2. add a deterministic prune or compact pass tied to continuity-owned identity rules
3. keep cleanup invisible to active notification delivery and operator inbox state

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
