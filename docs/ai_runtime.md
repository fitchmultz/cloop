# AI Runtime and pi Bridge

This document defines the shipped AI runtime contract in Cloop: selector resolution, tool budgets, replay rules, streaming behavior, final payloads, embedding ownership, and health/failure semantics.

## 1) Boundary and ownership

Cloop uses a split runtime:

- **Python owns product behavior**
  - request shaping for chat, RAG, planning, and enrichment
  - loop, memory, and RAG state in SQLite
  - Python-owned tool execution and tool policy
  - HTTP, CLI, and MCP transport behavior
- **The local pi bridge owns generic model execution**
  - selector resolution through the local `pi` installation
  - provider/auth-aware model runtime setup
  - assistant turn execution and tool-loop continuation
  - bridge-level JSONL protocol handling

Canonical code locations:

- `src/cloop/llm.py`
- `src/cloop/ai_bridge/protocol.py`
- `src/cloop/ai_bridge/runtime.py`
- `src/cloop/pi_bridge/bridge.mjs`
- `src/cloop/tools.py`

Cloop does not implement provider-specific auth or billing for generative calls. It passes selector preferences to `pi`, and `pi` remains responsible for provider resolution, auth, and model execution.

## 2) Runtime prerequisites

The bridge depends on local tools, not hosted infrastructure:

- Python 3.14+
- Node 25.8.2+
- `uv`
- `pi` installed locally
- `pi` authenticated for the selectors you plan to use

Setup:

```bash
uv sync --all-groups
pnpm --dir src/cloop/pi_bridge install --frozen-lockfile
cp .env.example .env
pi --list-models
```

## 3) Selector contract

Cloop resolves selectors through ordered preferences, not one hardcoded model name.

Primary env vars:

- `CLOOP_PI_MODEL`
- `CLOOP_PI_ORGANIZER_MODEL`
- `CLOOP_PI_SELECTOR_MODE`

Default preference order:

1. `zai/glm-5.1`
2. `kimi-coding/k2p6`
3. `openai-codex/gpt-5.5`

Selector modes:

- `fallback`: ask `pi` which configured selectors are available and use the first match
- `exact`: require exactly one configured selector for each role and fail if it is unavailable

The selector contract is exposed in `/health` for both chat and organizer roles:

- `requested_selector`
- `requested_selectors`
- `resolved_selector`
- `fallback_used`
- `selector_mode`
- `error`

## 4) Bridge protocol summary

All bridge messages are JSONL objects with a shared protocol version.

Python → bridge:

- `resolve_model`
- `start`
- `tool_result`
- `abort`
- `ping`

Bridge → Python:

- `hello`
- `pong`
- `model_resolved`
- `text_delta`
- `thinking_delta`
- `tool_call`
- `tool_result`
- `done`
- `error`

Terminal bridge events are `done` and `error`.

## 5) Replay contract

### Conversation replay

Python sends request-scoped message history to the bridge. The bridge normalizes that history into pi agent messages with these rules:

- system messages are joined into one effective system prompt
- user messages are replayed as text content blocks
- assistant history preserves explicit provider/api/model/usage/stop metadata when supplied
- if assistant replay metadata is absent, replay metadata defaults to the resolved selector for that request
- tool messages preserve `tool_call_id`, tool name, and `is_error`

That keeps replay aligned with the selected runtime instead of fabricating provider metadata.

### Idempotent mutation replay

HTTP and MCP mutation retries use the shared idempotency flow and replay the prior successful response for the same key + same payload. That is a separate contract from conversation replay.

## 6) Tool-budget contract

Python resolves tool-round budgets per surface before starting bridge execution:

- `chat` → `CLOOP_PI_CHAT_MAX_TOOL_ROUNDS` (default `4`)
- `planning` → `CLOOP_PI_PLANNING_MAX_TOOL_ROUNDS` (default `2`)
- `enrichment` → `CLOOP_PI_ENRICHMENT_MAX_TOOL_ROUNDS` (default `2`)
- `rag` → `CLOOP_PI_RAG_MAX_TOOL_ROUNDS` (default `2`)
- `mutation` → `CLOOP_PI_MUTATION_MAX_TOOL_ROUNDS` (default `2`)

When the bridge exhausts `max_tool_rounds`, it emits a terminal `tool_round_limit` error with structured details including:

- `tool_rounds_used`
- `max_tool_rounds`
- `stop_reason`
- `partial_text`

Python enriches that error with surface guidance plus partial results when available.

## 7) Read-only alternate-strategy contract

Read-only generation surfaces may use one bounded alternate attempt after a retryable upstream failure:

- grounded chat on the `chat` surface
- planning generation
- enrichment suggestion generation
- RAG answer generation

Mutation flows stay single-path.

Selection order:

