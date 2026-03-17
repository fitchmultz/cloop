# Command Palette and Quick Actions

## Why

A powerful system still feels slow if common actions require repeated pointer travel and panel hunting. Cloop should support an IDE-like command model for high-frequency operator work.

## Outcome

Users can invoke one palette and quickly:

- navigate to any state or object
- capture new work
- open a saved session or working set
- execute a common mutation
- search loops, memory, and RAG context
- repeat a recent action

## User jobs

- Move faster than the visible shell permits.
- Execute high-frequency actions without leaving the keyboard.
- Jump to exact objects, queues, or workflows.
- Discover available capabilities without memorizing routes.

## Non-goals

- Replacing visible affordances for novice users.
- Stuffing every possible system command into one flat list without ranking.
- Turning the palette into a chat box.

## UX principles applied

- Keyboard is first-class.
- State over subsystem.
- One obvious next move.
- Continuity is a feature.

## Command groups

- **Navigate**: states, recent objects, working sets, saved sessions
- **Capture**: new loop, note, memory entry, quick planning seed
- **Act**: transition loop, snooze, enrich, apply saved action, execute checkpoint
- **Review**: open next decision queue, jump to stale/blocked cohort
- **Recall**: semantic search, memory search, RAG ask
- **Recent**: recently used commands and recently opened objects

## Ranking model

The palette should rank using:

- current work state
- active working set
- recent usage
- currently selected object
- deterministic relevance, not opaque guessing

## Key workflows

### Fast navigation

1. User opens palette.
2. Types a few characters.
3. Result list mixes states, sessions, and objects with clear labels.
4. Enter opens the right destination already scoped.

### Quick mutation

1. User selects one or more loops.
2. Opens palette.
3. Chooses an action such as snooze, complete, or add to working set.
4. Action runs with confirmation when needed.

### Resume recent work

1. User opens palette after returning.
2. Recent section surfaces active plan, review queue, and working set.
3. User re-enters exact context without navigating manually.

## States and edge cases

- **No results**: explain why and suggest related commands.
- **Action requires selection**: prompt to select a target or pick one from search results.
- **Potentially destructive command**: require explicit confirmation or preview.
- **Unavailable AI**: deterministic commands still work and remain ranked.

## Contract implications

- Palette actions should call shared domain/service contracts, not bespoke UI shortcuts.
- Navigation targets should rely on real IDs for sessions, loops, and working sets.
- A command registry will likely be needed for consistent keyboard exposure across the web UI and potentially the CLI/TUI in the future.

## Acceptance criteria

- Users can reach core navigation and mutation flows from one palette.
- The palette can open saved sessions and working sets directly.
- Result ranking reflects current work context.
- High-frequency operator actions are keyboard-viable end to end.

## Current implementation defaults

- The web shell exposes a global palette via the header button, `⌘K` / `Ctrl+K`, and `/`.
- Result ranking is deterministic and currently combines query match, current shell state, active working-set focus anchors, selected loops, and local recent-command history.
- Quick actions currently include loop capture, direct memory creation, planning-session creation, working-set pinning, working-set activation/focus, and selected-loop mutations (complete, drop, status transitions, snooze, enrich).
- Search currently covers local loop/object matches, saved views, saved sessions, working sets, memory search, and recall-launch queries for grounded chat/documents.
- Recent commands are browser-local for now and complement — but do not replace — the broader continuity roadmap item.

## Dependencies

- [`docs/ux/state-navigation.md`](state-navigation.md)
- [`docs/ux/working-sets.md`](working-sets.md)
- [`docs/ux/review-redesign.md`](review-redesign.md)

## Open questions

- Which commands should be globally available versus context-sensitive only?
- Should saved actions and planning checkpoints be represented as first-class palette commands or grouped under parent objects?
