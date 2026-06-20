# Cloop Reference

Detailed command, server, web UI, configuration, webhook, and MCP reference for Cloop. Start with the outcome-first [README](../README.md) if you are evaluating the project for the first time.

## CLI Reference

### Chat Commands

```bash
# One-shot chat
cloop chat <prompt> [--format text|json]

# Add loop + memory grounding
cloop chat <prompt> --include-loop-context --include-memory-context

# Add document grounding
cloop chat <prompt> --include-rag-context [--rag-k N] [--rag-scope SCOPE]

# Stream token output
cloop chat <prompt> --stream

# Continue from a transcript file
cloop chat [<prompt>] --messages-file transcript.json

# Read the prompt from stdin explicitly
printf 'What should I do next?\n' | cloop chat -

# Manual tool call
cloop chat <prompt> --tool TOOL_NAME [--tool-arg KEY=VALUE ...]
```

Notes:
- `cloop chat` uses the same request/response model as the HTTP `/chat` endpoint.
- `--format text` is the default for conversational use; `--format json` emits the full structured response payload.
- `--tool` implies manual tool mode; otherwise CLI chat defaults to `tool_mode=none` unless you pass `--tool-mode` explicitly.
- Memory categories include `preference`, `pattern`, `person`, `event`, `context`, `commitment`, and `fact`.

### Memory Commands

```bash
# List memory entries
cloop memory list [--category CATEGORY] [--source SOURCE] [--min-priority N] [--cursor CURSOR] [--format json|table]

# Search memory entries by key/content text
cloop memory search <query> [--category CATEGORY] [--source SOURCE] [--min-priority N] [--cursor CURSOR] [--format json|table]

# Fetch one memory entry
cloop memory get <id> [--format json|table]

# Create a memory entry
cloop memory create <content> [--key KEY] [--category CATEGORY] [--priority N] [--source SOURCE] [--metadata-json JSON] [--format json|table]

# Update a memory entry
cloop memory update <id> [--key KEY | --clear-key] [--content TEXT] [--category CATEGORY] [--priority N] [--source SOURCE] [--metadata-json JSON] [--format json|table]

# Delete a memory entry
cloop memory delete <id> [--format json|table]
```

Notes:
- `cloop memory *` reuses the shared `src/cloop/memory_management.py` contract rather than talking to storage directly.
- Updates preserve field presence, so `--clear-key` explicitly clears the nullable key instead of silently ignoring it.
- `--metadata-json` must be a JSON object.

### Continuity Diagnostics Commands

```bash
# Inspect the first page of delivery decisions
cloop continuity delivery-decisions [--channel all|push] [--limit N] [--cursor CURSOR] [--format json|table]

# Focus on push sendability with the shared bounded scan contract
cloop continuity delivery-decisions --channel push --limit 5

# Continue from a prior opaque cursor
cloop continuity delivery-decisions --cursor <opaque-cursor>
```

Notes:
- `cloop continuity delivery-decisions` reuses the shared `read_continuity_delivery_inspection(...)` contract used by HTTP and MCP.
- `--cursor` is an opaque continuation token; do not parse or edit it.
- `--limit` is the requested sendable-decision target, even when push diagnostics inspect additional non-sendable rows inside the bounded scan budget.

### Loop Lifecycle Commands

Full loop lifecycle management from the terminal:

```bash
# Get a loop by ID
cloop loop get <id> [--format json|table]

# List loops with filters
cloop loop list [--status STATUS] [--tag TAG] [--limit N] [--offset N] [--format json|table]
# Status options: inbox, actionable, blocked, scheduled, completed, dropped, open (default), all

# Search loops by DSL/text filters
cloop loop search <query> [--limit N] [--offset N] [--format json|table]

# Search loops by semantic similarity
cloop loop semantic-search <query> [--status STATUS] [--limit N] [--offset N] [--min-score FLOAT] [--format json|table]

# Update loop fields
cloop loop update <id> [OPTIONS] [--format json|table]
  --title TEXT              Update title
  --summary TEXT            Update summary
  --next-action TEXT        Update next action
  --due-at ISO8601          Update due date
  --snooze-until ISO8601    Update snooze time
  --time-minutes N          Estimated time
  --activation-energy N     0-3 scale
  --urgency FLOAT           0.0-1.0
  --importance FLOAT        0.0-1.0
  --project TEXT            Project name
  --blocked-reason TEXT     Reason for blocked status
  --tags TAGS               Comma-separated tags (clears existing)

# Transition loop status
cloop loop status <id> <status> [--note TEXT] [--format json|table]
# Status options: inbox, actionable, blocked, scheduled, completed, dropped

# Close a loop (completed or dropped)
cloop loop close <id> [--dropped] [--note TEXT] [--format json|table]

# Run AI enrichment synchronously and return the updated loop + suggestion metadata
cloop loop enrich <id> [--format json|table]

# Preview or run bulk enrichment across a filtered loop set
cloop loop bulk enrich --query "status:open" [--dry-run] [--limit 25] [--yes] [--format json|table]

# Snooze a loop
cloop loop snooze <id> <duration> [--format json|table]
# Duration examples: 30m, 1h, 2d, 1w, or ISO8601 timestamp

# Review duplicate/related candidates for one loop
cloop loop relationship review --loop <id> [--status open|all|inbox|actionable|blocked|scheduled|completed|dropped]

# List loops with pending relationship-review work
cloop loop relationship queue [--kind all|duplicate|related] [--status open|all|...]

# Confirm or dismiss a relationship decision
cloop loop relationship confirm --loop <id> --candidate <id> --type related|duplicate
cloop loop relationship dismiss --loop <id> --candidate <id> --type related|duplicate

# Save reusable relationship-review actions and filtered sessions
cloop review relationship-action create --name dismiss-suggested --action dismiss --relationship-type suggested
cloop review relationship-session create --name duplicate-pass --query "status:open" --kind duplicate
cloop review relationship-session apply-action --session 1 --loop 10 --candidate 11 --candidate-type duplicate --action-id 2
```

