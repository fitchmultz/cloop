# Outcome-Anchored Continuity History

Implementation plan: [`outcome-continuity-plan.md`](outcome-continuity-plan.md)

## Why

Cloop now has most of the raw pieces needed for continuity: shared action cards, post-action receipts, workflow handoffs, working-set session resumes, command-palette recents, and browser-local continuity state. The current gap is that continuity still too often describes where work started instead of what actually landed.

A user who executes a planning checkpoint, applies an enrichment suggestion, stages a working-set change, or takes a review action should later see the landed result first:

- what changed
- where it landed
- what to reopen next
- whether it is reversible

Today, the frontend already stores both launch-point context and receipt outcomes, but cross-surface continuity does not consistently privilege the receipt outcome. That leaves operator history, since-last summaries, and resume cues less trustworthy than the underlying system already allows.

## Outcome

Cloop’s continuity history is anchored to landed outcomes rather than launch points.

Operator “since last visit” summaries, recent-action history, working-set anchors, workflow handoffs, and command-palette resume flows should all prefer the actual post-action result and its best resume target.

A returning user should be able to answer, at a glance:

- what actually changed
- what durable object or queue was created or updated
- what surface to resume now
- how this related to the working set they were in

## User jobs

- Return after time away and see what actually landed, not just where they clicked from.
- Reopen the exact loop, review queue, planning session, or working-set session that now matters.
- Preserve bounded context across planning, review, recall, and working-set flows.
- Understand the difference between an action’s launch surface and its landed outcome.

## Non-goals

- Replacing the baseline or drift-detection model in [`continuity-intelligence.md`](continuity-intelligence.md).
- Persisting rich operator continuity history to the backend database in this phase.
- Capturing every low-signal navigation event as meaningful continuity.
- Inventing speculative AI summaries when deterministic receipts already exist.

## UX principles applied

- Continuity is a feature.
- One obvious next move.
- Workflow handoffs beat tab jumping.
- Trust at the point of action.
- Calm by default, deep on demand.

## Current implementation baseline

Frontend continuity and receipt primitives already exist:

- `frontend/src/continuity-intelligence.ts` stores:
  - `ContinuityBaselineSnapshot`
  - `ResumeAnchorState`
  - recent `RecentShellActionEntry[]`
- recent shell actions are browser-local in `localStorage`, capped at 12 entries, with 15-second deduping for matching label, location, and summary
- `frontend/src/continuity-intelligence.ts::readRecentShellReceiptEntries()` already filters recent actions down to receipt-kind entries
- `frontend/src/action-receipts.ts::createReceiptCard()` builds receipt-flavored `OperatorActionCard` objects with trust metadata, handoff metadata, and resume affordances
- `frontend/src/action-receipts.ts::withReceiptOutcome()` already attaches:
  - `outcome.card`
  - `outcome.resumeLocation`
  - `outcome.rollbackLabel`
  to `RecentShellActionEntry`
- `frontend/src/contracts-ui.ts` already defines the core client-side continuity types:
  - `RecentShellActionEntry`
  - `RecentShellActionOutcome`
  - `ShellLocationContract`
  - `OperatorActionCard`
  - `OperatorActionHandoff`
  - `ResumeAnchorState`
  - `ContinuityBaselineSnapshot`

Current gap: the data model already contains landed-outcome information, but many continuity surfaces still privilege `RecentShellActionEntry.location` over `RecentShellActionEntry.outcome.resumeLocation` and the receipt card that describes what landed.

## Outcome continuity model

### Launch point vs landed outcome

Every meaningful shell mutation has two different contexts:

1. **Launch point**
   - where the operator initiated the action
   - represented today by `RecentShellActionEntry.location`
2. **Landed outcome**
   - the actual result after the mutation completed
   - represented today by `RecentShellActionEntry.outcome.card` plus `RecentShellActionEntry.outcome.resumeLocation`

