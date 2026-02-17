# Cloop Assistant Blueprint

## Mission

Cloop is a **secretary-grade personal assistant** that helps you close open loops — those tasks, decisions, and obligations occupying your working memory. By providing frictionless capture (mobile or desktop), AI-powered organization, and intelligent prioritization, Cloop ensures nothing falls through the cracks while minimizing the cognitive load of managing your commitments.

**Core principle**: *"Get loops out of your head and into a trusted local system."*

## Design Principles

### Cognitive Load Reduction

- **Zero-decision capture**: Just dump the thought — no need to categorize, tag, or prioritize at capture time
- **AI handles organization**: Automatic title extraction, tagging, project assignment, and next-action identification
- **User intervenes only when uncertain**: Low-confidence AI suggestions become review items; high-confidence changes apply automatically
- **Progressive disclosure**: Simple interfaces for quick capture, rich interfaces for deep management

### Secretary Behaviors

A good secretary is:

- **Proactive**: Surfaces what needs attention (due soon, stale items, blocked loops)
- **Context-aware**: Considers related loops, current workload, and energy levels
- **Non-intrusive**: Suggestions wait for review unless confidence is high; never interrupts flow
- **Reliable**: Captures everything, loses nothing, provides clear audit trails

### Trust Model

- **Auto-apply threshold**: 0.85 confidence (configurable via `CLOOP_AUTOPILOT_AUTOAPPLY_MIN_CONFIDENCE`)
- **Low-confidence items**: Become suggestions requiring explicit user approval
- **User override**: Any AI decision can be manually overridden; user locks prevent AI from modifying specific fields
- **Audit trail**: Every change is logged in `loop_events` with full provenance

## User Journey

### Capture (Mobile or Desktop)

1. **Input**: User enters raw text
   - Mobile: Voice-to-text (OS-level), optimized for on-the-go capture
   - Desktop: Typed input, often more detailed
2. **Immediate persistence**: Loop created in `inbox` status instantly — guaranteed capture
3. **Async enrichment**: AI analysis runs in background (title, tags, project, next_action, time estimates)
4. **Suggestion application**: High-confidence fields auto-applied; low-confidence queued for review

### Organize (AI-Assisted)

AI extracts and suggests:
- **Metadata**: title, summary, tags, project, next_action
- **Estimates**: time_minutes, activation_energy (0-3 scale)
- **Priorities**: urgency, importance (0.0-1.0 scale)
- **Relations**: related loops, potential duplicates, dependencies
- **Temporal**: due dates, snooze times

User reviews suggestions via CLI (`cloop loop enrich`) or web UI suggestion panel.

### Prioritize

1. **Deterministic scoring**: Weighted combination of:
   - Due date proximity (`priority_weight_due`)
   - Urgency (`priority_weight_urgency`)
   - Importance (`priority_weight_importance`)
   - Time penalty (`priority_weight_time_penalty`)
   - Activation energy penalty (`priority_weight_activation_penalty`)

2. **Action buckets**:
   - **Quick wins**: ≤15 min, low activation energy
   - **Due soon**: Within 48 hours
   - **High leverage**: High importance, strategic value
   - **Standard**: Everything else actionable

3. **Blocked items excluded**: Loops with open dependencies don't appear in priority lists

**Note on limit semantics**: Currently, `limit` applies per-bucket, so `loop.next(limit=5)` can return up to 20 items (5 per bucket). This is a known issue (RQ-0115) and will be changed to cap total returned items.

### Act

1. **Pick from "Next 5"**: Prioritized list across all buckets
2. **Focus mode**: Timer tracking for work sessions (`time_sessions` table)
3. **Status transitions**: Move through inbox → actionable → completed

### Close

1. **Mark completed/dropped**: With optional closing note
2. **Event logged**: Full audit trail in `loop_events`
3. **Dependencies notified**: If other loops were blocked, they may become actionable
4. **Recurring loops**: Next occurrence auto-created based on RRULE

## Automation Boundaries

### Auto-Applied (High Confidence ≥ 0.85)

| Field | Rationale |
|-------|-----------|
| title | Low risk, easily corrected |
| tags | Non-destructive, additive |
| project | Based on text patterns and history |
| next_action | Concrete, verifiable |
| time_minutes | Estimate, not commitment |
| activation_energy | Scale 0-3, low stakes |
| related loop detection | Informational only |

### Requires Confirmation (Low Confidence < 0.85)

| Field | Rationale |
|-------|-----------|
| due_at | Critical for scheduling; user must verify |
| urgency | Subjective; depends on broader context |
| importance | Subjective; user knows priorities best |
| dependencies | Complex inference; relationships matter |

### Never Auto-Applied

- **Status transitions** (except capture → inbox): User controls workflow
- **Loop closure**: Must be explicit (completed/dropped)
- **Deletion**: Irreversible; requires explicit action
- **Snooze**: User decides when to defer

## Architecture

### Data Layer (SQLite-First)

