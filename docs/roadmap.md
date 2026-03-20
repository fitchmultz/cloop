# Cloop Roadmap

This is the canonical roadmap for Cloop.

The current priority is to turn the shipped operator shell, trust surfaces, workflow handoffs, shared action-card follow-through, and new receipt rail into a world-class cross-session decision and execution workspace: sharper landed-outcome history, tighter resume cues, and deeper operational memory.

## Direction

Cloop should feel like a local-first execution OS for human + AI operational work.

Current product goals:

- Replace subsystem-first navigation with state-driven workflows.
- Make the default experience answer: what should I do now, what needs a decision, and what changed.
- Keep planning, review, chat, and enrichment outputs grounded in explicit action surfaces with previews, rationale, and rollback cues.
- Preserve deterministic local control while letting AI accelerate preparation, synthesis, and handoff.
- Reuse shared service and execution contracts across HTTP, web, CLI, and MCP instead of inventing per-surface workflow logic.
- Keep the product calm by default and deep on demand through progressive disclosure.
- Make high-frequency operator flows keyboard-fast.
- Surface provenance, assumptions, and reversibility anywhere the system proposes or executes meaningful work.

## UX Vision and Spec Set

- Experience vision: [`docs/ux/experience-vision.md`](ux/experience-vision.md)
- Shared UX principles: [`docs/ux/principles.md`](ux/principles.md)

## Execution Order

### Phase 1 — Outcome-aware continuity history

Goal: finish turning the shipped operator shell, trust surfaces, shared action-card model, redesigned review shell, richer recall-result follow-through, and new receipt rail into a crisp decide-and-execute loop that stays coherent after work lands.

1. **Cross-surface continuity history tightening**
   - Make recent-action history, working-set anchors, workflow handoffs, and operator summaries reflect the final landed outcome instead of just the launch point.
   - Keep post-action context durable across operator, review, recall, and working-set surfaces so reopening a queue shows what changed and how to roll it back.
2. **Backend-backed undo actions where rollback already exists**
   - Turn receipt rollback cues into first-class executable actions anywhere the backend already supports undo or rollback, instead of leaving all reversibility as advisory text.
   - Keep the same receipt/trust contract so reversible and irreversible outcomes remain visually consistent.

## Immediate Next Sessions

If work is being planned session-by-session, the best near-term sequence is:

1. **Continuity history session**
   - align recent actions, working-set anchors, workflow handoffs, and operator since-last summaries around the landed outcome instead of the launch point
2. **Undo action session**
   - promote rollback cues into executable undo actions anywhere the backend already supports reversal

## Delivery Model

- Keep `docs/roadmap.md` concise and ordered.
- Use linked UX specs for detailed workflows, interaction models, and contract implications.
- Remove completed roadmap items instead of marking them done.
- Update the relevant spec when implementation materially changes intended behavior.
- Land UX changes as end-to-end workflow slices once a spec is accepted, not as isolated visual polish.

## Guardrails

- Do not add UI polish without improving workflow clarity, confidence, or speed.
- Prefer state-driven UX over feature-driven navigation.
- Prefer action surfaces over narrative AI output.
- Do not reintroduce legacy plain-JS frontend paths; all operator-shell and work-surface runtime work belongs in the TypeScript/Vite frontend.
- Keep all AI recommendations grounded in real loops, memory, RAG, or explicit operator context.
- Preserve deterministic escape hatches and visible rollback cues for meaningful mutations.
- Avoid transport-specific workflow drift; shared orchestration remains the source of truth.
- Treat `make ci` as the release gate for every milestone.
