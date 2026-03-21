# Workflow Handoffs

## Why

Cloop already has durable planning sessions, saved review queues, and explicit execution metadata. The next step is making handoffs feel obvious and frictionless so users do not need to manually reconstruct what comes next.

## Outcome

Any meaningful system action should answer:

- what changed
- what downstream work was created
- what the next likely operator step is
- how to launch that next step immediately
- how to get back

## User jobs

- Move from planning to review without searching.
- Resume the next queue after a mutation finishes.
- Understand downstream consequences of executed checkpoints.
- Preserve breadcrumbs across multi-surface workflows.

## Non-goals

- Replacing all navigation with forced redirects.
- Hiding alternate paths from experienced users.
- Auto-advancing through consequential work without confirmation.

## UX principles applied

- One obvious next move.
- Workflow handoffs beat tab jumping.
- Continuity is a feature.
- Trust at the point of action.

## Handoff model

Every handoff-capable workflow result should render:

1. **Change summary**
   - what succeeded, failed, or partially completed
2. **Created resources**
   - loops, sessions, views, templates, or other durable follow-ups
3. **Next operator surface**
   - the recommended downstream queue or object to open now
4. **Rollback / replay cues**
   - what can be undone or safely retried
5. **Breadcrumbs**
   - how to return to the prior workflow state

## Primary handoff chains

- planning checkpoint → saved review session
- planning checkpoint → newly created loop in working set
- continuity / command-palette handoff → dedicated working-set session surface
- review decision → next item in queue
- chat recommendation → edit/execute surface
- enrichment clarification answer → refreshed suggestion queue

## Interaction details

- The primary CTA should launch the next surface in-context.
- Secondary CTA should show details or keep the user in the current surface.
- Breadcrumbs should preserve prior session identity and cursor where relevant.
- Working-set-aware handoffs should render the same working-set badge, next-step cue, and breadcrumb trail in operator cards and downstream review/planning impact cards.
- Handoffs should prefer existing saved session IDs and resource references, not inferred client state.
- If the same workflow can be rerun or refreshed, the handoff should make strict invariants, variable attempt behavior, and the post-run landing surface explicit before execution.
- When several deterministic handoff themes changed at once, the operator shell may surface a grouped rollup card before deeper workflow-specific cards.

## States and edge cases

- **No downstream surface created**: result still explains completion and likely next manual option.
- **Multiple follow-up resources**: present ranked recommendations plus full list.
- **Partial failure**: make the handoff safe and explicit; do not imply full success.
- **Stale downstream target**: explain drift and offer an explicit recovery path such as open replacement workflow, reopen launch workflow, or return home safely.

## Contract implications

- Existing planning execution metadata (`summary`, `follow_up_resources`, `launch_surfaces`, `rollback_cues`) should become the pattern for other AI-backed workflows.
- Saved review sessions, planning sessions, and other durable resources should remain transport-neutral identifiers.
- Frontend components should consume structured handoff payloads rather than reverse-engineering them from prose.

## Acceptance criteria

- Planning, review, and other workflow surfaces visibly explain what comes next.
- A primary launch action exists whenever a real downstream surface was created.
- Users can return to their prior workflow state with breadcrumbs or session preservation.
- Handoff messaging never assumes outcomes that have not actually occurred.

## Dependencies

- [`docs/ux/principles.md`](principles.md)
- [`docs/ux/operator-workspace.md`](operator-workspace.md)
- [`docs/ux/ai-action-cards.md`](ai-action-cards.md)

## Open questions

- When multiple downstream surfaces are equally valid, should the operator workspace become the neutral handoff destination or should the current surface present ranked options inline?
