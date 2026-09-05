#!/usr/bin/env python3
"""
Auto-Editor: Phase-1 Production CLI Entry Point (produce.py)

Usage:
    python produce.py --campaign "camp_prod_test" --input "path/to/clip.mp4" [options]
    python produce.py --campaign "campaign.json" --input "path/to/clips_dir" --count 3 [options]
    python produce.py --campaign "camp_prod_test" --input "path/to/clip.mp4" --dry-run
"""

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Reconfigure stdout for Windows console UTF-8 compatibility
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure whop-editor is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
WHOP_EDITOR_DIR = SCRIPT_DIR / "whop-editor" if (SCRIPT_DIR / "whop-editor").exists() else SCRIPT_DIR
if str(WHOP_EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(WHOP_EDITOR_DIR))

from config import settings
from db.connection import check_db_connection
from db.repository import DatabaseRepository
from ingest.video import inspect_video_media, register_input_video, IngestError
from campaigns.models import parse_campaign_intake, StructuredCampaignRequirements, Provenance
from campaigns.manager import CampaignManager
from workers.models import JobStatus
from workers.base import WorkerPool, AntigravityWorker
from browser.profile_registry import ProfileRegistry, ProfileAuthStatus, ProfileRuntimeStatus
from review.reviewer import BaseVideoReviewer, GeminiBrowserReviewer, MockVideoReviewer
from pipeline.production_engine import ProductionEngine, ProductionEngineResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("produce")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-Editor: In-House Autonomous Campaign Video Production CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run production with real Gemini Web QA:
  python produce.py --campaign "camp_prod_test" --input "whop-editor/data/input/justin_clouted_whop_12s.mp4" --mode production

  # Fast benchmark / CI run with mock QA:
  python produce.py --campaign "camp_prod_test" --input "whop-editor/data/input/justin_clouted_whop_12s.mp4" --mode benchmark

  # Dry-run pre-flight validation (checks intake, media, DB, profiles without rendering):
  python produce.py --campaign "camp_prod_test" --input "whop-editor/data/input/justin_clouted_whop_12s.mp4" --dry-run
        """
    )

    parser.add_argument(
        "--campaign",
        required=True,
        help="Campaign ID, name, path to campaign JSON/text intake file, or JSON string."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to source video file (.mp4, .mov, etc.) or directory containing video clips."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of source clips to process if input is a directory (default: 1)."
    )
    parser.add_argument(
        "--mode",
        choices=["production", "benchmark"],
        default="production",
        help="Execution mode: 'production' (Gemini QA browser review) or 'benchmark' (mock reviewer)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform pre-flight verification (DB, intake provenance, video media, profiles) without rendering."
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Preferred Chrome profile ID (e.g. flow_profile_1, flow_profile_2). If omitted, dynamic leasing chooses an available profile."
    )
    parser.add_argument(
        "--target-word",
        default=None,
        help="Specific word token for punch-in zoom emphasis."
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="Punch-in zoom scale factor (e.g. 1.15)."
    )
    parser.add_argument(
        "--duration-ms",
        type=int,
        default=None,
        help="Punch-in effect duration in milliseconds (e.g. 750)."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Custom output directory. Default: whop-editor/data/output/{project_id}/{campaign_id}/{job_id}/"
    )
    parser.add_argument(
        "--quality-gate",
        type=float,
        default=7.0,
        help="Minimum overall QA score (0-10) required to pass quality gate (default: 7.0)."
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum autonomous correction and re-render cycles (default: 3)."
    )
    parser.add_argument(
        "--instructions",
        default=None,
        help="Custom scene/editing instructions for QA review. Defaults to campaign context."
    )

    return parser.parse_args()


def load_campaign_intake(
    campaign_arg: str,
    repo: DatabaseRepository,
    mgr: CampaignManager
) -> Tuple[Any, StructuredCampaignRequirements]:
    """
    Resolves campaign argument into a database Campaign object and StructuredCampaignRequirements.
    Handles existing DB campaign IDs, JSON files, text files, or raw intake strings.
    """
    camp_path = Path(campaign_arg)
    raw_text = ""

    if camp_path.suffix.lower() in (".json", ".yaml", ".yml", ".txt"):
        if not camp_path.exists() or not camp_path.is_file():
            raise FileNotFoundError(f"Campaign intake file not found at: {camp_path.resolve()}")
        logger.info(f"Loading campaign intake from file: {camp_path}")
        raw_text = camp_path.read_text(encoding="utf-8")
    elif camp_path.exists() and camp_path.is_file():
        logger.info(f"Loading campaign intake from file: {camp_path}")
        raw_text = camp_path.read_text(encoding="utf-8")
    else:
        raw_text = campaign_arg.strip()

    # Check if this matches an existing campaign in the DB
    existing_camp = mgr.get_campaign(campaign_arg)
    if existing_camp:
        logger.info(f"Found existing campaign in PostgreSQL: [{existing_camp.name}] (id: {existing_camp.id})")
        # Load stored config into structured requirements
        reqs = parse_campaign_intake(existing_camp.config if existing_camp.config else {"name": existing_camp.name, "id": existing_camp.id})
        return existing_camp, reqs

    # Parse campaign intake from text or JSON with strict provenance
    reqs = parse_campaign_intake(raw_text)

    # Determine campaign ID and project ID
    c_id = reqs.campaign_id.value or (campaign_arg if not camp_path.is_file() else f"camp_{uuid.uuid4().hex[:8]}")
    c_name = reqs.campaign_name.value or (campaign_arg if not camp_path.is_file() else camp_path.stem)
    p_id = reqs.campaign_id.value or f"proj_{c_id}"

    # Register campaign in DB
    camp = mgr.create_campaign(
        project_id=p_id,
        name=c_name,
        campaign_id=c_id,
        config=reqs.to_dict()
    )
    logger.info(f"Registered campaign in PostgreSQL: [{camp.name}] (id: {camp.id}, project: {camp.project_id})")
    return camp, reqs


def discover_input_clips(input_arg: str, count: int) -> List[Tuple[Path, Dict[str, Any]]]:
    """
    Finds and validates video files from an input path (file or directory).
    Returns list of (Path, media_info_dict).
    """
    in_path = Path(input_arg).resolve()
    valid_exts = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    video_files: List[Path] = []

    if in_path.is_file():
        if in_path.suffix.lower() not in valid_exts:
            raise IngestError(f"Input file '{in_path.name}' does not have a supported video extension: {valid_exts}")
        video_files.append(in_path)
    elif in_path.is_dir():
        for item in sorted(in_path.iterdir()):
            if item.is_file() and item.suffix.lower() in valid_exts:
                video_files.append(item)
                if len(video_files) >= count:
                    break
    else:
        raise FileNotFoundError(f"Input path does not exist: {in_path}")

    if not video_files:
        raise IngestError(f"No valid video files found at: {in_path}")

    validated_clips: List[Tuple[Path, Dict[str, Any]]] = []
    for vf in video_files:
        info = inspect_video_media(vf)
        validated_clips.append((vf, info))
        logger.info(
            f"Source Clip Validated: {vf.name} "
            f"({info['width']}x{info['height']}, {info['duration']:.2f}s, {info['fps']:.1f}fps, audio={'yes' if info['has_audio'] else 'no'})"
        )

    return validated_clips


def display_provenance_table(reqs: StructuredCampaignRequirements) -> None:
    """Displays structured campaign intake fields with provenance."""
    print("\n" + "=" * 70)
    print("CAMPAIGN INTAKE SPECIFICATION & PROVENANCE REPORT")
    print("=" * 70)
    fields = [
        ("Campaign Name", reqs.campaign_name),
        ("Campaign ID", reqs.campaign_id),
        ("Platform", reqs.platform),
        ("Content Type", reqs.content_type),
        ("Aspect Ratio", reqs.aspect_ratio),
        ("Min Duration", reqs.duration_min),
        ("Max Duration", reqs.duration_max),
        ("Quality Gate", reqs.quality_gate),
        ("Output Count", reqs.output_count),
        ("Required Mentions", reqs.required_mentions),
        ("Required Hashtags", reqs.required_hashtags),
        ("Prohibited Content", reqs.prohibited_content),
        ("Submission Method", reqs.submission_method),
        ("Notes", reqs.notes),
    ]

    for label, field_obj in fields:
        prov = field_obj.provenance.value if hasattr(field_obj.provenance, "value") else str(field_obj.provenance)
        val = str(field_obj.value) if field_obj.value is not None else "[NOT SPECIFIED]"
        print(f"  {label:<22} | {val:<28} | [{prov}]")
    print("=" * 70 + "\n")


def display_profile_status(registry: ProfileRegistry) -> None:
    """Displays browser profile lease and authentication statuses."""
    profiles = registry.get_all_profiles()
    print("=" * 70)
    print("BROWSER PROFILE & LEASING STATUS")
    print("=" * 70)
    for p in profiles:
        auth = p.auth_status.value if hasattr(p.auth_status, "value") else str(p.auth_status)
        status = p.current_status.value if hasattr(p.current_status, "value") else str(p.current_status)
        lease_info = f"Leased to: {p.lease_owner}" if p.lease_owner else "Available"
        print(f"  {p.profile_id:<16} | Auth: {auth:<14} | Status: {status:<8} | {lease_info}")
    print("=" * 70 + "\n")


def print_human_handoff(
    result: ProductionEngineResult,
    campaign_name: str,
    campaign_id: str,
    source_clip_name: str,
    source_info: Dict[str, Any]
) -> None:
    """
    Renders human verification handoff summary with explicit instructions and playback command.
    """
    print("\n" + "#" * 74)
    print("#                    HUMAN VERIFICATION HANDOFF                          #")
    print("#" * 74)
    print(f"  Campaign        : {campaign_name} ({campaign_id})")
    print(f"  Source Clip     : {source_clip_name} ({source_info.get('duration', 0):.2f}s, {source_info.get('width')}x{source_info.get('height')})")
    print(f"  Job ID          : {result.job_id}")
    print(f"  Final Verdict   : {result.final_verdict}")
    print(f"  Best Version    : {result.best_version or 'N/A'}")
    print(f"  Best QA Score   : {result.best_score:.1f}/10.0")
    print(f"  Cycles Run      : {result.iterations_run}")
    print(f"  Regressions     : {result.regressions_count}")
    print(f"  QC Passed       : {'YES' if result.qc_passed else 'NO'}")
    print(f"  Output Video    : {result.final_output_path}")

    if result.final_output_path and Path(result.final_output_path).exists():
        p = Path(result.final_output_path)
        print("\n  [VERIFICATION COMMANDS]:")
        print(f'    ffplay -autoexit "{p}"')
        print(f'    vlc "{p}"')
    else:
        print("\n  [WARNING] Output video artifact not found or production failed.")
        if result.error_message:
            print(f"  Failure Details : {result.error_message}")

    print("#" * 74 + "\n")


def main() -> int:
    args = parse_arguments()

    print("\n" + "=" * 70)
    print("AUTO-EDITOR — IN-HOUSE AUTONOMOUS VIDEO PRODUCTION SYSTEM")
    print(f"Mode: {args.mode.upper()} | Dry-Run: {args.dry_run}")
    print("=" * 70)

    # 1. Pre-flight: Check PostgreSQL connection
    logger.info("Checking PostgreSQL connection...")
    if not check_db_connection():
        logger.error("PostgreSQL database is NOT accessible! Please ensure the PostgreSQL daemon is running on port 5432.")
        return 1
    logger.info("PostgreSQL connection confirmed healthy.")

    repo = DatabaseRepository()
    worker_pool = WorkerPool(max_concurrent_workers=2)
    worker_pool.register_worker(AntigravityWorker("worker_ag_01"))
    mgr = CampaignManager(repo=repo, worker_pool=worker_pool)
    registry = ProfileRegistry()

    # 2. Campaign Intake & Provenance
    try:
        camp, reqs = load_campaign_intake(args.campaign, repo, mgr)
    except Exception as e:
        logger.error(f"Failed to load/parse campaign intake: {e}")
        return 1

    display_provenance_table(reqs)

    # 3. Discover and inspect source clips
    try:
        clips = discover_input_clips(args.input, args.count)
    except Exception as e:
        logger.error(f"Input validation error: {e}")
        return 1

    # Register each source clip in PostgreSQL
    for clip_path, media_info in clips:
        try:
            reg = register_input_video(clip_path, project_id=camp.project_id, repo=repo)
            logger.info(f"Registered in DB: video_id={reg['id']} for {clip_path.name}")
        except Exception as e:
            logger.warning(f"Could not register video in DB ({e}); proceeding with local path.")

    # 4. Profile Registry Status
    display_profile_status(registry)

    # 5. Handle Dry-Run
    if args.dry_run:
        print("[PRE-FLIGHT VALIDATION PASSED]")
        print("  - Database: Connected")
        print(f"  - Campaign: {camp.name} ({camp.id})")
        print(f"  - Validated Clips: {len(clips)}")
        print(f"  - Quality Gate: {args.quality_gate}")
        print(f"  - Mode: {args.mode}")
        print("Dry run completed successfully. No video renders were performed.\n")
        return 0

    # 6. Initialize Reviewer based on Mode
    reviewer: BaseVideoReviewer
    if args.mode == "production":
        logger.info("Configuring GeminiBrowserReviewer with profile leasing...")
        reviewer = GeminiBrowserReviewer(
            profile_id=args.profile,
            headless=False,
            db_repo=repo
        )
    else:
        logger.info("Configuring MockVideoReviewer (Benchmark Mode)...")
        reviewer = MockVideoReviewer(should_pass=True)

    # 7. Initialize Production Engine
    engine = ProductionEngine(
        campaign_manager=mgr,
        reviewer=reviewer,
        quality_gate_score=args.quality_gate,
        max_auto_iterations=args.max_iterations
    )

    instructions = args.instructions or f"Produce high-retention short-form video compliant with campaign {camp.name}."
    overall_success = True

    # 8. Execute Production for each clip
    for idx, (clip_path, media_info) in enumerate(clips, start=1):
        logger.info(f"\n>>> Starting Production Job [{idx}/{len(clips)}]: {clip_path.name}")
        out_filename = f"prod_{camp.id}_{clip_path.stem}.mp4"

        try:
            res = engine.produce_campaign_video(
                campaign_id=camp.id,
                source_video_path=clip_path,
                scene_instructions=instructions,
                output_filename=out_filename,
                target_word=args.target_word,
                scale=args.scale,
                duration_ms=args.duration_ms,
                output_dir=args.output_dir
            )

            print_human_handoff(
                result=res,
                campaign_name=camp.name,
                campaign_id=camp.id,
                source_clip_name=clip_path.name,
                source_info=media_info
            )

            if not res.success:
                overall_success = False

        except Exception as e:
            logger.error(f"Production failed unexpectedly for {clip_path.name}: {e}", exc_info=True)
            overall_success = False

    return 0 if overall_success else 2


if __name__ == "__main__":
    sys.exit(main())
