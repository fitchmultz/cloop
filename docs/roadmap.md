# Cloop Roadmap

This is the canonical roadmap for product and interface-parity work in Cloop.

## Direction

Cloop should use AI where it provides clear leverage, while keeping the local-first,
deterministic core trustworthy. AI features should not stay trapped in a single
surface when the underlying capability is already shared.

Current product goals:

- Keep the core generative runtime centered on pi.
- Default pi model selectors to the user's preferred provider/model combinations when Cloop needs an explicit selector, while still allowing any pi-supported provider/model combination.
- Keep embeddings separate where that remains the best fit.
- Prefer shared service-layer implementations over surface-specific forks.
- Improve feature symmetry across HTTP, web UI, CLI, and MCP when the capability
  is genuinely useful in each interface.
- Preserve deterministic loop operations even when AI is layered on top.

## Current AI Surface

Legend:

- `yes`: available today
- `partial`: available with meaningful limitations
- `no`: missing

| Capability | HTTP API | Web UI | CLI | MCP | Notes |
| --- | --- | --- | --- | --- | --- |
| Chat completion | yes | yes | yes | yes | HTTP, CLI, and MCP now reuse the shared grounded chat execution contract. |
| Chat streaming | yes | yes | yes | no | HTTP/web use SSE; CLI streams token output directly to stdout. MCP currently exposes the non-streaming chat contract only. |
| Chat tool calling | yes | yes | yes | yes | MCP chat now supports both `tool_mode=llm` and explicit manual tools through shared execution. |
| Chat with loop context | yes | yes | yes | yes | Loop grounding now shares one chat contract across HTTP/web/CLI/MCP. |
| Chat with memory context | yes | yes | yes | yes | Memory grounding now shares one chat contract across HTTP/web/CLI/MCP. |
| Chat with RAG context | yes | yes | yes | yes | Document grounding and scope filters now flow through the same shared chat contract everywhere except streaming. |
| RAG ask | yes | yes | yes | yes | HTTP, CLI, and MCP now reuse the shared `rag_execution` contract on top of shared ask orchestration. |
| RAG ingest | yes | yes | yes | yes | HTTP, CLI, and MCP now share ingest execution and bookkeeping (`files`, `chunks`, `files_skipped`, `failed_files`). |
| Loop enrichment | yes | yes | yes | yes | Explicit enrich flows now share one synchronous orchestration contract. |
| Suggestions and clarifications | yes | yes | yes | yes | Suggestion payloads now link persisted clarification rows, and all surfaces answer existing clarification IDs through the same review contract. |
| Saved review workflows | yes | yes | yes | yes | Saved review actions plus guided cursor movement and session-preserving relationship/enrichment refinement now share `loops/review_workflows.py` across all operator surfaces. |
| Planning workflows | yes | yes | yes | yes | Checkpointed planning sessions now share `loops/planning_workflows.py` across HTTP, the Review tab, CLI, and MCP with durable execution history. |
| Memory CRUD | yes | yes | yes | yes | HTTP, web, CLI, and MCP now reuse the shared `memory_management` contract for deterministic direct memory CRUD/search. |
| Semantic loop search | yes | yes | yes | yes | HTTP `/loops/search/semantic`, Inbox semantic mode, `cloop loop semantic-search`, and MCP `loop.semantic_search` now share the same `read_service` + `loops/similarity.py` contract with on-demand embedding backfill. |

## Execution Order

The next work should happen in this order so that the newly stabilized shared planning,
chat, enrichment, review, direct-memory, and pi-selector defaults can propagate outward without rework.

### Phase 1 — Extend parity for post-planning operator loops

Goal: make the handoff from planning/review into subsequent execution even more seamless now that the shared planning substrate exposes broader deterministic operations plus rollback/provenance metadata.

- Add transport-ready affordances wherever checkpoint execution should launch the next deterministic operator surface directly.
- Tighten chat/review/planning examples around multi-step operator sessions, especially when saved review sessions become the next queue.
- Teach the web Review tab and MCP clients how to surface execution summaries, rollback cues, and created follow-up resources without bespoke workflow glue.

Why next:

- The planning substrate now covers broader deterministic operations and richer execution metadata.
- The highest remaining leverage is to help operators move from executed checkpoints into the next surface with less friction.

### Phase 2 — Harden non-reversible planning steps

Goal: reduce remaining edge cases where planning checkpoints still rely on best-effort rollback.

- Tighten the contract around non-reversible enrichment-heavy checkpoint operations.
- Consider deeper replay / rollback handling only where the underlying shared enrichment primitives can support it cleanly.
- Keep follow-up execution analytics aligned if new checkpoint kinds add more downstream resources.

Why after Phase 1:

- The current rollback/provenance substrate is strong enough for broader transport adoption.
- Remaining rollback work should happen only after the operator handoff surfaces fully exploit the current contract.

## Immediate Next Sessions

If work is being planned session-by-session, the best short sequence is:

1. **Post-planning parity session**
   - polish the handoff from executed checkpoints into the next saved review/chat operator surface using the new execution summaries and rollback metadata
2. **Non-reversible-step hardening session**
   - deepen rollback/replay handling only where enrichment-heavy checkpoint operations can support a clean shared contract

That sequence gives the highest leverage while minimizing contract churn.

## Guardrails

- Do not add an AI surface to an interface unless the workflow is actually useful there.
- Prefer service-layer reuse over interface-specific prompt or tool logic.
- Treat shared execution/orchestration modules as the canonical behavior contract,
  then expose that behavior cleanly in HTTP, web, CLI, and MCP where appropriate.
- Preserve clear failure modes and deterministic escape hatches for every AI-backed workflow.
- Keep pi focused on generative runtime concerns; loop state, scheduling, storage,
  and deterministic domain logic remain Cloop-owned.
