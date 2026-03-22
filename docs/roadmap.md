# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to add durable delivery controls on top of the canonical summary-derived notification and digest feed, so acknowledgement, suppression, inboxing, and scheduled delivery stay tied to the same backend-authored workflow-summary identities.

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
- drift-aware since-last summaries and resume ranking driven by durable evidence instead of recency-first local history
- proactive operator guidance with one featured deterministic next move, a calm why-this-won digest, and a Recommended command-palette group
- explicit continuity recovery flows for superseded or unavailable workflows across operator cards, the receipt rail, and command-palette recommendations
- bounded read-only alternate generation strategies with surfaced provenance metadata
- shared rerun and refresh affordances across planning, saved review sessions, recall result cards, continuity, CLI, HTTP, and MCP

## Execution order

### Next — Durable delivery controls for continuity notifications

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)

Goal: add durable acknowledgement, suppression, inboxing, and scheduled-delivery controls on top of the shipped summary-derived notification/digest feed so calm continuity delivery stays stable across refreshes, devices, and future automation surfaces.

Why this comes next:
- workflow-summary identities now drive operator digests, in-app notifications, and push delivery from one canonical ranking feed
- the remaining gap is delivery control, not notification copy or ranking logic
- future nudges and digest scheduling should now extend the shared identity model instead of inventing per-surface preference state

Planned sequence:

1. define durable suppression and inbox state keyed to workflow-summary identity
2. expose notification inbox and delivery-control reads/writes through continuity surfaces
3. extend scheduler delivery to respect those controls for push and digest timing
4. keep acknowledgement and last-seen semantics aligned with the same stable workflow-summary identities

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
