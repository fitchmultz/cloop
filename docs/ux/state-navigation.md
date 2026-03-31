# State-Driven Navigation

## Why

Navigation currently reflects internal capability boundaries more than the user’s mental model. A powerhouse UX should move users through work states, not ask them to understand Cloop’s subsystem layout.

## Outcome

Users should navigate by the kind of work they are doing:

- capture something
- do ready work
- decide ambiguous work
- plan a multi-step pass
- review drift
- recall context

## User jobs

- Move quickly between work modes without interpreting product internals.
- Understand where planning, review, chat, memory, and retrieval fit in the same system.
- Resume a workflow from the right state instead of reopening generic tabs.

## Non-goals

- Hiding advanced capabilities.
- Removing deep surfaces for power users.
- Forcing one rigid workflow for every user.

## UX principles applied

- State over subsystem.
- One obvious next move.
- Workflow handoffs beat tab jumping.
- Keyboard is first-class.

## Proposed top-level model

### Primary states

- **Capture**: fast ingest of new work or context.
- **Do**: ready work, timers, and focused execution.
- **Decide**: review sessions, clarifications, and ambiguous items.
- **Plan**: checkpointed sessions and AI-prepared multi-step flows.
- **Review**: broader hygiene, drift, and quality-control passes.
- **Recall**: semantic search, memory, and RAG-backed retrieval.

### Object-level navigation

Within any state, the user can jump to concrete objects:

- loop
- planning session
- review session
- working set
- note / memory item
- chat thread or grounded response context

## Information architecture impact

- Rework the primary navigation shell around states, not subsystem labels.
- Existing surfaces such as chat, memory, and RAG should become state-specific tools or supporting panels where appropriate.
- Saved sessions and working sets should be first-class navigation targets.

## Mapping from current surfaces

- current Inbox / Next → mainly **Do**
- planning workspace → **Plan**
- relationship + enrichment review sessions → **Decide**
- daily/weekly review cohorts → **Review**
- memory + semantic search + RAG retrieval → **Recall**
- quick capture → **Capture**

## Key workflows

### Navigation from an action card

1. User accepts an action card in Operator workspace.
2. App routes to the correct state surface with context already selected.
3. Breadcrumbs keep the path back to the prior workflow.

### Navigation from command palette

1. User invokes palette.
2. User searches for a state, object, or saved workflow.
3. App opens the exact destination in the correct work mode.

## States and edge cases

- **No saved sessions in a state**: state still explains purpose and offers setup actions.
- **Deep-linked object**: shell still reflects the parent work state.
- **Unavailable AI/RAG**: state remains usable with deterministic tools.
- **Mobile layout**: small screens collapse Do, Decide, Plan, and Review under a single top-level Work entry with a secondary mode switcher, while deep links and desktop states remain unchanged.

## Contract implications

- Navigation state should be driven by real domain objects and session IDs rather than brittle client-only modes.
- Downstream deep links should carry enough context to open the target object already selected.
- Existing saved review/planning session contracts should remain the canonical object references.

## Acceptance criteria

- Top-level navigation language is state-oriented rather than subsystem-oriented.
- Users can enter planning, decision, review, and recall flows without remembering internal feature names.
- Deep links preserve both object identity and work-state context.
- Existing power-user workflows remain reachable but are nested under clearer state language.

## Dependencies

- [`docs/ux/principles.md`](principles.md)
- [`docs/ux/operator-workspace.md`](operator-workspace.md)

## Open questions

- Where should grounded chat live in the new shell: as a Recall tool, a persistent assistant, or both?
