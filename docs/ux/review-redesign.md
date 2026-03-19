# Review Redesign

## Why

Review is one of Cloop’s strongest differentiators, but list-heavy review UI still risks feeling like generic triage. The redesign should make review a crisp decision workspace with clear progress, confidence, and consequences.

## Outcome

Users should feel that review is the place to make one good decision at a time, not skim a dense backlog.

## User jobs

- Understand why an item is in the queue.
- Make a decision quickly and safely.
- Apply saved actions or compare options.
- See progress, queue health, and what remains.

## Non-goals

- Flattening all review types into one generic card grid.
- Hiding advanced detail required for merge, enrichment, or clarification work.
- Turning review into a dashboard detached from action.

## UX principles applied

- One obvious next move.
- Action over narration.
- Calm by default, deep on demand.
- Trust at the point of action.

## Review model

Every review surface should make these elements visible:

1. **Why this item is here**
   - stale, duplicate candidate, blocked too long, pending clarification, etc.
2. **Decision required**
   - choose relationship, answer clarification, apply suggestion, skip, defer
3. **Impact preview**
   - what changes if the user acts
4. **Queue health**
   - items remaining, highest-risk pockets, recent decisions
5. **Saved action support**
   - reusable presets where appropriate

## Recommended layout

- **Queue rail**: compact list of remaining items with reason chips
- **Decision workspace**: primary item, side-by-side comparison when needed
- **Impact panel**: result preview, rationale, related context, rollback cues
- **Session header**: session purpose, filters, progress, health, and last refresh status

Direction decision: relationship and enrichment review should share one visual shell with specialized decision panes and shared action-card/trust primitives, so queue handling, progress, and impact rendering stay consistent across review types.

## Key workflows

### Relationship review

1. User opens saved relationship session.
2. Queue shows top candidates by confidence and urgency.
3. Primary pane shows side-by-side comparison and recommended action.
4. User confirms, dismisses, merges, or defers.
5. Session advances and preserves cursor/state.

### Enrichment review

1. User opens saved enrichment session.
2. Primary pane shows suggestion or clarification need.
3. User applies saved action, edits fields, answers clarification, or rejects.
4. Session advances and updates queue health.

### Hygiene review

1. User opens daily or weekly review.
2. Cohorts emphasize the smallest next meaningful decision, not just count totals.
3. User can launch into deeper Decide or Do surfaces as needed.

## States and edge cases

- **Empty session**: explain why it is empty and what refresh or upstream action would repopulate it.
- **Stale session filters**: show drift warning and refresh option.
- **Low-confidence candidate**: emphasize manual review requirement.
- **Non-reversible consequence**: show warning before commit.

## Contract implications

- Saved review sessions remain the canonical queue state.
- Session snapshots should expose enough reason, progress, and context metadata to power the redesigned layout.
- Suggested actions, previews, and rationale should reuse the same structured outputs targeted by AI action cards.

## Acceptance criteria

- Review surfaces explain why each item is present and what decision is required.
- Session progress and queue health are visible without leaving the review surface.
- Relationship and enrichment review both support crisp primary decisions and clear downstream consequences.
- Empty and stale session states are informative, not dead ends.

## Current implementation baseline

- The review workspace now reuses the canonical action-card renderer for planning impact cards, relationship/enrichment impact previews, cohort impact previews, and enrichment suggestion cards.
- Relationship, enrichment, and hygiene review now expose explicit why-this-is-here cues, decision-required blocks, queue-health/progress summaries, drift-aware queue rails, and consequence warnings inside one shared shell.
- Mid-range review widths now preserve queue context with a denser stacked shell: overview cards collapse to two-up and the queue rail becomes a two-column card grid above the workspace.
- Phone-width review uses horizontally scrollable mode tabs plus a horizontal queue-card strip above the decision workspace so queue context stays available without pushing the primary decision too far below the fold.
- The next roadmap slice should focus on richer action-card follow-through instead of reopening the shared review-shell structure.

## Dependencies

- [`docs/ux/operator-workspace.md`](operator-workspace.md)
- [`docs/ux/ai-action-cards.md`](ai-action-cards.md)
- [`docs/ux/workflow-handoffs.md`](workflow-handoffs.md)
- [`docs/ux/trust-surfaces.md`](trust-surfaces.md)

## Open questions

- What is the right balance between queue rail density and side-by-side detail on smaller screens?
