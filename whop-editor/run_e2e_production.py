import logging
from pathlib import Path
import sys
import time

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.repository import DatabaseRepository
from campaigns.manager import CampaignManager
from workers.models import Worker, WorkerStatus
from workers.base import WorkerPool, AntigravityWorker
from review.reviewer import GeminiBrowserReviewer, MockVideoReviewer
from pipeline.production_engine import ProductionEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("whop_production_e2e")


def run_e2e(use_browser: bool = True):
    repo = DatabaseRepository()
    
    # 1. Initialize Worker Pool with 5 Workers (concurrency limit = 2)
    pool = WorkerPool(max_concurrent_workers=2)
    for i in range(1, 6):
        w_id = f"worker_antigravity_{i:02d}"
        pool.register_worker(AntigravityWorker(w_id))
    
    # 2. Campaign Manager
    camp_mgr = CampaignManager(repo=repo, worker_pool=pool)
    campaign = camp_mgr.create_campaign(
        project_id="proj_whop_shortform",
        name="Whop Creator Launch Campaign",
        campaign_id="camp_whop_launch_2026",
        config={
            "niche": "Whop Creator Education",
            "format": "9:16 vertical short-form",
            "target_punchin_scale": 1.15
        }
    )
    logger.info(f"Campaign active: [{campaign.id}] {campaign.name}")

    # 3. Choose Reviewer
    if use_browser:
        # Uses proven automated GeminiBrowserReviewer backed by ProfileRegistry & flow_profile_2
        reviewer = GeminiBrowserReviewer(
            profile_id="flow_profile_2",
            headless=False,
            timeout_ms=60000,
            db_repo=repo
        )
    else:
        logger.warning("Falling back to MockVideoReviewer for offline test.")
        reviewer = MockVideoReviewer(should_pass=True)

    # 4. Initialize Production Engine
    engine = ProductionEngine(
        campaign_manager=camp_mgr,
        reviewer=reviewer,
        max_review_retries=3
    )

    source_video = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()
    scene_instructions = (
        "Whop Creator Talking-Head Short:\n"
        "- Justin Banusing speaking about gaming leagues and monetization.\n"
        "- Centered 9:16 vertical framing.\n"
        "- Clean punch-in zoom applied on emphasized key term 'differential'.\n"
        "- Natural pacing, zero black bars, clear audio."
    )

    # 5. Execute Production Pipeline with Review & Correction Loop
    t0 = time.time()
    result = engine.produce_campaign_video(
        campaign_id=campaign.id,
        source_video_path=source_video,
        scene_instructions=scene_instructions,
        output_filename="whop_campaign_final_approved.mp4"
    )
    duration = time.time() - t0

    logger.info("=" * 65)
    logger.info(f"E2E PRODUCTION RESULT: Success={result.success} in {duration:.2f}s")
    logger.info(f"Final Output: {result.final_output_path}")
    logger.info(f"Verdict: {result.final_verdict}")
    logger.info(f"Review Attempts: {result.review_attempts}")
    logger.info(f"QC Passed: {result.qc_passed}")
    if result.latest_review:
        logger.info(f"Overall Score: {result.latest_review.overall_score}/10")
        logger.info(f"Problems Found: {len(result.latest_review.problems)}")
        logger.info(f"Corrections Applied: {result.latest_review.corrections}")
    logger.info("=" * 65)

    return result


if __name__ == "__main__":
    res = run_e2e(use_browser=True)
    sys.exit(0 if res.success else 1)
