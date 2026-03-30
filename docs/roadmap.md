# Cloop Roadmap

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do next, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, handoff, and rerun.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, reversibility, and rerun semantics anywhere the system proposes or re-executes meaningful work.

## UX Vision and Spec Set

- Experience vision: [`docs/ux/experience-vision.md`](ux/experience-vision.md)
- Shared UX principles: [`docs/ux/principles.md`](ux/principles.md)
- Working sets: [`docs/ux/working-sets.md`](ux/working-sets.md)
- Continuity intelligence: [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- Outcome-first continuity: [`docs/ux/outcome-continuity.md`](ux/outcome-continuity.md)
- Undo actions: [`docs/ux/undo-actions.md`](ux/undo-actions.md)

## Delivery model

- Keep this file short; link UX specs for acceptance detail.
- Remove finished work instead of marking it done.
- Update the relevant UX spec when behavior changes materially.
- Ship end-to-end slices (contract + storage + transport + UI), not isolated polish.

## Done

### Backend clarification-answer undo (HTTP, CLI, MCP)

- HTTP: `POST /loops/{loop_id}/clarifications/undo`
- MCP: `clarification.undo`
- CLI: `cloop clarification undo`
- Stale-state guard, duplicate-ID validation, partial-undo semantics, rowcount integrity checks
- Tests for all transports and service-layer edge cases

## Remaining work

### Slice 1 — Frontend clarification-answer undo contract and dispatcher

Add `ClarificationAnswerUndoHandle` to the shared frontend types and executable undo helpers so the browser can represent and execute answer-only clarification undo from receipts and recent history.

**Why this slice first:** the backend contract is already done. The frontend still cannot represent clarification undo as a typed action, so nothing else can render or execute it safely until the handle exists.

**Changes:**

1. `frontend/src/contracts-ui.ts` — add `ClarificationAnswerUndoHandle`:
   ```
   { kind: "clarification_answer"; loopId: number; clarificationIds: number[] }
   ```
   Extend `ExecutableUndoHandle` to include it.

2. `frontend/src/executable-undo.ts` — add a shared builder and dispatcher support:
   - `buildClarificationUndoAction(loopId, clarificationIds)` → `OperatorActionCardUndoAction | null`
   - `clarification_answer` branch in `executeUndoAction` that POSTs to `/loops/{loopId}/clarifications/undo`
   - post-undo receipt shaping for restored clarifications and reopened suggestions

3. `frontend/src/executable-undo.test.ts` — regression tests for the new handle, builder, dispatcher, and stale-state 422 handling.

**Acceptance:**
- `pnpm --dir frontend typecheck` passes
- `vitest run` passes for the new builder and dispatcher
- Existing undo flows remain unaffected

### Slice 2 — Browser direct-answer clarification receipt emission

Add the browser-facing answer-only clarification entrypoint on the loop suggestion surface and emit a landed receipt outcome that carries the clarification undo action, so recent history and the command palette can surface it automatically.

**Changes:**

1. Use the existing direct clarification submit helper from `frontend/src/surfaces/api.ts` in the browser surface that owns answer-only clarification entrypoints (the loop suggestion flow, likely `frontend/src/surfaces/suggestions.ts`).
2. Shape a receipt/outcome from `ClarificationSubmitResponse` and attach the `clarification_answer` undo action to the recorded recent shell action.
3. Keep the review-session answer+rerun path in the review workspace unchanged and irreversible.

**Acceptance:**
- A direct answer-only clarification action lands a receipt with Undo available
- The recent-action feed picks up the answer-only clarification outcome automatically
- The command palette shows a recent clarification undo command without a separate palette-only code path

### Slice 3 — Review undo parity matrix

Document the reversibility tier, handle kind, transport availability, and stale-state behavior for every review outcome in one reference table in `docs/ux/undo-actions.md`.

**Changes:**

1. Verify enrichment reject uses `undo_action: None` with the generic irreversible rollback label (already done).
2. Verify stale undo handles across relationship, enrichment, and working-set surfaces return specific reasons (already done in code; verify in docs).
3. Write one reversibility matrix table in `docs/ux/undo-actions.md` covering all seven review-outcome categories:

| Outcome | Tier | Handle kind | Transports |
|--------|------|-------------|-----------|
| Relationship confirm/dismiss | Reversible | `relationship_decision` | HTTP, web, CLI, MCP |
| Enrichment apply | Reversible | `loop_event` | HTTP, web, CLI, MCP |
| Enrichment reject | Irreversible | — | HTTP, web, CLI, MCP |
| Clarification answer-only | Reversible (stale guard) | `clarification_answer` | HTTP, CLI, MCP |
| Clarification answer+rerun | Irreversible | — | HTTP, web, CLI, MCP |
| Working-set mutation | Reversible | `working_set_event` | HTTP, web, CLI, MCP |
| Planning checkpoint | Reversible | `planning_run` | HTTP, web, CLI, MCP |

Each cell documents: whether undo is available from receipt cards, recent history, and command palette; what happens on stale state.

**Acceptance:**
- Matrix is complete for all seven categories
- Every cell specifies tier, handle kind, transport availability, and stale-state behavior
- `make ci` passes

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