Continuity should treat the landed outcome as the primary truth whenever it exists.

### Precedence rules

When rendering continuity history or resume cues:

1. prefer `RecentShellActionEntry.outcome.resumeLocation` over `RecentShellActionEntry.location`
2. prefer `RecentShellActionEntry.outcome.card.title`, `summary`, `preview`, and `handoff` over the original action label and description
3. preserve working-set context from the landed outcome:
   - use `outcome.card.handoff.workingSet` when available
   - otherwise use `resumeLocation.workingSetId` when present
4. only fall back to the launch point when:
   - the action never produced a receipt outcome
   - the action was purely navigational
   - the landed target is missing and no graceful fallback exists

### What counts as a continuity-worthy landed outcome

This spec applies to mutations that produce meaningful durable or workflow state, including:

- planning checkpoint execution
- review decisions that change loop or review state
- enrichment apply/reject flows that materially change loop state or queue status
- working-set mutations that change bounded context
- command-palette quick actions that mutate real objects
- post-action handoffs that create or update durable review or planning resources

Low-signal navigation-only actions should remain secondary history, not headline continuity.

## Surfaces in scope

### Operator workspace: Since last visit

The “Since last visit” zone in [`operator-workspace.md`](operator-workspace.md) should summarize what landed:

- changed loops
- created review sessions
- updated working-set state
- downstream queues now ready
- meaningful completions

It should not read like a click log.

### Recent-action history

Recent history should read like a landed-outcome ledger:

- “Applied enrichment to Loop 42”
- “Created relationship review session for hiring backlog”
- “Reordered working set Launch Readiness”

not just:

- “Used enrichment review”
- “Opened review”
- “Ran quick action”

### Working-set anchors

If an action was taken inside an active working set, continuity should keep the working-set scope visible after the mutation lands. Reopening the history item should return to the outcome inside that bounded context whenever possible.

### Workflow handoffs

[`workflow-handoffs.md`](workflow-handoffs.md) already defines change summary, created resources, next step, rollback cues, and breadcrumbs. Outcome continuity should reuse those handoff structures as continuity inputs instead of rebuilding summary text separately.

### Command palette recents and resume flows

The command palette should prefer recent landed outcomes over raw recent commands when offering resume-recent-work paths.

### Recall follow-through

Recall surfaces should record continuity around the durable result of a recall-side action, not just the fact that recall was opened. When a recall action stages work, saves a brief, or hands off into another surface, continuity should reopen that landed result.

## Key workflows

### Post-action continuity capture

1. User completes a meaningful mutation from planning, review, working set, recall follow-through, or command palette.
2. The surface creates a receipt card using `createReceiptCard(...)`.
3. The surface records the action using `withReceiptOutcome(...)` and `recordRecentShellAction(...)`.
4. Continuity readers later consume the receipt entry through `readRecentShellReceiptEntries()`.
5. Operator workspace, recent history, and command palette render the landed outcome and reopen `outcome.resumeLocation`.

### Return-to-app flow

1. User returns to Cloop after time away.
2. Operator workspace reads recent receipt entries and the baseline snapshot together.
3. “Since last visit” emphasizes landed changes first, with grouped summaries when several outcomes belong to the same workflow thread.
4. The primary CTA resumes the landed target, not the launch surface.

### Working-set continuity flow

1. User performs a mutation while a working set is active.
2. The receipt outcome preserves the working-set-aware handoff and resume location.
3. Recent history and command-palette recents reopen the outcome inside the working-set session when that context is still valid.
4. If the working set is gone, continuity falls back to the durable object target and explains the missing set context.

### Workflow handoff continuity flow

1. A planning or review action creates a downstream resource such as a saved review session.
2. The receipt card already shows the created resource and next launch surface.
3. Continuity history stores and reuses that downstream launch target as the primary resume point.
4. Reopening later should take the user into the created queue, not back to the source workflow unless the created queue is unavailable.

