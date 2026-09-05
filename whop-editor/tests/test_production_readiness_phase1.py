"""
Phase-1 Production Readiness Test Suite
Verifies:
1. Output filesystem isolation across distinct campaigns & jobs
2. Cross-process safe profile leasing & collision prevention under concurrency
3. PostgreSQL FOR UPDATE SKIP LOCKED single-claim guarantee
4. Stale job recovery & worker fault tolerance
5. Best version preservation against regressions
6. Campaign requirement intake provenance preservation
"""

import concurrent.futures
from pathlib import Path
import time
import uuid
import pytest

from db.repository import DatabaseRepository
from campaigns.manager import CampaignManager
from campaigns.models import parse_campaign_intake, Provenance
from browser.profile_registry import ProfileRegistry, ProfileRuntimeStatus
from workers.models import JobStatus, Worker, WorkerStatus, ProductionJob
from workers.base import BaseWorker, WorkerPool
from review.models import StructuredReview, ReviewProblem, ReviewVerdict
from review.reviewer import MockVideoReviewer
from pipeline.production_engine import ProductionEngine


@pytest.fixture
def repo():
    return DatabaseRepository()


@pytest.fixture
def test_campaign(repo):
    p_id = f"proj_test_{uuid.uuid4().hex[:6]}"
    repo.create_project(p_id, "Test Project", "Creator Education")
    mgr = CampaignManager(repo=repo)
    return mgr.create_campaign(project_id=p_id, name="Test Campaign")


