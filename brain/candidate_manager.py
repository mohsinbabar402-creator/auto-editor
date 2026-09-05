from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from brain.knowledge_database import KnowledgeDatabase


@dataclass
class SceneCandidate:
    candidate_id: str
    scene_id: str
    job_id: str
    created_at: str
    artifact_path: Optional[str] = None
    artifact_hash: Optional[str] = None
    file_size: int = 0
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    scores: Dict[str, float] = None
    overall_score: float = 0.0
    status: str = "PENDING"
    rejection_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.scores is None:
            self.scores = {}


class CandidateSelector:
    def __init__(self, db: KnowledgeDatabase) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        schema = """
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
            scores_json TEXT NOT NULL,
            overall_score REAL DEFAULT 0.0,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_candidates_scene ON scene_candidates(scene_id);
        """
        conn = self.db._get_connection()
        conn.executescript(schema)

    def _row_to_candidate(self, row: sqlite3.Row) -> SceneCandidate:
        return SceneCandidate(
            candidate_id=row["candidate_id"],
            scene_id=row["scene_id"],
            job_id=row["job_id"],
            artifact_path=row["artifact_path"],
            artifact_hash=row["artifact_hash"],
            file_size=row["file_size"],
            duration_sec=row["duration_sec"],
            width=row["width"],
            height=row["height"],
            scores=json.loads(row["scores_json"]),
            overall_score=row["overall_score"],
            status=row["status"],
            rejection_reason=row["rejection_reason"],
            created_at=row["created_at"],
        )

    def create_candidate(self, **kwargs: Any) -> SceneCandidate:
        with self._lock:
            if "created_at" not in kwargs:
                kwargs["created_at"] = datetime.now(timezone.utc).isoformat()
                
            candidate = SceneCandidate(**kwargs)
            
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO scene_candidates (
                        candidate_id, scene_id, job_id, artifact_path, artifact_hash,
                        file_size, duration_sec, width, height, scores_json, overall_score,
                        status, rejection_reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.candidate_id, candidate.scene_id, candidate.job_id,
                        candidate.artifact_path, candidate.artifact_hash, candidate.file_size,
                        candidate.duration_sec, candidate.width, candidate.height,
                        json.dumps(candidate.scores), candidate.overall_score,
                        candidate.status, candidate.rejection_reason, candidate.created_at
                    )
                )
            return candidate

    def get_candidate(self, candidate_id: str) -> Optional[SceneCandidate]:
        row = self.db.execute_single(
            "SELECT * FROM scene_candidates WHERE candidate_id = ?",
            (candidate_id,)
        )
        if row:
            return self._row_to_candidate(row)
        return None

    def get_candidates_for_scene(self, scene_id: str) -> List[SceneCandidate]:
        rows = self.db.execute(
            "SELECT * FROM scene_candidates WHERE scene_id = ? ORDER BY created_at DESC",
            (scene_id,)
        )
        return [self._row_to_candidate(row) for row in rows]

    def score_candidate(self, candidate_id: str, scores: Dict[str, float]) -> SceneCandidate:
        weights = {
            "file_integrity": 0.15,
            "resolution_match": 0.15,
            "duration_match": 0.15,
            "visual_quality": 0.20,
            "prompt_adherence": 0.20,
            "motion_quality": 0.15,
        }
        
        overall_score = 0.0
        for key, weight in weights.items():
            overall_score += scores.get(key, 0.0) * weight
            
        with self._lock:
            candidate = self.get_candidate(candidate_id)
            if not candidate:
                raise ValueError(f"Candidate {candidate_id} not found")
                
            candidate.scores = scores
            candidate.overall_score = overall_score
            
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE scene_candidates SET scores_json = ?, overall_score = ? WHERE candidate_id = ?",
                    (json.dumps(scores), overall_score, candidate_id)
                )
            return candidate

    def select_best_candidate(self, scene_id: str) -> Optional[SceneCandidate]:
        with self._lock:
            row = self.db.execute_single(
                """
                SELECT * FROM scene_candidates 
                WHERE scene_id = ? AND status = 'VERIFIED'
                ORDER BY overall_score DESC LIMIT 1
                """,
                (scene_id,)
            )
            if row:
                return self._row_to_candidate(row)
            return None

    def accept_candidate(self, candidate_id: str) -> SceneCandidate:
        with self._lock:
            candidate = self.get_candidate(candidate_id)
            if not candidate:
                raise ValueError(f"Candidate {candidate_id} not found")
                
            candidate.status = "ACCEPTED"
            
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE scene_candidates SET status = 'ACCEPTED' WHERE candidate_id = ?",
                    (candidate_id,)
                )
            return candidate

    def reject_candidate(self, candidate_id: str, reason: str) -> SceneCandidate:
        with self._lock:
            candidate = self.get_candidate(candidate_id)
            if not candidate:
                raise ValueError(f"Candidate {candidate_id} not found")
                
            candidate.status = "REJECTED"
            candidate.rejection_reason = reason
            
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE scene_candidates SET status = 'REJECTED', rejection_reason = ? WHERE candidate_id = ?",
                    (reason, candidate_id)
                )
            return candidate
