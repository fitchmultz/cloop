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
| Suggestions and clarifications | yes | yes | partial | no | Web + HTTP are strongest; CLI has suggestion commands but not full clarification parity. |
| Memory CRUD | yes | no | no | no | Memory exists as chat context substrate but is only directly managed over HTTP. |
| Semantic loop similarity | partial | partial | no | no | Used internally for duplicates/related context, not yet a first-class cross-surface feature. |

## Execution Order

The next work should happen in this order so that the newly stabilized shared chat
and enrichment contracts can propagate outward without rework.

### Phase 1 — Make clarification and suggestion workflows truly multi-surface

Goal: stop treating enrichment as triggerable everywhere but reviewable only in a
subset of surfaces.

- Add clarification review/completion flows outside HTTP/web.
- Align suggestion listing, inspection, apply, and reject behavior across CLI and MCP.
- Keep enrichment-result payloads and follow-up actions grounded in the same loop
  suggestion data model instead of transport-specific wrappers.

Why first:

- The explicit enrich trigger contract is now stable, so the next churn-reducing
  step is to stabilize what users can do with the resulting suggestions.
- Clarification parity depends on the enrichment payload shape that is now settled.

### Phase 2 — Add direct memory management beyond raw HTTP

Goal: expose memory as a first-class capability in the interfaces where grounded chat
already benefits from it.

- Add a web UI memory surface.
- Add CLI memory commands with deterministic CRUD semantics.
- Add MCP memory tools only if the read/write contract remains narrow and useful.
- Keep chat grounding on top of shared memory storage rather than introducing
  transport-owned memory state.

Why here:

- Memory already matters for grounded chat, but direct management should come after
  the main chat/retrieval contracts are settled in every transport that needs them.
- This sequencing avoids adding more moving parts before broader suggestion/memory UX parity is done.

### Phase 3 — Turn internal AI capabilities into explicit product features

Goal: promote the strongest existing internal AI signals into first-class features.

- Semantic loop search using the existing loop embedding infrastructure.
- Bulk enrichment across filtered loop sets.
- Better duplicate/related-loop review workflows built on the current similarity machinery.

Why after parity work:

- These are product bets built on top of already-shared infrastructure.
- They should not land while core transport contracts are still expanding.

### Phase 4 — Add richer AI-native workflows

Goal: move beyond one-shot actions only after the foundations are stable and shared.

- Conversational enrichment workflows that can ask follow-up clarification
  questions, collect answers, and rerun enrichment.
- Multi-step planning/review flows that reduce user effort without hiding
  system state or mutating loops opaquely.

Why last:

- These flows multiply state, UX, and transport complexity.
- They should reuse proven foundations instead of forcing another architectural reset.

## Immediate Next Sessions

If work is being planned session-by-session, the best short sequence is:

1. **Clarification + suggestion parity session**
   - add CLI/MCP clarification review flows
   - align suggestion list/show/apply/reject behavior everywhere it matters
2. **Memory management parity session**
   - add web UI memory management
   - add CLI memory commands
   - add MCP memory tools only if the contract stays narrow and deterministic
3. **Productized AI features session**
   - semantic search
   - duplicate/related review improvements
   - bulk enrichment workflows
4. **Richer AI-native workflows session**
   - conversational clarification/enrichment loops
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