All data lives in local SQLite files — no external dependencies, no network required.

#### core.db

| Table | Purpose |
|-------|---------|
| `loops` | Main loop records with status, metadata, provenance |
| `loop_events` | Audit trail of all changes (immutable) |
| `loop_suggestions` | Pending AI suggestions with confidence scores |
| `loop_claims` | Multi-agent ownership tokens |
| `loop_dependencies` | Dependency graph (DAG, cycle-protected) |
| `loop_links` | Related/duplicate/similar loop relationships |
| `loop_tags` | Many-to-many: loops ↔ tags |
| `notes` | Persistent memory (read_note/write_note tools) |
| `projects` | Project names (auto-created, user-editable) |
| `tags` | Tag names (normalized lowercase) |
| `time_sessions` | Focus timer tracking |
| `loop_templates` | Reusable loop patterns |
| `loop_comments` | Threaded discussion on loops |
| `loop_views` | Saved DSL queries |
| `loop_embeddings` | Vector embeddings for similarity search |
| `idempotency_keys` | Safe retry tracking |
| `webhook_subscriptions` | Outbound event subscriptions |
| `webhook_deliveries` | Delivery history with retry tracking |

#### rag.db

| Table | Purpose |
|-------|---------|
| `documents` | Ingested files with metadata |
| `chunks` | Text chunks with embeddings |

### Service Layer

```
┌─────────────────────────────────────────────────────────────────┐
│                      Presentation Layer                          │
│  CLI (cli.py)  │  HTTP Routes (routes/*.py)  │  MCP (mcp_server) │
├─────────────────────────────────────────────────────────────────┤
│                      Service Layer                               │
│  loops/service.py  │  loops/enrichment.py  │  rag/service.py    │
│  - Business logic  │  - AI suggestions      │  - RAG queries     │
│  - State machine   │  - Confidence gating   │                    │
├─────────────────────────────────────────────────────────────────┤
│                      Data Layer                                  │
│  loops/repo.py  │  db.py (schema + connection)                  │
│  - Query builders│  - Migrations                                │
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

#### Loop Service (`loops/service.py`)

**State Machine**:
```
                    ┌──────────────────────────────┐
                    │            inbox             │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   actionable    │◄──►│    blocked      │◄──►│   scheduled     │
└────────┬────────┘    └─────────────────┘    └─────────────────┘
         │
         │     ┌─────────────┐
         └────►│  completed  │
               └─────────────┘
               ┌─────────────┐
               │   dropped   │
               └─────────────┘
```

- **Allowed transitions**: Defined in `_ALLOWED_TRANSITIONS` dict
- **Dependency enforcement**: Blocked loops can't become actionable until dependencies complete
- **Event emission**: Every transition creates `loop_events` entry + webhook delivery

#### Recurrence (`loops/recurrence.py`)

- **RRULE support**: Standard RFC 5545 recurrence rules
- **Natural language**: `schedule` parameter parses phrases like "every Monday"
- **Timezone-aware**: Uses `recurrence_tz` for due date computation
- **Auto-generation**: Completed recurring loops create next occurrence automatically

#### Enrichment (`loops/enrichment.py`)

- **Model**: `LoopSuggestion` with per-field confidence scores
- **Prompt**: Structured JSON schema for LLM (Gemini Flash 3)
- **Gating**: Auto-apply when `confidence[field] >= autopilot_autoapply_min_confidence`
- **Provenance**: All AI changes tracked in `provenance_json`

#### MCP Server (`mcp_server.py`)

**Exposed Tools**:
- `loop.create` — Capture new loop
- `loop.update` — Update fields
- `loop.close` — Terminal status (completed/dropped)
- `loop.get` — Retrieve by ID
- `loop.next` — Get prioritized "Next 5"
- `loop.transition` — Non-terminal status changes
- `loop.list`, `loop.search` — Query with pagination
- `loop.snooze` — Defer until specific time
- `loop.enrich` — Trigger AI enrichment
- `loop.claim` / `loop.release_claim` — Multi-agent coordination
- `loop.dependency.add` / `.remove` / `.list` — Dependency management
- `loop.bulk_update` / `.bulk_close` / `.bulk_snooze` — Batch operations
- `loop.view.*` — Saved view management
- `project.list` — Project enumeration

#### Query DSL (`loops/query.py`)

**DSL Syntax**:
- `status:inbox` — Filter by status
- `tag:work` — Filter by tag
- `project:cloop` — Filter by project
- `due:today`, `due:week`, `due:overdue` — Temporal filters
- `sort:due`, `sort:updated` — Sort options

**Used by**: loop.search, loop.list, saved views

**Idempotency**: All mutations support `request_id` for safe retries

#### Prioritization (`loops/prioritization.py`)

**Scoring formula**:
```python
score = (due_weight * due_score + 
         urgency_weight * urgency + 
         importance_weight * importance - 
         time_penalty * time_minutes - 
         activation_penalty * activation_energy)
