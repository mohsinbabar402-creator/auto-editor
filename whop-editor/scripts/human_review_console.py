import argparse
import logging
from pathlib import Path
import sys
import uuid

# Ensure whop-editor in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.connection import transaction_scope
from db.repository import DatabaseRepository
from learning.knowledge_engine import KnowledgeEngine, KnowledgeStatus
from analysis.feedback_interpreter import FeedbackInterpreter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("human_review_console")


def run_human_review(decision: str = "A", feedback: str = "Framing and zoom look clean, approved for publication."):
    repo = DatabaseRepository()
    engine = KnowledgeEngine(repo)

    print("=" * 75)
    print(" HUMAN REVIEW & DECISION CONSOLE (FINAL QUALITY GATE)")
    print("=" * 75)

    # Fetch latest job requiring review or latest job
    with transaction_scope() as cur:
        cur.execute("""
            SELECT j.id, j.campaign_id, j.status, j.input_data_json, j.error_message
            FROM jobs j
            ORDER BY j.created_at DESC
            LIMIT 1;
        """)
        job_row = cur.fetchone()

        cur.execute("""
            SELECT v.id, v.file_path, v.status
            FROM videos v
            ORDER BY v.created_at DESC
            LIMIT 1;
        """)
        video_row = cur.fetchone()

        cur.execute("""
            SELECT r.id, r.attempt, r.verdict, r.overall_score, r.problems_json, r.corrections_json
            FROM reviews r
            ORDER BY r.created_at DESC
            LIMIT 1;
        """)
        review_row = cur.fetchone()

    if not job_row or not video_row:
        print("[!] No recent production jobs or videos found in database.")
        return

    job_id, camp_id, job_status, input_json, err_msg = job_row
    video_id, file_path, video_status = video_row
    rev_id, attempt, verdict, score, problems, corrections = review_row if review_row else ("none", 0, "NONE", 0.0, "[]", "[]")

    print(f"Latest Production Job: [{job_id}] (Status: {job_status})")
    print(f"Rendered Media:       {file_path} (Current Status: {video_status})")
    print(f"Gemini Review:        Verdict={verdict}, Score={score}/10, Attempt={attempt}")
    print(f"Problems Identified:  {problems}")
    print("-" * 75)

    decision_clean = decision.strip().upper()
    if decision_clean in ["A", "APPROVE"]:
        print(f"\n>> Human Editor APPROVED video [{video_id}].")
        print(f"Feedback: '{feedback}'")

        # 1. Update Video Status in PostgreSQL
        repo.update_video_status(video_id, "approved")
        repo.update_job(job_id, status="COMPLETED")

        # 2. Record Positive Learning Outcome into Knowledge Engine
        learned = engine.record_edit_outcome(
            project_id="proj_whop_shortform",
            video_id=video_id,
            event_type="HUMAN_APPROVAL",
            action_type="PUNCH_IN_PARAMS",
            parameters={"scale": 1.20, "duration_ms": 1100, "target_word": "differential"},
            approved=True,
            score=9.5,
            outcome_note=f"Human Editor approved after Gemini critique: '{feedback}'"
        )

        repo.log_audit(
            audit_id=f"audit_human_{uuid.uuid4().hex[:8]}",
            action="HUMAN_APPROVE",
            target=video_id,
            detail=f"Approved with feedback: '{feedback}'. Promoted Knowledge [{learned.get('id')}]."
        )

        print("\n" + "=" * 75)
        print(" [OK] PRODUCTION VERSION ACCEPTED AND PERSISTED TO MEMORY")
        print("=" * 75)
        print(f"Video Status:          APPROVED")
        print(f"Knowledge Candidate:   {learned.get('id')} ({learned.get('status', '').upper()})")
        print(f"Updated Confidence:    {learned.get('confidence', 0.0):.2f}")
        print(f"Sample Size:           {learned.get('sample_size', 0)}")
        print("=" * 75 + "\n")

    else:
        print(f"\n>> Human Editor REJECTED video [{video_id}].")
        print(f"Feedback: '{feedback}'")

        plan = FeedbackInterpreter.interpret_user_feedback(feedback)
        print(f"Structured Interpretation:")
        print(f"  Issue:      {plan.issue_type}")
        print(f"  Adjustment: scale={plan.scale_adjustment}, duration_ms={plan.duration_ms_adjustment}")
        print(f"  Confidence: {plan.confidence}")

        repo.log_audit(
            audit_id=f"audit_human_rej_{uuid.uuid4().hex[:8]}",
            action="HUMAN_REJECT",
            target=video_id,
            detail=f"Rejected with feedback: '{feedback}'. Interpretation: {plan.to_parameters_dict()}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Human Review Console")
    parser.add_argument("--decision", choices=["A", "R"], default="A", help="Approve (A) or Reject (R)")
    parser.add_argument("--feedback", type=str, default="Framing and punch-in look clean, approved for publication.", help="User feedback note")
    args = parser.parse_args()

    run_human_review(decision=args.decision, feedback=args.feedback)
