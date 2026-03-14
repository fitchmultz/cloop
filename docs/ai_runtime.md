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
It passes the configured `CLOOP_PI_MODEL` and `CLOOP_PI_ORGANIZER_MODEL` selector strings
through to pi, and pi remains responsible for provider resolution, auth, and runtime behavior.

## 2) Runtime prerequisites

The bridge depends on local runtime prerequisites, not hosted infrastructure:

- Python 3.14+
- Node 20+
- `uv`
- `pi` installed locally
- `pi` authenticated/configured for the model selectors you plan to use

Setup commands:

```bash
uv sync --all-groups --all-extras
npm ci --prefix src/cloop/pi_bridge
cp .env.example .env
```

Before blaming Cloop, confirm pi can actually see the configured model selectors:

```bash
pi --list-models
```

The project defaults both selectors to `zai/glm-5` in `settings.py` / `.env.example` today,
but users may point them at any selector that pi reports as available.
If `CLOOP_PI_MODEL` or `CLOOP_PI_ORGANIZER_MODEL` is not available in that list for your current auth/config, bridge startup or request execution will fail by design.

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

## 8) Tool-loop limits and abort behavior

Cloop keeps Python in control of tool execution and loop policy.

Important request controls:

- `timeout_ms`
- `max_tool_rounds`

Phase-1 hardening behavior:

- when a request exceeds `timeout_ms`, the bridge aborts the agent and emits a terminal timeout error
- when tool iterations exceed `max_tool_rounds`, the bridge aborts and emits a terminal `tool_round_limit` error
- when Python finishes consuming a session without a terminal success event, it aborts the in-flight bridge request before closing the session

## 9) Health endpoint expectations

`GET /health` and `GET /healthz` report bridge readiness alongside database status.

Relevant fields:

- `ai_backend`
- `chat_model`
- `organizer_model`
- `embed_model`
- `bridge_name`
- `bridge_version`
- `bridge_protocol`
- `checks.pi_bridge`

Healthy example characteristics:

- `checks.pi_bridge.ok == true`
- `bridge_name == "cloop-pi-bridge"`
- `bridge_protocol == 1`
- non-negative `checks.pi_bridge.latency_ms`

If `checks.pi_bridge.ok` is false, the `error` field should be enough to tell whether the failure is startup, process, auth/model availability, or protocol related.

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
