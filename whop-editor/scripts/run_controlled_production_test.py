import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Windows UTF-8 console output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add whop-editor to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from db.repository import DatabaseRepository
from db.connection import transaction_scope
from ingest.video import inspect_video_media, register_input_video
from analysis.whisper import transcribe_video_words
from analysis.transcript import NormalizedTranscript
from ai.editor import AIEditor
from validation.edit_schema import validate_edit_proposal
from editing.punch_in import render_punch_in
from qc.video_check import verify_rendered_video, QCValidationError
from review.reviewer import GeminiBrowserReviewer
from review.models import ReviewVerdict, StructuredReview
from analysis.feedback_interpreter import FeedbackInterpreter
from learning.knowledge_engine import KnowledgeEngine, KnowledgeStatus
from workers.resource_governor import get_resource_governor
from workers.worker_registry import WorkerRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("controlled_test")

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
WHOP_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def find_candidate_videos() -> List[Tuple[Path, Dict[str, Any], float]]:
    """
    Searches workspace media directories for video files (.mp4, .mov, .mkv, .webm, .avi).
    Inspects media properties and computes a suitability score.
    Returns sorted list: (path, media_info, suitability_score).
    """
    search_dirs = [
        WHOP_DATA_DIR / "input",
        PROJECT_DIR / "data",
        PROJECT_DIR,
    ]
    valid_exts = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
    candidates = []

    seen = set()
    for s_dir in search_dirs:
        if not s_dir.exists():
            continue
        for root, dirs, files in os.walk(s_dir):
            if any(skip in root.lower() for skip in ["browser", "node_modules", ".git", "pgsql", "tools", ".venv"]):
                continue
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in valid_exts:
                    f_path = (Path(root) / f).resolve()
                    if f_path in seen:
                        continue
                    seen.add(f_path)

                    if "data\\output" in str(f_path).lower() or "data/output" in str(f_path).lower():
                        continue

                    try:
                        info = inspect_video_media(f_path)
                        score = 0.0
                        if info.get("has_audio"):
                            score += 50.0
                        dur = info.get("duration", 0.0)
                        if 5.0 <= dur <= 30.0:
                            score += 40.0
                        elif 30.0 < dur <= 60.0:
                            score += 20.0

                        w = info.get("width", 0)
                        h = info.get("height", 0)
                        if h > w:
                            score += 30.0
                        if w >= 720 or h >= 720:
                            score += 20.0

                        candidates.append((f_path, info, score))
                    except Exception as e:
                        logger.warning(f"Could not inspect {f_path.name}: {e}")

    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates


