CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    niche_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    status TEXT NOT NULL,
    event_type TEXT NOT NULL,
    action_type TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.3,
    sample_size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    knowledge_id TEXT NOT NULL REFERENCES knowledge(id),
    video_id TEXT REFERENCES videos(id),
    outcome_note TEXT NOT NULL,
    metric_value REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    status TEXT NOT NULL,
    current_job_id TEXT,
    metadata_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    assigned_worker_id TEXT REFERENCES workers(id),
    input_data_json TEXT NOT NULL,
    output_data_json TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    video_id TEXT REFERENCES videos(id),
    attempt INTEGER NOT NULL,
    reviewer_type TEXT NOT NULL,
    verdict TEXT NOT NULL,
    overall_score REAL,
    scores_json TEXT,
    problems_json TEXT,
    corrections_json TEXT,
    raw_response TEXT,
    created_at TEXT NOT NULL
);
