# AI Runtime and pi Bridge

This document explains the generative runtime boundary in Cloop: what stays in Python, what runs through the local Node-based pi bridge, how the JSONL protocol works, and what to verify when the bridge is unhealthy.

## 1) Boundary and ownership

Cloop uses a **split runtime** for AI features:

- **Python owns product/domain behavior**
  - request shaping for chat/RAG/enrichment
  - loop, memory, and RAG state
  - tool execution policy and tool implementations
  - HTTP/CLI/MCP transport behavior
- **The local pi bridge owns generic model execution**
  - model selection through pi
  - provider/auth-aware runtime setup
  - assistant turn execution and tool-loop continuation
  - text/thinking delta streaming

Canonical code locations:

- Python facade: `src/cloop/llm.py`
- Bridge protocol: `src/cloop/ai_bridge/protocol.py`
- Bridge runtime/process manager: `src/cloop/ai_bridge/runtime.py`
- Node bridge implementation: `src/cloop/pi_bridge/bridge.mjs`
- Python-owned tool definitions: `src/cloop/tools.py`

This is an intentional boundary: Cloop reuses pi for generic generative plumbing, but keeps loop lifecycle, SQLite persistence, RAG retrieval, and MCP semantics in Python.

Cloop does not implement provider-specific auth or billing policy for generative calls.
It sends ordered selector preferences from `CLOOP_PI_MODEL` and
`CLOOP_PI_ORGANIZER_MODEL` to the local bridge, the bridge resolves those preferences
against pi's available-model registry, and pi remains responsible for provider resolution,
auth, and runtime behavior.

## 2) Runtime prerequisites

The bridge depends on local runtime prerequisites, not hosted infrastructure:

- Python 3.14+
- Node 25.8.1+
- `uv`
- `pi` installed locally
- `pi` authenticated/configured for the model selectors you plan to use

Setup commands:

```bash
uv sync --all-groups --all-extras
pnpm --dir src/cloop/pi_bridge install --frozen-lockfile
cp .env.example .env
```

Before blaming Cloop, confirm pi can actually see the configured model selectors:

```bash
pi --list-models
```

The project defaults both selector lists to the ordered preference chain
`zai/glm-5`, `kimi-coding/k2p5`, `openai-codex/gpt-5.4` in `settings.py` / `.env.example`.
In the default `CLOOP_PI_SELECTOR_MODE=fallback`, Cloop asks pi which selectors are
available and resolves to the first available match before request execution.
If you need strict pinning, set `CLOOP_PI_SELECTOR_MODE=exact` and configure exactly one
selector for each env var; in that mode unavailable selectors still fail hard by design.

## 3) Bridge process lifecycle

At runtime, Python starts one long-lived subprocess using the command resolved from `Settings.pi_bridge_command()`.

Startup flow:

1. Python launches the Node bridge process.
2. The bridge immediately emits a `hello` handshake line.
3. Python validates protocol compatibility.
4. Python keeps the subprocess alive and multiplexes per-request sessions by `request_id`.
5. On application shutdown, Python terminates the bridge runtime.

Key stabilization expectations:

- importing `src/cloop/pi_bridge/bridge.mjs` must **not** start the bridge
- startup failures must surface as typed bridge errors
- malformed JSONL or protocol mismatches must surface as protocol errors
- unfinished requests must be abortable from Python

## 4) JSONL protocol shape

All messages are JSON objects with a shared `protocol` version.

### Python -> bridge

- `resolve_model`
  - `request_id`
  - `selectors`
  - `selector_mode`
- `start`
  - `request_id`
  - `model`
  - `messages`
  - `thinking_level`
  - `timeout_ms`
  - `max_tool_rounds`
  - `tools`
- `tool_result`
  - `request_id`
  - `tool_call_id`
  - `payload`
  - `is_error`
- `abort`
  - `request_id`
- `ping`
  - `request_id`

### Bridge -> Python

- `hello`
  - bridge name/version handshake
- `pong`
  - ping response for readiness checks
- `model_resolved`
  - selector-resolution result before request execution
- `text_delta`
  - incremental assistant output
- `thinking_delta`
  - incremental reasoning/thinking text when exposed by pi
- `tool_call`
  - request for Python-owned tool execution
- `tool_result`
  - bridge echo/report of completed tool execution details
- `done`
  - terminal success event
- `error`
  - terminal typed failure event

Terminal events are `done` and `error`.

## 5) Conversation replay rules

Python sends a request-scoped message history to the bridge. The bridge normalizes that history into pi agent messages.

Phase-1 hardening rules:

- system messages are joined into one effective system prompt
- user messages are replayed as text content blocks
- assistant history preserves explicit provider/api/model/usage/stop metadata when supplied
- if assistant replay metadata is absent, the bridge defaults replay metadata to the currently selected model instead of hardcoding synthetic OpenAI values
- tool messages preserve `tool_call_id`, tool name, and `is_error`

That keeps replay behavior closer to the actual request model and avoids misleading fake provider metadata.

## 6) Supported tool-schema subset

