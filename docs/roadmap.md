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
| Chat completion | yes | yes | no | no | Web chat currently exposes only a reduced subset of backend chat features. |
| Chat streaming | yes | yes | no | no | SSE-backed in HTTP and web. |
| Chat tool calling | yes | partial | no | no | Backend supports tool modes; web hard-codes `tool_mode=none`. |
| Chat with loop context | yes | yes | no | no | Web defaults this on. |
| Chat with memory context | yes | yes | no | no | Web defaults this on. |
| Chat with RAG context | yes | no | no | no | Backend supports it; web does not expose it. |
| RAG ask | yes | yes | yes | no | Shared retrieval/generation path exists. |
| RAG ingest | yes | yes | yes | no | Embeddings-only, not generative AI. |
| Loop enrichment | yes | yes | partial | yes | CLI currently requests enrichment but does not execute the full synchronous flow. |
| Suggestions and clarifications | yes | yes | partial | no | Web + HTTP are strongest; CLI has suggestion commands but not full clarification parity. |
| Memory CRUD | yes | no | no | no | Memory exists as chat context substrate but is only directly managed over HTTP. |
| Semantic loop similarity | partial | partial | no | no | Used internally for duplicates/related context, not yet a first-class cross-surface feature. |

## Execution Order

The next work should happen in this order so that the new pi cutover stays stable
while the missing product surfaces are filled in deliberately.

### Phase 1 — Stabilize the pi bridge cutover

Goal: make the new runtime boundary boring, observable, and easy to support.

- Harden the bridge protocol and request lifecycle:
  - confirm abort behavior is reliable
  - confirm tool-round limit behavior is explicit and tested
  - confirm startup failures are surfaced cleanly when Node, pi, or auth is missing
- Tighten bridge/history semantics:
  - reduce synthetic provider/model metadata in replayed assistant history where possible
  - document current protocol/schema assumptions clearly
- Keep operational docs honest:
  - `/health` should remain the quick truth source for bridge readiness
  - setup docs should continue to reflect the actual pi + Node prerequisites
- Treat this phase as complete only when the cutover remains green under `make ci`
  without caveats.

### Phase 2 — Reach parity for the generative features we already have

Goal: expose the existing pi-backed capabilities across the right user surfaces.

- Add `cloop chat` so the CLI can use the same pi-backed chat capability already
  available in HTTP and the web UI.
- Expose more chat controls in the web UI for capabilities the backend already supports:
  - tool mode
  - optional RAG-in-chat
  - future scoped grounding controls
- Decide and implement the canonical CLI behavior for `cloop loop enrich`:
  - either execute the full synchronous enrichment flow like HTTP and MCP
  - or keep it request-only and document that decision explicitly

### Phase 3 — Add MCP parity where agent workflows benefit most

Goal: give agent clients access to the shared AI/retrieval capabilities that are
already stable elsewhere.

- Add MCP `rag.ask` so agent clients can use knowledge-grounded answering.
- Add MCP ingest support so agent workflows can refresh the knowledge base.
- Add MCP memory tools only after the read/write shape is proven useful and
  deterministic outside raw HTTP.

### Phase 4 — Make memory and enrichment workflows truly multi-surface

Goal: stop treating memory and clarification as HTTP/web-only workflows.

- Add direct memory management outside raw HTTP:
  - web UI memory surface
  - CLI memory commands
  - MCP memory tools (if still justified after Phase 3)
- Add clarification workflow parity so enrichment is not just triggerable from
  multiple surfaces but also reviewable and completable from them.
- Keep suggestion application/rejection behavior aligned across HTTP, web UI,
  CLI, and MCP where that surface genuinely benefits from it.

### Phase 5 — Turn internal AI capabilities into explicit product features

Goal: promote the strongest existing internal AI signals into first-class features.

- Semantic loop search using existing loop embedding infrastructure.
- Bulk enrichment across filtered loop sets.
- Better duplicate/related-loop review workflows built on the current similarity machinery.

### Phase 6 — Add richer AI-native workflows

Goal: move beyond one-shot actions only after the foundations are stable and shared.

- Conversational enrichment workflows that can ask follow-up clarification
  questions, collect answers, and rerun enrichment.
- Multi-step planning/review flows that reduce user effort without hiding
  system state or mutating loops opaquely.

## Immediate Next Sessions

If work is being planned session-by-session, the best short sequence is:

1. **Bridge hardening session**
   - tighten protocol edges
   - improve failure surfacing
   - add bridge-focused tests
2. **CLI + web chat parity session**
   - add `cloop chat`
   - expose backend chat controls in the web UI
3. **MCP retrieval parity session**
   - add MCP `rag.ask`
   - add MCP ingest

That sequence gives the highest leverage with the lowest architectural risk.

## Guardrails

- Do not add an AI surface to an interface unless the workflow is actually useful there.
- Prefer service-layer reuse over interface-specific prompt or tool logic.
- Treat HTTP as the canonical behavior contract, then expose that behavior cleanly
  in web, CLI, and MCP where appropriate.
- Preserve clear failure modes and deterministic escape hatches for every AI-backed workflow.
- Keep pi focused on generative runtime concerns; loop state, scheduling, storage,
  and deterministic domain logic remain Cloop-owned.
