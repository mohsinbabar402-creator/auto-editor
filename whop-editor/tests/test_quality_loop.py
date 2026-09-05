import pytest
import uuid
from pathlib import Path
from pydantic import ValidationError

from db.repository import DatabaseRepository
from campaigns.manager import CampaignManager
from workers.models import Worker, WorkerStatus, ProductionJob, JobStatus
from workers.base import BaseWorker, WorkerPool
from review.models import StructuredReview, ReviewVerdict
from pipeline.production_engine import ProductionEngine
from analysis.feedback_interpreter import FeedbackInterpreter, IssueType


class IterationTrackingWorker(BaseWorker):
    """Worker that outputs a distinct video ID and file path for each render attempt."""
    def __init__(self, repo: DatabaseRepository, project_id: str, worker_id: str = "w_iter_track"):
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
        self.rendered_paths = []
        self.history = []

    def execute(self, job: ProductionJob) -> ProductionJob:
        self.render_count += 1
        scale = job.input_data.get("scale")
        duration_ms = job.input_data.get("duration_ms")
        self.history.append({"scale": scale, "duration_ms": duration_ms})
        
        # Point to real sample video so QC passes
        base_sample = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()
        v_id = f"vid_iter_{self.render_count}_{uuid.uuid4().hex[:6]}"
        out_path = base_sample.parent / f"test_out_v{self.render_count}.mp4"
        
        # Create a lightweight copy or reference
        if not out_path.exists() and base_sample.exists():
            import shutil
            shutil.copy2(base_sample, out_path)
        self.rendered_paths.append(str(out_path))

        self.repo.register_video(v_id, self.project_id, str(out_path), "completed")
        job.status = JobStatus.COMPLETED
        job.output_data = {
            "output_path": str(out_path),
            "video_id": v_id,
            "selected_word": "differential",
            "scale": scale or 1.15,
            "duration_ms": duration_ms or 1000
        }
        return job


class ScriptedSequenceReviewer:
    """Reviewer that returns a scripted sequence of StructuredReview objects."""
    def __init__(self, script):
        self.script = script  # List of StructuredReview
        self.call_count = 0
        self.reviewed_paths = []

    def review_video(self, video_path, scene_instructions, campaign_context=None):
        self.reviewed_paths.append(str(video_path))
        idx = min(self.call_count, len(self.script) - 1)
        res = self.script[idx]
        self.call_count += 1
        return res


@pytest.fixture
def repo():
    return DatabaseRepository()


@pytest.fixture
def test_campaign(repo):
    proj_id = f"proj_ql_{uuid.uuid4().hex[:6]}"
    repo.create_project(proj_id, "Quality Loop Project", "Shorts")
    mgr = CampaignManager(repo=repo)
    return mgr.create_campaign(project_id=proj_id, name="Quality Loop Campaign")


def cleanup_rendered_paths(paths):
    for p in paths:
        path_obj = Path(p)
        if "test_out_v" in path_obj.name and path_obj.exists():
            try:
                path_obj.unlink()
            except Exception:
                pass


# SCENARIO 1, 2, 3: Scores 4.5, 7.0, and 9.5 continue the loop
def test_quality_gate_loop_continues_at_sub_10_scores(repo, test_campaign):
    worker = IterationTrackingWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    # 4.5 -> 7.0 -> 9.5 -> 10.0
    script = [
        StructuredReview(
            verdict="FAIL",
            overall_score=4.5,
            scene_accuracy=4.0,
            instruction_accuracy=4.5,
            timing_score=4.0,
            visual_quality=5.0,
            problems=[{"type": "framing", "description": "Too wide, punch in tighter"}],
            corrections=["Scale up to 1.20x"]
        ),
        StructuredReview(
            verdict="FAIL",
            overall_score=7.0,
            scene_accuracy=7.0,
            instruction_accuracy=7.0,
            timing_score=7.0,
            visual_quality=7.0,
            problems=[{"type": "timing", "description": "Hold punch in longer, extend duration"}],
            corrections=["Extend duration to 1250ms"]
        ),
        StructuredReview(
            verdict="FAIL",
            overall_score=9.5,
            scene_accuracy=9.5,
            instruction_accuracy=9.5,
            timing_score=9.5,
            visual_quality=9.5,
            problems=[{"type": "framing", "description": "Slightly closer punch in needed"}],
            corrections=["Scale up to 1.25x"]
        ),
        StructuredReview(
            verdict="PASS",
            overall_score=10.0,
            scene_accuracy=10.0,
            instruction_accuracy=10.0,
            timing_score=10.0,
            visual_quality=10.0,
            problems=[],
            corrections=[]
        ),
    ]
    reviewer = ScriptedSequenceReviewer(script)
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=10)

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=Path("whop-editor/data/input/justin_clouted_whop_12s.mp4"),
        scene_instructions="Center talking head with punch-in zoom on emphasized word."
    )

    cleanup_rendered_paths(worker.rendered_paths)

    # Verifies loop did NOT stop at 4.5, 7.0, or 9.5; it proceeded all the way to 10.0
    assert res.review_attempts == 4
    assert res.best_score == 10.0
    assert res.success is True
    assert res.final_verdict == "PASS"
    assert res.needs_human_review is True  # Section 11: When gate reached, flag human review