Cloop tool definitions are authored in Python and translated into pi parameter types inside `bridge.mjs`.

Supported JSON Schema subset:

- `type: string`
- `type: string` + `enum`
- `type: integer`
- `type: number`
- `type: boolean`
- `type: array`
- `type: object`
  - `properties`
  - `required`
  - `additionalProperties`
- descriptive fields such as `description`
- numeric bounds such as `minimum` / `maximum`
- array bounds such as `minItems` / `maxItems`
- `default`

Out of scope for the current bridge translation layer:

- advanced schema composition (`oneOf`, `anyOf`, `allOf`)
- conditional schemas
- pattern-based object keys
- arbitrary custom validators from JSON Schema drafts

If a tool schema needs more than this subset, update the translation layer deliberately instead of smuggling unsupported structure through.

## 7) Failure semantics

Bridge/runtime failures are surfaced as typed Python exceptions and then mapped into the shared app error contract.

Primary failure classes:

- `BridgeStartupError`
  - missing Node executable
  - bridge process exits before handshake
  - handshake never arrives
- `BridgeProcessError`
  - subprocess disappears or becomes unwritable during use
- `BridgeProtocolError`
  - malformed JSONL
  - missing `request_id`
  - protocol mismatch
  - invalid event shape
- `BridgeTimeoutError`
  - startup ping/request timeouts
- `BridgeUpstreamError`
  - bridge-reported model/provider failure
  - includes bridge-provided `code` and `retryable`

HTTP mapping:

- startup/process -> `503 ai_backend_unavailable`
- timeout -> `504 ai_backend_timeout`
- protocol -> `502 ai_backend_protocol_error`
- upstream retryable -> `503`
- upstream non-retryable -> `502`

## 8) Tool-loop budgets, exhaustion, and abort behavior

Cloop keeps Python in control of tool execution and loop policy.

Important request controls:

- `timeout_ms`
- `max_tool_rounds`

Python now resolves `max_tool_rounds` per surface before sending the request to the bridge:

- `chat` → `CLOOP_PI_CHAT_MAX_TOOL_ROUNDS` (default `4`)
- `planning` → `CLOOP_PI_PLANNING_MAX_TOOL_ROUNDS` (default `2`)
- `enrichment` → `CLOOP_PI_ENRICHMENT_MAX_TOOL_ROUNDS` (default `2`)
- `rag` → `CLOOP_PI_RAG_MAX_TOOL_ROUNDS` (default `2`)
- `mutation` → `CLOOP_PI_MUTATION_MAX_TOOL_ROUNDS` (default `2`)

That keeps advisory/read-only flows flexible enough for bounded multi-step tool behavior without treating mutation-heavy paths as open-ended loops.

Phase-1 hardening behavior:

- when a request exceeds `timeout_ms`, the bridge aborts the agent and emits a terminal timeout error
- when tool iterations exceed `max_tool_rounds`, the bridge aborts and emits a terminal `tool_round_limit` error
- streaming still emits one `tool_result` event per completed tool outcome
- final chat responses now preserve ordered `tool_results`; `tool_result` remains only as a transitional first-result alias
- `tool_round_limit` now carries structured details including `tool_rounds_used`, `max_tool_rounds`, `stop_reason`, and `partial_text`
- Python enriches `tool_round_limit` with surface-specific guidance plus `partial_results.text`, `partial_results.tool_calls`, and `partial_results.tool_results`
- when Python finishes consuming a session without a terminal success event, it aborts the in-flight bridge request before closing the session

## 9) Health endpoint expectations

`GET /health` and `GET /healthz` report bridge readiness alongside database status.

Relevant fields:

- `ai_backend`
- `chat_selector`
  - `requested_selector`
  - `requested_selectors`
  - `resolved_selector`
  - `fallback_used`
  - `selector_mode`
  - `error`
- `organizer_selector`
  - `requested_selector`
  - `requested_selectors`
  - `resolved_selector`
  - `fallback_used`
  - `selector_mode`
  - `error`
- `embed_model`
- `bridge_name`
- `bridge_version`
- `bridge_protocol`
- `checks.pi_bridge`

Healthy example characteristics:

- `checks.pi_bridge.ok == true`
- `bridge_name == "cloop-pi-bridge"`
- `bridge_protocol == 1`
- `chat_selector.resolved_selector` is populated
- non-negative `checks.pi_bridge.latency_ms`

If `checks.pi_bridge.ok` is false, the selector `error` fields and `checks.pi_bridge.error`
should be enough to tell whether the failure is startup, process, auth/model availability,
or protocol related.

## 10) Verification commands

Fast focused checks for bridge work:

```bash
npm test --prefix src/cloop/pi_bridge
uv run pytest tests/test_ai_bridge_runtime.py tests/test_llm.py tests/test_llm_failures.py
```

Full repo gates:

```bash
make check-fast
make ci
```

Manual smoke checks:

```bash
uv run uvicorn cloop.main:app --reload
open http://127.0.0.1:8000/health
pi --list-models
```
