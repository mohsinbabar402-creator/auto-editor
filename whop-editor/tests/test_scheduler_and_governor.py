import pytest
from unittest.mock import MagicMock, patch

from workers.models import ProductionJob, JobStatus, WorkerStatus
from workers.resource_governor import ResourceGovernor, ResourceUnavailableError
from workers.worker_registry import WorkerRegistry
from workers.scheduler import WorkerScheduler


class TestResourceGovernor:
    def test_governor_telemetry(self):
        gov = ResourceGovernor()
        telemetry = gov.get_telemetry()
        assert telemetry.ram_load_percent >= 0.0
        assert telemetry.total_ram_mb > 0.0
        assert telemetry.disk_free_gb >= 0.0
        assert isinstance(telemetry.to_dict(), dict)

    def test_governor_concurrency_ceiling(self):
        gov = ResourceGovernor(max_browsers=2, max_renders=1)
        
        # Test browsers: max 2
        assert gov.acquire_resource("browser")
        assert gov.acquire_resource("browser")
        assert not gov.acquire_resource("browser")  # Ceiling reached

        gov.release_resource("browser")
        assert gov.acquire_resource("browser")      # Slot freed

        # Test renders: max 1
        assert gov.acquire_resource("render")
        assert not gov.acquire_resource("render")
        gov.release_resource("render")
        assert gov.acquire_resource("render")

    def test_governor_managed_context(self):
        gov = ResourceGovernor(max_browsers=1)
        with gov.managed_execution("browser"):
            assert gov.get_telemetry().active_browsers == 1
        assert gov.get_telemetry().active_browsers == 0

    def test_governor_headroom_rejection(self):
        # High RAM threshold check
        gov = ResourceGovernor(max_ram_load=10.0)  # artificially low threshold
        can_run, reason = gov.can_dispatch("REVIEW")
        assert not can_run
        assert "RAM load excessive" in reason


class TestWorkerRegistry:
    def test_sync_profiles_to_db(self):
        reg = WorkerRegistry()
        synced = reg.sync_all_workers_to_db()
        assert len(synced) == 8

        workers = reg.list_workers()
        assert len(workers) >= 8
        worker_ids = {w.id for w in workers}
        assert "worker_w1" in worker_ids
        assert "worker_w8" in worker_ids

    def test_whop_worker_priority_routing(self):
        reg = WorkerRegistry()
        reg.sync_all_workers_to_db()

        # Whop REVIEW should pick an authenticated Whop production worker (w1 to w4)
        worker = reg.get_available_worker("REVIEW", project_id="proj_whop_shortform")
        assert worker is not None
        assert worker.id in ("worker_w1", "worker_w2", "worker_w3", "worker_w4")
        assert worker.metadata.get("role") == "whop_production"

    def test_worker_fallback_when_primary_busy(self):
        reg = WorkerRegistry()
        reg.sync_all_workers_to_db()

        # Exclude worker_w1, should fallback to worker_w2
        worker = reg.get_available_worker("REVIEW", project_id="proj_whop_shortform", exclude_ids=["worker_w1"])
        assert worker is not None
        assert worker.id != "worker_w1"
        assert worker.metadata.get("auth_status") == "AUTHENTICATED"


class TestWorkerScheduler:
    def test_submit_job_success_antigravity(self):
        sched = WorkerScheduler()
        # Mock executor for job
        mock_executor = MagicMock()
        def fake_exec(job):
            job.status = JobStatus.COMPLETED
            job.output_data = {"result": "success"}
            return job
        mock_executor.execute = fake_exec
        sched.worker_pool.register_worker(mock_executor)
        mock_executor.id = "mock_exec"

        with patch.object(sched, "_resolve_executor", return_value=mock_executor), \
             patch.object(sched.resource_governor, "can_dispatch", return_value=(True, None)):
            job = ProductionJob.create("camp_test", "PUNCH_IN_EDIT", {"input": "test.mp4"})
            res = sched.submit_job(job, project_id="proj_whop_shortform")
            assert res.status == JobStatus.COMPLETED

    def test_submit_job_queues_when_governor_saturated(self):
        sched = WorkerScheduler()
        # Force governor to reject
        with patch.object(sched.resource_governor, "can_dispatch", return_value=(False, "Resource saturated")):
            job = ProductionJob.create("camp_test", "REVIEW", {"input": "test.mp4"})
            res = sched.submit_job(job)
            assert res.status == JobStatus.PENDING
            assert sched.queue_size == 1
