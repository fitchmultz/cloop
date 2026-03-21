# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to carry landed outcomes and shared follow-through beyond one browser session so continuity remains trustworthy across time, device changes, and denser workflow activity.

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
- browser-local continuity baseline snapshots, outcome-anchored resume anchors, and landed-outcome recent shell-action history
- global command palette with deterministic ranking, quick actions, and outcome-first recents
- canonical ranked landed-outcome follow-through feed across operator home, the receipt rail, and command-palette recents
- bounded read-only alternate generation strategies with surfaced provenance metadata
- shared rerun and refresh affordances across planning, saved review sessions, recall result cards, continuity, CLI, HTTP, and MCP

## Execution order

### Next — Durable continuity and grouped workflow threads

**Primary specs:**
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)

Goal: move high-signal landed outcomes and resume anchors beyond browser-local storage while grouping multi-step workflow threads so continuity stays trustworthy even as reruns, receipts, and handoffs become more frequent.

Why this comes next:
- continuity is still browser-local, capped, and easy to lose after the new rerun/refresh affordances make landed outcomes more valuable
- multi-step planning, review, and recall flows now emit richer receipts, but operator history still reads as flat events instead of workflow threads
- durable continuity storage should land before any heavier personalization or proactive operator guidance so those later features build on trustworthy history

Planned sequence:

1. define a durable continuity storage contract for landed outcomes, resume anchors, degraded-target state, and grouped workflow threads
2. preserve the current landed-outcome precedence rules while adding backend-backed history and cross-device fallback behavior
3. group related receipts, reruns, and downstream handoffs into workflow threads so operator home and palette recents stay high-signal
4. keep stale or deleted targets explicit, with safe fallbacks that explain what changed instead of silently dropping continuity

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