# SCENARIO 4: Score 10.0 triggers human review
def test_score_10_triggers_human_review(repo, test_campaign):
    worker = IterationTrackingWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    script = [
        StructuredReview(
            verdict="PASS",
            overall_score=10.0,
            scene_accuracy=10.0,
            instruction_accuracy=10.0,
            timing_score=10.0,
            visual_quality=10.0,
            problems=[],
            corrections=[]
        )
    ]
    reviewer = ScriptedSequenceReviewer(script)
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=5)

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=Path("whop-editor/data/input/justin_clouted_whop_12s.mp4"),
        scene_instructions="Flawless edit."
    )
    cleanup_rendered_paths(worker.rendered_paths)

    assert res.success is True
    assert res.needs_human_review is True
    assert res.review_attempts == 1
    assert res.best_score == 10.0


# SCENARIO 5: Score > 10.0 or invalid score is rejected by schema
def test_score_greater_than_10_or_invalid_rejected():
    with pytest.raises(ValidationError):
        StructuredReview(
            verdict="PASS",
            overall_score=10.5,  # Exceeds 10.0
            scene_accuracy=10.0,
            instruction_accuracy=10.0,
            timing_score=10.0,
            visual_quality=10.0
        )

    with pytest.raises(ValidationError):
        StructuredReview(
            verdict="PASS",
            overall_score=-1.0,  # Negative score
            scene_accuracy=5.0,
            instruction_accuracy=5.0,
            timing_score=5.0,
            visual_quality=5.0
        )


# SCENARIO 6: Iteration limit reached while score < 10 -> NEEDS_HUMAN_REVIEW + QUALITY_GATE_NOT_REACHED
def test_emergency_limit_reached_below_quality_gate(repo, test_campaign):
    worker = IterationTrackingWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    script = [
        StructuredReview(
            verdict="FAIL",
            overall_score=6.0,
            scene_accuracy=6.0,
            instruction_accuracy=6.0,
            timing_score=6.0,
            visual_quality=6.0,
            problems=[{"type": "framing", "description": "Punch in tighter"}],
            corrections=["Scale to 1.20x"]
        ),
        StructuredReview(
            verdict="FAIL",
            overall_score=6.5,
            scene_accuracy=6.5,
            instruction_accuracy=6.5,
            timing_score=6.5,
            visual_quality=6.5,
            problems=[{"type": "timing", "description": "Extend duration"}],
            corrections=["Extend duration to 1100ms"]
        ),
        StructuredReview(
            verdict="FAIL",
            overall_score=7.0,
            scene_accuracy=7.0,
            instruction_accuracy=7.0,
            timing_score=7.0,
            visual_quality=7.0,
            problems=[{"type": "framing", "description": "Still slightly off"}],
            corrections=["Scale to 1.25x"]
        ),
    ]
    reviewer = ScriptedSequenceReviewer(script)
    # Set limit to 3
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=3)

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=Path("whop-editor/data/input/justin_clouted_whop_12s.mp4"),
        scene_instructions="Difficult edit reaching emergency ceiling."
    )
    cleanup_rendered_paths(worker.rendered_paths)

    assert res.success is False
    assert res.needs_human_review is True
    assert res.final_verdict == ReviewVerdict.NEEDS_HUMAN_REVIEW.value
    assert "QUALITY_GATE_NOT_REACHED" in (res.error_message or "")
    assert res.review_attempts == 3
    assert res.best_score == 7.0


# SCENARIO 7: New version better -> becomes BEST_VERSION
def test_new_version_better_becomes_best_version(repo, test_campaign):
    worker = IterationTrackingWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    script = [
        StructuredReview(
            verdict="FAIL",
            overall_score=5.0,
            scene_accuracy=5.0,
            instruction_accuracy=5.0,
            timing_score=5.0,
            visual_quality=5.0,
            problems=[{"type": "framing", "description": "Crop tighter"}],
            corrections=["Scale 1.20x"]
        ),
        StructuredReview(
            verdict="FAIL",
            overall_score=8.5,
            scene_accuracy=8.5,
            instruction_accuracy=8.5,
            timing_score=8.5,
            visual_quality=8.5,
            problems=[{"type": "timing", "description": "Good framing, tweak timing"}],
            corrections=["Hold longer"]
        )
    ]
    reviewer = ScriptedSequenceReviewer(script)
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=2)

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=Path("whop-editor/data/input/justin_clouted_whop_12s.mp4"),
        scene_instructions="Testing best version advancement."
    )
    cleanup_rendered_paths(worker.rendered_paths)

    assert res.best_score == 8.5
    # Worker rendered 2 versions; best output path should be the second version
    assert res.final_output_path == worker.rendered_paths[1]
    assert res.regressions_count == 0


