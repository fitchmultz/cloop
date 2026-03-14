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
| Memory CRUD | yes | yes | yes | yes | HTTP, web, CLI, and MCP now reuse the shared `memory_management` contract for deterministic direct memory CRUD/search. |
| Semantic loop search | yes | yes | yes | yes | HTTP `/loops/search/semantic`, Inbox semantic mode, `cloop loop semantic-search`, and MCP `loop.semantic_search` now share the same `read_service` + `loops/similarity.py` contract with on-demand embedding backfill. |

## Execution Order

The next work should happen in this order so that the newly stabilized shared chat,
enrichment, review, direct-memory, and pi-selector defaults can propagate outward without rework.

### Phase 1 — Add broader AI-native planning workflows

Goal: introduce larger multi-step assistance now that conversational refinement on top of saved sessions is in place.

- Multi-step planning/review flows that reduce user effort without hiding
  system state or mutating loops opaquely.
- Higher-level workflow generation that can orchestrate deterministic loop tools while still exposing state, checkpoints, and rollback-friendly results.

Why first now:

- Saved review sessions now support guided cursor movement plus clarification-answer-and-rerun refinement across HTTP, web, CLI, and MCP.
- The next leverage point is building larger workflow assistance on top of those proven review/refinement primitives rather than reopening transport-level churn.

### Phase 2 — Deepen transport ergonomics for shared AI workflows

Goal: polish the newest shared review/chat/RAG capabilities after the next higher-leverage planning workflows land.

- Better guided web UI affordances on top of saved review sessions and multi-step planning flows.
- Richer MCP ergonomics and examples for the newest shared review and grounded-chat operators.
- Documentation/examples that make the shared pi-selector and review-workflow model obvious for operators.

Why next:

- This work benefits from stabilized workflow primitives first.
- It is easier to polish transports after the next shared orchestration contracts settle.

## Immediate Next Sessions

If work is being planned session-by-session, the best short sequence is:

1. **Planning workflow session**
   - multi-step planning/review flows on top of the stabilized shared review contracts
   - checkpointed AI assistance that still exposes deterministic loop state transitions
2. **Transport polish session**
   - deeper web UX polish, richer MCP ergonomics, and docs/examples for the newest shared review operators

That sequence gives the highest leverage while minimizing contract churn.

## Guardrails

- Do not add an AI surface to an interface unless the workflow is actually useful there.
- Prefer service-layer reuse over interface-specific prompt or tool logic.
- Treat shared execution/orchestration modules as the canonical behavior contract,
  then expose that behavior cleanly in HTTP, web, CLI, and MCP where appropriate.
- Preserve clear failure modes and deterministic escape hatches for every AI-backed workflow.
- Keep pi focused on generative runtime concerns; loop state, scheduling, storage,
  and deterministic domain logic remain Cloop-owned.