Notes:
- `cloop loop semantic-search` returns ranked loop payloads plus `semantic_score` and indexing metadata in JSON mode.
- Semantic search backfills missing or stale loop embeddings on demand, so older loops become searchable without a one-off migration step.
- `cloop loop relationship *` reuses the shared semantic similarity + relationship review contract, so duplicate/related classification and review-state persistence stay aligned with HTTP, web, and MCP.
- `cloop loop bulk enrich` reuses the shared enrichment orchestration contract, so filtered target selection, result envelopes, and follow-up suggestion/clarification behavior stay aligned with HTTP, web, and MCP.

### Utility Commands

```bash
# List all tags in use
cloop tags [--format json|table]

# List all projects
cloop projects [--format json|table]

# Review enrichment suggestions
cloop suggestion list [--loop-id ID] [--pending] [--format json|table]
cloop suggestion show <suggestion-id> [--format json|table]
cloop suggestion apply <suggestion-id> [--fields title,tags] [--format json|table]
cloop suggestion reject <suggestion-id> [--format json|table]

# Review and answer clarification questions
cloop clarification list --loop-id <loop-id> [--format json|table]
cloop clarification answer <clarification-id> --loop-id <loop-id> --answer "Friday"
cloop clarification answer-many --loop-id <loop-id> --item 12=Friday --item 13=Finance
cloop clarification refine --loop-id <loop-id> --item 12=Friday --item 13=Finance

# Save reusable enrichment-review actions and filtered sessions
cloop review enrichment-action create --name apply-title --action apply --fields title
cloop review enrichment-session create --name follow-up-pass --query "status:open" --pending-kind all
cloop review enrichment-session move --session 1 --direction next
cloop review enrichment-session apply-action --session 1 --suggestion 15 --action-id 3
cloop review enrichment-session answer-clarifications --session 1 --loop 10 --item 21=Friday

# Guided relationship-review sessions
cloop review relationship-session create --name duplicate-pass --query "status:open" --kind duplicate
cloop review relationship-session move --session 2 --direction next

# Checkpointed planning sessions
cloop plan session create --name weekly-reset --prompt "Build a checkpointed plan for my open launch work" --query "status:open"
cloop plan session execute --session 3
cloop plan session refresh --session 3

# Export loops
cloop export [--output FILE] [--format json|table]
# Writes to stdout if no --output specified

# Import loops
cloop import [--file FILE] [--format json|table]
# Reads from stdin if no --file specified
```

### Planning and Review Playbooks

These shared workflows are defaults, not mandatory scripts. They are meant to compose with each other instead of living in one transport only. They all inherit the same pi selector defaults from `CLOOP_PI_MODEL` / `CLOOP_PI_ORGANIZER_MODEL`, so planning, review, and grounded chat stay on one configured generative runtime unless you intentionally change the selectors.

Required invariants:
- deterministic checkpoints only run after their prerequisites exist
- saved review sessions remain explicit operator handoff points
- transports preserve execution summaries, follow-up resources, launch surfaces, and rollback cues even if prompt phrasing or selector choice changes

**Checkpointed planning via CLI (common default):**
```bash
# Create a durable plan grounded in current launch work
cloop plan session create \
  --name weekly-launch-reset \
  --prompt "Build a checkpointed plan for my open launch work" \
  --query "project:launch status:open"

# Inspect, execute one checkpoint, then refresh if the loop set changed
cloop plan session get --session 1
cloop plan session execute --session 1
cloop plan session refresh --session 1

# Execution payloads include execution.summary, resource_change_summary,
# follow_up_resources, launch_surfaces, rollback_cues, and undo_action so
# operators can inspect what changed, what to open next, and what can be reversed.
```

