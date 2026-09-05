import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from db.repository import DatabaseRepository
from workers.models import ProductionJob, JobStatus
from workers.base import WorkerPool, AntigravityWorker
from campaigns.models import Campaign

logger = logging.getLogger("whop_editor.campaigns")


class CampaignManager:
    """
    Manages Whop campaigns, source material, production jobs, and worker execution.
    """

    def __init__(self, repo: Optional[DatabaseRepository] = None, worker_pool: Optional[WorkerPool] = None):
        self.repo = repo or DatabaseRepository()
        if worker_pool is None:
            pool = WorkerPool(max_concurrent_workers=2)
            pool.register_worker(AntigravityWorker("worker_ag_01"))
            self.worker_pool = pool
        else:
            self.worker_pool = worker_pool

        # Ensure workers in pool are registered in PostgreSQL workers table
        for w in getattr(self.worker_pool, "_workers", {}).values():
            try:
                self.repo.register_worker(
                    worker_id=w.id,
                    provider=w.provider,
                    capabilities=w.capabilities,
                    status="available"
                )
            except Exception as e:
                logger.debug(f"Could not register worker {w.id} in DB: {e}")

    def create_campaign(
        self,
        project_id: str,
        name: str,
        campaign_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Campaign:
        # Ensure project exists
        proj = self.repo.get_project(project_id)
        if not proj:
            proj_name = (config.get("project_name") or name) if config else name
            proj_desc = (config.get("niche_description") or f"Campaign production for {name}") if config else f"Campaign production for {name}"
            self.repo.create_project(
                project_id=project_id,
                name=proj_name,
                niche_description=proj_desc
            )


        if campaign_id:
            existing = self.get_campaign(campaign_id)
            if existing:
                logger.info(f"Reusing existing campaign '{campaign_id}'")
                return existing

        c_id = campaign_id or f"camp_{uuid.uuid4().hex[:10]}"
        record = self.repo.create_campaign(
            campaign_id=c_id,
            project_id=project_id,
            name=name,
            status="active",
            config=config or {}
        )
        self.repo.log_audit(
            audit_id=f"audit_camp_{uuid.uuid4().hex[:8]}",
            action="CREATE_CAMPAIGN",
            target=c_id,
            detail=f"Created campaign '{name}' under project '{project_id}'"
        )
        return Campaign(
            id=record["id"],
            project_id=record["project_id"],
            name=record["name"],
            status=record["status"],
            config=record["config"],
            created_at=record["created_at"],
            updated_at=record["updated_at"]
        )

    def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        data = self.repo.get_campaign(campaign_id)
        if not data:
            return None
        return Campaign(
            id=data["id"],
            project_id=data["project_id"],
            name=data["name"],
            status=data["status"],
            config=data["config"],
            created_at=data["created_at"],
            updated_at=data["updated_at"]
        )

    def list_campaigns(self, project_id: Optional[str] = None) -> List[Campaign]:
        records = self.repo.list_campaigns(project_id=project_id)
        return [
            Campaign(
                id=r["id"],
                project_id=r["project_id"],
                name=r["name"],
                status=r["status"],
                config=r["config"],
                created_at=r["created_at"],
                updated_at=r["updated_at"]
            )
            for r in records
        ]

    def create_production_job(
        self,
        campaign_id: str,
        input_video_path: str | Path,
        job_type: str = "PRODUCTION_EDIT",
        target_word: Optional[str] = None,
        scale: Optional[float] = None,
        duration_ms: Optional[int] = None,
        output_filename: Optional[str] = None,
        output_dir: Optional[str | Path] = None,
        job_id: Optional[str] = None
    ) -> ProductionJob:
        camp = self.get_campaign(campaign_id)
        if not camp:
            raise ValueError(f"Campaign '{campaign_id}' does not exist.")

        j_id = job_id or f"job_{uuid.uuid4().hex[:10]}"
        
        from config import settings
        resolved_out_dir = Path(output_dir).resolve() if output_dir else (settings.DATA_DIR / "output" / camp.project_id / campaign_id / j_id)
        resolved_out_dir.mkdir(parents=True, exist_ok=True)

        input_data = {
            "input_video_path": str(Path(input_video_path).resolve()),
            "project_id": camp.project_id,
            "campaign_id": campaign_id,
            "target_word": target_word,
            "scale": scale,
            "duration_ms": duration_ms,
            "output_filename": output_filename or "version_1.mp4",
            "output_dir": str(resolved_out_dir)
        }

        record = self.repo.create_job(
            job_id=j_id,
            campaign_id=campaign_id,
            job_type=job_type,
            input_data=input_data,
            status="queued"
        )

        self.repo.log_audit(
            audit_id=f"audit_job_{uuid.uuid4().hex[:8]}",
            action="CREATE_JOB",
            target=j_id,
            detail=f"Created production job [{job_type}] for campaign '{campaign_id}'"
        )

        return ProductionJob(
            id=record["id"],
            campaign_id=record["campaign_id"],
            job_type=record["job_type"],
            input_data=record["input_data"],
            status=JobStatus.PENDING,
            max_retries=record["max_retries"],
            created_at=record["created_at"]
        )

    def execute_job(self, job_id: str) -> ProductionJob:
        db_job = self.repo.get_job(job_id)
        if not db_job:
            raise ValueError(f"Job '{job_id}' not found.")

        job = ProductionJob(
            id=db_job["id"],
            campaign_id=db_job["campaign_id"],
            job_type=db_job["job_type"],
            input_data=db_job["input_data"],
            output_data=db_job["output_data"],
            status=db_job["status"],
            assigned_worker_id=db_job["assigned_worker_id"],
            retry_count=db_job["retry_count"],
            max_retries=db_job["max_retries"],
            error_message=db_job["error_message"],
            created_at=db_job["created_at"]
        )

        # Update status in DB
        self.repo.update_job(job_id=job.id, status=JobStatus.RUNNING)

        # Submit to worker pool
        executed_job = self.worker_pool.submit_job(job)

        # Ensure assigned worker is registered in DB to satisfy foreign key constraint
        if executed_job.assigned_worker_id:
            try:
                self.repo.register_worker(
                    worker_id=executed_job.assigned_worker_id,
                    provider="antigravity",
                    capabilities=["PRODUCTION_EDIT", "RENDER"],
                    status="available"
                )
            except Exception:
                pass

        # Persist updated status
        self.repo.update_job(
            job_id=executed_job.id,
            status=executed_job.status,
            assigned_worker_id=executed_job.assigned_worker_id,
            output_data=executed_job.output_data,
            error_message=executed_job.error_message,
            completed_at=executed_job.completed_at
        )

        self.repo.log_audit(
            audit_id=f"audit_exec_{uuid.uuid4().hex[:8]}",
            action="EXECUTE_JOB",
            target=executed_job.id,
            detail=f"Job [{executed_job.id}] finished with status: {executed_job.status}"
        )

        return executed_job
