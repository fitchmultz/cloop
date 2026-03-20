# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn the shipped operator-shell foundation into a world-class cross-session decision and execution workspace: outcome-anchored continuity that reflects what actually landed, then executable undo actions everywhere the backend already supports reversal.

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
- browser-local continuity baseline snapshots, resume anchors, and recent shell-action history
- global command palette with deterministic ranking, recent commands, and quick actions

## Execution order

### Session 1 — Outcome-anchored continuity history

**Primary spec:** [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)

Goal: make operator since-last summaries, recent-action history, working-set anchors, and workflow handoffs prefer the landed outcome instead of the launch point.

Planned sequence:

1. lock the landed-outcome continuity contract and precedence rules
2. align operator summaries, recent history, and resume anchors around that contract
3. finish cross-surface continuity behavior across planning, review, recall, working-set, and command-palette flows

Supporting specs:

- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)
- [`docs/ux/working-sets.md`](ux/working-sets.md)
- [`docs/ux/command-palette.md`](ux/command-palette.md)
- [`docs/ux/operator-workspace.md`](ux/operator-workspace.md)

### Session 2 — Executable undo actions

**Primary spec:** [`docs/ux/undo-actions.md`](ux/undo-actions.md)

Goal: promote existing backend undo and rollback support into first-class executable receipt/history actions wherever reversal is already supported.

Planned sequence:

1. lock the safe undo handle and transport contract
2. wire shared receipt/history/card actions to that contract
3. extend executable undo coverage across planning, review, enrichment, working-set, and command-palette follow-through

Supporting specs:

- [`docs/ux/trust-surfaces.md`](ux/trust-surfaces.md)
- [`docs/ux/ai-action-cards.md`](ux/ai-action-cards.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)
- [`docs/ux/review-redesign.md`](ux/review-redesign.md)
- [`docs/ux/state-navigation.md`](ux/state-navigation.md)

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
