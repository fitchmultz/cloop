# Cloop Roadmap

This is the canonical roadmap for product and interface-parity work in Cloop.

## Direction

Cloop should use AI where it provides clear leverage, while keeping the local-first,
deterministic core trustworthy. AI features should not stay trapped in a single
surface when the underlying capability is already shared.

Current product goals:

- Keep the core generative runtime centered on pi.
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
| Memory CRUD | yes | yes | yes | yes | HTTP, web, CLI, and MCP now reuse the shared `memory_management` contract for deterministic direct memory CRUD/search. |
| Semantic loop search | yes | yes | yes | yes | HTTP `/loops/search/semantic`, Inbox semantic mode, `cloop loop semantic-search`, and MCP `loop.semantic_search` now share the same `read_service` + `loops/similarity.py` contract with on-demand embedding backfill. |

## Execution Order

The next work should happen in this order so that the newly stabilized shared chat,
enrichment, review, and direct-memory contracts can propagate outward without rework.

### Phase 1 — Productize shared AI-assisted loop operations

Goal: turn the next strongest shared loop primitives into explicit operator workflows.

- Bulk enrichment across filtered loop sets.
- Saved review actions that can apply consistent duplicate/related decisions or enrichment follow-ups across a review session without transport-specific glue.

Why here:

- Relationship review and semantic search are now shared, so the next highest-leverage work is batching and session-level operator flow on top of those stabilized contracts.
- These features extend already-centralized behavior instead of creating fresh AI/runtime seams.

### Phase 2 — Add richer conversational loop refinement

Goal: move beyond one-shot actions only after shared operator workflows are stable.

- Conversational enrichment workflows that can ask follow-up clarification
  questions, collect answers, and rerun enrichment.
- Guided review flows that can step through relationship-review or enrichment queues without hiding deterministic state transitions.

Why next:

- These flows add UX and state complexity, but can now build on shared review and enrichment contracts instead of inventing new ones.

### Phase 3 — Add broader AI-native planning workflows

Goal: introduce larger multi-step assistance only after lower-level review/refinement flows are proven.

- Multi-step planning/review flows that reduce user effort without hiding
  system state or mutating loops opaquely.

Why last:

- These workflows compound transport, state, and trust concerns.
- They should sit on top of already-proven shared primitives rather than force another architectural reset.

## Immediate Next Sessions

If work is being planned session-by-session, the best short sequence is:

1. **Shared operator workflows session**
   - bulk enrichment workflows
   - saved review actions for relationship/enrichment queues
2. **Conversational refinement session**
   - conversational clarification/enrichment loops
   - guided relationship/enrichment review walkthroughs
3. **Planning workflow session**
   - multi-step planning/review flows on top of the stabilized shared contracts

That sequence gives the highest leverage while minimizing contract churn.

## Guardrails

- Do not add an AI surface to an interface unless the workflow is actually useful there.
- Prefer service-layer reuse over interface-specific prompt or tool logic.
- Treat shared execution/orchestration modules as the canonical behavior contract,
  then expose that behavior cleanly in HTTP, web, CLI, and MCP where appropriate.
- Preserve clear failure modes and deterministic escape hatches for every AI-backed workflow.
- Keep pi focused on generative runtime concerns; loop state, scheduling, storage,
  and deterministic domain logic remain Cloop-owned.
