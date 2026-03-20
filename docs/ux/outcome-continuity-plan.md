# Outcome-Anchored Continuity History — Implementation Plan

## 1. Objective and boundaries

This document is the implementation plan for **Roadmap Session 1 — Outcome-anchored continuity history** as defined in:

- [`docs/ux/outcome-continuity.md`](outcome-continuity.md)
- [`docs/roadmap.md`](../roadmap.md)

### Session goal

Make continuity surfaces prefer the **landed outcome** of a meaningful action instead of the **launch point** where the user started it.

A completed planning checkpoint, review decision, enrichment action, working-set mutation, or command-palette mutation should later reopen and describe:

- what actually landed
- where it landed
- what to resume next
- what working-set context still matters

### This is intentionally in scope

- frontend continuity contract and browser-local continuity persistence
- operator workspace “Since last visit” summaries
- recent-action and history readers
- working-set-aware continuity
- command-palette recent and resume behavior
- cross-surface receipt completeness for planning, review, working-set, command-palette, and recall follow-through
- degraded fallback behavior for missing or stale landed targets

### This is intentionally out of scope

- undo and executable rollback work from [`undo-actions.md`](undo-actions.md)
- backend persistence of continuity history
- replacing `ContinuityBaselineSnapshot` with receipt history
- speculative AI-authored continuity summaries when deterministic receipt data already exists

### Planning assumptions

This plan is based on the currently visible frontend files and UX specs. Implementation should treat this document as the source of truth, then perform a repo-wide sweep for additional emitters and readers that must be aligned.

## 2. Current-state diagnosis

The current system already has most of the required primitives, but they are applied inconsistently.

### Already outcome-aware today

These flows already emit receipt-backed `RecentShellActionEntry` records with `outcome.card` and `outcome.resumeLocation`:

1. planning checkpoint execution in `review-workspace.ts`
2. relationship review decisions and preset actions in `review-workspace.ts`
3. enrichment apply, reject, preset, and clarify flows in `review-workspace.ts`
4. working-set mutations in `shell-working-set.ts`
5. command-palette quick actions that already build receipts in `command-palette.ts`

### Still launch-point oriented or partially aligned

1. shell navigation via `applyLocation()` records plain history entries
2. review session switches via `noteActiveReviewSession()` record plain history entries
3. `ResumeAnchorState` stores launch-point session IDs only
4. `buildResumeAnchorsCard()` reads launch-point anchors and raw recent actions
5. command palette keeps a separate `storeRecentCommand()` localStorage system
6. recent-action dedupe uses label + location + outcome summary, but not landed target identity

### Core product gap

The spec says continuity should:

1. prefer `outcome.resumeLocation` over `location`
2. prefer `outcome.card.title`, `summary`, `preview`, and `handoff` over `label` and `description`
3. prefer landed working-set context from `outcome.card.handoff.workingSet`
4. fall back to launch metadata only when no landed outcome exists

The codebase already stores much of this data, but the readers and some emitters do not consistently treat it as canonical.

## 3. Scope and contract lock

This section defines the **landed-outcome continuity contract** that implementation must lock before broader reader and emitter work begins.

### 3.1 Locked precedence rules

1. **Resume target precedence**
   - use `RecentShellActionEntry.outcome.resumeLocation` first
   - fall back to `RecentShellActionEntry.location` only when no outcome exists or the landed target is unavailable
2. **Display precedence**
   - use `outcome.card.title`, `outcome.card.summary`, `outcome.card.preview`, and `outcome.card.handoff` first
   - fall back to `label` and `description` only for plain navigation and fallback entries
3. **Working-set precedence**
   - use `outcome.card.handoff.workingSet` first
   - if absent, fall back to `outcome.resumeLocation.workingSetId`
   - if still absent, fall back to launch metadata only as degraded context
4. **Fallback rules**
   - launch metadata is fallback-only
   - plain navigation must remain secondary history, not the headline continuity model

### 3.2 What counts as continuity-worthy

These should produce or drive outcome-anchored continuity:

- planning checkpoint execution
- review decisions that change queue or loop state
- enrichment decisions that materially change loop state or queue state
- working-set mutations that change durable bounded context
- command-palette quick actions that mutate durable state
- recall follow-through actions that create or update durable objects or hand off into another surface

