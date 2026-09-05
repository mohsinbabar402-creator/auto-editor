from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from db.repository import DatabaseRepository
from workers.models import ProductionJob, JobStatus
from workers.base import WorkerPool
from campaigns.manager import CampaignManager
from review.models import StructuredReview, ReviewVerdict
from review.reviewer import BaseVideoReviewer, GeminiBrowserReviewer, MockVideoReviewer
from qc.video_check import verify_rendered_video, QCValidationError
from analysis.feedback_interpreter import FeedbackInterpreter, StructuredCorrectionPlan
from learning.knowledge_engine import KnowledgeEngine
from config.settings import QUALITY_GATE_SCORE, MAX_AUTO_ITERATIONS

logger = logging.getLogger("whop_editor.production_engine")


@dataclass
class ProductionEngineResult:
    success: bool
    campaign_id: str
    job_id: str
    final_output_path: Optional[str] = None
    final_verdict: str = "PENDING"
    review_attempts: int = 0
    latest_review: Optional[StructuredReview] = None
    qc_passed: bool = False
    needs_human_review: bool = False
    error_message: Optional[str] = None
    best_version: Optional[str] = None
    best_score: float = 0.0
    iterations_run: int = 0
    regressions_count: int = 0
    corrections_count: int = 0


class ProductionEngine:
    """
    Whop Short-Form Autonomous Production Engine:
    Coordinates Campaign -> Worker Execution -> Gemini Video Review -> Correction Loop -> Final QC -> PostgreSQL Persistence.
    Enforces centralized quality gate, regression protection, best version selection, and emergency limits.
    """

    def __init__(
        self,
        campaign_manager: CampaignManager,
        reviewer: Optional[BaseVideoReviewer] = None,
        quality_gate_score: float = QUALITY_GATE_SCORE,
        max_auto_iterations: int = MAX_AUTO_ITERATIONS,
        max_review_retries: Optional[int] = None
    ):
        self.campaign_mgr = campaign_manager
        self.repo = campaign_manager.repo
        self.worker_pool = campaign_manager.worker_pool
        self.reviewer = reviewer or GeminiBrowserReviewer()
        self.quality_gate_score = quality_gate_score
        self.max_auto_iterations = max_review_retries if max_review_retries is not None else max_auto_iterations
        self.knowledge_engine = KnowledgeEngine(self.repo)

    def produce_campaign_video(
        self,
        campaign_id: str,
        source_video_path: str | Path,
        scene_instructions: str,
        output_filename: Optional[str] = None,
        target_word: Optional[str] = None,
        scale: Optional[float] = None,
        duration_ms: Optional[int] = None
    ) -> ProductionEngineResult:
        source_path = Path(source_video_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source video not found: {source_path}")

        campaign = self.campaign_mgr.get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign '{campaign_id}' does not exist.")

        logger.info(f"=== Starting Production for Campaign [{campaign.name}] ({campaign_id}) ===")

        # 1. Retrieve validated parameters from project knowledge if not explicitly specified
        learned_params = self.knowledge_engine.get_validated_parameters(project_id=campaign.project_id)
        current_scale = scale if scale is not None else learned_params.get("scale", 1.18)
        current_duration_ms = duration_ms if duration_ms is not None else learned_params.get("duration_ms", 850)
        current_target_word = target_word or learned_params.get("target_word", "differential")

        job = self.campaign_mgr.create_production_job(
            campaign_id=campaign_id,
            input_video_path=source_path,
            job_type="PRODUCTION_EDIT",
            target_word=current_target_word,
            scale=current_scale,
            duration_ms=current_duration_ms,
            output_filename=output_filename
        )

        engine_result = ProductionEngineResult(
            success=False,
            campaign_id=campaign_id,
            job_id=job.id
        )

        attempt = 0
        current_video_path = None
        current_video_id = None

        best_version_id: Optional[str] = None
        best_score: float = -1.0
        best_video_path: Optional[Path] = None
        best_review: Optional[StructuredReview] = None
        best_params: Dict[str, Any] = {
            "scale": current_scale,
            "duration_ms": current_duration_ms,
            "target_word": current_target_word
        }

        regressions_count = 0
        corrections_count = 0
        ineffective_strategies: set = set()
        last_strategy_param: Optional[str] = None

        while attempt < self.max_auto_iterations:
            attempt += 1
            engine_result.review_attempts = attempt
            engine_result.iterations_run = attempt
            logger.info(f"--- Quality Loop Cycle (Attempt {attempt}/{self.max_auto_iterations}) ---")

            # Execute render via Worker Pool
            executed_job = self.campaign_mgr.execute_job(job.id)
            if executed_job.status != JobStatus.COMPLETED:
                engine_result.error_message = f"Worker failed job: {executed_job.error_message}"
                engine_result.final_verdict = "WORKER_FAILED"
                return engine_result

            current_video_path = Path(executed_job.output_data["output_path"])
            current_video_id = executed_job.output_data.get("video_id")

            # Quality Control Check on the newly rendered MP4
            try:
                qc_rep = verify_rendered_video(current_video_path)
                engine_result.qc_passed = qc_rep.passed
                if not qc_rep.passed:
                    raise QCValidationError(f"QC check failed: {qc_rep.errors}")
            except QCValidationError as e:
                logger.error(f"QC validation failed on attempt {attempt}: {e}")
                engine_result.error_message = f"QC check failed: {e}"
                engine_result.final_verdict = "QC_FAILED"
                return engine_result

            # Review via Gemini Browser / Reviewer ON THE ACTUAL RENDERED MP4
            logger.info(f"Submitting rendered video [{current_video_path.name}] to Reviewer...")
            try:
                review = self.reviewer.review_video(
                    video_path=current_video_path,
                    scene_instructions=scene_instructions,
                    campaign_context=f"Campaign: {campaign.name} | Project: {campaign.project_id} (Iteration {attempt})"
                )
            except Exception as e:
                logger.error(f"Reviewer execution failed on attempt {attempt}: {e}")
                self.repo.record_review(
                    review_id=f"rev_err_{uuid.uuid4().hex[:8]}",
                    job_id=job.id,
                    video_id=current_video_id,
                    attempt=attempt,
                    reviewer_type=self.reviewer.__class__.__name__,
                    verdict="ERROR",
                    raw_response=str(e)
                )
                engine_result.error_message = str(e)
                return engine_result

            engine_result.latest_review = review
            engine_result.final_verdict = review.verdict

            # Persist review record in PostgreSQL
            review_id = f"rev_{uuid.uuid4().hex[:8]}"
            self.repo.record_review(
                review_id=review_id,
                job_id=job.id,
                video_id=current_video_id,
                attempt=attempt,
                reviewer_type=self.reviewer.__class__.__name__,
                verdict=review.verdict,
                overall_score=review.overall_score,
                scores={
                    "scene_accuracy": review.scene_accuracy or 0.0,
                    "instruction_accuracy": review.instruction_accuracy or 0.0,
                    "character_accuracy": review.character_accuracy or 0.0,
                    "timing_score": review.timing_score or 0.0,
                    "visual_quality": review.visual_quality or 0.0,
                    "iteration": attempt,
                    "version": f"V{attempt}",
                    "previous_best_score": best_score if best_score >= 0 else None
                },
                problems=[p.model_dump() if hasattr(p, "model_dump") else p for p in review.problems],
                corrections=review.corrections
            )

            # Compare new version with best version (Regression Protection)
            if review.overall_score > best_score:
                best_score = review.overall_score
                best_version_id = f"V{attempt}"
                best_video_path = current_video_path
                best_review = review
                best_params = {
                    "scale": current_scale,
                    "duration_ms": current_duration_ms,
                    "target_word": current_target_word
                }
                logger.info(f">> New BEST VERSION achieved: {best_version_id} (Score: {best_score:.1f}/10)")
                self.repo.log_audit(
                    audit_id=f"audit_best_{uuid.uuid4().hex[:8]}",
                    action="BEST_VERSION_UPDATED",
                    target=job.id,
                    detail=f"Attempt {attempt} reached new best score: {best_score:.1f}/10"
                )
            elif review.overall_score < best_score:
                regressions_count += 1
                logger.warning(
                    f">> REGRESSION DETECTED on Attempt {attempt} (Score {review.overall_score:.1f} < Best {best_score:.1f}). "
                    f"Preserving BEST VERSION {best_version_id}."
                )
                self.repo.log_audit(
                    audit_id=f"audit_reg_{uuid.uuid4().hex[:8]}",
                    action="REGRESSION_DETECTED",
                    target=job.id,
                    detail=f"Attempt {attempt} score {review.overall_score:.1f} < Best {best_score:.1f}. Preserving {best_version_id}."
                )
                if last_strategy_param:
                    ineffective_strategies.add(last_strategy_param)
                    logger.info(f"Strategy '{last_strategy_param}' marked ineffective due to regression.")
            else:
                # Deterministic tie-breaking: preserve earliest best unless no best exists yet
                if best_version_id is None:
                    best_score = review.overall_score
                    best_version_id = f"V{attempt}"
                    best_video_path = current_video_path
                    best_review = review
                    best_params = {
                        "scale": current_scale,
                        "duration_ms": current_duration_ms,
                        "target_word": current_target_word
                    }

            engine_result.best_version = best_version_id
            engine_result.best_score = best_score
            engine_result.final_output_path = str(best_video_path)
            engine_result.regressions_count = regressions_count
            engine_result.corrections_count = corrections_count

            # Quality Gate Evaluation
            if best_score >= self.quality_gate_score:
                logger.info(
                    f"=== Quality Gate REACHED on Attempt {attempt}! "
                    f"Score: {best_score:.1f}/{self.quality_gate_score:.1f} ==="
                )
                engine_result.success = True
                engine_result.final_verdict = "PASS"
                engine_result.needs_human_review = True  # Human review required after gate reached
                engine_result.latest_review = best_review

                if current_video_id:
                    self.repo.update_video_status(current_video_id, "approved")
                self.repo.update_job(job.id, status=JobStatus.COMPLETED)

                self.knowledge_engine.record_edit_outcome(
                    project_id=campaign.project_id,
                    video_id=current_video_id,
                    event_type="PUNCH_IN_EDIT",
                    action_type="PUNCH_IN_PARAMS",
                    parameters={
                        "scale": round(best_params["scale"], 3),
                        "duration_ms": best_params["duration_ms"],
                        "target_word": best_params["target_word"]
                    },
                    approved=True,
                    score=best_score,
                    outcome_note=f"Approved on attempt {attempt} reaching quality gate with score {best_score}"
                )
                return engine_result

            # Check Emergency Iteration Ceiling
            if attempt >= self.max_auto_iterations:
                logger.warning(
                    f"Emergency iteration limit ({self.max_auto_iterations}) reached while score ({best_score:.1f}) "
                    f"< Quality Gate ({self.quality_gate_score:.1f}). Halting cycles."
                )
                engine_result.success = False
                engine_result.needs_human_review = True
                engine_result.final_verdict = ReviewVerdict.NEEDS_HUMAN_REVIEW.value
                engine_result.error_message = (
                    f"QUALITY_GATE_NOT_REACHED: Reached max iterations ({self.max_auto_iterations}) with best score {best_score:.1f}/10."
                )
                self.repo.update_job(job.id, status=JobStatus.FAILED, error_message=engine_result.error_message)
                return engine_result

            # Record iteration rejection in knowledge engine as negative evidence
            self.knowledge_engine.record_edit_outcome(
                project_id=campaign.project_id,
                video_id=current_video_id,
                event_type="PUNCH_IN_EDIT",
                action_type="PUNCH_IN_PARAMS",
                parameters={
                    "scale": round(current_scale, 3),
                    "duration_ms": current_duration_ms,
                    "target_word": current_target_word
                },
                approved=False,
                score=review.overall_score or 4.0,
                outcome_note=f"Below quality gate ({review.overall_score:.1f}/{self.quality_gate_score:.1f}) on attempt {attempt}"
            )

            # Generate Targeted Correction from Gemini problems
            logger.info("Interpreting critique into structured correction plan...")
            base_scale = best_params.get("scale", current_scale)
            base_duration = best_params.get("duration_ms", current_duration_ms)

            correction_plan = FeedbackInterpreter.interpret_gemini_review(
                corrections=review.corrections,
                problems=review.problems,
                current_scale=base_scale,
                current_duration_ms=base_duration,
                ineffective_strategies=list(ineffective_strategies)
            )

            # Check if all automated corrections are exhausted
            if correction_plan.confidence == 0.0 or (
                correction_plan.scale_adjustment is None and
                correction_plan.duration_ms_adjustment is None and
                correction_plan.safe_margin_y is None
            ):
                logger.warning("No safe automated correction alternative remains. Flagging for human review.")
                engine_result.success = False
                engine_result.needs_human_review = True
                engine_result.final_verdict = ReviewVerdict.NEEDS_HUMAN_REVIEW.value
                engine_result.error_message = "SAFE_CORRECTIONS_EXHAUSTED: No safe automated correction strategy remaining."
                self.repo.update_job(job.id, status=JobStatus.FAILED, error_message=engine_result.error_message)
                return engine_result

            corrections_count += 1
            if correction_plan.scale_adjustment is not None:
                current_scale = correction_plan.scale_adjustment
                last_strategy_param = "scale"
            if correction_plan.duration_ms_adjustment is not None:
                current_duration_ms = correction_plan.duration_ms_adjustment
                last_strategy_param = "duration_ms"

            logger.info(
                f"Generated correction #{corrections_count}: issue={correction_plan.issue_type}, "
                f"new_scale={current_scale:.2f}, new_duration={current_duration_ms}ms"
            )
            self.repo.log_audit(
                audit_id=f"audit_corr_{uuid.uuid4().hex[:8]}",
                action="CORRECTION_PLAN_GENERATED",
                target=job.id,
                detail=f"Issue={correction_plan.issue_type} | Scale={current_scale:.2f} | Dur={current_duration_ms}ms"
            )

            # Update job input data with corrections for regeneration
            job.input_data["scale"] = current_scale
            job.input_data["duration_ms"] = current_duration_ms
            job.retry_count = attempt
            job.status = JobStatus.PENDING
            self.repo.update_job(
                job_id=job.id,
                status=JobStatus.PENDING,
                input_data=job.input_data,
                retry_count=attempt
            )

        return engine_result
