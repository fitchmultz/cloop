# Operator Workspace

## Why

The current product exposes strong capabilities, but users still have to mentally assemble their own cockpit by moving between tabs. The operator workspace makes Cloop feel like one coherent system instead of a capability collection.

## Outcome

A user should be able to open Cloop and immediately understand:

- what deserves attention now
- what is blocked or drifting
- what plan or review queue is active
- what the system prepared since the last session
- what action to take next

## User jobs

- Start the day without hunting for context.
- Resume an interrupted multi-step workflow.
- See the most important work, decisions, and follow-ups in one place.
- Launch directly into the next relevant surface.

## Non-goals

- Replacing every specialized screen.
- Building a metrics dashboard as the default landing page.
- Showing every open loop at once.

## UX principles applied

- State over subsystem.
- One obvious next move.
- Calm by default, deep on demand.
- Workflow handoffs beat tab jumping.
- Continuity is a feature.

## Core layout

The operator workspace should become the default landing surface and contain these zones:

1. **Now**
   - most urgent or highest-signal work items
   - active timer/focus item if present
2. **Decisions**
   - pending review sessions
   - queued clarifications
   - blocked items awaiting human judgment
3. **Plan in motion**
   - current planning session
   - current checkpoint
   - last execution result
   - launch surface to the next downstream queue
4. **Since last visit**
   - newly created follow-up resources
   - newly blocked or stale loops
   - recent completions and meaningful changes
5. **Working set**
   - pinned loops, sessions, notes, and related context

## Information architecture impact

- Introduce the operator workspace as the default route and visual home.
- Existing tabs or surfaces remain accessible, but they become subordinate deep-work surfaces rather than the main orientation model.
- Planning, review, and chat surfaces should be launchable from cards inside the operator workspace.

## Key workflows

### Start-of-session flow

1. User lands in operator workspace.
2. Workspace highlights the primary active queue or plan.
3. User chooses one recommended action card.
4. System opens the downstream surface with preserved context.

### Resume-work flow

1. User returns after time away.
2. Workspace shows “since last visit” summary.
3. User can re-open the last working set, review queue, or plan checkpoint directly.

### Handoff flow

1. A planning checkpoint or review action completes.
2. The operator workspace updates the relevant zone.
3. A follow-up card exposes the next queue or action without forcing tab navigation.

## States and edge cases

- **Empty first-run state**: explain the operator loop and offer capture plus starter setup.
- **No active plan/review state**: emphasize Now + Capture + suggested next setup.
- **Stale plan state**: highlight drift and offer refresh.
- **Unavailable AI state**: workspace still shows deterministic queues and context without collapsing.
- **No since-last-visit changes**: suppress the zone or show a compact calm state.

## Contract implications

The workspace should preferentially consume existing shared outputs rather than invent a frontend-only aggregator:

- planning session snapshots and execution history
- saved review session snapshots
- deterministic loop cohorts and prioritization outputs
- explicit handoff metadata such as launch surfaces and follow-up resources

A thin aggregation layer may be needed, but it should compose shared service outputs rather than fork their logic.

## Acceptance criteria

- Cloop has a single default landing workspace for active operational work.
- Users can see active work, pending decisions, plan status, and recent changes without tab hopping.
- At least one clear primary action is visible in each major zone.
- Planning and review handoffs can be launched directly from the workspace.
- Empty, stale, and unavailable-AI states are still coherent.

## Dependencies

- [`docs/ux/principles.md`](principles.md)
- [`docs/ux/state-navigation.md`](state-navigation.md)
- [`docs/ux/workflow-handoffs.md`](workflow-handoffs.md)

## Open questions

- Should the working set live inside the operator workspace by default or as a docked side panel?
- Which deterministic prioritization signals should drive the Now zone before learned/behavioral scoring exists?