These should remain low-signal and secondary:

- generic workspace navigation
- session switching with no durable result
- opening a tab or surface without a meaningful mutation
- any click-log style event with no landed state change

### 3.3 Locked contract meanings

| Contract surface | Locked meaning after Session 1 | Consumer rule |
| --- | --- | --- |
| `ShellLocationContract` | Canonical navigation contract for any continuity resume target | Never replace with raw hashes or route strings in continuity logic |
| `RecentShellActionEntry.location` | Launch metadata only | Use for breadcrumbs and degraded fallback, not as the primary resume target when `outcome` exists |
| `RecentShellActionOutcome.resumeLocation` | Canonical landed resume target | All continuity CTAs should prefer this |
| `RecentShellActionOutcome.card` | Canonical landed display payload | All continuity summaries should prefer this over raw label and description |
| `OperatorActionCard.handoff` | Canonical structured continuity summary | Do not rebuild divergent prose when the handoff already exists |
| `OperatorActionHandoff.workingSet` | Canonical working-set context when present | Prefer it over inferred `workingSetId` |
| `ResumeAnchorState` | Should become outcome-aware, not launch-point-only | Replace the current primitive launch-only model |
| `ContinuityBaselineSnapshot` | Drift and baseline comparison only | Do not overload it with receipt history |

### 3.4 Files and functions that constitute the landed-outcome contract

#### Core contract files

- `frontend/src/contracts-ui.ts`
  - `ShellLocationContract`
  - `RecentShellActionEntry`
  - `RecentShellActionOutcome`
  - `OperatorActionCard`
  - `OperatorActionHandoff`
  - `ResumeAnchorState`
  - `ContinuityBaselineSnapshot`
- `frontend/src/action-receipts.ts`
  - `createReceiptCard(...)`
  - `withReceiptOutcome(...)`
- `frontend/src/continuity-intelligence.ts`
  - `readRecentShellActions()`
  - `readRecentShellReceiptEntries()`
  - `recordRecentShellAction(...)`
  - `rememberPlanningAnchor(...)`
  - `rememberReviewAnchor(...)`
  - `readResumeAnchors()`

#### Primary continuity readers

- `frontend/src/shell-operator-cards.ts`
  - `buildSinceLastCards()`
  - `buildLatestReceiptCard()`
  - `buildResumeAnchorsCard()`
  - `buildRepeatedSnoozeCard()`
- `frontend/src/shell.ts`
  - `applyLocation()`
  - `renderShellReceiptRail()`
- `frontend/src/command-palette.ts`
  - `buildCommandReceipt()`
  - `storeRecentCommand()`
  - `commandHistoryKind()`
  - `commandHistoryLocation()`
  - recent-command result construction

#### Receipt and handoff producers that must remain aligned

- `frontend/src/review-workspace.ts`
- `frontend/src/review-workspace-action-cards.ts`
- `frontend/src/review-workspace-handoffs.ts`
- `frontend/src/shell-working-set.ts`

#### Supporting render and helper modules that must not diverge

- `frontend/src/continuity-card-helpers.ts`
- `frontend/src/operator-action-cards.ts`
- `frontend/src/workflow-handoff.ts`
- `frontend/src/shell-routing.ts`
- `frontend/src/command-palette-ranking.ts`

### 3.5 Recommended shared helper layer

Implementation should add a single shared helper module so outcome-precedence logic is not reimplemented ad hoc.

**Recommended new file:** `frontend/src/continuity-outcomes.ts`

**Recommended exports:**

