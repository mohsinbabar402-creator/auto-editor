from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import psycopg2.errors

from db.connection import transaction_scope, DatabaseTransactionError

logger = logging.getLogger("whop_editor.repository")


class RepositoryError(Exception):
    """Base repository error."""
    pass


class EntityNotFoundError(RepositoryError):
    """Raised when an entity is not found."""
    pass


class DuplicateEntityError(RepositoryError):
    """Raised on unique constraint violation."""
    pass


class ForeignKeyMissingError(RepositoryError):
    """Raised on foreign key violation."""
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseRepository:
    """PostgreSQL repository for projects, videos, knowledge, evidence, and audit logs."""

    # --- PROJECTS ---
    def create_project(self, project_id: str, name: str, niche_description: str) -> Dict[str, Any]:
        sql = """
            INSERT INTO projects (id, name, niche_description)
            VALUES (%s, %s, %s)
            RETURNING id, name, niche_description;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (project_id, name, niche_description))
                row = cur.fetchone()
                return {"id": row[0], "name": row[1], "niche_description": row[2]}
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Project '{project_id}' already exists.") from e
            raise RepositoryError(f"Failed to create project: {e}") from e

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, name, niche_description FROM projects WHERE id = %s;"
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (project_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {"id": row[0], "name": row[1], "niche_description": row[2]}
        except Exception as e:
            raise RepositoryError(f"Failed to fetch project '{project_id}': {e}") from e

    # --- VIDEOS ---
    def register_video(self, video_id: str, project_id: str, file_path: str, status: str = "registered") -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO videos (id, project_id, file_path, status, created_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, project_id, file_path, status, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (video_id, project_id, file_path, status, now))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "file_path": row[2],
                    "status": row[3],
                    "created_at": row[4]
                }
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.ForeignKeyViolation):
                raise ForeignKeyMissingError(f"Project '{project_id}' does not exist.") from e
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Video '{video_id}' already exists.") from e
            raise RepositoryError(f"Failed to register video: {e}") from e

    def update_video_status(self, video_id: str, status: str) -> None:
        sql = "UPDATE videos SET status = %s WHERE id = %s;"
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (status, video_id))
                if cur.rowcount == 0:
                    raise EntityNotFoundError(f"Video '{video_id}' not found for status update.")
        except DatabaseTransactionError as e:
            raise RepositoryError(f"Failed to update video status: {e}") from e

    def get_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, project_id, file_path, status, created_at FROM videos WHERE id = %s;"
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (video_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "file_path": row[2],
                    "status": row[3],
                    "created_at": row[4]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to fetch video '{video_id}': {e}") from e

    # --- KNOWLEDGE ---
    def create_knowledge_candidate(
        self,
        knowledge_id: str,
        project_id: Optional[str],
        event_type: str,
        action_type: str,
        parameters_json: str,
        confidence: float = 0.3,
        sample_size: int = 0
    ) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO knowledge (id, project_id, status, event_type, action_type, parameters_json, confidence, sample_size, created_at)
            VALUES (%s, %s, 'candidate', %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, status, event_type, action_type, parameters_json, confidence, sample_size, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (knowledge_id, project_id, event_type, action_type, parameters_json, confidence, sample_size, now))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "status": row[2],
                    "event_type": row[3],
                    "action_type": row[4],
                    "parameters_json": row[5],
                    "confidence": row[6],
                    "sample_size": row[7],
                    "created_at": row[8]
                }
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.ForeignKeyViolation):
                raise ForeignKeyMissingError(f"Project '{project_id}' does not exist.") from e
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Knowledge '{knowledge_id}' already exists.") from e
            raise RepositoryError(f"Failed to create knowledge candidate: {e}") from e

    def get_knowledge(self, knowledge_id: str) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT id, project_id, status, event_type, action_type, parameters_json, confidence, sample_size, created_at
            FROM knowledge WHERE id = %s;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (knowledge_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "status": row[2],
                    "event_type": row[3],
                    "action_type": row[4],
                    "parameters_json": row[5],
                    "confidence": row[6],
                    "sample_size": row[7],
                    "created_at": row[8]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to fetch knowledge '{knowledge_id}': {e}") from e

    def update_knowledge(
        self,
        knowledge_id: str,
        status: Optional[str] = None,
        confidence: Optional[float] = None,
        sample_size: Optional[int] = None,
        parameters_json: Optional[str] = None
    ) -> Dict[str, Any]:
        sql = """
            UPDATE knowledge
            SET status = COALESCE(%s, status),
                confidence = COALESCE(%s, confidence),
                sample_size = COALESCE(%s, sample_size),
                parameters_json = COALESCE(%s, parameters_json)
            WHERE id = %s
            RETURNING id, project_id, status, event_type, action_type, parameters_json, confidence, sample_size, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (status, confidence, sample_size, parameters_json, knowledge_id))
                row = cur.fetchone()
                if not row:
                    raise EntityNotFoundError(f"Knowledge '{knowledge_id}' not found.")
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "status": row[2],
                    "event_type": row[3],
                    "action_type": row[4],
                    "parameters_json": row[5],
                    "confidence": row[6],
                    "sample_size": row[7],
                    "created_at": row[8]
                }
        except DatabaseTransactionError as e:
            raise RepositoryError(f"Failed to update knowledge '{knowledge_id}': {e}") from e

    def list_knowledge(
        self,
        project_id: Optional[str] = None,
        action_type: Optional[str] = None,
        min_confidence: float = 0.0
    ) -> List[Dict[str, Any]]:
        conditions = ["confidence >= %s"]
        params: List[Any] = [min_confidence]

        if project_id:
            conditions.append("(project_id = %s OR project_id IS NULL)")
            params.append(project_id)
        if action_type:
            conditions.append("action_type = %s")
            params.append(action_type)

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT id, project_id, status, event_type, action_type, parameters_json, confidence, sample_size, created_at
            FROM knowledge
            WHERE {where_clause}
            ORDER BY confidence DESC, sample_size DESC;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                return [
                    {
                        "id": r[0],
                        "project_id": r[1],
                        "status": r[2],
                        "event_type": r[3],
                        "action_type": r[4],
                        "parameters_json": r[5],
                        "confidence": r[6],
                        "sample_size": r[7],
                        "created_at": r[8]
                    }
                    for r in rows
                ]
        except Exception as e:
            raise RepositoryError(f"Failed to list knowledge: {e}") from e

    # --- EVIDENCE ---
    def record_evidence(
        self,
        evidence_id: str,
        knowledge_id: str,
        video_id: Optional[str],
        outcome_note: str,
        metric_value: Optional[float] = None
    ) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO evidence (id, knowledge_id, video_id, outcome_note, metric_value, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, knowledge_id, video_id, outcome_note, metric_value, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (evidence_id, knowledge_id, video_id, outcome_note, metric_value, now))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "knowledge_id": row[1],
                    "video_id": row[2],
                    "outcome_note": row[3],
                    "metric_value": row[4],
                    "created_at": row[5]
                }
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.ForeignKeyViolation):
                raise ForeignKeyMissingError("Knowledge or Video referenced by evidence does not exist.") from e
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Evidence '{evidence_id}' already exists.") from e
            raise RepositoryError(f"Failed to record evidence: {e}") from e

    # --- AUDIT LOG ---
    def log_audit(self, audit_id: str, action: str, target: str, detail: str) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO audit_log (id, action, target, detail, created_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, action, target, detail, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (audit_id, action, target, detail, now))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "action": row[1],
                    "target": row[2],
                    "detail": row[3],
                    "created_at": row[4]
                }
        except DatabaseTransactionError as e:
            raise RepositoryError(f"Failed to write audit log: {e}") from e

    # --- CAMPAIGNS ---
    def create_campaign(
        self,
        campaign_id: str,
        project_id: str,
        name: str,
        status: str = "active",
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now = _now_iso()
        config_json = json.dumps(config or {})
        sql = """
            INSERT INTO campaigns (id, project_id, name, status, config_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, name, status, config_json, created_at, updated_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (campaign_id, project_id, name, status, config_json, now, now))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "name": row[2],
                    "status": row[3],
                    "config": json.loads(row[4]),
                    "created_at": row[5],
                    "updated_at": row[6]
                }
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.ForeignKeyViolation):
                raise ForeignKeyMissingError(f"Project '{project_id}' does not exist.") from e
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Campaign '{campaign_id}' already exists.") from e
            raise RepositoryError(f"Failed to create campaign: {e}") from e

    def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, project_id, name, status, config_json, created_at, updated_at FROM campaigns WHERE id = %s;"
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (campaign_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "project_id": row[1],
                    "name": row[2],
                    "status": row[3],
                    "config": json.loads(row[4]),
                    "created_at": row[5],
                    "updated_at": row[6]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to fetch campaign '{campaign_id}': {e}") from e

    def list_campaigns(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if project_id:
            sql = "SELECT id, project_id, name, status, config_json, created_at, updated_at FROM campaigns WHERE project_id = %s ORDER BY created_at DESC;"
            args = (project_id,)
        else:
            sql = "SELECT id, project_id, name, status, config_json, created_at, updated_at FROM campaigns ORDER BY created_at DESC;"
            args = ()
        try:
            with transaction_scope() as cur:
                cur.execute(sql, args)
                return [
                    {
                        "id": row[0],
                        "project_id": row[1],
                        "name": row[2],
                        "status": row[3],
                        "config": json.loads(row[4]),
                        "created_at": row[5],
                        "updated_at": row[6]
                    }
                    for row in cur.fetchall()
                ]
        except Exception as e:
            raise RepositoryError(f"Failed to list campaigns: {e}") from e

    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            UPDATE campaigns
            SET status = %s, updated_at = %s
            WHERE id = %s
            RETURNING id, project_id, name, status, updated_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (status, now, campaign_id))
                row = cur.fetchone()
                if not row:
                    raise EntityNotFoundError(f"Campaign '{campaign_id}' not found.")
                return {"id": row[0], "project_id": row[1], "name": row[2], "status": row[3], "updated_at": row[4]}
        except Exception as e:
            raise RepositoryError(f"Failed to update campaign status: {e}") from e

    # --- WORKERS ---
    def register_worker(
        self,
        worker_id: str,
        provider: str,
        capabilities: List[str],
        status: str = "available",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO workers (id, provider, capabilities_json, status, metadata_json, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET provider = EXCLUDED.provider,
                capabilities_json = EXCLUDED.capabilities_json,
                status = EXCLUDED.status,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = EXCLUDED.updated_at
            RETURNING id, provider, capabilities_json, status, metadata_json, updated_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (
                    worker_id, provider, json.dumps(capabilities), status, json.dumps(metadata or {}), now
                ))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "provider": row[1],
                    "capabilities": json.loads(row[2]),
                    "status": row[3],
                    "metadata": json.loads(row[4]) if row[4] else {},
                    "updated_at": row[5]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to register worker '{worker_id}': {e}") from e

    def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, provider, capabilities_json, status, current_job_id, metadata_json, updated_at FROM workers WHERE id = %s;"
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (worker_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "provider": row[1],
                    "capabilities": json.loads(row[2]),
                    "status": row[3],
                    "current_job_id": row[4],
                    "metadata": json.loads(row[5]) if row[5] else {},
                    "updated_at": row[6]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to fetch worker '{worker_id}': {e}") from e

    def list_workers(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        if provider:
            sql = "SELECT id, provider, capabilities_json, status, current_job_id, metadata_json, updated_at FROM workers WHERE provider = %s;"
            args = (provider,)
        else:
            sql = "SELECT id, provider, capabilities_json, status, current_job_id, metadata_json, updated_at FROM workers;"
            args = ()
        try:
            with transaction_scope() as cur:
                cur.execute(sql, args)
                return [
                    {
                        "id": row[0],
                        "provider": row[1],
                        "capabilities": json.loads(row[2]),
                        "status": row[3],
                        "current_job_id": row[4],
                        "metadata": json.loads(row[5]) if row[5] else {},
                        "updated_at": row[6]
                    }
                    for row in cur.fetchall()
                ]
        except Exception as e:
            raise RepositoryError(f"Failed to list workers: {e}") from e

    def update_worker_status(self, worker_id: str, status: str, current_job_id: Optional[str] = None) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            UPDATE workers
            SET status = %s, current_job_id = %s, updated_at = %s
            WHERE id = %s
            RETURNING id, status, current_job_id, updated_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (status, current_job_id, now, worker_id))
                row = cur.fetchone()
                if not row:
                    raise EntityNotFoundError(f"Worker '{worker_id}' not found.")
                return {"id": row[0], "status": row[1], "current_job_id": row[2], "updated_at": row[3]}
        except Exception as e:
            raise RepositoryError(f"Failed to update worker status: {e}") from e

    # --- JOBS ---
    def create_job(
        self,
        job_id: str,
        campaign_id: Optional[str],
        job_type: str,
        input_data: Dict[str, Any],
        status: str = "pending",
        max_retries: int = 3
    ) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO jobs (id, campaign_id, job_type, status, input_data_json, max_retries, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, campaign_id, job_type, status, input_data_json, max_retries, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (job_id, campaign_id, job_type, status, json.dumps(input_data), max_retries, now))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "campaign_id": row[1],
                    "job_type": row[2],
                    "status": row[3],
                    "input_data": json.loads(row[4]),
                    "max_retries": row[5],
                    "created_at": row[6]
                }
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.ForeignKeyViolation):
                raise ForeignKeyMissingError(f"Referenced campaign '{campaign_id}' does not exist.") from e
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Job '{job_id}' already exists.") from e
            raise RepositoryError(f"Failed to create job: {e}") from e

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT id, campaign_id, job_type, status, assigned_worker_id, input_data_json, output_data_json,
                   retry_count, max_retries, error_message, created_at, started_at, completed_at
            FROM jobs WHERE id = %s;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (job_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "campaign_id": row[1],
                    "job_type": row[2],
                    "status": row[3],
                    "assigned_worker_id": row[4],
                    "input_data": json.loads(row[5]) if row[5] else {},
                    "output_data": json.loads(row[6]) if row[6] else {},
                    "retry_count": row[7],
                    "max_retries": row[8],
                    "error_message": row[9],
                    "created_at": row[10],
                    "started_at": row[11],
                    "completed_at": row[12]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to fetch job '{job_id}': {e}") from e

    def update_job(
        self,
        job_id: str,
        status: str,
        assigned_worker_id: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        retry_count: Optional[int] = None,
        error_message: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None
    ) -> Dict[str, Any]:
        sql = """
            UPDATE jobs
            SET status = %s,
                assigned_worker_id = COALESCE(%s, assigned_worker_id),
                input_data_json = CASE WHEN %s IS NOT NULL THEN %s ELSE input_data_json END,
                output_data_json = CASE WHEN %s IS NOT NULL THEN %s ELSE output_data_json END,
                retry_count = COALESCE(%s, retry_count),
                error_message = COALESCE(%s, error_message),
                started_at = COALESCE(%s, started_at),
                completed_at = COALESCE(%s, completed_at)
            WHERE id = %s
            RETURNING id, status, assigned_worker_id, retry_count, error_message;
        """
        in_json = json.dumps(input_data) if input_data is not None else None
        out_json = json.dumps(output_data) if output_data is not None else None
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (
                    status, assigned_worker_id,
                    in_json, in_json,
                    out_json, out_json,
                    retry_count, error_message, started_at, completed_at,
                    job_id
                ))
                row = cur.fetchone()
                return {"id": row[0], "status": row[1], "assigned_worker_id": row[2], "retry_count": row[3], "error_message": row[4]}
        except Exception as e:
            raise RepositoryError(f"Failed to update job '{job_id}': {e}") from e

    def claim_next_job(
        self,
        worker_id: str,
        supported_job_types: Optional[List[str]] = None,
        stale_timeout_sec: int = 600
    ) -> Optional[Dict[str, Any]]:
        """
        Transactionally claims the next available queued job using SELECT ... FOR UPDATE SKIP LOCKED.
        Safely recovers stale jobs if any exceed stale_timeout_sec.
        """
        now = _now_iso()
        try:
            with transaction_scope() as cur:
                # 1. Recover stale jobs first within same transaction
                stale_sql = """
                    UPDATE jobs
                    SET status = 'queued',
                        assigned_worker_id = NULL,
                        error_message = 'Recovered from stale worker lease',
                        retry_count = retry_count + 1
                    WHERE status IN ('claimed', 'running')
                      AND started_at IS NOT NULL
                      AND started_at != ''
                      AND started_at::TIMESTAMPTZ < (NOW() - (%s || ' seconds')::INTERVAL)
                      AND retry_count < max_retries;
                """
                cur.execute(stale_sql, (stale_timeout_sec,))

                # 2. Select next job FOR UPDATE SKIP LOCKED
                if supported_job_types:
                    select_sql = """
                        SELECT id, campaign_id, job_type, status, assigned_worker_id, input_data_json, output_data_json,
                               retry_count, max_retries, error_message, created_at, started_at, completed_at
                        FROM jobs
                        WHERE status IN ('queued', 'pending')
                          AND job_type = ANY(%s)
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1;
                    """
                    cur.execute(select_sql, (supported_job_types,))
                else:
                    select_sql = """
                        SELECT id, campaign_id, job_type, status, assigned_worker_id, input_data_json, output_data_json,
                               retry_count, max_retries, error_message, created_at, started_at, completed_at
                        FROM jobs
                        WHERE status IN ('queued', 'pending')
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1;
                    """
                    cur.execute(select_sql)

                row = cur.fetchone()
                if not row:
                    return None

                job_id = row[0]
                # 3. Transition to claimed
                update_sql = """
                    UPDATE jobs
                    SET status = 'claimed',
                        assigned_worker_id = %s,
                        started_at = %s
                    WHERE id = %s;
                """
                cur.execute(update_sql, (worker_id, now, job_id))

                return {
                    "id": row[0],
                    "campaign_id": row[1],
                    "job_type": row[2],
                    "status": "claimed",
                    "assigned_worker_id": worker_id,
                    "input_data": json.loads(row[5]) if row[5] else {},
                    "output_data": json.loads(row[6]) if row[6] else {},
                    "retry_count": row[7],
                    "max_retries": row[8],
                    "error_message": row[9],
                    "created_at": row[10],
                    "started_at": now,
                    "completed_at": row[12]
                }
        except Exception as e:
            raise RepositoryError(f"Failed to claim next job: {e}") from e

    def recover_stale_jobs(self, stale_timeout_sec: int = 600) -> int:
        """
        Explicitly recovers any jobs stuck in 'claimed' or 'running' state beyond timeout.
        Returns number of recovered jobs.
        """
        stale_sql = """
            UPDATE jobs
            SET status = 'queued',
                assigned_worker_id = NULL,
                error_message = 'Explicitly recovered from stale worker lease',
                retry_count = retry_count + 1
            WHERE status IN ('claimed', 'running')
              AND started_at IS NOT NULL
              AND started_at != ''
              AND started_at::TIMESTAMPTZ < (NOW() - (%s || ' seconds')::INTERVAL)
              AND retry_count < max_retries;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(stale_sql, (stale_timeout_sec,))
                return cur.rowcount
        except Exception as e:
            raise RepositoryError(f"Failed to recover stale jobs: {e}") from e

    # --- REVIEWS ---

    def record_review(
        self,
        review_id: str,
        job_id: str,
        video_id: Optional[str],
        attempt: int,
        reviewer_type: str,
        verdict: str,
        overall_score: Optional[float] = None,
        scores: Optional[Dict[str, float]] = None,
        problems: Optional[List[Dict[str, Any]]] = None,
        corrections: Optional[List[str]] = None,
        raw_response: Optional[str] = None
    ) -> Dict[str, Any]:
        now = _now_iso()
        sql = """
            INSERT INTO reviews (
                id, job_id, video_id, attempt, reviewer_type, verdict,
                overall_score, scores_json, problems_json, corrections_json, raw_response, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, job_id, video_id, attempt, reviewer_type, verdict, overall_score, created_at;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (
                    review_id, job_id, video_id, attempt, reviewer_type, verdict,
                    overall_score,
                    json.dumps(scores or {}),
                    json.dumps(problems or []),
                    json.dumps(corrections or []),
                    raw_response,
                    now
                ))
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "job_id": row[1],
                    "video_id": row[2],
                    "attempt": row[3],
                    "reviewer_type": row[4],
                    "verdict": row[5],
                    "overall_score": row[6],
                    "created_at": row[7]
                }
        except DatabaseTransactionError as e:
            orig = getattr(e, "__cause__", None)
            if isinstance(orig, psycopg2.errors.ForeignKeyViolation):
                raise ForeignKeyMissingError(f"Job or video referenced in review does not exist.") from e
            if isinstance(orig, psycopg2.errors.UniqueViolation):
                raise DuplicateEntityError(f"Review '{review_id}' already exists.") from e
            raise RepositoryError(f"Failed to record review: {e}") from e

    def get_reviews_for_job(self, job_id: str) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, job_id, video_id, attempt, reviewer_type, verdict,
                   overall_score, scores_json, problems_json, corrections_json, raw_response, created_at
            FROM reviews
            WHERE job_id = %s
            ORDER BY attempt ASC;
        """
        try:
            with transaction_scope() as cur:
                cur.execute(sql, (job_id,))
                return [
                    {
                        "id": row[0],
                        "job_id": row[1],
                        "video_id": row[2],
                        "attempt": row[3],
                        "reviewer_type": row[4],
                        "verdict": row[5],
                        "overall_score": row[6],
                        "scores": json.loads(row[7]) if row[7] else {},
                        "problems": json.loads(row[8]) if row[8] else [],
                        "corrections": json.loads(row[9]) if row[9] else [],
                        "raw_response": row[10],
                        "created_at": row[11]
                    }
                    for row in cur.fetchall()
                ]
        except Exception as e:
            raise RepositoryError(f"Failed to fetch reviews for job '{job_id}': {e}") from e

