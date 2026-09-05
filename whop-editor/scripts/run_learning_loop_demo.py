import json
import logging
from pathlib import Path
import sys
import time

# Add whop-editor to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.repository import DatabaseRepository
from campaigns.manager import CampaignManager
from workers.base import WorkerPool, AntigravityWorker
from review.reviewer import GeminiBrowserReviewer
from pipeline.production_engine import ProductionEngine
from learning.knowledge_engine import KnowledgeEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("learning_loop_demo")


def run_learning_loop():
    print("=" * 75)
    print(" WHOP PRODUCTION SYSTEM — CLOSED-LOOP SELF-IMPROVING DEMONSTRATION")
    print("=" * 75)
    print("Executing Master Directive loop:")
    print("REAL WHOP SOURCE -> ANALYSIS -> EDIT -> RENDER -> QC -> GEMINI REVIEW")
    print("-> FEEDBACK INTERPRETATION -> CORRECTION PLAN -> RE-RENDER -> QC")
    print("-> GEMINI REVIEW -> APPROVAL -> PERSISTENT LEARNING IN POSTGRESQL\n")

    repo = DatabaseRepository()
    knowledge_engine = KnowledgeEngine(repo)

    # 1. Setup Worker Pool
    pool = WorkerPool(max_concurrent_workers=2)
    for i in range(1, 4):
        pool.register_worker(AntigravityWorker(f"worker_antigravity_{i:02d}"))

    # 2. Campaign Manager
    camp_mgr = CampaignManager(repo=repo, worker_pool=pool)
    campaign = camp_mgr.create_campaign(
        project_id="proj_whop_shortform",
        name="Whop Self-Improving Demo Campaign",
        campaign_id="camp_whop_learning_loop",
        config={
            "niche": "Whop Creator Education",
            "format": "9:16 vertical short-form"
        }
    )

    # 3. Check existing validated knowledge before starting
    initial_params = knowledge_engine.get_validated_parameters("proj_whop_shortform")
    print(f">> Initial Learned Parameters from PostgreSQL: {initial_params}\n")

    # 4. Reviewer with profile flow_profile_2
    reviewer = GeminiBrowserReviewer(
        profile_id="flow_profile_2",
        headless=False,
        timeout_ms=60000,
        db_repo=repo
    )

    # 5. Production Engine
    engine = ProductionEngine(
        campaign_manager=camp_mgr,
        reviewer=reviewer,
        max_review_retries=2
    )

    source_video = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()
    scene_instructions = (
        "Whop Creator Talking-Head Short:\n"
        "- Justin Banusing speaking about gaming leagues and monetization.\n"
        "- Centered 9:16 vertical framing.\n"
        "- Clean punch-in zoom applied on emphasized key term 'differential'.\n"
        "- Natural pacing, zero black bars, clear audio."
    )

    # 6. Execute Production with Automated Review & Correction Loop
    t0 = time.time()
    result = engine.produce_campaign_video(
        campaign_id=campaign.id,
        source_video_path=source_video,
        scene_instructions=scene_instructions,
        output_filename="whop_learning_loop_output.mp4"
    )
    total_time = time.time() - t0

    # 7. Audit and Report Database Learning Records
    print("\n" + "=" * 75)
    print(f" PRODUCTION CYCLE SUMMARY (Duration: {total_time:.2f}s)")
    print("=" * 75)
    print(f"Success:            {result.success}")
    print(f"Final Verdict:      {result.final_verdict}")
    print(f"Review Attempts:    {result.review_attempts}")
    print(f"QC Passed:          {result.qc_passed}")
    print(f"Needs Human Review: {result.needs_human_review}")
    print(f"Final Output:       {result.final_output_path}")

    # Query Knowledge and Evidence in DB
    print("\n" + "=" * 75)
    print(" POSTGRESQL PERSISTENT KNOWLEDGE RECORDS")
    print("=" * 75)
    knowledge_records = repo.list_knowledge(project_id="proj_whop_shortform")
    for k in knowledge_records:
        print(f"Knowledge ID:  {k['id']}")
        print(f"  Status:      {k['status'].upper()}")
        print(f"  Confidence:  {k['confidence']:.2f}")
        print(f"  Sample Size: {k['sample_size']}")
        print(f"  Parameters:  {k['parameters_json']}")
        print(f"  Created At:  {k['created_at']}")
        print("-" * 50)

    # Query Evidence Records
    print("\n" + "=" * 75)
    print(" POSTGRESQL PERSISTENT EVIDENCE CHAIN")
    print("=" * 75)
    from db.connection import transaction_scope
    with transaction_scope() as cur:
        cur.execute("""
            SELECT e.id, e.knowledge_id, e.outcome_note, e.metric_value, e.created_at
            FROM evidence e
            ORDER BY e.created_at DESC
            LIMIT 10;
        """)
        evidence_rows = cur.fetchall()
        for ev in evidence_rows:
            print(f"Evidence ID:   {ev[0]}")
            print(f"  Knowledge:   {ev[1]}")
            print(f"  Score:       {ev[3]}")
            print(f"  Outcome:     {ev[2]}")
            print(f"  Timestamp:   {ev[4]}")
            print("-" * 50)

    # Query Recent Audit Trail
    print("\n" + "=" * 75)
    print(" POSTGRESQL AUDIT TRAIL (DECISION & CORRECTION LOG)")
    print("=" * 75)
    with transaction_scope() as cur:
        cur.execute("""
            SELECT id, action, target, detail, created_at
            FROM audit_log
            ORDER BY created_at DESC
            LIMIT 6;
        """)
        audit_rows = cur.fetchall()
        for a in audit_rows:
            print(f"[{a[4]}] {a[1]:<28} | Target: {a[2]:<16} | {a[3]}")

    print(f"\n[OK] Learning Loop Execution Complete!")
    return result


if __name__ == "__main__":
    res = run_learning_loop()
    sys.exit(0 if res.success else 1)
