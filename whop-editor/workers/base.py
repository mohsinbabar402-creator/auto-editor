from abc import ABC, abstractmethod
from collections import deque
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from workers.models import Worker, WorkerStatus, ProductionJob, JobStatus, utc_now_iso

logger = logging.getLogger("whop_editor.workers")


class WorkerExecutionError(Exception):
    """Raised when worker execution fails."""
    pass


class BaseWorker(ABC):
    """Abstract base worker interface."""

    def __init__(self, worker_model: Worker):
        self.worker = worker_model

    @property
    def id(self) -> str:
        return self.worker.id

    @property
    def provider(self) -> str:
        return self.worker.provider

    @property
    def capabilities(self) -> List[str]:
        return self.worker.capabilities

    @abstractmethod
    def execute(self, job: ProductionJob) -> ProductionJob:
        """Executes the given job and updates its status and outputs."""
        pass


class AntigravityWorker(BaseWorker):
    """
    Standard Antigravity video worker: executes editing, normalization, and rendering jobs.
    """

    def __init__(self, worker_id: str = "worker_antigravity_01", capabilities: Optional[List[str]] = None):
        caps = capabilities or ["EDITING", "RENDERING", "AUDIO_EXTRACTION"]
        model = Worker(
            id=worker_id,
            provider="antigravity",
            capabilities=caps,
            status=WorkerStatus.AVAILABLE
        )
        super().__init__(model)

    def execute(self, job: ProductionJob) -> ProductionJob:
        logger.info(f"Worker [{self.id}] starting job [{job.id}] ({job.job_type})")
        job.status = JobStatus.RUNNING
        job.started_at = utc_now_iso()
        job.assigned_worker_id = self.id

        try:
            if job.job_type in ("PUNCH_IN_EDIT", "RENDER", "PRODUCTION_EDIT"):
                from pipeline.run import run_stage1_pipeline
                input_video = job.input_data.get("input_video_path")
                if not input_video:
                    raise WorkerExecutionError("Missing 'input_video_path' in job input_data.")
                
                campaign_id = job.campaign_id
                target_word = job.input_data.get("target_word")
                scale = job.input_data.get("scale")
                duration_ms = job.input_data.get("duration_ms")
                output_filename = job.input_data.get("output_filename")
                project_id = job.input_data.get("project_id", "default_proj")
                output_dir = job.input_data.get("output_dir")
                if not output_dir:
                    from config import settings
                    output_dir = settings.DATA_DIR / "output" / project_id / campaign_id / job.id
                else:
                    output_dir = Path(output_dir).resolve()

                pipeline_res = run_stage1_pipeline(
                    input_video_path=input_video,
                    project_id=project_id,
                    output_filename=output_filename,
                    output_dir=output_dir,
                    target_word=target_word,
                    scale=scale,
                    duration_ms=duration_ms
                )

                if not pipeline_res.success:
                    raise WorkerExecutionError(f"Pipeline error at [{pipeline_res.stage_failed}]: {pipeline_res.error_message}")

                job.output_data = {
                    "output_path": pipeline_res.output_path,
                    "video_id": pipeline_res.video_id,
                    "selected_word": pipeline_res.selected_word,
                    "selected_word_index": pipeline_res.selected_word_index,
                    "effect_start_sec": pipeline_res.effect_start_sec,
                    "effect_end_sec": pipeline_res.effect_end_sec,
                    "scale": pipeline_res.scale,
                    "knowledge_id": pipeline_res.knowledge_id
                }
                job.status = JobStatus.COMPLETED
                job.completed_at = utc_now_iso()
            else:
                raise WorkerExecutionError(f"Unsupported job type for AntigravityWorker: {job.job_type}")
        except Exception as e:
            logger.error(f"Worker [{self.id}] failed job [{job.id}]: {e}")
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = utc_now_iso()

        return job


