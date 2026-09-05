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
            self.repo.create_project(
                project_id=project_id,
                name="Whop Short-Form Creator Education",
                niche_description="Educational video shorts for creator communities and SaaS founders."
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
        output_filename: Optional[str] = None
    ) -> ProductionJob:
        camp = self.get_campaign(campaign_id)
        if not camp:
            raise ValueError(f"Campaign '{campaign_id}' does not exist.")

        j_id = f"job_{uuid.uuid4().hex[:10]}"
        input_data = {
            "input_video_path": str(Path(input_video_path).resolve()),
            "project_id": camp.project_id,
            "campaign_id": campaign_id,
            "target_word": target_word,
            "scale": scale,
            "duration_ms": duration_ms,
            "output_filename": output_filename
        }

        record = self.repo.create_job(
            job_id=j_id,
            campaign_id=campaign_id,
            job_type=job_type,
            input_data=input_data,
            status="pending"
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
