# Trust Surfaces

## Why

Cloop mixes deterministic state transitions, AI recommendations, saved queues, and planning handoffs. That combination is powerful only if users can quickly judge whether the system is using the right context, making the right assumptions, and changing the right things.

## Outcome

Trust information appears exactly where the user needs it, not buried in logs or raw payloads.

## User jobs

- Understand whether a result is grounded and credible.
- See what context influenced a recommendation.
- Know whether an action is reversible.
- Spot stale or assumption-heavy output before acting.

## Non-goals

- Overwhelming every screen with debug detail.
- Hiding uncertainty behind polished copy.
- Reducing trust to a single opaque confidence number.

## UX principles applied

- Trust at the point of action.
- Action over narration.
- Calm by default, deep on demand.
- Human authority, AI acceleration.

## Trust elements

Where relevant, the UI should expose:

- **Source context used**: loops, memory, RAG, saved session scope, query
- **Generation type**: deterministic, AI-assisted, or mixed
- **Assumptions**: unresolved assumptions that influenced output
- **Staleness**: whether the underlying state changed since generation
- **Reversibility**: rollback supported, undo snapshot kept, or non-reversible
- **Change summary**: what will or did change

## Recommended UI primitives

- provenance chips
- assumption blocks
- stale-state banners
- before/after previews
- rollback badges
- “why this is here” reason labels
- executed-vs-recommended distinction

## Key workflows

### Before execution

Action cards and review decisions should show:

- grounding sources
- assumptions
- target objects
- reversibility

### After execution

Result surfaces should show:

- what changed
- what was created
- rollback support
- next-step launch surface

### On stale output

If a plan, queue, or recommendation is outdated:

- make drift visible
- show what changed if known
- offer refresh/regenerate
- avoid implying the stale recommendation is still authoritative

## States and edge cases

- **No AI context used**: show deterministic-only provenance simply.
- **Mixed deterministic + AI flow**: separate what was proposed from what was executed.
- **Irreversible action**: use explicit language, not subtle iconography alone.
- **Provider unavailable**: explain degraded mode without collapsing deterministic functionality.

## Contract implications

- Shared outputs should carry provenance and reversibility fields in structured form.
- Existing planning execution metadata is a strong base but should not remain planning-only.
- Review, chat, and other recommendation-heavy flows should expose consistent trust metadata.

## Acceptance criteria

- Users can identify context source, assumption load, and rollback status before acting on important recommendations.
- Executed results clearly distinguish recommendation from committed state.
- Drift or stale-state warnings are visible when prior AI output may no longer be trustworthy.
- Deterministic degraded mode remains understandable when AI dependencies are unavailable.

## Dependencies

- [`docs/ux/principles.md`](principles.md)
- [`docs/ux/ai-action-cards.md`](ai-action-cards.md)
- [`docs/ux/workflow-handoffs.md`](workflow-handoffs.md)

## Open questions

- Which trust signals deserve permanent visibility versus disclosure behind a details affordance?
- How should the UI summarize mixed provenance when one result uses loops, memory, and RAG together?
