# Clarification-Answer Write-Path Inventory

Trace of every row and payload written by clarification-answer operations across all transports (HTTP, MCP, CLI, saved review sessions). Output for Slice 1 — used by Slice 2 (restore viability probe).

---

## Flow 1: Answer-only (`POST /loops/{loop_id}/clarifications/answer`)

Call chain:
1. HTTP → `run_idempotent_loop_route` → `submit_clarification_answers()`
2. MCP: `clarification.answer` / `clarification.answer_many` → `run_idempotent_tool_mutation` → `submit_clarification_answers()`
3. CLI: `cloop clarification answer` → `submit_clarification_answers()`
4. Saved session: delegates to `orchestrate_clarification_refinement` (see Flow 2)

### Write 1.1 — Clarification row UPDATE

- **Table**: `loop_clarifications`
- **SQL**: `UPDATE ... SET answer = ?, answered_at = ? WHERE id = ? AND answer IS NULL`
- **Location**: `_repo/events.py::answer_loop_clarification`
- **Before**: `{id, loop_id, question, answer: NULL, answered_at: NULL, created_at}`
- **After**: `{id, loop_id, question, answer: <user text>, answered_at: <utcnow>, created_at}`
- **Restore**: `UPDATE SET answer = NULL, answered_at = NULL WHERE id = ?`
- **Guard**: Check no later rerun produced a new suggestion whose `needs_clarification` references this question. If one exists, un-answering would invalidate that suggestion's context.

### Write 1.2 — Suggestion supersede UPDATE

- **Table**: `loop_suggestions`
- **SQL**: `UPDATE ... SET resolution = 'superseded', resolved_at = ?, resolved_fields_json = NULL WHERE id = ?`
- **Location**: `_repo/events.py::resolve_loop_suggestion` from `_supersede_answered_suggestions`
- **Condition**: Pending suggestions whose `needs_clarification` intersects answered questions.
- **Before**: `{..., resolution: NULL, resolved_at: NULL, resolved_fields_json: NULL}`
- **After**: `{..., resolution: 'superseded', resolved_at: <utcnow>}`
- **Restore**: `UPDATE SET resolution = NULL, resolved_at = NULL, resolved_fields_json = NULL WHERE id = ?`
- **Guard**: Low risk — no automation acts on superseded state.

### Write 1.3 — Idempotency record INSERT (conditional)

- **Table**: `idempotency_requests`
- **Condition**: Only if `idempotency_key` header provided.
- **IRREVERSIBLE** — append-only by design. Replay after undo returns pre-undo response; acceptable since keys are caller-managed.

### No continuity outcomes written by this path.

---

## Flow 2: Answer + rerun (`POST /loops/{loop_id}/clarifications/refine`)

Call chain:
1. HTTP → `run_idempotent_loop_route` → `orchestrate_clarification_refinement()`
2. MCP: `clarification.refine` → `run_idempotent_tool_mutation` → `orchestrate_clarification_refinement()`
3. Saved session: `answer_enrichment_review_session_clarifications` → `orchestrate_clarification_refinement()`

`orchestrate_clarification_refinement` calls `submit_clarification_answers()` (Writes 1.1, 1.2) then `orchestrate_loop_enrichment()` (Writes 2.1–2.11 below).

### Write 2.1 — enrichment_state → PENDING

- **Table**: `loops`
- **Location**: `service.py::request_enrichment`
- **Restore**: Snapshot prior `enrichment_state`, write back on undo.

### Write 2.2 — ENRICH_REQUEST event INSERT

- **Table**: `loop_events`
- **Restore**: `DELETE FROM loop_events WHERE id = ?`. Safe for the most recent event if nothing downstream consumed it.

### Write 2.3 — Webhook delivery queue INSERTs (request event)

- **Table**: `webhook_deliveries`
- **GUARDED** — `DELETE FROM webhook_deliveries WHERE event_id = ?` works locally, but any delivery already sent to an external endpoint is irreversible.

### Write 2.4 — New suggestion INSERT

- **Table**: `loop_suggestions`
- **Restore**: `DELETE FROM loop_suggestions WHERE id = ?`.

### Write 2.5 — Loop field UPDATE (auto-applied fields)

- **Table**: `loops`
- **Location**: `enrichment.py::_apply_suggestion` via `update_loop_fields`
- **Condition**: Autopilot enabled + confidence threshold met.
- **Restore**: Snapshot all fields + `provenance_json` before update. Also reverse tag/project side effects.

### Write 2.5a — Tag REPLACE (conditional)

- **Table**: `loop_tags`
- **Restore**: Snapshot prior tag set, call `replace_loop_tags` with snapshot.

### Write 2.5b — Project UPSERT (conditional)

- **Table**: `projects`
- **GUARDED** — project may already exist. If created here and no other loops reference it, delete. Must check FK references first.

### Write 2.6 — enrichment_state → COMPLETE

- **Table**: `loops`
- **Restore**: Snapshot prior state, write back on undo.

### Write 2.7 — ENRICH_SUCCESS event INSERT

- **Table**: `loop_events`
- **Payload**: `{suggestion_id, applied_fields, generation_metadata}`
- **Restore**: `DELETE FROM loop_events WHERE id = ?`.

### Write 2.8 — Webhook delivery queue INSERTs (success event)

- Same shape as 2.3. **GUARDED** — same caveat.

### Write 2.9 — New clarification row INSERTs (conditional)