```ts
import type {
  OperatorActionCard,
  OperatorActionHandoff,
  RecentShellActionEntry,
  ShellLocationContract,
  WorkingSetSessionMetadata,
} from "./contracts-ui";

export interface ResolvedContinuityEntry {
  entry: RecentShellActionEntry;
  hasOutcome: boolean;
  card: OperatorActionCard | null;
  displayTitle: string;
  displaySummary: string;
  resumeLocation: ShellLocationContract | null;
  launchLocation: ShellLocationContract | null;
  handoff: OperatorActionHandoff | null;
  workingSet: WorkingSetSessionMetadata | null;
  workingSetId: number | null;
  degradedReason: "none" | "no_outcome" | "missing_resume_location";
}

export function resolveContinuityEntry(entry: RecentShellActionEntry): ResolvedContinuityEntry;
export function resolveContinuityResumeLocation(entry: RecentShellActionEntry): ShellLocationContract | null;
export function resolveContinuityWorkingSetId(entry: RecentShellActionEntry): number | null;
export function continuityLocationIdentity(location: ShellLocationContract | null): string;
export function recentShellActionDedupKey(entry: RecentShellActionEntry): string;
export function isLowSignalNavigationEntry(entry: RecentShellActionEntry): boolean;
```

**Rule:** all continuity readers should consume this helper layer instead of open-coding precedence logic.

### 3.6 Recommended `ResumeAnchorState` cutover

The current `ResumeAnchorState` is too launch-point oriented for Session 1.

**Recommended hard cutover:**

- replace the current primitive shape
- bump the localStorage key
- do not build a long-lived parallel anchor model

**Recommended replacement shape:**

```ts
export interface ResumeAnchorTarget {
  kind: "planning" | "relationship" | "enrichment";
  reviewFocus: "planning" | "relationship" | "enrichment";
  sessionId: number;
  visitedAtUtc: string;
  launchLocation: ShellLocationContract | null;
  resumeLocation: ShellLocationContract | null;
  outcomeTitle: string | null;
  outcomeSummary: string | null;
  workingSetId: number | null;
}

export interface ResumeAnchorState {
  planning: ResumeAnchorTarget | null;
  review: ResumeAnchorTarget | null;
}
```

**Why this cutover is preferred:**

- anchors become directly usable by outcome-first readers
- launch and landed context can coexist cleanly
- browser-local continuity is disposable enough that a storage-key bump is cheaper than maintaining a migration burden

## 4. Delivery phases and step-by-step engineering plan

The roadmap defines three phases. This plan keeps those phases but makes the implementation order explicit.

## 4.1 Phase 1 — Lock the landed-outcome contract and precedence rules

### Phase goal

Create one stable continuity contract so all readers and emitters can agree on what “landed outcome” means.

### Engineering steps

1. **Add the shared continuity-resolution helper layer**
   - create `frontend/src/continuity-outcomes.ts`
   - centralize outcome-vs-launch precedence, working-set precedence, landed-target identity, low-signal navigation classification, and dedupe key generation
2. **Cut over `ResumeAnchorState` to an outcome-aware shape**
   - update `frontend/src/contracts-ui.ts`
   - replace the launch-point-only shape with the richer anchor target shape
3. **Bump resume-anchor localStorage schema**
   - update `RESUME_ANCHORS_STORAGE_KEY` in `continuity-intelligence.ts`
   - treat old local browser anchor data as disposable
   - use tolerant parsing so malformed or old values degrade to empty anchors
4. **Change anchor writers to record landed context**
   - refactor `rememberPlanningAnchor(...)` and `rememberReviewAnchor(...)` to accept rich anchor payloads instead of only `(sessionId, workingSetId)`
   - store launch location, landed resume location, landed title and summary, working-set context, and visited timestamp
5. **Make recent-action dedupe outcome-aware**
   - update `recordRecentShellAction(...)`
   - dedupe should compare landed resume target identity first, landed title and summary second, and time window third
6. **Tighten receipt completeness**
   - update `action-receipts.ts` so receipt helpers make missing `resumeLocation` visibly wrong during implementation
   - treat “meaningful mutation emitted a receipt but no landed `resumeLocation`” as a bug to fix at the emitter
7. **Add contract-level test coverage**
   - cover precedence resolution, working-set precedence, dedupe behavior, and launch-only fallback behavior

### Phase 1 acceptance slices

#### Slice 1A — Precedence helper is canonical

- A mixed `RecentShellActionEntry` with both `location` and `outcome` resolves to `outcome.resumeLocation`.
- The resolved display title and summary come from `outcome.card`, not `label` and `description`.
- Working-set metadata comes from `outcome.card.handoff.workingSet` before any location fallback.

#### Slice 1B — Anchors become outcome-aware

