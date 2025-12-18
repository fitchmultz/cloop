Here is the single best path forward that matches what you described: **treat “capture” as a guaranteed write, treat “organization + prioritization” as an AI enrichment layer, and treat “action” as a tight, low friction loop state machine.** SQLite stays the source of truth. Gemini 3 Flash Preview does the heavy lifting, but only as a *suggestion engine* unless confidence is very high.

This gives you the thing you actually want: **you can dump anything instantly, trust it won’t get lost, and later pull up the right 5 things to do with near zero mental sorting.**

## Product design spec in natural language

### The mental model

A **loop** is a single “open thread” that you want out of your head. The system has one job:

1. Capture fast (no sorting required)
2. Turn raw input into structured intent (AI)
3. Make “next action” obvious (AI + UI)
4. Close it with one tap

Think of the capture inbox like a write ahead log: it is the place you dump raw events. Later you can replay that log into structured work without losing anything.

### The default object: a loop record

Every loop is the same object whether personal or professional. No separate silos. The loop has:

* **Raw capture**: exactly what you typed (never overwritten)
* **Title**: short, clean, human readable
* **Definition of done**: what “closed” means in plain terms
* **Next action**: the smallest next step
* **Due date**: optional, but parsed when implied
* **Status**: inbox, active, waiting, scheduled, done, dropped
* **Effort** (2 dimensions):

  * **Time estimate** (minutes)
  * **Activation energy** (0–3)
    0 = can do instantly, 3 = requires setup/context/mental load
* **Context**: inferred tags like `AZ DPS`, `Amazon`, `Errands`, `Computer`, `Phone`
* **Project/thread**: inferred grouping like “AZ DPS admin”
* **Related loops**: auto linked by similarity (with confidence)
* **Confidence + provenance**: which fields came from AI, with what confidence, and what you manually changed

That last bullet is not fluff. It is how you keep the system trustworthy: AI can be wrong without corrupting your reality.

### Capture UX (phone + computer)

You will use the same capture flow everywhere:

**Screen: Quick Capture**

* One text box, big
* One button: **Save**
* Optional tiny toggles you can ignore:

  * “This is urgent”
  * “This is scheduled”
  * “This is waiting on someone”

When you hit Save:

* The loop is created immediately (no AI gating)
* The UI instantly shows the loop card in an Inbox list
* Within a moment, the card upgrades itself with AI enrichment

The user experience should feel like:

* Type “return Amazon package by Friday”
* Hit Save
* It becomes:

  * Title: “Return Amazon package”
  * Due: next Friday relative to capture timestamp
  * Context: Errands
  * Activation energy: 1
  * Next action: “Find the return QR code and box the item”
  * Related: any other “Amazon returns” loop

Key requirement: due date parsing must be anchored to **capture timestamp + timezone offset from the client**, not server local time. Otherwise “by Friday” breaks when you travel.

### Inbox UX (the triage queue, low cognitive load)

**Screen: Inbox**

* Shows newest captures first
* Every card shows:

  * Title (AI)
  * Due (if any)
  * Effort: time + activation
  * Project/thread (AI)
  * 2–3 tags (AI)
  * “Related” badge if duplicates suspected

Each card has exactly these actions:

* **Do next** (moves to active)
* **Schedule** (sets a date or snooze)
* **Waiting** (blocked on someone)
* **Done** (close it)
* **Edit** (manual override)

That is it. No tag management required. Tags exist but are mostly invisible until you filter or search.

### “What should I do now?” UX

This is your killer feature. It must be faster than thinking.

**Screen: Next 5**

* Default list is computed, not manually curated
* You get:

  1. “Due soon”
  2. “Fast wins” (activation energy 0–1, under 10–15 min)
  3. “High leverage” (importance high, effort moderate)

A loop is actionable if:

* Status is active OR inbox and has a clear next action
* Not snoozed
* Not waiting

When you tap a loop:

* You see next action at the top
* Any needed context below (links, notes, retrieved doc snippets)
* One tap to mark done

### Search and filtering (without tag maintenance)

One universal search box. You type:

* “AZ DPS”
* “errands”
* “due this week”
* “quick wins”
* “waiting on John”
* “Amazon returns”

Under the hood, this is a mix of:

* FTS search over loop text
* Structured filters over fields (status, due, project)
* Optional semantic search via embeddings

The UI surfaces tags and projects as *suggestions*, not obligations.

### Closing a loop

Closing must be frictionless:

* Tap Done
* Optional: “Add outcome note” (one line)
* Done