1. if a tool-using read-only request fails with `tool_round_limit`, retry once on the same resolved selector with `tools=[]` and `CLOOP_PI_READONLY_LOWER_BUDGET_MAX_TOOL_ROUNDS`
2. otherwise, if fallback candidates remain, retry once on the next ordered selector
3. otherwise, retry once on the same resolved selector in exact mode

Invariants:

- at most one alternate attempt
- retries stop before the first client-visible streaming event
- successful responses record `generation_strategy`, `alternate_strategy_used`, `strategy_reason`, and ordered `strategy_attempts`
- exhausted bounded strategies raise `readonly_generation_exhausted`

## 8) Streaming contract

### HTTP `/chat`

`POST /chat?stream=true` emits SSE events with these names:

- `token`
- `tool_call`
- `tool_result`
- `done`

### HTTP `/ask`

`GET /ask?stream=true` emits SSE events with these names:

- `token`
- `done`

### Shared rules

- streaming retries only happen before the first visible event
- chat streaming preserves one `tool_result` event per completed tool outcome
- the terminal `done` payload is the same final structured response body returned by the non-streaming route
- MCP `chat.complete` exposes the same grounded chat contract as non-streaming HTTP/CLI chat; it does not expose the streaming SSE surface

## 9) Final-payload contract

### Chat final payload (`ChatResponse`)

`/chat`, `cloop chat --format json`, and MCP `chat.complete` share the same final payload shape:

- `message`
- `tool_results` — ordered tool outcome payloads
- `tool_calls`
- `model`
- `metadata`
- `options`
- `context`
- `sources`
- `rerun_action`

`metadata` includes the runtime provenance fields that matter across transports:

- `latency_ms`
- `model`
- `provider`
- `api`
- `usage`
- `stop_reason`
- `requested_selector`
- `requested_selectors`
- `resolved_selector`
- `fallback_used`
- `selector_mode`
- `generation_strategy`
- `alternate_strategy_used`
- `strategy_reason`
- `strategy_attempts`

### RAG ask final payload (`AskResponse`)

`/ask`, `cloop ask`, and the `done` event from `/ask?stream=true` share this final payload shape:

- `answer`
- `chunks`
- `model`
- `sources`
- `metadata`
- `rerun_action`

The RAG `metadata` payload uses the same selector/strategy provenance fields as chat when generation runs through the bridge.

## 10) Embedding contract

Embeddings are separate from the pi generative runtime.

- chat, planning, enrichment, and RAG generation use the local pi bridge
- embeddings stay on the LiteLLM-compatible embedding path
- embedding provider resolution lives in `src/cloop/embedding_providers.py`

Primary embedding env vars:

- `CLOOP_EMBED_MODEL`
- `CLOOP_OLLAMA_API_BASE`
- `CLOOP_LMSTUDIO_API_BASE`
- `CLOOP_OPENAI_API_KEY`
- `CLOOP_OPENAI_API_BASE`
- `CLOOP_GOOGLE_API_KEY`
- `CLOOP_OPENROUTER_API_BASE`

Provider rules:

- `ollama/...` requires `CLOOP_OLLAMA_API_BASE`
- `gemini/...` and `google/...` require `CLOOP_GOOGLE_API_KEY`
- `openai/...`, `gpt-*`, and `o1-*` require `CLOOP_OPENAI_API_KEY`
- `lmstudio/...` and `openrouter/...` use their matching base-url settings when configured

Embedding credentials do not authenticate pi generative requests.

## 11) Health and failure contract

`GET /health` and `GET /healthz` report:

- `ai_backend`
- `chat_selector`
- `organizer_selector`
- `embed_model`
- `bridge_name`
- `bridge_version`
- `bridge_protocol`
- `checks.pi_bridge`

Healthy bridge characteristics:

- `checks.pi_bridge.ok == true`
- `bridge_name == "cloop-pi-bridge"`
- `bridge_protocol == 1`
- selector resolution fields are populated

Primary failure classes:

- `BridgeStartupError`
- `BridgeProcessError`
- `BridgeProtocolError`
- `BridgeTimeoutError`
- `BridgeUpstreamError`
- `ReadOnlyGenerationExhaustedError`

HTTP mapping:

- startup/process → `503 ai_backend_unavailable`
- timeout → `504 ai_backend_timeout`
- protocol → `502 ai_backend_protocol_error`
- upstream retryable → `503`
- upstream non-retryable → `502`
- exhausted read-only strategy envelope → `503 readonly_generation_exhausted`

## 12) Verification commands

Focused runtime checks:

```bash
npm test --prefix src/cloop/pi_bridge
uv run pytest tests/test_ai_bridge_runtime.py tests/test_llm.py tests/test_llm_failures.py
pi --list-models
```

Repo gates:

```bash
make check-fast
make ci
```