Planning checkpoints may reuse broader deterministic primitives when the
shared services already own them: query-bulk loop updates/close/snooze steps,
saved review-session creation, saved-view creation/update, and template capture
from existing loops.

**Saved review queues via CLI (common default):**
```bash
# Preserve duplicate review work across sessions
cloop review relationship-session create \
  --name launch-duplicates \
  --query "project:launch status:open" \
  --kind duplicate

# Preserve enrichment follow-up work and answer clarifications in-session
cloop review enrichment-session create \
  --name launch-follow-ups \
  --query "project:launch status:open" \
  --pending-kind all
cloop review enrichment-session answer-clarifications \
  --session 2 \
  --loop 14 \
  --item 31="Need budget by Friday"
```

**HTTP workflow sketch (one valid path):**
```bash
# Create a planning session
curl -X POST http://127.0.0.1:8000/loops/planning/sessions \
  -H 'content-type: application/json' \
  -d '{
    "name": "weekly-launch-reset",
    "prompt": "Build a checkpointed plan for my open launch work",
    "query": "project:launch status:open",
    "include_memory_context": true,
    "include_rag_context": false
  }'

# Execute the current checkpoint
curl -X POST http://127.0.0.1:8000/loops/planning/sessions/1/execute
```

**MCP operator pattern (good default, not the only valid sequence):**
- `plan.session.create` → generate the durable checkpointed plan.
- `plan.session.get` / `plan.session.move` → inspect and navigate checkpoints before execution.
- `plan.session.execute` → run exactly one deterministic checkpoint and inspect `execution.results`, `execution.summary`, `execution.resource_change_summary`, `execution.follow_up_resources`, `execution.launch_surfaces`, `execution.rollback_cues`, and `execution.undo_action`.
- `review.relationship_session.*` and `review.enrichment_session.*` → continue any saved follow-up sessions that a checkpoint created.
- `chat.complete` → ask for advice against the live loop/memory/RAG state after deterministic work lands.

Clients can enter at any compatible step. The MCP tool descriptions are intentionally rich: clients should surface the `Args`, `Returns`, and `Examples` sections so operators can discover the shared workflow model without separate transport-specific docs.

### Review Commands

```bash
# View review cohorts (daily by default)
cloop loop review [--format json|table]

# Weekly review only (stale + blocked_too_long)
cloop loop review --weekly --no-daily

# Both daily and weekly
cloop loop review --all

# Limit items per cohort
cloop loop review --limit 5

# Filter to specific cohort
cloop loop review --cohort stale
```

Review cohorts identify loops needing attention:
- **daily**: stale (72h+), no_next_action, blocked_too_long (48h+), due_soon_unplanned (48h)
- **weekly**: stale, blocked_too_long (deeper review subset)

### RAG Commands

```bash
# Ingest documents
cloop ingest <paths...> [--mode MODE] [--no-recursive]
# Mode options: add (default), reindex, purge, sync

# Query knowledge base
cloop ask <question> [--k N] [--scope SCOPE]
```

### Capture Commands

```bash
# Capture a loop
cloop capture <text> [STATUS_FLAGS] [--captured-at ISO8601] [--tz-offset-min N]
# Status flags: --actionable, --scheduled, --blocked
# Aliases: --urgent (same as --actionable), --waiting (same as --blocked)

# View inbox
cloop inbox [--limit N]

# View next actions (prioritized)
cloop next [--limit N]
# `--limit` is a total cap across all buckets, not per bucket
```

### Exit Codes

- `0`: Success
- `1`: Validation error (invalid arguments, no fields to update, etc.)
- `2`: Not found error (loop not found, invalid transition, etc.)

### Example Workflows

**Capture and complete a task:**
```bash
uv run cloop capture "Review PR #123" --actionable
uv run cloop loop update 1 --next-action "Open PR" --due-at "2026-02-14T17:00:00Z"
uv run cloop loop list --status actionable
uv run cloop loop close 1 --note "Approved and merged"
```

**Export and import data:**
```bash
uv run cloop export --output backup.json
uv run cloop import --file backup.json
```

**Search and update:**
```bash
uv run cloop loop search "groceries"
uv run cloop loop semantic-search "buy milk and eggs"
uv run cloop loop update 5 --tags "shopping,weekly"
```

## Running the Server

Start the local service:

```bash
make run
```

Then open `http://127.0.0.1:8000/` for the Cloop workspace.

Endpoints:

