from dataclasses import dataclass, asdict
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from db.repository import DatabaseRepository, RepositoryError
from ingest.video import register_input_video, IngestError
from analysis.whisper import transcribe_video_words, WhisperAnalysisError
from analysis.transcript import NormalizedTranscript, TranscriptError
from ai.editor import AIEditor, AIEditorError
from validation.edit_schema import validate_edit_proposal, ProposalValidationError
from editing.punch_in import render_punch_in, PunchInRenderError
from qc.video_check import verify_rendered_video, QCValidationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("whop_editor.pipeline")


class PipelineStageError(Exception):
    """Encapsulates a pipeline failure with stage attribution."""
    def __init__(self, stage: str, message: str, retryable: bool = False):
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.retryable = retryable


@dataclass
class PipelineResult:
    success: bool
    project_id: str
    video_id: str
    input_path: str
    output_path: Optional[str] = None
    selected_word: Optional[str] = None
    selected_word_index: Optional[int] = None
    effect_start_sec: Optional[float] = None
    effect_end_sec: Optional[float] = None
    scale: Optional[float] = None
    knowledge_id: Optional[str] = None
    evidence_id: Optional[str] = None
    stage_failed: Optional[str] = None
    error_message: Optional[str] = None


def run_stage1_pipeline(
    input_video_path: str | Path,
    project_id: str = "proj_whop_shortform",
    repo: Optional[DatabaseRepository] = None,
    ai_editor: Optional[AIEditor] = None,
    output_filename: Optional[str] = None,
    output_dir: Optional[Path] = None,
    target_word: Optional[str] = None,
    scale: Optional[float] = None,
    duration_ms: Optional[int] = None
) -> PipelineResult:

    """
    Executes the complete Stage-1 vertical slice:
    Video -> Whisper -> AI Decision -> Validation -> FFmpeg Render -> QC -> PostgreSQL -> Audit
    """
    in_path = Path(input_video_path).resolve()
    active_repo = repo or DatabaseRepository()
    active_ai = ai_editor or AIEditor()
    v_id = f"vid_{uuid.uuid4().hex[:10]}"

    result = PipelineResult(
        success=False,
        project_id=project_id,
        video_id=v_id,
        input_path=str(in_path)
    )

    # 1. Ensure project exists in repository
    try:
        proj = active_repo.get_project(project_id)
        if not proj:
            # Auto-seed project if missing
            active_repo.create_project(
                project_id=project_id,
                name="Whop Short-Form Creator Education",
                niche_description="Educational video shorts for creator communities and SaaS founders."
            )
            logger.info(f"Initialized default project '{project_id}'")
            proj = active_repo.get_project(project_id)
    except Exception as e:
        result.stage_failed = "DATABASE_PROJECT"
        result.error_message = str(e)
        logger.error(f"Failed project lookup/seed: {e}")
        return result

    # 2. Stage: Ingest & Register Video
    logger.info("=== STAGE 1: Video Ingestion & Registration ===")
    try:
        video_record = register_input_video(
            file_path=in_path,
            project_id=project_id,
            video_id=v_id,
            repo=active_repo
        )
    except IngestError as e:
        result.stage_failed = "INGEST"
        result.error_message = str(e)
        logger.error(f"Ingest failed: {e}")
        return result
    except Exception as e:
        result.stage_failed = "INGEST"
        result.error_message = f"Unexpected ingest error: {e}"
        return result

    # 3. Stage: Whisper Transcription
    logger.info("=== STAGE 2: Speech-to-Text & Word Timestamps ===")
    try:
        transcript_data = transcribe_video_words(
            video_path=in_path,
            video_id=v_id
        )
    except WhisperAnalysisError as e:
        active_repo.update_video_status(v_id, "failed_whisper")
        result.stage_failed = "WHISPER_ANALYSIS"
        result.error_message = str(e)
        logger.error(f"Whisper failed: {e}")
        return result

    # 4. Stage: Transcript Normalization
    logger.info("=== STAGE 3: Transcript Normalization ===")
    try:
        normalized = NormalizedTranscript(
            raw_words=transcript_data.get("words", []),
            full_text=transcript_data.get("text", "")
        )
    except TranscriptError as e:
        active_repo.update_video_status(v_id, "failed_transcript")
        result.stage_failed = "TRANSCRIPT_NORMALIZATION"
        result.error_message = str(e)
        logger.error(f"Transcript normalization failed: {e}")
        return result

    # 5. Stage: AI Edit Proposal
    logger.info("=== STAGE 4: AI Punch-In Proposal ===")
    try:
        raw_proposal = active_ai.propose_punch_in(
            transcript=normalized,
            project_niche=proj.get("niche_description", "") if proj else "",
            target_word=target_word,
            scale=scale,
            duration_ms=duration_ms
        )

    except AIEditorError as e:
        active_repo.update_video_status(v_id, "failed_ai_proposal")
        result.stage_failed = "AI_PROPOSAL"
        result.error_message = str(e)
        logger.error(f"AI proposal failed: {e}")
        return result

    # 6. Stage: Strict Validation
    logger.info("=== STAGE 5: Deterministic Proposal Validation ===")
    try:
        validated_proposal = validate_edit_proposal(
            raw_proposal=raw_proposal,
            transcript_word_count=len(normalized)
        )
    except ProposalValidationError as e:
        active_repo.update_video_status(v_id, "rejected_proposal")
        result.stage_failed = "VALIDATION"
        result.error_message = str(e)
        logger.error(f"Validation rejected proposal: {e}")
        return result

    # 7. Stage: Effect Window Resolution
    selected_token = normalized.get_word(validated_proposal.word_index)
    start_sec, end_sec = normalized.resolve_effect_window(
        word_index=validated_proposal.word_index,
        duration_ms=validated_proposal.duration_ms,
        pre_offset_ms=settings.TIMING_PRE_OFFSET_MS,
        video_duration=video_record["duration"]
    )
    result.selected_word = selected_token.word
    result.selected_word_index = selected_token.index
    result.effect_start_sec = start_sec
    result.effect_end_sec = end_sec
    result.scale = validated_proposal.scale

    logger.info(
        f"Punch-in Target: '{selected_token.word}' (idx={selected_token.index}), "
        f"Window=[{start_sec}s - {end_sec}s], Scale={validated_proposal.scale}x"
    )

    # 8. Stage: FFmpeg Render
    logger.info("=== STAGE 6: Deterministic FFmpeg Render ===")
    target_dir = Path(output_dir).resolve() if output_dir else settings.OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = output_filename or f"{v_id}_punchin.mp4"
    out_path = target_dir / out_name

    try:
        render_punch_in(
            input_path=in_path,
            start_time=start_sec,
            end_time=end_sec,
            scale=validated_proposal.scale,
            output_path=out_path
        )
        result.output_path = str(out_path)
    except PunchInRenderError as e:
        active_repo.update_video_status(v_id, "failed_render")
        result.stage_failed = "FFMPEG_RENDER"
        result.error_message = str(e)
        logger.error(f"FFmpeg render failed: {e}")
        return result

    # 9. Stage: Quality Control Check
    logger.info("=== STAGE 7: Quality Control Verification ===")
    try:
        verify_rendered_video(
            output_path=out_path,
            expected_input_info=video_record
        )
    except QCValidationError as e:
        active_repo.update_video_status(v_id, "failed_qc")
        result.stage_failed = "QUALITY_CONTROL"
        result.error_message = str(e)
        logger.error(f"QC verification failed: {e}")
        return result

    # 10. Stage: PostgreSQL Knowledge & Evidence Persistence
    logger.info("=== STAGE 8: PostgreSQL Persistence & Audit Ledger ===")
    k_id = f"know_punchin_{uuid.uuid4().hex[:8]}"
    ev_id = f"evid_{uuid.uuid4().hex[:8]}"
    try:
        active_repo.update_video_status(v_id, "completed")
        
        # Knowledge candidate
        params_json = json.dumps({
            "target_token": selected_token.word,
            "scale": validated_proposal.scale,
            "duration_ms": validated_proposal.duration_ms,
            "pre_offset_ms": settings.TIMING_PRE_OFFSET_MS,
            "start_time": start_sec,
            "end_time": end_sec
        })
        active_repo.create_knowledge_candidate(
            knowledge_id=k_id,
            project_id=project_id,
            event_type="SPEECH_EMPHASIS",
            action_type="PUNCH_IN_ZOOM",
            parameters_json=params_json,
            confidence=0.5,
            sample_size=1
        )
        result.knowledge_id = k_id

        # Evidence record
        active_repo.record_evidence(
            evidence_id=ev_id,
            knowledge_id=k_id,
            video_id=v_id,
            outcome_note=f"Rendered punch-in on token '{selected_token.word}' with scale {validated_proposal.scale}x; QC verified.",
            metric_value=1.0 # Successful production execution
        )
        result.evidence_id = ev_id

        # Audit log
        active_repo.log_audit(
            audit_id=f"audit_run_{uuid.uuid4().hex[:8]}",
            action="EXECUTE_STAGE1_EDIT",
            target=v_id,
            detail=(
                f"Successfully produced punch-in edit for word '{selected_token.word}' "
                f"(scale={validated_proposal.scale}x, window=[{start_sec}s, {end_sec}s]). Output: {out_path.name}"
            )
        )
    except RepositoryError as e:
        result.stage_failed = "DATABASE_PERSISTENCE"
        result.error_message = str(e)
        logger.error(f"PostgreSQL persistence failed: {e}")
        return result

    result.success = True
    logger.info(f"=== PIPELINE COMPLETED SUCCESSFULLY: {out_path.name} ===")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline/run.py <path_to_video.mp4> [project_id]")
        sys.exit(1)

    video_input = sys.argv[1]
    proj_input = sys.argv[2] if len(sys.argv) > 2 else "proj_whop_shortform"
    res = run_stage1_pipeline(video_input, proj_input)
    print("\n--- Pipeline Run Summary ---")
    print(json.dumps(asdict(res), indent=2))
    sys.exit(0 if res.success else 1)
