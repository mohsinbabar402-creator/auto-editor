"""
Persistent Knowledge Base — Canonical SQL Database Engine (Phase 17)

PURPOSE:
    ACID-compliant SQL database layer for durable knowledge persistence.
    Provides thread-safe connections, transaction management, migration execution,
    and normalized querying.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple


SCHEMA_MIGRATION_V1 = """
-- Model Execution Registry
CREATE TABLE IF NOT EXISTS model_runs (
    id TEXT PRIMARY KEY,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    task_type TEXT NOT NULL,
    input_reference TEXT,
    output_reference TEXT,
    latency_ms INTEGER DEFAULT 0,
    token_usage_json TEXT,
    success INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Creative Decision Records
CREATE TABLE IF NOT EXISTS creative_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    clip_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    decision_payload_json TEXT NOT NULL,
    reasoning_summary TEXT NOT NULL,
    model_run_id TEXT,
    memory_context_ids_json TEXT,
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(model_run_id) REFERENCES model_runs(id)
);

-- Learning Events (Immutable Evidence Trail)
CREATE TABLE IF NOT EXISTS learning_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    confidence_weight REAL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

-- Knowledge Patterns (Learned Strategic Beliefs)
CREATE TABLE IF NOT EXISTS knowledge_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    statement TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    evidence_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    source_event_ids_json TEXT,
    version INTEGER DEFAULT 1,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    account_id TEXT,
    project_id TEXT,
    counterexamples_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Experiments Framework
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    variant_a_json TEXT NOT NULL,
    variant_b_json TEXT NOT NULL,
    target_metrics_json TEXT NOT NULL,
    sample_size_a INTEGER DEFAULT 0,
    sample_size_b INTEGER DEFAULT 0,
    results_a_json TEXT,
    results_b_json TEXT,
    status TEXT NOT NULL,
    winner TEXT DEFAULT 'INCONCLUSIVE',
    confidence REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indices for Fast Filtered Scopes
CREATE INDEX IF NOT EXISTS idx_decisions_project_clip ON creative_decisions(project_id, clip_id);
CREATE INDEX IF NOT EXISTS idx_events_type_source ON learning_events(event_type, source_id);
CREATE INDEX IF NOT EXISTS idx_events_account_project ON learning_events(account_id, project_id);
CREATE INDEX IF NOT EXISTS idx_patterns_type_status ON knowledge_patterns(pattern_type, status);
CREATE INDEX IF NOT EXISTS idx_patterns_scope ON knowledge_patterns(scope, account_id, project_id);
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);

-- Phase 18/19: Character Bible
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    age_range TEXT,
    gender_presentation TEXT,
    physical_description TEXT,
    face_description TEXT,
    hair TEXT,
    eyes TEXT,
    skin_description TEXT,
    body_type TEXT,
    wardrobe TEXT,
    signature_items_json TEXT,
    personality TEXT,
    speech_style TEXT,
    voice_id TEXT,
    voice_provider TEXT DEFAULT 'elevenlabs',
    voice_version TEXT,
    visual_style TEXT,
    negative_constraints_json TEXT,
    reference_asset_paths_json TEXT,
    version INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_characters_cid ON characters(character_id);
CREATE INDEX IF NOT EXISTS idx_characters_active ON characters(is_active);

-- Phase 18/19: World Bible & Style
CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    architecture TEXT,
    walls TEXT,
    windows TEXT,
    furniture TEXT,
    lighting TEXT,
    time_of_day TEXT,
    weather TEXT,
    props_json TEXT,
    visual_constraints_json TEXT,
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_locations_lid ON locations(location_id);