- `GET /docs`: interactive Swagger UI for all API operations.
- `GET /redoc`: ReDoc-style API reference.
- `GET /openapi.json`: machine-readable OpenAPI schema.
- `POST /life/message`: conversational Life feed endpoint for messy capture, open-loop resurfacing, preference memory, duplicate-aware updates, and undoable cleanup plans.
- `POST /chat`: chat completion with configurable tool/grounding options; `?stream=true` for SSE streaming.
- `POST /ingest`: ingest local files/folders into `rag.db`.
- `GET /ask`: RAG question answering; returns an answer plus `sources` pointing at the retrieved chunks.
- `GET /health`: shows the active pi backend, chat/organizer models, embedding model, and bridge readiness.
- `POST /loops/capture`: capture a loop (write-first).
- `GET /loops`: list loops (default `status=open`).
- `GET /loops/{id}`: fetch a loop.
- `POST /loops/search/semantic`: semantic loop search with ranked matches plus on-demand embedding refresh metadata.
- `GET /loops/relationships/review`: relationship-review queue across loops with duplicate/related candidate previews.
- `GET /loops/{id}/relationships/review`: per-loop duplicate/related candidate review.
- `POST /loops/{id}/relationships/{candidate_id}/confirm`: confirm a duplicate or related relationship decision.
- `POST /loops/{id}/relationships/{candidate_id}/dismiss`: dismiss a duplicate or related relationship suggestion.
- `PATCH /loops/{id}`: update loop fields.
- `POST /loops/{id}/close`: close a loop (completed or dropped).
- `POST /loops/{id}/enrich`: run synchronous enrichment for a loop and return the updated loop plus suggestion metadata.
- `POST /loops/bulk/enrich`: run explicit enrichment for a selected set of loops.
- `POST /loops/bulk/query/enrich`: preview or run explicit enrichment across a DSL-selected loop set.
- `GET /loops/planning/sessions`: list saved planning sessions.
- `POST /loops/planning/sessions`: create a planning session from a grounded AI prompt.
- `GET /loops/planning/sessions/{session_id}`: fetch one planning session snapshot.
- `POST /loops/planning/sessions/{session_id}/move`: move the current planning checkpoint cursor.
- `POST /loops/planning/sessions/{session_id}/refresh`: regenerate a saved plan against current grounded context.
- `POST /loops/planning/sessions/{session_id}/execute`: execute the current deterministic checkpoint.
- `DELETE /loops/planning/sessions/{session_id}`: delete a saved planning session.
- `GET /loops/{id}/suggestions`: list suggestions for a loop, including linked clarification rows.
- `GET /loops/suggestions/pending`: list unresolved suggestions across loops.
- `GET /loops/suggestions/{suggestion_id}`: fetch one suggestion with parsed payload and linked clarifications.
- `POST /loops/suggestions/{suggestion_id}/apply`: apply suggestion fields to the target loop.
- `POST /loops/suggestions/{suggestion_id}/reject`: reject a suggestion.
- `GET /loops/{id}/clarifications`: list clarification rows for a loop.
- `POST /loops/{id}/clarifications/answer`: answer one or more clarification rows by `clarification_id`.
- `POST /loops/{id}/clarifications/refine`: answer clarification rows and rerun enrichment in one mutation.
- `POST /loops/clarifications/{clarification_id}/answer`: answer a single clarification row.
- `GET /loops/next`: deterministic “Next 5” buckets.
- `GET /loops/tags`: list all tags in use.
- `GET /loops/events/stream`: SSE stream of loop events (capture, update, status changes, enrichment).
- `POST /loops/webhooks/subscriptions`: create webhook subscription for outbound events.
- `GET /loops/webhooks/subscriptions`: list webhook subscriptions.
- `PATCH /loops/webhooks/subscriptions/{id}`: update a webhook subscription.
- `DELETE /loops/webhooks/subscriptions/{id}`: delete a webhook subscription.
- `GET /loops/webhooks/subscriptions/{id}/deliveries`: list delivery history for a subscription.

Example requests:

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H 'content-type: application/json' \
  -d '{"paths":["./my-docs"],"mode":"add","recursive":true}'

curl 'http://127.0.0.1:8000/ask?q=What%20is%20Cloop%3F&k=5'
```

## Web UI Workflow

Open `http://127.0.0.1:8000/` after starting the server for a keyboard-driven loop management interface.

### Tabs

| Tab | Purpose |
|-----|---------|
| **Life feed** (1) | Agent-organized natural-language capture, resurfacing, cleanup, and grouped open loops |
| **Next** (2) | Prioritized "what should I do next?" buckets |
| **Chat** (3) | LLM conversation with configurable loop, memory, document, and tool grounding |
| **Memory** (4) | Durable memory CRUD/search powered by the shared direct-memory contract |
| **RAG** (5) | Query your knowledge base |
| **Review** (6) | Checkpointed planning sessions, bulk enrichment, saved relationship/enrichment review sessions, plus daily/weekly review cohorts |
| **Metrics** (7) | Loop health statistics |