- `ResumeAnchorState` no longer stores only session IDs and timestamps.
- Planning and review anchors can directly represent landed resume targets and landed text.

#### Slice 1C — Dedupe matches landed outcomes

- Repeating the same landed outcome within 15 seconds collapses to one entry even if the launch label changed.
- Two entries with the same launch point but different landed resume targets are not deduped together.

### Spec criteria covered by Phase 1

- prefer `outcome.resumeLocation` over `location`
- prefer `outcome.card.title`, `summary`, and related fields over original launch metadata
- preserve working-set context for scoped actions
- dedupe based on landed outcome identity

## 4.2 Phase 2 — Align core readers and summaries around that contract

### Phase goal

Make the operator workspace and other core continuity readers consume the landed-outcome contract consistently.

### Engineering steps

1. **Refactor operator continuity readers to use the shared helper layer**
   - update `shell-operator-cards.ts` so all continuity readers resolve entries through `resolveContinuityEntry(...)`
   - do not leave ad hoc `entry.outcome?.… ?? entry.…` logic inside readers
2. **Rewrite `buildResumeAnchorsCard()` around landed outcomes**
   - use the new outcome-aware `ResumeAnchorState` as the primary source
   - show landed title and summary first
   - treat launch-point context as secondary detail only
3. **Deduplicate anchor and recent-action CTAs**
   - if the latest receipt and the anchor point to the same landed resume target, do not surface duplicate primary actions in the same continuity deck
4. **Make “Since last visit” calm and high-signal**
   - keep latest receipt, handoffs, drift cards, and grouped rollups
   - do not let low-signal navigation displace outcome cards
5. **Make repeated-snooze detection outcome-aware where possible**
   - update `buildRepeatedSnoozeCard()` and supporting helpers to prefer landed receipt text when snooze entries carry outcomes
6. **Add safe fallback behavior for stale or missing landed targets**
   - validate continuity targets against current working-set and session state when building cards
   - missing working sets should strip missing scope and fall back to the durable object or session target
   - missing landed resources should fall back to launch location if valid, otherwise operator home
7. **Keep the shell receipt rail aligned**
   - verify `renderShellReceiptRail()` remains outcome-first and does not regress to raw history text

### Phase 2 acceptance slices

#### Slice 2A — Operator “Since last visit” is outcome-first

- `buildResumeAnchorsCard()` uses landed outcome text and landed resume targets.
- Continuity cards no longer read like a click log when receipt data exists.
- Launch-point context is secondary, not headline copy.

#### Slice 2B — Resume flows reopen landed targets

- Resume CTAs built from anchors or recent actions open `outcome.resumeLocation`.
- When a working set was active, the continuity CTA reopens the outcome inside that scope when still valid.

#### Slice 2C — Degraded cases are explicit and safe

- Missing working sets degrade to durable object or session targets.
- Missing landed sessions or resources degrade to launch location or operator home.
- The UI does not silently open the wrong place when the original target is gone.

### Spec criteria covered by Phase 2

- operator “Since last visit” prefers landed receipt outcomes
- recent-action history reopens landed targets
- working-set-scoped actions preserve working-set context
- missing or stale landed targets degrade gracefully
- continuity remains calm and high-signal

## 4.3 Phase 3 — Finish cross-surface continuity behavior

### Phase goal

Close the remaining emitter and reader gaps so all major continuity surfaces use landed outcomes consistently.

### Engineering steps

1. **Refactor command-palette recents to prefer landed outcomes**
   - keep `storeRecentCommand()` only as usage and ranking metadata
   - do not treat it as the source of truth for continuity resumes
2. **Refactor command execution to return structured landed outcomes**
   - replace generic pre-execution descriptors with an execution result shape that carries landed title, summary, resume location, and handoff data
3. **Reduce low-signal navigation noise in shell history**
   - update `shell.ts::applyLocation()`
   - stop recording generic navigation events that do not produce continuity value
4. **Change review session switches to anchor-only by default**
   - update `review-workspace.ts::noteActiveReviewSession()`
   - keep updating resume anchors
   - stop adding plain recent-action history entries for session switches by default
5. **Audit working-set receipts for contract completeness**
   - verify every working-set receipt has a landed `resumeLocation`, preserves `handoff.workingSet`, and points primary resume back to `#working-set/:id` when that session is the real landed outcome