Closed loops are never deleted by default. They go to an archive you can search.

### Weekly review UX (alignment, drift control)

Once a week (or whenever), you open:

**Screen: Review**

* “Stale loops” (not touched in N days)
* “Missing next action”
* “Due soon but not active”
* “Duplicates suspected”
* “Big loops that need splitting”

This is where the agentic part shines, but still keeps you in control.

## The AI autopilot behavior

### Use Gemini 3 Flash Preview as your organizer model

Gemini 3 Flash Preview explicitly supports function calling, structured outputs, “thinking”, and large context windows. Model ID is `gemini-3-flash-preview`. ([Google AI for Developers][1])

It also supports “thinking_level” controls, including Flash-specific levels like `minimal`, `medium`, alongside `low` and `high`. This matters because most of your loop enrichment should be fast and cheap. ([Google AI for Developers][2])

### Autopilot contract (non negotiable)

1. **Capture never waits on AI**
2. **AI writes suggestions, not truth**
3. **User edits become locks**
   If you manually set due date or project, AI stops overwriting that field unless you explicitly re-run autopilot.
4. **Confidence gates automation**

   * High confidence fields can be auto-applied (example: title cleanup)
   * Medium and low confidence fields stay as suggestions
5. **No destructive actions without explicit confirmation**
   Never auto-merge loops, never auto-close loops, never auto-delete

### Autopilot output schema (what Gemini must produce)

On every capture, Gemini returns structured JSON like:

* `title`
* `summary`
* `definition_of_done`
* `next_action`
* `due_at` (ISO datetime or null)
* `snooze_until` (optional)
* `tags` (ranked)
* `project` (string)
* `activation_energy` (0–3)
* `time_minutes` (int)
* `urgency` (0–1)
* `importance` (0–1)
* `confidence` per field
* `needs_clarification` (list of questions to ask later, not now)

Gemini 3 Flash Preview supports structured outputs, which is exactly what makes this stable. ([Google AI for Developers][1])

### Related-loop linking (the “keeps things in track” part)

After capture, the system does:

1. Embed the loop text (same embed model you already use for RAG)
2. Search similar embeddings in existing loops
3. If similarity above threshold:

   * suggest “related loops”
   * suggest “possible duplicate”
   * suggest “belongs to project X”

This is how “respond to AZ DPS” automatically gets attached to existing AZ DPS threads without you doing anything.

### Prioritization (how the Next 5 list is computed)

Do not let the model decide priority as vibes. Make it deterministic from model estimates.

Compute a priority score from:

* Due proximity (hard signal)
* Urgency estimate (soft)
* Importance estimate (soft)
* Effort penalty (time + activation)

Then present in user-facing buckets:

* Due soon
* Quick wins
* High leverage

This gives you predictable behavior you can trust, while still benefiting from AI inference.

## Agentic execution boundary with MCP

You want agentic behavior without giving the model raw, dangerous powers. MCP is the right interface boundary for that.

MCP is JSON-RPC based and standardizes how tools and data are exposed. It supports stdio for local servers and Streamable HTTP for remote servers. ([Model Context Protocol][3])

### The best MCP approach for your project

Do **not** start by giving the model a generic SQLite MCP server with arbitrary SQL execution. Those exist (example: mcp-sqlite exposes CRUD and custom SQL query tools), but it is too easy for an agent to do something dumb with raw SQL. ([GitHub][4])

Instead, implement a **purpose-built MCP server** with tools that match your domain:

* `loop.create`
* `loop.update`
* `loop.close`
* `loop.list`
* `loop.search`
* `loop.link_related`
* `loop.snooze`
* `project.list`
* `project.merge` (manual confirmation required)

This keeps the agent powerful but boxed in.

You can build this cleanly in Python using the official MCP Python SDK (`mcp` package), which supports servers and clients and transports like stdio and Streamable HTTP. ([PyPI][5])

### Where Claude Agent SDK fits

Claude Agent SDK is useful if you want a reusable agent harness, and it can host custom tools as in-process MCP servers. ([GitHub][6])

But your core design does not depend on it. Your system can be “agentic” simply by running Gemini in a tight loop:

* plan (structured output)
* call tools (typed operations)
* write back results
* stop

MCP is the key. The harness is just plumbing.

## SQLite-first architecture plan

You already have:

* `core.db` for notes + interactions
* `rag.db` for documents + chunks

Keep that separation. Extend `core.db` with loop tables.

### Core tables you will add (conceptual)