CREATE TABLE IF NOT EXISTS style_bibles (
    id TEXT PRIMARY KEY,
    style_id TEXT NOT NULL,
    name TEXT NOT NULL,
    lens TEXT,
    color_palette TEXT,
    lighting_style TEXT,
    camera_defaults TEXT,
    depth_of_field TEXT,
    grain_texture TEXT,
    aspect_ratio TEXT DEFAULT '9:16',
    negative_style_json TEXT,
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_style_bibles_sid ON style_bibles(style_id);

-- Phase 18/19: Story Bible & Episodes
CREATE TABLE IF NOT EXISTS story_bibles (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL UNIQUE,
    series_name TEXT NOT NULL,
    genre TEXT,
    premise TEXT,
    tone TEXT,
    themes_json TEXT,
    world_rules_json TEXT,
    character_ids_json TEXT,
    location_ids_json TEXT,
    visual_style_id TEXT,
    audio_style TEXT,
    canon_events_json TEXT,
    open_threads_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_bibles (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL UNIQUE,
    story_id TEXT NOT NULL,
    episode_number INTEGER DEFAULT 1,
    title TEXT NOT NULL,
    story_arc TEXT,
    previous_episode_summary TEXT,
    current_conflict TEXT,
    character_states_json TEXT,
    location_states_json TEXT,
    important_props_json TEXT,
    open_questions_json TEXT,
    resolved_questions_json TEXT,
    visual_continuity TEXT,
    audio_continuity TEXT,
    canon_status TEXT DEFAULT 'CANON',
    scene_ids_json TEXT,
    final_artifact_path TEXT,
    analytics_snapshot_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(story_id) REFERENCES story_bibles(story_id)
);
CREATE INDEX IF NOT EXISTS idx_episodes_story ON episode_bibles(story_id, episode_number);

-- Phase 18/19: Scene Graph
CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL UNIQUE,
    episode_id TEXT NOT NULL,
    scene_number INTEGER NOT NULL,
    scene_name TEXT NOT NULL,
    description TEXT,
    character_ids_json TEXT,
    location_id TEXT,
    camera_json TEXT,
    actions_json TEXT,
    dialogue_lines_json TEXT,
    transition_in TEXT,
    transition_out TEXT,
    previous_scene_state TEXT,
    current_state TEXT,
    next_scene_intent TEXT,
    prompt_text TEXT,
    prompt_version TEXT,
    duration_target_sec REAL DEFAULT 5.0,
    generation_job_id TEXT,
    selected_candidate_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_episode ON scenes(episode_id, scene_number);

-- Phase 18/19: Candidate Manager
CREATE TABLE IF NOT EXISTS scene_candidates (
    candidate_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    artifact_path TEXT,
    artifact_hash TEXT,
    file_size INTEGER DEFAULT 0,
    duration_sec REAL DEFAULT 0.0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    scores_json TEXT,
    overall_score REAL DEFAULT 0.0,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_scene ON scene_candidates(scene_id, overall_score);
"""


class KnowledgeDatabase:
    """
    Canonical SQL Database Engine for long-lived production knowledge.
    Manages connections, schema initialization, transactions, and concurrency locking.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = f"file:memdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._is_uri = True
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_path)
            self._is_uri = False

        self._lock = threading.RLock()
        self._local = threading.local()
        self._all_conns = set()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                uri=self._is_uri,
                timeout=30.0,
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode; transactions handled explicitly
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign keys for high performance and integrity
            if not self._is_uri:
                conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.conn = conn
            with self._lock:
                self._all_conns.add(conn)
        return self._local.conn

    def _init_database(self) -> None:
        """Run schema migrations on startup."""
        with self._lock:
            conn = self._get_connection()
            conn.executescript(SCHEMA_MIGRATION_V1)

    @contextlib.contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Thread-safe ACID transaction context.
        Rolls back automatically on unhandled exceptions.
        """
        with self._lock:
            conn = self._get_connection()
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
            try:
                yield cur
                conn.execute("COMMIT;")
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                cur.close()

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        """Execute a query and return rows."""
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            try:
                cur.execute(query, params)
                return cur.fetchall()
            finally:
                cur.close()

    def execute_single(self, query: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            try:
                cur.execute(query, params)
                return cur.fetchone()
            finally:
                cur.close()

    def close(self) -> None:
        with self._lock:
            for c in list(self._all_conns):
                try:
                    c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                except Exception:
                    pass
                try:
                    c.close()
                except Exception:
                    pass
            self._all_conns.clear()
            self._local.conn = None
