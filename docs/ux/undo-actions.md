# Executable Undo and Rollback Actions

## Why

Cloop already exposes reversibility signals in its trust surfaces, but too much of that reversibility is still advisory text rather than an executable control.

The backend already supports undo in two important places:

- single-loop event undo in `src/cloop/loops/events.py::undo_last_event`, exposed over HTTP at `POST /loops/{loop_id}/undo` and via MCP `loop.undo`
- planning checkpoint rollback metadata and rollback execution helpers in `src/cloop/loops/_planning_workflows/execution_rollback.py`, surfaced through planning execution metadata in `src/cloop/loops/planning_workflows.py`

The frontend already renders receipt cards with `trust.rollbackLabel`, but that label is display-only. A user can be told something is reversible without being given an actual undo action. That weakens trust exactly where trust is supposed to be strongest: after consequential work lands.

## Outcome

Whenever Cloop already has real backend reversal support, the user gets a first-class executable undo or rollback action from the same receipt and history surfaces that describe the landed result.

Reversible outcomes should behave consistently across planning, review, enrichment, working-set, and command-palette flows:

- reversible work gets an executable `undo_action`
- rerunnable work gets an explicit `rerun_action`
- irreversible work is labeled clearly as irreversible
- stale or no-longer-safe undo paths are disabled with explicit reasons
- successful undo creates its own landed receipt and resume target

## User jobs

- Reverse an unintended action without leaving the current workflow context.
- Know whether an executed result is actually reversible or only described as reversible.
- Undo from the receipt card, recent history, operator workspace, or command palette.
- Understand where they will land after undo completes.

## Non-goals

- Providing global time travel or multi-step arbitrary history replay.
- Pretending every mutation is undoable.
- Hiding partial rollback risk behind a one-click UI.
- Replacing confirmation and trust metadata for consequential reversals.

## UX principles applied

- Trust at the point of action.
- Action over narration.
- One obvious next move.
- Workflow handoffs beat tab jumping.
- Human authority, AI acceleration.

## Contract

The executable undo model is a first-class shared workflow contract.

### Backend-safe handles

- loop undo is freshness-safe and exact-handle only:
  - `POST /loops/{loop_id}/undo`
  - body requires `expected_event_id`
  - stale handles are rejected explicitly instead of undoing “whatever is latest”
- loop undo responses return enough data to land a fresh receipt:
  - restored loop payload
  - `undone_event_id`
  - `undo_event_id`
  - `undone_event_type`
- loop mutation responses expose reversible-event metadata so the frontend can attach real undo handles:
  - `latest_reversible_event_id`
  - `latest_reversible_event_type`
- planning rollback is a public transport contract:
  - `POST /loops/planning/sessions/{session_id}/rollback`
  - body requires `run_id`
  - only the latest active run can be rolled back
  - fully rolled-back runs stay in history but are marked inactive for continuity and analytics
- planning execution payloads carry a shared executable `undo_action` contract plus advisory `rollback_cues` across HTTP, CLI, MCP, and web, so clients stop re-deriving rollback handles from raw cue counts or prose
- working-set undo is a public exact-handle contract:
  - `POST /loops/working-sets/undo`
  - body requires `expected_event_id`
  - stale handles are rejected explicitly instead of undoing a newer working-set change
  - reversible working-set responses expose `latest_reversible_event_id` and `latest_reversible_event_type`

### Shared frontend contract

- `frontend/src/contracts-ui.ts` includes a first-class `undo` action type on shared operator action cards
- `RecentShellActionOutcome` stores both trust copy and a structured executable `undoAction`
- `frontend/src/executable-undo.ts` centralizes:
  - loop-event undo handles
  - planning-run rollback handles
  - HTTP execution helpers
  - stale-action failure handling
  - post-undo receipt shaping

### Surfaces using executable undo

Executable undo appears anywhere the backend already exposes a safe inverse contract:

- planning execution receipts and operator handoff cards
- enrichment apply receipts
- working-set continuity receipts for create/update/delete/focus/pin/stage/defer/reorder/remove/bulk-add flows
- recent shell-action continuity entries
- operator “since last” outcome cards
- command-palette quick undo commands

