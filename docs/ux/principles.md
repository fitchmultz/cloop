# UX Principles

## Why

These principles define the interaction rules for the next generation of Cloop so individual epics do not drift into disconnected screen redesigns.

## Principles

### 1. State over subsystem

Organize the experience around user state:

- Capture
- Do
- Decide
- Plan
- Review
- Recall

Do not make users think first about internal subsystems such as loops, planning, review workflows, chat, memory, or RAG.

### 2. One obvious next move

Every meaningful screen should answer:

- what matters here
- what action is primary
- what should happen next

If a user finishes a task and has to infer where to go, the UI is incomplete.

### 3. Action over narration

AI should produce structured action surfaces whenever possible:

- recommendation
- rationale
- preview
- execute / edit / defer / reject
- rollback cues

Narrative text is supporting context, not the main deliverable.

### 4. Calm by default, deep on demand

Default views should surface only the highest-signal information:

- status
- reason it matters
- primary action

Metadata, raw payloads, assumptions, and diagnostics should be available through progressive disclosure instead of always-on density.

### 5. Continuity is a feature

Users should not repeatedly rebuild context. Plans, review sessions, working sets, and recent actions should preserve place and resume naturally.

### 6. Trust at the point of action

Whenever the system proposes or performs meaningful work, the UI should surface:

- source context used
- whether the result was deterministic or AI-generated
- assumptions
- what changed
- whether the result is reversible

### 7. Shared contract, local ergonomics

HTTP, web UI, CLI, and MCP should share workflow semantics and payload contracts while expressing them with interface-appropriate ergonomics.

### 8. Keyboard is first-class

High-frequency operator flows must be fast from the keyboard. Command palette, shortcuts, and repeatable actions are part of the core UX, not afterthoughts.

### 9. Workflow handoffs beat tab jumping

The product should move users directly from one real workflow to the next instead of requiring navigation back through generic tabs or landing pages.

### 10. Human authority, AI acceleration

AI can prepare, summarize, suggest, and queue work. Humans remain the decision-makers for consequential actions unless the system is explicitly configured otherwise.

## Implications for implementation

- Prefer unified operator surfaces over proliferating specialized pages.
- Prefer saved sessions, working sets, and action cards over ad-hoc client-only state.
- Prefer explicit entry/exit states, empty states, stale states, and error states in every spec.
- Prefer reuse of existing shared backend contracts before inventing new frontend-only models.

## Spec checklist

Every major UX spec should explicitly describe:

- user jobs
- primary workflow
- empty/loading/error/stale states
- contract implications
- acceptance criteria
- dependencies on prior UX epics