* `loops`

  * id, raw_text, title, status, due_at, snooze_until
  * next_action, definition_of_done
  * time_minutes, activation_energy
  * urgency, importance
  * project_id
  * created_at, updated_at, closed_at
  * user_locks JSON (fields the user has overridden)
* `projects`

  * id, name, summary, created_at
* `tags`

  * id, name
* `loop_tags`

  * loop_id, tag_id, source(ai|user), confidence
* `loop_links`

  * loop_id, related_loop_id, relationship_type, confidence
* `loop_suggestions`

  * loop_id, suggestion_json, model, created_at
* `loop_events` (append-only audit log)

  * loop_id, event_type, payload_json, created_at
* Optional but high value:

  * `loops_fts` (FTS5 index for fast search)
  * `loop_embeddings` (blob + norm for similarity search, like your chunk storage)

This structure supports:

* fast capture
* transparent history
* AI suggestions without overwriting raw truth
* dedupe and grouping
* deterministic prioritization

### API surfaces (FastAPI)

Add endpoints that map to the UX, not to the database:

* `POST /loops/capture`
* `GET /loops` (filters: status, due range, project, tag)
* `GET /loops/next` (returns Next 5 with buckets)
* `GET /loops/{id}`
* `PATCH /loops/{id}` (manual edits + locking)
* `POST /loops/{id}/close`
* `POST /loops/{id}/snooze`
* `POST /loops/{id}/enrich` (rerun AI)

Leave `/chat`, `/ask`, `/ingest` as-is, but make loops able to pull in RAG context:

* When enriching a loop, you can query `rag.db` for relevant chunks and include those snippets as “context references” inside the loop detail view.

## The single implementation sequence I would actually follow

### Phase 1: Trustworthy capture + inbox

* Add `loops` table + minimal API
* Build a mobile-first web page (PWA later) with only Quick Capture + Inbox
* No AI yet, only manual edit

Goal: you can capture from phone and not lose anything.

### Phase 2: Gemini autopilot enrichment

* Add `loop_suggestions` table and the enrichment pipeline
* Gemini 3 Flash Preview (`gemini-3-flash-preview`) returns structured JSON
* Auto-apply only low-risk fields (title cleanup), suggest the rest
* Store confidence and provenance

Gemini 3 Flash Preview supports structured outputs and function calling which makes this stable. ([Google AI for Developers][1])

### Phase 3: Next 5 view (the payoff)

* Implement deterministic priority scoring
* Add activation energy and time estimate to the UI
* Add the Next 5 endpoint and screen

Goal: you stop thinking “what should I do” and just do.

### Phase 4: Related loops and threads

* Store embeddings for loops
* Auto-suggest related loops and project grouping
* Add “merge suggestion” UX (manual confirm only)

### Phase 5: MCP server

* Add `cloop-mcp` using MCP Python SDK
* Expose only your typed loop tools
* Now any MCP-capable client or agent harness can manage your loops without raw SQL access ([PyPI][5])

## Why this is the best path (first principles)

* **You need a trusted capture system before you need intelligence.** If capture is not frictionless, you will not use it consistently.
* **AI must enrich, not own the truth.** Otherwise you stop trusting it after the first wrong inference.
* **Prioritization must be deterministic.** If the “Next 5” list changes for unclear reasons, you will fight the system.
* **MCP is the right tool boundary.** It standardizes tool access and keeps the agent from being a loose cannon. ([Model Context Protocol][3])

If you want, I can turn this into a concrete written “Product Spec v0.1” document with:

* the exact loop states and transitions
* the exact fields and what auto-applies vs suggests
* the exact screens and card layouts
* the exact AI JSON schema and confidence gating rules

That spec becomes the contract before any refactor touches your codebase.

[1]: https://ai.google.dev/gemini-api/docs/models "Gemini models  |  Gemini API  |  Google AI for Developers"
[2]: https://ai.google.dev/gemini-api/docs/gemini-3 "Gemini 3 Developer Guide  |  Gemini API  |  Google AI for Developers"
[3]: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports "Transports - Model Context Protocol"
[4]: https://github.com/jparkerweb/mcp-sqlite "GitHub - jparkerweb/mcp-sqlite:  Model Context Protocol (MCP) server that provides comprehensive SQLite database interaction capabilities"
[5]: https://pypi.org/project/mcp/ "mcp · PyPI"
[6]: https://github.com/anthropics/claude-agent-sdk-python "GitHub - anthropics/claude-agent-sdk-python"
