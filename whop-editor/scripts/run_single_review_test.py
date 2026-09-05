import logging
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from browser.gemini_reviewer import GeminiReviewer
from browser.profile_registry import ProfileRegistry
from db.repository import DatabaseRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_single_review_test")

VIDEO_FILE = Path("whop-editor/data/output/whop_campaign_final_approved.mp4").resolve()


def run_test(run_number: int = 1):
    print("\n" + "=" * 70)
    print(f"  AUTOMATED GEMINI VIDEO REVIEW — HANDS-FREE TEST RUN #{run_number}")
    print("=" * 70)
    logger.info(f"Target Video: {VIDEO_FILE} ({VIDEO_FILE.stat().st_size} bytes)")
    assert VIDEO_FILE.exists(), f"Video file not found: {VIDEO_FILE}"

    # Initialize Repository for PostgreSQL audit
    try:
        repo = DatabaseRepository()
    except Exception as e:
        logger.warning(f"Database connection warning: {e}")
        repo = None

    job_id = f"job_test_run_{run_number}_{int(time.time())}"
    if repo:
        try:
            repo.create_job(
                job_id=job_id,
                campaign_id=None,
                job_type="REVIEW",
                input_data={"video_file": str(VIDEO_FILE), "run_number": run_number},
                status="in_progress"
            )
        except Exception as e:
            logger.warning(f"Could not create job record: {e}")

    registry = ProfileRegistry()
    reviewer = GeminiReviewer(
        registry=registry,
        headless=False,
        timeout_ms=60000,
        db_repo=repo
    )

    logger.info("Executing automated review (no user interaction)...")
    res = reviewer.review_video(
        video_path=VIDEO_FILE,
        profile_id="flow_profile_2",
        scene_instructions=(
            "Whop Creator Talking-Head Short:\n"
            "- Inspect visual accuracy to the source.\n"
            "- Check punch-in zoom timing and human speaker framing.\n"
            "- Ensure no distracting artifacts or cut-off text.\n"
            "- Return strict JSON with: verdict (PASS/FAIL), overall_score, problems, corrections."
        ),
        campaign_context="Whop Creator Short-Form Campaign",
        job_id=job_id,
        attempt=1
    )

    print("\n" + "=" * 70)
    print(f"  RUN #{run_number} RESULT SUMMARY:")
    print(f"  Verdict:       {res['verdict']}")
    print(f"  Overall Score: {res['overall_score']}/10")
    print(f"  Profile Used:  {res['profile_id']}")
    print(f"  Auth Status:   {res['auth_status']}")
    print(f"  Duration:      {res['review_duration_seconds']}s")
    print(f"  Problems ({len(res['problems'])}):")
    for p in res['problems']:
        print(f"    - {p}")
    print(f"  Corrections ({len(res['corrections'])}):")
    for c in res['corrections']:
        print(f"    - {c}")
    print("=" * 70 + "\n")

    return res


if __name__ == "__main__":
    run_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    res = run_test(run_number=run_num)
    sys.exit(0 if res.get("verdict") in ("PASS", "FAIL") else 1)