## States and edge cases

- **No receipt outcome available**: fall back to `RecentShellActionEntry.location`, but treat that as degraded continuity, not the desired standard.
- **Landed target deleted or stale**: show a stale or missing state and offer a safe fallback to the originating workflow or operator workspace.
- **Multiple resources created by one action**: use the receipt’s primary `resumeLocation` as the main CTA and expose the remaining created resources in the secondary details or handoff area.
- **Rapid repeated actions**: dedupe based on landed outcome identity and summary when possible, not just launch-point label.
- **First browser session or cleared local storage**: continuity can fall back to baseline snapshots and active saved sessions without pretending there is recent local outcome history.
- **Cross-device usage**: browser-local history may be absent on another device; the UI should degrade gracefully rather than implying history loss is an error.
- **Irreversible action**: still show the landed outcome clearly; undo behavior is specified separately in [`undo-actions.md`](undo-actions.md).

## Contract implications

- `RecentShellActionEntry.location` remains useful launch metadata, but it is not the canonical continuity target once `outcome` exists.
- `RecentShellActionOutcome.card` and `RecentShellActionOutcome.resumeLocation` should become the canonical source for:
  - recent outcome history
  - since-last summary cards
  - command-palette resume items
  - working-set-aware reopen targets
- `ShellLocationContract` remains the canonical navigation contract for landed resume targets. Do not replace it with raw route strings.
- `OperatorActionCard.handoff` should be treated as structured continuity input, especially:
  - `changeSummary`
  - `createdResources`
  - `nextStep`
  - `breadcrumbs`
  - `workingSet`
- `ContinuityBaselineSnapshot` should remain focused on drift, baseline, and system-state comparisons. Do not overload it with detailed recent receipt history.
- Any meaningful mutation that emits a receipt but omits a landed `resumeLocation` should be treated as a contract bug to fix in the emitting surface.

## Recommended delivery sequence

1. **Lock the landed-outcome contract**
   - finalize precedence rules between launch metadata and landed receipt metadata
   - define what qualifies as continuity-worthy history versus low-signal navigation noise
2. **Align core readers and summaries**
   - update operator since-last logic, recent-action readers, and resume anchors to consume landed outcomes first
   - make grouped summaries and dedupe rules outcome-aware
3. **Finish cross-surface emitters**
   - planning, review, recall follow-through, working-set flows, and command-palette mutations should all emit complete landed receipt data
4. **Verify degraded cases**
   - missing targets, cleared browser storage, stale resources, and removed working sets should all fall back predictably

## Acceptance criteria

- Operator “Since last visit” content prefers landed receipt outcomes over launch-point labels when receipt data exists.
- Recent-action history reopens the landed target through `outcome.resumeLocation` rather than the originating surface.
- Working-set-scoped actions preserve working-set context in continuity and resume flows.
- Workflow handoff summaries and continuity summaries use the same structured receipt and handoff data instead of diverging prose.
- Missing or stale landed targets degrade gracefully with explicit fallback behavior.
- Continuity remains calm and high-signal; it does not become a raw event log.

## Dependencies

- [`continuity-intelligence.md`](continuity-intelligence.md)
- [`workflow-handoffs.md`](workflow-handoffs.md)
- [`working-sets.md`](working-sets.md)
- [`operator-workspace.md`](operator-workspace.md)
- [`command-palette.md`](command-palette.md)
- [`ai-action-cards.md`](ai-action-cards.md)
- [`trust-surfaces.md`](trust-surfaces.md)

## Open questions

- Should the 12-entry recent-action cap stay fixed once landed outcomes become the primary continuity rail, or should it increase?
- When several landed outcomes belong to one planning checkpoint, should the operator workspace show one grouped rollup by default or multiple individual receipts?
- Should launch-point context remain visible inline on continuity cards, or move behind a details affordance once landed outcomes become primary?