- **Table**: `loop_clarifications`
- **Condition**: New suggestion has `needs_clarification` questions not already unanswered.
- **Restore**: `DELETE FROM loop_clarifications WHERE id = ?`. Must delete these **before** restoring superseded suggestions — unique index `idx_loop_clarifications_pending_question` on `(loop_id, question)` would block re-insert on overlap.

### Write 2.10 — Interaction log INSERT

- **Table**: `interactions`
- **IRREVERSIBLE** — append-only analytics. Acceptable side effect.

### Write 2.11 — Embedding + similarity side effects (conditional)

- **Tables**: `loop_embeddings`, `loop_links`
- **Condition**: `autopilot_enabled` + embedding provider configured.
- **GUARDED** — embeddings regenerable but non-deterministic. Best-effort only.

### Write 2.12 — Idempotency record INSERT (conditional)

- Same as 1.3. **IRREVERSIBLE**.

---

## Flow 3: Saved review session clarification answer

Delegates to `orchestrate_clarification_refinement` (Flow 2). Additional behavior:

- Review session snapshot rebuilt from live data after refinement (`enrichment_review_sessions.updated_at` changes, queue may advance). No separate session-row undo needed — restoring underlying data naturally restores the session view.
- `follow_through` payload built with `undo_action: None` and `rollback_label: "Undo is not available for this enrichment outcome."` — display-only, nothing persisted.

---

## Restore Matrix

| # | Write | Table | Restorable | Guard |
|---|-------|-------|-----------|-------|
| 1.1 | Answer clarification | `loop_clarifications` | YES | No new suggestion depends on this answer |
| 1.2 | Supersede suggestion | `loop_suggestions` | YES | Low — no automation on superseded |
| 1.3 | Idempotency record | `idempotency_requests` | NO | Append-only; stale replay acceptable |
| 2.1 | enrichment_state → PENDING | `loops` | YES | Snapshot prior state |
| 2.2 | ENRICH_REQUEST event | `loop_events` | YES | Delete if not consumed downstream |
| 2.3 | Webhook deliveries (request) | `webhook_deliveries` | GUARDED | May have been sent externally |
| 2.4 | New suggestion INSERT | `loop_suggestions` | YES | Delete before restoring old |
| 2.5 | Loop field UPDATE | `loops` | YES | Snapshot fields + provenance |
| 2.5a | Tag REPLACE | `loop_tags` | YES | Snapshot prior tags |
| 2.5b | Project UPSERT | `projects` | GUARDED | Check FK refs before deleting |
| 2.6 | enrichment_state → COMPLETE | `loops` | YES | Snapshot prior state |
| 2.7 | ENRICH_SUCCESS event | `loop_events` | YES | Delete if not consumed downstream |
| 2.8 | Webhook deliveries (success) | `webhook_deliveries` | GUARDED | May have been sent externally |
| 2.9 | New clarification INSERTs | `loop_clarifications` | YES | Delete before restoring superseded (unique index) |
| 2.10 | Interaction log | `interactions` | NO | Append-only analytics |
| 2.11 | Embeddings + similarity | `loop_embeddings`, `loop_links` | GUARDED | Non-deterministic — best-effort |
| 2.12 | Idempotency record | `idempotency_requests` | NO | Same as 1.3 |
| 3.1 | Review session snapshot | `enrichment_review_sessions` | GUARDED | Derived — restore underlying data |
| 3.2 | Continuity follow-through | display-only | N/A | Nothing persisted |

Counts: **10 restorable**, **5 guarded**, **3 irreversible** (idempotency × 2, interaction log)

## Restore Ordering (answer + rerun undo)

Execute in this exact order:

1. Delete new clarification rows (2.9) — before step 3 due to unique index
2. Delete new suggestion row (2.4)
3. Restore superseded suggestion rows (1.2 reverse)
4. Restore clarification answers to NULL (1.1 reverse) — verify no other pending suggestion references same question first
5. Restore loop fields, tags, project, provenance (2.5 reverse)
6. Restore enrichment_state to prior value (2.1/2.6 reverse)
7. Delete ENRICH_SUCCESS and ENRICH_REQUEST events (2.2, 2.7 reverse)
8. Delete webhook deliveries for those events (2.3, 2.8 reverse)
9. Idempotency records and interaction logs remain (irreversible, acceptable)

## Source Files

| File | Key functions |
|------|--------------|
| `loops/enrichment_review.py` | `submit_clarification_answers`, `_supersede_answered_suggestions` |
| `loops/enrichment_orchestration.py` | `orchestrate_clarification_refinement`, `orchestrate_loop_enrichment` |
| `loops/enrichment.py` | `enrich_loop`, `_apply_suggestion` |
| `loops/service.py` | `request_enrichment` |
| `loops/_repo/events.py` | `answer_loop_clarification`, `resolve_loop_suggestion`, `insert_loop_suggestion`, `insert_loop_event`, `insert_loop_clarification` |
| `loops/_repo/core.py` | `update_loop_fields` |
| `routes/loops/suggestions_clarifications.py` | HTTP endpoints |
| `routes/loops/_common.py` | `run_idempotent_loop_route` |
| `idempotency_flow.py` | `finalize_idempotent_response` |
| `webhooks/service.py` | `queue_deliveries` |
| `loops/_review_workflows/execution.py` | `answer_enrichment_review_session_clarifications`, `_enrichment_follow_through` |
| `storage/interaction_store.py` | `record_interaction` |
