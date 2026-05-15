-- MindForge PGLite Schema (SQLite-compatible)
-- Generated: 2026-05-13

-- WritingProfile (singleton)
CREATE TABLE IF NOT EXISTS writing_profile (
    id                  TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    tone                TEXT NOT NULL DEFAULT 'semi-formal',
    sentence_length     TEXT NOT NULL DEFAULT 'medium',
    first_person        TEXT NOT NULL DEFAULT 'I',
    signature_phrases   TEXT NOT NULL DEFAULT '[]',
    greeting_style      TEXT NOT NULL DEFAULT 'Hi [Name],',
    signoff_style       TEXT NOT NULL DEFAULT 'Cheers',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Task
CREATE TABLE IF NOT EXISTS task (
    id              TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    skill_id        TEXT,
    skill_version   INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    task_type       TEXT NOT NULL DEFAULT 'general',
    project_id      TEXT,
    description     TEXT NOT NULL,
    context         TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    FOREIGN KEY (skill_id) REFERENCES skill(id)
);

CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
CREATE INDEX IF NOT EXISTS idx_task_project ON task(project_id);

-- TaskStep
CREATE TABLE IF NOT EXISTS task_step (
    id                       TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    task_id                  TEXT NOT NULL,
    node_id                  TEXT NOT NULL,
    agent_role               TEXT NOT NULL,
    step_order               INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'pending',
    action_taken             TEXT,
    result                   TEXT,
    approval_required        INTEGER NOT NULL DEFAULT 0,
    approval_status          TEXT,
    approval_edited_content  TEXT,
    approved_at              TEXT,
    error                    TEXT,
    retry_count              INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_step_task ON task_step(task_id);

-- Integration
CREATE TABLE IF NOT EXISTS integration (
    id                 TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    app_name           TEXT NOT NULL UNIQUE,
    auth_token_enc     TEXT NOT NULL,
    refresh_token_enc  TEXT,
    token_key_id       TEXT NOT NULL DEFAULT 'local',
    status             TEXT NOT NULL DEFAULT 'active',
    last_sync_at       TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    extra              TEXT,
    permissions        TEXT NOT NULL DEFAULT '[]',
    allowed_agents     TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_integration_app ON integration(app_name);
CREATE INDEX IF NOT EXISTS idx_integration_status ON integration(status);

-- Skill
CREATE TABLE IF NOT EXISTS skill (
    id                TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    name              TEXT NOT NULL UNIQUE,
    description       TEXT NOT NULL,
    category          TEXT NOT NULL,
    agent_role        TEXT NOT NULL,
    yaml_content      TEXT NOT NULL,
    version           INTEGER NOT NULL DEFAULT 1,
    tools             TEXT NOT NULL DEFAULT '[]',
    memory_layers     TEXT NOT NULL DEFAULT '[]',
    trigger_type      TEXT NOT NULL DEFAULT 'keyword',
    trigger_keywords  TEXT,
    trigger_intents   TEXT,
    success_count     INTEGER NOT NULL DEFAULT 0,
    failure_count     INTEGER NOT NULL DEFAULT 0,
    last_run_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_name ON skill(name);
CREATE INDEX IF NOT EXISTS idx_skill_category ON skill(category);

-- EpisodicMemory
CREATE TABLE IF NOT EXISTS episodic_memory (
    id              TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    project_id      TEXT,
    task_id         TEXT,
    task_type       TEXT NOT NULL,
    agent_role      TEXT NOT NULL,
    summary         TEXT NOT NULL,
    outcome_status  TEXT NOT NULL,
    feedback        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_episodic_project ON episodic_memory(project_id);
CREATE INDEX IF NOT EXISTS idx_episodic_task_type ON episodic_memory(task_type);
CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memory(created_at);

-- UserPreference (singleton)
CREATE TABLE IF NOT EXISTS user_preference (
    id                                   TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    proactive_monitoring_enabled          INTEGER NOT NULL DEFAULT 1,
    email_check_interval_minutes          INTEGER NOT NULL DEFAULT 30,
    calendar_check_interval_minutes       INTEGER NOT NULL DEFAULT 60,
    billing_alert_threshold_usd           INTEGER NOT NULL DEFAULT 50,
    notification_channel                  TEXT NOT NULL DEFAULT 'dashboard',
    notification_handle                   TEXT,
    -- Set to 1 by POST /api/onboarding (or /api/onboarding/skip). The
    -- frontend first-run gate keys off this; the singleton row is created
    -- at first migration so the previous "id == ''" signal never fired
    -- for real users (#72).
    onboarding_completed                  INTEGER NOT NULL DEFAULT 0,
    created_at                           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Enforce singletons (INSERT OR IGNORE is SQLite; for PGLite use ON CONFLICT DO NOTHING)
INSERT OR IGNORE INTO writing_profile (id) VALUES (lower(hex(randomblob(16))));
INSERT OR IGNORE INTO user_preference (id) VALUES (lower(hex(randomblob(16))));
