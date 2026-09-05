from collections import deque
import logging
from typing import Any, Dict, List, Optional, Tuple

from workers.base import BaseWorker, AntigravityWorker, GeminiReviewWorker, WorkerPool
from workers.models import ProductionJob, JobStatus, WorkerStatus, utc_now_iso
from workers.resource_governor import ResourceGovernor, get_resource_governor
from workers.worker_registry import WorkerRegistry

logger = logging.getLogger("whop_editor.scheduler")


class WorkerScheduler:
    """
    Central Autonomous Scheduler for the Content Engine.
    Dispatches production and review jobs by coordinating:
    1. Machine Resource Governor (RAM, disk space, process concurrency limits)
    2. Worker Registry (W1-W8 role affinity, capabilities, authentication state)
    3. Graceful fallback and prioritized queuing
    """

    def __init__(
        self,
        worker_registry: Optional[WorkerRegistry] = None,
        resource_governor: Optional[ResourceGovernor] = None,
        max_concurrent_workers: int = 2,
    ):
        self.worker_registry = worker_registry or WorkerRegistry()
        self.resource_governor = resource_governor or get_resource_governor()
        self.worker_pool = WorkerPool(max_concurrent_workers=max_concurrent_workers)
        self._queue: deque[ProductionJob] = deque()

        # Initialize default execution workers in worker_pool
        self._ensure_default_workers()

    def _ensure_default_workers(self):
        """Registers default execution backends in the local worker pool."""
        if not self.worker_pool.get_worker("worker_antigravity_01"):
            self.worker_pool.register_worker(AntigravityWorker("worker_antigravity_01"))
        if not self.worker_pool.get_worker("worker_gemini_review_01"):
            self.worker_pool.register_worker(GeminiReviewWorker("worker_gemini_review_01"))

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def get_queue(self) -> List[ProductionJob]:
        return list(self._queue)

    def submit_job(self, job: ProductionJob, project_id: str = "proj_whop_shortform") -> ProductionJob:
        """
        Dispatches a job if both host machine resources and a compatible worker are available.
        Otherwise enqueues the job.
        """
        logger.info(f"Received job [{job.id}] ({job.job_type}) for project [{project_id}]")

        # 1. Resource Governor Check
        can_dispatch, reason = self.resource_governor.can_dispatch(job.job_type)
        if not can_dispatch:
            logger.warning(f"Job [{job.id}] queued due to resource constraints: {reason}")
            job.status = JobStatus.PENDING
            self._queue.append(job)
            return job

        # 2. Worker Registry Discovery
        candidate_worker = self.worker_registry.get_available_worker(
            capability=job.job_type,
            project_id=project_id,
        )
        if candidate_worker is None:
            logger.info(f"No available authenticated worker for [{job.job_type}] on [{project_id}]. Enqueuing job [{job.id}].")
            job.status = JobStatus.PENDING
            self._queue.append(job)
            return job

        # 3. Dispatch Job
        return self._execute_dispatched_job(job, candidate_worker.id)

    def _execute_dispatched_job(self, job: ProductionJob, worker_id: str) -> ProductionJob:
        """
        Executes a job on the designated worker inside a managed resource slot.
        """
        res_type = self.resource_governor.resolve_resource_type(job.job_type)
        acquired_slot = self.resource_governor.acquire_resource(res_type)
        if not acquired_slot:
            logger.warning(f"Failed to acquire governor slot '{res_type}' for job [{job.id}]. Enqueuing.")
            job.status = JobStatus.PENDING
            self._queue.append(job)
            return job

        self.worker_registry.acquire_worker(worker_id, job.id)
        job.assigned_worker_id = worker_id

        try:
            # Find an executor worker in worker_pool that can handle this job type
            executor = self._resolve_executor(job.job_type, worker_id)
            if executor is None:
                raise RuntimeError(f"No executor available for job type: {job.job_type}")

            job = executor.execute(job)
            success = job.status == JobStatus.COMPLETED
            return job
        except Exception as e:
            logger.error(f"Execution error on worker [{worker_id}] for job [{job.id}]: {e}")
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = utc_now_iso()
            success = False
            return job
        finally:
            self.worker_registry.release_worker(worker_id, success=success)
            self.resource_governor.release_resource(res_type)
            self.drain_queue()

    def _resolve_executor(self, job_type: str, worker_id: str) -> Optional[BaseWorker]:
        """Resolves an execution backend from the local worker pool."""
        job_clean = job_type.strip().upper()
        if job_clean in ("REVIEW", "GEMINI_REVIEW", "QA"):
            # Check if there's a worker with matching id, else fallback to default gemini review worker
            w = self.worker_pool.get_worker(worker_id)
            if w:
                return w
            return self.worker_pool.get_worker("worker_gemini_review_01")
        elif job_clean in ("PRODUCTION_EDIT", "PUNCH_IN_EDIT", "RENDER", "AUDIO_EXTRACTION"):
            w = self.worker_pool.get_worker(worker_id)
            if w:
                return w
            return self.worker_pool.get_worker("worker_antigravity_01")
        return None

    def drain_queue(self) -> List[ProductionJob]:
        """
        Attempts to dispatch queued jobs if resources and workers have freed up.
        """
        dispatched: List[ProductionJob] = []
        if not self._queue:
            return dispatched

        remaining: deque[ProductionJob] = deque()
        while self._queue:
            job = self._queue.popleft()
            can_dispatch, _ = self.resource_governor.can_dispatch(job.job_type)
            if not can_dispatch:
                remaining.append(job)
                continue

            worker = self.worker_registry.get_available_worker(job.job_type)
            if worker is None:
                remaining.append(job)
                continue

            dispatched_job = self._execute_dispatched_job(job, worker.id)
            dispatched.append(dispatched_job)

        self._queue = remaining
        return dispatched

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive telemetry of the scheduling system."""
        telemetry = self.resource_governor.get_telemetry()
        workers = self.worker_registry.list_workers()
        return {
            "queue_length": len(self._queue),
            "total_workers": len(workers),
            "available_workers": sum(1 for w in workers if w.is_available()),
            "busy_workers": sum(1 for w in workers if w.status == WorkerStatus.BUSY),
            "offline_workers": sum(1 for w in workers if w.status == WorkerStatus.OFFLINE),
            "resource_telemetry": telemetry.to_dict(),
        }
