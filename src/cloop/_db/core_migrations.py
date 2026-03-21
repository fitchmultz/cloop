"""Incremental core database migration scripts.

Purpose:
    Store ordered incremental SQL migrations for upgrading existing core
    databases to the current schema version.

Responsibilities:
    - Define per-version migration SQL keyed by target schema version
    - Keep upgrade steps canonical and replayable by the migration runner
    - Preserve migration history separate from fresh-install bootstrap SQL

Non-scope:
    - Executing migrations or handling savepoints
    - Defining the RAG schema or connection defaults

Scope:
    - Static migration SQL only
    - No runtime orchestration or version checks

Usage:
    Imported by `cloop.db` and `cloop._db.schema_ops` callers when applying
    pending core-schema upgrades.

Invariants/Assumptions:
    - Keys are integer schema versions in ascending historical order
    - Each migration produces the schema expected by its version key
"""

# ruff: noqa: E501

from __future__ import annotations

_CORE_MIGRATIONS: dict[int, str] = {
    43: """
    CREATE TABLE continuity_last_seen_markers (
        entity_kind TEXT NOT NULL CHECK (
            entity_kind IN (
                'planning_session',
                'review_session',
                'working_set',
                'cohort_snapshot',
                'workflow_thread'
            )
        ),
        entity_key TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        working_set_id INTEGER,
        workflow_thread_id TEXT,
        observed_fingerprint TEXT NOT NULL,
        observed_state_json TEXT NOT NULL DEFAULT '{}',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (entity_kind, entity_key)
    );

    CREATE INDEX idx_continuity_last_seen_observed_at
        ON continuity_last_seen_markers(observed_at_utc DESC, entity_kind, entity_key);

    CREATE INDEX idx_continuity_last_seen_working_set
        ON continuity_last_seen_markers(working_set_id, observed_at_utc DESC);

    CREATE INDEX idx_continuity_last_seen_thread
        ON continuity_last_seen_markers(workflow_thread_id, observed_at_utc DESC);
    """,
    42: """
    CREATE TABLE continuity_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        description TEXT NOT NULL,
        occurred_at_utc TEXT NOT NULL,
        launch_location_json TEXT,
        outcome_json TEXT NOT NULL,
        resume_location_json TEXT,
        working_set_id INTEGER,
        workflow_thread_id TEXT NOT NULL,
        workflow_thread_kind TEXT NOT NULL,
        workflow_thread_title TEXT NOT NULL,
        workflow_thread_summary TEXT,
        parent_outcome_id INTEGER REFERENCES continuity_outcomes(id) ON DELETE SET NULL,
        dedupe_key TEXT NOT NULL,
        source_surface TEXT NOT NULL,
        signal_level TEXT NOT NULL CHECK (signal_level IN ('high', 'secondary')),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_continuity_outcomes_occurred_at
        ON continuity_outcomes(occurred_at_utc DESC, id DESC);

    CREATE INDEX idx_continuity_outcomes_thread
        ON continuity_outcomes(workflow_thread_id, occurred_at_utc DESC, id DESC);

    CREATE INDEX idx_continuity_outcomes_signal
        ON continuity_outcomes(signal_level, occurred_at_utc DESC, id DESC);

    CREATE INDEX idx_continuity_outcomes_working_set
        ON continuity_outcomes(working_set_id, occurred_at_utc DESC, id DESC);

    CREATE TABLE continuity_resume_anchors (
        anchor_kind TEXT PRIMARY KEY CHECK (anchor_kind IN ('planning', 'review')),
        review_focus TEXT NOT NULL CHECK (review_focus IN ('planning', 'relationship', 'enrichment')),
        session_id INTEGER NOT NULL,
        visited_at_utc TEXT NOT NULL,
        launch_location_json TEXT,
        resume_location_json TEXT,
        outcome_title TEXT,
        outcome_summary TEXT,
        working_set_id INTEGER,
        workflow_thread_id TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    41: """
    ALTER TABLE interactions ADD COLUMN tool_results TEXT NOT NULL DEFAULT '[]';
    """,
    40: """
    CREATE TABLE working_set_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_type TEXT NOT NULL CHECK (subject_type IN ('working_set', 'working_set_context')),
        subject_id INTEGER NOT NULL,
        event_type TEXT NOT NULL CHECK (
            event_type IN (
                'create',
                'update',
                'delete',
                'add_item',
                'bulk_add_items',
                'remove_item',
                'reorder',
                'context_update',
                'undo'
            )
        ),
        before_state_json TEXT NOT NULL DEFAULT '{}',
        after_state_json TEXT NOT NULL DEFAULT '{}',
        undone_by_event_id INTEGER REFERENCES working_set_events(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_working_set_events_subject
        ON working_set_events(subject_type, subject_id, id DESC);

    CREATE INDEX idx_working_set_events_latest_reversible
        ON working_set_events(subject_type, subject_id, id DESC)
        WHERE event_type != 'undo' AND undone_by_event_id IS NULL;
    """,
    39: """
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
    """,
    38: """
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
    """,
    37: """
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
        ON review_sessions(current_loop_id)
        WHERE current_loop_id IS NOT NULL;
    """,
    36: """
    ALTER TABLE loop_links ADD COLUMN link_state TEXT NOT NULL DEFAULT 'active';
    ALTER TABLE loop_links ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP;

    UPDATE loop_links
    SET relationship_type = 'duplicate',
        link_state = 'resolved'
    WHERE relationship_type = 'duplicate_resolved';

    CREATE TEMP TABLE loop_links_ranked AS
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY loop_id, related_loop_id, relationship_type
                ORDER BY
                    CASE link_state
                        WHEN 'resolved' THEN 3
                        WHEN 'active' THEN 2
                        WHEN 'dismissed' THEN 1
                        ELSE 0
                    END DESC,
                    CASE WHEN confidence IS NULL THEN -1.0 ELSE confidence END DESC,
                    created_at DESC,
                    id DESC
            ) AS rank_order
        FROM loop_links;

    DELETE FROM loop_links
    WHERE id IN (
        SELECT id
        FROM loop_links_ranked
        WHERE rank_order > 1
    );

    DROP TABLE loop_links_ranked;
    DROP INDEX idx_loop_links_unique;
    CREATE UNIQUE INDEX idx_loop_links_unique
        ON loop_links(loop_id, related_loop_id, relationship_type);
    CREATE INDEX idx_loop_links_loop_type_state_confidence
        ON loop_links(loop_id, relationship_type, link_state, confidence DESC, related_loop_id);
    """,
    35: """
    ALTER TABLE loop_embeddings ADD COLUMN source_text_hash TEXT NOT NULL DEFAULT '';
    """,
    34: """
    DELETE FROM loop_clarifications
    WHERE id IN (
        SELECT duplicate.id
        FROM loop_clarifications AS duplicate
        JOIN loop_clarifications AS keeper
          ON duplicate.loop_id = keeper.loop_id
         AND duplicate.question = keeper.question
         AND duplicate.answer IS NULL
         AND keeper.answer IS NULL
         AND duplicate.id > keeper.id
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_loop_clarifications_pending_question
        ON loop_clarifications(loop_id, question)
        WHERE answer IS NULL;
    """,
    33: """
    ALTER TABLE loops ADD COLUMN due_date TEXT;

    UPDATE loops
    SET due_date = substr(due_at_utc, 1, 10)
    WHERE due_at_utc IS NOT NULL
      AND due_date IS NULL
      AND (time(due_at_utc) = '23:59:59' OR time(due_at_utc) = '23:59:00');
    """,
    32: """
    ALTER TABLE loop_events ADD COLUMN source_task_name TEXT;
    ALTER TABLE loop_events ADD COLUMN source_slot_key TEXT;
    CREATE UNIQUE INDEX idx_loop_events_scheduler_slot
        ON loop_events(source_task_name, source_slot_key, event_type)
        WHERE source_task_name IS NOT NULL AND source_slot_key IS NOT NULL;

    ALTER TABLE loop_nudges ADD COLUMN last_slot_key TEXT;

    DROP TABLE IF EXISTS scheduler_push_deliveries;
    DROP TABLE IF EXISTS scheduler_task_runs;
    DROP TABLE IF EXISTS scheduler_task_schedule;
    DROP TABLE IF EXISTS scheduler_task_executions;
    DROP TABLE IF EXISTS scheduler_task_state;
    DROP TABLE IF EXISTS scheduler_task_leases;

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

    DROP TABLE IF EXISTS webhook_delivery_attempts;
    ALTER TABLE webhook_deliveries RENAME TO webhook_deliveries_old;

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

    INSERT INTO webhook_deliveries (
        id,
        subscription_id,
        event_id,
        event_type,
        source_payload_json,
        last_attempt_payload_json,
        status,
        http_status,
        response_body,
        error_message,
        signature_header,
        attempt_count,
        last_attempted_at,
        next_retry_at_epoch,
        created_at,
        updated_at
    )
    SELECT
        id,
        subscription_id,
        event_id,
        event_type,
        source_payload_json,
        last_attempt_payload_json,
        CASE
            WHEN status = 'success' THEN 'succeeded'
            WHEN status = 'pending' THEN 'queued'
            ELSE status
        END,
        http_status,
        response_body,
        error_message,
        signature_header,
        attempt_count,
        last_attempted_at,
        CASE
            WHEN next_retry_at IS NULL THEN NULL
            ELSE unixepoch(next_retry_at)
        END,
        created_at,
        updated_at
    FROM webhook_deliveries_old;

    DROP TABLE webhook_deliveries_old;

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
    CREATE INDEX idx_webhook_delivery_attempts_delivery
        ON webhook_delivery_attempts(delivery_id, attempt_number DESC);
    """,
    31: """
    CREATE TABLE scheduler_task_executions (
        run_id TEXT PRIMARY KEY,
        task_name TEXT NOT NULL,
        owner_token TEXT NOT NULL,
        started_at TEXT NOT NULL,
        heartbeat_at TEXT,
        finished_at TEXT,
        status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'abandoned')),
        error TEXT,
        result_json TEXT
    );

    CREATE INDEX idx_scheduler_task_executions_task_started
        ON scheduler_task_executions(task_name, started_at DESC);
    """,
    30: """
    CREATE TABLE webhook_deliveries_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscription_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        source_payload_json TEXT NOT NULL,
        last_attempt_payload_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        http_status INTEGER,
        response_body TEXT,
        error_message TEXT,
        signature_header TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_attempted_at TEXT,
        next_retry_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
        FOREIGN KEY(event_id) REFERENCES loop_events(id) ON DELETE CASCADE
    );

    INSERT INTO webhook_deliveries_new (
        id,
        subscription_id,
        event_id,
        event_type,
        source_payload_json,
        last_attempt_payload_json,
        status,
        http_status,
        response_body,
        error_message,
        signature_header,
        attempt_count,
        last_attempted_at,
        next_retry_at,
        created_at,
        updated_at
    )
    SELECT
        id,
        subscription_id,
        event_id,
        event_type,
        payload_json,
        NULL,
        status,
        http_status,
        response_body,
        error_message,
        signature,
        attempt_count,
        NULL,
        next_retry_at,
        created_at,
        updated_at
    FROM webhook_deliveries;

    DROP TABLE webhook_deliveries;
    ALTER TABLE webhook_deliveries_new RENAME TO webhook_deliveries;

    CREATE INDEX idx_webhook_deliveries_status ON webhook_deliveries(status);
    CREATE INDEX idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at)
        WHERE status = 'pending';
    CREATE INDEX idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
    """,
    29: """
    DROP TABLE IF EXISTS scheduler_runs;

    CREATE TABLE scheduler_task_leases (
        task_name TEXT PRIMARY KEY,
        owner_token TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        heartbeat_at TEXT NOT NULL,
        lease_until TEXT NOT NULL
    );

    CREATE INDEX idx_scheduler_task_leases_until ON scheduler_task_leases(lease_until);

    CREATE TABLE scheduler_task_state (
        task_name TEXT PRIMARY KEY,
        last_started_at TEXT,
        last_finished_at TEXT,
        last_success_at TEXT,
        last_failure_at TEXT,
        last_error TEXT,
        last_result_json TEXT,
        next_due_at TEXT,
        runs_count INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX idx_scheduler_task_state_next_due ON scheduler_task_state(next_due_at);
    """,
    28: """
    -- Make loop_id nullable to support system-level events (e.g., REVIEW_GENERATED)
    -- SQLite requires recreating the table to drop NOT NULL constraint
    CREATE TABLE loop_events_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    INSERT INTO loop_events_new (id, loop_id, event_type, payload_json, created_at)
        SELECT id, loop_id, event_type, payload_json, created_at FROM loop_events;

    DROP TABLE loop_events;
    ALTER TABLE loop_events_new RENAME TO loop_events;

    CREATE INDEX idx_loop_events_loop_id ON loop_events(loop_id);
    CREATE INDEX idx_loop_events_type_created ON loop_events(event_type, created_at);
    """,
    27: """
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
    """,
    26: """
    -- Create loop_clarifications table for AI clarification Q&A
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
    """,
    25: """
    -- Create push_subscriptions table for browser push notifications
    CREATE TABLE push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        user_agent TEXT,
        created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_push_subscriptions_endpoint
    ON push_subscriptions(endpoint);
    """,
    24: """
    -- Create loop_nudges table for tracking nudge escalation state
    CREATE TABLE loop_nudges (
        loop_id INTEGER NOT NULL,
        nudge_type TEXT NOT NULL CHECK (nudge_type IN ('due_soon', 'stale', 'blocked')),
        escalation_level INTEGER NOT NULL DEFAULT 0,
        nudge_count INTEGER NOT NULL DEFAULT 0,
        first_nudged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_nudged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_nudge_event_id INTEGER,
        PRIMARY KEY (loop_id, nudge_type),
        FOREIGN KEY (loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        FOREIGN KEY (last_nudge_event_id) REFERENCES loop_events(id) ON DELETE SET NULL
    );

    CREATE INDEX idx_loop_nudges_escalation ON loop_nudges(escalation_level, nudge_type);
    CREATE INDEX idx_loop_nudges_last_nudged ON loop_nudges(last_nudged_at DESC);
    """,
    23: """
    -- Index for metrics queries filtering by event_type + created_at range
    CREATE INDEX idx_loop_events_type_created
        ON loop_events(event_type, created_at);

    -- Index for owner-filtered claim lookups
    CREATE INDEX idx_loop_claims_owner_lease
        ON loop_claims(owner, lease_until);
    """,
    22: """
    -- Scheduler state tracking for periodic tasks
    CREATE TABLE scheduler_runs (
        task_name TEXT PRIMARY KEY,
        last_run_at TEXT NOT NULL,
        last_result_json TEXT,
        runs_count INTEGER NOT NULL DEFAULT 0
    );
    """,
    21: """
    -- Add resolution tracking to loop_suggestions
    ALTER TABLE loop_suggestions ADD COLUMN resolution TEXT;
    ALTER TABLE loop_suggestions ADD COLUMN resolved_at TEXT;
    ALTER TABLE loop_suggestions ADD COLUMN resolved_fields_json TEXT;
    CREATE INDEX idx_loop_suggestions_resolution ON loop_suggestions(resolution);
    """,
    20: """
    -- Index for ORDER BY updated_at DESC queries (list, search, cursor pagination)
    CREATE INDEX idx_loops_updated_at ON loops(updated_at DESC);
    """,
    19: """
    -- Partial index for next-loop candidate queries
    -- Filters to actionable candidates with next_action defined
    CREATE INDEX idx_loops_next_candidates
        ON loops(status, updated_at DESC, captured_at_utc DESC, id DESC)
        WHERE next_action IS NOT NULL;
    """,
    18: """
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
    """,
    17: """
    -- Create loop_templates table for reusable loop patterns
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

    -- Insert system templates
    INSERT INTO loop_templates (name, description, raw_text_pattern, defaults_json, is_system) VALUES
        ('Daily Standup', 'Daily standup notes template', 'Standup notes for {{date}}\n\nYesterday:\n- \n\nToday:\n- \n\nBlockers:\n- ', '{"tags": ["standup", "daily"], "time_minutes": 15}', 1),
        ('Weekly Review', 'Weekly review template', 'Weekly review - {{week}} of {{year}}\n\nAccomplishments:\n- \n\nPriorities for next week:\n- \n\nOpen items:\n- ', '{"tags": ["review", "weekly"], "time_minutes": 30}', 1),
        ('Meeting Notes', 'Meeting notes template', 'Meeting: [Title]\nDate: {{date}}\nTime: {{time}}\nAttendees: \n\nAgenda:\n- \n\nNotes:\n- \n\nAction items:\n- ', '{"tags": ["meeting"], "actionable": true}', 1),
        ('Bug Report', 'Bug report template', 'Bug: [Description]\n\nSteps to reproduce:\n1. \n\nExpected:\n\nActual:\n\nEnvironment:', '{"tags": ["bug"], "blocked": true}', 1),
        ('Quick Task', 'Simple actionable task template', '', '{"actionable": true, "time_minutes": 30}', 1);
    """,
    2: """
    CREATE TABLE loops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_text TEXT NOT NULL,
        title TEXT,
        status TEXT NOT NULL,
        captured_at_utc TEXT NOT NULL,
        captured_tz_offset_min INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_at TEXT
    );

    CREATE INDEX idx_loops_status ON loops(status);
    CREATE INDEX idx_loops_captured_at ON loops(captured_at_utc);

    CREATE TABLE loop_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_events_loop_id ON loop_events(loop_id);
    """,
    3: """
    ALTER TABLE loops ADD COLUMN summary TEXT;
    ALTER TABLE loops ADD COLUMN definition_of_done TEXT;
    ALTER TABLE loops ADD COLUMN next_action TEXT;
    ALTER TABLE loops ADD COLUMN due_at_utc TEXT;
    ALTER TABLE loops ADD COLUMN snooze_until_utc TEXT;
    ALTER TABLE loops ADD COLUMN time_minutes INTEGER;
    ALTER TABLE loops ADD COLUMN activation_energy INTEGER;
    ALTER TABLE loops ADD COLUMN urgency REAL;
    ALTER TABLE loops ADD COLUMN importance REAL;
    ALTER TABLE loops ADD COLUMN project_id INTEGER;
    ALTER TABLE loops ADD COLUMN user_locks_json TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE loops ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE loops ADD COLUMN enrichment_state TEXT NOT NULL DEFAULT 'idle';

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

    CREATE TABLE loop_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        suggestion_json TEXT NOT NULL,
        model TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_suggestions_loop_id ON loop_suggestions(loop_id);
    """,
    4: """
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
    """,
    5: """
    UPDATE loops SET status = 'actionable' WHERE status = 'active';
    UPDATE loops SET status = 'blocked' WHERE status = 'waiting';
    UPDATE loops SET status = 'completed' WHERE status = 'done';
    """,
    6: """
    CREATE TEMP TABLE tag_merge AS
        SELECT LOWER(name) AS lname, MIN(id) AS keep_id
        FROM tags
        GROUP BY LOWER(name);

    UPDATE loop_tags
    SET tag_id = (
        SELECT keep_id
        FROM tag_merge
        WHERE lname = (
            SELECT LOWER(name) FROM tags WHERE id = loop_tags.tag_id
        )
    );

    DELETE FROM tags WHERE id NOT IN (SELECT keep_id FROM tag_merge);
    UPDATE tags SET name = LOWER(name);
    DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM loop_tags);
    DROP TABLE tag_merge;
    """,
    7: """
    UPDATE loops
    SET updated_at = created_at
    WHERE updated_at IS NULL OR updated_at = '';
    """,
    8: """
    ALTER TABLE loops ADD COLUMN blocked_reason TEXT;
    """,
    9: """
    ALTER TABLE loops ADD COLUMN completion_note TEXT;
    """,
    10: """
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
    """,
    11: """
    CREATE TABLE loop_views (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        query TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_loop_views_name ON loop_views(name);
    """,
    12: """
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
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        http_status INTEGER,
        response_body TEXT,
        error_message TEXT,
        signature TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        next_retry_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
        FOREIGN KEY(event_id) REFERENCES loop_events(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_webhook_deliveries_status ON webhook_deliveries(status);
    CREATE INDEX idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at)
        WHERE status = 'pending';
    CREATE INDEX idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
    """,
    13: """
    CREATE TABLE loop_claims (
        loop_id INTEGER PRIMARY KEY,
        owner TEXT NOT NULL,
        claim_token TEXT NOT NULL,
        leased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        lease_until TEXT NOT NULL,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_claims_lease_until ON loop_claims(lease_until);
    """,
    14: """
    ALTER TABLE loops ADD COLUMN recurrence_rrule TEXT;
    ALTER TABLE loops ADD COLUMN recurrence_tz TEXT;
    ALTER TABLE loops ADD COLUMN next_due_at_utc TEXT;
    ALTER TABLE loops ADD COLUMN recurrence_enabled INTEGER NOT NULL DEFAULT 0;

    CREATE INDEX idx_loops_recurrence_enabled ON loops(recurrence_enabled);
    CREATE INDEX idx_loops_next_due_at ON loops(next_due_at_utc) WHERE recurrence_enabled = 1;
    """,
    15: """
    -- Add parent_loop_id for hierarchical subtask relationships
    ALTER TABLE loops ADD COLUMN parent_loop_id INTEGER REFERENCES loops(id) ON DELETE SET NULL;

    -- Create index for parent-child queries
    CREATE INDEX idx_loops_parent_id ON loops(parent_loop_id);

    -- Create loop_dependencies table for explicit blocked-by relationships
    CREATE TABLE loop_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        depends_on_loop_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        FOREIGN KEY(depends_on_loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        UNIQUE(loop_id, depends_on_loop_id)
    );

    -- Index for finding what blocks a loop
    CREATE INDEX idx_loop_dependencies_loop_id ON loop_dependencies(loop_id);

    -- Index for finding what depends on a loop (for cascade checks)
    CREATE INDEX idx_loop_dependencies_depends_on ON loop_dependencies(depends_on_loop_id);
    """,
    16: """
    -- Create time_sessions table for tracking actual time spent on loops
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

    -- Index for finding sessions by loop
    CREATE INDEX idx_time_sessions_loop_id ON time_sessions(loop_id);

    -- Index for finding active sessions (where ended_at IS NULL)
    CREATE INDEX idx_time_sessions_active ON time_sessions(loop_id, ended_at)
        WHERE ended_at IS NULL;
    """,
}

__all__ = ["_CORE_MIGRATIONS"]
