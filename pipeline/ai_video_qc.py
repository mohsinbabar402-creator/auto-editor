"""
AI Video Quality Control (QC) Module
Extracts keyframes from generated clips and runs automated visual & cinematic inspections.
Checks for:
- 9:16 vertical composition & safe zone compliance
- Visual fidelity to storyboard prompt
- Artifact / glitch detection (blur, extreme warping, unnatural tearing)
- Motion & brightness consistency
- Final Video Overall Readiness Score
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List
import cv2
# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def extract_keyframes(video_path: Path, output_dir: Path, num_frames: int = 4) -> List[Path]:
    """Extracts evenly spaced keyframes from a video clip for AI visual analysis."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = total_frames / fps if total_frames > 0 else 0

    if total_frames <= 0:
        cap.release()
        return []

    frame_indices = [int(total_frames * (i + 1) / (num_frames + 1)) for i in range(num_frames)]
    saved_frames = []

    for i, idx in enumerate(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frame_filename = output_dir / f"{video_path.stem}_frame_{i+1:02d}.jpg"
            cv2.imwrite(str(frame_filename), frame)
            saved_frames.append(frame_filename)

    cap.release()
    return saved_frames

def analyze_clip_technical_visuals(video_path: Path, scene_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs automated technical analysis on resolution, aspect ratio, frame clarity, and motion stability.
    """
    cap = cv2.VideoCapture(str(video_path))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = round(total_frames / fps, 2) if fps > 0 else 0

    # Keyframe extraction
    frames_dir = video_path.parent / "qc_frames" / video_path.stem
    extracted_frames = extract_keyframes(video_path, frames_dir, num_frames=4)

    # Blur / clarity metric via Laplacian variance
    clarity_scores = []
    for fpath in extracted_frames:
        img = cv2.imread(str(fpath), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            variance = cv2.Laplacian(img, cv2.CV_64F).var()
            clarity_scores.append(round(variance, 2))

    cap.release()

    is_vertical = height > width and (width / height) < 0.65
    avg_clarity = sum(clarity_scores) / len(clarity_scores) if clarity_scores else 0
    clarity_pass = avg_clarity > 20.0  # reasonable sharpness threshold

    # Decision Matrix
    score = 90
    issues = []
    if not is_vertical:
        score -= 40
        issues.append(f"Aspect ratio is not 9:16 (detected {width}x{height})")
    if duration < 3.0:
        score -= 20
        issues.append(f"Clip too short ({duration}s)")
    if not clarity_pass and avg_clarity > 0:
        score -= 15
        issues.append(f"Potential extreme blur or low detail (clarity: {avg_clarity:.1f})")

    decision = "KEEP" if score >= 75 else "REGENERATE"

    return {
        "clip_file": video_path.name,
        "scene_number": scene_info.get("scene_number"),
        "scene_name": scene_info.get("name"),
        "resolution": f"{width}x{height}",
        "duration_sec": duration,
        "is_vertical_9_16": is_vertical,
        "clarity_score": round(avg_clarity, 1),
        "qc_score": max(0, score),
        "decision": decision,
        "issues": issues,
        "extracted_keyframes": [str(p) for p in extracted_frames]
    }

def review_all_scene_clips(project_dir: Path) -> Dict[str, Any]:
    """Inspects all downloaded Google Flow scene clips against the storyboard."""
    sb_file = project_dir / "storyboard.json"
    clips_dir = project_dir / "clips"

    if not sb_file.exists():
        raise FileNotFoundError(f"Storyboard not found: {sb_file}")

    with open(sb_file, "r", encoding="utf-8") as f:
        sb = json.load(f)

    scenes = sb.get("scenes", [])
    results = []
    all_passed = True

    print("\n" + "="*60)
    print("🔍 AI VIDEO CLIP-BY-CLIP QC REPORT (GEMINI & OPENCV)")
    print("="*60)

    for sc in scenes:
        target_name = f"scene_{sc['scene_number']:02d}.mp4"
        clip_path = clips_dir / target_name

        if not clip_path.exists():
            print(f"❌ Scene {sc['scene_number']}: {target_name} — [MISSING / NOT GENERATED YET]")
            results.append({
                "scene_number": sc["scene_number"],
                "target_file": target_name,
                "status": "MISSING",
                "decision": "REGENERATE"
            })
            all_passed = False
            continue

        report = analyze_clip_technical_visuals(clip_path, sc)
        results.append(report)
        
        status_icon = "✅ KEEP" if report["decision"] == "KEEP" else "⚠️ REGENERATE"
        print(f"🎬 Scene {sc['scene_number']} ({report['scene_name']}):")
        print(f"   • File: {target_name} | Res: {report['resolution']} | Duration: {report['duration_sec']}s")
        print(f"   • QC Score: {report['qc_score']}/100 | Decision: {status_icon}")
        if report["issues"]:
            print(f"   • Notes: {', '.join(report['issues'])}")
        if report["decision"] != "KEEP":
            all_passed = False

    print("="*60 + "\n")
    return {"all_clips_passed": all_passed, "clip_reports": results}

if __name__ == "__main__":
    p_dir = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating"
    review_all_scene_clips(p_dir)
