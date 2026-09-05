import pytest
from workers.models import Worker, WorkerStatus, ProductionJob, JobStatus
from workers.base import BaseWorker, WorkerPool, WorkerExecutionError


class MockEditingWorker(BaseWorker):
    def __init__(self, worker_id: str = "mock_w1", should_fail: bool = False):
        model = Worker(
            id=worker_id,
            provider="mock_provider",
            capabilities=["EDITING", "RENDERING"],
            status=WorkerStatus.AVAILABLE
        )
        super().__init__(model)
        self.should_fail = should_fail
        self.call_count = 0

    def execute(self, job: ProductionJob) -> ProductionJob:
        self.call_count += 1
        if self.should_fail:
            job.status = JobStatus.FAILED
            job.error_message = "Simulated worker failure"
        else:
            job.status = JobStatus.COMPLETED
            job.output_data = {"rendered_file": "test_output.mp4"}
        return job


def test_worker_availability_and_capabilities():
    w = Worker(id="w1", provider="antigravity", capabilities=["EDITING", "REVIEW"])
    assert w.is_available()
    assert w.can_handle("EDITING")
    assert w.can_handle("editing")
    assert not w.can_handle("TRANSCRIPTION")

    w.status = WorkerStatus.BUSY
    assert not w.is_available()


def test_worker_pool_dispatch_and_status_transition():
    pool = WorkerPool(max_concurrent_workers=2)
    worker = MockEditingWorker("w1")
    pool.register_worker(worker)

    job = ProductionJob.create(campaign_id="camp_01", job_type="EDITING", input_data={})
    res = pool.submit_job(job)

    assert res.status == JobStatus.COMPLETED
    assert res.output_data["rendered_file"] == "test_output.mp4"
    # Verify worker returned to AVAILABLE
    assert worker.worker.status == WorkerStatus.AVAILABLE
    assert worker.worker.current_job_id is None
    assert worker.call_count == 1


def test_worker_pool_queues_when_workers_busy():
    pool = WorkerPool(max_concurrent_workers=1)
    w1 = MockEditingWorker("w1")
    w1.worker.status = WorkerStatus.BUSY  # Simulate busy worker
    pool.register_worker(w1)

    job = ProductionJob.create(campaign_id="camp_01", job_type="EDITING", input_data={})
    # Submitting should enqueue without crashing
    res = pool.submit_job(job)
    assert pool.queue_size == 1
    assert res.status == JobStatus.PENDING


def test_worker_pool_drains_queue_on_release():
    pool = WorkerPool(max_concurrent_workers=1)
    worker = MockEditingWorker("w1")
    pool.register_worker(worker)

    # Artificially push job to queue
    queued_job = ProductionJob.create(campaign_id="camp_01", job_type="EDITING", input_data={})
    pool._queue.append(queued_job)
    assert pool.queue_size == 1

    # Drain queue
    pool._drain_queue()
    assert pool.queue_size == 0
    assert queued_job.status == JobStatus.COMPLETED
    assert worker.call_count == 1


def test_worker_failure_updates_job_status():
    pool = WorkerPool(max_concurrent_workers=1)
    failing_worker = MockEditingWorker("failing_w1", should_fail=True)
    pool.register_worker(failing_worker)

    job = ProductionJob.create(campaign_id="camp_01", job_type="EDITING", input_data={})
    res = pool.submit_job(job)
    assert res.status == JobStatus.FAILED
    assert "Simulated worker failure" in res.error_message
    assert failing_worker.worker.status == WorkerStatus.AVAILABLE
