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
| Chat completion | yes | yes | no | no | Web chat now exposes the core backend grounding/tool controls. |
| Chat streaming | yes | yes | no | no | SSE-backed in HTTP and web. |
| Chat tool calling | yes | yes | no | no | Web can now opt into `tool_mode=llm`. |
| Chat with loop context | yes | yes | no | no | Web defaults this on. |
| Chat with memory context | yes | yes | no | no | Web defaults this on. |
| Chat with RAG context | yes | yes | no | no | Web can now opt into document grounding and scope it. |
| RAG ask | yes | yes | yes | no | Shared retrieval/generation path exists. |
| RAG ingest | yes | yes | yes | no | Embeddings-only, not generative AI. |
| Loop enrichment | yes | yes | partial | yes | CLI currently requests enrichment but does not execute the full synchronous flow. |
| Suggestions and clarifications | yes | yes | partial | no | Web + HTTP are strongest; CLI has suggestion commands but not full clarification parity. |
| Memory CRUD | yes | no | no | no | Memory exists as chat context substrate but is only directly managed over HTTP. |
| Semantic loop similarity | partial | partial | no | no | Used internally for duplicates/related context, not yet a first-class cross-surface feature. |

## Execution Order

The next work should happen in this order so that shared contracts settle before
new surfaces depend on them.

### Phase 1 — Finish parity for the remaining generative contract gaps

Goal: lock the last unstable chat/enrichment semantics before expanding into more transports.

- Decide and implement the canonical CLI behavior for `cloop loop enrich`:
  - either execute the full synchronous enrichment flow like the shared service-layer behavior
  - or keep it request-only and document that decision explicitly
- Keep the shared chat request/response contract stable now that web and HTTP both expose grounding/tool controls.
- Avoid transport-specific drift while CLI and MCP inherit the stabilized behavior.

Why first:

- the web + HTTP chat contract is now broad enough that new transports should reuse it rather than reshape it
- locking the enrich behavior now prevents CLI and MCP from growing around temporary semantics
- this phase reduces follow-on churn for every later surface

### Phase 2 — Add CLI parity for shared generative workflows

Goal: make the terminal a first-class interface for the stabilized chat/enrichment flows.

- Add `cloop chat` on top of the same pi-backed chat capability already used by HTTP/web.
- Carry over the stabilized controls from Phase 1 instead of inventing a CLI-only chat model.
- Bring `cloop loop enrich` into parity with the chosen canonical enrichment behavior.
- Keep output/rendering concerns in the CLI layer while reusing the shared orchestration underneath.

Why before MCP:

- CLI is a thinner integration than MCP and is easier to iterate on while contracts are still fresh
- the same shared orchestration can then be promoted into MCP with less duplication

### Phase 3 — Add MCP parity where agent workflows benefit most

Goal: give agent clients access to the shared AI/retrieval capabilities that are already stable elsewhere.

- Add MCP `rag.ask` so agent clients can use knowledge-grounded answering.
- Add MCP ingest support so agent workflows can refresh the knowledge base.
- Add MCP chat only if the CLI/web/HTTP contract from the earlier phases proves clean and stable enough to expose directly.
- Add MCP memory tools only after the read/write shape is proven useful and deterministic outside raw HTTP.

Why after CLI:

- MCP is another public contract surface; it should inherit stabilized behavior, not drive it
- retrieval parity is usually higher leverage for agent clients than immediate chat parity

### Phase 4 — Make memory and clarification workflows truly multi-surface

Goal: stop treating memory and clarification as HTTP/web-only workflows.

- Add direct memory management outside raw HTTP:
  - web UI memory surface
  - CLI memory commands
  - MCP memory tools (if still justified after Phase 3)
- Add clarification workflow parity so enrichment is not just triggerable from
  multiple surfaces but also reviewable and completable from them.
- Keep suggestion application/rejection behavior aligned across HTTP, web UI,
  CLI, and MCP where that surface genuinely benefits from it.

Why here:

- memory and clarification shape should build on already-stable chat/retrieval transport contracts
- these workflows are broader than one transport, so they should come after the main AI interfaces settle

### Phase 5 — Turn internal AI capabilities into explicit product features

Goal: promote the strongest existing internal AI signals into first-class features.

- Semantic loop search using existing loop embedding infrastructure.
- Bulk enrichment across filtered loop sets.
- Better duplicate/related-loop review workflows built on the current similarity machinery.

Why after parity work:

- these features are higher-level product bets and should not be built on top of moving cross-surface foundations

### Phase 6 — Add richer AI-native workflows

Goal: move beyond one-shot actions only after the foundations are stable and shared.

- Conversational enrichment workflows that can ask follow-up clarification
  questions, collect answers, and rerun enrichment.
- Multi-step planning/review flows that reduce user effort without hiding
  system state or mutating loops opaquely.

Why last:

- these flows multiply state, UX, and transport complexity
- they should reuse proven foundations instead of forcing another architectural reset

## Immediate Next Sessions

If work is being planned session-by-session, the best short sequence is:

1. **CLI generative parity session**
   - add `cloop chat`
   - finalize the canonical `cloop loop enrich` behavior in CLI
2. **MCP retrieval parity session**
   - add MCP `rag.ask`
   - add MCP ingest
3. **Memory + clarification parity session**
   - add direct memory management outside HTTP
   - align clarification review/apply flows across surfaces
4. **Productized AI features session**
   - promote semantic search / duplicate review / bulk enrichment into explicit product features

That sequence gives the highest leverage while minimizing contract churn.

## Guardrails

- Do not add an AI surface to an interface unless the workflow is actually useful there.
- Prefer service-layer reuse over interface-specific prompt or tool logic.
- Treat HTTP as the canonical behavior contract, then expose that behavior cleanly
  in web, CLI, and MCP where appropriate.
- Preserve clear failure modes and deterministic escape hatches for every AI-backed workflow.
- Keep pi focused on generative runtime concerns; loop state, scheduling, storage,
  and deterministic domain logic remain Cloop-owned.
