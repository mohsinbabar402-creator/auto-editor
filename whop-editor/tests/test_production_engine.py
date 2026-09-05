import pytest
import uuid
from pathlib import Path

from db.repository import DatabaseRepository
from campaigns.manager import CampaignManager
from workers.models import Worker, WorkerStatus, ProductionJob, JobStatus
from workers.base import BaseWorker, WorkerPool
from review.models import StructuredReview, ReviewProblem, ReviewVerdict
from review.reviewer import MockVideoReviewer
from pipeline.production_engine import ProductionEngine


class MockProductionWorker(BaseWorker):
    def __init__(self, repo: DatabaseRepository, project_id: str, worker_id: str = "w_prod_mock"):
        model = Worker(
            id=worker_id,
            provider="antigravity",
            capabilities=["PRODUCTION_EDIT", "RENDER"],
            status=WorkerStatus.AVAILABLE
        )
        super().__init__(model)
        self.repo = repo
        self.project_id = project_id
        self.render_count = 0
        self.last_scale = None
        self.last_duration_ms = None

    def execute(self, job: ProductionJob) -> ProductionJob:
        self.render_count += 1
        self.last_scale = job.input_data.get("scale")
        self.last_duration_ms = job.input_data.get("duration_ms")
        job.status = JobStatus.COMPLETED
        # Return a valid existing sample file for QC pass
        dummy_out = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()
        v_id = f"vid_test_{uuid.uuid4().hex[:8]}"
        self.repo.register_video(v_id, self.project_id, str(dummy_out), "completed")
        job.output_data = {
            "output_path": str(dummy_out),
            "video_id": v_id,
            "selected_word": "differential",
            "scale": self.last_scale or 1.15
        }
        return job


@pytest.fixture
def repo():
    return DatabaseRepository()


@pytest.fixture
def test_campaign(repo):
    proj_id = f"proj_pe_{uuid.uuid4().hex[:6]}"
    repo.create_project(proj_id, "Engine Test Proj", "Shorts")
    mgr = CampaignManager(repo=repo)
    return mgr.create_campaign(project_id=proj_id, name="Engine Test Campaign")


def test_production_engine_pass_on_first_try(repo, test_campaign):
    worker = MockProductionWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)

    mgr = CampaignManager(repo=repo, worker_pool=pool)
    reviewer = MockVideoReviewer(should_pass=True)

    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=3)
    sample_vid = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4")

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=sample_vid,
        scene_instructions="Center talking head on emphasized word with punch-in zoom."
    )

    assert res.success is True
    assert res.final_verdict == "PASS"
    assert res.review_attempts == 1
    assert res.qc_passed is True
    assert worker.render_count == 1


def test_production_engine_correction_loop(repo, test_campaign):
    worker = MockProductionWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)

    mgr = CampaignManager(repo=repo, worker_pool=pool)

    # First attempt fails, second attempt passes
    class TwoStageReviewer:
        def __init__(self):
            self.attempt = 0

        def review_video(self, video_path, scene_instructions, campaign_context=None):
            self.attempt += 1
            if self.attempt == 1:
                return StructuredReview(
                    verdict="FAIL",
                    overall_score=5.5,
                    scene_accuracy=5.0,
                    instruction_accuracy=6.0,
                    timing_score=5.0,
                    problems=[{"scene": 1, "type": "scale", "description": "Punch-in scale too low"}],
                    corrections=["Adjust scale to 1.20x and extend duration."]
                )
            else:
                return StructuredReview(
                    verdict="PASS",
                    overall_score=10.0,
                    scene_accuracy=10.0,
                    instruction_accuracy=10.0,
                    timing_score=10.0,
                    problems=[],
                    corrections=[]
                )

    reviewer = TwoStageReviewer()
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=3)
    sample_vid = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4")

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=sample_vid,
        scene_instructions="Ensure punch-in zoom is clear and well-timed."
    )

    assert res.success is True
    assert res.review_attempts == 2
    assert res.final_verdict == "PASS"
    assert worker.render_count == 2
    # Verify corrections were applied on second render
    assert worker.last_scale == 1.20


def test_production_engine_exceeds_max_retries_flags_human_review(repo, test_campaign):
    worker = MockProductionWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)

    mgr = CampaignManager(repo=repo, worker_pool=pool)
    always_fail_reviewer = MockVideoReviewer(should_pass=False)

    engine = ProductionEngine(campaign_manager=mgr, reviewer=always_fail_reviewer, max_review_retries=2)
    sample_vid = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4")

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=sample_vid,
        scene_instructions="Strict instructions that cannot be met automatically."
    )

    assert res.success is False
    assert res.needs_human_review is True
    assert res.final_verdict == ReviewVerdict.NEEDS_HUMAN_REVIEW.value
    assert res.review_attempts == 2
    # Confirm it stopped and didn't loop infinitely
    assert worker.render_count == 2
