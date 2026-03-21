# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn durable continuity history into sharper resume guidance, drift recovery, and calmer operator summaries now that landed outcomes survive browser and device boundaries.

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
- durable backend-backed continuity outcomes and resume anchors with browser-local baseline snapshots still preserved for visit-to-visit drift comparison
- grouped workflow-thread continuity across operator home, the receipt rail, and command-palette recents
- canonical ranked landed-outcome follow-through feed with stale-target fallback and cross-device hydration
- bounded read-only alternate generation strategies with surfaced provenance metadata
- shared rerun and refresh affordances across planning, saved review sessions, recall result cards, continuity, CLI, HTTP, and MCP

## Execution order

### Next — Deterministic drift recovery and continuity intelligence

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)

Goal: turn durable continuity history into sharper since-last summaries, explicit drift warnings, and resume prioritization so the operator workspace answers what changed and what deserves action now without reading like a ledger.

Why this comes next:
- backend-backed continuity now preserves trustworthy landed outcomes, but the shell still ranks mostly by recency instead of explicit drift, aging, or replacement signals
- planning and saved review sessions already expose deterministic freshness and queue metadata that can power better stale-session recovery without adding speculative AI
- durable workflow threads should feed higher-signal summaries before any heavier personalization or proactive recommendation work lands

Planned sequence:

1. add durable last-seen markers and deterministic thread/session drift comparisons for planning, review, and working-set continuity
2. distinguish calm progress, stale drift, replaced workflows, and broken resume targets directly in since-last cards and palette recents
3. rank resume suggestions using drift severity, working-set relevance, and downstream queue readiness instead of recency alone
4. keep operator summaries concise by collapsing low-value receipts behind thread rollups while surfacing one obvious next move

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