# SCENARIO 8: New version worse -> BEST_VERSION preserved (Regression Protection)
def test_new_version_worse_preserves_best_version(repo, test_campaign):
    worker = IterationTrackingWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    script = [
        StructuredReview(
            verdict="FAIL",
            overall_score=7.8,
            scene_accuracy=8.0,
            instruction_accuracy=8.0,
            timing_score=7.5,
            visual_quality=7.8,
            problems=[{"type": "framing", "description": "Punch in tighter"}],
            corrections=["Scale 1.25x"]
        ),
        # Version 2 regresses to 4.2
        StructuredReview(
            verdict="FAIL",
            overall_score=4.2,
            scene_accuracy=4.0,
            instruction_accuracy=4.0,
            timing_score=4.0,
            visual_quality=4.2,
            problems=[{"type": "framing", "description": "Way too tight now"}],
            corrections=["Pull back"]
        )
    ]
    reviewer = ScriptedSequenceReviewer(script)
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=2)

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=Path("whop-editor/data/input/justin_clouted_whop_12s.mp4"),
        scene_instructions="Testing regression preservation."
    )
    cleanup_rendered_paths(worker.rendered_paths)

    assert res.best_score == 7.8
    # Regression occurred: best output path must remain Version 1's path!
    assert res.final_output_path == worker.rendered_paths[0]
    assert res.regressions_count == 1


# SCENARIO 9: Repeated ineffective correction -> alternative strategy / safe stop
def test_repeated_ineffective_strategy_diverts_and_safely_stops(repo, test_campaign):
    # Test strategy diversion in FeedbackInterpreter
    plan_scale_blocked = FeedbackInterpreter.interpret_gemini_review(
        corrections=["Punch in tighter scale 1.22x"],
        problems=[{"type": "framing", "description": "Crop tighter"}],
        current_scale=1.15,
        current_duration_ms=800,
        ineffective_strategies=["scale"]
    )
    # When scale is ineffective, it must divert to timing
    assert plan_scale_blocked.scale_adjustment is None
    assert plan_scale_blocked.duration_ms_adjustment is not None
    assert plan_scale_blocked.issue_type == IssueType.TIMING

    # When both scale and duration are ineffective, it safely signals exhaustion
    plan_exhausted = FeedbackInterpreter.interpret_gemini_review(
        corrections=["Punch in tighter scale 1.22x and hold longer"],
        problems=[{"type": "framing", "description": "Crop tighter"}],
        current_scale=1.15,
        current_duration_ms=800,
        ineffective_strategies=["scale", "duration_ms"]
    )
    assert plan_exhausted.confidence == 0.0
    assert plan_exhausted.scale_adjustment is None
    assert plan_exhausted.duration_ms_adjustment is None


# SCENARIO 10: Gemini review corresponds to actual rendered output
def test_gemini_review_corresponds_to_actual_rendered_output(repo, test_campaign):
    worker = IterationTrackingWorker(repo, test_campaign.project_id)
    pool = WorkerPool(max_concurrent_workers=1)
    pool.register_worker(worker)
    mgr = CampaignManager(repo=repo, worker_pool=pool)

    script = [
        StructuredReview(
            verdict="FAIL",
            overall_score=6.0,
            problems=[{"type": "framing", "description": "Adjust scale"}],
            corrections=["Scale 1.20x"]
        ),
        StructuredReview(
            verdict="PASS",
            overall_score=10.0,
            problems=[],
            corrections=[]
        )
    ]
    reviewer = ScriptedSequenceReviewer(script)
    engine = ProductionEngine(campaign_manager=mgr, reviewer=reviewer, max_review_retries=2)

    res = engine.produce_campaign_video(
        campaign_id=test_campaign.id,
        source_video_path=Path("whop-editor/data/input/justin_clouted_whop_12s.mp4"),
        scene_instructions="Review artifact correspondence verification."
    )
    cleanup_rendered_paths(worker.rendered_paths)

    # Reviewer must have been called exactly for the files rendered by the worker
    assert len(reviewer.reviewed_paths) == 2
    assert reviewer.reviewed_paths[0] == worker.rendered_paths[0]
    assert reviewer.reviewed_paths[1] == worker.rendered_paths[1]
    # And the paths must be distinct (not reviewing the same artifact or raw JSON)
    assert reviewer.reviewed_paths[0] != reviewer.reviewed_paths[1]
