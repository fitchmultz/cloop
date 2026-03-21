# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn proactive operator guidance into explicit recovery flows whenever a previously saved path was superseded, degraded, or deleted, so resume can stay calm even when the original workflow is no longer the right place to land.

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
- grouped workflow-thread continuity across operator home, the receipt rail, and command-palette recents
- drift-aware since-last summaries and resume ranking driven by durable evidence instead of recency-first local history
- proactive operator guidance with one featured deterministic next move, a calm why-this-won digest, and a Recommended command-palette group
- bounded read-only alternate generation strategies with surfaced provenance metadata
- shared rerun and refresh affordances across planning, saved review sessions, recall result cards, continuity, CLI, HTTP, and MCP

## Execution order

### Next — Explicit recovery flows for superseded or unavailable workflows

**Primary specs:**
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)

Goal: turn replaced, gone, or degraded continuity paths into explicit recovery UX with clear replacement targets, safe fallbacks, and minimal dead-end navigation across operator home, review, planning, and recall handoffs.

Why this comes next:
- proactive next-move guidance now exists in the operator workspace and command palette, so the next churn-reducing step is to make stale destinations recoverable everywhere they appear
- replaced/gone reasoning is now computed from durable anchors and last-seen evidence, but degraded destinations still surface mostly as labels instead of full recovery flows
- recovery UX should land before deeper recommendation expansion so every surfaced recommendation remains trustworthy when the original target disappears

Planned sequence:

1. add explicit replacement and gone-state recovery actions anywhere a saved continuity target is opened or resumed
2. prefer jump-to-replacement affordances over home fallbacks when a deterministic successor exists
3. preserve the same recovery explanation across operator cards, the command palette, receipt rail, and downstream work surfaces
4. expose recovery provenance and rollback cues so operators can see why the original path changed before they jump

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