class GeminiReviewWorker(BaseWorker):
    """
    Worker that executes video QA review using the Gemini reviewer.
    """

    def __init__(self, worker_id: str = "worker_gemini_review_01", profile_id: Optional[str] = None):
        caps = ["REVIEW", "GEMINI_REVIEW", "QA"]
        model = Worker(
            id=worker_id,
            provider="gemini",
            capabilities=caps,
            status=WorkerStatus.AVAILABLE,
            metadata={"profile_id": profile_id} if profile_id else {},
        )
        super().__init__(model)
        self.profile_id = profile_id

    def execute(self, job: ProductionJob) -> ProductionJob:
        logger.info(f"GeminiReviewWorker [{self.id}] starting job [{job.id}]")
        job.status = JobStatus.RUNNING
        job.started_at = utc_now_iso()
        job.assigned_worker_id = self.id

        try:
            from browser.gemini_reviewer import GeminiReviewer
            video_path = job.input_data.get("video_path")
            if not video_path:
                raise WorkerExecutionError("Missing 'video_path' in job input_data.")

            prompt_instruction = job.input_data.get("prompt_instruction")
            reviewer = GeminiReviewer(headless=job.input_data.get("headless", True))
            review = reviewer.review_video(
                video_path=video_path,
                profile_id=self.profile_id or job.input_data.get("profile_id"),
                custom_prompt=prompt_instruction,
            )
            job.output_data = {
                "verdict": review.verdict.value if hasattr(review.verdict, "value") else str(review.verdict),
                "overall_score": review.overall_score,
                "problems": [p.to_dict() if hasattr(p, "to_dict") else p for p in review.problems],
                "corrections": review.corrections,
                "confidence": review.confidence,
                "raw_response": review.raw_response,
            }
            job.status = JobStatus.COMPLETED
            job.completed_at = utc_now_iso()
        except Exception as e:
            logger.error(f"GeminiReviewWorker [{self.id}] failed job [{job.id}]: {e}")
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = utc_now_iso()

        return job


class WorkerPool:
    """
    Manages registered workers, local job queue, and concurrency limits.
    """

    def __init__(self, max_concurrent_workers: int = 2):
        self.max_concurrent_workers = max_concurrent_workers
        self._workers: Dict[str, BaseWorker] = {}
        self._queue: deque[ProductionJob] = deque()

    def register_worker(self, worker: BaseWorker):
        self._workers[worker.id] = worker
        logger.info(f"Registered worker [{worker.id}] ({worker.provider}, capabilities={worker.capabilities})")

    def get_worker(self, worker_id: str) -> Optional[BaseWorker]:
        return self._workers.get(worker_id)

    def list_workers(self) -> List[Worker]:
        return [w.worker for w in self._workers.values()]

    def get_available_worker(self, capability: str) -> Optional[BaseWorker]:
        busy_count = sum(1 for w in self._workers.values() if w.worker.status == WorkerStatus.BUSY)
        if busy_count >= self.max_concurrent_workers:
            logger.info(f"Concurrency ceiling reached ({busy_count}/{self.max_concurrent_workers} busy).")
            return None

        for w in self._workers.values():
            if w.worker.is_available() and w.worker.can_handle(capability):
                return w
        return None

    def submit_job(self, job: ProductionJob) -> Optional[ProductionJob]:
        """
        Dispatches job to an available worker immediately, or queues it if all busy.
        """
        worker = self.get_available_worker(job.job_type)
        if worker is None:
            logger.info(f"No worker available for job [{job.id}]. Enqueuing in local queue.")
            self._queue.append(job)
            return job

        # Acquire worker
        worker.worker.status = WorkerStatus.BUSY
        worker.worker.current_job_id = job.id
        try:
            return worker.execute(job)
        finally:
            worker.worker.status = WorkerStatus.AVAILABLE
            worker.worker.current_job_id = None
            worker.worker.updated_at = utc_now_iso()
            self._drain_queue()

    def _drain_queue(self):
        """Processes queued jobs if workers become available."""
        while self._queue:
            peek_job = self._queue[0]
            worker = self.get_available_worker(peek_job.job_type)
            if worker is None:
                break
            job = self._queue.popleft()
            worker.worker.status = WorkerStatus.BUSY
            worker.worker.current_job_id = job.id
            try:
                worker.execute(job)
            finally:
                worker.worker.status = WorkerStatus.AVAILABLE
                worker.worker.current_job_id = None
                worker.worker.updated_at = utc_now_iso()

    @property
    def queue_size(self) -> int:
        return len(self._queue)
