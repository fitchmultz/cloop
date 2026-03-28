# Outcome-First Continuity History

## Why

Cloop continuity should describe what landed, not just where the operator started.

A planning checkpoint, review action, working-set mutation, or recall-side handoff should later answer:

- what changed
- where it landed
- what to reopen now
- whether it is reversible

## Outcome

Cloop uses an outcome-first continuity model.

The operator workspace, receipt rail, command-palette recents, and stale-workflow recovery paths should all prefer the landed result and its resolved reopen target over raw launch metadata.

Working sets still support lightweight reusable launch helpers. `state_anchor` and `query_anchor` remain the API/storage item-type values for those helpers, but backend continuity no longer stores a separate resume-anchor model.

## Current implementation contract

### Durable backend continuity

`src/cloop/storage/continuity_store.py` and `/loops/continuity*` now persist and hydrate:

- landed outcomes
- workflow summaries
- resolved resume and recovery targets
- last-seen markers
- notification delivery state
- recovery acknowledgements

### Browser-local continuity

`frontend/src/continuity-intelligence.ts` keeps browser-local state for:

- baseline snapshots used for since-last comparisons
- cached durable outcomes, workflow summaries, notifications, and acknowledgements
- pending unsynced landed outcomes and other high-signal continuity writes
- recent command usage that still affects palette ranking locally

### Reopen and display precedence

1. Durable reopen and stale-target recovery should use backend-authored workflow summaries and resolved resume targets.
2. Fresh local receipts may be merged into frontend continuity feeds before sync catches up.
3. Launch metadata remains fallback context only when no landed outcome or durable recovery target is available.

### Working-set boundary

Continuity should preserve working-set scope when the landed result belongs to an active bounded context.

If that scope disappears, continuity should fall back to the durable target or home using the backend-authored recovery contract.

## Surfaces in scope

### Operator workspace

The since-last area should summarize landed changes, durable workflow movement, and explicit recovery paths instead of replaying click history.

### Receipt rail

The global receipt rail should surface the latest landed result, rollback cues, and rerun affordances using the same outcome contract as operator home.

### Command palette

The Recent group and durable resume commands should stay aligned with the ranked continuity feed and durable reopen resolution.

### Planning and review recovery

Saved planning and review session reopen flows should resolve through durable continuity summaries, not stale browser-local launch state.

### Recall follow-through

Recall-side mutations should record landed receipts so downstream work reopens from the result, not from the recall surface entry point.

## Non-goals

- Reintroducing backend resume-anchor persistence.
- Promoting low-signal navigation events into continuity headlines.
- Replacing deterministic drift and recovery logic with speculative AI summaries.

## Acceptance criteria

- Returning users see landed changes and workflow movement in the default operator workspace.
- Fresh local receipts can appear in continuity feeds before backend sync completes, without changing durable reopen resolution.
- Stale or missing planning/review targets degrade through explicit backend-authored recovery paths.
- Working-set `state_anchor` and `query_anchor` values remain valid API/storage launch-helper item types without becoming continuity transport state.
- Continuity remains calm and high-signal rather than turning into an event log.

## Dependencies

- [`continuity-intelligence.md`](continuity-intelligence.md)
- [`workflow-handoffs.md`](workflow-handoffs.md)
- [`working-sets.md`](working-sets.md)
- [`operator-workspace.md`](operator-workspace.md)
- [`command-palette.md`](command-palette.md)
- [`ai-action-cards.md`](ai-action-cards.md)
- [`trust-surfaces.md`](trust-surfaces.md)
