"""Canonical core database bootstrap schema.

Purpose:
    Hold the full bootstrap SQL for the core application database used by
    loops, notes, reviews, planning, webhooks, and related features.

Responsibilities:
    - Define the fresh-install core schema in one canonical SQL script
    - Keep core-table/index declarations version-aligned with migrations
    - Avoid duplicating bootstrap SQL across runtime modules

Non-scope:
    - Incremental migration scripts for older schemas
    - SQL execution or connection management

Scope:
    - Static bootstrap SQL only
    - No runtime logic beyond constant definition

Usage:
    Imported by `cloop.db` when initializing a fresh core database.

Invariants/Assumptions:
    - The bootstrap schema matches `SCHEMA_VERSION`
    - Fresh installs should not require replaying migrations
"""

# ruff: noqa: E501

from __future__ import annotations

_CORE_SCHEMA = """
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    model TEXT,
    latency_ms REAL,
    request_payload TEXT,
    response_payload TEXT,
    tool_calls TEXT,
    selected_chunks TEXT,
    token_estimate INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE loops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    definition_of_done TEXT,
    next_action TEXT,
    status TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    captured_tz_offset_min INTEGER NOT NULL,
    due_date TEXT,
    due_at_utc TEXT,
    snooze_until_utc TEXT,
    time_minutes INTEGER,
    activation_energy INTEGER,
    urgency REAL,
    importance REAL,
    project_id INTEGER,
    blocked_reason TEXT,
    completion_note TEXT,
    user_locks_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    enrichment_state TEXT NOT NULL DEFAULT 'idle',
    recurrence_rrule TEXT,
    recurrence_tz TEXT,
    next_due_at_utc TEXT,
    recurrence_enabled INTEGER NOT NULL DEFAULT 0,
    parent_loop_id INTEGER REFERENCES loops(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX idx_loops_status ON loops(status);
CREATE INDEX idx_loops_captured_at ON loops(captured_at_utc);
CREATE INDEX idx_loops_updated_at ON loops(updated_at DESC);
CREATE INDEX idx_loops_recurrence_enabled ON loops(recurrence_enabled);
CREATE INDEX idx_loops_next_due_at ON loops(next_due_at_utc) WHERE recurrence_enabled = 1;
CREATE INDEX idx_loops_parent_id ON loops(parent_loop_id);

CREATE TABLE loop_tags (
    loop_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (loop_id, tag_id),
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_tags_loop_id ON loop_tags(loop_id);
CREATE INDEX idx_loop_tags_tag_id ON loop_tags(tag_id);

CREATE TABLE loop_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    related_loop_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    link_state TEXT NOT NULL DEFAULT 'active',
    confidence REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY(related_loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_loop_links_unique
    ON loop_links(loop_id, related_loop_id, relationship_type);
CREATE INDEX idx_loop_links_loop_type_state_confidence
    ON loop_links(loop_id, relationship_type, link_state, confidence DESC, related_loop_id);

CREATE TABLE loop_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_task_name TEXT,
    source_slot_key TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_events_loop_id ON loop_events(loop_id);
CREATE INDEX idx_loop_events_type_created ON loop_events(event_type, created_at);
CREATE UNIQUE INDEX idx_loop_events_scheduler_slot
    ON loop_events(source_task_name, source_slot_key, event_type)
    WHERE source_task_name IS NOT NULL AND source_slot_key IS NOT NULL;

CREATE TABLE loop_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    suggestion_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolution TEXT,
    resolved_at TEXT,
    resolved_fields_json TEXT,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_suggestions_loop_id ON loop_suggestions(loop_id);
CREATE INDEX idx_loop_suggestions_resolution ON loop_suggestions(resolution);

CREATE TABLE loop_clarifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    answered_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_clarifications_loop_id ON loop_clarifications(loop_id);
CREATE INDEX idx_loop_clarifications_answered ON loop_clarifications(answered_at);
CREATE UNIQUE INDEX idx_loop_clarifications_pending_question
    ON loop_clarifications(loop_id, question)
    WHERE answer IS NULL;

CREATE TABLE loop_embeddings (
    loop_id INTEGER PRIMARY KEY,
    embedding_blob BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_norm REAL NOT NULL,
    embed_model TEXT NOT NULL,
    source_text_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE TABLE idempotency_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER,
    response_body_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    UNIQUE(scope, idempotency_key)
);

CREATE INDEX idx_idempotency_keys_expires_at ON idempotency_keys(expires_at);

CREATE TABLE loop_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    query TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_loop_views_name ON loop_views(name);

CREATE TABLE review_action_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    review_kind TEXT NOT NULL CHECK (review_kind IN ('relationship', 'enrichment')),
    action_type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_action_presets_kind_name
    ON review_action_presets(review_kind, name);

CREATE TABLE review_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    review_kind TEXT NOT NULL CHECK (review_kind IN ('relationship', 'enrichment')),
    query TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    current_loop_id INTEGER REFERENCES loops(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_sessions_kind_name
    ON review_sessions(review_kind, name);
CREATE INDEX idx_review_sessions_current_loop
    ON review_sessions(current_loop_id) WHERE current_loop_id IS NOT NULL;

CREATE TABLE planning_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    prompt TEXT NOT NULL,
    query TEXT,
    options_json TEXT NOT NULL DEFAULT '{}',
    plan_json TEXT NOT NULL,
    current_checkpoint_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_planning_sessions_updated
    ON planning_sessions(updated_at DESC, id DESC);

CREATE TABLE planning_session_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    checkpoint_index INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES planning_sessions(id) ON DELETE CASCADE,
    UNIQUE(session_id, checkpoint_index)
);

CREATE INDEX idx_planning_session_runs_session
    ON planning_session_runs(session_id, checkpoint_index);

CREATE TABLE working_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    last_activated_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_working_sets_last_activated
    ON working_sets(last_activated_at DESC, updated_at DESC, id DESC);

CREATE TABLE working_set_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    working_set_id INTEGER NOT NULL,
    item_type TEXT NOT NULL CHECK (
        item_type IN (
            'loop',
            'planning_session',
            'relationship_review_session',
            'enrichment_review_session',
            'view',
            'memory',
            'query_anchor',
            'state_anchor'
        )
    ),
    item_id INTEGER,
    label TEXT NOT NULL,
    description TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(working_set_id) REFERENCES working_sets(id) ON DELETE CASCADE
);

CREATE INDEX idx_working_set_items_parent_position
    ON working_set_items(working_set_id, position, id);

CREATE TABLE working_set_context (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    active_working_set_id INTEGER REFERENCES working_sets(id) ON DELETE SET NULL,
    focus_mode_enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO working_set_context (singleton_id, active_working_set_id, focus_mode_enabled)
VALUES (1, NULL, 0);

CREATE TABLE webhook_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    event_types TEXT NOT NULL DEFAULT '["*"]',
    active BOOLEAN NOT NULL DEFAULT 1,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_webhook_subscriptions_active ON webhook_subscriptions(active);

CREATE TABLE webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    source_payload_json TEXT NOT NULL,
    last_attempt_payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'in_flight', 'succeeded', 'dead_letter')),
    http_status INTEGER,
    response_body TEXT,
    error_message TEXT,
    signature_header TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    active_attempt_number INTEGER,
    last_attempted_at TEXT,
    next_retry_at_epoch INTEGER,
    lease_owner TEXT,
    lease_until_epoch INTEGER,
    last_connect_ip TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES loop_events(id) ON DELETE CASCADE
);

CREATE TABLE webhook_delivery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    request_bytes BLOB,
    signature_header TEXT,
    http_status INTEGER,
    response_body TEXT,
    error_message TEXT,
    connect_ip TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(delivery_id) REFERENCES webhook_deliveries(id) ON DELETE CASCADE,
    UNIQUE(delivery_id, attempt_number)
);

CREATE INDEX idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at_epoch)
    WHERE status = 'queued';
CREATE INDEX idx_webhook_deliveries_inflight_lease ON webhook_deliveries(lease_until_epoch)
    WHERE status = 'in_flight';
CREATE INDEX idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
CREATE INDEX idx_webhook_delivery_attempts_delivery ON webhook_delivery_attempts(delivery_id, attempt_number DESC);

CREATE TABLE loop_claims (
    loop_id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    claim_token TEXT NOT NULL,
    leased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_until TEXT NOT NULL,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_claims_lease_until ON loop_claims(lease_until);
CREATE INDEX idx_loop_claims_owner_lease ON loop_claims(owner, lease_until);

CREATE TABLE loop_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    depends_on_loop_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY(depends_on_loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    UNIQUE(loop_id, depends_on_loop_id)
);

CREATE INDEX idx_loop_dependencies_loop_id ON loop_dependencies(loop_id);
CREATE INDEX idx_loop_dependencies_depends_on ON loop_dependencies(depends_on_loop_id);

CREATE TABLE time_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_time_sessions_loop_id ON time_sessions(loop_id);
CREATE INDEX idx_time_sessions_active ON time_sessions(loop_id, ended_at) WHERE ended_at IS NULL;

CREATE TABLE loop_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    raw_text_pattern TEXT NOT NULL DEFAULT '',
    defaults_json TEXT NOT NULL DEFAULT '{}',
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_loop_templates_name ON loop_templates(name);
CREATE INDEX idx_loop_templates_is_system ON loop_templates(is_system);

-- Create loop_comments table for threaded discussion on loops
CREATE TABLE loop_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    parent_id INTEGER REFERENCES loop_comments(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    body_md TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_comments_loop_id ON loop_comments(loop_id);
CREATE INDEX idx_loop_comments_parent_id ON loop_comments(parent_id);
CREATE INDEX idx_loop_comments_created_at ON loop_comments(created_at);

-- Scheduler slot coordination and run-state tracking
CREATE TABLE scheduler_task_schedule (
    task_name TEXT PRIMARY KEY,
    next_due_at TEXT,
    last_slot_key TEXT,
    last_started_at TEXT,
    last_finished_at TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_result_json TEXT,
    last_error TEXT,
    runs_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_scheduler_task_schedule_next_due ON scheduler_task_schedule(next_due_at);

CREATE TABLE scheduler_task_runs (
    task_name TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'abandoned')),
    owner_token TEXT,
    lease_until TEXT,
    started_at TEXT,
    heartbeat_at TEXT,
    finished_at TEXT,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_name, slot_key)
);

CREATE INDEX idx_scheduler_task_runs_status_lease
    ON scheduler_task_runs(task_name, status, lease_until);

CREATE TABLE scheduler_push_deliveries (
    task_name TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    push_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    push_count INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (task_name, slot_key, push_kind)
);

-- Nudge tracking for escalation state
CREATE TABLE loop_nudges (
    loop_id INTEGER NOT NULL,
    nudge_type TEXT NOT NULL CHECK (nudge_type IN ('due_soon', 'stale', 'blocked')),
    escalation_level INTEGER NOT NULL DEFAULT 0,
    nudge_count INTEGER NOT NULL DEFAULT 0,
    first_nudged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_nudged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_nudge_event_id INTEGER,
    last_slot_key TEXT,
    PRIMARY KEY (loop_id, nudge_type),
    FOREIGN KEY (loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY (last_nudge_event_id) REFERENCES loop_events(id) ON DELETE SET NULL
);

CREATE INDEX idx_loop_nudges_escalation ON loop_nudges(escalation_level, nudge_type);
CREATE INDEX idx_loop_nudges_last_nudged ON loop_nudges(last_nudged_at DESC);

-- Push notification subscriptions
CREATE TABLE push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_push_subscriptions_endpoint ON push_subscriptions(endpoint);

-- Create memory_entries table for durable assistant memory
CREATE TABLE memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'fact'
        CHECK (category IN ('preference', 'fact', 'commitment', 'context')),
    priority INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'user_stated'
        CHECK (source IN ('user_stated', 'inferred', 'imported', 'system')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_memory_entries_category ON memory_entries(category);
CREATE INDEX idx_memory_entries_priority ON memory_entries(priority DESC);
CREATE INDEX idx_memory_entries_key ON memory_entries(key) WHERE key IS NOT NULL;
CREATE INDEX idx_memory_entries_updated ON memory_entries(updated_at DESC);

-- Insert system templates for fresh installations
INSERT INTO loop_templates (name, description, raw_text_pattern, defaults_json, is_system) VALUES
    ('Daily Standup', 'Daily standup notes template', 'Standup notes for {{date}}\n\nYesterday:\n- \n\nToday:\n- \n\nBlockers:\n- ', '{"tags": ["standup", "daily"], "time_minutes": 15}', 1),
    ('Weekly Review', 'Weekly review template', 'Weekly review - {{week}} of {{year}}\n\nAccomplishments:\n- \n\nPriorities for next week:\n- \n\nOpen items:\n- ', '{"tags": ["review", "weekly"], "time_minutes": 30}', 1),
    ('Meeting Notes', 'Meeting notes template', 'Meeting: [Title]\nDate: {{date}}\nTime: {{time}}\nAttendees: \n\nAgenda:\n- \n\nNotes:\n- \n\nAction items:\n- ', '{"tags": ["meeting"], "actionable": true}', 1),
    ('Bug Report', 'Bug report template', 'Bug: [Description]\n\nSteps to reproduce:\n1. \n\nExpected:\n\nActual:\n\nEnvironment:', '{"tags": ["bug"], "blocked": true}', 1),
    ('Quick Task', 'Simple actionable task template', '', '{"actionable": true, "time_minutes": 30}', 1);
"""

__all__ = ["_CORE_SCHEMA"]
