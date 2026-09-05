"""
Master Pipeline Orchestrator for AI Auto-Video Generator
Coordinates the full workflow from Idea -> Storyboard -> Prompts -> Voiceover -> Subtitles -> Compositor -> Final 9:16 Video.
"""

import sys
import argparse
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config
from pipeline.stage1_storyboard import create_earth_stops_storyboard, save_storyboard
from pipeline.stage2_prompts import generate_prompts_file
from pipeline.flow_browser_bot import generate_all_flow_clips
from pipeline.stage3_voiceover import generate_voiceover
from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import compose_video
from pipeline.stage6_qc import inspect_video
from pipeline.ai_video_qc import review_all_scene_clips

def run_project_pipeline(project_name: str = "earth_stops_rotating", use_dry_run: bool = True, skip_render: bool = False, use_flow_browser: bool = False):
    proj_dir = config.PROJECTS_DIR / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)

    storyboard_file = proj_dir / "storyboard.json"
    prompts_md_file = proj_dir / "google_flow_prompts.md"
    prompts_json_file = proj_dir / "google_flow_prompts.json"
    narration_audio = proj_dir / "narration.mp3"
    narration_words = proj_dir / "narration_words.json"
    captions_ass = proj_dir / "captions.ass"
    clips_dir = proj_dir / "clips"
    output_video = proj_dir / "output" / "final_short.mp4"

    print("="*60)
    print(f"🚀 RUNNING AI VIDEO PIPELINE: {project_name}")
    print(f"Mode: {'DRY RUN (Zero Credits Used)' if use_dry_run else 'PRODUCTION (ElevenLabs Live)'}")
    print(f"Google Flow Browser Worker: {'ENABLED' if use_flow_browser else 'STANDBY'}")
    print("="*60)

    # Stage 1: Storyboard & Script
    print("\n▶ [STAGE 1] Building Storyboard & Script...")
    if not storyboard_file.exists():
        sb_data = create_earth_stops_storyboard()
        save_storyboard(sb_data, storyboard_file)
    else:
        print(f"Existing storyboard loaded from {storyboard_file}")

    # Stage 2: Google Flow / Veo Prompts
    print("\n▶ [STAGE 2] Generating Cinematic Flow / Veo Prompts...")
    generate_prompts_file(storyboard_file, prompts_md_file)

    # Stage 2.5: Persistent Browser Google Flow Clip Generator
    if use_flow_browser:
        print("\n▶ [STAGE 2.5] Running Persistent Browser Google Flow Worker...")
        generate_all_flow_clips(
            prompts_path=prompts_json_file,
            clips_dir=clips_dir,
            browser_profile_dir=config.BROWSER_PROFILE_DIR
        )

    # Optional / Automatic AI Clip Inspection
    if not use_dry_run or use_flow_browser:
        print("\n▶ [AI VIDEO QC] Inspecting generated clips...")
        qc_result = review_all_scene_clips(proj_dir)
        if not qc_result["all_clips_passed"]:
            print("⚠️ Some clips failed QC or are missing. Please review recommendations above before final render.")

    # Stage 3: Voiceover & Alignment
    print("\n▶ [STAGE 3] Generating Voiceover & Word Timestamps...")
    generate_voiceover(storyboard_file, narration_audio, narration_words, use_dry_run=use_dry_run)

    # Stage 4: Subtitles & Animated Captions
    print("\n▶ [STAGE 4] Generating Dynamic Animated Captions (ASS)...")
    generate_ass_subtitles(narration_words, captions_ass)

    # Stage 5: Compositor & Render
    if not skip_render:
        print("\n▶ [STAGE 5] Assembling Video, Mixing Audio & Ducking, Burning Captions...")
        compose_video(
            storyboard_path=storyboard_file,
            narration_audio_path=narration_audio,
            captions_ass_path=captions_ass,
            clips_dir=clips_dir,
            output_video_path=output_video,
            allow_synthetic_clips=not use_flow_browser
        )

        # Stage 6: Quality Control
        print("\n▶ [STAGE 6] Performing Automated Quality Control Check...")
        inspect_video(output_video)
    else:
        print("\n[INFO] Skipped render stage as requested.")

    print("\n" + "="*60)
    print("🎉 PIPELINE RUN COMPLETED SUCCESSFULLY!")
    print(f"📁 Project Folder: {proj_dir}")
    if not skip_render and output_video.exists():
        print(f"🎥 Rendered Video: {output_video}")
    print(f"📝 Google Flow Prompts: {prompts_md_file}")
    print("="*60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Auto-Video Generator Pipeline")
    parser.add_argument("--project", default="earth_stops_rotating", help="Project name")
    parser.add_argument("--live", action="store_true", help="Use live ElevenLabs API (consumes credits)")
    parser.add_argument("--flow", action="store_true", help="Run persistent browser Google Flow clip generator")
    parser.add_argument("--skip-render", action="store_true", help="Skip video compositing")
    args = parser.parse_args()

    run_project_pipeline(
        project_name=args.project,
        use_dry_run=not args.live,
        skip_render=args.skip_render,
        use_flow_browser=args.flow
    )