Successful undo or rollback creates a new landed receipt with a clear resume target. Stale or drifted handles are disabled with explicit reasons instead of silently failing.

## Undo model

### Reversibility tiers

Cloop should distinguish three cases clearly.

#### 1. Direct executable undo

Use when the backend already supports a precise reverse operation for the landed result.

Examples:

- loop update, status, or close mutations handled through `undo_last_event`
- planning execution results with explicit `rollback_actions`

#### 2. Executable rollback with caveats

Use when rollback exists but may be partial, best-effort, or stale-sensitive.

Examples:

- planning execution rollback that may fail for some actions if downstream state has drifted
- multi-resource outcomes where some actions are reversible and others are not

The UI should still expose executable rollback, but with stronger trust language and confirmation.

#### 3. Advisory-only irreversibility

Use when no safe backend reversal exists yet.

In this case:

- show trust metadata clearly
- do not render a fake undo button
- keep copy explicit about why reversal is unavailable

### Safe-handle rule

Undo must never be inferred from label text alone.

An executable undo action must be backed by structured backend-aware data, not by guessing from `rollbackLabel`. The system should treat “rollback supported” as different from “safe to execute this exact undo now.”

That means the UI needs a real undo handle or validated target, not only a string.

## Surfaces in scope

Executable undo should appear in the same follow-through surfaces that already show receipt outcomes:

- receipt cards rendered from `OperatorActionCard`
- recent-action history entries built from `RecentShellActionEntry`
- operator workspace “Since last visit” items when a landed receipt is shown there
- review workspace post-action follow-through
- working-set follow-through receipts
- command-palette recent actions and quick undo commands

The interaction model should stay consistent across surfaces: the same outcome should not be undoable in one place, rerunnable in another, and text-only somewhere else.

## Surface-specific behavior

### Planning execution

Planning execution already exposes the richest rollback metadata. The UI should:

- render a first-class rollback action when `undoable` is true and `rollback_actions` exist
- explain when rollback is partial or best-effort
- return the user to a sensible post-rollback surface, typically the planning session or a restored downstream object context

### Review decisions and enrichment applies

Review and enrichment flows often land as loop updates, closes, or status transitions. When the landed result maps to a reversible loop event, the receipt should expose executable undo through the same loop-event undo path used elsewhere.

If a review action is not actually reversible, the receipt should remain explicit about that.

### Working-set mutations

Working-set mutations use the same executable undo model as loop and planning receipts.

Working-set undo coverage includes:

- create, update, and delete of named working sets
- active working-set / focus-mode context changes
- single-item pin, stage, defer, remove, and reorder mutations
- bulk loop-add expansion into the active working set

These receipts carry exact working-set event handles through the shared undo contract, so recent history, operator outcome cards, and command-palette quick undo all reuse the same safe backend path.

### Command-palette quick actions

The command palette should reuse the same executable undo handles already attached to receipt outcomes. It should not invent a separate undo path. Keyboard-first users should be able to undo recent reversible actions without leaving the palette flow.

## Key workflows

### Immediate post-action undo

1. User executes a reversible mutation.
2. The resulting receipt card includes an explicit Undo or Rollback action.
3. User invokes undo from the receipt.
4. Backend executes the matching reversal path.
5. UI renders a new landed receipt describing what was restored and where to continue.

### Undo from recent history

1. User opens recent actions or “Since last visit.”
2. A prior landed receipt still has a valid executable undo handle.
3. User triggers undo from that history entry.
4. If the handle is still valid, undo runs and emits a fresh receipt.
5. If the handle is stale or unsafe, the action is disabled and the reason is shown.

### Review and enrichment follow-through undo

1. User applies a review decision or enrichment suggestion.
2. The review workspace emits a receipt card describing the landed change.
3. If that change maps to a reversible backend event, the receipt includes Undo.
4. Undo restores the prior loop state and keeps the user in a sensible review or loop context.

### Palette quick undo

1. User opens the command palette.
2. Recent reversible outcomes are offered as quick undo commands.
3. User executes undo directly from the keyboard.
4. The palette closes into the post-undo resume target or refreshes the recent list, depending on context.