def run_controlled_production_test(campaign_id: Optional[str] = None, output_filename: Optional[str] = None):
    target_campaign_id = campaign_id or (sys.argv[1] if len(sys.argv) > 1 else "camp_whop_shortform_01")
    target_output_name = output_filename or (sys.argv[2] if len(sys.argv) > 2 else "controlled_test_short.mp4")

    print("=" * 80)
    print("       AUTONOMOUS CONTENT ENGINE — CONTROLLED PRODUCTION TEST")
    print("=" * 80)
    print(f"Target Campaign: {target_campaign_id}")
    print("Objective: Full-loop execution from raw media to finished video using existing architecture.")
    print("Pipeline: Discovery -> Inspection -> Whisper -> Edit Plan -> Validation -> Render -> QC -> Gemini QA -> PostgreSQL\n")

    repo = DatabaseRepository()
    knowledge_engine = KnowledgeEngine(repo)
    governor = get_resource_governor()

    # Ensure Project and Campaign exist in PostgreSQL
    if not repo.get_project("proj_whop_shortform"):
        repo.create_project(
            project_id="proj_whop_shortform",
            name="Whop Short-Form Creator Education",
            niche_description="Educational video shorts for creator communities and SaaS founders."
        )
    camp_rec = repo.get_campaign(target_campaign_id)
    if not camp_rec:
        camp_rec = repo.create_campaign(
            campaign_id=target_campaign_id,
            project_id="proj_whop_shortform",
            name=f"Whop Production Campaign ({target_campaign_id})",
            status="active"
        )
    campaign_name = camp_rec.get("name", target_campaign_id)

    # Synchronize worker registry into PostgreSQL
    worker_reg = WorkerRegistry(repo=repo)
    worker_reg.sync_all_workers_to_db()
    assigned_worker_id = "worker_w2"
    assigned_profile_id = "flow_profile_2"

    # Hardware Governor Check
    telemetry = governor.get_telemetry()
    print(f">> Host Hardware Check: RAM {telemetry.ram_load_percent:.1f}% load ({telemetry.avail_ram_mb:.0f} MB avail) | Disk: {telemetry.disk_free_gb:.2f} GB free")
    can_run, gov_reason = governor.can_dispatch("REVIEW")
    if not can_run:
        print(f"CRITICAL: Resource Governor blocked execution: {gov_reason}")
        return

    # =========================================================================
    # STEP 1: AUTOMATIC MEDIA DISCOVERY & SELECTION
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 1: AUTOMATIC CANDIDATE DISCOVERY & SELECTION")
    print("-" * 80)

    candidates = find_candidate_videos()
    if not candidates:
        print("ERROR: No suitable input video files found in workspace media directories.")
        return

    print(f"Found {len(candidates)} candidate video(s):")
    for idx, (c_path, c_info, c_score) in enumerate(candidates[:10], start=1):
        print(f"  [{idx}] {c_path.name:<35} | {c_info.get('duration', 0.0):.1f}s | {c_info.get('width', 0)}x{c_info.get('height', 0)} | Audio: {c_info.get('has_audio')} | Suitability Score: {c_score:.0f}")

    selected_source, source_info, _ = candidates[0]
    print(f"\n>> Selected Best Candidate: {selected_source.name}")
    print(f"   Path: {selected_source}")

    # =========================================================================
    # STEP 2: SOURCE INSPECTION & WHISPER TRANSCRIPTION
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 2: SOURCE INSPECTION & WHISPER TRANSCRIPTION")
    print("-" * 80)

    print(f"Source Parameters:")
    print(f"  - Duration:   {source_info['duration']:.2f}s")
    print(f"  - Resolution: {source_info['width']}x{source_info['height']}")
    print(f"  - FPS:        {source_info['fps']:.2f}")
    print(f"  - Audio:      {'Present' if source_info['has_audio'] else 'None'}")
    print(f"  - File Size:  {source_info['file_size'] / (1024*1024):.2f} MB")

    # Ingest into PostgreSQL
    video_id = f"vid_{uuid.uuid4().hex[:10]}"
    repo.register_video(video_id=video_id, project_id="proj_whop_shortform", file_path=str(selected_source))
    print(f"Registered source video in PostgreSQL: {video_id}")
    repo.log_audit(
        audit_id=f"audit_vid_{uuid.uuid4().hex[:8]}",
        action="REGISTER_VIDEO",
        target=video_id,
        detail=f"Registered source video {selected_source.name} under proj_whop_shortform"
    )

    print("Running Whisper Speech Analysis...")
    with governor.managed_execution("whisper"):
        transcript_data = transcribe_video_words(
            video_path=selected_source,
            video_id=video_id
        )

    transcript = NormalizedTranscript(
        raw_words=transcript_data.get("words", []),
        full_text=transcript_data.get("text", "")
    )
    print(f">> Whisper Analysis Complete: {len(transcript.words)} spoken words detected.")
    repo.log_audit(
        audit_id=f"audit_whisp_{uuid.uuid4().hex[:8]}",
        action="ANALYZE_TRANSCRIPT",
        target=video_id,
        detail=f"Whisper speech analysis complete: {len(transcript.words)} spoken words detected"
    )
    sample_text = " ".join([w.word for w in transcript.words[:15]])
    print(f"   Opening excerpt: \"{sample_text}...\"")

    # =========================================================================
    # STEP 3: GENERATE ONE STRUCTURED EDIT PLAN
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 3: GENERATE ONE STRUCTURED EDIT PLAN")
    print("-" * 80)

    # Fetch validated canonical knowledge from PostgreSQL
    validated_params = knowledge_engine.get_validated_parameters(project_id="proj_whop_shortform")
    target_word = validated_params.get("target_word", "differential")
    scale = validated_params.get("scale", 1.20)
    duration_ms = validated_params.get("duration_ms", 1100)

    print(f"Inherited Knowledge from PostgreSQL: scale={scale:.2f}x, duration={duration_ms}ms, target_word='{target_word}'")

    # Find target word index in transcript
    word_index = None
    for idx, w in enumerate(transcript.words):
        if target_word.lower() in w.word.lower():
            word_index = idx
            break

    if word_index is None:
        ai_editor = AIEditor()
        prop_dict = ai_editor.propose_punch_in(transcript=transcript)
        word_index = prop_dict.get("word_index", 0)
        target_word = transcript.words[word_index].word
        print(f"Target word '{target_word}' selected via AI Editor heuristic at index {word_index}.")

    target_token = transcript.get_word(word_index)
    start_sec, end_sec = transcript.resolve_effect_window(
        word_index=word_index,
        duration_ms=duration_ms,
        video_duration=source_info['duration']
    )

    print(f"AI Edit Plan Generated:")
    print(f"  - Target Word:   '{target_word}' (index: {word_index}, time: {target_token.start:.2f}s -> {target_token.end:.2f}s)")
    print(f"  - Effect Window: {start_sec:.2f}s -> {end_sec:.2f}s ({duration_ms}ms)")
    print(f"  - Scale:         {scale:.2f}x zoom")
    repo.log_audit(
        audit_id=f"audit_plan_{uuid.uuid4().hex[:8]}",
        action="GENERATE_EDIT_PLAN",
        target=video_id,
        detail=f"Target word '{target_word}' at index {word_index} | Scale={scale:.2f}x | Duration={duration_ms}ms"
    )

    # =========================================================================
    # STEP 4: STRICT EDIT PLAN VALIDATION
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 4: STRICT EDIT PLAN VALIDATION")
    print("-" * 80)

    proposal_payload = {
        "word_index": word_index,
        "scale": scale,
        "duration_ms": duration_ms
    }
    validated_proposal = validate_edit_proposal(proposal_payload, len(transcript.words))
    print(f">> Edit Plan Validation: PASSED (Schema, bounds, and word index {validated_proposal.word_index} verified)")
    repo.log_audit(
        audit_id=f"audit_val_{uuid.uuid4().hex[:8]}",
        action="VALIDATE_EDIT_PLAN",
        target=video_id,
        detail="Edit proposal validated: schema, bounds, and token index verified"
    )

    # =========================================================================
    # STEP 5: RENDER ONE REAL VIDEO WITH FFMPEG (VERSION 1)
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 5: RENDER ONE REAL VIDEO WITH FFMPEG (VERSION 1)")
    print("-" * 80)

    output_dir = WHOP_DATA_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    v1_output_path = output_dir / "version_1.mp4"

    if v1_output_path.exists():
        try:
            v1_output_path.unlink()
        except Exception:
            pass

    print(f"Rendering effect to: {v1_output_path.name}...")
    t_render_start = time.time()
    with governor.managed_execution("render"):
        render_punch_in(
            input_path=selected_source,
            start_time=start_sec,
            end_time=end_sec,
            scale=scale,
            output_path=v1_output_path
        )
    render_elapsed = time.time() - t_render_start
    print(f">> Render Completed in {render_elapsed:.2f}s | Output Size: {v1_output_path.stat().st_size / (1024*1024):.2f} MB")
    repo.log_audit(
        audit_id=f"audit_rnd1_{uuid.uuid4().hex[:8]}",
        action="RENDER_VERSION",
        target="version_1.mp4",
        detail=f"Render completed in {render_elapsed:.2f}s ({v1_output_path.stat().st_size} bytes)"
    )

    # =========================================================================
    # STEP 6: DETERMINISTIC QUALITY CONTROL (QC)
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 6: DETERMINISTIC QUALITY CONTROL (QC)")
    print("-" * 80)

    qc_report = verify_rendered_video(v1_output_path)
    print(f"QC Integrity Verification (Version 1):")
    print(f"  - Output Exists:   {Path(qc_report.output_path).exists()}")
    print(f"  - Duration:        {qc_report.output_duration:.2f}s")
    print(f"  - Resolution:      {qc_report.width}x{qc_report.height}")
    print(f"  - Audio Stream:    {'Present' if qc_report.has_audio else 'Missing'}")
    print(f"  - Overall Verdict: {'PASS' if qc_report.passed else 'FAIL'}")

    if not qc_report.passed:
        print(f"ERROR: Deterministic QC failed: {qc_report.errors}")
        return

    repo.log_audit(
        audit_id=f"audit_qc1_{uuid.uuid4().hex[:8]}",
        action="QC_VERIFY",
        target="version_1.mp4",
        detail=f"QC passed: duration={qc_report.output_duration:.2f}s, res={qc_report.width}x{qc_report.height}, audio={qc_report.has_audio}"
    )

    # =========================================================================
    # STEP 7: INDEPENDENT GEMINI REVIEW (VERSION 1)
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 7: INDEPENDENT GEMINI QA REVIEW (VERSION 1)")
    print("-" * 80)
    print("Submitting the ACTUAL rendered MP4 video (Version 1) to Gemini QA Reviewer...")

    reviewer = GeminiBrowserReviewer(
        profile_id=assigned_profile_id,
        headless=False,
        timeout_ms=60000,
        db_repo=repo
    )

    scene_instructions = (
        "Whop Creator Talking-Head Short:\n"
        "- Speaker: Justin Banusing discussing high-ticket gaming leagues.\n"
        "- Vertical 9:16 portrait framing.\n"
        f"- Punch-in emphasis applied on keyword '{target_word}'.\n"
        "- Natural pacing, zero black bars, clear audio."
    )

    review_attempt = 1
    with governor.managed_execution("browser"):
        review = reviewer.review_video(
            video_path=v1_output_path,
            scene_instructions=scene_instructions,
            campaign_context=f"Campaign: {campaign_name} | Whop Creator Short (Iteration 1)"
        )

    print(f"\n>> Gemini Review Result (Iteration {review_attempt}):")
    print(f"   Verdict:       {review.verdict}")
    print(f"   Overall Score: {review.overall_score:.1f}/10")
    print(f"   Problems:      {len(review.problems)}")
    for p in review.problems:
        p_dict = p.model_dump() if hasattr(p, "model_dump") else p
        print(f"     * [{p_dict.get('type', 'general').upper()}]: {p_dict.get('description', '')}")
    if review.corrections:
        print(f"   Corrections:   {review.corrections}")

    # Record job in PostgreSQL
    job_id = f"job_ctrl_{uuid.uuid4().hex[:8]}"
    repo.create_job(
        job_id=job_id,
        campaign_id=target_campaign_id,
        job_type="controlled_production_test",
        input_data={
            "video_id": video_id,
            "source": selected_source.name,
            "target_word": target_word,
            "scale": scale,
            "duration_ms": duration_ms,
            "assigned_worker_id": assigned_worker_id,
            "profile_id": assigned_profile_id,
            "transcript_word_count": len(transcript.words)
        },
        status="running"
    )
    repo.update_job(job_id=job_id, status="running", assigned_worker_id=assigned_worker_id)
    repo.log_audit(
        audit_id=f"audit_job_{uuid.uuid4().hex[:8]}",
        action="CREATE_JOB",
        target=job_id,
        detail=f"Created production job under {target_campaign_id} on worker {assigned_worker_id}"
    )

    # Record review in PostgreSQL
    repo.record_review(
        review_id=f"rev_test_{uuid.uuid4().hex[:8]}",
        job_id=job_id,
        video_id=video_id,
        attempt=review_attempt,
        reviewer_type="GeminiBrowserReviewer",
        verdict=review.verdict,
        overall_score=review.overall_score,
        scores={
            "scene_accuracy": review.scene_accuracy or 0.0,
            "instruction_accuracy": review.instruction_accuracy or 0.0,
            "character_accuracy": review.character_accuracy or 0.0,
            "timing_score": review.timing_score or 0.0,
            "visual_quality": review.visual_quality or 0.0,
            "worker_id": assigned_worker_id,
            "profile_id": assigned_profile_id
        },
        problems=[p.model_dump() if hasattr(p, "model_dump") else p for p in review.problems],
        corrections=review.corrections
    )
    repo.log_audit(
        audit_id=f"audit_rev1_{uuid.uuid4().hex[:8]}",
        action="GEMINI_REVIEW",
        target=job_id,
        detail=f"Iteration 1 review: score={review.overall_score:.1f}/10, verdict={review.verdict}"
    )

    # Track full versions history for PostgreSQL recovery
    versions_history = [{
        "version": 1,
        "path": str(v1_output_path),
        "scale": scale,
        "duration_ms": duration_ms,
        "window": [start_sec, end_sec],
        "qc_passed": qc_report.passed,
        "gemini_verdict": review.verdict,
        "gemini_score": review.overall_score,
        "problems": [p.model_dump() if hasattr(p, "model_dump") else p for p in review.problems],
        "corrections": review.corrections,
        "worker_id": assigned_worker_id,
        "profile_id": assigned_profile_id
    }]

    # =========================================================================
    # STEP 8: AUTOMATED QUALITY LOOP (QUALITY GATE & REGRESSION PROTECTION)
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 8: AUTOMATED QUALITY LOOP")
    print("-" * 80)

    quality_gate_score = settings.QUALITY_GATE_SCORE
    max_auto_iterations = settings.MAX_AUTO_ITERATIONS

    best_version = 1
    best_score = review.overall_score
    best_path = v1_output_path
    best_params = {
        "scale": scale,
        "duration_ms": duration_ms,
        "y_offset": 0.0,
        "target_word": target_word
    }
    best_review = review

    current_scale = scale
    current_duration_ms = duration_ms
    current_y_offset = 0.0
    current_review = review
    iteration = 1
    corrections_count = 0
    regressions_count = 0
    gemini_reviews_count = 1
    ineffective_strategies = set()
    trajectory = [(1, review.overall_score, review.verdict)]
    final_state = "NEEDS_HUMAN_REVIEW"

    seen_param_signatures = {(round(scale, 2), duration_ms, 0.0)}

    while True:
        # Check Quality Gate
        if best_score >= quality_gate_score:
            print(f"\n>> Quality Gate REACHED! Score: {best_score:.1f}/{quality_gate_score:.1f}. Halting automatic cycles.")
            final_state = "QUALITY GATE REACHED"
            break

        # Check Emergency Limit
        if iteration >= max_auto_iterations:
            print(f"\n>> Emergency iteration limit ({max_auto_iterations}) reached while score ({best_score:.1f}) < Quality Gate ({quality_gate_score:.1f}).")
            print(">> QUALITY_GATE_NOT_REACHED. Halting cycles for safety.")
            final_state = "NEEDS_HUMAN_REVIEW"
            break

        # Check if safe automated corrections are already exhausted
        if "scale" in ineffective_strategies and "duration_ms" in ineffective_strategies and "y_offset" in ineffective_strategies:
            print("\n>> All primary automated correction strategies have been tried and failed. Halting cycles.")
            repo.log_audit(
                audit_id=f"audit_halt_{uuid.uuid4().hex[:8]}",
                action="SAFE_HALT_REACHED",
                target=job_id,
                detail="All primary automated correction strategies have been tried and failed. Halting cycles."
            )
            final_state = "NEEDS_HUMAN_REVIEW"
            break

        print(f"\nCurrent best score ({best_score:.1f}/10) < Quality Gate ({quality_gate_score:.1f}/10). Generating targeted correction...")

        # Generate targeted correction plan from Gemini critique
        correction_plan = FeedbackInterpreter.interpret_gemini_review(
            corrections=current_review.corrections,
            problems=current_review.problems,
            current_scale=best_params["scale"],
            current_duration_ms=best_params["duration_ms"],
            current_y_offset=best_params.get("y_offset", 0.0),
            ineffective_strategies=list(ineffective_strategies)
        )

        # Check if safe automated corrections are exhausted
        if correction_plan.confidence == 0.0 or (
            correction_plan.scale_adjustment is None and
            correction_plan.duration_ms_adjustment is None and
            correction_plan.y_offset_adjustment is None and
            correction_plan.safe_margin_y is None
        ):
            print("\n>> All safe automated correction alternatives exhausted. Halting cycles.")
            repo.log_audit(
                audit_id=f"audit_halt_{uuid.uuid4().hex[:8]}",
                action="SAFE_HALT_REACHED",
                target=job_id,
                detail="All safe automated correction alternatives exhausted. Halting cycles."
            )
            final_state = "NEEDS_HUMAN_REVIEW"
            break

        corrections_count += 1
        last_strategy = None
        if correction_plan.scale_adjustment is not None:
            current_scale = correction_plan.scale_adjustment
            last_strategy = "scale"
        if correction_plan.duration_ms_adjustment is not None:
            current_duration_ms = correction_plan.duration_ms_adjustment
            last_strategy = "duration_ms"
        if correction_plan.y_offset_adjustment is not None:
            current_y_offset = correction_plan.y_offset_adjustment
            last_strategy = "y_offset"

        # Check if proposed parameter signature was already tried
        param_sig = (round(current_scale, 2), current_duration_ms, round(current_y_offset, 2))
        if param_sig in seen_param_signatures:
            print(f"\n>> Parameter set scale={param_sig[0]:.2f}x, duration={param_sig[1]}ms, y_offset={param_sig[2]}px already evaluated. Safe alternatives exhausted.")
            repo.log_audit(
                audit_id=f"audit_halt_{uuid.uuid4().hex[:8]}",
                action="SAFE_HALT_REACHED",
                target=job_id,
                detail=f"Parameter set scale={param_sig[0]:.2f}x, duration={param_sig[1]}ms, y_offset={param_sig[2]}px already evaluated. Halting cycles."
            )
            final_state = "NEEDS_HUMAN_REVIEW"
            break
        seen_param_signatures.add(param_sig)

        iteration += 1
        print(f"\n--- Starting Iteration {iteration} ---")
        print(f"Targeted Correction #{corrections_count}: issue={correction_plan.issue_type}, scale={current_scale:.2f}x, duration={current_duration_ms}ms, y_offset={current_y_offset:.1f}px")
        repo.log_audit(
            audit_id=f"audit_corr_{uuid.uuid4().hex[:8]}",
            action="CORRECTION_PLAN_GENERATED",
            target=job_id,
            detail=f"Targeted Correction #{corrections_count}: issue={correction_plan.issue_type}, scale={current_scale:.2f}x, duration={current_duration_ms}ms, y_offset={current_y_offset:.1f}px"
        )

        # Resolve effect window for new version
        new_start, new_end = transcript.resolve_effect_window(
            word_index=word_index,
            duration_ms=current_duration_ms,
            video_duration=source_info['duration']
        )

        iter_output_path = output_dir / f"version_{iteration}.mp4"
        if iter_output_path.exists():
            try:
                iter_output_path.unlink()
            except Exception:
                pass

        print(f"Rendering Version {iteration}...")
        with governor.managed_execution("render"):
            render_punch_in(
                input_path=selected_source,
                start_time=new_start,
                end_time=new_end,
                scale=current_scale,
                output_path=iter_output_path,
                y_offset=current_y_offset
            )

        # QC Verification on Version {iteration}
        qc_iter = verify_rendered_video(iter_output_path)
        print(f"QC Version {iteration}: {'PASS' if qc_iter.passed else 'FAIL'}")
        if not qc_iter.passed:
            print(f"ERROR: QC failed on Version {iteration}: {qc_iter.errors}")
            break

        repo.log_audit(
            audit_id=f"audit_qc_{uuid.uuid4().hex[:8]}",
            action="QC_VERIFY",
            target=f"version_{iteration}.mp4",
            detail=f"QC Version {iteration} passed"
        )

        # Independent Gemini QA Review on ACTUAL newly rendered MP4
        print(f"Submitting ACTUAL rendered MP4 (Version {iteration}) to Gemini QA...")
        with governor.managed_execution("browser"):
            current_review = reviewer.review_video(
                video_path=iter_output_path,
                scene_instructions=scene_instructions,
                campaign_context=f"Campaign: {campaign_name} | Whop Creator Short (Iteration {iteration})"
            )
        gemini_reviews_count += 1

        print(f">> Gemini Review Result (Iteration {iteration}): Verdict={current_review.verdict} (Score: {current_review.overall_score:.1f}/10)")
        trajectory.append((iteration, current_review.overall_score, current_review.verdict))

        # Record review in PostgreSQL
        repo.record_review(
            review_id=f"rev_test_{uuid.uuid4().hex[:8]}",
            job_id=job_id,
            video_id=video_id,
            attempt=iteration,
            reviewer_type="GeminiBrowserReviewer",
            verdict=current_review.verdict,
            overall_score=current_review.overall_score,
            scores={
                "scene_accuracy": current_review.scene_accuracy or 0.0,
                "instruction_accuracy": current_review.instruction_accuracy or 0.0,
                "character_accuracy": current_review.character_accuracy or 0.0,
                "timing_score": current_review.timing_score or 0.0,
                "visual_quality": current_review.visual_quality or 0.0,
                "worker_id": assigned_worker_id,
                "profile_id": assigned_profile_id
            },
            problems=[p.model_dump() if hasattr(p, "model_dump") else p for p in current_review.problems],
            corrections=current_review.corrections
        )
        repo.log_audit(
            audit_id=f"audit_rev_{uuid.uuid4().hex[:8]}",
            action="GEMINI_REVIEW",
            target=job_id,
            detail=f"Iteration {iteration} review: score={current_review.overall_score:.1f}/10, verdict={current_review.verdict}"
        )

        versions_history.append({
            "version": iteration,
            "path": str(iter_output_path),
            "scale": current_scale,
            "duration_ms": current_duration_ms,
            "y_offset": current_y_offset,
            "window": [new_start, new_end],
            "qc_passed": qc_iter.passed,
            "gemini_verdict": current_review.verdict,
            "gemini_score": current_review.overall_score,
            "problems": [p.model_dump() if hasattr(p, "model_dump") else p for p in current_review.problems],
            "corrections": current_review.corrections,
            "worker_id": assigned_worker_id,
            "profile_id": assigned_profile_id
        })

        # Regression Protection & Best Version Tracking
        if current_review.overall_score > best_score:
            print(f">> IMPROVEMENT: Score improved from {best_score:.1f} to {current_review.overall_score:.1f}! Version {iteration} is now BEST_VERSION.")
            best_score = current_review.overall_score
            best_version = iteration
            best_path = iter_output_path
            best_params = {
                "scale": current_scale,
                "duration_ms": current_duration_ms,
                "y_offset": current_y_offset,
                "target_word": target_word
            }
            best_review = current_review
            repo.log_audit(
                audit_id=f"audit_best_{uuid.uuid4().hex[:8]}",
                action="BEST_VERSION_UPDATED",
                target=job_id,
                detail=f"Iteration {iteration} reached score {best_score:.1f}/10. Version {iteration} is now BEST_VERSION."
            )
        else:
            regressions_count += 1
            print(f">> REGRESSION/STAGNATION: Score {current_review.overall_score:.1f} <= best score {best_score:.1f}. Preserving Version {best_version} as BEST_VERSION.")
            repo.log_audit(
                audit_id=f"audit_reg_{uuid.uuid4().hex[:8]}",
                action="REGRESSION_DETECTED",
                target=job_id,
                detail=f"Iteration {iteration} score {current_review.overall_score:.1f} <= {best_score:.1f}. Preserving Version {best_version}."
            )
            if current_scale != best_params["scale"]:
                ineffective_strategies.add("scale")
                print(">> Strategy 'scale' marked ineffective.")
                repo.log_audit(
                    audit_id=f"audit_strat_sc_{uuid.uuid4().hex[:8]}",
                    action="STRATEGY_DIVERTED",
                    target=job_id,
                    detail="Strategy 'scale' marked ineffective."
                )
            if current_duration_ms != best_params["duration_ms"]:
                ineffective_strategies.add("duration_ms")
                print(">> Strategy 'duration_ms' marked ineffective.")
                repo.log_audit(
                    audit_id=f"audit_strat_dur_{uuid.uuid4().hex[:8]}",
                    action="STRATEGY_DIVERTED",
                    target=job_id,
                    detail="Strategy 'duration_ms' marked ineffective."
                )
            if current_y_offset != best_params.get("y_offset", 0.0):
                ineffective_strategies.add("y_offset")
                print(">> Strategy 'y_offset' marked ineffective.")
                repo.log_audit(
                    audit_id=f"audit_strat_y_{uuid.uuid4().hex[:8]}",
                    action="STRATEGY_DIVERTED",
                    target=job_id,
                    detail="Strategy 'y_offset' marked ineffective."
                )

    # =========================================================================
    # STEP 9 & 10: BEST VERSION PRESERVATION & POSTGRESQL RECORD
    # =========================================================================
    print("\n" + "-" * 80)
    print("STEP 9 & 10: BEST VERSION PRESERVATION & POSTGRESQL RECORD")
    print("-" * 80)

    final_output_path = output_dir / target_output_name
    if best_path != final_output_path:
        shutil.copy2(best_path, final_output_path)
    print(f">> Final Output Video preserved from BEST_VERSION (Version {best_version}) at: {final_output_path}")
    repo.log_audit(
        audit_id=f"audit_pres_{uuid.uuid4().hex[:8]}",
        action="BEST_VERSION_PRESERVED",
        target=job_id,
        detail=f"Preserved Version {best_version} to {target_output_name}"
    )

    # Record test outcome in PostgreSQL as OBSERVATION
    obs_id = f"know_obs_{uuid.uuid4().hex[:8]}"
    repo.create_knowledge_candidate(
        knowledge_id=obs_id,
        project_id="proj_whop_shortform",
        event_type="CONTROLLED_TEST",
        action_type="PUNCH_IN_PARAMS",
        parameters_json=json.dumps({
            "scale": round(best_params["scale"], 2),
            "duration_ms": best_params["duration_ms"],
            "y_offset": round(best_params.get("y_offset", 0.0), 2),
            "target_word": best_params["target_word"],
            "best_version": best_version,
            "best_score": best_score,
            "source": selected_source.name
        }),
        confidence=0.40,
        sample_size=1
    )
    repo.record_evidence(
        evidence_id=f"evid_test_{uuid.uuid4().hex[:8]}",
        knowledge_id=obs_id,
        video_id=video_id,
        outcome_note=f"Controlled test mission completed. Best score={best_score:.1f}/10 (v{best_version}), total iterations={iteration}, regressions={regressions_count}",
        metric_value=best_score
    )
    repo.update_job(
        job_id=job_id,
        status="completed" if best_score >= quality_gate_score else "needs_review",
        assigned_worker_id=assigned_worker_id,
        output_data={
            "output_path": str(final_output_path),
            "best_version": best_version,
            "best_score": best_score,
            "final_scale": best_params["scale"],
            "final_duration_ms": best_params["duration_ms"],
            "final_y_offset": best_params.get("y_offset", 0.0),
            "gemini_verdict": best_review.verdict,
            "gemini_score": best_score,
            "iterations": iteration,
            "corrections": corrections_count,
            "regressions": regressions_count,
            "final_state": final_state,
            "versions": versions_history,
            "worker_id": assigned_worker_id,
            "profile_id": assigned_profile_id
        }
    )
    repo.log_audit(
        audit_id=f"audit_fin_{uuid.uuid4().hex[:8]}",
        action="JOB_FLAGGED_REVIEW" if best_score < quality_gate_score else "JOB_COMPLETED",
        target=job_id,
        detail=f"Completed production test. Best score: {best_score:.1f}/10, Final state: {final_state}"
    )
    print(f"Recorded OBSERVATION in PostgreSQL: {obs_id}")
    print(f"Tied Evidence in PostgreSQL linked to Video: {video_id}")

    # =========================================================================
    # STEP 11: FINAL STRUCTURED REPORT
    # =========================================================================
    print("\n" + "=" * 80)
    print("                  CONTROLLED TEST MISSION REPORT")
    print("=" * 80)
    print(f"SOURCE:              {selected_source.name}")
    print(f"OUTPUT:              {final_output_path.name}")
    print(f"DURATION:            {source_info['duration']:.2f}s")
    print(f"EDIT:                Punch-in zoom ({best_params['scale']:.2f}x) on emphasized keyword '{best_params['target_word']}' ({best_params['duration_ms']}ms window)")
    print(f"QUALITY GATE:        {quality_gate_score:.1f}/10")
    print(f"MAX AUTO ITERATIONS: {max_auto_iterations}")
    print(f"TRAJECTORY:")
    for it, sc, vd in trajectory:
        print(f"  Iteration {it} = {sc:.1f}/10 ({vd})")
    print(f"FINAL SCORE:         {best_score:.1f}/10")
    print(f"BEST VERSION:        Version {best_version}")
    print(f"FINAL STATE:         {final_state}")
    print(f"GEMINI REVIEWS:      {gemini_reviews_count}")
    print(f"CORRECTIONS:         {corrections_count}")
    print(f"REGRESSIONS:         {regressions_count}")
    print(f"QC:                  PASS")
    print(f"HUMAN REVIEW:        REQUIRED")
    print(f"EXACT PATH:          {final_output_path.resolve()}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_controlled_production_test()