6. **Audit review receipts for contract completeness**
   - verify all review and planning receipt builders keep landed title and summary, working-set-aware handoff, and the correct primary resume target
7. **Find and align recall follow-through emitters**
   - search `frontend/src/surfaces/**/*` and any recall-follow-through modules for staged actions, saved briefs, defer flows, edit-before-execute flows, and handoff actions that create or update durable resources
   - any meaningful recall mutation should emit `createReceiptCard(...)`, `withReceiptOutcome(...)`, `recordRecentShellAction(...)`, and a real landed `resumeLocation`
8. **Perform a repo-wide emitter and reader sweep**
   - search for `recordRecentShellAction(`, `withReceiptOutcome(`, `createReceiptCard(`, `storeRecentCommand(`, `rememberPlanningAnchor(`, and `rememberReviewAnchor(`
   - align any newly discovered continuity reader or emitter to the same contract before Session 1 is considered complete

### Phase 3 acceptance slices

#### Slice 3A — Command palette recent and resume is outcome-first

- Palette recent results use landed outcome titles and summaries when available.
- Reopening a recent outcome uses the landed resume target, not the raw command invocation.
- Recent command usage metadata still influences ranking but does not override landed continuity truth.

#### Slice 3B — Navigation noise stays secondary

- Review session switching no longer pollutes recent continuity history by default.
- Generic shell navigation does not displace meaningful receipts in continuity surfaces.

#### Slice 3C — Hidden follow-through emitters are aligned

- Recall-side durable actions emit complete landed receipts.
- Any newly discovered continuity emitter uses the same contract and precedence rules.

### Spec criteria covered by Phase 3

- command palette prefers recent landed outcomes over raw recent commands
- recall surfaces record continuity around durable landed results
- low-signal navigation-only actions remain secondary history
- workflow handoff summaries and continuity summaries use the same structured data

## 5. File-by-file change map

| File | What changes | Why | Change class |
| --- | --- | --- | --- |
| `frontend/src/contracts-ui.ts` | Replace `ResumeAnchorState` with an outcome-aware shape; add any helper-facing anchor types needed for landed continuity | Current anchor type is launch-point-only and blocks outcome-first resume behavior | Type contract change |
| `frontend/src/continuity-outcomes.ts` | Add shared continuity resolution, landed target identity, working-set precedence, and low-signal classification helpers | Prevent duplicated precedence logic across readers | New contract/helper file |
| `frontend/src/continuity-intelligence.ts` | Cut over anchor storage to v2; update anchor writers to store landed context; update dedupe to use landed outcome identity; optionally add higher-level continuity readers | Browser-local persistence must match the new outcome contract | Type contract and reader alignment |
| `frontend/src/action-receipts.ts` | Tighten receipt completeness expectations; keep receipt helpers outcome-first and reusable | Meaningful mutations without landed resume targets should be treated as contract bugs | Contract alignment |
| `frontend/src/shell-operator-cards.ts` | Refactor continuity readers to consume shared helper outputs; rewrite `buildResumeAnchorsCard()` outcome-first; dedupe anchor and recent CTAs; add degraded fallback behavior | Operator workspace “Since last visit” is a primary Session 1 surface | Reader alignment |
| `frontend/src/continuity-card-helpers.ts` | Update snooze and helper logic where raw labels still assume launch-point text; add helper support as needed for calm outcome summaries | Prevent helper-level drift between continuity cards | Reader alignment |
| `frontend/src/shell.ts` | Reduce generic navigation history noise; keep anchor updates separate from recent-action recording; verify receipt rail still reads latest receipt outcome | Shell navigation currently emits too much launch-point-only history | Emitter alignment |
| `frontend/src/review-workspace.ts` | Change `noteActiveReviewSession()` policy to anchor-only by default; verify all existing review and planning receipts preserve correct landed targets | Session switching is low-signal; existing receipts are already close to correct | Emitter alignment |
| `frontend/src/review-workspace-action-cards.ts` | Audit receipt builders for landed resume location, handoff reuse, working-set context, and no divergent prose | Receipt builders are the canonical landed display payload for review and planning results | Emitter alignment |
| `frontend/src/review-workspace-handoffs.ts` | Verify working-set metadata remains canonical in planning and review handoffs used by continuity | Continuity should reuse structured handoff data, not infer it elsewhere | Reader and contract verification |
| `frontend/src/command-palette.ts` | Refactor Recent section to prefer outcome history; treat `storeRecentCommand()` as usage metadata only; add structured command execution outcome results | Current palette recent storage is separate and launch or invocation oriented | Reader alignment and emitter addition |
| `frontend/src/command-palette-ranking.ts` | Verify ranking still behaves correctly when recent items are sourced from landed outcome locations; update identity matching only if needed | Recent ranking should remain deterministic after recents change source | Reader alignment |
| `frontend/src/shell-working-set.ts` | Audit all working-set receipts for landed `resumeLocation`, working-set handoff completeness, and `#working-set/:id` resume behavior | Working-set mutations are already outcome-aware and should stay the strongest example of the pattern | Emitter verification |
| `frontend/src/shell-routing.ts` | Minimal or no planned logic change; reuse or expose location identity only if helpful | `ShellLocationContract` remains canonical navigation | Verification or minor support |
| `frontend/src/operator-action-cards.ts` | Change only if launch-point detail needs a secondary disclosure affordance | Card renderer should not force launch-point text back into primary continuity copy | Optional render alignment |
| `frontend/src/workflow-handoff.ts` | Change only if UX keeps launch-point context behind a details affordance | Handoff remains the structured detail surface | Optional render alignment |
| `frontend/src/surfaces/**/*` and recall follow-through modules | Find recall-side durable mutations and emit full receipt outcomes | Visible context did not include the full recall implementation, but Session 1 includes recall follow-through | Discovery and emitter addition |
| New frontend unit tests and or Playwright coverage | Add contract, reader, palette, and fallback coverage | Session 1 touches subtle browser-local behavior and needs regression protection | Test coverage |