### Life Feed

The first screen is the Life feed:
1. Dump scattered thoughts, obligations, reminders, worries, or plans in one message.
2. The organizer model returns a structured Life plan for captures, duplicate-aware updates, merges, split child loops, related-loop links, blocker/dependency links, prepared drafts/checklists/scripts/shortlists/appointment prep, optional contextual clarifications, clarification answers to previously pending questions, preference, pattern, person, event, or context memory, memory-layer gardening, cleanup, rescheduling, waiting/active state changes, resurfacing groups, and background digest notifications. It can carry effort, urgency, importance, emotional weight, confidence estimates, authority/risk claims, agent-authored group titles/summaries, group item rationale/state, cleanup bucket placement, resulting Life states, source-evidence labels from pasted links or attached files, and agent-authored notification copy. It receives current loops, recent history, pending and answered clarification rows, durable memory, external input metadata, and raw factual timing/deferral/user-touch/agent-touch/dependency evidence before making those decisions.
3. Cloop validates that plan, enforces local safety boundaries for authority/risk, persists changes through shared loop/memory services, and returns undo handles for automatic cleanup.
4. Life memories are layered as active, warm, or cold context and separated by category so preferences, patterns, people, events, generic context, commitments, and facts are not treated equally.
5. Resurfaced loops receive lightweight history events so future Life turns know what was recently put back in front of the user.
6. Background Life garden, due-soon, and stale-rescue passes send push digests only when the organizer explicitly sets `notify_user` and provides notification copy. Scheduler code owns slots and dedupe, not staleness, priority, escalation, or nudge wording.
7. Use the older work surfaces below the feed when you need detailed loop search, review queues, planning sessions, or memory management.

Loop and memory mutations still go through the same shared backend contracts as the HTTP, CLI, and MCP surfaces. The agent decides what the message means; deterministic code validates and writes it.

### Review Cohorts

The Review tab has five review layers, plus an in-product workflow guide that shows when to plan, execute, refresh, and hand work off to saved review sessions:

- **Checkpointed planning sessions**: grounded AI plans with durable checkpoints, explicit deterministic operations, execution history, and refreshable context snapshots.
- **Bulk enrichment**: a DSL-driven preview-and-run workflow for re-enriching a filtered loop set without leaving the review workspace.
- **Saved relationship-review sessions**: filtered duplicate/related review queues with preserved cursor state, guided next/previous stepping, saved decision presets, inline confirm/dismiss flows, and duplicate merge entrypoints.
- **Saved enrichment-review sessions**: filtered suggestion/clarification queues with preserved cursor state, guided next/previous stepping, saved apply/reject presets, and one-shot clarification-answer-plus-rerun refinement inside the same session.
- **Daily/weekly cohorts**: deterministic hygiene buckets for stale, blocked, and under-specified loops.

The cohort section groups loops needing attention:

**Daily cohorts**:
- **stale**: Loops not updated in 72+ hours
- **no_next_action**: Actionable loops without a defined next step
- **blocked_too_long**: Blocked for 48+ hours
- **due_soon_unplanned**: Due within 48 hours but no next action

**Weekly cohorts**: Subset of daily (stale, blocked_too_long) for deeper review.

### Keyboard Shortcuts

Press `?` in the web UI to see all shortcuts:

| Action | Keys |
|--------|------|
| New loop (focus capture) | `n` |
| Search/query | `/` |
| Complete selected | `c` |
| Enrich selected | `e` |
| Refresh | `r` |
| Toggle timer | `t` |
| Snooze | `s` |
| Switch tabs | `1`-`7` |
| Go to Inbox/Next/Chat/Memory/RAG/Review/Metrics | `g i` / `g n` / `g c` / `g e` / `g r` / `g v` / `g m` |
| Select all visible | `Ctrl+A` |
| Clear selection | `Esc` |
| Show help | `?` |

### Bulk Operations

Select multiple loops (Shift+Click for range, Ctrl+A for all) to:
- Complete / Drop
- Change status
- Snooze
- Add tags

## Configuration

Cloop reads configuration from environment variables (a `.env` file works well).

### Pi models

