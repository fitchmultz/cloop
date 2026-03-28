# Working Sets and Focus Mode

## Why

Real work rarely happens one loop at a time. Users operate on a temporary, meaningful slice of the system: a launch, a hiring process, a weekly review, or a troubleshooting pass. Cloop should make that working context durable.

## Outcome

Users can create, save, resume, and share a temporary operational slice containing the objects that matter for one effort, with a dedicated working-set session surface that restores the full bounded context.

## User jobs

- Pin the loops, sessions, and context relevant to one initiative.
- Return later without rebuilding context.
- Focus on a bounded set of work without unrelated noise.
- Launch planning, review, chat, and search against the current working set.

## Non-goals

- Replacing saved views or saved review sessions.
- Creating a second generic tagging system.
- Turning working sets into permanent project management objects by default.

## UX principles applied

- Continuity is a feature.
- Calm by default, deep on demand.
- Shared contract, local ergonomics.
- Keyboard is first-class.

## Working-set model

A working set can contain:

- loops
- planning sessions
- saved review sessions
- saved views
- notes or memory references
- optional saved queries and saved locations (`query_anchor` and `state_anchor` remain the API/storage `item_type` values for these launch helpers)

Working sets should support:

- quick pin / unpin
- ordering
- naming
- restoring last active set
- switching to focus mode

Contract defaults:

- one durable active working-set context is stored alongside the named sets
- a dedicated shell route (`#working-set/:id`) restores the set as a first-class session surface
- focus mode is explicit and can be toggled on/off without deleting the active set
- sets may contain both durable object references and lightweight launch helpers when the shell needs a reusable launch target
- working-set create/focus/pin/stage/defer/reorder/remove/bulk-add mutations emit shared receipt cards so the landed outcome, executable undo action, and reopen path stay visible after the mutation lands
- working-set and focus-mode responses expose exact reversible event handles so receipts, recent history, and command-palette recents can replay the same safe undo contract everywhere

## Focus mode

Focus mode should:

- suppress unrelated noise outside the active set
- keep the active queue, plan, or loop prominent
- preserve fast navigation within the set
- expose exit and breadcrumb controls clearly

## Key workflows

### Build a working set

1. User pins loops and sessions from Operator, Plan, Review, or Recall surfaces.
2. User saves the selection as a named set.
3. Set becomes available from operator workspace and command palette.

### Resume a working set

1. User returns later.
2. Operator workspace, continuity cards, or command palette surface a working-set session launch.
3. User opens the dedicated session surface, sees the full ordered membership, and optionally enters focus mode.

### Use a working set during planning

1. User opens a planning session from an active set.
2. Planning and AI recommendations reference the set as the current operational context.
3. Follow-up sessions created from the plan can be added to the same set automatically or by prompt.
4. Planning impact cards and downstream review launches keep the same working-set badge, breadcrumb trail, and next-surface cue so the bounded context remains visible after execution.

## States and edge cases

- **Empty working set**: show setup guidance, not an empty shell.
- **Deleted object inside set**: show graceful missing-state chips rather than breaking the set.
- **Stale saved query**: explain drift and offer refresh.
- **Too-large set**: nudge the user toward splitting the set if it loses focus value.

## Contract implications

- Working sets need a durable domain object plus a reversible event log for exact-handle undo.
- They should reference existing durable objects by IDs instead of duplicating payloads.
- `query_anchor` and `state_anchor` remain stable API/storage `item_type` values, while user-facing copy should stay neutral.
- Shared surfaces should be able to read/write working-set membership consistently.
- Working-set context changes and working-set membership mutations should reuse the same shared undo contract rather than bespoke transport-specific reversal paths.

## Acceptance criteria

- Users can save and restore a bounded cross-surface context.
- Working sets can include both work objects and workflow objects.
- Focus mode visibly reduces unrelated noise.
- Working sets integrate with operator workspace, planning, review, and command palette flows.

## Dependencies

- [`docs/ux/operator-workspace.md`](operator-workspace.md)
- [`docs/ux/state-navigation.md`](state-navigation.md)
- [`docs/ux/command-palette.md`](command-palette.md)

## Open questions

- Should working sets auto-capture associated sessions and follow-up resources by default, or only when the user explicitly opts in?
- Should one global “current working set” exist in addition to saved named sets?