```

**Buckets**:
- `quick_wins`: time_minutes ≤ 15 AND activation_energy ≤ 1
- `due_soon`: due within 48 hours
- `high_leverage`: importance ≥ 0.7 AND urgency ≥ 0.5
- `standard`: Everything else actionable

### Configuration (`settings.py`)

**Key assistant behavior settings**:

```python
autopilot_enabled: bool = True
autopilot_autoapply_min_confidence: float = 0.85

# Prioritization
prioritization_due_soon_hours: float = 48.0
prioritization_quick_win_minutes: int = 15
prioritization_high_leverage_threshold: float = 0.7

# Scoring weights
priority_weight_due: float = 1.0
priority_weight_urgency: float = 0.7
priority_weight_importance: float = 0.9
priority_weight_time_penalty: float = 0.2
priority_weight_activation_penalty: float = 0.3

# Related loop detection
related_similarity_threshold: float = 0.78
duplicate_similarity_threshold: float = 0.95

# Models
organizer_model: str = "gemini/gemini-3-flash-preview"
```

## Mobile/Desktop Flows

### Mobile (On-the-go capture)

**Use case**: Walking, commuting, away from desk

1. Open Quick Capture UI at `http://host:8000/`
2. Use OS voice-to-text to enter raw text
3. Tap capture → immediate inbox placement
4. AI enrichment runs server-side
5. Review and organize later on desktop

**Design notes**:
- Minimal UI: single text field + capture button
- No complex navigation — capture only
- Voice-first input method

### Desktop (Full management)

**Use case**: Planning, organizing, batch processing

1. Full loop management UI with search/filter
2. Suggestion review panel for AI recommendations
3. Priority list view with action buckets
4. Timer/focus mode for execution
5. Template selection for common loop types

**Design notes**:
- Keyboard shortcuts for power users
- Bulk operations for efficiency
- Rich metadata editing
- Dependency visualization

## Data Lifecycle

### Loop Lifecycle

```
[capture] 
    │
    ▼
[inbox] ─────────────────────────────┐
    │                                │
    ▼                                │
[actionable] ◄─────┐                 │
    │              │                 │
    ├──► [blocked]─┘                 │
    │         │                      │
    │         └──► [actionable]      │
    │                                │
    ├──► [scheduled] ──► [actionable]│
    │                                │
    ├──► [completed] ◄───────────────┘
    └──► [dropped]  ◄────────────────┘
```

### Event Retention

- **All events**: Stored indefinitely in `loop_events`
- **Audit value**: Complete history of every change
- **Metrics source**: Aggregated analytics from event stream
- **Backup/restore**: Via `cloop export` / `cloop import`

### Suggestion Lifecycle

1. **Created**: By enrichment process with confidence scores
2. **Visible**: In suggestion review UI/CLI
3. **Applied**: User accepts → becomes loop field values
4. **Dismissed**: User rejects → suggestion marked rejected
5. **Auto-applied**: High-confidence fields applied without review

### Dependency Lifecycle

1. **Created**: Via `loop.dependency.add` or AI detection
2. **Blocks**: Dependent loop can't become actionable
3. **Resolves**: When blocking loop completed/dropped
4. **Notifies**: Dependent loop may auto-transition to actionable

## Multi-Agent Coordination

### Claim System

- **Purpose**: Prevent conflicting edits when multiple agents (human or AI) access loops
- **Mechanism**: Lease-based claims with TTL
- **Token required**: Mutations on claimed loops need `claim_token`
- **Override**: Admin can force-release claims

### Idempotency

- **HTTP API**: `Idempotency-Key` header
- **MCP tools**: `request_id` parameter
- **Behavior**: Same key + same payload = replayed response, no duplicate writes
- **TTL**: 24 hours (configurable)

## Integration Patterns

### Webhooks

- **Delivery**: HTTPS only with HMAC-SHA256 signatures
- **Retry**: Exponential backoff with jitter
- **Events**: capture, update, status_change, close, enrich_request, enrich_success, enrich_failure

### SSE (Server-Sent Events)

- **Endpoint**: `GET /loops/events/stream`
- **Reconnection**: `Last-Event-ID` header or `?cursor=` param
- **Use case**: Real-time UI updates

## Security Model

- **Local-first**: No cloud dependencies, no data leaves your machine
- **Webhook security**: HTTPS + HMAC signatures + replay protection
- **No secrets in logs**: API keys redacted
- **Claims**: Token-based access control for multi-agent scenarios

## Future Considerations

This blueprint captures the current architecture. Planned enhancements include:

- Energy/time-of-day aware scheduling
- Natural language recurrence ("every Monday", "first of month") — PARTIALLY IMPLEMENTED via `schedule` parameter in loop.create
- Advanced dependency types (soft dependencies, sub-tasks)
- Collaboration features (shared loops, comments)
- Analytics dashboard from event stream
- Mobile app (currently web-based)
