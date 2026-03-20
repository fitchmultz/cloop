# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn the shipped operator-shell foundation into a world-class cross-session decision and execution workspace: unify landed outcomes into one ranked follow-through model now that executable undo covers loop, planning, and working-set continuity mutations.

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do now, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, and handoff.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, and reversibility anywhere the system proposes or executes meaningful work.

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
- browser-local continuity baseline snapshots, outcome-anchored resume anchors, and landed-outcome recent shell-action history
- global command palette with deterministic ranking, quick actions, and outcome-first recents

## Execution order

### Session 1 — Outcome-centric follow-through consolidation

**Primary specs:**
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- [`docs/ux/command-palette.md`](ux/command-palette.md)
- [`docs/ux/ai-action-cards.md`](ux/ai-action-cards.md)

Goal: collapse the remaining duplicated “latest receipt”, “since last”, and palette-recent follow-through patterns into one prioritized outcome feed with consistent resume, undo, and rerun affordances.

Planned sequence:

1. define one canonical ranking model for landed outcomes across operator home, receipt rail, and command-palette recents
2. remove duplicated render paths that restate the same landed result with different copy or action ordering
3. preserve the same outcome contract everywhere so new durable workflows only need to emit one receipt/handoff payload

### Session 2 — Shared rerun and refresh affordances

**Primary specs:**
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)
- [`docs/ux/ai-action-cards.md`](ux/ai-action-cards.md)

Goal: make landed outcomes as repeatable as they are resumable by standardizing rerun, refresh, and regenerate affordances for planning, review, and recall flows.

Planned sequence:

1. inventory where landed outcomes already imply a rerun or refresh path but still describe it with bespoke copy or one-off buttons
2. define one shared action-card contract for rerun and refresh semantics, including provenance and post-run landing behavior
3. reuse that contract across planning refresh, review-session regeneration, and recall follow-through so the unified outcome feed stays actionable without per-surface forks

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