## 6. Acceptance matrix

| Spec acceptance criterion | Delivery phase | Verifiable implementation outcome |
| --- | --- | --- |
| Operator “Since last visit” prefers landed receipt outcomes over launch labels | Phase 2 | `buildResumeAnchorsCard()` and related readers render resolved landed title and summary and use landed resume targets |
| Recent-action history reopens landed target through `outcome.resumeLocation` | Phases 2–3 | Any history or recents surface uses resolved landed target first; launch location only as fallback |
| Working-set-scoped actions preserve working-set context | Phases 1–3 | Resolved continuity uses `handoff.workingSet` first and falls back safely when working sets disappear |
| Workflow handoff summaries and continuity summaries use the same structured data | Phases 1–2 | Readers consume `outcome.card.handoff` instead of rebuilding custom prose |
| Missing or stale landed targets degrade gracefully | Phase 2 | Missing working set, session, or resource falls back safely and explicitly |
| Continuity remains calm and high-signal | Phases 2–3 | Low-signal navigation is suppressed or deprioritized; receipts and handoffs remain primary |

## 7. Open decisions

| Decision | Recommended default for Session 1 | Decider | Options | Blocking? |
| --- | --- | --- | --- | --- |
| Should review and planning session switches become receipt-bearing entries? | **No.** Keep them as anchor updates only and remove them from recent continuity history unless research shows they are independently meaningful | Product + frontend lead | anchor-only, low-signal plain history, or full receipts | Low if default accepted |
| Should command palette unify storage or keep dual storage? | **Keep dual storage with split responsibility.** `recordRecentShellAction()` becomes continuity truth; `storeRecentCommand()` becomes usage and ranking metadata only | Frontend architecture lead | full unification or split truth/ranking model | Medium |
| Should the 12-entry continuity cap change? | **Keep 12 for the initial cutover**, then revisit after outcome-first recents are live | Product + frontend lead | keep 12, raise to 18, or dynamic cap by entry kind | Low |
| Should multiple outcomes from one planning checkpoint become a receipt-group rollup? | **No new receipt grouping in Session 1.** Keep receipt outcomes plus existing baseline or grouped rollups separate | Product/UX | keep current split, grouped receipt rollup, or individual receipts only | Low |
| Should launch-point context remain inline on continuity cards? | **Move it to secondary detail, breadcrumb, or handoff treatment**, not primary headline copy | UX/design | inline, secondary detail, or hidden entirely unless degraded | Low |
| Should launch-only anchor data be migrated or reset? | **Reset via storage-key bump** | Frontend lead | hard reset or one-time migration | Low |