- `CLOOP_PI_MODEL`: ordered chat selector preferences in `provider/model` form (default: `zai/glm-5.2,kimi-coding/kimi-for-coding,openai-codex/gpt-5.5`)
- `CLOOP_PI_ORGANIZER_MODEL`: ordered organizer/enrichment selector preferences (default: `zai/glm-5.2,kimi-coding/kimi-for-coding,openai-codex/gpt-5.5`)
- `CLOOP_PI_THINKING_LEVEL`: chat thinking level (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`)
- `CLOOP_PI_ORGANIZER_THINKING_LEVEL`: organizer thinking level
- `CLOOP_PI_TIMEOUT`: chat timeout in seconds (default: `30.0`)
- `CLOOP_PI_ORGANIZER_TIMEOUT`: organizer timeout in seconds (default: `60.0`)
- `CLOOP_PI_BRIDGE_CMD`: optional override for the Node bridge command
- `CLOOP_PI_AGENT_DIR`: optional override for pi auth/model config (`PI_CODING_AGENT_DIR` is also honored)
- `CLOOP_PI_CHAT_MAX_TOOL_ROUNDS`: advisory chat tool-round budget (default: `4`)
- `CLOOP_PI_PLANNING_MAX_TOOL_ROUNDS`: planning-generation tool-round budget (default: `2`)
- `CLOOP_PI_ENRICHMENT_MAX_TOOL_ROUNDS`: enrichment-generation tool-round budget (default: `2`)
- `CLOOP_PI_RAG_MAX_TOOL_ROUNDS`: RAG-answer tool-round budget (default: `2`)
- `CLOOP_PI_MUTATION_MAX_TOOL_ROUNDS`: mutation/tool-writing budget (default: `2`)

Cloop passes these selector strings straight through to `pi` and relies on `pi --list-models`
for availability. The default selector preference order is `zai/glm-5.2`, `kimi-coding/kimi-for-coding`,
then `openai-codex/gpt-5.5`, but any pi-supported selector is valid.

`fallback` resolves each role to the first available configured selector. `exact` requires
one explicit selector per role and fails if it is unavailable.

Cloop resolves tool budgets per surface instead of assuming one repo-wide loop. Read-only
chat, planning, enrichment, and RAG can use one bounded alternate strategy before returning
`readonly_generation_exhausted`; mutation stays single-path.

Check available models with:

```bash
pi --list-models
```

Authenticate pi separately from Cloop, for example with the normal `pi` login flow for the providers you use.
If the bridge reports model unavailability, startup failures, or protocol problems, use [docs/ai_runtime.md](ai_runtime.md) as the troubleshooting reference.

### Embedding providers

Embeddings use the separate LiteLLM-compatible embedding path.

- `CLOOP_EMBED_MODEL`: embedding model used for RAG (default: `ollama/nomic-embed-text`)
- `CLOOP_OLLAMA_API_BASE`: required when embeddings use `ollama/...`
- `CLOOP_LMSTUDIO_API_BASE`: optional when embeddings use `lmstudio/...`
- `CLOOP_OPENAI_API_KEY`: required when embeddings use `openai/...`, `gpt-*`, or `o1-*`
- `CLOOP_OPENAI_API_BASE`: optional custom base URL for OpenAI-compatible embeddings
- `CLOOP_GOOGLE_API_KEY`: required when embeddings use `gemini/...` or `google/...`
- `CLOOP_OPENROUTER_API_BASE`: optional base URL when embeddings use `openrouter/...`

These embedding credentials are separate from the pi chat/organizer runtime.
Cloop does not use `CLOOP_OPENAI_API_KEY` or `CLOOP_GOOGLE_API_KEY` to authenticate pi chat requests.

### Where your data lives

- `CLOOP_DATA_DIR`: directory for `core.db` and `rag.db` (default: `./data`)
- `CLOOP_CORE_DB_PATH`, `CLOOP_RAG_DB_PATH`: override individual DB paths

### RAG behavior

- `CLOOP_DEFAULT_TOP_K`: number of chunks to retrieve (default: `5`)
- `CLOOP_CHUNK_SIZE`: chunk size in tokens/words-ish units (default: `800`)
- `CLOOP_VECTOR_MODE`: `python` (default), `sqlite`, or `auto`
- `CLOOP_EMBED_STORAGE`: `json`, `blob`, or `dual` (default: `dual`)
  - Note: `CLOOP_VECTOR_MODE=sqlite` requires `CLOOP_EMBED_STORAGE=json` or `dual`.
- `CLOOP_SQLITE_VECTOR_EXTENSION`: optional path to a SQLite vector extension, if you have one.

### Note tools (separate from durable memory entries)

- `CLOOP_TOOL_MODE`: `manual`, `llm`, or `none` (default: `manual`)
  - `manual`: you must send a `tool_call` to `/chat` (e.g., `read_note`, `write_note`)
  - `llm`: the pi bridge runs the tool loop and proxies tool execution back into Python
  - `none`: tools disabled
- `CLOOP_STREAM_DEFAULT`: set to `true` to stream by default

#### Note Discovery Tools

Notes support enumeration and search via tool operations:

- `list_notes`: List all stored notes with pagination
- `search_notes`: Search notes by text (matches title and body)

Example chat usage:
```json
{"tool_call": {"name": "list_notes", "arguments": {"limit": 10}}}
{"tool_call": {"name": "search_notes", "arguments": {"query": "meeting notes"}}}
```

Both operations return:
- `items`: Array of note objects with id, title, body, created_at, updated_at
- `next_cursor`: Pagination cursor for fetching more results (null if no more)
- `limit`: The limit used for this query

### Organizer autopilot

- `CLOOP_AUTOPILOT_ENABLED`: enable loop enrichment (default: `false`)
- `CLOOP_AUTOPILOT_AUTOAPPLY_MIN_CONFIDENCE`: auto-apply threshold (default: `0.85`)
- `CLOOP_SCHEDULER_ENABLED`: enable the dedicated review/nudge scheduler process (default: `false`)
- `CLOOP_SCHEDULER_LIFE_GARDEN_INTERVAL_HOURS`: background Life organizer cleanup and memory-gardening interval (default: `24.0`)
- `CLOOP_SCHEDULER_POLL_INTERVAL_SECONDS`: scheduler poll interval (default: `60.0`)
- `CLOOP_SCHEDULER_LEASE_SECONDS`: scheduler lease duration (default: `180`)

### Idempotency (safe retries)

Shared idempotency support covers the mutation surfaces that already use the common
idempotency flow:

- `CLOOP_IDEMPOTENCY_TTL_SECONDS`: retention window for idempotency keys (default: `86400` = 24 hours)
- `CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH`: max key length (default: `255`)

**HTTP API**: Include `Idempotency-Key` header with supported loop/review POST/PATCH mutations.
- Same key + same payload: replays prior response without additional writes
- Same key + different payload: returns 409 Conflict

**MCP tools**: Pass `request_id` argument to supported mutation tools (`loop.create`, `loop.update`, `loop.close`, `loop.transition`, `loop.snooze`, `loop.enrich`, `memory.create`, `memory.update`, `memory.delete`, `suggestion.apply`, `suggestion.reject`, `clarification.answer`, `clarification.answer_many`, `clarification.refine`, `review.relationship_session.move`, `review.enrichment_session.move`, `review.enrichment_session.answer_clarifications`).
- Same request_id + same args: replays prior response
- Same request_id + different args: raises `ToolError`

Example HTTP retry:
```bash
curl -X POST http://127.0.0.1:8000/loops/capture \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: my-unique-key-123' \
  -d '{"raw_text": "Buy groceries", "captured_at": "2026-02-13T10:00:00Z", "client_tz_offset_min": 0}'
```

Example MCP tool call with idempotency:
```python
loop_create(
    raw_text="Buy groceries",
    captured_at="2026-02-13T10:00:00Z",
    client_tz_offset_min=0,
    request_id="my-unique-key-123"
)
```

## Webhooks and SSE

Cloop supports real-time event delivery via webhooks (outbound HTTP) and SSE (Server-Sent Events).

### Server-Sent Events (SSE)

Stream loop events in real-time:

```bash
curl -N http://127.0.0.1:8000/loops/events/stream
```

**Reconnection support**: Pass `Last-Event-ID` header or `?cursor=` query param to resume from a specific event ID:

```bash
curl -N -H "Last-Event-ID: 42" http://127.0.0.1:8000/loops/events/stream
```

**Event types**:
- `capture`: New loop created
- `update`: Loop fields modified
- `status_change`: Status transition
- `close`: Loop completed or dropped
- `enrich_request`/`enrich_success`: Enrichment lifecycle

### Webhooks

Register HTTPS endpoints to receive loop events with HMAC-SHA256 signatures.

**Create a subscription**:

```bash
curl -X POST http://127.0.0.1:8000/loops/webhooks/subscriptions \
  -H 'content-type: application/json' \
  -d '{
    "url": "https://example.com/webhook",
    "event_types": ["capture", "update", "close"],
    "description": "My webhook"
  }'