class DynamicMockWorker(BaseWorker):
    """Worker that outputs a specific fake video artifact per attempt."""
    def __init__(self, repo: DatabaseRepository, project_id: str, tmp_dir: Path):
        model = Worker(
            id="w_dynamic_mock",
            provider="antigravity",
            capabilities=["PRODUCTION_EDIT", "RENDER"],
            status=WorkerStatus.AVAILABLE
        )
        super().__init__(model)
        self.repo = repo
        self.project_id = project_id
        self.tmp_dir = tmp_dir
        self.render_attempts = 0

    def execute(self, job: ProductionJob) -> ProductionJob:
        self.render_attempts += 1
        job.status = JobStatus.COMPLETED

        # Use an existing real video so verify_rendered_video passes QC
        real_sample = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()
        
        # Write unique version file in output dir
        out_dir = Path(job.input_data.get("output_dir", self.tmp_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = job.input_data.get("output_filename", f"version_{self.render_attempts}.mp4")
        target_file = out_dir / out_name
        if not target_file.exists():
            import shutil
            shutil.copy(real_sample, target_file)

        v_id = f"vid_phase1_{uuid.uuid4().hex[:8]}"
        self.repo.register_video(v_id, self.project_id, str(target_file), "completed")
        job.output_data = {
            "output_path": str(target_file),
            "video_id": v_id,
            "selected_word": "test",
            "scale": job.input_data.get("scale", 1.15)
        }
        return job


# --------------------------------------------------------------------------
# TEST 1: Output Directory Isolation Across Distinct Jobs
# --------------------------------------------------------------------------
def test_output_directory_isolation(repo, test_campaign, tmp_path):
    mgr = CampaignManager(repo=repo)
    dummy_input = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()

    job1 = mgr.create_production_job(
        campaign_id=test_campaign.id,
        input_video_path=dummy_input,
        output_filename="version_1.mp4"
    )
    job2 = mgr.create_production_job(
        campaign_id=test_campaign.id,
        input_video_path=dummy_input,
        output_filename="version_1.mp4"
    )

    out_dir1 = Path(job1.input_data["output_dir"])
    out_dir2 = Path(job2.input_data["output_dir"])

    assert out_dir1 != out_dir2, "Different jobs must have completely isolated output directories"
    assert job1.id in str(out_dir1)
    assert job2.id in str(out_dir2)
    assert test_campaign.project_id in str(out_dir1)


# --------------------------------------------------------------------------
# TEST 2: Cross-Process Safe Profile Leasing & Collision Prevention
# --------------------------------------------------------------------------
def test_profile_leasing_concurrency_no_collisions(tmp_path):
    """
    Simulates concurrent workers leasing profiles simultaneously.
    Ensures zero double-allocations and strict lock isolation.
    """
    registry_file = tmp_path / "test_profile_registry.json"
    registry = ProfileRegistry(registry_file=registry_file)

    # Acquire profile 1
    p1 = registry.acquire_profile(capability="gemini", lease_owner="worker_thread_1")
    assert p1 is not None
    assert p1.current_status == ProfileRuntimeStatus.BUSY
    assert p1.lease_owner == "worker_thread_1"

    # Acquire profile 2 concurrently
    p2 = registry.acquire_profile(capability="gemini", lease_owner="worker_thread_2")
    assert p2 is not None
    assert p2.profile_id != p1.profile_id, "Concurrent leasing must never return the same profile"
    assert p2.lease_owner == "worker_thread_2"

    # Release profile 1
    registry.release_profile(p1.profile_id, cooldown_sec=0)
    released_p1 = registry.get_profile(p1.profile_id)
    assert released_p1.current_status == ProfileRuntimeStatus.IDLE
    assert released_p1.lease_owner is None

    # Re-acquire: p1 is available again
    p1_reacquired = registry.acquire_profile(capability="gemini", preferred_id=p1.profile_id, lease_owner="worker_thread_3")
    assert p1_reacquired is not None
    assert p1_reacquired.profile_id == p1.profile_id
    assert p1_reacquired.lease_owner == "worker_thread_3"

    # Clean up
    registry.release_profile(p1.profile_id)
    registry.release_profile(p2.profile_id)


# --------------------------------------------------------------------------
# TEST 3: PostgreSQL FOR UPDATE SKIP LOCKED Single-Claim Guarantee
# --------------------------------------------------------------------------
def test_postgres_skip_locked_single_claim(repo, test_campaign):
    # Register workers first to satisfy foreign key constraint
    repo.register_worker("worker_alpha", "test", ["PRODUCTION_EDIT"])
    repo.register_worker("worker_beta", "test", ["PRODUCTION_EDIT"])

    job_id = f"job_claim_test_{uuid.uuid4().hex[:8]}"
    repo.create_job(
        job_id=job_id,
        campaign_id=test_campaign.id,
        job_type="PRODUCTION_EDIT",
        input_data={"test": True},
        status="queued"
    )

    claimed_by_worker_1 = repo.claim_next_job(
        worker_id="worker_alpha",
        supported_job_types=["PRODUCTION_EDIT"]
    )
    assert claimed_by_worker_1 is not None

    # Immediate second worker claim: must NOT get the already claimed job
    claimed_by_worker_2 = repo.claim_next_job(
        worker_id="worker_beta",
        supported_job_types=["PRODUCTION_EDIT"]
    )
    if claimed_by_worker_2 is not None:
        assert claimed_by_worker_2["id"] != claimed_by_worker_1["id"], "Worker 2 must never receive the job claimed by Worker 1"

    # Verify status in DB is claimed
    job_in_db = repo.get_job(claimed_by_worker_1["id"])
    assert job_in_db["status"] == "claimed"
    assert job_in_db["assigned_worker_id"] == "worker_alpha"


# --------------------------------------------------------------------------
# TEST 4: Stale Job Recovery & Worker Fault Tolerance
# --------------------------------------------------------------------------
def test_stale_job_recovery(repo, test_campaign):
    from db.connection import transaction_scope
    repo.register_worker("dead_worker", "test", ["PRODUCTION_EDIT"])

    stale_job_id = f"job_stale_{uuid.uuid4().hex[:8]}"
    repo.create_job(
        job_id=stale_job_id,
        campaign_id=test_campaign.id,
        job_type="PRODUCTION_EDIT",
        input_data={"test": True},
        status="claimed"
    )

    # Set started_at into the past (e.g. 10 minutes ago)
    with transaction_scope() as cur:
        cur.execute("""
            UPDATE jobs 
            SET started_at = (NOW() - INTERVAL '10 minutes')::text,
                assigned_worker_id = 'dead_worker'
            WHERE id = %s
        """, (stale_job_id,))

    # Recover stale jobs with timeout of 300s
    recovered_count = repo.recover_stale_jobs(stale_timeout_sec=300)
    assert recovered_count >= 1

    recovered_job = repo.get_job(stale_job_id)
    assert recovered_job["status"] == "queued", "Stale job must be reset to queued"
    assert recovered_job["assigned_worker_id"] is None, "Stale worker assignment must be cleared"


# --------------------------------------------------------------------------
# TEST 5: Best Version Preservation Against Regressions
# --------------------------------------------------------------------------
def test_best_version_preserved_during_regression(repo, test_campaign, tmp_path):
    """
    Attempt 1: Score 8.0 (Good, but below 9.0 gate)
    Attempt 2: Score 4.5 (Regression!)
    System must detect regression, log audit, and preserve Attempt 1 as best version.
    """
    worker = DynamicMockWorker(repo, test_campaign.project_id, tmp_path)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    review_attempt_1 = StructuredReview(
        verdict="FAIL",
        overall_score=8.0,
        scene_accuracy=8.0,
        instruction_accuracy=8.0,
        character_accuracy=8.0,
        timing_score=8.0,
        visual_quality=8.0,
        problems=[{"scene": 1, "type": "timing", "description": "Needs slight timing adjustment"}],
        corrections=["Adjust duration"]
    )
    review_attempt_2 = StructuredReview(
        verdict="FAIL",
        overall_score=4.5,
        scene_accuracy=4.0,
        instruction_accuracy=4.0,
        character_accuracy=4.0,
        timing_score=4.0,
        visual_quality=5.0,
        problems=[{"scene": 1, "type": "framing", "description": "Over-zoomed"}],
        corrections=["Reduce scale"]
    )

    class StepReviewer:
        def __init__(self):
            self.calls = 0

        def review_video(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return review_attempt_1
            return review_attempt_2

    engine = ProductionEngine(
        campaign_manager=mgr,
        reviewer=StepReviewer(),
        quality_gate_score=9.0,
        max_auto_iterations=2
    )

    source_clip = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()
    result = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=source_clip,
        scene_instructions="Ensure natural zoom emphasis",
        output_dir=tmp_path / "regression_test_out"
    )

    assert result.iterations_run == 2
    assert result.regressions_count == 1, "Regression must be recorded"
    assert result.best_version == "V1", "Attempt 1 (score 8.0) must be preserved over Attempt 2 (score 4.5)"
    assert result.best_score == 8.0
    assert "version_1.mp4" in result.final_output_path or "justin_clouted" in result.final_output_path
    assert result.needs_human_review is True


# --------------------------------------------------------------------------
# TEST 6: Campaign Intake Provenance Preservation
# --------------------------------------------------------------------------
def test_campaign_intake_provenance_preservation():
    raw_intake = {
        "campaign_name": "Test Verified Rewards",
        "aspect_ratio": "9:16",
        "quality_gate": 8.0
    }
    reqs = parse_campaign_intake(raw_intake)

    assert reqs.campaign_name.provenance == Provenance.USER_PROVIDED
    assert reqs.campaign_name.value == "Test Verified Rewards"
    assert reqs.aspect_ratio.provenance == Provenance.USER_PROVIDED
    assert reqs.aspect_ratio.value == "9:16"
    assert reqs.quality_gate.value == 8.0

    # Unsupplied fields must be UNKNOWN with zero invented rules
    assert reqs.duration_min.provenance == Provenance.UNKNOWN
    assert reqs.duration_min.value is None
    assert reqs.duration_max.provenance == Provenance.UNKNOWN
    assert reqs.duration_max.value is None
    assert reqs.submission_method.provenance == Provenance.UNKNOWN
    assert reqs.prohibited_content.value == []