## States and edge cases

- **Irreversible action**: show a clear irreversible label and no executable undo control.
- **Stale undo handle**: disable the action and explain that newer changes or drift prevent safe rollback.
- **Partial rollback**: if only part of a planning rollback succeeds, show the partial result explicitly with failure detail and next-step guidance.
- **Concurrent changes after the receipt**: the undo path must validate freshness so an old receipt cannot silently undo a newer change.
- **Claimed loops**: if loop undo requires claim-aware execution, the transport contract must expose the needed claim context before web undo is treated as complete.
- **Repeated clicks or retries**: undo actions should be idempotent or clearly reject duplicates without creating ambiguous state.
- **Deleted target after execution**: show why undo is no longer available rather than failing silently.

## Contract implications

- `frontend/src/contracts-ui.ts` should gain a first-class undo action contract instead of overloading `event` or `rollbackLabel`.
- Shared operator action cards should be able to carry both trust copy and executable undo actions without introducing a separate receipt-only renderer.
- `RecentShellActionOutcome` should carry structured executable undo metadata, not just `rollbackLabel`.
- `frontend/src/action-receipts.ts` should be able to attach undo actions to receipt cards using the same shared action-card model as open, pin, stage, and defer actions.
- `TrustSurfaceMetadata.rollbackLabel` should remain trust copy, not the executable contract.
- Planning rollback needs a public transport-safe execution path. Internal helpers in `execution_rollback.py` are not sufficient by themselves for frontend-triggered rollback.
- Loop-event undo should validate that the intended reversible event is still the correct one to undo. If the existing `POST /loops/{loop_id}/undo` contract is too coarse for safe receipt-driven undo, it should be extended with freshness validation such as an expected event identifier or equivalent server-side guard.
- Working-set undo should follow the same freshness-safe rule, using durable working-set event handles instead of advisory rollback copy.
- Undo responses should return enough structured data to create a new receipt and handoff result so continuity remains coherent after rollback.
- `ShellLocationContract` should remain the canonical navigation target for post-undo landing states.

## Recommended delivery sequence

1. **Lock the backend-safe undo contract**
   - decide what structured undo handle the frontend may safely store and replay
   - distinguish direct loop-event undo from planning rollback actions
2. **Add shared frontend action support**
   - extend the shared card and receipt model to represent executable undo cleanly
   - keep advisory rollback text separate from executable actions
3. **Ship the highest-value reversible flows first**
   - planning rollback and loop-event undo are the first mandatory surfaces
   - review, enrichment, working-set, and command-palette follow-through then reuse the same shared model
4. **Define degraded behavior**
   - stale handles, partial rollback, drift, and irreversible actions should all render explicit reasons instead of generic failure messages

## Acceptance criteria

- Any receipt for a backend-reversible outcome can render an executable undo or rollback action through the shared action-card model.
- Reversible and irreversible outcomes remain visually consistent, but only truly reversible outcomes render executable controls.
- Undo is available from receipt cards, recent history, and command-palette recents using the same underlying handle.
- Review, enrichment, planning, and working-set follow-through all use the same reversibility model instead of bespoke per-surface affordances.
- Stale, partial, or no-longer-safe undo paths are explained explicitly.
- Successful undo emits a new landed receipt with a clear resume target.

## Dependencies

- [`trust-surfaces.md`](trust-surfaces.md)
- [`ai-action-cards.md`](ai-action-cards.md)
- [`workflow-handoffs.md`](workflow-handoffs.md)
- [`review-redesign.md`](review-redesign.md)
- [`working-sets.md`](working-sets.md)
- [`command-palette.md`](command-palette.md)
- [`state-navigation.md`](state-navigation.md)
- [`outcome-continuity.md`](outcome-continuity.md)

## Open questions

- Should planning rollback be presented as “Undo” when it is complete and as “Rollback” when it is best-effort, or should one label be used consistently?
- Should stale undo handles remain visible but disabled for auditability, or disappear once unsafe?
- For multi-resource outcomes, should the user get one top-level rollback action or an intermediate confirmation view listing the exact rollback operations that will run?