```

Response includes a `secret` for signature verification. Store this securely.

**Webhook security model**:

- **HTTPS only**: Only HTTPS URLs are accepted (no HTTP)
- **HMAC-SHA256 signatures**: Each payload is signed with the subscription secret
- **Replay protection**: Signatures include timestamps valid for ±5 minutes
- **Exponential backoff**: Failed deliveries retry with jitter (3 retries by default)
- **Dead letter tracking**: Failed deliveries after max retries are preserved for inspection

**Signature verification** (Python example):

```python
import hmac
import hashlib
import json
import time

def verify_webhook(payload: dict, secret: str, signature_header: str) -> bool:
    """Verify webhook signature with replay protection."""
    # Header format: t=<timestamp>,v1=<hex_signature>
    parts = signature_header.split(",")
    timestamp = parts[0].split("=")[1]
    
    # Check timestamp is recent (prevent replay attacks)
    if abs(int(timestamp) - int(time.time())) > 300:
        return False
    
    # Reconstruct expected signature
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signed_payload = f"{timestamp}.{payload_bytes.decode()}".encode("utf-8")
    expected_sig = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256
    ).hexdigest()
    expected = f"t={timestamp},v1={expected_sig}"
    
    return hmac.compare_digest(expected, signature_header)
```

**Webhook headers**:
- `X-Webhook-Signature`: `t=<timestamp>,v1=<signature>`
- `X-Webhook-Event`: Event type (e.g., `capture`)
- `X-Webhook-Event-Id`: Loop event ID for idempotency

**Configuration**:

- `CLOOP_WEBHOOK_MAX_RETRIES`: Max retry attempts (default: 3)
- `CLOOP_WEBHOOK_RETRY_BASE_DELAY`: Initial retry delay in seconds (default: 5.0)
- `CLOOP_WEBHOOK_RETRY_MAX_DELAY`: Max retry delay cap (default: 300.0)
- `CLOOP_WEBHOOK_TIMEOUT_SECONDS`: HTTP request timeout (default: 30.0)

## MCP Server

Run the MCP server (stdio transport):

```bash
uv run cloop-mcp
```

Exposed tools include `chat.complete`, `continuity.delivery_decisions`, `loop.create`,
`loop.update`, `loop.close`, `loop.get`, `loop.next`, `loop.transition`, `loop.tags`,
`loop.list`, `loop.search`, `loop.semantic_search`, `loop.relationship_review`,
`loop.relationship_queue`, `loop.relationship_confirm`, `loop.relationship_dismiss`,
`loop.snooze`, `loop.enrich`, `loop.bulk_enrich`, `loop.bulk_enrich_query`, `memory.list`,
`memory.search`, `memory.get`, `memory.create`, `memory.update`, `memory.delete`,
`suggestion.list`, `suggestion.get`, `suggestion.apply`, `suggestion.reject`,
`clarification.list`, `clarification.answer`, `clarification.answer_many`, `clarification.refine`,
`review.relationship_session.move`, `review.enrichment_session.move`,
`review.enrichment_session.answer_clarifications`, `project.list`, `rag.ask`, and `rag.ingest`.

`chat.complete` reuses the same grounded chat contract as HTTP `/chat` and `cloop chat`, so
manual-tool behavior, bridge-led tool calling, ordered `tool_results`, metadata, sources, and
interaction logging stay aligned. It exposes the shared non-streaming chat payload.

`plan.session.*` and `review.*` are designed to chain: planning sessions can create follow-up
review sessions, saved views, and reusable templates, and saved review sessions preserve cursor
state for later MCP calls. Planning execution results expose `execution.summary`,
`execution.follow_up_resources`, `execution.launch_surfaces`, `execution.rollback_cues`, and
`execution.undo_action` so MCP clients can surface next-step handoffs and reversible-change cues
without re-deriving them. Their tool descriptions include operator-facing `Args`, `Returns`, and
`Examples` guidance that matches the runtime docs.

`memory.*` reuses the shared `memory_management` contract as the HTTP, web, and CLI surfaces,
so direct memory CRUD/search semantics stay aligned everywhere.

`continuity.delivery_decisions` reuses the same shared continuity delivery-diagnostics contract as
HTTP `/loops/continuity/debug/delivery-decisions` and `cloop continuity delivery-decisions`, so
opaque cursor paging, sendability reasons, resend timing, and latest scheduler-push provenance stay aligned.

`loop.semantic_search` reuses the same shared semantic loop-search contract as HTTP, the Inbox web UI,
and `cloop loop semantic-search`, so ranking logic, on-demand embedding refresh, and similarity-score payloads stay aligned.

`loop.relationship_*` reuses the shared `src/cloop/loops/relationship_review.py` contract as HTTP,
the web Review tab, and `cloop loop relationship *`, so duplicate-vs-related classification, queueing,
and confirm/dismiss persistence stay aligned everywhere.

`loop.bulk_enrich*` reuses the shared `src/cloop/loops/enrichment_orchestration.py` contract as HTTP,
the web Review tab, the Inbox bulk `Enrich` action, and `cloop loop bulk enrich`, so filtered target
selection, result envelopes, and follow-up suggestion/clarification behavior stay aligned everywhere.

`suggestion.*` and `clarification.*` reuse the shared enrichment-review and enrichment-orchestration
contracts as the HTTP, web, and CLI surfaces, so suggestion payloads, linked clarification rows,
clarification-answer semantics, and answer-plus-rerun refinement stay aligned.

`rag.ask` and `rag.ingest` reuse the same shared retrieval execution contract as the HTTP and CLI surfaces,
so answer/source semantics and ingest bookkeeping stay aligned.

