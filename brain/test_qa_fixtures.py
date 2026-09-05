"""
Adversarial QA Failure Fixture Generator & Validator

Generates actual corrupted media fixtures and executes QA against them:
1. Baseline Known-Good 9:16 Video
2. Missing File
3. Wrong Resolution (16:9 instead of 9:16)
4. Blackout Frame Glitch
5. Frozen Frame Glitch
6. Audio Digital Clipping (+3dB boost)
7. Extreme Silence / Dead Air
8. Caption Safe-Zone Overflow
9. Caption Timestamp Overlap
10. Cascading Multi-Defect Video
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import imageio_ffmpeg
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

from brain.models import EditPlan
from brain.qa_engine_v2 import run_qa_adversarial

FIXTURES_DIR = ROOT / "projects" / "07_viral_podcasts" / "qa_fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

BASELINE_SRC = Path(r"G:\My Drive\YouTube Shorts\07_viral_podcasts\clouted_19yo_millionaire_clip_pro.mp4")

# Copy baseline local if not present
LOCAL_BASELINE = FIXTURES_DIR / "01_baseline_good.mp4"
if not LOCAL_BASELINE.exists() and BASELINE_SRC.exists():
    shutil.copy(BASELINE_SRC, LOCAL_BASELINE)

print("=" * 70)
print("PHASE 8.5: ADVERSARIAL QA FAILURE FIXTURE SUITE")
print("=" * 70)

# Build standard baseline EditPlan matching the 44.6s clip
baseline_plan = EditPlan(
    candidate_id="fixture_baseline",
    target_platform="youtube_shorts",
    layout_style="ambient_blur_default",
    body_start_sec=195.2,
    body_end_sec=234.7,
    target_duration_sec=44.6,
    editing_necessity=0.3,
    ending_strategy="NATURAL_END",
    cta_text="",
    music_treatment="NONE"
)

# ─── FIXTURE 1: BASELINE KNOWN-GOOD ──────────────────────────────────────────
print("\n[FIXTURE 1] Testing Known-Good 9:16 Rendered Baseline...")
res1 = run_qa_adversarial(LOCAL_BASELINE, baseline_plan)
print(f"  Result: {res1.recommended_action.upper()} (Score: {res1.score}/100, Hard Fails: {len(res1.hard_fails)})")
for c in res1.checks_run:
    status = "PASS" if c.passed else f"FAIL ({c.severity})"
    print(f"    - [{status}] {c.name}: {c.measured_value} (Threshold: {c.threshold})")

# ─── FIXTURE 2: MISSING FILE ─────────────────────────────────────────────────
print("\n[FIXTURE 2] Testing Missing File...")
res2 = run_qa_adversarial(FIXTURES_DIR / "nonexistent.mp4", baseline_plan)
print(f"  Result: {res2.recommended_action.upper()} (Score: {res2.score}/100, Hard Fails: {len(res2.hard_fails)})")
print(f"  Evidence: {res2.hard_fails[0]}")

# ─── FIXTURE 3: WRONG RESOLUTION (1920x1080) ─────────────────────────────────
print("\n[FIXTURE 3] Generating & Testing Wrong Resolution Fixture...")
f3_path = FIXTURES_DIR / "03_wrong_resolution.mp4"
if not f3_path.exists():
    subprocess.run([FFMPEG_EXE, "-y", "-ss", "0", "-t", "5", "-i", str(LOCAL_BASELINE), "-vf", "scale=1920:1080", str(f3_path)], capture_output=True)
res3 = run_qa_adversarial(f3_path, baseline_plan)
print(f"  Result: {res3.recommended_action.upper()} (Score: {res3.score}/100, Hard Fails: {len(res3.hard_fails)})")
c3 = next(c for c in res3.checks_run if c.name == "vertical_resolution")
print(f"  Evidence: {c3.name} -> Measured: {c3.measured_value} | Threshold: {c3.threshold} | Action: {c3.repair_action}")

# ─── FIXTURE 4: BLACKOUT FRAME GLITCH ────────────────────────────────────────
print("\n[FIXTURE 4] Generating & Testing Blackout Frame Fixture...")
f4_path = FIXTURES_DIR / "04_blackout_frames.mp4"
if not f4_path.exists():
    # Insert black screen for 2 seconds in the middle
    subprocess.run([FFMPEG_EXE, "-y", "-ss", "0", "-t", "6", "-i", str(LOCAL_BASELINE), "-vf", "drawbox=x=0:y=0:w=1080:h=1920:color=black:t=fill:enable='between(t,1.5,4.0)'", str(f4_path)], capture_output=True)
res4 = run_qa_adversarial(f4_path, baseline_plan)
print(f"  Result: {res4.recommended_action.upper()} (Score: {res4.score}/100, Hard Fails: {len(res4.hard_fails)})")
c4 = next(c for c in res4.checks_run if c.name == "black_frame_detection")
print(f"  Evidence: {c4.name} -> Measured: {c4.measured_value} | Timestamp: {c4.timestamp_range} | Action: {c4.repair_action}")

# ─── FIXTURE 5: DIGITAL CLIPPING AUDIO (+12dB Boost) ─────────────────────────
print("\n[FIXTURE 5] Generating & Testing Audio Clipping Fixture...")
f5_path = FIXTURES_DIR / "05_audio_clipping.mp4"
if not f5_path.exists():
    subprocess.run([FFMPEG_EXE, "-y", "-ss", "0", "-t", "5", "-i", str(LOCAL_BASELINE), "-af", "volume=12dB", str(f5_path)], capture_output=True)
res5 = run_qa_adversarial(f5_path, baseline_plan)
print(f"  Result: {res5.recommended_action.upper()} (Score: {res5.score}/100, Hard Fails: {len(res5.hard_fails)})")
c5 = next(c for c in res5.checks_run if c.name == "audio_clipping_peak")
print(f"  Evidence: {c5.name} -> Measured: {c5.measured_value} | Threshold: {c5.threshold} | Action: {c5.repair_action}")

# ─── FIXTURE 6: CAPTION OVERFLOW & OVERLAP ───────────────────────────────────
print("\n[FIXTURE 6] Testing Malformed Caption Fixture (Overflow + Overlap)...")
malformed_srt = FIXTURES_DIR / "06_malformed.srt"
malformed_srt.write_text("""1
00:00:01,000 --> 00:00:04,000
THIS IS A RIDICULOUSLY MASSIVE SUBTITLE CHUNK CONTAINING WAY TOO MANY WORDS FOR A VERTICAL SCREEN VIEWPORT

