# Cloop Roadmap

Execution focus: collapse the continuity selector split, then remove the now-unused anchor transport before runtime chunking work.

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do now, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, handoff, and rerun.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, reversibility, and rerun semantics anywhere the system proposes or re-executes meaningful work.

## UX Vision and Spec Set

- Experience vision: [`docs/ux/experience-vision.md`](ux/experience-vision.md)
- Shared UX principles: [`docs/ux/principles.md`](ux/principles.md)
- Continuity intelligence: [`docs/ux/continuity-intelligence.md`](ux/continuity-intelligence.md)
- Undo actions: [`docs/ux/undo-actions.md`](ux/undo-actions.md)

## Execution order

### Next — Collapse the continuity selector split

Tighten the continuity model now that reopen is summary-only.

1. Keep one shared display-feed selector for fresh receipts plus durable summaries.
2. Keep one durable-only reopen/recovery selector, and remove any extra overlap between the two paths.
3. Delete dead `source === "anchor"` or other continuity-branching code that no longer survives the cutover.

### Then — Remove unused anchor transport

Delete the backend/storage/API leftovers now that the browser no longer reads or writes anchors.

1. Remove unused continuity anchor writes, snapshot payload plumbing, and storage helpers that no longer feed any frontend path.
2. Trim frontend continuity API/domain exports that only existed for anchor transport.
3. Regenerate/update tests after the contract removal so continuity stays outcome-first end to end.

### Then — Frontend shell/runtime boundary cleanup

Fix the current chunking warnings after continuity contracts settle.

1. Remove the ineffective dynamic imports around `frontend/src/surfaces/bootstrap.ts`, `loop.ts`, `next.ts`, `timer.ts`, and `render.ts`.
2. Lazy-load surfaces from real activation boundaries so the main operator bundle drops below the current warning path.
3. Keep the shell bootstrap thin and avoid reintroducing secondary entrypoints.

## Delivery model

- Keep this file short; link UX specs for acceptance detail.
- Remove finished work instead of marking it done.
- Update the relevant UX spec when behavior changes materially.
- Ship end-to-end slices (contract + storage + transport + UI), not isolated polish.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; operator shell and work surfaces stay strict TypeScript under `frontend/src/surfaces/*.ts` and shared shell modules.
- Keep AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration stays canonical.
- Treat `make ci` as the release gate for every milestone.
