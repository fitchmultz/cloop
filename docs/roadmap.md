# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to relax brittle AI-runtime constraints so stochastic planning, chat, and enrichment flows can succeed through more than one valid model/tool path before more UX-level workflow affordances land.

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
- canonical ranked landed-outcome follow-through feed across operator home, the receipt rail, and command-palette recents

## Execution order

### Next — Relax brittle AI-runtime constraints

**Primary specs:**
- [`docs/ai_runtime.md`](ai_runtime.md)
- [`README.md`](../README.md)
- [`docs/verification_checklist.md`](verification_checklist.md)

Goal: keep strict contracts at deterministic edges while widening the stochastic middle so chat, planning, enrichment, and MCP/operator flows do not fail just because one preferred model/tool path is unavailable.

Why this comes first:
- runtime brittleness currently creates avoidable failures before the user even reaches the higher-level rerun/refresh UX
- the current single-path assumptions leak into HTTP, CLI, MCP, docs, tests, and the frontend contract, so fixing them first reduces follow-on churn
- later handoff UX work should build on more flexible execution contracts instead of immediately depending on contracts we already know are too narrow

#### Slice 1 — Preserve multi-tool outcomes instead of collapsing them

Objective: stop forcing stochastic multi-step tool behavior through one preferred intermediate artifact.

Planned work:
1. evolve the shared chat/runtime contract from singular `tool_result` to plural tool-result handling
2. preserve ordered `tool_calls` and `tool_results` across HTTP, CLI, MCP, frontend state, and interaction logs
3. keep a compatibility summary field only as a migration bridge where existing surfaces still expect one primary result
4. ensure receipts and debug views can show multiple valid tool outcomes without losing provenance
5. update transport docs and examples to describe outcome-oriented handling rather than one canonical tool artifact

Acceptance bar:
- multi-tool runs no longer lose information in public response payloads
- frontend/operator surfaces can render more than one tool outcome cleanly
- logging preserves the actual tool sequence that occurred
- compatibility shims are transitional and clearly scoped

#### Slice 2 — Add bounded alternate strategies for read-only generation paths

Objective: avoid repeating one failing path when the request has not produced side effects and another valid strategy could succeed.

Planned work:
1. define safe alternate-strategy rules for read-only flows only:
   - grounded chat without mutations
   - planning generation
   - enrichment suggestion generation
   - RAG answer generation
2. use retryability signals and capability detection to choose between:
   - retry same selector once
   - fallback selector
   - no-tool / lower-budget retry where appropriate
3. keep mutation-started flows single-path after side effects begin
4. record which strategy succeeded so operators can audit why a request completed
5. keep failure contracts explicit when all bounded strategies are exhausted

Acceptance bar:
- retryable upstream failures can use one bounded alternate strategy when no side effects occurred
- mutation-producing flows do not silently branch after work begins
- logs and responses preserve provenance for fallback/retry decisions
- operators still get deterministic final failure states when all allowed strategies fail

#### Slice 3 — De-brittle prompts, tests, and operator guidance around stochastic behavior

Objective: stop baking exact wording and exact preferred process into the surrounding harness when task-level invariants are what actually matter.

Planned work:
1. remove tests that require exact prompt prose where semantic intent is enough
2. prefer assertions about:
   - structured contract validity
   - grounding actually being applied
   - correct invariants at deterministic boundaries
   - task completion / safety outcomes
3. trim docs that imply one mandatory reasoning path or one mandatory tool path unless that constraint is truly required
4. update examples so they present preferred paths as defaults, not the only valid path
5. keep strict JSON/schema/output requirements only where deterministic downstream code depends on them

Acceptance bar:
- prompt iteration does not break tests unless behavior or contracts change
- docs distinguish preferred path from required invariant
- structured boundaries remain strict while stochastic internals become less scripted

### After that — Shared rerun and refresh affordances

**Primary specs:**
- [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- [`docs/ux/workflow-handoffs.md`](ux/workflow-handoffs.md)
- [`docs/ux/ai-action-cards.md`](ux/ai-action-cards.md)

Goal: make landed outcomes as repeatable as they are resumable by standardizing rerun, refresh, and regenerate affordances for planning, review, and recall flows.

Why it follows the runtime slice:
- rerun/refresh UX should sit on top of flexible execution contracts, not re-encode today’s brittle runtime assumptions
- shared action cards need better provenance from selector resolution, alternate strategies, and richer multi-tool outcomes
- refresh affordances are easier to standardize once runtime fallback and result-shaping behavior are stable across transports

Planned sequence:

1. inventory where landed outcomes already imply a rerun or refresh path but still describe it with bespoke copy or one-off buttons
2. define one shared action-card contract for rerun and refresh semantics, including provenance, freshness, strategy summary, and post-run landing behavior
3. reuse that contract across planning refresh, review-session regeneration, and recall follow-through so the unified outcome feed stays actionable without per-surface forks
4. ensure rerun/refresh affordances describe what remains strict versus what may vary across AI attempts

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