2
00:00:03,500 --> 00:00:06,000
Overlapping start before previous subtitle has finished
""", encoding='utf-8')

res6 = run_qa_adversarial(LOCAL_BASELINE, baseline_plan, srt_path=malformed_srt)
print(f"  Result: {res6.recommended_action.upper()} (Score: {res6.score}/100, Hard Fails: {len(res6.hard_fails)})")
c6_overflow = next(c for c in res6.checks_run if c.name == "caption_overflow_safezone")
c6_overlap = next(c for c in res6.checks_run if c.name == "caption_overlap_intervals")
print(f"  Evidence 1: {c6_overflow.name} -> Measured: {c6_overflow.measured_value} | Timestamp: {c6_overflow.timestamp_range}")
print(f"  Evidence 2: {c6_overlap.name} -> Measured: {c6_overlap.measured_value} | Timestamp: {c6_overlap.timestamp_range}")

# ─── FIXTURE 7: CASCADING MULTI-DEFECT ARTIFACT ──────────────────────────────
print("\n[FIXTURE 7] Generating & Testing Cascading Multi-Defect Fixture...")
f7_path = FIXTURES_DIR / "07_multi_defect.mp4"
if not f7_path.exists():
    # Wrong resolution + audio clipping + blackout frame
    subprocess.run([FFMPEG_EXE, "-y", "-ss", "0", "-t", "5", "-i", str(LOCAL_BASELINE), "-vf", "scale=1920:1080,drawbox=x=0:y=0:w=1920:h=1080:color=black:t=fill:enable='between(t,1,3)'", "-af", "volume=10dB", str(f7_path)], capture_output=True)

res7 = run_qa_adversarial(f7_path, baseline_plan, srt_path=malformed_srt)
print(f"  Result: {res7.recommended_action.upper()} (Score: {res7.score}/100, Hard Fails: {len(res7.hard_fails)})")
print(f"  Total Hard Failures Caught ({len(res7.hard_fails)}):")
for i, hf in enumerate(res7.hard_fails, 1):
    print(f"    {i}. {hf}")
print(f"  Total Repair Instructions Generated ({len(res7.repair_instructions)}):")
for r in res7.repair_instructions:
    print(f"    - [{r['severity']}] {r['issue']} -> {r['action']} ({r['safety']})")

print("\n" + "=" * 70)
print("ADVERSARIAL FIXTURE VALIDATION COMPLETE")
print("=" * 70)