## 8. Risk areas and safeguards

### 8.1 Browser-local schema drift

**Risk:** old anchor and history payloads may no longer match the new outcome-aware contract.

**Safeguard:**

- bump anchor storage keys when the schema changes
- keep parsing tolerant
- treat old browser-local state as disposable

### 8.2 Duplicate continuity cards

**Risk:** the same landed outcome could appear through latest receipt, resume anchors, and recent actions simultaneously.

**Safeguard:**

- dedupe by landed resume target identity
- dedupe again by landed title and summary where necessary
- keep launch-only entries secondary

### 8.3 Broken resume targets when working sets disappear

**Risk:** continuity tries to reopen a dead working-set context and lands nowhere useful.

**Safeguard:**

- validate working-set IDs against current loaded working sets
- strip missing set scope and fall back to durable session or loop target
- if no durable target exists, fall back to operator home

### 8.4 Palette recents drift from continuity truth

**Risk:** command palette continues surfacing invocation history instead of landed outcomes.

**Safeguard:**

- separate ranking metadata from continuity truth
- source recent resume flows from recent action outcomes first

### 8.5 Hidden recall emitters missed during implementation

**Risk:** Session 1 appears complete in visible files but recall follow-through still records launch-only history.

**Safeguard:**

- perform a repo-wide search for receipt and history emitters
- explicitly scan `frontend/src/surfaces/**/*` and recall follow-through handlers

### 8.6 Over-suppressing useful navigation history

**Risk:** reducing navigation noise could remove fallback resume context users still need.

**Safeguard:**

- keep anchors as the lightweight fallback resume model
- retain session and object openings only where they remain meaningfully resumable
- validate with manual QA before broad suppression

### 8.7 Double-counting planning activity

**Risk:** receipt outcomes and baseline or grouped rollups both tell the same story in slightly different ways.

**Safeguard:**

- keep receipt cards for “what landed”
- keep grouped and baseline cards for “what changed since last visit”
- do not invent new receipt grouping until product and UX choose it

## 9. Recommended execution order

Implementation should proceed in this order:

1. add the shared continuity-resolution helper layer
2. cut over `ResumeAnchorState` and local anchor persistence
3. make recent-action dedupe landed-target-aware
4. refactor operator continuity readers in `shell-operator-cards.ts` to consume the shared helper layer
5. add degraded fallback behavior for missing working sets, sessions, and resources
6. refactor shell navigation and session-switch behavior to suppress low-signal history noise
7. refactor command-palette recents to prefer landed outcomes and return structured execution outcomes
8. audit working-set and review receipt builders for completeness
9. sweep hidden recall and follow-through emitters and any other repo-wide continuity emitters or readers
10. add regression coverage and run manual continuity and resume QA

## 10. Suggested verification scenarios

These scenarios should be used during implementation QA.

1. **Planning checkpoint → created review session**
   - execute checkpoint
   - confirm latest continuity card shows the created queue outcome
   - reopen from continuity and land in the created queue, not the source plan
2. **Enrichment apply inside active working set**
   - apply a suggestion from an active working set
   - confirm continuity shows the landed queue or outcome with working-set context preserved
   - reopen from continuity and remain inside the working-set-scoped context
3. **Working-set mutation**
   - create, focus, pin, reorder, and remove
   - confirm continuity resume target is the dedicated `#working-set/:id` session when appropriate
4. **Command-palette quick mutation**
   - create a planning session or capture loop from the palette
   - confirm palette recents and continuity history reopen the landed object or session, not a generic palette location
5. **Deleted working set fallback**
   - create a continuity entry scoped to a working set
   - delete the working set
   - confirm the continuity card degrades to a durable fallback target with explicit degraded context
6. **Low-signal navigation noise check**
   - switch review sessions and navigate between generic shell states
   - confirm meaningful receipts remain primary and generic navigation does not dominate the continuity deck
