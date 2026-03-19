# Continuity and Session Intelligence

## Why

A powerhouse tool should feel like it remembers what happened, what drifted, and what deserves attention now. Continuity turns Cloop from a static store of objects into an ongoing operating environment.

## Outcome

Users can return to Cloop and immediately understand what changed, what is aging, and which workflows should resume next.

## User jobs

- Pick up where they left off.
- See meaningful changes since the last visit.
- Detect drift in plans, queues, and long-lived work.
- Understand emerging risk without running manual audits.

## Non-goals

- Creating noisy notification spam.
- Guessing at behavior with opaque ML before deterministic signals exist.
- Replacing explicit review workflows.

## UX principles applied

- Continuity is a feature.
- One obvious next move.
- Trust at the point of action.
- Calm by default, deep on demand.

## Core continuity surfaces

### Since last visit

A compact summary should highlight:

- newly created or updated follow-up resources
- grouped planning-driven resource rollups when checkpoint execution changed multiple durable objects
- newly blocked or stale loops
- completed work
- plans or sessions that drifted
- recent important decisions

### Resume points

The app should remember and surface:

- last active working-set session
- last active planning session
- last active review session
- recent command/action history
- working-set-scoped resumes ahead of generic session resumes when a bounded context is already active

### Drift signals

The system should surface when:

- a plan’s grounding no longer reflects current loop state, including which target loops changed and which fields drifted
- a newer planning session replaced the prior primary plan with partial or zero target overlap
- checkpoint execution changed downstream durable resources such as review sessions, views, or templates
- a saved session’s queue meaningfully changed
- loops silently aged into higher-risk cohorts
- repeated defer/snooze behavior suggests avoidance or drift

## Key workflows

### Return-to-app flow

1. User opens Cloop.
2. Operator workspace shows a since-last-visit summary.
3. User can resume prior work or pivot to newly urgent work.

### Drift-recovery flow

1. System detects a plan or queue is stale.
2. UI shows why it is stale and what changed.
3. User refreshes, accepts drift, or archives the workflow.

### Momentum flow

1. User completes several decisions or actions.
2. System updates recent changes and queue health.
3. Operator workspace reflects progress without requiring manual refresh across surfaces.

## States and edge cases

- **First session**: no continuity module; emphasize setup and capture.
- **No meaningful changes**: show a calm state rather than synthetic activity.
- **Large change burst**: summarize at a higher level with grouped change themes, then allow drill-down.
- **Unavailable AI**: continuity should still work from deterministic signals.

## Contract implications

- The system likely needs durable “last seen” or “last visited” tracking at the UI/session level.
- Continuity views should compose existing event history, saved session metadata, and planning execution outputs before adding new intelligence layers.
- Drift detection should begin with deterministic comparisons, not speculative scoring.

## Acceptance criteria

- Returning users can see a since-last-visit summary in the default workspace.
- The app surfaces clear resume points for active workflows.
- Plan and session drift is visible and actionable.
- Continuity information remains calm and high-signal rather than noisy.

## Dependencies

- [`docs/ux/operator-workspace.md`](operator-workspace.md)
- [`docs/ux/working-sets.md`](working-sets.md)
- [`docs/ux/trust-surfaces.md`](trust-surfaces.md)

## Open questions

- Should continuity be primarily local-to-device/session, or is there value in persisting a richer operator history inside the core DB?
- Which drift signals should block action versus simply warn?
